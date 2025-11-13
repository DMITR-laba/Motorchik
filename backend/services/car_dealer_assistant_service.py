"""
Главный сервис ассистента автосалона
Объединяет все компоненты для обработки запросов клиентов
"""
from typing import Dict, Any, List, Optional
import time
from services.dialogue_history_service import DialogueHistoryService
from services.relation_analyzer_service import RelationAnalyzerService
from services.context_manager_service import ContextManagerService
from services.memory_manager_service import MemoryManagerService
# Отключены: анализ эмоций и проактивные предложения
# from services.emotion_analyzer_service import EmotionAnalyzerService
# from services.proactive_assistant_service import ProactiveAssistantService
from services.intelligent_search_service import IntelligentSearchService
from services.fuzzy_query_interpreter import FuzzyQueryInterpreter
from services.recommendation_service import RecommendationService
from services.finance_calculator_service import FinanceCalculatorService
from services.elasticsearch_service import ElasticsearchService
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType


class CarDealerAssistantService:
    """Главный сервис ассистента автосалона"""
    
    def __init__(self, user_id: str, session_id: Optional[int] = None):
        self.user_id = user_id
        self.session_id = session_id
        
        # Инициализируем сервисы
        self.history = DialogueHistoryService(user_id, session_id)
        self.relation_analyzer = RelationAnalyzerService()
        self.context_manager = ContextManagerService()
        self.memory_manager = MemoryManagerService()
        # Отключены: анализ эмоций и проактивные предложения
        # self.emotion_analyzer = EmotionAnalyzerService()
        # self.proactive_assistant = ProactiveAssistantService()
        self.intelligent_search = IntelligentSearchService()
        self.fuzzy_interpreter = FuzzyQueryInterpreter()
        self.recommendation_service = RecommendationService()
        self.finance_calculator = FinanceCalculatorService()
        self.es_service = ElasticsearchService()
        self.orchestrator = AIModelOrchestratorService()
    
    async def process_query(self, user_query: str) -> Dict[str, Any]:
        """
        Обрабатывает запрос пользователя
        
        Returns:
            Dict с результатами обработки:
            - user_query: исходный запрос
            - query_topic: тема запроса
            - is_related: связан ли с предыдущим диалогом
            - relation_type: тип связи
            - search_performed: был ли выполнен поиск
            - search_results: результаты поиска (если был)
            - clarifying_questions: уточняющие вопросы
            - proactive_suggestions: проактивные предложения
            - finance_calculation: финансовые расчеты (если запрошены)
            - response_time: время обработки
        """
        start_time = time.time()
        
        try:
            # 1. Анализ эмоций - ОТКЛЮЧЕН
            emotion_data = {
                "sentiment": "neutral",
                "urgency": "medium",
                "emotion": "neutral",
                "confidence": 0.5
            }
            
            # 2. Определение темы - упрощено (используем общую тему)
            query_topic = "подбор автомобиля"  # Упрощенное определение темы
            
            # 3. Анализ связанности с историей
            dialogue_history_text = self.history.get_recent_context(10)
            previous_topics = self.history.get_already_covered_topics()
            
            is_related, relation_type, relation_confidence = await self.relation_analyzer.analyze_relation(
                current_query=user_query,
                dialogue_history=dialogue_history_text,
                previous_topics=previous_topics
            )
            
            # 4. Подготовка контекста
            context_strategy = self.context_manager.get_context_strategy(
                relation_type=relation_type,
                confidence=relation_confidence
            )
            
            context = self.context_manager.prepare_context(
                history=self.history,
                strategy=context_strategy,
                current_topic=query_topic
            )
            
            # 5. Добавляем сообщение пользователя в историю
            self.history.add_message(
                role="user",
                content=user_query,
                topic=query_topic,
                emotion_data=emotion_data
            )
            
            # 6. Определяем, нужен ли поиск автомобилей
            search_performed = False
            search_results = None
            
            if self._should_perform_search(user_query, query_topic):
                # Интерпретируем размытый запрос, если нужно
                interpreted_params = await self._interpret_query_if_needed(
                    user_query,
                    context.get("recent", "")
                )
                
                # Выполняем интеллектуальный поиск
                search_results = await self.intelligent_search.search_with_intelligence(
                    initial_params=interpreted_params,
                    user_query=user_query,
                    dialogue_context=self.context_manager.format_context_for_prompt(context)
                )
                
                search_performed = True
            
            # 7. Генерация уточняющих вопросов
            clarifying_questions = await self._generate_clarifying_questions(
                user_query=user_query,
                query_topic=query_topic,
                search_results=search_results,
                emotion_data=emotion_data,
                context=context
            )
            
            # 8. Генерация проактивных предложений - ОТКЛЮЧЕНА
            proactive_suggestions = []
            
            # 9. Финансовые расчеты (если запрошены)
            finance_calculation = None
            if self._is_finance_query(user_query, query_topic):
                finance_calculation = await self._calculate_finance(user_query, search_results)
            
            # 10. Формируем ответ
            response = self._format_response(
                user_query=user_query,
                search_results=search_results,
                clarifying_questions=clarifying_questions,
                proactive_suggestions=proactive_suggestions,
                finance_calculation=finance_calculation,
                emotion_data=emotion_data
            )
            
            # 11. Сохраняем ответ ассистента в историю
            self.history.add_message(
                role="assistant",
                content=response,
                topic=query_topic,
                questions_answers=clarifying_questions
            )
            
            # 12. Сжимаем историю, если нужно
            all_messages = self.history.get_all_messages()
            if len(all_messages) > 50:
                compressed = self.memory_manager.compress_history(all_messages, max_messages=50)
                # Обновляем историю (упрощенная версия - в реальности нужно перезаписать в Redis)
            
            response_time = time.time() - start_time
            
            return {
                "user_query": user_query,
                "query_topic": query_topic,
                "is_related": is_related,
                "relation_type": relation_type,
                "relation_confidence": relation_confidence,
                "search_performed": search_performed,
                "search_results": search_results,
                "clarifying_questions": clarifying_questions,
                "proactive_suggestions": proactive_suggestions,
                "finance_calculation": finance_calculation,
                "response": response,
                "emotion_data": emotion_data,
                "response_time": round(response_time, 2)
            }
            
        except Exception as e:
            print(f"❌ Ошибка обработки запроса: {e}")
            return {
                "user_query": user_query,
                "error": str(e),
                "response": "Извините, произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз.",
                "response_time": time.time() - start_time
            }
    
    def _should_perform_search(self, query: str, topic: str) -> bool:
        """Определяет, нужно ли выполнять поиск автомобилей"""
        search_keywords = [
            "найти", "поиск", "хочу", "нужен", "ищу", "покажи", "найди",
            "автомобиль", "машина", "авто", "купить"
        ]
        
        query_lower = query.lower()
        topic_lower = topic.lower()
        
        # Если тема связана с поиском
        if "поиск" in topic_lower or "автомобиль" in topic_lower:
            return True
        
        # Если есть ключевые слова поиска
        if any(keyword in query_lower for keyword in search_keywords):
            return True
        
        return False
    
    async def _interpret_query_if_needed(
        self,
        user_query: str,
        dialogue_context: str
    ) -> Dict[str, Any]:
        """Интерпретирует размытый запрос, если нужно"""
        try:
            # Получаем доступные марки и категории
            available_brands = self._get_available_brands()
            available_categories = self._get_available_categories()
            
            # Интерпретируем запрос
            interpretation = await self.fuzzy_interpreter.interpret_fuzzy_query(
                user_query=user_query,
                dialogue_context=dialogue_context,
                available_brands=available_brands,
                available_categories=available_categories
            )
            
            # Используем интерпретированные параметры, если уверенность высокая
            if interpretation.get("confidence", 0) >= 0.7:
                return interpretation.get("interpreted_parameters", {})
            
            return {}
        except Exception as e:
            print(f"⚠️ Ошибка интерпретации запроса: {e}")
            return {}
    
    def _get_available_brands(self) -> List[str]:
        """Получает список доступных марок"""
        try:
            # Простой поиск для получения марок
            result = self.es_service.search_cars(limit=100)
            brands = set()
            
            for hit in result.get("hits", []):
                brand = hit.get("_source", {}).get("mark")
                if brand:
                    brands.add(brand)
            
            return list(brands)[:20]  # Возвращаем до 20 марок
        except Exception:
            return []
    
    def _get_available_categories(self) -> List[str]:
        """Получает список доступных категорий"""
        try:
            result = self.es_service.search_cars(limit=100)
            categories = set()
            
            for hit in result.get("hits", []):
                category = hit.get("_source", {}).get("body_type") or hit.get("_source", {}).get("category")
                if category:
                    categories.add(category)
            
            return list(categories)[:15]  # Возвращаем до 15 категорий
        except Exception:
            return []
    
    async def _generate_clarifying_questions(
        self,
        user_query: str,
        query_topic: str,
        search_results: Optional[Dict],
        emotion_data: Dict,
        context: Dict[str, str]
    ) -> List[Dict]:
        """Генерирует уточняющие вопросы"""
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.QUESTION_GENERATION
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            import json
            
            # Определяем, нужны ли вопросы
            if search_results and search_results.get("total", 0) > 0:
                # Если есть результаты, вопросы не критичны
                return []
            
            prompt = f"""Сгенерируй 2-3 уточняющих вопроса для клиента автосалона.

ЗАПРОС КЛИЕНТА: {user_query}
ТЕМА: {query_topic}
РЕЗУЛЬТАТЫ ПОИСКА: {"Найдено результатов" if search_results and search_results.get("total", 0) > 0 else "Результатов не найдено"}

Вопросы должны быть:
- Конкретными и полезными
- Помогать уточнить потребности клиента
- Адаптированы под тему запроса

Ответ в формате JSON:
{{
    "questions": ["вопрос 1", "вопрос 2", "вопрос 3"]
}}"""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты генерируешь уточняющие вопросы для клиентов автосалона. Возвращаешь JSON."),
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
                    questions = result.get("questions", [])
                    
                    # Адаптация тона вопросов под эмоции - ОТКЛЮЧЕНА
                    adjusted_questions = questions  # Используем вопросы без адаптации
                    
                    return [{"question": q} for q in adjusted_questions]
            except Exception as e:
                print(f"⚠️ Ошибка парсинга вопросов: {e}")
            
            return []
            
        except Exception as e:
            print(f"⚠️ Ошибка генерации вопросов: {e}")
            return []
    
    def _is_finance_query(self, query: str, topic: str) -> bool:
        """Определяет, является ли запрос финансовым"""
        finance_keywords = ["кредит", "лизинг", "рассрочка", "финансирование", "платеж", "взнос"]
        query_lower = query.lower()
        topic_lower = topic.lower()
        
        return (
            "финансирование" in topic_lower or
            any(keyword in query_lower for keyword in finance_keywords)
        )
    
    async def _calculate_finance(
        self,
        user_query: str,
        search_results: Optional[Dict]
    ) -> Optional[Dict[str, Any]]:
        """Выполняет финансовые расчеты"""
        try:
            # Извлекаем параметры из запроса или результатов поиска
            if search_results and search_results.get("results"):
                # Берем первый автомобиль из результатов
                first_car = search_results["results"][0]
                car_price = self._extract_price(first_car)
                
                if car_price:
                    # Стандартные параметры
                    down_payment_percent = 20.0
                    loan_term = 60
                    
                    # Пытаемся извлечь из запроса
                    query_lower = user_query.lower()
                    if "взнос" in query_lower or "первоначальный" in query_lower:
                        # Простое извлечение процента (упрощенно)
                        pass
                    
                    return self.finance_calculator.calculate_with_credit_offers(
                        car_price=car_price,
                        down_payment_percent=down_payment_percent,
                        loan_term=loan_term
                    )
        except Exception as e:
            print(f"⚠️ Ошибка расчета финансов: {e}")
        
        return None
    
    def _extract_price(self, car_data: Dict) -> Optional[float]:
        """Извлекает цену из данных автомобиля"""
        try:
            source = car_data.get("_source", {})
            price = source.get("price") or source.get("sale_price")
            
            if price:
                if isinstance(price, (int, float)):
                    return float(price)
                elif isinstance(price, str):
                    # Убираем пробелы и символы
                    price_clean = price.replace(" ", "").replace(",", ".").replace("₽", "")
                    try:
                        return float(price_clean)
                    except:
                        return None
        except Exception:
            pass
        return None
    
    def _format_response(
        self,
        user_query: str,
        search_results: Optional[Dict],
        clarifying_questions: List[Dict],
        proactive_suggestions: List[Dict],
        finance_calculation: Optional[Dict],
        emotion_data: Dict
    ) -> str:
        """Форматирует финальный ответ"""
        parts = []
        
        # Основной ответ на основе результатов поиска
        if search_results:
            if search_results.get("total", 0) > 0:
                total = search_results.get("total", 0)
                parts.append(f"Найдено {total} автомобилей, соответствующих вашему запросу.")
                
                if search_results.get("relaxation_applied"):
                    parts.append("Результаты найдены после небольшого расширения критериев поиска.")
            else:
                parts.append("К сожалению, по вашим критериям не найдено автомобилей.")
                
                if search_results.get("recommendations"):
                    parts.append("Рекомендую рассмотреть альтернативные варианты.")
        else:
            parts.append("Чем могу помочь?")
        
        # Финансовые расчеты
        if finance_calculation:
            best_offer = finance_calculation.get("best_offer")
            if best_offer:
                monthly = best_offer.get("monthly_payment", 0)
                parts.append(f"Ежемесячный платеж: {monthly:,.0f} руб.")
        
        # Уточняющие вопросы
        if clarifying_questions:
            parts.append("\nДля уточнения запроса:")
            for q in clarifying_questions[:2]:  # Максимум 2 вопроса
                parts.append(f"- {q.get('question', '')}")
        
        # Проактивные предложения
        if proactive_suggestions:
            parts.append("\nТакже могу предложить:")
            for suggestion in proactive_suggestions[:2]:  # Максимум 2 предложения
                parts.append(f"- {suggestion.get('text', '')}")
        
        return "\n".join(parts)



