"""
Сервис для генерации проактивных предложений
"""
from typing import List, Dict, Any
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType
from services.dialogue_history_service import DialogueHistoryService


class ProactiveAssistantService:
    """Генерация проактивных предложений для углубления диалога"""
    
    def __init__(self):
        self.orchestrator = AIModelOrchestratorService()
    
    async def generate_proactive_suggestions(
        self,
        history: DialogueHistoryService,
        current_topic: str,
        user_interests: List[str]
    ) -> List[Dict]:
        """
        Генерирует проактивные предложения на основе истории диалога
        
        Returns:
            List[Dict] с предложениями:
            - text: текст предложения
            - type: тип предложения ("finance", "test_drive", "trade_in", "similar", "related")
            - relevance: релевантность (0.0-1.0)
        """
        try:
            # Анализируем историю для выявления нераскрытых аспектов
            all_messages = history.get_all_messages()
            covered_topics = history.get_already_covered_topics()
            
            # Определяем, какие аспекты еще не раскрыты
            uncovered_aspects = self._identify_uncovered_aspects(
                all_messages,
                covered_topics,
                current_topic
            )
            
            # Генерируем предложения через LLM
            suggestions = await self._generate_suggestions_with_llm(
                current_topic,
                uncovered_aspects,
                user_interests,
                covered_topics
            )
            
            # Если LLM не сгенерировал, используем простые шаблоны
            if not suggestions:
                suggestions = self._generate_simple_suggestions(
                    current_topic,
                    uncovered_aspects
                )
            
            return suggestions
            
        except Exception as e:
            print(f"⚠️ Ошибка генерации проактивных предложений: {e}")
            return []
    
    def _identify_uncovered_aspects(
        self,
        messages: List[Dict],
        covered_topics: List[str],
        current_topic: str
    ) -> List[str]:
        """Определяет нераскрытые аспекты темы"""
        uncovered = []
        
        # Проверяем, какие аспекты уже обсуждались
        all_content = " ".join([str(msg.get("content", "")) for msg in messages]).lower()
        
        aspects = {
            "finance": ["кредит", "лизинг", "рассрочка", "финансирование", "платеж"],
            "test_drive": ["тест-драйв", "пробная поездка", "прокат"],
            "trade_in": ["trade-in", "обмен", "сдать", "выкуп"],
            "warranty": ["гарантия", "сервис", "обслуживание"],
            "options": ["опции", "комплектация", "дополнительно"],
            "delivery": ["доставка", "транспортировка", "перевозка"]
        }
        
        for aspect, keywords in aspects.items():
            if not any(keyword in all_content for keyword in keywords):
                uncovered.append(aspect)
        
        return uncovered
    
    async def _generate_suggestions_with_llm(
        self,
        current_topic: str,
        uncovered_aspects: List[str],
        user_interests: List[str],
        covered_topics: List[str]
    ) -> List[Dict]:
        """Генерирует предложения через LLM"""
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.PROACTIVE_SUGGESTIONS
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            import json
            
            prompt = f"""Ты - проактивный ассистент автосалона. Сгенерируй 2-3 проактивных предложения для клиента.

ТЕКУЩАЯ ТЕМА: {current_topic}
ОБСУЖДЕННЫЕ ТЕМЫ: {', '.join(covered_topics[:5]) if covered_topics else "Нет"}
ИНТЕРЕСЫ КЛИЕНТА: {', '.join(user_interests[:5]) if user_interests else "Не определены"}
НЕРАСКРЫТЫЕ АСПЕКТЫ: {', '.join(uncovered_aspects) if uncovered_aspects else "Все раскрыто"}

Сгенерируй предложения, которые:
1. Релевантны текущей теме
2. Помогают углубить диалог
3. Предлагают полезные дополнительные услуги
4. Не повторяют уже обсужденное

Типы предложений:
- finance: финансирование, кредит, лизинг
- test_drive: тест-драйв
- trade_in: обмен автомобиля
- similar: похожие варианты
- related: связанные темы

Ответ в формате JSON:
{{
    "suggestions": [
        {{
            "text": "Текст предложения",
            "type": "finance|test_drive|trade_in|similar|related",
            "relevance": 0.85
        }}
    ]
}}

ВАЖНО: Используй двойные фигурные скобки {{}} для JSON структуры в ответе."""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты генерируешь проактивные предложения для клиентов автосалона. Возвращаешь JSON."),
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
                    return result.get("suggestions", [])
            except Exception as e:
                print(f"⚠️ Ошибка парсинга предложений: {e}")
            
            return []
            
        except Exception as e:
            print(f"⚠️ Ошибка генерации предложений через LLM: {e}")
            return []
    
    def _generate_simple_suggestions(
        self,
        current_topic: str,
        uncovered_aspects: List[str]
    ) -> List[Dict]:
        """Генерирует простые предложения без LLM"""
        suggestions = []
        
        # Шаблоны предложений
        templates = {
            "finance": {
                "text": "Может быть, вас также заинтересуют программы кредитования или лизинга?",
                "type": "finance",
                "relevance": 0.7
            },
            "test_drive": {
                "text": "Хотите записаться на тест-драйв?",
                "type": "test_drive",
                "relevance": 0.8
            },
            "trade_in": {
                "text": "Интересует ли вас программа trade-in (обмен вашего автомобиля)?",
                "type": "trade_in",
                "relevance": 0.6
            },
            "warranty": {
                "text": "Хотите узнать о гарантийном обслуживании?",
                "type": "related",
                "relevance": 0.5
            },
            "options": {
                "text": "Может быть, вас заинтересуют дополнительные опции и комплектации?",
                "type": "related",
                "relevance": 0.6
            }
        }
        
        # Добавляем предложения для нераскрытых аспектов
        for aspect in uncovered_aspects[:3]:  # Максимум 3 предложения
            if aspect in templates:
                suggestions.append(templates[aspect])
        
        # Если нет нераскрытых аспектов, предлагаем общие темы
        if not suggestions:
            if "поиск" in current_topic.lower():
                suggestions.append({
                    "text": "Хотите узнать о программах финансирования?",
                    "type": "finance",
                    "relevance": 0.6
                })
        
        return suggestions


