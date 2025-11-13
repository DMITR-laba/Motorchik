"""
Сервис для анализа запросов пользователей и определения их типа (точный/расплывчатый)
с генерацией параметров для расплывчатых компонентов
"""
import re
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class QueryType(Enum):
    """Тип запроса"""
    VAGUE = "vague"  # Расплывчатый
    SPECIFIC = "specific"  # Точный
    MIXED = "mixed"  # Смешанный


@dataclass
class QueryAnalysis:
    """Результат анализа запроса"""
    query_type: QueryType
    vague_components: List[str]
    specific_components: List[str]
    needs_clarification: bool
    clarification_questions: List[str]
    confidence: float


@dataclass
class GeneratedParameters:
    """Сгенерированные параметры для расплывчатого компонента"""
    vague_component: str
    sql_conditions: Dict[str, Any]
    explanation: str
    confidence: float


class QueryAnalyzerService:
    """Сервис для анализа запросов с использованием LLM"""
    
    def __init__(self, ai_service=None, langchain_service=None, model: str = None):
        """
        Инициализация сервиса анализа запросов
        
        Args:
            ai_service: Сервис для работы с AI (AIService)
            langchain_service: Сервис LangChain (опционально)
            model: Модель для использования (если не указана, используется codellama:34b)
        """
        self.ai_service = ai_service
        self.langchain_service = langchain_service
        self.model = model or "codellama:34b"  # Модель по умолчанию
        self.clarification_context = {}
        
        if model:
            logger.info(f"🔧 QueryAnalyzer использует модель: {model}")
        else:
            logger.info(f"🔧 QueryAnalyzer использует модель по умолчанию: {self.model}")
    
    async def analyze_query(self, user_query: str) -> QueryAnalysis:
        """
        Анализирует запрос с помощью LLM для определения типов компонентов
        
        Args:
            user_query: Запрос пользователя
            
        Returns:
            QueryAnalysis: Результат анализа
        """
        # logger.info(f"🔍 Анализ запроса: {user_query}")  # ОТКЛЮЧЕНО
        
        analysis_prompt = f"""Ты - эксперт по анализу пользовательских запросов для автомобильной базы данных. 
Твоя задача - определить, содержит ли запрос расплывчатые (vague) и/или точные (specific) компоненты.

РАСПЛЫВЧАТЫЕ КОМПОНЕНТЫ: субъективные описания, качественные характеристики, эмоциональные оценки
- "спортивный", "быстрый", "комфортный", "стильный", "элегантный"
- "что-то интересное", "похожий на...", "неплохой"
- "не слишком дорогой", "довольно мощный", "достаточно просторный"
- "красивый", "надежный", "экономичный"

ТОЧНЫЕ КОМПОНЕНТЫ: конкретные характеристики, числа, определенные значения
- "красный", "BMW", "2020 года", "тойота", "toyota", "Toyota"
- "мощность 150 л.с.", "цена до 50000", "до 5 млн"
- "автоматическая коробка", "дизельный двигатель", "автомат", "механика"
- "седан", "кроссовер", "бензин", "дизель"
- "Москва", "Санкт-Петербург"
- "пробег до 100000", "пробегом до 10000 км", "не старше 2013 года", "с пробегом"
- "подбери", "найди", "покажи" - это команды, НЕ расплывчатые компоненты!

Проанализируй этот запрос и определи тип компонентов: "{user_query}"

Верни ответ ТОЛЬКО в формате JSON (без дополнительного текста, без markdown):
{{
    "query_type": "vague|specific|mixed",
    "vague_components": ["список расплывчатых частей запроса"],
    "specific_components": ["список точных частей запроса"], 
    "needs_clarification": true/false,
    "clarification_questions": ["вопросы для уточнения если нужно"],
    "confidence": 0.85
}}

КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА: 
1. ТИП ЗАПРОСА:
   - Если запрос содержит только точные компоненты (марка, модель, год, цена, пробег, КПП, топливо, кузов) - query_type = "specific"
   - Если запрос содержит только расплывчатые описания БЕЗ конкретных параметров - query_type = "vague"
   - Если содержит и то, и другое - query_type = "mixed"

2. УТОЧНЕНИЕ (needs_clarification):
   - needs_clarification = true ТОЛЬКО если запрос ПОЛНОСТЬЮ расплывчатый БЕЗ ЛЮБЫХ конкретных параметров
   - Примеры запросов, требующих уточнения: "что-то интересное", "что-то спортивное", "подбери что-нибудь"
   - Если есть ХОТЯ БЫ ОДИН точный компонент (марка, модель, год, пробег, цена, КПП, топливо, кузов, город) - needs_clarification = false
   - Примеры НЕ требующих уточнения: "toyota с пробегом до 10000", "BMW 2020 года", "красный седан", "подбери автомобили toyota с пробегом до 10000 км"

3. РАСПЛЫВЧАТЫЕ КОМПОНЕНТЫ:
   - НЕ включай в vague_components команды: "подбери", "найди", "покажи", "ищу" - это команды, не расплывчатые описания!
   - НЕ включай в vague_components конкретные параметры: "toyota", "пробег", "10000" - это точные компоненты!

4. ТОЧНЫЕ КОМПОНЕНТЫ:
   - Включай марки: "toyota", "bmw", "mercedes" и т.д.
   - Включай параметры: "пробег до 10000", "не старше 2013", "цена до 5 млн"
   - Включай характеристики: "автомат", "механика", "бензин", "седан", "красный"
"""
        
        try:
            # Используем LangChain если доступен
            if self.langchain_service:
                response = await self._analyze_with_langchain(analysis_prompt)
            else:
                # Используем прямой API через ai_service
                response = await self._analyze_with_direct_api(analysis_prompt)
            
            # Парсим JSON ответ
            result = self._parse_json_response(response)
            
            # Если парсинг не удался, используем fallback
            if result is None:
                logger.warning("⚠️ Не удалось распарсить JSON, используем fallback анализ")
                return self._fallback_analysis(user_query)
            
            # Создаем анализ из результата
            analysis = QueryAnalysis(
                query_type=QueryType(result.get("query_type", "mixed")),
                vague_components=result.get("vague_components", []),
                specific_components=result.get("specific_components", []),
                needs_clarification=result.get("needs_clarification", False),
                clarification_questions=result.get("clarification_questions", []),
                confidence=float(result.get("confidence", 0.5))
            )
            
            # Дополнительная проверка: если есть точные компоненты, не требуем уточнения
            if analysis.specific_components and len(analysis.specific_components) > 0:
                analysis.needs_clarification = False
                # logger.info(f"✅ Обнаружены точные компоненты ({len(analysis.specific_components)}), уточнение не требуется")  # ОТКЛЮЧЕНО
            
            return analysis
            
        except Exception as e:
            logger.error(f"❌ Ошибка анализа запроса: {e}")
            # Fallback анализ
            return self._fallback_analysis(user_query)
    
    async def _analyze_with_langchain(self, prompt: str) -> str:
        """Анализ через LangChain"""
        try:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
            
            system_template = "Ты - эксперт по анализу пользовательских запросов. Отвечай ТОЛЬКО в формате JSON без дополнительного текста."
            user_template = "{prompt}"
            
            prompt_template = ChatPromptTemplate.from_messages([
                SystemMessagePromptTemplate.from_template(system_template),
                HumanMessagePromptTemplate.from_template(user_template)
            ])
            
            # Используем модель из настроек или по умолчанию
            llm = self.langchain_service.get_llm(self.model, None)
            chain = prompt_template | llm | StrOutputParser()
            
            result = await chain.ainvoke({"prompt": prompt})
            return result
        except Exception as e:
            logger.error(f"❌ Ошибка анализа через LangChain: {e}")
            # Fallback на прямой API
            return await self._analyze_with_direct_api(prompt)
    
    async def _analyze_with_direct_api(self, prompt: str) -> str:
        """Анализ через прямой API"""
        if not self.ai_service:
            raise Exception("AI service не доступен")
        
        # Используем Ollama для анализа
        from services.ollama_utils import find_working_ollama_url
        working_url = await find_working_ollama_url(timeout=2.0)
        if not working_url:
            raise Exception("Ollama недоступен")
        
        # Извлекаем имя модели (убираем префикс "ollama:" если есть)
        model_name = self.model.replace("ollama:", "") if self.model.startswith("ollama:") else self.model
        
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{working_url}/api/generate",
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 2048
                    }
                },
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
    
    def _parse_json_response(self, text: str) -> Dict:
        """Парсит JSON из ответа LLM"""
        try:
            # Очистка текста и поиск JSON
            cleaned_text = text.strip()
            
            # Удаляем возможные markdown блоки кода
            cleaned_text = re.sub(r'```json\s*', '', cleaned_text)
            cleaned_text = re.sub(r'```\s*', '', cleaned_text)
            
            # Ищем JSON объект
            json_match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                result = json.loads(json_str)
                
                # Проверяем и корректируем needs_clarification
                # Если есть точные компоненты - не требуем уточнения
                if result.get("specific_components") and len(result.get("specific_components", [])) > 0:
                    result["needs_clarification"] = False
                    # logger.info(f"✅ Обнаружены точные компоненты, уточнение не требуется")  # ОТКЛЮЧЕНО
                
                return result
            else:
                # Пытаемся прочитать весь текст как JSON
                result = json.loads(cleaned_text)
                
                # Проверяем и корректируем needs_clarification
                if result.get("specific_components") and len(result.get("specific_components", [])) > 0:
                    result["needs_clarification"] = False
                
                return result
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}\nТекст: {text[:200]}")
            # Используем fallback анализ
            return None  # Вернем None, чтобы использовать fallback
    
    def _fallback_analysis(self, user_query: str) -> QueryAnalysis:
        """Резервный анализ при ошибке LLM"""
        # Простая эвристика для fallback
        vague_keywords = ["спортивный", "быстрый", "комфортный", "стильный", "красивый", 
                         "надежный", "экономичный", "что-то", "похожий", "неплохой"]
        specific_keywords = ["bmw", "тойота", "toyota", "mercedes", "красный", "синий", "автомат", 
                           "механика", "бензин", "дизель", "седан", "кроссовер", "пробег", "пробегом",
                           "до", "не старше", "год", "года", "мощность", "цена", "москва", "санкт-петербург"]
        
        query_lower = user_query.lower()
        has_vague = any(kw in query_lower for kw in vague_keywords)
        has_specific = any(kw in query_lower for kw in specific_keywords)
        
        if has_vague and has_specific:
            query_type = QueryType.MIXED
        elif has_vague:
            query_type = QueryType.VAGUE
        else:
            query_type = QueryType.SPECIFIC
        
        # Уточнение требуется ТОЛЬКО если запрос полностью расплывчатый БЕЗ конкретных параметров
        needs_clarification = query_type == QueryType.VAGUE and not has_specific
        
        return QueryAnalysis(
            query_type=query_type,
            vague_components=[kw for kw in vague_keywords if kw in query_lower] if has_vague else [],
            specific_components=[kw for kw in specific_keywords if kw in query_lower] if has_specific else [],
            needs_clarification=needs_clarification,
            clarification_questions=["Уточните, какие характеристики автомобиля вам важны?"] if needs_clarification else [],
            confidence=0.5
        )
    
    async def generate_parameters(self, vague_components: List[str], 
                                 context: Dict = None) -> List[GeneratedParameters]:
        """
        Генерирует конкретные параметры для каждого расплывчатого компонента
        
        Args:
            vague_components: Список расплывчатых компонентов
            context: Контекст уточнений от пользователя
            
        Returns:
            List[GeneratedParameters]: Список сгенерированных параметров
        """
        if not vague_components:
            return []
        
        # logger.info(f"🔧 Генерация параметров для {len(vague_components)} расплывчатых компонентов")  # ОТКЛЮЧЕНО
        
        generated_params = []
        
        for component in vague_components:
            params = await self._generate_for_component(component, context)
            generated_params.append(params)
            # logger.info(f"✅ Сгенерировано для '{component}': {params.sql_conditions} (уверенность: {params.confidence})")  # ОТКЛЮЧЕНО
        
        return generated_params
    
    async def _generate_for_component(self, vague_component: str, context: Dict) -> GeneratedParameters:
        """Генерирует параметры для одного расплывчатого компонента"""
        
        generation_prompt = f"""Ты - эксперт по автомобилям. Твоя задача - преобразовать расплывчатое описание в конкретные параметры для SQL запроса.

ИНСТРУКЦИИ:
1. Проанализируй расплывчатое описание
2. Определи, какие конкретные характеристики автомобиля подходят под это описание
3. Сгенерируй параметры в виде условий для SQL WHERE
4. Объясни логику преобразования

ПРИМЕРЫ ПРЕОБРАЗОВАНИЯ:
- "спортивный" -> высокая мощность (power > 200), быстрый разгон, спортивный тип кузова (купе, седан)
- "комфортный" -> просторный салон, автоматическая коробка (gear_box_type LIKE '%автомат%' OR gear_box_type LIKE '%automatic%'), кондиционер
- "экономичный" -> низкий расход, доступная цена (price < 2000000), небольшой объем двигателя (engine_vol < 2000)
- "стильный" -> современный год (manufacture_year >= 2020), привлекательный цвет
- "надежный" -> не слишком старый (manufacture_year >= 2015), проверенный производитель

Преобразуй это расплывчатое описание в конкретные SQL-условия: "{vague_component}"

Контекст уточнений: {json.dumps(context, ensure_ascii=False) if context else "не предоставлен"}

Верни ответ ТОЛЬКО в формате JSON (без дополнительного текста, без markdown):
{{
    "vague_component": "{vague_component}",
    "sql_conditions": {{
        "field1": "value1",
        "field2": {{"min": 100, "max": 200}},
        "field3": ["option1", "option2"]
    }},
    "explanation": "логика преобразования на русском языке",
    "confidence": 0.9
}}

Используй только стандартные поля автомобильной БД:
- mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, driving_gear_type
- mileage (только для used_cars), power, engine_vol, color
- Для price используй числовые значения в рублях
- Для manufacture_year используй целые числа (год)
- Для mileage используй целые числа (километры)
- Для power используй числовые значения (лошадиные силы)
- Для engine_vol используй целые числа (кубические сантиметры, например 2000 = 2.0л)
"""
        
        try:
            # Используем LangChain если доступен
            if self.langchain_service:
                response = await self._generate_with_langchain(generation_prompt)
            else:
                # Используем прямой API
                response = await self._generate_with_direct_api(generation_prompt)
            
            # Парсим JSON ответ
            result = self._parse_json_response(response)
            
            return GeneratedParameters(
                vague_component=result.get("vague_component", vague_component),
                sql_conditions=result.get("sql_conditions", {}),
                explanation=result.get("explanation", ""),
                confidence=float(result.get("confidence", 0.5))
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка генерации параметров для '{vague_component}': {e}")
            return self._fallback_parameters(vague_component)
    
    async def _generate_with_langchain(self, prompt: str) -> str:
        """Генерация через LangChain"""
        try:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
            
            system_template = "Ты - эксперт по автомобилям. Отвечай ТОЛЬКО в формате JSON без дополнительного текста."
            user_template = "{prompt}"
            
            prompt_template = ChatPromptTemplate.from_messages([
                SystemMessagePromptTemplate.from_template(system_template),
                HumanMessagePromptTemplate.from_template(user_template)
            ])
            
            # Используем модель из настроек или по умолчанию
            llm = self.langchain_service.get_llm(self.model, None)
            chain = prompt_template | llm | StrOutputParser()
            
            result = await chain.ainvoke({"prompt": prompt})
            return result
        except Exception as e:
            logger.error(f"❌ Ошибка генерации через LangChain: {e}")
            # Fallback на прямой API
            return await self._generate_with_direct_api(prompt)
    
    async def _generate_with_direct_api(self, prompt: str) -> str:
        """Генерация через прямой API"""
        from services.ollama_utils import find_working_ollama_url
        working_url = await find_working_ollama_url(timeout=2.0)
        if not working_url:
            raise Exception("Ollama недоступен")
        
        # Извлекаем имя модели (убираем префикс "ollama:" если есть)
        model_name = self.model.replace("ollama:", "") if self.model.startswith("ollama:") else self.model
        
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{working_url}/api/generate",
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 2048
                    }
                },
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
    
    def _fallback_parameters(self, vague_component: str) -> GeneratedParameters:
        """Резервная генерация параметров"""
        # Простые эвристики для fallback
        component_lower = vague_component.lower()
        sql_conditions = {}
        
        if "спортивный" in component_lower or "быстрый" in component_lower:
            sql_conditions = {"power": {"min": 200}}
        elif "комфортный" in component_lower:
            sql_conditions = {"gear_box_type": ["автомат", "automatic"]}
        elif "экономичный" in component_lower:
            sql_conditions = {"price": {"max": 2000000}, "engine_vol": {"max": 2000}}
        elif "стильный" in component_lower or "красивый" in component_lower:
            sql_conditions = {"manufacture_year": {"min": 2020}}
        
        return GeneratedParameters(
            vague_component=vague_component,
            sql_conditions=sql_conditions,
            explanation="Автоматическая генерация параметров (fallback)",
            confidence=0.3
        )
    
    def combine_components(self, original_query: str,
                          specific_components: List[str],
                          generated_params: List[GeneratedParameters]) -> str:
        """
        Объединяет точные и сгенерированные компоненты в финальный запрос
        
        Args:
            original_query: Исходный запрос пользователя
            specific_components: Точные компоненты
            generated_params: Сгенерированные параметры
            
        Returns:
            str: Финальный объединенный запрос
        """
        if not generated_params:
            return original_query
        
        # Фильтруем параметры по уверенности
        confident_params = [p for p in generated_params if p.confidence > 0.5]
        
        if not confident_params:
            return original_query
        
        # Формируем дополнения к запросу
        additions = []
        for param in confident_params:
            conditions = param.sql_conditions
            if conditions:
                # Преобразуем условия в естественный язык
                conditions_text = self._conditions_to_text(conditions)
                if conditions_text:
                    additions.append(conditions_text)
        
        if additions:
            combined = f"{original_query}. {', '.join(additions)}"
            # logger.info(f"✅ Объединенный запрос: {combined}")  # ОТКЛЮЧЕНО
            return combined
        
        return original_query
    
    def _conditions_to_text(self, conditions: Dict[str, Any]) -> str:
        """Преобразует SQL условия в естественный язык"""
        parts = []
        
        for field, value in conditions.items():
            if isinstance(value, dict):
                if "min" in value:
                    if field == "price":
                        parts.append(f"цена от {value['min']:,} рублей")
                    elif field == "power":
                        parts.append(f"мощность от {value['min']} л.с.")
                    elif field == "manufacture_year":
                        parts.append(f"не старше {value['min']} года")
                    elif field == "mileage":
                        parts.append(f"пробег от {value['min']} км")
                
                if "max" in value:
                    if field == "price":
                        parts.append(f"цена до {value['max']:,} рублей")
                    elif field == "power":
                        parts.append(f"мощность до {value['max']} л.с.")
                    elif field == "manufacture_year":
                        parts.append(f"не новее {value['max']} года")
                    elif field == "mileage":
                        parts.append(f"пробег до {value['max']} км")
                    elif field == "engine_vol":
                        parts.append(f"объем двигателя до {value['max']} см³")
            
            elif isinstance(value, list):
                if field == "gear_box_type":
                    if "автомат" in str(value).lower() or "automatic" in str(value).lower():
                        parts.append("автоматическая коробка передач")
                    elif "механика" in str(value).lower() or "manual" in str(value).lower():
                        parts.append("механическая коробка передач")
                elif field == "body_type":
                    parts.append(f"кузов: {', '.join(value)}")
                elif field == "fuel_type":
                    parts.append(f"топливо: {', '.join(value)}")
            
            elif isinstance(value, str):
                parts.append(f"{field}: {value}")
        
        return ", ".join(parts) if parts else ""
    
    def provide_clarification(self, clarification_data: Dict):
        """Добавляет уточняющую информацию от пользователя"""
        self.clarification_context.update(clarification_data)
        logger.info(f"✅ Обновлен контекст уточнений: {self.clarification_context}")
    
    def reset_context(self):
        """Сбрасывает контекст уточнений"""
        self.clarification_context = {}
        logger.info("🔄 Контекст уточнений сброшен")

