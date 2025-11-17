#!/usr/bin/env python3
"""
Скрипт для миграции памяти пользователей из Qdrant в PostgreSQL
Переносит все воспоминания из Mem0/Qdrant в таблицу user_memories
"""
import sys
import os
from pathlib import Path
import asyncio

# Добавляем путь к модулям
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from services.unified_memory_service import UnifiedMemoryService


def get_qdrant_client():
    """Создает клиент Qdrant"""
    try:
        from qdrant_client import QdrantClient
        
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        return QdrantClient(url=qdrant_url)
    except ImportError:
        print("❌ Qdrant клиент не установлен. Установите: pip install qdrant-client")
        return None
    except Exception as e:
        print(f"❌ Ошибка подключения к Qdrant: {e}")
        return None


async def migrate_memories():
    """Переносит память из Qdrant в PostgreSQL"""
    print("🚀 Начало миграции памяти из Qdrant в PostgreSQL")
    
    # Создаем подключение к БД
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=False
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_session = SessionLocal()
    
    # Создаем UnifiedMemoryService
    memory_service = UnifiedMemoryService(db_session=db_session)
    
    # Подключаемся к Qdrant
    qdrant = get_qdrant_client()
    if not qdrant:
        print("❌ Не удалось подключиться к Qdrant")
        return 1
    
    try:
        # Получаем все коллекции
        collections = qdrant.get_collections()
        
        migrated_count = 0
        error_count = 0
        
        print(f"📊 Найдено коллекций: {len(collections.collections)}")
        
        for collection in collections.collections:
            collection_name = collection.name
            
            # Пропускаем системные коллекции
            if collection_name == "mem0migrations":
                continue
            
            # Извлекаем user_id из имени коллекции
            # Формат: user_{user_id}_memories или {user_id}_memories
            if "_memories" in collection_name:
                user_id = collection_name.replace("_memories", "").replace("user_", "")
            else:
                # Пробуем найти user_id в метаданных точек
                user_id = None
            
            if not user_id:
                print(f"⚠️ Не удалось определить user_id для коллекции {collection_name}, пропускаем")
                continue
            
            print(f"📦 Обрабатываю коллекцию: {collection_name} (user_id: {user_id})")
            
            try:
                # Получаем все точки из коллекции
                points, _ = qdrant.scroll(
                    collection_name=collection_name,
                    limit=1000,
                    with_payload=True,
                    with_vectors=True
                )
                
                print(f"  Найдено точек: {len(points)}")
                
                for point in points:
                    try:
                        payload = point.payload or {}
                        
                        # Извлекаем данные
                        memory_text = payload.get("memory", payload.get("content", ""))
                        if not memory_text:
                            continue
                        
                        metadata = payload.get("metadata", {})
                        memory_type = metadata.get("memory_type", "preference")
                        
                        # Используем вектор из точки
                        embedding = point.vector if hasattr(point, 'vector') and point.vector else None
                        
                        # Сохраняем в PostgreSQL
                        memory_id = await memory_service.save_memory(
                            user_id=user_id,
                            memory_data={
                                "memory_type": memory_type,
                                "memory_text": memory_text,
                                "metadata": metadata,
                                "embedding": embedding,
                                "confidence": metadata.get("confidence", 1.0)
                            }
                        )
                        
                        if memory_id:
                            migrated_count += 1
                        else:
                            error_count += 1
                            print(f"  ⚠️ Не удалось сохранить память для точки {point.id}")
                    
                    except Exception as e:
                        error_count += 1
                        print(f"  ⚠️ Ошибка обработки точки {point.id}: {e}")
                
                print(f"  ✅ Коллекция {collection_name} обработана")
            
            except Exception as e:
                print(f"  ❌ Ошибка обработки коллекции {collection_name}: {e}")
                error_count += 1
        
        print(f"\n📊 Результат миграции:")
        print(f"  ✅ Успешно мигрировано: {migrated_count}")
        print(f"  ❌ Ошибок: {error_count}")
        
        if migrated_count > 0:
            print(f"\n✅ Миграция завершена успешно!")
            return 0
        else:
            print(f"\n⚠️ Не было мигрировано ни одной записи")
            return 1
    
    except Exception as e:
        print(f"❌ Критическая ошибка миграции: {e}")
        return 1
    
    finally:
        db_session.close()


def main():
    """Основная функция"""
    try:
        result = asyncio.run(migrate_memories())
        return result
    except KeyboardInterrupt:
        print("\n⚠️ Миграция прервана пользователем")
        return 1
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        return 1


if __name__ == "__main__":
    exit(main())

