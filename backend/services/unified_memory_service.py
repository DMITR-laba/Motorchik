"""
UnifiedMemoryService - единый сервис для работы с долговременной памятью пользователя
Использует PostgreSQL + pgvector для хранения и семантического поиска предпочтений
"""
from typing import Dict, Any, List, Optional
import json
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import text
from models.database import UserMemory
from app.core.config import settings


class UnifiedMemoryService:
    """
    Единый сервис для работы с долговременной памятью пользователя
    
    Заменяет сложную схему Redis → Mem0 → Qdrant на простую:
    PostgreSQL + pgvector → прямое хранение и поиск
    """
    
    def __init__(self, db_session: Session, embedding_service=None):
        """
        Инициализация сервиса
        
        Args:
            db_session: SQLAlchemy сессия
            embedding_service: Сервис для создания эмбеддингов (опционально)
        """
        self.db = db_session
        self.embedding_service = embedding_service
    
    async def get_user_context(self, user_id: str, current_query: str) -> Dict[str, Any]:
        """
        Получает ВСЕ релевантные данные пользователя за один запрос
        
        Args:
            user_id: ID пользователя
            current_query: Текущий запрос пользователя
            
        Returns:
            Словарь с контекстом: history, preferences, entities, inferred_criteria
        """
        # 1. История диалога (последние 10 сообщений)
        history = await self._get_recent_history(user_id)
        
        # 2. Долговременные предпочтения из pgvector
        preferences = await self._get_user_preferences(user_id, current_query)
        
        # 3. Извлеченные сущности из текущего диалога
        entities = await self._extract_entities(history + [{"role": "user", "content": current_query}])
        
        return {
            "history": history,
            "preferences": preferences,
            "entities": entities,
            "inferred_criteria": self._infer_search_criteria(preferences, entities)
        }
    
    async def _get_recent_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Получает последние сообщения пользователя"""
        try:
            from models.database import ChatMessage
            from sqlalchemy import desc
            from sqlalchemy.exc import OperationalError, ProgrammingError
            
            try:
                messages = self.db.query(ChatMessage)\
                    .filter(ChatMessage.user_id == user_id)\
                    .order_by(desc(ChatMessage.created_at))\
                    .limit(limit)\
                    .all()
                
                history = []
                for msg in reversed(messages):  # В хронологическом порядке
                    history.append({
                        "role": "user",
                        "content": msg.message
                    })
                    if msg.response:
                        history.append({
                            "role": "assistant",
                            "content": msg.response
                        })
                
                return history
            except (OperationalError, ProgrammingError) as db_error:
                # Таблица не существует - это нормально для тестов
                if "no such table" in str(db_error).lower() or "does not exist" in str(db_error).lower():
                    return []
                raise
        except Exception as e:
            # Не логируем ошибки отсутствия таблиц как критичные
            if "no such table" not in str(e).lower() and "does not exist" not in str(e).lower():
                print(f"⚠️ Ошибка получения истории: {e}")
            return []
    
    async def _get_user_preferences(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Семантический поиск предпочтений в pgvector
        
        Args:
            user_id: ID пользователя
            query: Поисковый запрос
            limit: Максимальное количество результатов
            
        Returns:
            Список релевантных предпочтений
        """
        if not self.embedding_service:
            # Fallback: поиск без векторов (по тексту)
            return await self._get_preferences_by_text(user_id, query, limit)
        
        try:
            # Создаем эмбеддинг для запроса
            query_embedding = await self._get_embedding(query)
            if not query_embedding:
                return await self._get_preferences_by_text(user_id, query, limit)
            
            # Семантический поиск в pgvector
            # Преобразуем список в строку для PostgreSQL
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            # Используем оператор <=> для косинусного расстояния
            results = self.db.execute(
                text("""
                    SELECT 
                        id,
                        memory_type,
                        memory_text,
                        memory_metadata,
                        confidence,
                        1 - (embedding <=> :embedding::vector) as similarity
                    FROM user_memories 
                    WHERE user_id = :user_id 
                    AND embedding IS NOT NULL
                    AND embedding <=> :embedding::vector < 0.3
                    ORDER BY embedding <=> :embedding::vector
                    LIMIT :limit
                """),
                {
                    "user_id": user_id,
                    "embedding": embedding_str,
                    "limit": limit
                }
            )
            
            preferences = []
            for row in results:
                metadata = json.loads(row.memory_metadata) if row.memory_metadata else {}
                preferences.append({
                    "id": row.id,
                    "memory_type": row.memory_type,
                    "memory_text": row.memory_text,
                    "metadata": metadata,
                    "confidence": row.confidence,
                    "similarity": float(row.similarity) if row.similarity else 0.0
                })
            
            return preferences
            
        except Exception as e:
            print(f"⚠️ Ошибка семантического поиска предпочтений: {e}")
            return await self._get_preferences_by_text(user_id, query, limit)
    
    async def _get_preferences_by_text(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Fallback: поиск предпочтений по тексту (без векторов)"""
        try:
            from models.database import UserMemory
            from sqlalchemy.exc import OperationalError, ProgrammingError
            
            try:
                # Простой текстовый поиск
                memories = self.db.query(UserMemory)\
                    .filter(UserMemory.user_id == user_id)\
                    .filter(UserMemory.memory_text.ilike(f"%{query}%"))\
                    .order_by(UserMemory.confidence.desc(), UserMemory.created_at.desc())\
                    .limit(limit)\
                    .all()
                
                preferences = []
                for mem in memories:
                    metadata = json.loads(mem.memory_metadata) if mem.memory_metadata else {}
                    preferences.append({
                        "id": mem.id,
                        "memory_type": mem.memory_type,
                        "memory_text": mem.memory_text,
                        "metadata": metadata,
                        "confidence": mem.confidence,
                        "similarity": 0.5  # Нет векторов, используем среднее значение
                    })
                
                return preferences
            except (OperationalError, ProgrammingError) as db_error:
                # Таблица не существует - это нормально для тестов
                if "no such table" in str(db_error).lower() or "does not exist" in str(db_error).lower():
                    return []
                raise
        except Exception as e:
            # Не логируем ошибки отсутствия таблиц как критичные
            if "no such table" not in str(e).lower() and "does not exist" not in str(e).lower():
                print(f"⚠️ Ошибка текстового поиска предпочтений: {e}")
            return []
    
    async def save_memory(self, user_id: str, memory_data: Dict[str, Any]) -> Optional[int]:
        """
        Сохраняет ключевые факты о пользователе
        
        Args:
            user_id: ID пользователя
            memory_data: Данные памяти:
                - memory_type: 'preference', 'rejection', 'interest', 'criteria'
                - memory_text: Человекочитаемое описание
                - metadata: Структурированные данные (dict)
                - embedding: Векторное представление (опционально)
                - confidence: Уверенность (0.0-1.0, опционально)
                
        Returns:
            ID созданной записи или None при ошибке
        """
        try:
            from models.database import UserMemory
            
            memory_type = memory_data.get("memory_type", "preference")
            memory_text = memory_data.get("memory_text", "")
            metadata = memory_data.get("metadata", {})
            confidence = memory_data.get("confidence", 1.0)
            
            # Получаем или создаем эмбеддинг
            embedding = memory_data.get("embedding")
            if not embedding:
                embedding = await self._get_embedding(memory_text)
            
            # Преобразуем embedding в правильный формат для pgvector
            # Если это список, оставляем как есть (pgvector.sqlalchemy.Vector примет его)
            # Если это None, оставляем None
            
            # Создаем запись
            user_memory = UserMemory(
                user_id=user_id,
                memory_type=memory_type,
                memory_text=memory_text,
                embedding=embedding,  # pgvector примет список напрямую
                memory_metadata=json.dumps(metadata, ensure_ascii=False),
                confidence=confidence
            )
            
            self.db.add(user_memory)
            self.db.commit()
            self.db.refresh(user_memory)
            
            print(f"✅ Сохранена память для пользователя {user_id}: {memory_type} - {memory_text[:50]}...")
            return user_memory.id
            
        except Exception as e:
            print(f"⚠️ Ошибка сохранения памяти: {e}")
            import traceback
            traceback.print_exc()
            self.db.rollback()
            return None
    
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Получает эмбеддинг для текста"""
        if not self.embedding_service:
            # Используем Mistral API напрямую
            return await self._get_mistral_embedding(text)
        
        try:
            # Пробуем разные методы получения эмбеддинга
            if hasattr(self.embedding_service, 'embed_query'):
                result = self.embedding_service.embed_query(text)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            elif hasattr(self.embedding_service, 'encode'):
                return self.embedding_service.encode(text).tolist()
            elif callable(self.embedding_service):
                result = self.embedding_service(text)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            else:
                return await self._get_mistral_embedding(text)
        except Exception as e:
            print(f"⚠️ Ошибка создания эмбеддинга через сервис: {e}")
            return await self._get_mistral_embedding(text)
    
    async def _get_mistral_embedding(self, text: str) -> Optional[List[float]]:
        """Получает эмбеддинг через Mistral API"""
        try:
            import httpx
            from app.core.config import settings
            
            url = f"{settings.mistral_base_url}/v1/embeddings"
            headers = {
                "Authorization": f"Bearer {settings.mistral_api_key}",
                "Content-Type": "application/json",
            }
            
            payload = {
                "model": settings.mistral_embed_model,
                "input": text
            }
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                items = data.get("data", [])
                if items:
                    embedding = items[0].get("embedding", [])
                    if len(embedding) == 1024:
                        return embedding
            
            return None
        except Exception as e:
            print(f"⚠️ Ошибка получения эмбеддинга через Mistral API: {e}")
            return None
    
    async def _extract_entities(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Извлекает сущности из диалога (упрощенная версия)
        
        В полной реализации здесь будет вызов LLM для извлечения сущностей
        """
        # Упрощенная версия - извлекаем базовые паттерны
        entities = {
            "brands": [],
            "budget": {"min": None, "max": None},
            "preferences": []
        }
        
        # Простой парсинг (в полной версии будет LLM)
        for msg in messages:
            content = msg.get("content", "").lower()
            
            # Поиск брендов (упрощенно)
            brands = ["audi", "bmw", "mercedes", "ford", "toyota", "volkswagen"]
            for brand in brands:
                if brand in content:
                    if brand not in entities["brands"]:
                        entities["brands"].append(brand)
        
        return entities
    
    def _infer_search_criteria(self, preferences: List[Dict[str, Any]], entities: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выводит критерии поиска на основе предпочтений и сущностей
        
        Args:
            preferences: Список предпочтений пользователя
            entities: Извлеченные сущности
            
        Returns:
            Словарь с критериями поиска
        """
        criteria = {}
        
        # Извлекаем критерии из предпочтений
        for pref in preferences:
            metadata = pref.get("metadata", {})
            
            # Бренды
            if "brands" in metadata:
                criteria.setdefault("brands", []).extend(metadata["brands"])
            
            # Бюджет
            if "max_price" in metadata:
                if "max_price" not in criteria or criteria["max_price"] > metadata["max_price"]:
                    criteria["max_price"] = metadata["max_price"]
            
            if "min_price" in metadata:
                if "min_price" not in criteria or criteria["min_price"] < metadata["min_price"]:
                    criteria["min_price"] = metadata["min_price"]
            
            # Другие критерии
            for key in ["body_types", "fuel_types", "drive_types", "cities"]:
                if key in metadata:
                    criteria.setdefault(key, []).extend(metadata[key])
        
        # Добавляем критерии из сущностей
        if entities.get("brands"):
            criteria.setdefault("brands", []).extend(entities["brands"])
        
        if entities.get("budget", {}).get("max"):
            criteria["max_price"] = entities["budget"]["max"]
        
        # Убираем дубликаты
        for key in ["brands", "body_types", "fuel_types", "drive_types", "cities"]:
            if key in criteria:
                criteria[key] = list(set(criteria[key]))
        
        return criteria
    
    def _format_memory(self, memory_data: Dict[str, Any]) -> str:
        """Форматирует данные памяти в читаемый текст"""
        memory_type = memory_data.get("memory_type", "preference")
        metadata = memory_data.get("metadata", {})
        
        parts = []
        
        if memory_type == "preference":
            parts.append("Пользователь предпочитает")
            
            if metadata.get("brands"):
                parts.append(f"марки: {', '.join(metadata['brands'])}")
            
            if metadata.get("max_price"):
                parts.append(f"бюджет до {metadata['max_price']} руб")
            
            if metadata.get("body_types"):
                parts.append(f"тип кузова: {', '.join(metadata['body_types'])}")
        
        elif memory_type == "rejection":
            parts.append("Пользователь отказался от")
            
            if metadata.get("rejected_car_id"):
                parts.append(f"автомобиля ID {metadata['rejected_car_id']}")
            
            if metadata.get("rejection_reason"):
                parts.append(f"по причине: {metadata['rejection_reason']}")
        
        return " ".join(parts) if parts else memory_data.get("memory_text", "")

