"""
API для управления доменным именем и конфигурацией Nginx
"""
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from models import get_db
from models.database import User
from app.api.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/domain", tags=["domain"])

# Путь к файлу настроек домена
DOMAIN_SETTINGS_FILE = Path("/app/domain_settings.json")
# Путь к конфигурации Nginx в проекте (для обновления)
# В Docker контейнере backend файл монтируется как volume: /app/nginx/conf.d/app.conf
NGINX_CONF_DOCKER = Path("/app/nginx/conf.d/app.conf")
# Альтернативные пути для разных окружений
NGINX_CONF_PROJECT_PATH = Path("/app/../nginx/conf.d/app.conf")
# Абсолютный путь от backend директории (для локальной разработки)
NGINX_CONF_ABSOLUTE = Path(__file__).parent.parent.parent.parent / "nginx" / "conf.d" / "app.conf"

# Путь к директории сертификатов
# В Docker контейнере backend certbot/conf монтируется как volume: /app/certbot/conf
CERTBOT_CONF_DOCKER = Path("/app/certbot/conf")
CERTBOT_CONF_ABSOLUTE = Path(__file__).parent.parent.parent.parent / "certbot" / "conf"


class DomainSettingsRequest(BaseModel):
    domain: str


class DomainSettingsResponse(BaseModel):
    domain: str
    nginx_reloaded: bool = False
    message: Optional[str] = None


class DomainTestRequest(BaseModel):
    domain: str


class DomainTestResponse(BaseModel):
    accessible: bool
    message: str


