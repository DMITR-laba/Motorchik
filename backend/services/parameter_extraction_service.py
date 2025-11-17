"""
ParameterExtractionService - извлечение параметров поиска через LLM
Использует структурированный вывод для точного извлечения критериев
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from app.core.config import settings


class CarSearchCriteria(BaseModel):
    """Структура критериев поиска автомобилей"""
    brands: Optional[List[str]] = None
    models: Optional[List[str]] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    body_types: Optional[List[str]] = None
    fuel_types: Optional[List[str]] = None
    gearbox_types: Optional[List[str]] = None
    drive_types: Optional[List[str]] = None
    min_power: Optional[int] = None
    max_power: Optional[int] = None
    cities: Optional[List[str]] = None
    must_have_features: Optional[List[str]] = None
    exclude_features: Optional[List[str]] = None
    exclude_brands: Optional[List[str]] = None
    urgency: Optional[str] = None  # "immediate", "soon", "exploring"
    budget_flexibility: Optional[str] = None  # "strict", "flexible", "premium"


class ParameterExtractionService:
    """
    Сервис для извлечения параметров поиска из естественного языка
    
    Использует LLM для структурированного извлечения критериев
    """
    
    def __init__(self, llm_service=None):
        """
        Инициализация сервиса
        
        Args:
            llm_service: Сервис для работы с LLM (опционально)
        """
        self.llm_service = llm_service
        self.system_prompt = self._create_system_prompt()
    
    def _create_system_prompt(self) -> str:
        """Создает системный промпт для извлечения параметров"""
        return """
Ты - экспертный ассистент по подбору автомобилей. Извлекай параметры из запросов пользователей.

Важные правила:
1. Цены: "3 миллиона" = 3000000, "полтора миллиона" = 1500000, "2 ляма" = 2000000
2. Года: "машина 2020 года" → min_year=2020, max_year=2020
   "после 2020" → min_year=2020
   "до 2020" → max_year=2020
3. Марки: нормализуй к английским названиям (Ауди → Audi, БМВ → BMW)
4. Неявные параметры: 
   - "семейный автомобиль" → body_types=["универсал", "внедорожник"]
   - "надежный" → brands=["Toyota", "Honda", "Lexus"]
5. Относительные параметры: 
   - "подешевле" → уменьшай max_price на 20%
   - "посвежее" → увеличивай min_year на 1-2 года
6. Исключения: "кроме BMW" → exclude_brands=["BMW"]
7. Срочность: "срочно", "быстро" → urgency="immediate"
8. Гибкость бюджета: "строго до 3 млн" → budget_flexibility="strict"

Отвечай ТОЛЬКО в формате JSON согласно схеме CarSearchCriteria.
"""
    
    async def extract_parameters(
        self,
        query: str,
        context: Dict[str, Any] = None
    ) -> CarSearchCriteria:
        """
        Извлекает параметры поиска из запроса
        
        Args:
            query: Запрос пользователя
            context: Контекст диалога (предыдущие критерии, история)
            
        Returns:
            CarSearchCriteria с извлеченными параметрами
        """
        # Обогащаем запрос контекстом
        enriched_query = self._enrich_with_context(query, context or {})
        
        # Извлекаем параметры через LLM или простой парсинг
        if self.llm_service:
            criteria = await self._call_llm_for_extraction(enriched_query)
        else:
            criteria = self._simple_extraction(query)
        
        return criteria
    
    def _enrich_with_context(self, query: str, context: Dict[str, Any]) -> str:
        """Обогащает запрос контекстом диалога"""
        context_parts = []
        
        if context.get("previous_criteria"):
            prev = context["previous_criteria"]
            if isinstance(prev, dict):
                parts = []
                if prev.get("brands"):
                    parts.append(f"марки: {', '.join(prev['brands'])}")
                if prev.get("max_price"):
                    parts.append(f"бюджет до {prev['max_price']} руб")
                if parts:
                    context_parts.append(f"Ранее обсуждали: {', '.join(parts)}")
        
        if context.get("rejected_cars"):
            rejected = context["rejected_cars"]
            if isinstance(rejected, list) and rejected:
                context_parts.append(f"Отклоненные варианты: {len(rejected)} автомобилей")
        
        if context_parts:
            return f"{query} [Контекст: {'; '.join(context_parts)}]"
        
        return query
    
    async def _call_llm_for_extraction(self, query: str) -> CarSearchCriteria:
        """Извлекает параметры через LLM"""
        try:
            from services.ai_service import AIService
            
            ai_service = AIService()
            
            prompt = f"""
Запрос пользователя: {query}

