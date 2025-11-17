"""
CarDealerAgent - единый агент для обработки запросов пользователей
Использует LangGraph для управления состоянием и координации всех инструментов
"""
from typing import Dict, Any, List, Optional, TypedDict, Annotated
import operator
from sqlalchemy.orm import Session

# Попытка импорта LangGraph
try:
    from langgraph.graph import StateGraph, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    print("⚠️ LangGraph не установлен. Установите: pip install langgraph")


class AgentState(TypedDict):
    """Состояние агента для LangGraph"""
    # Входные данные
    user_input: str
    user_id: str
    session_id: str
    chat_id: Optional[int]
    
    # Контекст диалога
    chat_history: List[dict]
    dialogue_context: dict  # Контекст диалога (не используем operator.add для dict)
    user_preferences: List[dict]
    
    # Поисковые результаты
    search_criteria: dict
    search_results: list  # Результаты поиска
    knowledge_results: list  # Результаты поиска в базе знаний
    
    # Состояние
    current_intent: str
    needs_clarification: bool
    clarification_questions: List[str]
    
    # Выходные данные
    response: str
    suggested_actions: List[str]
    memory_updates: List[dict]
    used_tools: List[str]
    
    # Метаданные
    related_articles: List[dict]
    related_documents: List[dict]
    related_cars: List[dict]
    related_used_cars: List[dict]
    sources_data: dict


