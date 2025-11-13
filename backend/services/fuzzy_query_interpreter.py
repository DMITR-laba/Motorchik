"""
Интерпретатор размытых запросов для преобразования качественных характеристик
в структурированные параметры поиска автомобилей
"""
from typing import Dict, Any, List, Optional
import json
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType
from services.langchain_llm_service import LangChainLLMService


class FuzzyQueryInterpreter:
    """Интерпретирует размытые запросы в структурированные параметры поиска"""
    
    def __init__(self):
        self.orchestrator = AIModelOrchestratorService()
        self.langchain_service = LangChainLLMService()
    
    async def interpret_fuzzy_query(
        self,
        user_query: str,
        dialogue_context: str = "",
        available_brands: Optional[List[str]] = None,
        available_categories: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Интерпретирует размытый запрос в структурированные параметры поиска
        
        Args:
            user_query: Запрос пользователя (например, "хороший семейный автомобиль")
            dialogue_context: Контекст диалога
            available_brands: Список доступных марок
            available_categories: Список доступных категорий
        
        Returns:
            Dict с интерпретированными параметрами, уверенностью и вопросами для уточнения
        """
        if not user_query or not user_query.strip():
            return {
                "interpreted_parameters": {},
                "confidence": 0.0,
                "reasoning": "Пустой запрос",
                "clarification_questions": ["Что именно вы ищете?"]
            }
        
        # Получаем LLM для интерпретации
        llm = await self.orchestrator.get_llm_for_task_async(
            task_type=TaskType.FUZZY_INTERPRETATION
        )
        
        # Формируем промпт
        prompt = self._create_interpretation_prompt(
            user_query=user_query,
            dialogue_context=dialogue_context,
            available_brands=available_brands or [],
            available_categories=available_categories or []
        )
        
        try:
            # Генерируем интерпретацию
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты - эксперт по подбору автомобилей. Интерпретируй размытые запросы клиентов в конкретные параметры для поиска."),
                ("human", prompt)
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            # Парсим JSON ответ
            result = self._parse_interpretation_response(response)
            
            return result
            
        except Exception as e:
            print(f"⚠️ Ошибка интерпретации запроса: {e}")
            # Fallback на базовую интерпретацию
            return self._fallback_interpretation(user_query, available_brands, available_categories)
    
    def _create_interpretation_prompt(
        self,
        user_query: str,
        dialogue_context: str,
        available_brands: List[str],
        available_categories: List[str]
    ) -> str:
        """Создает промпт для интерпретации"""
        
        brands_text = ", ".join(available_brands) if available_brands else "любые"
        categories_text = ", ".join(available_categories) if available_categories else "любые"
        
        prompt = f"""Интерпретируй размытый запрос клиента в конкретные параметры для поиска автомобилей.

ДОСТУПНЫЕ МАРКИ: {brands_text}
ДОСТУПНЫЕ КАТЕГОРИИ: {categories_text}

ЗАПРОС КЛИЕНТА: {user_query}
"""
        
        if dialogue_context:
            prompt += f"\nКОНТЕКСТ ДИАЛОГА: {dialogue_context}\n"
        
        prompt += """
Распознай в запросе:
- Бюджетные предпочтения (дешевый, дорогой, эконом-класс, премиум, до X млн, от X млн)
- Тип автомобиля (семейный, городской, для путешествий, бизнес-класс, спортивный)
- Предполагаемое использование (город, трасса, бездорожье, дальние поездки)
- Ключевые характеристики (экономичный, мощный, комфортный, надежный, безопасный, вместительный)
- Размер (компактный, средний, большой, внедорожник)
- Тип топлива (бензин, дизель, гибрид, электро)

Преобразуй в структурированные параметры поиска.

Ответ в формате JSON:
{{
    "interpreted_parameters": {{
        "max_price": число или null,
        "min_price": число или null,
        "category": "категория" или null,
        "fuel_type": "тип топлива" или null,
        "body_type": "тип кузова" или null,
        "keywords": "ключевые слова через запятую",
        "min_year": число или null,
        "max_year": число или null,
        "min_power": число или null,
        "max_power": число или null
    }},
    "confidence": 0.85,
    "reasoning": "обоснование интерпретации",
    "clarification_questions": ["вопрос 1", "вопрос 2"]
}}

Важно:
- confidence должен быть от 0.0 до 1.0
- Если уверенность < 0.5, добавь вопросы для уточнения
- Используй только доступные марки и категории
- Если марка/категория не указана явно, оставь null
"""
        
        return prompt
    
    def _parse_interpretation_response(self, response: str) -> Dict[str, Any]:
        """Парсит ответ LLM в структурированный формат"""
        try:
            # Пытаемся найти JSON в ответе
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                result = json.loads(json_str)
                
                # Валидация и нормализация
                if "interpreted_parameters" not in result:
                    result["interpreted_parameters"] = {}
                
                if "confidence" not in result:
                    result["confidence"] = 0.5
                
                if "reasoning" not in result:
                    result["reasoning"] = "Интерпретация выполнена"
                
                if "clarification_questions" not in result:
                    result["clarification_questions"] = []
                
                # Нормализуем параметры
                params = result["interpreted_parameters"]
                for key in ["max_price", "min_price", "min_year", "max_year", "min_power", "max_power"]:
                    if key in params and params[key] is not None:
                        try:
                            params[key] = float(params[key])
                        except (ValueError, TypeError):
                            params[key] = None
                
                # Очищаем null значения
                params = {k: v for k, v in params.items() if v is not None}
                result["interpreted_parameters"] = params
                
                return result
            else:
                # Не удалось найти JSON
                return self._create_fallback_result(response)
                
        except json.JSONDecodeError as e:
            print(f"⚠️ Ошибка парсинга JSON: {e}")
            return self._create_fallback_result(response)
        except Exception as e:
            print(f"⚠️ Ошибка обработки ответа: {e}")
            return self._create_fallback_result(response)
    
    def _create_fallback_result(self, response: str) -> Dict[str, Any]:
        """Создает fallback результат при ошибке парсинга"""
        return {
            "interpreted_parameters": {},
            "confidence": 0.3,
            "reasoning": f"Не удалось распарсить ответ: {response[:100]}",
            "clarification_questions": [
                "Какой бюджет вы рассматриваете?",
                "Какой тип автомобиля вам нужен?",
                "Для каких целей планируете использовать автомобиль?"
            ]
        }
    
    def _fallback_interpretation(
        self,
        user_query: str,
        available_brands: Optional[List[str]],
        available_categories: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Базовая интерпретация без LLM (fallback)"""
        query_lower = user_query.lower()
        params = {}
        
        # Простое извлечение ключевых слов
        keywords = []
        if "семейн" in query_lower:
            keywords.append("семейный")
            params["body_type"] = "внедорожник"  # По умолчанию для семейных
        if "городск" in query_lower:
            keywords.append("городской")
        if "экономичн" in query_lower or "эконом" in query_lower:
            keywords.append("экономичный")
        if "премиум" in query_lower or "премиальн" in query_lower:
            keywords.append("премиум")
        if "спортивн" in query_lower:
            keywords.append("спортивный")
        
        return {
            "interpreted_parameters": params,
            "confidence": 0.4,
            "reasoning": "Базовая интерпретация (fallback)",
            "clarification_questions": [
                "Какой бюджет вы рассматриваете?",
                "Какой тип кузова предпочитаете?",
                "Какой тип топлива вас интересует?"
            ],
            "keywords": ", ".join(keywords) if keywords else None
        }




