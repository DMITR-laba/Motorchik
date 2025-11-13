"""
Сервис для анализа связанности текущего запроса с историей диалога
"""
from typing import Tuple, Optional
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType
from services.dialogue_history_service import DialogueHistoryService


class RelationAnalyzerService:
    """Анализ связанности запросов с историей диалога"""
    
    def __init__(self):
        self.orchestrator = AIModelOrchestratorService()
    
    async def analyze_relation(
        self,
        current_query: str,
        dialogue_history: str,
        previous_topics: list
    ) -> Tuple[bool, str, float]:
        """
        Анализирует связанность текущего запроса с историей диалога
        
        Returns:
            Tuple[is_related, relation_type, confidence]
            relation_type: "continuation", "clarification", "new_topic", "topic_change"
        """
        if not dialogue_history and not previous_topics:
            return False, "new_topic", 1.0
        
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.RELATION_ANALYSIS
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            import json
            
            prompt = f"""Проанализируй связь текущего запроса пользователя с историей диалога.

ИСТОРИЯ ДИАЛОГА:
{dialogue_history[:1000] if dialogue_history else "История пуста"}

ПРЕДЫДУЩИЕ ТЕМЫ: {', '.join(previous_topics[:5]) if previous_topics else "Нет"}

ТЕКУЩИЙ ЗАПРОС: {current_query}

Определи:
1. Связан ли текущий запрос с историей диалога? (да/нет)
2. Тип связи:
   - "continuation" - продолжение той же темы
   - "clarification" - уточнение предыдущего запроса
   - "new_topic" - новая тема, не связанная с историей
   - "topic_change" - переход на другую тему
3. Уверенность в оценке (0.0-1.0)

Ответ в формате JSON:
{{
    "is_related": true/false,
    "relation_type": "continuation|clarification|new_topic|topic_change",
    "confidence": 0.85
}}"""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты анализируешь связь запросов в диалоге. Возвращаешь JSON с анализом."),
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
                    is_related = result.get("is_related", False)
                    relation_type = result.get("relation_type", "new_topic")
                    confidence = float(result.get("confidence", 0.5))
                    
                    return is_related, relation_type, confidence
            except Exception as e:
                print(f"⚠️ Ошибка парсинга ответа анализатора: {e}")
            
            # Fallback - простая эвристика
            return self._simple_relation_analysis(current_query, dialogue_history, previous_topics)
            
        except Exception as e:
            print(f"⚠️ Ошибка анализа связанности: {e}")
            return self._simple_relation_analysis(current_query, dialogue_history, previous_topics)
    
    def _simple_relation_analysis(
        self,
        current_query: str,
        dialogue_history: str,
        previous_topics: list
    ) -> Tuple[bool, str, float]:
        """Простой анализ связанности без LLM"""
        if not dialogue_history:
            return False, "new_topic", 1.0
        
        query_lower = current_query.lower()
        history_lower = dialogue_history.lower()
        
        # Проверяем наличие общих слов
        query_words = set(query_lower.split())
        history_words = set(history_lower.split())
        common_words = query_words & history_words
        
        # Убираем стоп-слова
        stop_words = {"и", "в", "на", "с", "по", "для", "как", "что", "это", "то", "а", "но"}
        common_words = common_words - stop_words
        
        if len(common_words) >= 2:
            # Есть связь
            if any(word in query_lower for word in ["еще", "также", "также", "продолжи", "далее"]):
                return True, "continuation", 0.8
            elif any(word in query_lower for word in ["уточни", "конкретнее", "подробнее", "какой", "какая"]):
                return True, "clarification", 0.7
            else:
                return True, "continuation", 0.6
        elif len(common_words) == 1:
            return True, "topic_change", 0.4
        else:
            return False, "new_topic", 0.7



