"""
Утилиты для работы с Ollama
Включает проверку доступности и выбор правильного адреса
"""
import httpx
from typing import Optional, List
from app.core.config import settings


async def check_ollama_availability(url: str, timeout: float = 2.0) -> bool:
    """
    Проверяет доступность Ollama по указанному URL
    
    Args:
        url: URL для проверки (например, "http://localhost:11434")
        timeout: Таймаут в секундах
        
    Returns:
        True если Ollama доступен, False иначе
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{url}/api/version",
                timeout=timeout
            )
            return response.status_code == 200
    except Exception:
        return False


async def find_working_ollama_url(timeout: float = 2.0) -> Optional[str]:
    """
    Находит рабочий URL для Ollama, проверяя несколько адресов
    
    Args:
        timeout: Таймаут для каждой проверки в секундах
        
    Returns:
        Рабочий URL или None если ни один не доступен
    """
    # Получаем настройки из config
    ollama_host = getattr(settings, 'ollama_host', 'host.docker.internal')
    ollama_port = getattr(settings, 'ollama_port', 11434)
    
    # Нормализуем host (убираем http:// если есть)
    if ollama_host.startswith('http://'):
        ollama_host = ollama_host.replace('http://', '')
    if ollama_host.startswith('https://'):
        ollama_host = ollama_host.replace('https://', '')
    
    # Список адресов для проверки (в порядке приоритета)
    ollama_urls: List[str] = [
        "http://localhost:11434",  # Приоритет 1: localhost
        f"http://{ollama_host}:{ollama_port}",  # Приоритет 2: из настроек
        "http://host.docker.internal:11434",  # Приоритет 3: Docker host
        "http://127.0.0.1:11434",  # Приоритет 4: 127.0.0.1
    ]
    
    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique_urls = []
    for url in ollama_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    
    # Проверяем каждый адрес
    for url in unique_urls:
        print(f"🔍 Проверка доступности Ollama: {url}...")
        if await check_ollama_availability(url, timeout):
            print(f"✅ Ollama доступен по адресу: {url}")
            return url
        else:
            print(f"⚠️ Ollama недоступен по адресу: {url}")
    
    print("❌ Ollama недоступен ни по одному из адресов")
    return None


def normalize_ollama_url(url: str) -> str:
    """
    Нормализует URL Ollama (убирает лишние http://, добавляет если нужно)
    
    Args:
        url: URL для нормализации
        
    Returns:
        Нормализованный URL
    """
    url = url.strip()
    
    # Если URL уже содержит протокол, возвращаем как есть
    if url.startswith('http://') or url.startswith('https://'):
        return url
    
    # Если URL содержит только host:port, добавляем http://
    if '://' not in url:
        return f"http://{url}"
    
    return url

