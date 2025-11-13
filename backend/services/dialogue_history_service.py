"""
Сервис для управления историей диалога
Интегрирован с существующей структурой Redis
"""
from typing import Dict, Any, List, Optional
import json
import time
# Отключено: определение темы через LLM
# from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType
from services.dialog_state_service import _init_redis_client


class DialogueHistoryService:
    """Управление историей диалога с определением тем и контекста"""
    
    def __init__(self, user_id: str, session_id: Optional[int] = None):
        self.user_id = user_id
        self.redis_client = _init_redis_client()
        # Отключено: определение темы через LLM
        # self.orchestrator = AIModelOrchestratorService()
        
        # Получаем или создаем session_id
        if session_id is None:
            self.session_id = self._get_current_session_id()
        else:
            self.session_id = session_id
        
        self.history_key = f"chat:history:{user_id}:{self.session_id}"
        self.topics_key = f"dialogue:topics:{user_id}:{self.session_id}"
        self.interests_key = f"dialogue:interests:{user_id}"
    
    def _get_current_session_id(self) -> int:
        """Получает текущую сессию пользователя"""
        try:
            session_id = self.redis_client.get(f"chat:current:{self.user_id}")
            if session_id:
                return int(session_id)
        except Exception:
            pass
        return 0
    
    def add_message(
        self,
        role: str,
        content: Any,
        questions_answers: Optional[List[Dict]] = None,
        topic: Optional[str] = None,
        emotion_data: Optional[Dict] = None
    ):
        """
        Добавляет сообщение в историю диалога
        
        Args:
            role: "user" или "assistant"
            content: Содержимое сообщения (строка или dict)
            questions_answers: Список вопросов-ответов (для assistant)
            topic: Тема сообщения
            emotion_data: Данные об эмоциях
        """
        try:
            message = {
                "role": role,
                "content": content if isinstance(content, str) else json.dumps(content),
                "timestamp": time.time(),
                "topic": topic,
                "emotion": emotion_data,
                "questions_answers": questions_answers or []
            }
            
            # Сохраняем в Redis
            self.redis_client.rpush(self.history_key, json.dumps(message))
            
            # Определяем тему, если не указана
            if not topic and role == "user":
                detected_topic = self.detect_topic(str(content))
                if detected_topic:
                    message["topic"] = detected_topic
                    # Обновляем сообщение с темой
                    self.redis_client.lset(
                        self.history_key,
                        -1,
                        json.dumps(message)
                    )
            
            # Обновляем интересы пользователя
            if topic:
                self._update_interests(topic)
            
        except Exception as e:
            print(f"⚠️ Ошибка добавления сообщения в историю: {e}")
    
    def get_recent_context(self, max_messages: int = 6) -> str:
        """Получает контекст последних сообщений"""
        try:
            items = self.redis_client.lrange(self.history_key, -max_messages, -1)
            context_parts = []
            
            for item in items:
                try:
                    msg = json.loads(item)
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    
                    if role == "user":
                        context_parts.append(f"Пользователь: {content}")
                    elif role == "assistant":
                        context_parts.append(f"Ассистент: {content}")
                except Exception:
                    continue
            
            return "\n".join(context_parts)
        except Exception:
            return ""
    
    def get_topic_context(self, topic: Optional[str] = None) -> str:
        """Получает контекст сообщений по теме"""
        try:
            items = self.redis_client.lrange(self.history_key, 0, -1)
            context_parts = []
            
            for item in items:
                try:
                    msg = json.loads(item)
                    msg_topic = msg.get("topic", "")
                    if topic is None or msg_topic == topic:
                        role = msg.get("role", "unknown")
                        content = msg.get("content", "")
                        
                        if role == "user":
                            context_parts.append(f"Пользователь: {content}")
                        elif role == "assistant":
                            context_parts.append(f"Ассистент: {content}")
                except Exception:
                    continue
            
            return "\n".join(context_parts)
        except Exception:
            return ""
    
    def get_summary_context(self) -> str:
        """Получает краткое резюме диалога"""
        try:
            items = self.redis_client.lrange(self.history_key, 0, -1)
            if not items:
                return ""
            
            # Собираем основные темы
            topics = set()
            user_messages = []
            
            for item in items:
                try:
                    msg = json.loads(item)
                    topic = msg.get("topic")
                    if topic:
                        topics.add(topic)
                    
                    if msg.get("role") == "user":
                        user_messages.append(msg.get("content", ""))
                except Exception:
                    continue
            
            summary = f"Темы диалога: {', '.join(list(topics)[:5])}\n"
            summary += f"Количество сообщений: {len(items)}\n"
            if user_messages:
                summary += f"Последний запрос: {user_messages[-1][:100]}"
            
            return summary
        except Exception:
            return ""
    
    def detect_topic(self, query: str) -> str:
        """Определяет тему запроса - УПРОЩЕНО (возвращает общую тему)"""
        # Отключено сложное определение темы через LLM
        # Возвращаем общую тему для всех запросов
        return "подбор автомобиля"
    
    def get_already_covered_topics(self) -> List[str]:
        """Получает уже обсужденные темы - УПРОЩЕНО (возвращает пустой список)"""
        # Отключено сложное определение тем
        return []
    
    def _update_interests(self, topic: str):
        """Обновляет интересы пользователя"""
        try:
            interests = self.get_user_interests()
            if topic not in interests:
                interests.append(topic)
                # Сохраняем только последние 20 интересов
                interests = interests[-20:]
                self.redis_client.set(
                    self.interests_key,
                    json.dumps(interests),
                    ex=86400 * 30  # 30 дней
                )
        except Exception:
            pass
    
    def get_user_interests(self) -> List[str]:
        """Получает интересы пользователя - УПРОЩЕНО (возвращает пустой список)"""
        # Отключено сложное определение интересов
        return []
    
    def get_all_messages(self) -> List[Dict[str, Any]]:
        """Получает все сообщения диалога"""
        try:
            items = self.redis_client.lrange(self.history_key, 0, -1)
            messages = []
            
            for item in items:
                try:
                    messages.append(json.loads(item))
                except Exception:
                    continue
            
            return messages
        except Exception:
            return []
    
    def clear_history(self):
        """Очищает историю диалога"""
        try:
            self.redis_client.delete(self.history_key)
        except Exception:
            pass



