"""
ProactiveSuggestionsService - сервис для проактивных предложений
Анализирует контекст диалога и предлагает релевантные действия
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session


class ProactiveSuggestionsService:
    """
    Сервис для генерации проактивных предложений
    
    Анализирует:
    - Текущий запрос пользователя
    - Историю диалога
    - Результаты поиска
    - Предпочтения пользователя
    
    Предлагает:
    - Уточняющие вопросы
    - Альтернативные варианты
    - Дополнительную информацию
    - Следующие шаги
    """
    
    def __init__(self, db_session: Session, memory_service=None):
        """
        Инициализация сервиса
        
        Args:
            db_session: SQLAlchemy сессия
            memory_service: UnifiedMemoryService (опционально)
        """
        self.db = db_session
        self.memory = memory_service
    
    async def generate_suggestions(
        self,
        user_query: str,
        search_results: List[Dict[str, Any]] = None,
        user_context: Dict[str, Any] = None,
        dialogue_history: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Генерирует проактивные предложения
        
        Args:
            user_query: Текущий запрос пользователя
            search_results: Результаты поиска
            user_context: Контекст пользователя
            dialogue_history: История диалога
            
        Returns:
            Словарь с предложениями:
            - clarifying_questions: Уточняющие вопросы
            - alternative_options: Альтернативные варианты
            - next_steps: Следующие шаги
            - related_info: Связанная информация
        """
        suggestions = {
            "clarifying_questions": [],
            "alternative_options": [],
            "next_steps": [],
            "related_info": []
        }
        
        # Анализируем контекст
        query_lower = user_query.lower()
        has_results = search_results and len(search_results) > 0
        results_count = len(search_results) if search_results else 0
        
        # 1. Уточняющие вопросы (если запрос неполный)
        if not has_results or results_count == 0:
            suggestions["clarifying_questions"] = await self._generate_clarifying_questions(
                user_query, user_context
            )
        
        # 2. Альтернативные варианты (если результаты есть, но мало)
        if has_results and 0 < results_count < 5:
            suggestions["alternative_options"] = await self._generate_alternatives(
                user_query, search_results, user_context
            )
        
        # 3. Следующие шаги (на основе контекста)
        suggestions["next_steps"] = await self._generate_next_steps(
            user_query, search_results, user_context, dialogue_history
        )
        
        # 4. Связанная информация
        suggestions["related_info"] = await self._generate_related_info(
            user_query, search_results, user_context
        )
        
        return suggestions
    
    async def _generate_clarifying_questions(
        self,
        query: str,
        context: Dict[str, Any] = None
    ) -> List[str]:
        """Генерирует уточняющие вопросы"""
        questions = []
        query_lower = query.lower()
        
        # Проверяем, какие параметры отсутствуют
        has_brand = any(brand in query_lower for brand in ["audi", "bmw", "mercedes", "ford", "toyota", "марка"])
        has_price = any(word in query_lower for word in ["цена", "бюджет", "миллион", "тысяч", "руб"])
        has_year = any(word in query_lower for word in ["год", "новый", "подержанный"])
        has_body = any(word in query_lower for word in ["седан", "внедорожник", "универсал", "кузов"])
        
        if not has_brand:
            questions.append("Какая марка автомобиля вас интересует?")
        
        if not has_price:
            questions.append("Какой у вас бюджет?")
        
        if not has_year:
            questions.append("Какой год выпуска предпочтителен?")
        
        if not has_body and not has_brand:
            questions.append("Какой тип кузова вас интересует?")
        
        # Если ничего не найдено, предлагаем общие вопросы
        if not questions:
            questions.append("Можете уточнить критерии поиска?")
            questions.append("Что для вас наиболее важно при выборе автомобиля?")
        
        return questions[:3]  # Максимум 3 вопроса
    
    async def _generate_alternatives(
        self,
        query: str,
        results: List[Dict[str, Any]],
        context: Dict[str, Any] = None
    ) -> List[str]:
        """Генерирует альтернативные варианты"""
        alternatives = []
        
        if not results:
            return alternatives
        
        # Анализируем результаты
        brands_in_results = set()
        price_range = {"min": None, "max": None}
        
        for result in results:
            data = result.get("data", {})
            brand = data.get("mark")
            price = data.get("price")
            
            if brand:
                brands_in_results.add(brand)
            
            if price:
                if price_range["min"] is None or price < price_range["min"]:
                    price_range["min"] = price
                if price_range["max"] is None or price > price_range["max"]:
                    price_range["max"] = price
        
        # Предлагаем альтернативы
        if len(brands_in_results) == 1:
            brand = list(brands_in_results)[0]
            alternatives.append(f"Рассмотрите другие марки, похожие на {brand}")
        
        if price_range["min"] and price_range["max"]:
            if price_range["max"] - price_range["min"] < 500000:
                alternatives.append("Попробуйте расширить диапазон цен")
        
        # Предлагаем похожие варианты
        alternatives.append("Могу показать похожие варианты с другими параметрами")
        
        return alternatives[:3]
    
    async def _generate_next_steps(
        self,
        query: str,
        results: List[Dict[str, Any]] = None,
        context: Dict[str, Any] = None,
        history: List[Dict[str, Any]] = None
    ) -> List[str]:
        """Генерирует предложения следующих шагов"""
        steps = []
        
        if results and len(results) > 0:
            # Если есть результаты, предлагаем действия
            steps.append("Могу показать подробную информацию о любом автомобиле")
            steps.append("Могу сравнить несколько вариантов")
            
            # Проверяем, есть ли в истории вопросы о финансировании
            if history:
                history_text = " ".join([h.get("content", "") for h in history[-3:]])
                if "кредит" not in history_text.lower() and "рассрочка" not in history_text.lower():
                    steps.append("Могу рассчитать условия кредита или рассрочки")
        else:
            # Если результатов нет, предлагаем уточнить
            steps.append("Попробуйте изменить критерии поиска")
            steps.append("Могу помочь подобрать автомобиль по вашим требованиям")
        
        # Предлагаем сохранение поиска
        if context and context.get("preferences"):
            steps.append("Могу сохранить ваши предпочтения для будущих поисков")
        
        return steps[:3]
    
    async def _generate_related_info(
        self,
        query: str,
        results: List[Dict[str, Any]] = None,
        context: Dict[str, Any] = None
    ) -> List[str]:
        """Генерирует предложения связанной информации"""
        info = []
        query_lower = query.lower()
        
        # Предлагаем информацию на основе запроса
        if "отзыв" in query_lower or "рейтинг" in query_lower:
            info.append("Могу найти отзывы и рейтинги автомобилей")
        
        if "сравн" in query_lower:
            info.append("Могу сравнить характеристики нескольких моделей")
        
        if "финанс" in query_lower or "кредит" in query_lower:
            info.append("Могу рассчитать условия кредита или рассрочки")
        
        if "гарант" in query_lower or "сервис" in query_lower:
            info.append("Могу предоставить информацию о гарантии и сервисном обслуживании")
        
        # Общие предложения
        if not info:
            if results and len(results) > 0:
                info.append("Могу показать дополнительные характеристики автомобилей")
                info.append("Могу найти похожие варианты")
            else:
                info.append("Могу помочь с выбором автомобиля")
                info.append("Могу предоставить информацию о доступных моделях")
        
        return info[:2]
    
    def format_suggestions_for_response(self, suggestions: Dict[str, Any]) -> str:
        """
        Форматирует предложения для включения в ответ
        
        Args:
            suggestions: Словарь с предложениями
            
        Returns:
            Отформатированная строка с предложениями
        """
        parts = []
        
        if suggestions.get("clarifying_questions"):
            parts.append("💡 Уточняющие вопросы:")
            for q in suggestions["clarifying_questions"][:2]:
                parts.append(f"   • {q}")
        
        if suggestions.get("next_steps"):
            parts.append("\n📋 Что дальше:")
            for step in suggestions["next_steps"][:2]:
                parts.append(f"   • {step}")
        
        if suggestions.get("related_info"):
            parts.append("\nℹ️ Полезная информация:")
            for info in suggestions["related_info"][:2]:
                parts.append(f"   • {info}")
        
        return "\n".join(parts) if parts else ""

