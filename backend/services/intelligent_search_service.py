"""
Интеллектуальный поиск автомобилей с автоматическим ослаблением фильтров
"""
from typing import Dict, Any, List, Optional, Tuple
import json
import os
from services.elasticsearch_service import ElasticsearchService
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType
from services.fuzzy_query_interpreter import FuzzyQueryInterpreter
from services.recommendation_service import RecommendationService
from sqlalchemy.orm import Session


class IntelligentSearchService:
    """Интеллектуальный поиск с ослаблением фильтров"""
    
    def __init__(self, config_path: str = "backend/intelligent_search_config.json", db_session: Optional[Session] = None):
        self.config_path = config_path
        self.es_service = ElasticsearchService()
        self.orchestrator = AIModelOrchestratorService()
        self.fuzzy_interpreter = FuzzyQueryInterpreter()
        self.recommendation_service = RecommendationService()
        self.config = self._load_config()
        self.db_session = db_session
        self._sql_agent = None  # Ленивая инициализация
    
    def _load_config(self) -> Dict[str, Any]:
        """Загружает конфигурацию интеллектуального поиска"""
        config_path = self.config_path if hasattr(self, 'config_path') else "backend/intelligent_search_config.json"
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Ошибка загрузки конфигурации: {e}, используем значения по умолчанию")
        
        default_config = {
            "relaxation": {
                "enabled": True,
                "max_steps": 5,
                "priority": [
                    "color",
                    "features",
                    "transmission",
                    "fuel_type",
                    "max_price",
                    "min_year",
                    "category",
                    "brand"
                ],
                "rules": {
                    "price": {
                        "increase_percent": 20,
                        "max_increase_percent": 50
                    },
                    "year": {
                        "decrease_years": 2,
                        "max_decrease_years": 5
                    }
                }
            },
            "fuzzy_interpretation": {
                "enabled": True,
                "confidence_threshold": 0.7,
                "require_clarification_below": 0.5
            },
            "recommendations": {
                "enabled": True,
                "max_recommendations": 5,
                "min_similarity": 0.6
            }
        }
        
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    # Рекурсивно обновляем конфигурацию
                    def update_dict(base, user):
                        for key, value in user.items():
                            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                                update_dict(base[key], value)
                            else:
                                base[key] = value
                    update_dict(default_config, user_config)
        except Exception as e:
            print(f"⚠️ Ошибка загрузки конфигурации: {e}, используем настройки по умолчанию")
        
        return default_config
    
    def _get_sql_agent(self):
        """Ленивая инициализация SQL агента"""
        if self._sql_agent is None and self.db_session is not None:
            try:
                from services.sql_agent_service import SQLAgentService
                self._sql_agent = SQLAgentService(self.db_session, use_langchain=True)
            except Exception as e:
                print(f"⚠️ Не удалось инициализировать SQL агент: {e}")
        return self._sql_agent
    
    async def search_with_intelligence(
        self,
        initial_params: Dict[str, Any],
        user_query: str = "",
        dialogue_context: str = "",
        use_sql_agent: bool = False
    ) -> Dict[str, Any]:
        """
        Выполняет интеллектуальный поиск с автоматическим ослаблением фильтров
        
        Args:
            initial_params: Начальные параметры поиска
            user_query: Текстовый запрос пользователя
            dialogue_context: Контекст диалога
            use_sql_agent: Использовать SQL агент вместо Elasticsearch
        
        Returns:
            Dict с результатами поиска, информацией об ослаблении и рекомендациями
        """
        # Если запрошен SQL агент и он доступен - используем его
        if use_sql_agent:
            sql_agent = self._get_sql_agent()
            if sql_agent:
                try:
                    # Используем SQL агент для поиска
                    sql_result = await sql_agent.process_question(
                        question=user_query or self._params_to_query(initial_params),
                        try_alternative_on_zero=True
                    )
                    
                    if sql_result.get("success") and sql_result.get("row_count", 0) > 0:
                        # Конвертируем результаты SQL в формат Elasticsearch
                        es_results = self._convert_sql_to_es_format(sql_result)
                        return {
                            "success": True,
                            "results": es_results.get("hits", []),
                            "total": es_results.get("total", 0),
                            "relaxation_applied": False,
                            "relaxation_steps": 0,
                            "relaxed_params": None,
                            "original_params": None,
                            "recommendations": None,
                            "message": f"Найдено {es_results.get('total', 0)} результатов",
                            "search_method": "sql_agent"
                        }
                except Exception as e:
                    print(f"⚠️ Ошибка SQL агента: {e}, переключаемся на Elasticsearch")
        
        # Fallback на Elasticsearch
        if not self.es_service.is_available():
            return {
                "success": False,
                "error": "Elasticsearch недоступен",
                "results": [],
                "total": 0,
                "relaxation_applied": False,
                "relaxation_steps": 0,
                "relaxed_params": None,
                "original_params": None,
                "recommendations": None,
                "message": "Elasticsearch недоступен"
            }
        
        # 1. Первичный поиск
        primary_results = self._perform_search(initial_params)
        
        if primary_results.get("total", 0) > 0:
            return {
                "success": True,
                "results": primary_results.get("hits", []),
                "total": primary_results.get("total", 0),
                "relaxation_applied": False,
                "relaxation_steps": 0,
                "relaxed_params": None,
                "original_params": None,
                "recommendations": None,
                "message": f"Найдено {primary_results.get('total', 0)} результатов",
                "search_method": "elasticsearch"
            }
        
        # 2. Если нет результатов и ослабление включено - ослабляем фильтры
        if not self.config.get("relaxation", {}).get("enabled", True):
            return {
                "success": False,
                "results": [],
                "total": 0,
                "relaxation_applied": False,
                "relaxation_steps": 0,
                "relaxed_params": None,
                "original_params": initial_params,
                "recommendations": None,
                "message": "Результаты не найдены. Ослабление фильтров отключено."
            }
        
        # 3. Ослабление фильтров
        relaxed_params, relaxation_steps = await self._relax_filters(
            initial_params.copy(),
            user_query,
            max_steps=self.config.get("relaxation", {}).get("max_steps", 5)
        )
        
        # 4. Поиск с ослабленными фильтрами
        relaxed_results = self._perform_search(relaxed_params)
        
        # 5. Если все еще нет результатов - генерируем рекомендации
        recommendations = None
        if relaxed_results.get("total", 0) == 0 and self.config.get("recommendations", {}).get("enabled", True):
            # Получаем все доступные автомобили для рекомендаций
            all_cars = self._perform_search({})  # Поиск без фильтров
            available_cars = all_cars.get("hits", [])
            
            if available_cars:
                recommendations = await self.recommendation_service.generate_recommendations(
                    initial_params=initial_params,
                    user_query=user_query,
                    available_cars=available_cars,
                    dialogue_context=dialogue_context
                )
        
        total_found = relaxed_results.get("total", 0)
        message_text = (
            f"Найдено {total_found} результатов после ослабления фильтров" 
            if total_found > 0 
            else "Результаты не найдены даже после ослабления фильтров. Смотрите рекомендации."
        )
        
        return {
            "success": total_found > 0,
            "results": relaxed_results.get("hits", []),
            "total": total_found,
            "relaxation_applied": True,
            "relaxation_steps": relaxation_steps,
            "relaxed_params": relaxed_params,
            "original_params": initial_params,
            "recommendations": recommendations,
            "message": message_text,
            "search_method": "elasticsearch"
        }
    
    def _params_to_query(self, params: Dict[str, Any]) -> str:
        """Конвертирует параметры поиска в текстовый запрос"""
        parts = []
        if params.get("mark"):
            parts.append(params["mark"])
        if params.get("model"):
            parts.append(params["model"])
        if params.get("city"):
            parts.append(f"в {params['city']}")
        if params.get("min_price") or params.get("max_price"):
            price_str = ""
            if params.get("min_price"):
                price_str += f"от {params['min_price']}"
            if params.get("max_price"):
                price_str += f" до {params['max_price']}"
            parts.append(price_str)
        if params.get("min_year") or params.get("max_year"):
            year_str = ""
            if params.get("min_year"):
                year_str += f"от {params['min_year']} года"
            if params.get("max_year"):
                year_str += f" до {params['max_year']} года"
            parts.append(year_str)
        return " ".join(parts) if parts else ""
    
    def _convert_sql_to_es_format(self, sql_result: Dict[str, Any]) -> Dict[str, Any]:
        """Конвертирует результаты SQL в формат Elasticsearch"""
        data = sql_result.get("data", [])
        columns = sql_result.get("columns", [])
        
        hits = []
        for row in data:
            # Создаем словарь из строки данных
            car_data = {}
            for i, col in enumerate(columns):
                if i < len(row):
                    car_data[col] = row[i]
            
            # Формируем структуру как в Elasticsearch
            hit = {
                "_source": car_data,
                "_id": str(car_data.get("id", ""))
            }
            hits.append(hit)
        
        return {
            "hits": hits,
            "total": len(hits)
        }
    
    def _perform_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Выполняет поиск через ElasticsearchService"""
        # Извлекаем параметры для поиска
        search_params = {
            "query": params.get("query", ""),
            "mark": params.get("mark"),
            "model": params.get("model"),
            "city": params.get("city"),
            "fuel_type": params.get("fuel_type"),
            "body_type": params.get("body_type"),
            "gear_box_type": params.get("gear_box_type"),
            "driving_gear_type": params.get("driving_gear_type"),
            "min_price": params.get("min_price"),
            "max_price": params.get("max_price"),
            "min_year": params.get("min_year"),
            "max_year": params.get("max_year"),
            "min_mileage": params.get("min_mileage"),
            "max_mileage": params.get("max_mileage"),
            "color": params.get("color"),
            "interior_color": params.get("interior_color"),
            "options": params.get("options"),
            "car_type": params.get("car_type"),
            "min_power": params.get("min_power"),
            "max_power": params.get("max_power"),
            "min_engine_vol": params.get("min_engine_vol"),
            "max_engine_vol": params.get("max_engine_vol"),
            "limit": params.get("limit", 20),
            "offset": params.get("offset", 0),
            "sort_orders": params.get("sort_orders")  # Добавляем поддержку множественной сортировки
        }
        
        # Удаляем None значения
        search_params = {k: v for k, v in search_params.items() if v is not None}
        
        return self.es_service.search_cars(**search_params)
    
    async def _relax_filters(
        self,
        params: Dict[str, Any],
        user_query: str,
        max_steps: int = 5
    ) -> Tuple[Dict[str, Any], int]:
        """
        Ослабляет фильтры по приоритету
        
        Returns:
            Tuple[relaxed_params, steps_taken]
        """
        relaxation_priority = self.config.get("relaxation", {}).get("priority", [])
        relaxation_rules = self.config.get("relaxation", {}).get("rules", {})
        
        relaxed_params = params.copy()
        steps_taken = 0
        
        for step in range(max_steps):
            # Выбираем параметр для ослабления
            param_to_relax = await self._choose_parameter_to_relax(
                relaxed_params,
                user_query,
                relaxation_priority
            )
            
            if not param_to_relax:
                # Больше нечего ослаблять
                break
            
            # Ослабляем параметр
            relaxed_params = self._apply_relaxation(
                relaxed_params,
                param_to_relax,
                relaxation_rules
            )
            
            steps_taken += 1
            
            # Проверяем, есть ли результаты с новыми параметрами
            test_results = self._perform_search(relaxed_params)
            if test_results.get("total", 0) > 0:
                # Нашли результаты, останавливаемся
                break
        
        return relaxed_params, steps_taken
    
    async def _choose_parameter_to_relax(
        self,
        params: Dict[str, Any],
        user_query: str,
        priority: List[str]
    ) -> Optional[str]:
        """
        Выбирает параметр для ослабления на основе анализа запроса и приоритетов
        """
        # Используем LLM для выбора параметра, если доступен
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.FILTER_RELAXATION
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            
            prompt = f"""Проанализируй запрос пользователя и определи, какой параметр поиска автомобиля можно ослабить в первую очередь без существенного ущерба для потребностей клиента.

