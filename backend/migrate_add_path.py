#!/usr/bin/env python3
"""
Скрипт для добавления столбца path в таблицу documents
"""
import sys
from pathlib import Path

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent))

from models import get_db
from sqlalchemy import text

def migrate_add_path():
    """Добавляет столбец path в таблицу documents"""
    db = next(get_db())
    
    try:
        # Проверяем, существует ли столбец path
        result = db.execute(text("PRAGMA table_info(documents)"))
        columns = [row[1] for row in result.fetchall()]
        
        if 'path' in columns:
            print("✅ Столбец 'path' уже существует в таблице documents")
            return
        
        # Добавляем столбец path
        db.execute(text("ALTER TABLE documents ADD COLUMN path VARCHAR(512)"))
        
        db.commit()
        print("✅ Столбец 'path' успешно добавлен в таблицу documents!")
        
    except Exception as e:
        print(f"❌ Ошибка при добавлении столбца: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    migrate_add_path()







