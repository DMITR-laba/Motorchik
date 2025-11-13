"""
Сервис для генерации и уточнения поисковых запросов
"""
from typing import Dict, Any, List, Optional
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType
from services.dialogue_history_service import DialogueHistoryService


class CarQueryGeneratorService:
    """Генерация и уточнение поисковых запросов"""
    
    def __init__(self):
        self.orchestrator = AIModelOrchestratorService()
    
    async def refine_search_parameters(
        self,
        initial_params: Dict[str, Any],
        dialogue_history: str,
        missing_info: Optional[List[str]] = None,
        available_brands: Optional[List[str]] = None,
        available_categories: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Уточняет параметры поиска на основе истории диалога
        
        Args:
            initial_params: Исходные параметры поиска
            dialogue_history: История диалога
            missing_info: Список недостающей информации
            available_brands: Доступные марки
            available_categories: Доступные категории
        
        Returns:
            Уточненные параметры поиска
        """
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.QUERY_REFINEMENT
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            import json
            
            prompt = f"""Уточни параметры поиска автомобилей на основе истории диалога.

ИСХОДНЫЕ ПАРАМЕТРЫ: {json.dumps(initial_params, ensure_ascii=False, indent=2)}
ИСТОРИЯ ДИАЛОГА: {dialogue_history[:800] if dialogue_history else "Нет"}
НЕДОСТАЮЩАЯ ИНФОРМАЦИЯ: {', '.join(missing_info) if missing_info else "Нет"}
ДОСТУПНЫЕ МАРКИ: {', '.join(available_brands[:20]) if available_brands else "Не указаны"}
ДОСТУПНЫЕ КАТЕГОРИИ: {', '.join(available_categories[:15]) if available_categories else "Не указаны"}

Уточни параметры, добавив информацию из истории диалога. Сохрани все существующие параметры, если они не противоречат истории.

Ответ в формате JSON с уточненными параметрами:
{{
    "mark": "марка или null",
    "model": "модель или null",
    "min_price": число или null,
    "max_price": число или null,
    "min_year": число или null,
    "max_year": число или null,
    "body_type": "категория или null",
    "fuel_type": "тип топлива или null",
    "city": "город или null"
}}"""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты уточняешь параметры поиска автомобилей. Возвращаешь JSON с параметрами."),
                ("human", prompt)
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            # Парсим JSON
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    refined = json.loads(json_match.group(0))
                    # Объединяем с исходными параметрами
                    result = {**initial_params}
                    for key, value in refined.items():
                        if value is not None:
                            result[key] = value
                    return result
            except Exception as e:
                print(f"⚠️ Ошибка парсинга уточненных параметров: {e}")
            
            # Fallback - возвращаем исходные параметры
            return initial_params
            
        except Exception as e:
            print(f"⚠️ Ошибка уточнения параметров: {e}")
            return initial_params
    
    def identify_missing_parameters(
        self,
        search_type: str,
        current_params: Dict[str, Any]
    ) -> List[str]:
        """
        Определяет недостающие параметры для поиска
        
        Args:
            search_type: Тип поиска ("new", "used", "both")
            current_params: Текущие параметры
        
        Returns:
            Список недостающих параметров
        """
        missing = []
        
        # Базовые параметры, которые желательны
        desired_params = {
            "mark": "марка",
            "max_price": "максимальная цена",
            "body_type": "тип кузова"
        }
        
        # Для подержанных автомобилей важны дополнительные параметры
        if search_type == "used":
            desired_params["max_mileage"] = "максимальный пробег"
            desired_params["min_year"] = "минимальный год"
        
        # Проверяем, какие параметры отсутствуют
        for param_key, param_name in desired_params.items():
            if param_key not in current_params or current_params[param_key] is None:
                missing.append(param_name)
        
        return missing
    
    async def generate_search_params_from_query(
        self,
        user_query: str,
        dialogue_history: str,
        available_brands: Optional[List[str]] = None,
        available_categories: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Генерирует параметры поиска из текстового запроса
        
        Args:
            user_query: Запрос пользователя
            dialogue_history: История диалога
            available_brands: Доступные марки
            available_categories: Доступные категории
        
        Returns:
            Параметры поиска
        """
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.QUERY_REFINEMENT
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            import json
            
            prompt = f"""Извлеки параметры поиска автомобилей из запроса пользователя.

ЗАПРОС: {user_query}
ИСТОРИЯ ДИАЛОГА: {dialogue_history[:500] if dialogue_history else "Нет"}
ДОСТУПНЫЕ МАРКИ: {', '.join(available_brands[:20]) if available_brands else "Не указаны"}
ДОСТУПНЫЕ КАТЕГОРИИ: {', '.join(available_categories[:15]) if available_categories else "Не указаны"}

Извлеки все параметры, которые можно определить из запроса:
- Марка (mark)
- Модель (model)
- Минимальная цена (min_price)
- Максимальная цена (max_price)
- Минимальный год (min_year)
- Максимальный год (max_year)
- Тип кузова (body_type)
- Тип топлива (fuel_type)
- Город (city)
- Максимальный пробег (max_mileage) - только для подержанных

Ответ в формате JSON:
{{
    "mark": "марка или null",
    "model": "модель или null",
    "min_price": число или null,
    "max_price": число или null,
    "min_year": число или null,
    "max_year": число или null,
    "body_type": "категория или null",
    "fuel_type": "тип топлива или null",
    "city": "город или null",
    "max_mileage": число или null
}}"""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты извлекаешь параметры поиска из запроса. Возвращаешь JSON."),
                ("human", prompt)
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            # Парсим JSON
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    params = json.loads(json_match.group(0))
                    # Удаляем null значения
                    return {k: v for k, v in params.items() if v is not None}
            except Exception as e:
                print(f"⚠️ Ошибка парсинга параметров: {e}")
            
            return {}
            
        except Exception as e:
            print(f"⚠️ Ошибка генерации параметров: {e}")
            return {}



