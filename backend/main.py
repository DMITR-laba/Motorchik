from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import chat, admin, auth, documents, chunks, ai, cars
from app.api import search_es
from app.api import import_api, parser_api, voice_api, domain_api
from app.api import model_management
from app.core.config import settings
from models import Base, engine
from models import database  # Импортируем модели для создания таблиц
import logging
import time
import asyncio
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_database():
    """Инициализация базы данных с проверкой подключения"""
    max_retries = 30
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            # Проверяем подключение к базе данных
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            
            logger.info("Подключение к базе данных установлено")
            
            # Создаем все таблицы
            Base.metadata.create_all(bind=engine)
            logger.info("Таблицы базы данных созданы/проверены")
            return True
            
        except OperationalError as e:
            logger.warning(f"Попытка {attempt + 1}/{max_retries}: Не удалось подключиться к базе данных: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error("Не удалось подключиться к базе данных после всех попыток")
                raise
        except Exception as e:
            logger.error(f"Ошибка при инициализации базы данных: {e}")
            raise

# Инициализируем базу данных
init_database()

app = FastAPI(
    title="AI-Портал техподдержки",
    description="Единый портал внутренней техподдержки с AI-ассистентом",
    version="1.0.0"
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение роутеров
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chunks.router)
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(import_api.router, prefix="/api/import", tags=["import"])
app.include_router(cars.router)
app.include_router(search_es.router)
app.include_router(parser_api.router, prefix="/api")
app.include_router(voice_api.router, prefix="/api")
app.include_router(domain_api.router)
app.include_router(model_management.router)


async def check_and_index_vector_db():
    """
    Проверяет наличие документов в векторной БД и запускает индексацию при необходимости
    """
    try:
        from services.vector_search_service import VectorSearchService
        from models import get_db
        from sqlalchemy import text
        
        logger.info("🔍 Проверяю наличие документов в векторной БД...")
        
        # Проверяем подключение к БД
        db = next(get_db())
        try:
            # Проверяем, есть ли документы в векторной БД
            # PGVector из langchain_postgres использует 'langchain_pg_embedding'
            # PGVector из langchain_community использует 'langchain_pg_embedding_{collection_name}'
            collection_name = "cars_collection"
            
            # Определяем имя таблицы в зависимости от версии PGVector
            try:
                from langchain_postgres import PGVector
                USE_NEW_PGVECTOR_CHECK = True
            except ImportError:
                try:
                    from langchain_community.vectorstores import PGVector
                    USE_NEW_PGVECTOR_CHECK = False
                except ImportError:
                    USE_NEW_PGVECTOR_CHECK = None
            
            if USE_NEW_PGVECTOR_CHECK:
                # Новая версия использует 'langchain_pg_embedding'
                table_name = "langchain_pg_embedding"
            else:
                # Старая версия использует 'langchain_pg_embedding_{collection_name}'
                table_name = f"langchain_pg_embedding_{collection_name}"
            
            # Используем begin() для автоматического управления транзакцией
            with engine.begin() as connection:
                # Проверяем, что расширение pgvector установлено
                try:
                    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                    logger.info("✅ Расширение pgvector установлено/проверено")
                except Exception as ext_error:
                    logger.warning(f"⚠️ Расширение pgvector не установлено в PostgreSQL: {ext_error}")
                    logger.warning("   Для работы векторного поиска необходимо установить pgvector:")
                    logger.warning("   1. Используйте образ PostgreSQL с pgvector (например, ankane/pgvector)")
                    logger.warning("   2. Или установите pgvector вручную в PostgreSQL")
                    # Векторный поиск будет недоступен, но приложение продолжит работу
                    return
                
                # Проверяем наличие таблицы
                try:
                    result = connection.execute(text(f"""
                        SELECT COUNT(*) as count 
                        FROM information_schema.tables 
                        WHERE table_name = '{table_name}'
                    """))
                    table_exists = result.scalar() > 0
                except Exception as table_check_error:
                    logger.warning(f"⚠️ Ошибка проверки таблицы: {table_check_error}")
                    return
                
                if table_exists:
                    # Проверяем количество документов
                    result = connection.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                    doc_count = result.scalar()
                    logger.info(f"📊 Найдено {doc_count} документов в векторной БД (pgvector)")
                    
                    # Если документов мало или нет - запускаем индексацию
                    if doc_count < 10:
                        logger.info("⚠️ Документов в векторной БД мало, запускаю индексацию...")
                        await run_vector_indexing(db)
                    else:
                        logger.info("✅ Векторная БД уже проиндексирована")
                else:
                    logger.info("⚠️ Таблица векторной БД не найдена, запускаю индексацию...")
                    await run_vector_indexing(db)
        finally:
            db.close()
            
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при проверке/индексации векторной БД: {e}")
        logger.warning("   Векторный поиск может быть недоступен, но приложение продолжит работу")


async def run_vector_indexing(db):
    """
    Запускает индексацию автомобилей в векторную БД в фоновом режиме
    """
    try:
        from index_cars_to_vector_db import index_cars_to_vector_db
        
        logger.info("🚀 Запускаю индексацию автомобилей в векторную БД...")
        # Запускаем индексацию в фоне (не блокируем запуск приложения)
        asyncio.create_task(index_cars_to_vector_db(batch_size=100, db_session=db))
        logger.info("✅ Индексация запущена в фоновом режиме")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска индексации: {e}")


@app.on_event("startup")
async def startup_event():
    """
    События при запуске приложения
    """
    logger.info("🚀 Запуск приложения...")
    
    # Индексация векторной БД уже выполнена в docker-entrypoint.sh
    # Здесь только проверяем статус (не блокируем запуск)
    try:
        from sqlalchemy import text
        with engine.begin() as connection:
            result = connection.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.tables 
                WHERE table_name = 'langchain_pg_embedding_cars_collection'
            """))
            table_exists = result.scalar() > 0
            if table_exists:
                result = connection.execute(text("SELECT COUNT(*) FROM langchain_pg_embedding_cars_collection"))
                doc_count = result.scalar()
                logger.info(f"📊 Векторная БД: {doc_count} документов")
            else:
                logger.info("📊 Векторная БД: не проиндексирована (будет доступна после индексации)")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось проверить статус векторной БД: {e}")


@app.get("/")
async def root():
    return {
        "message": "AI-Портал техподдержки API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )
