#!/usr/bin/env python3
"""
Скрипт для создания таблицы чанков документов
"""
import sys
from pathlib import Path

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent))

from models import get_db
from models.database import DocumentChunk
from sqlalchemy import text

def migrate_chunks():
    """Создает таблицу для чанков документов"""
    db = next(get_db())
    
    try:
        # Проверяем, существует ли таблица
        result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'"))
        if result.fetchone():
            print("✅ Таблица document_chunks уже существует")
            return
        
        # Создаем таблицу
        db.execute(text("""
            CREATE TABLE document_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents (id)
            )
        """))
        
        # Создаем индексы
        db.execute(text("CREATE INDEX ix_document_chunks_document_id ON document_chunks (document_id)"))
        db.execute(text("CREATE INDEX ix_document_chunks_chunk_index ON document_chunks (chunk_index)"))
        
        db.commit()
        print("✅ Таблица document_chunks успешно создана!")
        print("Созданные индексы:")
        print("- ix_document_chunks_document_id")
        print("- ix_document_chunks_chunk_index")
        
    except Exception as e:
        print(f"❌ Ошибка при создании таблицы: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    migrate_chunks()







