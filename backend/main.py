from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import chat, admin, auth, documents, chunks, ai, cars
from app.api import search_es
from app.api import import_api, parser_api, voice_api
from app.core.config import settings
from models import Base, engine
from models import database  # Импортируем модели для создания таблиц
import logging
import time
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
