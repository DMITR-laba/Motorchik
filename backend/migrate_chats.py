"""
Скрипт миграции для добавления таблицы chats и обновления chat_messages
"""
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text
from app.core.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_database():
    """Выполняет миграцию базы данных для чатов"""
    try:
        # Создаем engine
        engine = create_engine(
            settings.database_url,
            echo=False
        )
        
        with engine.connect() as conn:
            # Начинаем транзакцию
            trans = conn.begin()
            
            try:
                # 1. Создаем таблицу chats если её нет
                logger.info("Проверяю наличие таблицы chats...")
                result = conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='chats'
                """))
                
                if result.fetchone() is None:
                    logger.info("Создаю таблицу chats...")
                    conn.execute(text("""
                        CREATE TABLE chats (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id VARCHAR(100) NOT NULL,
                            title VARCHAR(500),
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME
                        )
                    """))
                    conn.execute(text("CREATE INDEX ix_chats_user_id ON chats(user_id)"))
                    logger.info("✅ Таблица chats создана")
                else:
                    logger.info("✅ Таблица chats уже существует")
                
                # 2. Проверяем и добавляем колонку chat_id в chat_messages
                logger.info("Проверяю наличие колонки chat_id в chat_messages...")
                result = conn.execute(text("PRAGMA table_info(chat_messages)"))
                columns = [row[1] for row in result.fetchall()]
                
                if 'chat_id' not in columns:
                    logger.info("Добавляю колонку chat_id в chat_messages...")
                    # SQLite не поддерживает ALTER TABLE ADD COLUMN с NOT NULL без значения по умолчанию
                    # Поэтому добавляем как nullable сначала
                    conn.execute(text("""
                        ALTER TABLE chat_messages 
                        ADD COLUMN chat_id INTEGER
                    """))
                    # Создаем индекс для chat_id
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_messages_chat_id ON chat_messages(chat_id)"))
                    logger.info("✅ Колонка chat_id добавлена")
                else:
                    logger.info("✅ Колонка chat_id уже существует")
                
                # 3. Проверяем и добавляем колонку sources_data в chat_messages
                logger.info("Проверяю наличие колонки sources_data в chat_messages...")
                result = conn.execute(text("PRAGMA table_info(chat_messages)"))
                columns = [row[1] for row in result.fetchall()]
                
                if 'sources_data' not in columns:
                    logger.info("Добавляю колонку sources_data в chat_messages...")
                    conn.execute(text("""
                        ALTER TABLE chat_messages 
                        ADD COLUMN sources_data TEXT
                    """))
                    logger.info("✅ Колонка sources_data добавлена")
                else:
                    logger.info("✅ Колонка sources_data уже существует")
                
                # 4. Если есть записи без chat_id, создаем для них чат
                logger.info("Проверяю записи без chat_id...")
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM chat_messages WHERE chat_id IS NULL
                """))
                count = result.fetchone()[0]
                
                if count > 0:
                    logger.info(f"Найдено {count} записей без chat_id. Создаю чаты для них...")
                    # Группируем по user_id и создаем чат для каждой группы
                    result = conn.execute(text("""
                        SELECT DISTINCT user_id FROM chat_messages WHERE chat_id IS NULL
                    """))
                    user_ids = [row[0] for row in result.fetchall()]
                    
                    for user_id in user_ids:
                        # Создаем чат для пользователя
                        conn.execute(text("""
                            INSERT INTO chats (user_id, title, created_at)
                            VALUES (:user_id, NULL, CURRENT_TIMESTAMP)
                        """), {"user_id": user_id})
                        
                        # Получаем ID созданного чата
                        result = conn.execute(text("""
                            SELECT id FROM chats WHERE user_id = :user_id 
                            ORDER BY created_at DESC LIMIT 1
                        """), {"user_id": user_id})
                        chat_id = result.fetchone()[0]
                        
                        # Обновляем все сообщения этого пользователя без chat_id
                        conn.execute(text("""
                            UPDATE chat_messages 
                            SET chat_id = :chat_id 
                            WHERE user_id = :user_id AND chat_id IS NULL
                        """), {"chat_id": chat_id, "user_id": user_id})
                    
                    logger.info(f"✅ Создано {len(user_ids)} чатов для существующих сообщений")
                
                # Коммитим транзакцию
                trans.commit()
                logger.info("✅ Миграция успешно завершена")
                return True
                
            except Exception as e:
                trans.rollback()
                logger.error(f"❌ Ошибка при миграции: {e}")
                raise
                
    except Exception as e:
        logger.error(f"❌ Критическая ошибка миграции: {e}")
        return False


if __name__ == "__main__":
    logger.info("🚀 Начинаю миграцию базы данных для чатов...")
    success = migrate_database()
    if success:
        logger.info("✅ Миграция завершена успешно")
        sys.exit(0)
    else:
        logger.error("❌ Миграция завершена с ошибками")
        sys.exit(1)



