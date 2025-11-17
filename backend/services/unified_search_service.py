"""
UnifiedSearchService - единый сервис для интеллектуального поиска
Объединяет Elasticsearch (полнотекстовый) и pgvector (семантический) в гибридный поиск
"""
from typing import Dict, Any, List, Optional
import asyncio
from sqlalchemy.orm import Session


class UnifiedSearchService:
    """
    Единый сервис для интеллектуального поиска автомобилей
    
    Заменяет множественные пути поиска на один унифицированный:
    - Анализирует запрос
    - Выбирает стратегию поиска (точный, гибридный, семантический)
    - Объединяет результаты из разных источников
    - Переранжирует результаты
    """
    
    def __init__(
        self,
        elasticsearch_service=None,
        vector_search_service=None,
        database_service=None
    ):
        """
        Инициализация сервиса
        
        Args:
            elasticsearch_service: Сервис для полнотекстового поиска
            vector_search_service: Сервис для векторного поиска
            database_service: Сервис для работы с БД
        """
        self.es = elasticsearch_service
        self.vector = vector_search_service
        self.db = database_service
    
    async def intelligent_search(
        self,
        query: str,
        user_context: Dict[str, Any] = None,
        filters: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Умный поиск, который сам решает, какие источники использовать
        
        Args:
            query: Поисковый запрос пользователя
            user_context: Контекст пользователя (предпочтения, история)
            filters: Дополнительные фильтры поиска
            
        Returns:
            Словарь с результатами поиска
        """
        if not query or not query.strip():
            return {
                "results": [],
                "total": 0,
                "search_type": "empty",
                "confidence": 0.0
            }
        
        # Анализ запроса
        intent_analysis = await self._analyze_query_intent(query, user_context or {})
        
        results = {}
        
        # Параллельный поиск по всем источникам
        if intent_analysis.get("needs_car_search", True):
            results["cars"] = await self._hybrid_car_search(query, filters or {}, user_context or {})
        
        if intent_analysis.get("needs_knowledge", False):
            results["knowledge"] = await self._knowledge_search(query, user_context or {})
        
        # Объединение и переранжирование
        return self._rank_and_merge_results(results, intent_analysis)
    
    async def _analyze_query_intent(
        self,
        query: str,
        user_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Анализирует намерение запроса
        
        Returns:
            Словарь с анализом: needs_car_search, needs_knowledge, search_type
        """
        query_lower = query.lower()
        
        # Ключевые слова для определения типа запроса
        car_keywords = [
            "автомобиль", "машина", "авто", "купить", "цена", "бюджет",
            "марка", "модель", "год", "пробег", "vin", "привод", "кузов"
        ]
        
        knowledge_keywords = [
            "как", "что такое", "объясни", "расскажи", "информация",
            "характеристики", "отзывы", "сравнение"
        ]
        
        has_car_intent = any(keyword in query_lower for keyword in car_keywords)
        has_knowledge_intent = any(keyword in query_lower for keyword in knowledge_keywords)
        
        # Определяем тип поиска
        if has_car_intent:
            search_type = "exact" if self._is_exact_query(query) else "hybrid"
        elif has_knowledge_intent:
            search_type = "knowledge"
        else:
            search_type = "hybrid"  # По умолчанию гибридный
        
        return {
            "needs_car_search": has_car_intent or not has_knowledge_intent,
            "needs_knowledge": has_knowledge_intent,
            "search_type": search_type,
            "is_exact": self._is_exact_query(query)
        }
    
    def _is_exact_query(self, query: str) -> bool:
        """Проверяет, является ли запрос точным (VIN, марка-модель)"""
        import re
        
        # VIN код
        if re.search(r'\b[A-HJ-NPR-Z0-9]{11,17}\b', query, re.IGNORECASE):
            return True
        
        # Точная марка и модель
        if re.search(r'\b(audi|bmw|mercedes|ford|toyota)\s+\w+\b', query, re.IGNORECASE):
            return True
        
        return False
    
    async def _hybrid_car_search(
        self,
        query: str,
        filters: Dict[str, Any],
        user_context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Гибридный поиск автомобилей
        
        Объединяет:
        1. Точный поиск (Elasticsearch) - для точных совпадений
        2. Семантический поиск (pgvector) - для семантических совпадений
        """
        # Параллельный поиск
        es_future = self._exact_search(query, filters)
        vector_future = self._semantic_search(query, filters, user_context)
        
        es_results, vector_results = await asyncio.gather(
            es_future,
            vector_future,
            return_exceptions=True
        )
        
        # Обработка ошибок
        if isinstance(es_results, Exception):
            print(f"⚠️ Ошибка Elasticsearch поиска: {es_results}")
            es_results = []
        
        if isinstance(vector_results, Exception):
            print(f"⚠️ Ошибка векторного поиска: {vector_results}")
            vector_results = []
        
        # Объединение и переранжирование
        return await self._merge_search_results(es_results, vector_results, user_context)
    
    async def _exact_search(
        self,
        query: str,
        criteria: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Поиск по точным совпадениям в Elasticsearch"""
        if not self.es or not self.es.is_available():
            return []
        
        try:
            # Преобразуем критерии в параметры Elasticsearch
            es_params = {
                "query": query,
                "mark": criteria.get("brands", [None])[0] if criteria.get("brands") else None,
                "min_price": criteria.get("min_price"),
                "max_price": criteria.get("max_price"),
                "min_year": criteria.get("min_year"),
                "max_year": criteria.get("max_year"),
                "limit": 20
            }
            
            # Удаляем None значения
            es_params = {k: v for k, v in es_params.items() if v is not None}
            
            # ElasticsearchService.search_cars может быть синхронным
            if asyncio.iscoroutinefunction(self.es.search_cars):
                result = await self.es.search_cars(**es_params)
            else:
                result = self.es.search_cars(**es_params)
            
            # Преобразуем в единый формат
            cars = []
            for hit in result.get("hits", []):
                source = hit.get("_source", {})
                car_id = source.get("id")
                car_type = source.get("type", "car")
                
                # Загружаем полный объект из БД, если доступен
                car_obj = None
                if car_id and self.db:
                    if car_type == "used_car":
                        car_obj = self.db.get_used_car(car_id)
                    else:
                        car_obj = self.db.get_car(car_id)
                
                cars.append({
                    "id": car_id,
                    "type": car_type,
                    "score": hit.get("_score", 0.0),
                    "sources": ["elasticsearch"],  # Список источников
                    "data": car_obj if car_obj else source  # Возвращаем объект, если есть, иначе словарь
                })
            
            return cars
            
        except Exception as e:
            print(f"⚠️ Ошибка точного поиска: {e}")
            return []
    
    async def _semantic_search(
        self,
        query: str,
        criteria: Dict[str, Any],
        user_context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Семантический поиск с учетом контекста пользователя"""
        if not self.vector:
            return []
        
        try:
            # Подготавливаем запрос для семантического поиска
            semantic_query = self._prepare_semantic_query(query, user_context)
            
            # Векторный поиск
            # Используем k вместо limit (параметр называется k в VectorSearchService)
            vector_results = await self.vector.similarity_search(
                semantic_query,
                k=20,  # Исправлено: используем k вместо limit
                filters=criteria
            )
            
            # Преобразуем в единый формат
            cars = []
            for doc, score in vector_results:
                metadata = getattr(doc, 'metadata', {}) if hasattr(doc, 'metadata') else {}
                car_id = metadata.get("car_id") or metadata.get("id")
                
                if car_id and self.db:
                    # Загружаем полные данные из БД
                    car_type = metadata.get("type", "car")
                    if car_type == "used_car":
                        car_obj = self.db.get_used_car(car_id)
                    else:
                        car_obj = self.db.get_car(car_id)
                    
                    if car_obj:
                        cars.append({
                            "id": car_id,
                            "type": car_type,
                            "score": float(score),
                            "sources": ["vector"],  # Список источников
                            "data": self._car_to_dict(car_obj)
                        })
            
            return cars
            
        except Exception as e:
            # Не логируем как критичную ошибку, если это просто отсутствие pgvector
            if "pgvector" not in str(e).lower() and "document" not in str(e).lower():
                print(f"⚠️ Ошибка семантического поиска: {e}")
            return []
    
    def _prepare_semantic_query(self, query: str, user_context: Dict[str, Any]) -> str:
        """Подготавливает запрос для семантического поиска"""
        import re
        
        # Удаляем числовые параметры (они уже в фильтрах)
        cleaned_query = re.sub(r'\d+', '', query)
        
        # Добавляем контекст пользователя
        if user_context.get("preferences"):
            pref_texts = [p.get("memory_text", "") for p in user_context["preferences"][:3]]
            if pref_texts:
                cleaned_query += " " + " ".join(pref_texts)
        
        return cleaned_query.strip()
    
    async def _merge_search_results(
        self,
        es_results: List[Dict[str, Any]],
        vector_results: List[Dict[str, Any]],
        user_context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Объединяет и переранжирует результаты из разных источников"""
        # Собираем все результаты
        all_results = {}
        
        # Добавляем результаты Elasticsearch (приоритет выше)
        for result in es_results:
            car_id = result.get("id")
            if car_id:
                result["combined_score"] = result.get("score", 0.0) * 1.2  # Бонус за точный поиск
                if "sources" not in result:
                    result["sources"] = []
                all_results[car_id] = result
        
        # Добавляем результаты векторного поиска
        for result in vector_results:
            car_id = result.get("id")
            if car_id:
                if car_id in all_results:
                    # Объединяем результаты
                    all_results[car_id]["combined_score"] = max(
                        all_results[car_id]["combined_score"],
                        result.get("score", 0.0)
                    )
                    # Объединяем источники
                    if "sources" not in all_results[car_id]:
                        all_results[car_id]["sources"] = []
                    if "vector" not in all_results[car_id]["sources"]:
                        all_results[car_id]["sources"].append("vector")
                else:
                    result["combined_score"] = result.get("score", 0.0)
                    if "sources" not in result:
                        result["sources"] = []
                    all_results[car_id] = result
        
        # Сортируем по combined_score
        sorted_results = sorted(
            all_results.values(),
            key=lambda x: x.get("combined_score", 0.0),
            reverse=True
        )
        
        return sorted_results[:20]  # Возвращаем топ-20
    
    def _car_to_dict(self, car_obj) -> Dict[str, Any]:
        """Преобразует объект Car/UsedCar в словарь"""
        if not car_obj:
            return {}
        
        result = {
            "id": car_obj.id,
            "mark": car_obj.mark,
            "model": car_obj.model,
            "price": car_obj.price,
            "city": car_obj.city,
            "manufacture_year": car_obj.manufacture_year,
        }
        
        # Добавляем специфичные поля
        if hasattr(car_obj, "mileage"):
            result["mileage"] = car_obj.mileage
            result["type"] = "used_car"
        else:
            result["type"] = "car"
        
        return result
    
    async def _knowledge_search(
        self,
        query: str,
        user_context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Поиск в базе знаний (статьи, документы)"""
        # Упрощенная версия - в полной реализации будет RAG поиск
        return []
    
    def _rank_and_merge_results(
        self,
        results: Dict[str, List[Dict[str, Any]]],
        intent_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Переранжирует и объединяет результаты"""
        cars = results.get("cars", [])
        knowledge = results.get("knowledge", [])
        
        return {
            "results": cars,
            "knowledge": knowledge,
            "total": len(cars),
            "search_type": intent_analysis.get("search_type", "hybrid"),
            "confidence": self._calculate_confidence(cars, intent_analysis)
        }
    
    def _calculate_confidence(
        self,
        results: List[Dict[str, Any]],
        intent_analysis: Dict[str, Any]
    ) -> float:
        """Вычисляет уверенность в результатах"""
        if not results:
            return 0.0
        
        # Базовая уверенность
        confidence = 0.5
        
        # Бонус за точный поиск
        if intent_analysis.get("is_exact"):
            confidence += 0.3
        
        # Бонус за количество результатов
        if len(results) >= 5:
            confidence += 0.2
        elif len(results) >= 3:
            confidence += 0.1
        
        # Бонус за высокие оценки
        if results and results[0].get("combined_score", 0) > 0.8:
            confidence += 0.1
        
        return min(confidence, 1.0)

