"""
Сервис для многоуровневого управления контекстом диалога
"""
from typing import Dict, Optional
from services.dialogue_history_service import DialogueHistoryService


class ContextManagerService:
    """Многоуровневое управление контекстом диалога"""
    
    def get_context_strategy(
        self,
        relation_type: str,
        confidence: float
    ) -> Dict:
        """
        Выбирает стратегию контекста в зависимости от типа связи
        
        Returns:
            Dict с параметрами стратегии:
            - context_level: "recent", "topic", "session", "summary"
            - max_messages: количество сообщений
            - include_summary: включать ли резюме
        """
        strategies = {
            "continuation": {
                "context_level": "topic",
                "max_messages": 10,
                "include_summary": False
            },
            "clarification": {
                "context_level": "recent",
                "max_messages": 6,
                "include_summary": False
            },
            "new_topic": {
                "context_level": "recent",
                "max_messages": 3,
                "include_summary": True
            },
            "topic_change": {
                "context_level": "recent",
                "max_messages": 5,
                "include_summary": True
            }
        }
        
        strategy = strategies.get(relation_type, strategies["new_topic"])
        
        # Адаптируем стратегию в зависимости от уверенности
        if confidence < 0.5:
            # Низкая уверенность - используем больше контекста
            strategy["max_messages"] = min(strategy["max_messages"] + 3, 15)
            strategy["include_summary"] = True
        
        return strategy
    
    def prepare_context(
        self,
        history: DialogueHistoryService,
        strategy: Dict,
        current_topic: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Подготавливает контекст разных уровней
        
        Returns:
            Dict с ключами:
            - recent: последние сообщения
            - topic: сообщения по теме
            - summary: резюме диалога
        """
        context = {}
        
        context_level = strategy.get("context_level", "recent")
        max_messages = strategy.get("max_messages", 6)
        include_summary = strategy.get("include_summary", False)
        
        # Получаем контекст в зависимости от уровня
        if context_level == "recent":
            context["recent"] = history.get_recent_context(max_messages)
        elif context_level == "topic":
            context["topic"] = history.get_topic_context(current_topic)
            # Также добавляем недавние сообщения
            context["recent"] = history.get_recent_context(3)
        elif context_level == "session":
            context["recent"] = history.get_recent_context(max_messages)
            context["topic"] = history.get_topic_context(current_topic)
        
        # Добавляем резюме, если нужно
        if include_summary:
            context["summary"] = history.get_summary_context()
        
        return context
    
    def format_context_for_prompt(self, context: Dict[str, str]) -> str:
        """Форматирует контекст для включения в промпт"""
        parts = []
        
        if context.get("summary"):
            parts.append(f"КРАТКОЕ РЕЗЮМЕ ДИАЛОГА:\n{context['summary']}\n")
        
        if context.get("topic"):
            parts.append(f"КОНТЕКСТ ПО ТЕМЕ:\n{context['topic']}\n")
        
        if context.get("recent"):
            parts.append(f"ПОСЛЕДНИЕ СООБЩЕНИЯ:\n{context['recent']}")
        
        return "\n".join(parts) if parts else ""



