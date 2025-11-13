"""
Сервис для динамического управления памятью диалога
"""
from typing import List, Dict, Any
import time


class MemoryManagerService:
    """Динамическое управление памятью диалога с сжатием"""
    
    def calculate_message_importance(self, message: Dict[str, Any]) -> float:
        """
        Рассчитывает важность сообщения для сохранения в памяти
        
        Returns:
            Оценка важности от 0.0 до 1.0
        """
        importance = 0.5  # Базовая важность
        
        # Увеличиваем важность для сообщений с темами
        if message.get("topic"):
            importance += 0.2
        
        # Увеличиваем важность для сообщений с вопросами-ответами
        if message.get("questions_answers"):
            importance += 0.15
        
        # Увеличиваем важность для сообщений с эмоциями
        if message.get("emotion"):
            emotion_data = message.get("emotion", {})
            if emotion_data.get("urgency") == "high":
                importance += 0.1
            if emotion_data.get("sentiment") in ["positive", "negative"]:
                importance += 0.05
        
        # Уменьшаем важность старых сообщений
        timestamp = message.get("timestamp", time.time())
        age_hours = (time.time() - timestamp) / 3600
        if age_hours > 24:
            importance *= 0.7
        elif age_hours > 12:
            importance *= 0.85
        
        return min(importance, 1.0)
    
    def compress_history(
        self,
        history: List[Dict[str, Any]],
        max_messages: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Сжимает историю, сохраняя важные сообщения
        
        Args:
            history: Полная история сообщений
            max_messages: Максимальное количество сообщений после сжатия
        
        Returns:
            Сжатая история с сохранением важных сообщений
        """
        if len(history) <= max_messages:
            return history
        
        # Рассчитываем важность каждого сообщения
        messages_with_importance = [
            (msg, self.calculate_message_importance(msg))
            for msg in history
        ]
        
        # Сортируем по важности (убывание)
        messages_with_importance.sort(key=lambda x: x[1], reverse=True)
        
        # Берем топ-N важных сообщений
        important_messages = [msg for msg, _ in messages_with_importance[:max_messages]]
        
        # Сохраняем порядок по времени для важных сообщений
        important_messages.sort(key=lambda x: x.get("timestamp", 0))
        
        # Добавляем последние сообщения (всегда важны)
        recent_messages = history[-5:]
        for msg in recent_messages:
            if msg not in important_messages:
                important_messages.append(msg)
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        compressed = []
        for msg in important_messages:
            msg_id = id(msg)  # Используем id для уникальности
            if msg_id not in seen:
                seen.add(msg_id)
                compressed.append(msg)
        
        return compressed
    
    def extract_key_entities(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Извлекает ключевые сущности из истории диалога
        
        Returns:
            Dict с ключевыми сущностями:
            - topics: список тем
            - interests: интересы пользователя
            - mentioned_brands: упомянутые марки
            - mentioned_models: упомянутые модели
        """
        entities = {
            "topics": set(),
            "interests": set(),
            "mentioned_brands": set(),
            "mentioned_models": set()
        }
        
        # Список популярных марок для извлечения
        popular_brands = [
            "toyota", "bmw", "mercedes", "audi", "volkswagen", "ford",
            "hyundai", "kia", "nissan", "honda", "mazda", "skoda",
            "chery", "omoda", "dongfeng", "hongqi", "jac", "geely",
            "haval", "changan", "belgee", "москвич"
        ]
        
        for msg in history:
            content = str(msg.get("content", "")).lower()
            
            # Извлекаем темы
            topic = msg.get("topic")
            if topic:
                entities["topics"].add(topic)
            
            # Извлекаем марки
            for brand in popular_brands:
                if brand in content:
                    entities["mentioned_brands"].add(brand)
            
            # Простое извлечение моделей (слова после марки)
            words = content.split()
            for i, word in enumerate(words):
                if word in popular_brands and i + 1 < len(words):
                    entities["mentioned_models"].add(words[i + 1])
        
        return {
            "topics": list(entities["topics"]),
            "interests": list(entities["interests"]),
            "mentioned_brands": list(entities["mentioned_brands"]),
            "mentioned_models": list(entities["mentioned_models"])
        }



