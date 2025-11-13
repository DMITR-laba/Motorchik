"""Сервис для управления состоянием диалога пользователя"""
from typing import Dict, Any, Optional, List
import json
import redis
from app.core.config import settings


class _MemoryStorage:
    """In-memory хранилище для fallback когда Redis недоступен"""
    def __init__(self):
        self._data: Dict[str, str] = {}
        self._lists: Dict[str, List[str]] = {}
    
    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)
    
    def set(self, key: str, value: str, ex: Optional[int] = None):
        self._data[key] = value
        return True
    
    def delete(self, key: str):
        deleted = 0
        if key in self._data:
            del self._data[key]
            deleted += 1
        if key in self._lists:
            del self._lists[key]
            deleted += 1
        return deleted
    
    def rpush(self, key: str, value: str):
        """Добавляет элемент в конец списка"""
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].append(value)
        return len(self._lists[key])
    
    def lrange(self, key: str, start: int, end: int) -> List[str]:
        """Получает элементы списка"""
        if key not in self._lists:
            return []
        lst = self._lists[key]
        # Redis lrange: end=-1 означает конец списка
        if end == -1:
            end = len(lst) - 1
        return lst[start:end+1] if end >= start else []
    
    def llen(self, key: str) -> int:
        """Возвращает длину списка"""
        return len(self._lists.get(key, []))
    
    def ltrim(self, key: str, start: int, end: int):
        """Обрезает список"""
        if key not in self._lists:
            return True
        lst = self._lists[key]
        if end == -1:
            end = len(lst) - 1
        self._lists[key] = lst[start:end+1] if end >= start else []
        return True
    
    def keys(self, pattern: str) -> List[str]:
        """Возвращает ключи, соответствующие паттерну"""
        import fnmatch
        all_keys = list(self._data.keys()) + list(self._lists.keys())
        return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]


def _init_redis_client():
    """Инициализация Redis клиента с fallback"""
    try:
        client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True
        )
        client.ping()
        return client
    except Exception:
        return _MemoryStorage()


_redis_client = _init_redis_client()


class DialogStateService:
    """Управляет состоянием диалога пользователя (критерии поиска, текущие результаты и т.д.)"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.state_key = f"dialog:state:{user_id}"
        self.results_key = f"dialog:results:{user_id}"
        self.last_question_key = f"dialog:last_question:{user_id}"
    
    def get_state(self) -> Dict[str, Any]:
        """Получает текущее состояние диалога"""
        try:
            data = _redis_client.get(self.state_key)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return {
            "criteria": {},
            "mode": "search",  # search, compare, details
            "last_shown_cars": [],
            "current_question": None,
        }
    
    def save_state(self, state: Dict[str, Any]):
        """Сохраняет состояние диалога"""
        try:
            _redis_client.set(self.state_key, json.dumps(state), ex=3600)  # TTL 1 час
        except Exception:
            pass
    
    def update_criteria(self, criteria: Dict[str, Any]):
        """Обновляет критерии поиска"""
        state = self.get_state()
        state["criteria"].update(criteria)
        self.save_state(state)
    
    def clear_criteria(self):
        """Очищает все критерии (сброс поиска)"""
        state = self.get_state()
        state["criteria"] = {}
        state["last_shown_cars"] = []
        state["current_question"] = None
        self.save_state(state)
    
    def get_criteria(self) -> Dict[str, Any]:
        """Получает текущие критерии"""
        return self.get_state().get("criteria", {})
    
    def set_last_shown_cars(self, cars: List[Dict[str, Any]]):
        """Сохраняет последние показанные автомобили"""
        state = self.get_state()
        state["last_shown_cars"] = cars[:10]  # Сохраняем до 10 последних
        self.save_state(state)
    
    def get_last_shown_cars(self) -> List[Dict[str, Any]]:
        """Получает последние показанные автомобили"""
        return self.get_state().get("last_shown_cars", [])
    
    def set_current_question(self, question: str):
        """Устанавливает текущий вопрос, на который ждем ответ"""
        state = self.get_state()
        state["current_question"] = question
        self.save_state(state)
    
    def get_current_question(self) -> Optional[str]:
        """Получает текущий вопрос"""
        return self.get_state().get("current_question")
    
    def save_search_results(self, results: Dict[str, Any]):
        """Сохраняет результаты поиска"""
        try:
            _redis_client.set(self.results_key, json.dumps(results), ex=3600)
        except Exception:
            pass
    
    def get_search_results(self) -> Optional[Dict[str, Any]]:
        """Получает сохраненные результаты поиска"""
        try:
            data = _redis_client.get(self.results_key)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None


