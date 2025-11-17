#!/usr/bin/env python3
"""
Скрипт для применения миграций базы данных
"""
import sys
import os
from pathlib import Path

# Добавляем путь к модулям
sys.path.append(str(Path(__file__).parent.parent))

import asyncio
from sqlalchemy import create_engine, text
from app.core.config import settings


def apply_migration(engine, migration_file: str):
    """Применяет SQL миграцию из файла"""
    migration_path = Path(__file__).parent.parent / "migrations" / migration_file
    
    if not migration_path.exists():
        print(f"❌ Файл миграции не найден: {migration_path}")
        return False
    
    print(f"📄 Применяю миграцию: {migration_file}")
    
    try:
        with open(migration_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        with engine.begin() as connection:
            # Разбиваем на отдельные команды (разделитель ;)
            commands = [cmd.strip() for cmd in sql_content.split(';') if cmd.strip()]
            
            for i, command in enumerate(commands, 1):
                if command:
                    try:
                        connection.execute(text(command))
                        print(f"  ✅ Команда {i}/{len(commands)} выполнена")
                    except Exception as e:
                        # Некоторые команды могут быть уже выполнены (IF NOT EXISTS)
                        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                            print(f"  ⚠️ Команда {i} пропущена (уже выполнена): {e}")
                        else:
                            raise
        
        print(f"✅ Миграция {migration_file} успешно применена")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка применения миграции {migration_file}: {e}")
        return False


def main():
    """Основная функция"""
    print("🚀 Применение миграций базы данных")
    print(f"📊 Подключение к: {settings.database_url.split('@')[1] if '@' in settings.database_url else 'скрыто'}")
    
    # Создаем подключение
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=False
    )
    
    # Список миграций в порядке применения
    migrations = [
        "001_create_user_memories.sql",
        "002_fix_chat_message_chat_id.sql"
    ]
    
    success_count = 0
    for migration in migrations:
        if apply_migration(engine, migration):
            success_count += 1
        else:
            print(f"⚠️ Миграция {migration} не применена, продолжаем...")
    
    print(f"\n📊 Результат: {success_count}/{len(migrations)} миграций применено")
    
    if success_count == len(migrations):
        print("✅ Все миграции успешно применены!")
        return 0
    else:
        print("⚠️ Некоторые миграции не применены, проверьте логи")
        return 1


if __name__ == "__main__":
    exit(main())

