#!/usr/bin/env python3
"""
Скрипт для импорта статей из articles.json в базу данных
"""
import json
import sys
import os
from pathlib import Path

# Добавляем путь к модулям
sys.path.append(str(Path(__file__).parent))

from models import SessionLocal, Base, engine
from models.schemas import ArticleCreate
from services.database_service import DatabaseService
from app.api.auth import get_password_hash
from models.schemas import UserCreate
from app.core.config import settings
import requests
import re
import time

# Создаем таблицы
Base.metadata.create_all(bind=engine)


def import_articles(json_file_path: str):
    """Импортирует статьи из JSON файла"""
    
    # Читаем JSON файл
    with open(json_file_path, 'r', encoding='utf-8') as f:
        articles_data = json.load(f)
    
    print(f"Найдено {len(articles_data)} статей для импорта")
    
    # Подключаемся к БД
    db = SessionLocal()
    db_service = DatabaseService(db)
    
    imported_count = 0
    error_count = 0
    
    for i, article_data in enumerate(articles_data, 1):
        try:
            # Создаем объект ArticleCreate
            title = article_data.get('title', '') or ''
            text = article_data.get('text', '') or ''
            url = article_data.get('url', '') or ''
            language = article_data.get('language', 'ru') or 'ru'

            # Авто-теги (простая эвристика)
            tag_names = extract_tags_from_text(f"{title}\n{text}")
            # Если эвристика не дала результатов — попросим llama3 сгенерировать 3-8 тегов
            if not tag_names:
                try:
                    tag_names = generate_tags_with_ollama(title, text)
                except Exception:
                    tag_names = []
            article_create = ArticleCreate(
                title=title,
                text=text,
                url=url,
                language=language,
                category_ids=[],  # Пока без категорий
                tag_names=tag_names[:8]      # до 8 тегов
            )
            
            # Сохраняем в БД
            db_service.create_article(article_create)
            imported_count += 1
            
            if i % 100 == 0:
                print(f"Обработано {i} статей...")
                
        except Exception as e:
            error_count += 1
            print(f"Ошибка при импорте статьи {i}: {str(e)}")
            continue
    
    db.close()
    
    print(f"\nИмпорт завершен!")
    print(f"Успешно импортировано: {imported_count}")
    print(f"Ошибок: {error_count}")


def extract_tags_from_text(text: str):
    text = text or ''
    tags = set()
    # Вытащим часто встречающиеся тех. слова (латиница/кириллица, цифры, дефисы), длина 3..24
    for m in re.findall(r"\b[\w\-]{3,24}\b", text, flags=re.IGNORECASE):
        token = m.strip().strip('-_').lower()
        if len(token) < 3:
            continue
        # простые фильтры стоп-слов
        if token in { 'the','and','или','для','при','это','that','this','with','from','как','что','где','или','или','без' }:
            continue
        # доменные кандидаты
        if any(s in token for s in ['autocad','excel','outlook','sql','mssql','rdp','сбп','офд','git','dms','glpi','crypto','крипто','честный','знак','wa','payment','haraba']):
            tags.add(token.upper())
        # ключевые паттерны
        if re.match(r"^[A-Z0-9\-]{3,24}$", m):
            tags.add(m.upper())
    return list(tags)


def generate_tags_with_ollama(title: str, text: str):
    prompt = (
        "Ты — помощник по разметке базы знаний. По заголовку и тексту статьи предложи от 3 до 8 кратких тегов "
        "(одно-двухсловные маркеры) на русском языке, БЕЗ комментариев. Верни только список через запятую.\n\n"
        f"Заголовок: {title}\n\nТекст: {text[:1200]}"
    )
    # Используем Mistral для генерации тегов
    url = f"{settings.mistral_base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.mistral_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.mistral_model,
        "messages": [
            {"role": "system", "content": "Ты — помощник по разметке базы знаний. Отвечай только тегами."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 256,
        "stream": False,
    }
    # Повторы на случай 429
    last_err = None
    for attempt in range(4):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else (0.5 * (2 ** attempt))
                time.sleep(min(delay, 5.0))
                continue
            resp.raise_for_status()
            data = resp.json() or {}
            break
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (2 ** attempt))
    else:
        # Фолбэк: без LLM вернем эвристические теги
        return extract_tags_from_text(f"{title}\n{text}")
    raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    # Преобразуем в набор тегов
    parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
    # нормализуем
    norm = []
    for p in parts:
        # удалим служебные символы
        p = re.sub(r"[^\w\-\sА-Яа-я]", "", p, flags=re.UNICODE)
        p = p.strip()
        if 2 < len(p) <= 32 and p.lower() not in {"теги", "тег", "категория", "категории"}:
            norm.append(p.upper())
    # уникализируем и ограничим 8
    out = []
    for t in norm:
        if t not in out:
            out.append(t)
        if len(out) >= 8:
            break
    return out


