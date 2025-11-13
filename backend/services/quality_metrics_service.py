"""
Сервис для сбора метрик качества работы системы
"""
from typing import Dict, Any, List, Optional
import time
from datetime import datetime
import json
from services.dialog_state_service import _init_redis_client


class QualityMetricsService:
    """Сбор и анализ метрик качества работы системы"""
    
    def __init__(self):
        self.redis_client = _init_redis_client()
        self.metrics_key = "quality:metrics"
        self.interactions_key = "quality:interactions"
    
    def log_interaction(
        self,
        relation_data: Dict[str, Any],
        questions: List[str],
        response_time: float,
        search_performed: bool = False,
        search_success: bool = False,
        user_satisfaction: Optional[float] = None
    ):
        """
        Логирует метрики взаимодействия
        
        Args:
            relation_data: Данные о связанности запроса
            questions: Список сгенерированных вопросов
            response_time: Время ответа в секундах
            search_performed: Был ли выполнен поиск
            search_success: Был ли поиск успешным
            user_satisfaction: Удовлетворенность пользователя (0.0-1.0, опционально)
        """
        try:
            interaction = {
                "timestamp": datetime.now().isoformat(),
                "relation_type": relation_data.get("relation_type", "unknown"),
                "relation_confidence": relation_data.get("confidence", 0.0),
                "questions_count": len(questions),
                "response_time": response_time,
                "search_performed": search_performed,
                "search_success": search_success,
                "user_satisfaction": user_satisfaction
            }
            
            # Сохраняем в Redis
            self.redis_client.rpush(
                self.interactions_key,
                json.dumps(interaction)
            )
            
            # Ограничиваем количество записей (храним последние 1000)
            length = self.redis_client.llen(self.interactions_key)
            if length > 1000:
                self.redis_client.ltrim(self.interactions_key, -1000, -1)
            
        except Exception as e:
            print(f"⚠️ Ошибка логирования метрик: {e}")
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Получает сводку метрик производительности
        
        Returns:
            Dict с метриками:
            - total_interactions: общее количество взаимодействий
            - avg_response_time: среднее время ответа
            - search_success_rate: процент успешных поисков
            - relation_types_distribution: распределение типов связи
            - avg_questions_per_interaction: среднее количество вопросов
        """
        try:
            items = self.redis_client.lrange(self.interactions_key, 0, -1)
            
            if not items:
                return {
                    "total_interactions": 0,
                    "avg_response_time": 0.0,
                    "search_success_rate": 0.0,
                    "relation_types_distribution": {},
                    "avg_questions_per_interaction": 0.0
                }
            
            total_interactions = len(items)
            total_response_time = 0.0
            search_performed_count = 0
            search_success_count = 0
            total_questions = 0
            relation_types = {}
            
            for item in items:
                try:
                    interaction = json.loads(item)
                    total_response_time += interaction.get("response_time", 0.0)
                    
                    if interaction.get("search_performed"):
                        search_performed_count += 1
                        if interaction.get("search_success"):
                            search_success_count += 1
                    
                    total_questions += interaction.get("questions_count", 0)
                    
                    relation_type = interaction.get("relation_type", "unknown")
                    relation_types[relation_type] = relation_types.get(relation_type, 0) + 1
                    
                except Exception:
                    continue
            
            avg_response_time = total_response_time / total_interactions if total_interactions > 0 else 0.0
            search_success_rate = (search_success_count / search_performed_count * 100) if search_performed_count > 0 else 0.0
            avg_questions = total_questions / total_interactions if total_interactions > 0 else 0.0
            
            return {
                "total_interactions": total_interactions,
                "avg_response_time": round(avg_response_time, 2),
                "search_success_rate": round(search_success_rate, 2),
                "relation_types_distribution": relation_types,
                "avg_questions_per_interaction": round(avg_questions, 2),
                "search_performed_count": search_performed_count,
                "search_success_count": search_success_count
            }
            
        except Exception as e:
            print(f"⚠️ Ошибка получения метрик: {e}")
            return {
                "total_interactions": 0,
                "avg_response_time": 0.0,
                "search_success_rate": 0.0,
                "relation_types_distribution": {},
                "avg_questions_per_interaction": 0.0,
                "error": str(e)
            }
    
    def log_model_usage(
        self,
        model_name: str,
        task_type: str,
        success: bool,
        response_time: float
    ):
        """Логирует использование модели"""
        try:
            usage_key = f"quality:model_usage:{model_name}"
            usage = {
                "timestamp": datetime.now().isoformat(),
                "task_type": task_type,
                "success": success,
                "response_time": response_time
            }
            
            self.redis_client.rpush(usage_key, json.dumps(usage))
            
            # Ограничиваем количество записей
            length = self.redis_client.llen(usage_key)
            if length > 500:
                self.redis_client.ltrim(usage_key, -500, -1)
                
        except Exception as e:
            print(f"⚠️ Ошибка логирования использования модели: {e}")
    
    def get_model_performance(self, model_name: str) -> Dict[str, Any]:
        """Получает метрики производительности модели"""
        try:
            usage_key = f"quality:model_usage:{model_name}"
            items = self.redis_client.lrange(usage_key, 0, -1)
            
            if not items:
                return {
                    "model_name": model_name,
                    "total_uses": 0,
                    "success_rate": 0.0,
                    "avg_response_time": 0.0
                }
            
            total_uses = len(items)
            success_count = 0
            total_response_time = 0.0
            
            for item in items:
                try:
                    usage = json.loads(item)
                    if usage.get("success"):
                        success_count += 1
                    total_response_time += usage.get("response_time", 0.0)
                except Exception:
                    continue
            
            return {
                "model_name": model_name,
                "total_uses": total_uses,
                "success_rate": round((success_count / total_uses * 100), 2) if total_uses > 0 else 0.0,
                "avg_response_time": round(total_response_time / total_uses, 2) if total_uses > 0 else 0.0
            }
            
        except Exception as e:
            print(f"⚠️ Ошибка получения метрик модели: {e}")
            return {
                "model_name": model_name,
                "total_uses": 0,
                "success_rate": 0.0,
                "avg_response_time": 0.0,
                "error": str(e)
            }
    
    def clear_metrics(self):
        """Очищает все метрики"""
        try:
            # Очищаем взаимодействия
            self.redis_client.delete(self.interactions_key)
            
            # Очищаем метрики моделей (находим все ключи)
            keys = self.redis_client.keys("quality:model_usage:*")
            if keys:
                self.redis_client.delete(*keys)
                
        except Exception as e:
            print(f"⚠️ Ошибка очистки метрик: {e}")