class CarDealerAgent:
    """
    Единый агент для обработки запросов пользователей
    
    Заменяет множественные сервисы на один координирующий агент:
    - Анализирует намерение пользователя
    - Выбирает нужные инструменты
    - Координирует их работу
    - Генерирует согласованный ответ
    """
    
    def __init__(
        self,
        db_session: Session,
        memory_service=None,
        search_service=None,
        llm_service=None,
        sql_agent=None,
        parameter_extractor=None,
        proactive_service=None
    ):
        """
        Инициализация агента
        
        Args:
            db_session: SQLAlchemy сессия
            memory_service: UnifiedMemoryService
            search_service: UnifiedSearchService
            llm_service: Сервис для работы с LLM
            sql_agent: SQLAgentService (опционально)
            parameter_extractor: ParameterExtractionService (опционально)
            proactive_service: ProactiveSuggestionsService (опционально)
        """
        self.db = db_session
        self.memory = memory_service
        self.search = search_service
        self.llm = llm_service
        self.sql_agent = sql_agent
        self.parameter_extractor = parameter_extractor
        self.proactive_service = proactive_service
        
        self.graph = None
        if LANGGRAPH_AVAILABLE:
            try:
                self.graph = self._build_graph()
                print("✅ CarDealerAgent инициализирован с LangGraph")
            except Exception as e:
                print(f"⚠️ Ошибка инициализации графа: {e}")
                self.graph = None
        else:
            print("⚠️ LangGraph недоступен, используется упрощенная версия")
    
    def _build_graph(self):
        """Строит граф состояний LangGraph"""
        if not LANGGRAPH_AVAILABLE:
            return None
        
        workflow = StateGraph(AgentState)
        
        # Добавляем узлы
        workflow.add_node("analyze_intent", self.analyze_intent)
        workflow.add_node("extract_parameters", self.extract_parameters)
        workflow.add_node("search_cars", self.search_cars)
        workflow.add_node("search_knowledge", self.search_knowledge)
        workflow.add_node("sql_query", self.sql_query)
        workflow.add_node("extract_preferences", self.extract_preferences)
        workflow.add_node("generate_response", self.generate_response)
        workflow.add_node("update_memory", self.update_memory)
        
        # Маршрутизация
        workflow.set_entry_point("analyze_intent")
        
        # Условные переходы после анализа намерения
        workflow.add_conditional_edges(
            "analyze_intent",
            self.route_by_intent,
            {
                "car_search": "extract_parameters",
                "knowledge_query": "search_knowledge",
                "structured_query": "sql_query",
                "clarification": "generate_response",
                "general": "generate_response"
            }
        )
        
        # Переходы после извлечения параметров
        workflow.add_conditional_edges(
            "extract_parameters",
            self.route_after_extraction,
            {
                "search": "search_cars",
                "clarification": "generate_response"
            }
        )
        
        # Переходы после поиска
        workflow.add_edge("search_cars", "extract_preferences")
        workflow.add_edge("search_knowledge", "extract_preferences")
        workflow.add_edge("sql_query", "extract_preferences")
        workflow.add_edge("extract_preferences", "generate_response")
        workflow.add_edge("generate_response", "update_memory")
        workflow.add_edge("update_memory", END)
        
        return workflow.compile()
    
    async def analyze_intent(self, state: AgentState) -> AgentState:
        """Анализирует намерение пользователя"""
        user_input = state["user_input"].lower()
        
        # Простой анализ намерения (в полной версии будет LLM)
        if any(word in user_input for word in ["покажи", "найди", "ищу", "купить", "автомобиль", "машина"]):
            intent = "car_search"
        elif any(word in user_input for word in ["сколько", "количество", "статистика", "сколько у вас"]):
            intent = "structured_query"
        elif any(word in user_input for word in ["как", "что такое", "объясни", "расскажи"]):
            intent = "knowledge_query"
        elif any(word in user_input for word in ["да", "нет", "уточни", "подробнее"]):
            intent = "clarification"
        else:
            intent = "general"
        
        state["current_intent"] = intent
        state["needs_clarification"] = intent == "clarification"
        
        return state
    
    async def route_by_intent(self, state: AgentState) -> str:
        """Маршрутизация на основе намерения"""
        intent = state["current_intent"]
        
        if intent == "car_search":
            return "car_search"
        elif intent == "knowledge_query":
            return "knowledge_query"
        elif intent == "structured_query":
            return "structured_query"
        elif intent == "clarification":
            return "clarification"
        else:
            return "general"
    
    async def extract_parameters(self, state: AgentState) -> AgentState:
        """Извлекает параметры поиска из запроса"""
        user_input = state["user_input"]
        existing_criteria = state.get("search_criteria", {})
        dialogue_context = state.get("dialogue_context", {})
        
        # Используем ParameterExtractionService, если доступен
        if self.parameter_extractor:
            try:
                from services.parameter_extraction_service import ParameterExtractionService
                
                context = {
                    "previous_criteria": existing_criteria,
                    "user_preferences": state.get("user_preferences", [])
                }
                
                extracted = await self.parameter_extractor.extract_parameters(
                    query=user_input,
                    context=context
                )
                
                # Объединяем с существующими критериями
                merged = self.parameter_extractor.merge_criteria(
                    existing=existing_criteria,
                    new=extracted
                )
                
                state["search_criteria"] = merged
                return state
            
            except Exception as e:
                print(f"⚠️ Ошибка извлечения параметров через LLM: {e}")
                # Fallback на простой парсинг
        
        # Упрощенная версия (fallback)
        import re
        
        criteria = existing_criteria.copy()
        
        # Поиск цены
        price_match = re.search(r'(\d+)\s*(млн|миллион|тыс|тысяч)', user_input, re.IGNORECASE)
        if price_match:
            value = int(price_match.group(1))
            unit = price_match.group(2).lower()
            if "млн" in unit or "миллион" in unit:
                criteria["max_price"] = value * 1000000
            elif "тыс" in unit or "тысяч" in unit:
                criteria["max_price"] = value * 1000
        
        # Поиск года
        year_match = re.search(r'(\d{4})\s*год', user_input, re.IGNORECASE)
        if year_match:
            criteria["min_year"] = int(year_match.group(1))
        
        # Поиск марки
        brands = ["audi", "bmw", "mercedes", "ford", "toyota", "volkswagen"]
        for brand in brands:
            if brand in user_input.lower():
                criteria.setdefault("brands", []).append(brand.capitalize())
        
        state["search_criteria"] = criteria
        return state
    
    async def route_after_extraction(self, state: AgentState) -> str:
        """Маршрутизация после извлечения параметров"""
        criteria = state.get("search_criteria", {})
        
        # Проверяем, достаточно ли параметров для поиска
        if criteria.get("brands") or criteria.get("max_price") or criteria.get("min_year"):
            return "search"
        else:
            return "clarification"
    
    async def search_cars(self, state: AgentState) -> AgentState:
        """Поиск автомобилей через UnifiedSearchService"""
        if not self.search:
            state["search_results"] = []
            return state
        
        try:
            query = state["user_input"]
            criteria = state.get("search_criteria", {})
            user_context = state.get("dialogue_context", {})
            
            result = await self.search.intelligent_search(
                query=query,
                user_context=user_context,
                filters=criteria
            )
            
            state["search_results"] = result.get("results", [])
            state["used_tools"].append("unified_search")
            
        except Exception as e:
            print(f"⚠️ Ошибка поиска автомобилей: {e}")
            state["search_results"] = []
        
        return state
    
    async def search_knowledge(self, state: AgentState) -> AgentState:
        """Поиск в базе знаний"""
        # Упрощенная версия - в полной версии будет RAG поиск
        state["knowledge_results"] = []
        return state
    
    async def sql_query(self, state: AgentState) -> AgentState:
        """Выполнение SQL запроса через SQL Agent"""
        if not self.sql_agent:
            state["search_results"] = []
            return state
        
        try:
            # SQL Agent может не принимать user_id, проверяем сигнатуру
            import inspect
            sig = inspect.signature(self.sql_agent.process_question)
            if "user_id" in sig.parameters:
                result = await self.sql_agent.process_question(
                    state["user_input"],
                    user_id=state["user_id"]
                )
            else:
                result = await self.sql_agent.process_question(
                    state["user_input"]
                )
            
            if result.get("success"):
                state["search_results"] = result.get("data", [])
                state["used_tools"].append("sql_agent")
            else:
                state["search_results"] = []
        
        except Exception as e:
            print(f"⚠️ Ошибка SQL запроса: {e}")
            state["search_results"] = []
        
        return state
    
    async def extract_preferences(self, state: AgentState) -> AgentState:
        """Извлекает предпочтения из результатов поиска"""
        # Упрощенная версия - в полной версии будет извлечение через LLM
        state["memory_updates"] = []
        return state
    
    async def generate_response(self, state: AgentState) -> AgentState:
        """Генерирует финальный ответ"""
        search_results = state.get("search_results", [])
        user_input = state["user_input"]
        intent = state.get("current_intent", "")
        
        # Всегда пытаемся использовать LLM для лучших ответов
        try:
            from services.ai_service import AIService
            ai_service = AIService()
            use_llm = True
        except Exception as e:
            print(f"⚠️ AIService недоступен: {e}")
            ai_service = None
            use_llm = False
        
        # Используем LLM для генерации ответа, если доступен
        if use_llm and ai_service:
            try:
                
                # Формируем детальный контекст для генерации
                context_parts = []
                
                if search_results:
                    context_parts.append(f"Найдено {len(search_results)} автомобилей, соответствующих запросу:")
                    for i, result in enumerate(search_results[:5], 1):
                        data = result.get("data", {})
                        mark = data.get("mark", "Неизвестно")
                        model = data.get("model", "Неизвестно")
                        price = data.get("price", 0)
                        year = data.get("manufacture_year", "?")
                        city = data.get("city", "")
                        body_type = data.get("body_type", "")
                        fuel_type = data.get("fuel_type", "")
                        mileage = data.get("mileage")
                        
                        car_info = f"{i}. {mark} {model}"
                        if year:
                            car_info += f", {year} год"
                        if price:
                            car_info += f", {price:,} руб"
                        if city:
                            car_info += f", г. {city}"
                        if body_type:
                            car_info += f", {body_type}"
                        if fuel_type:
                            car_info += f", {fuel_type}"
                        if mileage:
                            car_info += f", пробег {mileage:,} км"
                        
                        context_parts.append(car_info)
                
                # Добавляем информацию о предпочтениях пользователя
                user_preferences = state.get("user_preferences", [])
                if user_preferences:
                    pref_text = "; ".join([p.get("memory_text", "") for p in user_preferences[:3]])
                    context_parts.append(f"\nУчитывая предпочтения пользователя: {pref_text}")
                
                # Добавляем информацию о критериях поиска
                search_criteria = state.get("search_criteria", {})
                if search_criteria:
                    criteria_parts = []
                    if search_criteria.get("brands"):
                        criteria_parts.append(f"марки: {', '.join(search_criteria['brands'])}")
                    if search_criteria.get("max_price"):
                        criteria_parts.append(f"бюджет до {search_criteria['max_price']:,} руб")
                    if search_criteria.get("min_year"):
                        criteria_parts.append(f"от {search_criteria['min_year']} года")
                    if criteria_parts:
                        context_parts.append(f"\nКритерии поиска: {', '.join(criteria_parts)}")
                
                context = "\n".join(context_parts) if context_parts else "Результаты поиска не найдены"
                
                # Улучшенный промпт для генерации ответа
                prompt = f"""
Запрос пользователя: "{user_input}"

{context}

Сформируй дружелюбный, информативный и привлекательный ответ на русском языке.

ТРЕБОВАНИЯ К ОТВЕТУ:
1. Если найдены автомобили:
   - Представь их кратко, но информативно
   - Укажи ключевые характеристики (марка, модель, год, цена, город)
   - Сделай ответ привлекательным и мотивирующим
   - Предложи следующие шаги (показать подробнее, сравнить и т.д.)

2. Если не найдено:
   - Вежливо сообщи об этом
   - Предложи уточнить критерии поиска
   - Предложи альтернативные варианты

3. Стиль:
   - Дружелюбный и профессиональный
   - Используй эмодзи для визуального оформления (🚗, 💰, 📍 и т.д.)
   - Будь конкретным и полезным
   - Не используй маркдаун форматирование, только текст

Сформируй ответ:
"""
                
                system_prompt = """Ты - профессиональный консультант по продаже автомобилей в автосалоне.
Твоя задача - помочь клиенту найти идеальный автомобиль.

Ты должен:
- Быть дружелюбным и профессиональным
- Предоставлять точную и полезную информацию
- Мотивировать клиента к действию
- Предлагать дополнительные услуги (кредит, рассрочка, обмен)
- Использовать эмодзи для визуального оформления

Отвечай на русском языке, будь конкретным и полезным."""
                
                # Используем функцию генерации из rag_service
                from services.rag_service import _generate_with_ai_settings
                
                # Объединяем system_prompt и prompt
                full_prompt = f"{system_prompt}\n\n{prompt}"
                
                response, _ = await _generate_with_ai_settings(
                    prompt=full_prompt,
                    deep_thinking_enabled=False
                )
                
                state["response"] = response
                return state
            
            except Exception as e:
                print(f"⚠️ Ошибка генерации ответа через LLM: {e}")
                # Fallback на простую генерацию
        
        # Улучшенная версия (fallback)
        if search_results:
            cars_info = []
            for r in search_results[:3]:
                data = r.get("data", {})
                mark = data.get("mark", "")
                model = data.get("model", "")
                price = data.get("price", 0)
                year = data.get("manufacture_year", "")
                city = data.get("city", "")
                
                car_desc = f"🚗 {mark} {model}"
                if year:
                    car_desc += f" {year} года"
                if price:
                    car_desc += f" - {price:,} руб"
                if city:
                    car_desc += f" (г. {city})"
                
                cars_info.append(car_desc)
            
            if cars_info:
                state["response"] = f"✅ Найдено {len(search_results)} автомобилей, соответствующих вашим критериям!\n\n" + \
                                  "Вот несколько вариантов:\n" + "\n".join(cars_info) + \
                                  "\n\n💡 Могу показать подробную информацию о любом из них или найти похожие варианты."
            else:
                state["response"] = f"✅ Найдено {len(search_results)} автомобилей. Могу показать подробную информацию."
        else:
            # Улучшенный ответ при отсутствии результатов
            search_criteria = state.get("search_criteria", {})
            suggestions = []
            
            if not search_criteria.get("brands"):
                suggestions.append("указать марку автомобиля")
            if not search_criteria.get("max_price"):
                suggestions.append("указать бюджет")
            if not search_criteria.get("min_year"):
                suggestions.append("указать желаемый год выпуска")
            
            suggestion_text = ""
            if suggestions:
                suggestion_text = f"\n\n💡 Рекомендую: {', '.join(suggestions)}."
            
            state["response"] = "🔍 К сожалению, по указанным критериям не удалось найти подходящие варианты." + \
                              suggestion_text + \
                              "\n\nПопробуйте изменить параметры поиска, и я найду для вас идеальный автомобиль!"
        
        return state
    
    async def update_memory(self, state: AgentState) -> AgentState:
        """Обновляет долговременную память"""
        if not self.memory:
            return state
        
        try:
            # Сохраняем ключевые факты из диалога
            memory_updates = state.get("memory_updates", [])
            
            for memory_data in memory_updates:
                await self.memory.save_memory(
                    user_id=state["user_id"],
                    memory_data=memory_data
                )
        
        except Exception as e:
            print(f"⚠️ Ошибка обновления памяти: {e}")
        
        return state
    
    async def process_message(
        self,
        user_input: str,
        user_id: str,
        session_id: str,
        chat_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Обрабатывает сообщение пользователя
        
        Args:
            user_input: Сообщение пользователя
            user_id: ID пользователя
            session_id: ID сессии
            chat_id: ID чата (опционально)
            
        Returns:
            Словарь с результатом обработки
        """
        # Получаем контекст пользователя
        user_context = {}
        if self.memory:
            try:
                user_context = await self.memory.get_user_context(user_id, user_input)
            except Exception as e:
                print(f"⚠️ Ошибка получения контекста: {e}")
        
        # Инициализируем состояние
        initial_state: AgentState = {
            "user_input": user_input,
            "user_id": user_id,
            "session_id": session_id,
            "chat_id": chat_id,
            "chat_history": user_context.get("history", []),
            "dialogue_context": user_context,
            "user_preferences": user_context.get("preferences", []),
            "search_criteria": user_context.get("inferred_criteria", {}),
            "search_results": [],
            "knowledge_results": [],
            "current_intent": "",
            "needs_clarification": False,
            "clarification_questions": [],
            "response": "",
            "suggested_actions": [],
            "memory_updates": [],
            "used_tools": [],
            "related_articles": [],
            "related_documents": [],
            "related_cars": [],
            "related_used_cars": [],
            "sources_data": {}
        }
        
        # Запускаем граф или упрощенную версию
        if self.graph:
            try:
                final_state = await self.graph.ainvoke(initial_state)
            except Exception as e:
                print(f"⚠️ Ошибка выполнения графа: {e}")
                final_state = await self._process_simple(initial_state)
        else:
            final_state = await self._process_simple(initial_state)
        
        # Генерируем проактивные предложения
        proactive_suggestions = {}
        if self.proactive_service:
            try:
                proactive_suggestions = await self.proactive_service.generate_suggestions(
                    user_query=user_input,
                    search_results=final_state.get("search_results", []),
                    user_context=user_context,
                    dialogue_history=final_state.get("chat_history", [])
                )
                
                # Добавляем предложения в suggested_actions
                suggested_actions = final_state.get("suggested_actions", [])
                if proactive_suggestions.get("next_steps"):
                    suggested_actions.extend(proactive_suggestions["next_steps"])
                final_state["suggested_actions"] = suggested_actions
            except Exception as e:
                print(f"⚠️ Ошибка генерации проактивных предложений: {e}")
        
        # Извлекаем автомобили из результатов поиска
        related_cars = []
        related_used_cars = []
        
        for result in final_state.get("search_results", []):
            # UnifiedSearchService возвращает словари с ключом "data"
            if isinstance(result, dict):
                data = result.get("data")
                car_id = result.get("id") or (data.get("id") if isinstance(data, dict) else None)
                car_type = result.get("type") or (data.get("type") if isinstance(data, dict) else "car")
                
                # Если data - это объект Car/UsedCar
                if data and hasattr(data, 'id'):
                    if hasattr(data, 'mileage') and data.mileage is not None:
                        related_used_cars.append(data)
                    else:
                        related_cars.append(data)
                # Если data - это словарь или есть car_id, загружаем из БД
                elif car_id and self.db_session:
                    from services.database_service import DatabaseService
                    db_service = DatabaseService(self.db_session)
                    
                    if car_type == "used_car":
                        used_car = db_service.get_used_car(car_id)
                        if used_car:
                            related_used_cars.append(used_car)
                    else:
                        car = db_service.get_car(car_id)
                        if car:
                            related_cars.append(car)
            # Если result - это уже объект Car/UsedCar
            elif hasattr(result, 'id'):
                if hasattr(result, 'mileage') and result.mileage is not None:
                    related_used_cars.append(result)
                else:
                    related_cars.append(result)
        
        # Убеждаемся, что response не пустой
        response_text = final_state.get("response", "")
        if not response_text or not response_text.strip():
            response_text = "Извините, не удалось сформировать ответ. Попробуйте переформулировать запрос."
        
        # Формируем результат
        # Убеждаемся, что chat_id присутствует
        result_chat_id = chat_id if chat_id else None
        
        return {
            "response": response_text,  # Всегда не пустой
            "related_cars": related_cars,
            "related_used_cars": related_used_cars,
            "related_articles": final_state.get("related_articles", []),
            "related_documents": final_state.get("related_documents", []),
            "suggested_actions": final_state.get("suggested_actions", []),
            "clarifying_questions": proactive_suggestions.get("clarifying_questions", []),
            "alternative_options": proactive_suggestions.get("alternative_options", []),
            "related_info": proactive_suggestions.get("related_info", []),
            "chat_id": result_chat_id,  # Может быть None, но API создаст новый
            "sources_data": {
                "cars": [{"id": c.id, "type": "car"} for c in related_cars],
                "used_cars": [{"id": c.id, "type": "used_car"} for c in related_used_cars],
                "articles": final_state.get("related_articles", []),
                "documents": final_state.get("related_documents", [])
            }
        }
    
    async def _process_simple(self, state: AgentState) -> AgentState:
        """Упрощенная обработка без графа"""
        # Последовательная обработка
        state = await self.analyze_intent(state)
        
        if state["current_intent"] == "car_search":
            state = await self.extract_parameters(state)
            state = await self.search_cars(state)
            state = await self.generate_response(state)
        elif state["current_intent"] == "structured_query":
            state = await self.sql_query(state)
            state = await self.generate_response(state)
        else:
            state = await self.generate_response(state)
        
        state = await self.update_memory(state)
        
        return state