def create_default_categories(db_service: DatabaseService):
    """Создает стандартные категории"""
    categories = [
        {"name": "AutoCAD", "description": "Проблемы и настройки AutoCAD"},
        {"name": "Офисные приложения (MSO)", "description": "Excel, Outlook, создание подписей"},
        {"name": "Операционные системы (Windows)", "description": "Ошибки проводника, удаление профиля, активация"},
        {"name": "Базы данных (SQL Server)", "description": "Версии MSSQL"},
        {"name": "ИТ-Инфраструктура", "description": "Терминальные серверы, RDP, сопоставление файлов"},
        {"name": "Внутренние системы и регламенты", "description": "Регламент взаимодействия, ИТ-паспорта"},
        {"name": "Система DMS МТ", "description": "Обновление МТ, работа с заказ-нарядами"},
        {"name": "ЭДО и Финансы", "description": "Диадок, Честный знак, СБП, эквайринг, ОФД"},
        {"name": "Веб и API", "description": "Git, Haraba, WaPayment, фиды"},
        {"name": "Интеграции и Внешние сервисы", "description": "Launch, ODIS, СИТИС, киоски"},
        {"name": "Инструкции для пользователей", "description": "Как получить ИНН, авторизация в GLPI"},
        {"name": "Оборудование", "description": "Планшеты, кассы, Getac"}
    ]
    
    for cat_data in categories:
        try:
            from models.schemas import CategoryCreate
            category_create = CategoryCreate(name=cat_data["name"], description=cat_data["description"])
            db_service.create_category(category_create)
            print(f"Создана категория: {cat_data['name']}")
        except Exception as e:
            print(f"Ошибка при создании категории {cat_data['name']}: {str(e)}")


KW_TO_CATEGORY = {
    'autocad': 'AutoCAD',
    'excel': 'Офисные приложения (MSO)',
    'outlook': 'Офисные приложения (MSO)',
    'word': 'Офисные приложения (MSO)',
    'windows': 'Операционные системы (Windows)',
    'mssql': 'Базы данных (SQL Server)',
    'sql server': 'Базы данных (SQL Server)',
    'rdp': 'ИТ-Инфраструктура',
    'терминал': 'ИТ-Инфраструктура',
    'сбп': 'ЭДО и Финансы',
    'офд': 'ЭДО и Финансы',
    'честный знак': 'ЭДО и Финансы',
    'git': 'Веб и API',
}


def choose_category_by_keywords(text: str, existing_names: list[str]) -> str | None:
    low = (text or '').lower()
    for kw, cat in KW_TO_CATEGORY.items():
        if kw in low and cat in existing_names:
            return cat
    return None


def generate_category_with_ollama(title: str, text: str, choices: list[str]) -> str | None:
    if not choices:
        return None
    prompt = (
        "Выберите ОДНУ наиболее подходящую категорию для статьи из списка. Отвечайте только точным названием из списка без дополнительных слов.\n\n"
        f"Заголовок: {title}\n\nТекст: {text[:1200]}\n\nКатегории: {', '.join(choices)}"
    )
    # Используем Mistral для выбора категории
    url = f"{settings.mistral_base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.mistral_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.mistral_model,
        "messages": [
            {"role": "system", "content": "Выбирай только ОДНО название категории из списка."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 64,
        "stream": False,
    }
    last_err = None
    for attempt in range(4):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else (0.5 * (2 ** attempt))
                time.sleep(min(delay, 5.0))
                continue
            resp.raise_for_status()
            ans = (((resp.json() or {}).get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
            break
        except Exception as e:
            last_err = e
            time.sleep(0.5 * (2 ** attempt))
    else:
        return None
    # вернем первое совпадение
    for c in choices:
        if c.lower() in ans.lower():
            return c
    return None


if __name__ == "__main__":
    # Путь к файлу articles.json
    json_file = "articles.json"
    
    if not os.path.exists(json_file):
        print(f"Файл {json_file} не найден!")
        print("Убедитесь, что файл articles.json находится в корневой директории проекта")
        sys.exit(1)
    
    print("Начинаем импорт статей и создание администратора...")
    
    # Создаем подключение к БД для создания категорий
    db = SessionLocal()
    db_service = DatabaseService(db)
    
    # Создаем стандартные категории
    print("Создаем стандартные категории...")
    create_default_categories(db_service)
    
    # Создаем администратора, если отсутствует
    if not db_service.get_user_by_email("admin@example.com"):
        user_data = UserCreate(email="admin@example.com", full_name="Admin", password="admin123")
        db_service.create_user(user_data, hashed_password=get_password_hash(user_data.password), role="admin")
        print("Создан пользователь администратор: admin@example.com / admin123")
    db.close()
    
    # Импортируем статьи
    import_articles(json_file)