def _load_domain_settings() -> dict:
    """Загружает настройки домена из файла"""
    default_domain = "app.domain"
    
    if DOMAIN_SETTINGS_FILE.exists():
        try:
            import json
            with open(DOMAIN_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                return settings
        except Exception as e:
            logger.warning(f"Ошибка загрузки настроек домена: {e}")
    
    return {"domain": default_domain}


def _save_domain_settings(domain: str):
    """Сохраняет настройки домена в файл"""
    try:
        import json
        settings = {"domain": domain}
        
        # Создаем директорию, если не существует
        DOMAIN_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(DOMAIN_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Настройки домена сохранены: {domain}")
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек домена: {e}")
        raise


def _validate_domain(domain: str) -> bool:
    """Валидация доменного имени"""
    if not domain or not domain.strip():
        return False
    
    domain = domain.strip()
    
    # Разрешаем localhost
    if domain == "localhost":
        return True
    
    # Валидация доменного имени
    domain_regex = r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    return bool(re.match(domain_regex, domain))


def _update_nginx_config(domain: str) -> bool:
    """Обновляет конфигурацию Nginx с новым доменом"""
    try:
        # Пробуем обновить конфигурацию в проекте
        # Приоритет: Docker volume, затем альтернативные пути
        nginx_conf_paths = [
            NGINX_CONF_DOCKER,  # В Docker контейнере (монтируется как volume)
            NGINX_CONF_ABSOLUTE,  # Абсолютный путь от backend (локальная разработка)
            NGINX_CONF_PROJECT_PATH,  # Относительный путь
            Path("/app/../nginx/conf.d/app.conf"),  # Альтернативный относительный путь
        ]
        
        nginx_conf = None
        for path in nginx_conf_paths:
            try:
                if path.exists():
                    nginx_conf = path
                    break
            except Exception:
                continue
        
        if not nginx_conf:
            logger.warning(f"Файл конфигурации Nginx не найден. Проверенные пути: {nginx_conf_paths}")
            return False
        
        # Читаем текущую конфигурацию
        with open(nginx_conf, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Обновляем server_name в HTTP блоке
        content = re.sub(
            r'server_name\s+[^;]+;',
            f'server_name {domain} localhost;',
            content,
            count=1
        )
        
        # Обновляем server_name в HTTPS блоке (если есть)
        content = re.sub(
            r'server_name\s+[^;]+;',
            f'server_name {domain} localhost;',
            content,
            count=1
        )
        
        # Сохраняем обновленную конфигурацию
        with open(nginx_conf, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"Конфигурация Nginx обновлена для домена: {domain}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка обновления конфигурации Nginx: {e}")
        return False


def _create_ssl_certificate(domain: str) -> bool:
    """Создает самоподписанный SSL сертификат для домена"""
    try:
        # Определяем путь к директории сертификатов
        # Приоритет: Docker volume, затем альтернативные пути
        certbot_paths = [
            CERTBOT_CONF_DOCKER,  # В Docker контейнере (монтируется как volume)
            CERTBOT_CONF_ABSOLUTE,  # Абсолютный путь от backend (локальная разработка)
            Path("/app/../certbot/conf"),  # Альтернативный относительный путь
        ]
        
        certbot_conf = None
        for path in certbot_paths:
            try:
                if path.exists() or path.parent.exists():
                    certbot_conf = path
                    break
            except Exception:
                continue
        
        if not certbot_conf:
            logger.warning(f"Директория certbot/conf не найдена. Проверенные пути: {certbot_paths}")
            return False
        
        # Создаем директорию для сертификатов домена
        cert_dir = certbot_conf / "live" / domain
        cert_dir.mkdir(parents=True, exist_ok=True)
        
        cert_file = cert_dir / "fullchain.pem"
        key_file = cert_dir / "privkey.pem"
        
        # Проверяем, существует ли уже сертификат для этого домена
        if cert_file.exists() and key_file.exists():
            logger.info(f"Сертификат для домена '{domain}' уже существует, пропускаем создание")
            return True
        
        # Пробуем создать сертификат через openssl в системе
        # В контейнере backend может не быть openssl, поэтому пробуем через subprocess
        try:
            # Пробуем найти openssl
            openssl_cmd = None
            for cmd in ["openssl", "/usr/bin/openssl", "/bin/openssl"]:
                try:
                    result = subprocess.run(
                        [cmd, "version"],
                        capture_output=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        openssl_cmd = cmd
                        break
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            
            if not openssl_cmd:
                logger.warning("OpenSSL не найден в системе. Сертификат не будет создан автоматически.")
                logger.info(f"Создайте сертификат вручную для домена '{domain}' в {cert_dir}")
                return False
            
            # Создаем самоподписанный сертификат
            cmd = [
                openssl_cmd, "req", "-x509", "-nodes", "-newkey", "rsa:4096",
                "-days", "365",
                "-keyout", str(key_file),
                "-out", str(cert_file),
                "-subj", f"/CN={domain}/O=Motorchik/C=RU",
                "-addext", f"subjectAltName=DNS:{domain},DNS:*.{domain},IP:127.0.0.1"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info(f"✅ Самоподписанный SSL сертификат создан для домена '{domain}'")
                logger.info(f"   Сертификат: {cert_file}")
                logger.info(f"   Ключ: {key_file}")
                return True
            else:
                logger.error(f"Ошибка создания сертификата: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Таймаут при создании сертификата")
            return False
        except Exception as e:
            logger.error(f"Ошибка при создании сертификата: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка создания SSL сертификата для домена '{domain}': {e}")
        return False


def _reload_nginx() -> bool:
    """Перезагружает Nginx через HTTP запрос к Nginx контейнеру"""
    try:
        import httpx
        
        # Пробуем перезагрузить Nginx через HTTP запрос к контейнеру
        # Nginx контейнер может иметь endpoint для перезагрузки или мы можем использовать сигнал
        # Альтернатива: использовать docker socket, но он может быть недоступен
        
        # Пробуем через HTTP запрос к Nginx (если есть специальный endpoint)
        # Или используем прямой доступ к контейнеру через сеть Docker
        try:
            # Пробуем подключиться к Nginx контейнеру напрямую
            # В Docker сети контейнеры доступны по имени сервиса
            with httpx.Client(timeout=5.0) as client:
                # Проверяем доступность Nginx
                response = client.get("http://motorchik-nginx:80/", follow_redirects=False)
                if response.status_code in [200, 301, 302]:
                    logger.info("Nginx контейнер доступен")
        except Exception as e:
            logger.debug(f"Не удалось проверить доступность Nginx: {e}")
        
        # В контейнере backend нет доступа к docker CLI
        # Перезагрузка Nginx должна выполняться вручную или через внешний скрипт
        # Возвращаем True, так как конфигурация уже обновлена
        logger.info("Конфигурация Nginx обновлена. Перезагрузите Nginx вручную: docker-compose exec nginx nginx -s reload")
        return False  # Возвращаем False, чтобы показать, что нужна ручная перезагрузка
        
    except Exception as e:
        logger.error(f"Ошибка перезагрузки Nginx: {e}")
        return False


@router.get("/settings", response_model=DomainSettingsResponse)
async def get_domain_settings(_: User = Depends(require_admin)):
    """Получить текущие настройки домена"""
    try:
        settings = _load_domain_settings()
        return DomainSettingsResponse(
            domain=settings.get("domain", "app.domain"),
            nginx_reloaded=False
        )
    except Exception as e:
        logger.error(f"Ошибка получения настроек домена: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка получения настроек: {str(e)}")


@router.post("/settings", response_model=DomainSettingsResponse)
async def save_domain_settings(
    request: DomainSettingsRequest,
    _: User = Depends(require_admin)
):
    """Сохранить настройки домена и обновить конфигурацию Nginx"""
    try:
        domain = request.domain.strip()
        
        # Валидация домена
        if not _validate_domain(domain):
            raise HTTPException(
                status_code=400,
                detail="Некорректный формат доменного имени"
            )
        
        # Сохраняем настройки
        _save_domain_settings(domain)
        
        # Создаем SSL сертификат для нового домена (если еще не существует)
        cert_created = _create_ssl_certificate(domain)
        
        # Обновляем конфигурацию Nginx
        nginx_updated = _update_nginx_config(domain)
        
        # Перезагружаем Nginx
        nginx_reloaded = False
        if nginx_updated:
            nginx_reloaded = _reload_nginx()
        
        message = f"Домен '{domain}' сохранен"
        if cert_created:
            message += ", SSL сертификат создан"
        elif not cert_created:
            # Проверяем, существует ли сертификат
            cert_paths = [
                CERTBOT_CONF_DOCKER / "live" / domain / "fullchain.pem",
                CERTBOT_CONF_ABSOLUTE / "live" / domain / "fullchain.pem",
                Path("/app/../certbot/conf/live") / domain / "fullchain.pem",
            ]
            cert_exists = any(p.exists() for p in cert_paths if p)
            if not cert_exists:
                message += ". ⚠️ SSL сертификат не создан (создайте вручную или установите openssl)"
        if nginx_updated:
            message += ", конфигурация Nginx обновлена"
            if not nginx_reloaded:
                message += ". Для применения изменений выполните: docker-compose exec nginx nginx -s reload"
        if nginx_reloaded:
            message += ". Nginx перезагружен автоматически"
        
        return DomainSettingsResponse(
            domain=domain,
            nginx_reloaded=nginx_reloaded,
            message=message
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек домена: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {str(e)}")


@router.post("/test", response_model=DomainTestResponse)
async def test_domain_connection(
    request: DomainTestRequest,
    _: User = Depends(require_admin)
):
    """Проверить доступность домена"""
    try:
        domain = request.domain.strip()
        
        if not _validate_domain(domain):
            return DomainTestResponse(
                accessible=False,
                message="Некорректный формат доменного имени"
            )
        
        # Тестовые домены, которые не требуют DNS проверки
        test_domains = ['localhost', 'app.domain', 'test.domain', 'local.domain']
        is_test_domain = domain.lower() in test_domains or domain.endswith('.local')
        
        if is_test_domain:
            return DomainTestResponse(
                accessible=True,
                message=f"Домен '{domain}' - тестовый домен. Для использования настройте DNS запись или используйте /etc/hosts для локального тестирования."
            )
        
        # Пробуем выполнить ping или проверить DNS
        import socket
        try:
            # Проверяем DNS резолюцию
            ip_address = socket.gethostbyname(domain)
            return DomainTestResponse(
                accessible=True,
                message=f"Домен '{domain}' разрешается в DNS (IP: {ip_address})"
            )
        except socket.gaierror:
            return DomainTestResponse(
                accessible=False,
                message=f"Домен '{domain}' не разрешается в DNS. Убедитесь, что DNS запись настроена. Для локального тестирования добавьте запись в /etc/hosts (Windows: C:\\Windows\\System32\\drivers\\etc\\hosts)"
            )
        except Exception as e:
            return DomainTestResponse(
                accessible=False,
                message=f"Ошибка проверки: {str(e)}"
            )
            
    except Exception as e:
        logger.error(f"Ошибка проверки домена: {e}")
        return DomainTestResponse(
            accessible=False,
            message=f"Ошибка проверки: {str(e)}"
        )


@router.post("/reload-nginx", response_model=dict)
async def reload_nginx(_: User = Depends(require_admin)):
    """Перезагрузить Nginx"""
    try:
        nginx_reloaded = _reload_nginx()
        
        if nginx_reloaded:
            return {
                "success": True,
                "message": "Nginx успешно перезагружен"
            }
        else:
            return {
                "success": False,
                "message": "Не удалось перезагрузить Nginx. Проверьте логи."
            }
            
    except Exception as e:
        logger.error(f"Ошибка перезагрузки Nginx: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка перезагрузки: {str(e)}")