Извлеки параметры поиска. Учитывай:
- Числа и их контекст (цена, год, мощность)
- Неявные предпочтения ("надежный" → марки с хорошей репутацией)
- Относительные выражения ("подешевле", "посвежее")
- Исключения ("кроме BMW")

Верни JSON согласно схеме CarSearchCriteria.
"""
            
            # Используем структурированный вывод, если доступен
            if hasattr(ai_service, 'generate_structured'):
                response = await ai_service.generate_structured(
                    prompt=prompt,
                    system_prompt=self.system_prompt,
                    response_model=CarSearchCriteria
                )
                return response
            else:
                # Fallback: используем функцию генерации из rag_service
                from services.rag_service import _generate_with_ai_settings
                
                full_prompt = f"{self.system_prompt}\n\n{prompt}"
                response_text, _ = await _generate_with_ai_settings(
                    prompt=full_prompt,
                    deep_thinking_enabled=False
                )
                return self._parse_json_response(response_text)
        
        except Exception as e:
            print(f"⚠️ Ошибка извлечения параметров через LLM: {e}")
            return self._simple_extraction(query)
    
    def _parse_json_response(self, response_text: str) -> CarSearchCriteria:
        """Парсит JSON из текстового ответа LLM"""
        import json
        import re
        
        try:
            # Пытаемся найти JSON в ответе
            json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                return CarSearchCriteria(**data)
        except Exception as e:
            print(f"⚠️ Ошибка парсинга JSON: {e}")
        
        return CarSearchCriteria()
    
    def _simple_extraction(self, query: str) -> CarSearchCriteria:
        """Упрощенное извлечение параметров без LLM"""
        import re
        
        criteria = {}
        query_lower = query.lower()
        
        # Поиск цены
        price_patterns = [
            (r'(\d+)\s*(млн|миллион)', lambda m: int(m.group(1)) * 1000000),
            (r'(\d+)\s*(тыс|тысяч)', lambda m: int(m.group(1)) * 1000),
            (r'(\d+)\s*(лям|ляма)', lambda m: int(m.group(1)) * 1000000),
        ]
        
        for pattern, converter in price_patterns:
            match = re.search(pattern, query_lower)
            if match:
                criteria["max_price"] = converter(match)
                break
        
        # Поиск года
        year_match = re.search(r'(\d{4})\s*год', query_lower)
        if year_match:
            year = int(year_match.group(1))
            if "после" in query_lower or "с" in query_lower:
                criteria["min_year"] = year
            elif "до" in query_lower or "не старше" in query_lower:
                criteria["max_year"] = year
            else:
                criteria["min_year"] = year
                criteria["max_year"] = year
        
        # Поиск марки
        brands_map = {
            "audi": "Audi", "ауди": "Audi",
            "bmw": "BMW", "бмв": "BMW",
            "mercedes": "Mercedes", "мерседес": "Mercedes",
            "ford": "Ford", "форд": "Ford",
            "toyota": "Toyota", "тойота": "Toyota",
            "volkswagen": "Volkswagen", "фольксваген": "Volkswagen"
        }
        
        found_brands = []
        for key, brand in brands_map.items():
            if key in query_lower:
                found_brands.append(brand)
        
        if found_brands:
            criteria["brands"] = found_brands
        
        # Исключения
        exclude_match = re.search(r'кроме\s+(\w+)', query_lower)
        if exclude_match:
            exclude_brand = exclude_match.group(1).capitalize()
            criteria["exclude_brands"] = [exclude_brand]
        
        # Тип кузова
        if "седан" in query_lower:
            criteria["body_types"] = ["Седан"]
        elif "внедорожник" in query_lower or "джип" in query_lower:
            criteria["body_types"] = ["Внедорожник"]
        elif "универсал" in query_lower:
            criteria["body_types"] = ["Универсал"]
        
        # Привод
        if "полный" in query_lower or "4wd" in query_lower or "awd" in query_lower:
            criteria["drive_types"] = ["Полный", "4WD", "AWD"]
        
        return CarSearchCriteria(**criteria)
    
    def merge_criteria(
        self,
        existing: Dict[str, Any],
        new: CarSearchCriteria
    ) -> Dict[str, Any]:
        """
        Объединяет старые и новые критерии поиска
        
        Args:
            existing: Существующие критерии
            new: Новые критерии
            
        Returns:
            Объединенные критерии
        """
        merged = existing.copy() if existing else {}
        new_dict = new.model_dump(exclude_none=True)
        
        for key, value in new_dict.items():
            if value is not None:
                if isinstance(value, list) and key in merged and merged[key] is not None:
                    # Объединяем списки, убирая дубликаты
                    merged[key] = list(set(merged[key] + value))
                else:
                    merged[key] = value
        
        return merged