ТЕКУЩИЕ ПАРАМЕТРЫ: {json.dumps(params, ensure_ascii=False, indent=2)}
ЗАПРОС КЛИЕНТА: {user_query}
ПРИОРИТЕТ ОСЛАБЛЕНИЯ: {', '.join(priority)}

Проанализируй:
1. Какие параметры критически важны для клиента (явно указаны как обязательные)
2. Какие параметры являются пожеланиями
3. В каком порядке ослаблять параметры по наименьшей важности

Верни только название параметра для ослабления из списка приоритетов или "none" если ослаблять нечего.
Доступные параметры: {', '.join(priority)}

Ответ должен быть только одним словом - названием параметра или "none"."""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты - эксперт по подбору автомобилей. Определяешь, какие параметры поиска можно ослабить."),
                ("human", prompt)
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            # Парсим ответ
            param = response.strip().lower()
            if param == "none" or not param:
                return None
            
            # Проверяем, что параметр в приоритетах и присутствует в params
            for p in priority:
                if p.lower() in param or param in p.lower():
                    if p in params and params[p] is not None:
                        return p
            
            # Если не нашли точное совпадение, используем первый доступный из приоритетов
            for p in priority:
                if p in params and params[p] is not None:
                    return p
            
            return None
            
        except Exception as e:
            print(f"⚠️ Ошибка выбора параметра через LLM: {e}, используем простой алгоритм")
            # Fallback на простой алгоритм
            for param in priority:
                if param in params and params[param] is not None:
                    return param
            return None
    
    def _apply_relaxation(
        self,
        params: Dict[str, Any],
        param_name: str,
        rules: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Применяет ослабление к конкретному параметру"""
        relaxed = params.copy()
        
        if param_name == "max_price":
            # Увеличиваем максимальную цену
            current_price = params.get("max_price")
            if current_price and isinstance(current_price, (int, float)):
                increase_percent = rules.get("price", {}).get("increase_percent", 20)
                max_increase = rules.get("price", {}).get("max_increase_percent", 50)
                # Проверяем, не превысили ли максимальное увеличение
                original_price = params.get("original_max_price", current_price)
                max_allowed = original_price * (1 + max_increase / 100)
                new_price = min(current_price * (1 + increase_percent / 100), max_allowed)
                relaxed["max_price"] = int(new_price)
                if "original_max_price" not in relaxed:
                    relaxed["original_max_price"] = original_price
        
        elif param_name == "min_year":
            # Уменьшаем минимальный год
            current_year = params.get("min_year")
            if current_year and isinstance(current_year, int):
                decrease_years = rules.get("year", {}).get("decrease_years", 2)
                max_decrease = rules.get("year", {}).get("max_decrease_years", 5)
                original_year = params.get("original_min_year", current_year)
                min_allowed = original_year - max_decrease
                new_year = max(current_year - decrease_years, min_allowed, 2000)  # Не раньше 2000 года
                relaxed["min_year"] = new_year
                if "original_min_year" not in relaxed:
                    relaxed["original_min_year"] = original_year
        
        elif param_name in ["color", "interior_color", "options", "transmission", "fuel_type"]:
            # Удаляем фильтр (самое мягкое ослабление)
            relaxed.pop(param_name, None)
        
        elif param_name == "category" or param_name == "body_type":
            # Удаляем фильтр категории
            relaxed.pop("category", None)
            relaxed.pop("body_type", None)
        
        elif param_name == "brand":
            # Удаляем фильтр марки (самое строгое ослабление)
            relaxed.pop("brand", None)
            relaxed.pop("model", None)  # Также убираем модель
        
        return relaxed

