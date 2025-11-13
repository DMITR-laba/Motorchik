"""
Сервис для анализа поисковых намерений пользователя
"""
from typing import Dict, Any, List, Optional
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType


class CarSearchAnalyzerService:
    """Анализ поисковых намерений пользователя"""
    
    def __init__(self):
        self.orchestrator = AIModelOrchestratorService()
    
    async def analyze_search_intent(
        self,
        user_query: str,
        dialogue_history: str,
        current_topic: str,
        available_categories: List[str]
    ) -> Dict[str, Any]:
        """
        Анализирует поисковое намерение пользователя
        
        Returns:
            Dict с ключами:
            - needs_search: нужен ли поиск автомобилей
            - confidence: уверенность в необходимости поиска (0.0-1.0)
            - search_type: тип поиска ("new", "used", "both")
            - extracted_params: извлеченные параметры поиска
            - needs_finance: нужна ли информация о финансировании
            - reasoning: обоснование анализа
        """
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.SEARCH_INTENT_ANALYSIS
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            import json
            
            prompt = f"""Проанализируй запрос пользователя автосалона и определи, нужно ли выполнять поиск автомобилей.

ЗАПРОС: {user_query}
ТЕМА: {current_topic}
ИСТОРИЯ ДИАЛОГА: {dialogue_history[:500] if dialogue_history else "Нет"}
ДОСТУПНЫЕ КАТЕГОРИИ: {', '.join(available_categories[:10]) if available_categories else "Не указаны"}

Определи:
1. Нужен ли поиск автомобилей? (да/нет)
2. Уверенность в необходимости поиска (0.0-1.0)
3. Тип поиска: "new" (новые), "used" (подержанные), "both" (оба)
4. Извлеченные параметры поиска (марка, модель, цена, год, и т.д.)
5. Нужна ли информация о финансировании? (да/нет)

Ответ в формате JSON:
{{
    "needs_search": true/false,
    "confidence": 0.85,
    "search_type": "new|used|both",
    "extracted_params": {{
        "mark": "марка или null",
        "model": "модель или null",
        "min_price": число или null,
        "max_price": число или null,
        "min_year": число или null,
        "body_type": "категория или null"
    }},
    "needs_finance": true/false,
    "reasoning": "обоснование анализа"
}}"""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты анализируешь намерения пользователя автосалона. Возвращаешь JSON с анализом."),
                ("human", prompt)
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            # Парсим JSON
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                    return {
                        "needs_search": result.get("needs_search", False),
                        "confidence": float(result.get("confidence", 0.5)),
                        "search_type": result.get("search_type", "both"),
                        "extracted_params": result.get("extracted_params", {}),
                        "needs_finance": result.get("needs_finance", False),
                        "reasoning": result.get("reasoning", "")
                    }
            except Exception as e:
                print(f"⚠️ Ошибка парсинга ответа анализатора: {e}")
            
            # Fallback - простая эвристика
            return self._simple_search_intent_analysis(user_query, current_topic)
            
        except Exception as e:
            print(f"⚠️ Ошибка анализа поискового намерения: {e}")
            return self._simple_search_intent_analysis(user_query, current_topic)
    
    def _simple_search_intent_analysis(
        self,
        user_query: str,
        current_topic: str
    ) -> Dict[str, Any]:
        """Простой анализ намерения без LLM"""
        query_lower = user_query.lower()
        topic_lower = current_topic.lower()
        
        # Ключевые слова для поиска
        search_keywords = [
            "найти", "поиск", "хочу", "нужен", "ищу", "покажи", "найди",
            "автомобиль", "машина", "авто", "купить", "выбрать"
        ]
        
        needs_search = (
            any(keyword in query_lower for keyword in search_keywords) or
            "поиск" in topic_lower or "автомобиль" in topic_lower
        )
        
        # Определяем тип поиска
        search_type = "both"
        if "новый" in query_lower or "новые" in query_lower:
            search_type = "new"
        elif "подержанный" in query_lower or "б/у" in query_lower or "с пробегом" in query_lower:
            search_type = "used"
        
        # Проверяем финансирование
        finance_keywords = ["кредит", "лизинг", "рассрочка", "финансирование", "платеж"]
        needs_finance = any(keyword in query_lower for keyword in finance_keywords)
        
        return {
            "needs_search": needs_search,
            "confidence": 0.7 if needs_search else 0.3,
            "search_type": search_type,
            "extracted_params": {},
            "needs_finance": needs_finance,
            "reasoning": "Простой анализ на основе ключевых слов"
        }
    
    def should_perform_search(self, search_intent: Dict[str, Any]) -> bool:
        """
        Определяет, нужно ли выполнять поиск на основе анализа намерения
        
        Args:
            search_intent: Результат analyze_search_intent
        
        Returns:
            True если нужно выполнить поиск
        """
        needs_search = search_intent.get("needs_search", False)
        confidence = search_intent.get("confidence", 0.0)
        
        # Выполняем поиск, если нужно и уверенность >= 0.5
        return needs_search and confidence >= 0.5



