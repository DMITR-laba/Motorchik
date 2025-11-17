from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.inspection import inspect as sql_inspect
from typing import List, Dict, Any, Optional
import httpx
import os
import json
from datetime import datetime
from models import get_db
from models.schemas import (
    AIConnectionTest, AIModelSettings, OllamaModel,
    SQLAgentQuestionRequest, SQLAgentResponse, SQLAgentToggleRequest
)
from services.ai_service import AIService
from services.sql_agent_service import SQLAgentService
from services.elasticsearch_service import ElasticsearchService
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType, Complexity
from app.api.search_es import _extract_filters_from_text, _extract_filters_with_ai
from app.api.auth import require_admin
from models.schemas import (
    ModelSelectionRequest, ModelSelectionResponse, OrchestratorPerformanceResponse,
    BulkModelUpdateRequest, BulkModelUpdateResponse,
    IntelligentSearchRequest, IntelligentSearchResponse,
    CarDealerQueryRequest, CarDealerQueryResponse,
    FinanceCalculationRequest, FinanceCalculationResponse,
    DialogueHistoryRequest, DialogueHistoryResponse,
    DialogueVisualizationResponse, QualityMetricsResponse
)
from services.fuzzy_query_interpreter import FuzzyQueryInterpreter
from services.intelligent_search_service import IntelligentSearchService
from services.car_dealer_assistant_service import CarDealerAssistantService
from services.dialog_state_service import DialogStateService
from services.vector_search_service import VectorSearchService

router = APIRouter()

async def _interpret_descriptive_criteria_with_ai(
    user_query: str,
    saved_criteria: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Использует ИИ для интерпретации описательных характеристик автомобиля
    (люксовый, премиальный, семейный, городской, быстрый, красивый и т.д.)
    и преобразует их в конкретные критерии или уточняющие вопросы.
    
    ВАЖНО: Вызывается ТОЛЬКО если в запросе есть описательные характеристики!
    
    Возвращает:
    {
        "has_descriptive": bool,  # есть ли описательные характеристики
        "interpreted_criteria": Dict[str, Any],  # интерпретированные критерии
        "clarification_needed": bool,  # нужно ли уточнение
        "clarification_question": str,  # вопрос для уточнения
        "reasoning": str  # обоснование
    }
    """
    try:
        from services.ai_model_orchestrator_service import AIModelOrchestratorService
        from services.langchain_llm_service import LangChainLLMService
        
        from services.ai_model_orchestrator_service import TaskType, Complexity
        
        orchestrator = AIModelOrchestratorService()
        model_name = await orchestrator.select_model_for_task(TaskType.QUERY_ANALYSIS, Complexity.LIGHT)
        
        llm_service = LangChainLLMService()
        llm = llm_service.get_llm(model_name)
        
        saved_criteria_text = ""
        if saved_criteria:
            criteria_list = []
            if saved_criteria.get("max_price"):
                criteria_list.append(f"Бюджет: до {saved_criteria['max_price']} руб.")
            if saved_criteria.get("min_price"):
                criteria_list.append(f"Бюджет: от {saved_criteria['min_price']} руб.")
            if saved_criteria.get("body_type"):
                criteria_list.append(f"Кузов: {saved_criteria['body_type']}")
            if saved_criteria.get("gear_box_type"):
                criteria_list.append(f"Коробка: {saved_criteria['gear_box_type']}")
            if saved_criteria.get("mark"):
                criteria_list.append(f"Марка: {saved_criteria['mark']}")
            
            if criteria_list:
                saved_criteria_text = "\nСохраненные критерии:\n" + "\n".join(criteria_list)
        
        # Экранируем фигурные скобки в промпте, чтобы LangChain не интерпретировал их как переменные
        prompt = f"""Ты — эксперт по интерпретации описательных характеристик автомобилей.

{saved_criteria_text}

ТЕКУЩИЙ ЗАПРОС ПОЛЬЗОВАТЕЛЯ: "{user_query}"

ТВОЯ ЗАДАЧА: Определи, содержит ли запрос описательные характеристики автомобиля (люксовый, премиальный, семейный, городской, быстрый, красивый, милый, шустрый, экономичный, надежный, комфортный, спортивный, стильный, современный, удобный, практичный, элегантный, роскошный, престижный, качественный, прочный, безопасный, просторный, компактный, мощный, динамичный, маневренный, универсальный, функциональный и т.д.) и интерпретируй их в конкретные критерии.

🚨 КРИТИЧЕСКИ ВАЖНО:
- НЕ добавляй критерии, которых НЕТ в запросе!
- Если в запросе указаны только явные критерии (марка, модель, цена, кузов, пробег, год, коробка передач) БЕЗ описательных характеристик - верни has_descriptive: false!
- Интерпретируй ТОЛЬКО описательные характеристики (люксовый, премиальный, семейный и т.д.)!
- НЕ интерпретируй явные критерии (марка, модель, цена, кузов, пробег, год, коробка передач) - они уже извлечены!
- Описательные характеристики - это субъективные оценки (люксовый, красивый, комфортный), а НЕ технические параметры (автомат, седан, BMW)!

ПРИМЕРЫ ПРАВИЛЬНОГО ОПРЕДЕЛЕНИЯ:
- Запрос: "Найди бмв с пробегом до 5 млн седан" → has_descriptive: false (нет описательных характеристик, только явные критерии: марка, цена, кузов)
- Запрос: "бмв седан автомат" → has_descriptive: false (нет описательных характеристик, только явные критерии: марка, кузов, коробка)
- Запрос: "люксовый автомобиль" → has_descriptive: true, interpreted_criteria: {{"max_price": 5000000, "mark": "BMW" или "Mercedes"}}
- Запрос: "семейный автомобиль" → has_descriptive: true, interpreted_criteria: {{"body_type": "кроссовер" или "минивэн"}}
- Запрос: "комфортный седан" → has_descriptive: true (есть описательная характеристика "комфортный"), interpreted_criteria: {{"gear_box_type": "automatic"}}
- Запрос: "красивый бмв" → has_descriptive: true (есть описательная характеристика "красивый"), interpreted_criteria: {{"mark": "BMW" или "Mercedes"}}

ПРИМЕРЫ ИНТЕРПРЕТАЦИИ ОПИСАТЕЛЬНЫХ ХАРАКТЕРИСТИК:
- "люксовый" → может означать: высокий бюджет (от 3-5 млн), премиальные марки (BMW, Mercedes, Audi, Lexus), высокую мощность, автоматическую коробку, полный привод
- "премиальный" → похоже на "люксовый": высокий бюджет, премиальные марки, высокое качество
- "семейный" → может означать: большой кузов (кроссовер, минивэн, универсал), 7 мест, безопасность, экономичность, автоматическая коробка
- "городской" → может означать: компактный размер (хэтчбек, седан), экономичный двигатель (до 2.0 л), автоматическая коробка, маневренность
- "быстрый" → может означать: высокая мощность (от 200 л.с.), спортивный стиль, автоматическая коробка
- "красивый" → может означать: современный дизайн, определенные марки (Tesla, BMW, Mercedes), определенные цвета
- "экономичный" → может означать: гибрид или электрический, малый объем двигателя (до 1.6 л), низкий расход топлива
- "надежный" → может означать: определенные марки (Toyota, Honda, Lexus), новый автомобиль (от 2020 года)
- "комфортный" → может означать: автоматическая коробка, большой кузов, премиальные опции
- "спортивный" → может означать: высокая мощность, задний или полный привод, спортивный кузов (купе, седан)

ВАЖНО:
- Если характеристика неоднозначна (например, "красивый", "милый"), определи, нужно ли уточнение
- Если характеристика может означать несколько критериев, предложи уточняющий вопрос
- Если характеристика четко определяет критерии, преобразуй их в конкретные значения
- Учитывай уже сохраненные критерии - не предлагай противоречащие значения
- НЕ добавляй критерии, которых НЕТ в запросе и которые НЕ следуют из описательных характеристик!

Ответь ТОЛЬКО в формате JSON (используй двойные фигурные скобки для экранирования):
{{{{"has_descriptive": true/false, "interpreted_criteria": {{{{"max_price": число или null, "min_price": число или null, "mark": "марка" или null, "body_type": "тип кузова" или null, "gear_box_type": "тип коробки" или null, "power": число или null, "min_power": число или null, "fuel_type": "тип топлива" или null, "driving_gear_type": "тип привода" или null, "min_year": число или null}}}}, "clarification_needed": true/false, "clarification_question": "вопрос для уточнения" или null, "reasoning": "краткое обоснование"}}}}"""

        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser
        except ImportError:
            from langchain.prompts import ChatPromptTemplate
            from langchain.output_parsers import JsonOutputParser
        
        # Используем обычный промпт без переменных, так как все данные уже в строке
        # LangChain не должен интерпретировать фигурные скобки как переменные
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", "Ты эксперт по интерпретации описательных характеристик. Отвечай ТОЛЬКО валидным JSON."),
            ("human", "{prompt_text}")
        ])
        
        chain = prompt_template | llm | JsonOutputParser()
        result = await chain.ainvoke({"prompt_text": prompt})
        
        # Обрабатываем результат
        if isinstance(result, str):
            try:
                import json
                result = json.loads(result)
            except:
                raise Exception("Failed to parse JSON")
        
        if not isinstance(result, dict):
            raise Exception("Result is not a dictionary")
        
        # Очищаем null значения из interpreted_criteria
        interpreted_criteria = result.get("interpreted_criteria", {})
        interpreted_criteria = {k: v for k, v in interpreted_criteria.items() if v is not None}
        
        return {
            "has_descriptive": result.get("has_descriptive", False),
            "interpreted_criteria": interpreted_criteria,
            "clarification_needed": result.get("clarification_needed", False),
            "clarification_question": result.get("clarification_question"),
            "reasoning": result.get("reasoning", "")
        }
        
    except Exception as e:
        print(f"⚠️ Ошибка интерпретации описательных характеристик через ИИ: {e}")
        import traceback
        traceback.print_exc()
        return {
            "has_descriptive": False,
            "interpreted_criteria": {},
            "clarification_needed": False,
            "clarification_question": None,
            "reasoning": f"Ошибка: {str(e)}"
        }


async def _check_car_relevance_with_ai(
    user_query: str
) -> bool:
    """
    Использует ИИ для определения, связан ли запрос с подбором автомобилей.
    
    Возвращает:
    - True: если запрос связан с автомобилями, приветствием, благодарностью или вопросом о возможностях
    - False: если запрос не связан с автомобилями
    """
    try:
        from services.ai_model_orchestrator_service import AIModelOrchestratorService
        from services.langchain_llm_service import LangChainLLMService
        from services.ai_model_orchestrator_service import TaskType, Complexity
        
        orchestrator = AIModelOrchestratorService()
        model_name = await orchestrator.select_model_for_task(TaskType.QUERY_ANALYSIS, Complexity.LIGHT)
        
        llm_service = LangChainLLMService()
        llm = llm_service.get_llm(model_name)
        
        # Используем обычную строку вместо f-string, чтобы избежать проблем с экранированием
        # Экранируем фигурные скобки в JSON примерах
        prompt = f"""Ты — эксперт по анализу запросов в диалоге с автосалоном.

ТЕКУЩИЙ ЗАПРОС ПОЛЬЗОВАТЕЛЯ: "{user_query}"

ТВОЯ ЗАДАЧА: Определи, связан ли запрос с подбором автомобилей, приветствием, благодарностью или вопросом о возможностях ассистента.

ЗАПРОС СВЯЗАН с автомобилями, если:
- Пользователь упоминает автомобили, машины, авто (любые упоминания)
- Пользователь просит подобрать, показать, найти автомобили
- Пользователь указывает критерии поиска (бюджет, кузов, коробка, год, марка, модель, город и т.д.)
- Пользователь использует описательные характеристики автомобилей (люксовый, премиальный, семейный, милый, красивый и т.д.)
- Пользователь спрашивает про автомобили, их характеристики, цены, наличие
- Пользователь упоминает запчасти, резину, шины, диски, колеса, покрышки (это связано с автомобилями)

ЗАПРОС СВЯЗАН, если это:
- Приветствие (привет, здравствуй, добрый день, добрый вечер, доброе утро, здравствуйте, hi, hello)
- Благодарность (спасибо, благодарю, благодар, thanks, thank you)
- Вопрос о возможностях ассистента (что умеешь, что можешь, возможности, помощь, помоги, помочь, как пользоваться, как использовать)

ЗАПРОС НЕ СВЯЗАН, если:
- Пользователь задает вопросы не связанные с автомобилями (погода, еда, новости, общие вопросы, личные вопросы)
- Пользователь спрашивает про другие темы (спорт, кино, музыка, политика и т.д.)
- Пользователь задает вопросы, которые не относятся к автосалону или автомобилям

ПРИМЕРЫ:
- "какая погода" → is_related: false (не связано с автомобилями)
- "что кушал" → is_related: false (не связано с автомобилями)
- "какого цвета резина" → is_related: true (резина связана с автомобилями)
- "подбери машину" → is_related: true (команда подбора автомобиля)
- "бюджет до 5 млн" → is_related: true (критерий поиска)
- "привет" → is_related: true (приветствие)
- "спасибо" → is_related: true (благодарность)
- "что умеешь" → is_related: true (вопрос о возможностях)
- "хочу миленький автомобиль" → is_related: true (описательная характеристика автомобиля)
- "BMW" → is_related: true (марка автомобиля)
- "седан" → is_related: true (тип кузова)
- "автомат" → is_related: true (коробка передач)

Ответь ТОЛЬКО в формате JSON. Пример ответа:
{{{{"is_related": true, "confidence": 0.9, "reasoning": "запрос связан с автомобилями"}}}}

Если не связано:
{{{{"is_related": false, "confidence": 0.9, "reasoning": "запрос не связан с автомобилями"}}}}"""
        
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser
        except ImportError:
            from langchain.prompts import ChatPromptTemplate
            from langchain.output_parsers import JsonOutputParser
        
        # Экранируем все фигурные скобки в промпте, чтобы LangChain не интерпретировал их как переменные
        # В f-string уже экранированы фигурные скобки в JSON примерах ({{{{ -> {{ после f-string)
        # Нужно дополнительно экранировать, чтобы LangChain не интерпретировал их как переменные
        # Заменяем все { на {{ и } на }}, но сохраняем уже экранированные
        # Сначала заменяем уже экранированные {{{{ на временный маркер
        escaped_prompt = prompt.replace("{{{{", "___QUAD_BRACE_START___")
        escaped_prompt = escaped_prompt.replace("}}}}", "___QUAD_BRACE_END___")
        # Затем экранируем оставшиеся одинарные фигурные скобки
        escaped_prompt = escaped_prompt.replace("{", "{{").replace("}", "}}")
        # Возвращаем обратно экранированные JSON примеры (теперь они будут {{{{{{{{ -> {{{{ после обработки)
        escaped_prompt = escaped_prompt.replace("___QUAD_BRACE_START___", "{{{{{{{{")
        escaped_prompt = escaped_prompt.replace("___QUAD_BRACE_END___", "}}}}}}}}")
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", "Ты эксперт по анализу связанности запросов. Отвечай ТОЛЬКО валидным JSON."),
            ("human", escaped_prompt)
        ])
        
        chain = prompt_template | llm | JsonOutputParser()
        result = await chain.ainvoke({})
        
        if isinstance(result, str):
            try:
                import json
                result = json.loads(result)
            except:
                raise Exception("Failed to parse JSON")
        
        if not isinstance(result, dict):
            raise Exception("Result is not a dictionary")
        
        is_related = result.get("is_related", True)  # По умолчанию считаем связанным
        confidence = result.get("confidence", 0.5)
        
        print(f"🔍 Проверка связанности с автомобилями: {is_related} (уверенность: {confidence:.2f})")
        print(f"📝 Обоснование: {result.get('reasoning', '')}")
        
        return is_related
        
    except Exception as e:
        print(f"⚠️ Ошибка определения связанности запроса с автомобилями через ИИ: {e}")
        # Fallback: если есть ключевые слова связанные с автомобилями, считаем связанным
        car_keywords = ["машин", "автомобил", "авто", "подбери", "покажи", "найди", "бюджет", "цена", "седан", "кузов", "коробка", "автомат", "механик", "бензин", "дизель", "год", "пробег", "марка", "модель", "город", "люксов", "премиальн", "семейн", "мил", "красив", "резина", "шины", "покрышки", "диски", "колес", "привет", "здравствуй", "спасибо", "благодарю", "что умеешь", "что можешь", "возможности", "ford", "mustang", "bmw", "audi", "mercedes", "toyota", "honda", "nissan", "volkswagen", "hyundai", "kia", "расскажи", "подробнее", "про"]
        query_lower = user_query.lower()
        has_car_keywords = any(keyword in query_lower for keyword in car_keywords)
        
        # Также проверяем, если запрос содержит марку или модель автомобиля (даже если нет других ключевых слов)
        car_brands = ["ford", "mustang", "bmw", "audi", "mercedes", "toyota", "honda", "nissan", "volkswagen", "hyundai", "kia", "mazda", "skoda", "renault", "peugeot", "citroen", "opel", "volvo", "lexus", "infiniti", "acura", "cadillac", "chevrolet", "dodge", "jeep", "lada", "газ", "уаз", "zeekr", "changan", "chery", "geely", "haval", "jac", "jaecoo", "omoda", "tank"]
        has_car_brand = any(brand in query_lower for brand in car_brands)
        
        return has_car_keywords or has_car_brand


async def _extract_sorting_with_ai(
    user_query: str,
    extracted_filters: Dict[str, Any] = None
) -> List[Dict[str, str]]:
    """
    Использует ИИ для извлечения сортировки из запроса пользователя.
    
    Возвращает список словарей с полями сортировки:
    [
        {"field": "price", "direction": "desc"},
        {"field": "year", "direction": "desc"}
    ]
    
    Поддерживаемые поля: price, year, mileage, power, engine_vol
    Направления: asc, desc
    """
    try:
        from services.ai_model_orchestrator_service import AIModelOrchestratorService
        from services.langchain_llm_service import LangChainLLMService
        from services.ai_model_orchestrator_service import TaskType, Complexity
        
        orchestrator = AIModelOrchestratorService()
        model_name = await orchestrator.select_model_for_task(TaskType.QUERY_ANALYSIS, Complexity.LIGHT)
        
        llm_service = LangChainLLMService()
        llm = llm_service.get_llm(model_name)
        
        # Формируем информацию о фильтрах для контекста
        filters_info = ""
        if extracted_filters:
            if extracted_filters.get("max_price"):
                filters_info += f"\nУказан максимальный бюджет: {extracted_filters['max_price']} руб."
            if extracted_filters.get("min_price"):
                filters_info += f"\nУказан минимальный бюджет: {extracted_filters['min_price']} руб."
        
        prompt = f"""Ты — эксперт по анализу запросов пользователей автосалона.

ТЕКУЩИЙ ЗАПРОС ПОЛЬЗОВАТЕЛЯ: "{user_query}"
{filters_info}

ТВОЯ ЗАДАЧА: Извлеки информацию о сортировке из запроса пользователя.

ВАЖНО:
- Если пользователь указал максимальный бюджет (например, "до 5 млн"), то логично показывать сначала самые дорогие автомобили (близкие к лимиту), т.е. сортировка по цене по убыванию (price desc)
- Если пользователь указал минимальный бюджет (например, "от 1 млн"), то логично показывать сначала самые дешевые автомобили (близкие к лимиту), т.е. сортировка по цене по возрастанию (price asc)
- Если пользователь явно указал сортировку (например, "от дорогих к дешевым", "сначала новые", "по пробегу"), извлеки её
- Может быть несколько сортировок (например, сначала по цене, потом по году)

ПОДДЕРЖИВАЕМЫЕ ПОЛЯ ДЛЯ СОРТИРОВКИ:
- price (цена)
- year (год выпуска, manufacture_year)
- mileage (пробег)
- power (мощность)
- engine_vol (объем двигателя)

НАПРАВЛЕНИЯ:
- desc (по убыванию, от большего к меньшему, от дорогих к дешевым, от новых к старым)
- asc (по возрастанию, от меньшего к большему, от дешевых к дорогим, от старых к новым)

ПРИМЕРЫ:
- "машины до 5 млн" → [{{{{"field": "price", "direction": "desc"}}}}] (показываем сначала самые дорогие, близкие к лимиту)
- "машины от 1 млн" → [{{{{"field": "price", "direction": "asc"}}}}] (показываем сначала самые дешевые, близкие к лимиту)
- "от дорогих к дешевым" → [{{{{"field": "price", "direction": "desc"}}}}]
- "сначала новые, потом по цене" → [{{{{"field": "year", "direction": "desc"}}}}, {{{{ "field": "price", "direction": "desc"}}}}]
- "по пробегу от меньшего" → [{{{{"field": "mileage", "direction": "asc"}}}}]
- "самые мощные" → [{{{{"field": "power", "direction": "desc"}}}}]
- "бюджет до 3 млн, седан" → [{{{{"field": "price", "direction": "desc"}}}}] (автоматически добавляем сортировку по цене по убыванию при наличии max_price)

ПРАВИЛА:
1. Если указан max_price (максимальный бюджет) - ВСЕГДА добавляй сортировку по цене по убыванию (price desc) как первую
2. Если указан min_price (минимальный бюджет) - ВСЕГДА добавляй сортировку по цене по возрастанию (price asc) как первую
3. Если пользователь явно указал другую сортировку - используй её, но приоритет у явной сортировки
4. Если пользователь указал несколько сортировок - верни их все в порядке приоритета

Ответь ТОЛЬКО в формате JSON. Пример ответа:
{{{{"sort_orders": [{{{{"field": "price", "direction": "desc"}}}}, {{{{ "field": "year", "direction": "desc"}}}}]}}}}

Если сортировки нет, верни:
{{{{"sort_orders": []}}}}"""
        
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser
        except ImportError:
            from langchain.prompts import ChatPromptTemplate
            from langchain.output_parsers import JsonOutputParser
        
        # Экранируем все фигурные скобки в промпте, чтобы LangChain не интерпретировал их как переменные
        # В f-string уже экранированы фигурные скобки в JSON примерах ({{{{ -> {{ после f-string)
        # Нужно дополнительно экранировать, чтобы LangChain не интерпретировал их как переменные
        # Заменяем все { на {{ и } на }}, но сохраняем уже экранированные
        # Сначала заменяем уже экранированные {{{{ на временный маркер
        escaped_prompt = prompt.replace("{{{{", "___QUAD_BRACE_START___")
        escaped_prompt = escaped_prompt.replace("}}}}", "___QUAD_BRACE_END___")
        # Затем экранируем оставшиеся одинарные фигурные скобки
        escaped_prompt = escaped_prompt.replace("{", "{{").replace("}", "}}")
        # Возвращаем обратно экранированные JSON примеры (теперь они будут {{{{{{{{ -> {{{{ после обработки)
        escaped_prompt = escaped_prompt.replace("___QUAD_BRACE_START___", "{{{{{{{{")
        escaped_prompt = escaped_prompt.replace("___QUAD_BRACE_END___", "}}}}}}}}")
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", "Ты эксперт по извлечению сортировки из запросов. Отвечай ТОЛЬКО валидным JSON."),
            ("human", escaped_prompt)
        ])
        
        chain = prompt_template | llm | JsonOutputParser()
        result = await chain.ainvoke({})
        
        if isinstance(result, str):
            try:
                import json
                result = json.loads(result)
            except:
                raise Exception("Failed to parse JSON")
        
        if not isinstance(result, dict):
            raise Exception("Result is not a dictionary")
        
        sort_orders = result.get("sort_orders", [])
        
        # Валидация и нормализация
        valid_fields = ["price", "year", "mileage", "power", "engine_vol"]
        valid_directions = ["asc", "desc"]
        
        validated_orders = []
        for order in sort_orders:
            if isinstance(order, dict):
                field = order.get("field", "").lower()
                direction = order.get("direction", "").lower()
                
                # Маппинг полей
                field_mapping = {
                    "price": "price",
                    "year": "year",
                    "manufacture_year": "year",
                    "mileage": "mileage",
                    "power": "power",
                    "engine_vol": "engine_vol",
                    "engine_volume": "engine_vol"
                }
                
                field = field_mapping.get(field, field)
                
                if field in valid_fields and direction in valid_directions:
                    validated_orders.append({
                        "field": field,
                        "direction": direction
                    })
        
        # Автоматическое добавление сортировки по цене, если указан max_price или min_price
        if extracted_filters:
            has_price_sort = any(order.get("field") == "price" for order in validated_orders)
            
            if not has_price_sort:
                if extracted_filters.get("max_price"):
                    # При максимальном бюджете показываем сначала самые дорогие
                    validated_orders.insert(0, {"field": "price", "direction": "desc"})
                    print(f"✅ Автоматически добавлена сортировка по цене по убыванию (max_price={extracted_filters['max_price']})")
                elif extracted_filters.get("min_price"):
                    # При минимальном бюджете показываем сначала самые дешевые
                    validated_orders.insert(0, {"field": "price", "direction": "asc"})
                    print(f"✅ Автоматически добавлена сортировка по цене по возрастанию (min_price={extracted_filters['min_price']})")
        
        print(f"🔍 Извлечена сортировка: {validated_orders}")
        return validated_orders
        
    except Exception as e:
        print(f"⚠️ Ошибка извлечения сортировки через ИИ: {e}")
        # Fallback: автоматически добавляем сортировку по цене, если указан max_price или min_price
        sort_orders = []
        if extracted_filters:
            if extracted_filters.get("max_price"):
                sort_orders.append({"field": "price", "direction": "desc"})
                print(f"✅ Fallback: добавлена сортировка по цене по убыванию (max_price={extracted_filters['max_price']})")
            elif extracted_filters.get("min_price"):
                sort_orders.append({"field": "price", "direction": "asc"})
                print(f"✅ Fallback: добавлена сортировка по цене по возрастанию (min_price={extracted_filters['min_price']})")
        return sort_orders


async def _check_query_relevance_with_ai(
    user_query: str,
    dialogue_context: str = "",
    saved_criteria: Dict[str, Any] = None,
    last_response_text: str = ""
) -> Dict[str, Any]:
    """
    Использует ИИ для определения, связан ли новый запрос с предыдущим контекстом подбора автомобилей.
    
    Возвращает:
    {
        "is_related": bool,  # связан ли запрос с подбором автомобилей
        "confidence": float,  # уверенность в ответе
        "reasoning": str  # обоснование
    }
    """
    try:
        from services.ai_model_orchestrator_service import AIModelOrchestratorService
        from services.langchain_llm_service import LangChainLLMService
        from services.ai_model_orchestrator_service import TaskType, Complexity
        
        orchestrator = AIModelOrchestratorService()
        model_name = await orchestrator.select_model_for_task(TaskType.QUERY_ANALYSIS, Complexity.LIGHT)
        
        llm_service = LangChainLLMService()
        llm = llm_service.get_llm(model_name)
        
        saved_criteria_text = ""
        if saved_criteria:
            criteria_list = []
            if saved_criteria.get("max_price"):
                criteria_list.append(f"Бюджет: до {saved_criteria['max_price']} руб.")
            if saved_criteria.get("body_type"):
                criteria_list.append(f"Кузов: {saved_criteria['body_type']}")
            if saved_criteria.get("gear_box_type"):
                criteria_list.append(f"Коробка: {saved_criteria['gear_box_type']}")
            if criteria_list:
                saved_criteria_text = "\nСохраненные критерии:\n" + "\n".join(criteria_list)
        
        context_info = ""
        if dialogue_context:
            context_info = f"КОНТЕКСТ ДИАЛОГА:\n{dialogue_context}\n\n"
        
        # Добавляем последний ответ системы, если он есть
        last_response_info = ""
        if last_response_text:
            # Берем первые 2000 символов последнего ответа, чтобы не перегружать промпт
            last_response_truncated = last_response_text[:2000]
            last_response_info = f"\nПОСЛЕДНИЙ ОТВЕТ СИСТЕМЫ (где были показаны автомобили):\n{last_response_truncated}\n\n"
        
        prompt = f"""Ты — эксперт по анализу связанности запросов в диалоге с автосалоном.

{context_info}{last_response_info}{saved_criteria_text}ТЕКУЩИЙ ЗАПРОС ПОЛЬЗОВАТЕЛЯ: "{user_query}"

ТВОЯ ЗАДАЧА: Определи, связан ли новый запрос пользователя с предыдущим контекстом подбора автомобилей.

ВАЖНО: Если пользователь начинает НОВЫЙ поиск (например, "хочу миленький автомобиль", "подбери машину", "покажи авто"), это НЕ связано с предыдущим контекстом, даже если запрос про автомобили!

ЗАПРОС СВЯЗАН с предыдущим контекстом, если:
- Пользователь продолжает уточнять критерии поиска БЕЗ начала нового поиска (бюджет, кузов, коробка, год, марка, модель, город и т.д.)
- Пользователь отвечает на вопросы о подборе автомобилей (да, нет, конечно, хочу)
- Пользователь подтверждает или отклоняет предложения по подбору
- Пользователь уточняет уже собранные критерии
- Пользователь спрашивает про конкретный автомобиль, который был показан в предыдущем ответе системы (например: "Расскажи подробнее про Ford Mustang", "Что за Zeekr 007?", "Интересует BMW 520d")
- Пользователь просит дополнительную информацию об автомобиле из предыдущего ответа (например: "Подробнее про первый вариант", "Расскажи про второй автомобиль", "Что за третий?")

ЗАПРОС НЕ СВЯЗАН с предыдущим контекстом, если:
- Пользователь начинает НОВЫЙ поиск (например: "хочу миленький автомобиль", "подбери машину", "покажи авто", "ищу автомобиль", "найди машину")
- Пользователь явно просит начать заново или очистить критерии ("заново", "сначала", "очистить", "новый поиск", "другой поиск")
- Пользователь задает вопросы не связанные с автомобилями (погода, новости, общие вопросы)
- Пользователь начинает новый разговор на другую тему
- Пользователь спрашивает про услуги автосалона (ремонт, запчасти, сервис) БЕЗ упоминания подбора автомобилей
- Пользователь просто приветствует или прощается БЕЗ упоминания автомобилей

ПРИМЕРЫ:
- "Хочу миленький автомобиль" → is_related: false (НОВЫЙ поиск, не связан с предыдущим контекстом)
- "Подбери машину" → is_related: false (НОВЫЙ поиск)
- "Покажи авто" → is_related: false (НОВЫЙ поиск)
- "Ищу автомобиль" → is_related: false (НОВЫЙ поиск)
- "Бюджет до 5 млн" → is_related: true (уточнение критерия в текущем диалоге)
- "Автомат" → is_related: true (уточнение критерия)
- "Да, хочу начать поиск" → is_related: true (ответ на вопрос в текущем диалоге)
- "Расскажи подробнее про Ford Mustang" → is_related: true (вопрос про автомобиль из предыдущего ответа)
- "Что за Zeekr 007?" → is_related: true (вопрос про автомобиль из предыдущего ответа)
- "Подробнее про первый вариант" → is_related: true (ссылка на автомобиль из предыдущего ответа)
- "Какая погода?" → is_related: false (не связано с автомобилями)
- "Привет" → is_related: false (если нет контекста подбора)
- "Привет, хочу машину" → is_related: false (НОВЫЙ поиск, даже если есть приветствие)
- "Сколько стоит ремонт?" → is_related: false (не связано с подбором)
- "Заново" → is_related: false (явная команда начать заново)
- "Очистить критерии" → is_related: false (явная команда очистки)

Ответь ТОЛЬКО в формате JSON (используй двойные фигурные скобки для экранирования):
{{{{"is_related": true/false, "confidence": 0.0-1.0, "reasoning": "краткое обоснование"}}}}"""
        
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser
        except ImportError:
            from langchain.prompts import ChatPromptTemplate
            from langchain.output_parsers import JsonOutputParser
        
        # Экранируем все фигурные скобки в промпте, чтобы LangChain не интерпретировал их как переменные
        # Заменяем { на {{ и } на }}, но только в JSON примерах (не трогаем f-string переменные)
        # Сначала заменяем уже экранированные {{{{ на временный маркер
        escaped_prompt = prompt.replace("{{{{", "___QUAD_BRACE___")
        escaped_prompt = escaped_prompt.replace("}}}}", "___QUAD_BRACE_END___")
        # Затем экранируем оставшиеся одинарные фигурные скобки
        escaped_prompt = escaped_prompt.replace("{", "{{").replace("}", "}}")
        # Возвращаем обратно экранированные JSON примеры
        escaped_prompt = escaped_prompt.replace("___QUAD_BRACE___", "{{{{")
        escaped_prompt = escaped_prompt.replace("___QUAD_BRACE_END___", "}}}}")
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", "Ты эксперт по анализу связанности запросов. Отвечай ТОЛЬКО валидным JSON."),
            ("human", escaped_prompt)
        ])
        
        chain = prompt_template | llm | JsonOutputParser()
        result = await chain.ainvoke({})
        
        if isinstance(result, str):
            try:
                import json
                result = json.loads(result)
            except:
                raise Exception("Failed to parse JSON")
        
        if not isinstance(result, dict):
            raise Exception("Result is not a dictionary")
        
        return {
            "is_related": result.get("is_related", True),  # По умолчанию считаем связанным
            "confidence": result.get("confidence", 0.5),
            "reasoning": result.get("reasoning", "")
        }
        
    except Exception as e:
        print(f"⚠️ Ошибка определения связанности запроса через ИИ: {e}")
        # Fallback: проверяем, является ли запрос началом нового поиска
        query_lower = user_query.lower()
        new_search_keywords = ["хочу", "подбери", "покажи", "найди", "ищу", "ищем", "иска", "хочу посмотреть", "хочу увидеть", "давай посмотрим", "начни поиск"]
        is_new_search = any(keyword in query_lower for keyword in new_search_keywords)
        
        # Если это начало нового поиска - не связано с предыдущим контекстом
        if is_new_search:
            return {
                "is_related": False,
                "confidence": 0.7,
                "reasoning": "Fallback: обнаружена команда начала нового поиска"
            }
        
        # Если есть только критерии без команд поиска - может быть связано
        car_criteria_keywords = ["бюджет", "цена", "седан", "кузов", "коробка", "автомат", "механик", "бензин", "дизель", "год", "пробег", "марка", "модель", "город"]
        has_criteria_only = any(keyword in query_lower for keyword in car_criteria_keywords) and not is_new_search
        
        return {
            "is_related": has_criteria_only,
            "confidence": 0.6 if has_criteria_only else 0.4,
            "reasoning": f"Fallback: {'найдены только критерии без команды поиска' if has_criteria_only else 'не найдено связи с предыдущим контекстом'}"
        }


async def _detect_search_intent_with_ai(
    user_query: str,
    dialogue_context: str = "",
    saved_criteria: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Использует ИИ для определения намерения пользователя:
    - хочет ли он начать поиск
    - или просто уточняет критерии
    
    Возвращает:
    {
        "should_start_search": bool,
        "intent": str,  # "start_search", "clarify_criteria", "continue_dialogue"
        "confidence": float,
        "reasoning": str
    }
    """
    try:
        from services.ai_model_orchestrator_service import AIModelOrchestratorService
        from services.langchain_llm_service import LangChainLLMService
        
        from services.ai_model_orchestrator_service import TaskType, Complexity
        
        orchestrator = AIModelOrchestratorService()
        model_name = await orchestrator.select_model_for_task(TaskType.QUERY_ANALYSIS, Complexity.LIGHT)
        
        llm_service = LangChainLLMService()
        llm = llm_service.get_llm(model_name)
        
        saved_criteria_text = ""
        if saved_criteria:
            criteria_list = []
            if saved_criteria.get("max_price"):
                criteria_list.append(f"Бюджет: до {saved_criteria['max_price']} руб.")
            if saved_criteria.get("min_price"):
                criteria_list.append(f"Бюджет: от {saved_criteria['min_price']} руб.")
            if saved_criteria.get("body_type"):
                criteria_list.append(f"Кузов: {saved_criteria['body_type']}")
            if saved_criteria.get("gear_box_type"):
                criteria_list.append(f"Коробка: {saved_criteria['gear_box_type']}")
            if saved_criteria.get("min_year"):
                criteria_list.append(f"Год: от {saved_criteria['min_year']}")
            if saved_criteria.get("max_year"):
                criteria_list.append(f"Год: до {saved_criteria['max_year']}")
            if saved_criteria.get("city"):
                criteria_list.append(f"Город: {saved_criteria['city']}")
            if saved_criteria.get("mark"):
                criteria_list.append(f"Марка: {saved_criteria['mark']}")
            if saved_criteria.get("model"):
                criteria_list.append(f"Модель: {saved_criteria['model']}")
            if saved_criteria.get("fuel_type"):
                criteria_list.append(f"Топливо: {saved_criteria['fuel_type']}")
            
            if criteria_list:
                saved_criteria_text = "\nСохраненные критерии:\n" + "\n".join(criteria_list)
        
        # Формируем более детальный контекст для анализа
        context_info = ""
        if dialogue_context:
            context_info = f"КОНТЕКСТ ДИАЛОГА:\n{dialogue_context}\n\n"
        
        criteria_info = ""
        if saved_criteria_text:
            criteria_info = f"{saved_criteria_text}\n\n"
        
        prompt = f"""Ты — эксперт по анализу намерений пользователя в диалоге с автосалоном.

{context_info}{criteria_info}ТЕКУЩИЙ ЗАПРОС ПОЛЬЗОВАТЕЛЯ: "{user_query}"

ТВОЯ ЗАДАЧА: Определи, что хочет пользователь:
1. **start_search** — пользователь хочет начать поиск автомобилей (явно просит показать, найти, подобрать, искать)
2. **clarify_criteria** — пользователь просто уточняет критерии (называет только параметры без команды поиска)
3. **continue_dialogue** — пользователь отвечает на вопрос или продолжает диалог

ПРИМЕРЫ:
- "Бюджет 5 миллионов" → clarify_criteria (просто уточняет критерий, нет команды поиска)
- "Бюджет до 5 млн" → clarify_criteria (просто уточняет критерий)
- "Покажи машины" → start_search (явная команда поиска)
- "Покажи машины бюджет до 5млн, седан, автомат" → start_search (3+ критерия + команда поиска = сразу поиск)
- "Найди авто" → start_search (явная команда поиска)
- "Ищу машину" → start_search (явная команда поиска)
- "Хочу посмотреть варианты" → start_search (явная команда поиска)
- "Седан, автомат" → clarify_criteria (просто критерии, нет команды)
- "В Краснодаре" → clarify_criteria (просто критерий)
- "Да, ищу" → start_search (подтверждение желания начать поиск)
- "Хорошо, покажи" → start_search (подтверждение желания начать поиск)
- "Автомат" → clarify_criteria (просто критерий)
- "До 3 миллионов" → clarify_criteria (просто критерий)
- "Да" → анализируй контекст: если в контексте есть вопрос "Хотите начать поиск?" или "Могу начать поиск" или "начать поиск" → start_search, иначе → clarify_criteria
- "Да, хочу" → start_search (подтверждение желания начать поиск)
- "Конечно" → анализируй контекст: если в контексте есть вопрос о начале поиска → start_search
- "Начни" → start_search (явная команда начать поиск)
- "Начни поиск" → start_search (явная команда начать поиск)

ВАЖНО:
- Если в запросе есть явные команды поиска (покажи, найди, ищи, подбери, ищу, хочу, хочу посмотреть, давай посмотрим, начни, начни поиск) И при этом есть 3+ критерия → start_search (сразу начинаем поиск, ВЫСОКАЯ уверенность 0.9+)
- Если в запросе есть явные команды поиска (покажи, найди, ищи, подбери, ищу, хочу, хочу посмотреть, давай посмотрим, начни, начни поиск) БЕЗ критериев или с 1-2 критериями → start_search (но может потребоваться уточнение, уверенность 0.7+)
- Если в запросе только критерии БЕЗ команд поиска (бюджет, кузов, коробка, год, город, марка, модель) → clarify_criteria
- Если запрос — ответ на вопрос (да, нет, хорошо, конечно) → анализируй контекст:
  * Если контекст содержит вопрос "Хотите начать поиск?" или "Могу начать поиск" или "начать поиск" или "готовы?" → start_search (уверенность 0.8+)
  * Если контекст содержит просьбу уточнить критерии → clarify_criteria
  * Если контекст содержит предложение начать поиск → start_search (уверенность 0.8+)
- Если запрос содержит "да, хочу" или "да, ищу" или "да, начни" → start_search (явное подтверждение желания начать поиск, уверенность 0.9+)
- Если запрос содержит "нет" или "не хочу" или "не нужно" → clarify_criteria (отказ от поиска, но может быть уточнение)
- Если в контексте диалога есть уточняющие вопросы от ассистента, а пользователь просто называет критерий → clarify_criteria
- Если пользователь подтверждает готовность искать (да, конечно, хочу, готов, давай) после вопроса о начале поиска → start_search (уверенность 0.8+)

Ответь ТОЛЬКО в формате JSON (используй двойные фигурные скобки для экранирования):
{{{{"should_start_search": true/false, "intent": "start_search" | "clarify_criteria" | "continue_dialogue", "confidence": 0.0-1.0, "reasoning": "краткое обоснование"}}}}"""

        try:
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import JsonOutputParser
        except ImportError:
            # Fallback для старых версий langchain
            from langchain.prompts import ChatPromptTemplate
            from langchain.output_parsers import JsonOutputParser
        
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", "Ты эксперт по анализу намерений. Отвечай ТОЛЬКО валидным JSON."),
            ("human", prompt)
        ])
        
        chain = prompt_template | llm | JsonOutputParser()
        result = await chain.ainvoke({})
        
        # Обрабатываем результат - может быть dict или str
        if isinstance(result, str):
            try:
                import json
                result = json.loads(result)
            except:
                # Если не удалось распарсить, используем fallback
                print(f"⚠️ Не удалось распарсить JSON результат: {result}")
                raise Exception("Failed to parse JSON")
        
        # Проверяем, что result - это словарь
        if not isinstance(result, dict):
            print(f"⚠️ Результат не является словарем: {type(result)}, значение: {result}")
            raise Exception("Result is not a dictionary")
        
        return {
            "should_start_search": result.get("should_start_search", False),
            "intent": result.get("intent", "continue_dialogue"),
            "confidence": result.get("confidence", 0.5),
            "reasoning": result.get("reasoning", "")
        }
        
    except Exception as e:
        print(f"⚠️ Ошибка определения намерения через ИИ: {e}")
        # Fallback: если есть явные команды поиска, начинаем поиск
        search_keywords = ["покажи", "найди", "ищи", "подбери", "ищу", "хочу посмотреть", "хочу увидеть", "давай посмотрим"]
        query_lower = user_query.lower()
        has_search_command = any(keyword in query_lower for keyword in search_keywords)
        
        return {
            "should_start_search": has_search_command,
            "intent": "start_search" if has_search_command else "clarify_criteria",
            "confidence": 0.6 if has_search_command else 0.4,
            "reasoning": "Fallback: проверка ключевых слов"
        }

# Файл для хранения состояния SQL-агента
SQL_AGENT_SETTINGS_FILE = "sql_agent_settings.json"

def _load_sql_agent_settings() -> Dict[str, Any]:
    """Загружает настройки SQL-агента"""
    try:
        if os.path.exists(SQL_AGENT_SETTINGS_FILE):
            with open(SQL_AGENT_SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
                # Добавляем значения по умолчанию для новых полей
                if "es_fallback_enabled" not in settings:
                    settings["es_fallback_enabled"] = False
                if "vector_search_enabled" not in settings:
                    settings["vector_search_enabled"] = True  # Векторный поиск включен по умолчанию
                if "es_model" not in settings:
                    settings["es_model"] = "bert_spacy"
                if "sql_model" not in settings:
                    settings["sql_model"] = ""  # По умолчанию используется response_model из AI настроек
                return settings
    except Exception:
        pass
    return {
        "enabled": False,
        "es_fallback_enabled": False,
        "es_model": "bert_spacy",
        "sql_model": ""  # По умолчанию используется response_model из AI настроек
    }

def _save_sql_agent_settings(settings: Dict[str, Any]):
    """Сохраняет настройки SQL-агента"""
    try:
        with open(SQL_AGENT_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise Exception(f"Ошибка сохранения настроек: {str(e)}")

def _relax_filters_for_alternatives(filters: Dict[str, Any], question: str) -> Dict[str, Any]:
    """
    Упрощает фильтры для поиска альтернатив.
    Убирает строгие ограничения, оставляя только основные критерии.
    """
    relaxed = {}
    question_lower = question.lower()
    
    # Сохраняем основные критерии (марка, модель, тип кузова, топливо)
    if filters.get("mark"):
        relaxed["mark"] = filters["mark"]
    if filters.get("model"):
        relaxed["model"] = filters["model"]
    
    # Ослабляем фильтры по цене (расширяем диапазон на 20-30%)
    if filters.get("max_price"):
        relaxed["max_price"] = int(filters["max_price"] * 1.3)  # Увеличиваем на 30%
    if filters.get("min_price"):
        relaxed["min_price"] = max(0, int(filters["min_price"] * 0.8))  # Уменьшаем на 20%
    
    # Ослабляем фильтры по году (расширяем диапазон)
    if filters.get("min_year"):
        relaxed["min_year"] = max(2000, filters["min_year"] - 2)  # Уменьшаем на 2 года
    if filters.get("max_year"):
        relaxed["max_year"] = min(2030, filters["max_year"] + 2)  # Увеличиваем на 2 года
    
    # Ослабляем фильтры по пробегу (увеличиваем максимальный пробег на 30%)
    if filters.get("max_mileage"):
        relaxed["max_mileage"] = int(filters["max_mileage"] * 1.3)
    
    # Сохраняем тип кузова и топливо, если они упоминаются в запросе
    if "седан" in question_lower or "sedan" in question_lower:
        relaxed["body_type"] = "Седан"
    elif "внедорожник" in question_lower or "suv" in question_lower:
        relaxed["body_type"] = "Внедорожник"
    elif "кроссовер" in question_lower or "crossover" in question_lower:
        relaxed["body_type"] = "Кроссовер"
    
    if "бензин" in question_lower or "petrol" in question_lower:
        relaxed["fuel_type"] = "бензин"
    elif "дизель" in question_lower or "diesel" in question_lower:
        relaxed["fuel_type"] = "дизель"
    
    # Убираем строгие фильтры (опции, цвет, город и т.д.)
    # Они могут быть слишком ограничивающими
    
    return relaxed

@router.post("/test-connection")
async def test_connection(
    request: AIConnectionTest,
    db: Session = Depends(get_db)
):
    """Тестирование подключения к внешнему API"""
    try:
        ai_service = AIService()
        result = await ai_service.test_api_connection(request.service, request.key)
        return {"success": True, "message": "Подключение успешно", "details": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка подключения: {str(e)}")

@router.get("/ollama/models")
async def get_ollama_models(db: Session = Depends(get_db), _: object = Depends(require_admin)):
    """Получение списка моделей Ollama"""
    try:
        ai_service = AIService()
        models = await ai_service.get_ollama_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения моделей: {str(e)}")

@router.post("/ollama/pull")
async def pull_ollama_model(
    model_name: str,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Загрузка модели в Ollama"""
    try:
        ai_service = AIService()
        result = await ai_service.pull_ollama_model(model_name)
        return {"success": True, "message": f"Модель {model_name} загружается", "details": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка загрузки модели: {str(e)}")

@router.get("/ollama/status")
async def get_ollama_status(db: Session = Depends(get_db)):
    """Проверка статуса Ollama"""
    try:
        ai_service = AIService()
        status = await ai_service.check_ollama_status()
        return {"status": status}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка проверки статуса: {str(e)}")

@router.post("/settings/save")
async def save_ai_settings(
    settings: AIModelSettings,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Сохранение настроек AI"""
    try:
        ai_service = AIService()
        # Преобразуем Pydantic модель в словарь
        settings_dict = {
            "response_model": settings.response_model,
            "embedding_model": settings.embedding_model,
            "api_service": settings.api_service,
            "api_key": settings.api_key,
            "deep_thinking_model": settings.deep_thinking_model or "",
            "deepseek_api_key": settings.deepseek_api_key or "",
            "updated_at": datetime.now().isoformat()
        }
        result = await ai_service.save_settings_dict(settings_dict)
        return {"success": True, "message": "Настройки сохранены", "settings": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка сохранения настроек: {str(e)}")

@router.get("/settings")
async def get_ai_settings(db: Session = Depends(get_db), _: object = Depends(require_admin)):
    """Получение текущих настроек AI"""
    try:
        ai_service = AIService()
        settings = await ai_service.get_settings()
        return {"settings": settings}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения настроек: {str(e)}")

@router.post("/test-model")
async def test_model(
    model_name: str,
    model_type: str,  # "response" или "embedding"
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Тестирование конкретной модели"""
    try:
        ai_service = AIService()
        
        if model_type == "response":
            result = await ai_service.test_response_model(model_name)
        elif model_type == "embedding":
            result = await ai_service.test_embedding_model(model_name)
        else:
            raise HTTPException(status_code=400, detail="Неверный тип модели")
        
        return {"success": True, "message": f"Модель {model_name} работает корректно", "details": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка тестирования модели: {str(e)}")

# ============================================================================
# SQL-АГЕНТ ЭНДПОИНТЫ
# ============================================================================

@router.get("/sql-agent/status")
async def get_sql_agent_status(db: Session = Depends(get_db)):
    """Получение статуса SQL-агента"""
    try:
        settings = _load_sql_agent_settings()
        return {
            "enabled": settings.get("enabled", False),
            "es_fallback_enabled": settings.get("es_fallback_enabled", False),
            "es_model": settings.get("es_model", "bert_spacy"),
            "sql_model": settings.get("sql_model", "")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения статуса: {str(e)}")

@router.post("/sql-agent/settings/fallback")
async def update_sql_agent_fallback_settings(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Обновление настроек fallback для SQL-агента"""
    try:
        settings = _load_sql_agent_settings()
        if "es_fallback_enabled" in request:
            settings["es_fallback_enabled"] = request["es_fallback_enabled"]
        if "es_model" in request:
            settings["es_model"] = request["es_model"]
        if "sql_model" in request:
            settings["sql_model"] = request["sql_model"]
        _save_sql_agent_settings(settings)
        return {
            "success": True,
            "message": "Настройки fallback обновлены",
            "settings": {
                "es_fallback_enabled": settings.get("es_fallback_enabled", False),
                "es_model": settings.get("es_model", "bert_spacy"),
                "sql_model": settings.get("sql_model", "")
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка обновления настроек: {str(e)}")

@router.post("/sql-agent/toggle")
async def toggle_sql_agent(
    request: SQLAgentToggleRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Включение/выключение SQL-агента"""
    try:
        settings = _load_sql_agent_settings()
        settings["enabled"] = request.enabled
        _save_sql_agent_settings(settings)
        return {
            "success": True,
            "message": f"SQL-агент {'включен' if request.enabled else 'выключен'}",
            "enabled": request.enabled
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка изменения статуса: {str(e)}")

@router.post("/sql-agent/query", response_model=SQLAgentResponse)
async def query_sql_agent(
    request: SQLAgentQuestionRequest,
    db: Session = Depends(get_db)
):
    """Обработка вопроса через SQL-агента
    
    ВАЖНО: SQL-агент работает изолированно и НЕ использует:
    - RAG сервис
    - Elasticsearch
    - Document service
    - Другие сервисы для поиска информации
    """
    try:
        # Проверяем, включен ли SQL-агент
        settings = _load_sql_agent_settings()
        if not settings.get("enabled", False):
            return SQLAgentResponse(
                success=False,
                error="SQL-агент выключен. Включите его в настройках AI."
            )
        
        print(f"🔍 SQL-агент обрабатывает запрос: {request.question}")
        if settings.get("es_fallback_enabled", False):
            print("✅ Fallback на Elasticsearch включен - будет использован при ошибках SQL-агента")
        
        # Получаем состояние диалога для проверки режима диалога
        user_id = getattr(request, 'user_id', 'sql-agent-user')
        dialog_state = DialogStateService(user_id)
        saved_criteria = dialog_state.get_criteria()
        
        # Получаем контекст диалога (последние сообщения)
        dialogue_context = ""
        try:
            from services.dialogue_history_service import DialogueHistoryService
            history_service = DialogueHistoryService(user_id)
            recent_context = history_service.get_recent_context(max_messages=6)
            dialogue_context = recent_context if recent_context else ""
        except Exception as e:
            print(f"⚠️ Не удалось получить контекст диалога: {e}")
        
        # ПЕРВЫМ ДЕЛОМ: Проверяем, связан ли запрос с подбором автомобилей через ИИ
        # Если запрос не связан с автомобилями, вежливо сообщаем о специализации
        query_lower = request.question.lower().strip()
        
        # Проверяем через ИИ, связан ли запрос с автомобилями
        is_car_related = await _check_car_relevance_with_ai(request.question)
        
        if not is_car_related:
            print(f"🚫 Запрос не связан с подбором автомобилей - генерирую вежливый ответ о специализации")
            try:
                from services.rag_service import _generate_with_ai_settings
                
                prompt = f"""Ты — вежливый и профессиональный ассистент по подбору автомобилей в автосалоне.

Пользователь задал вопрос, который не связан с подбором автомобилей: "{request.question}"

ТВОЯ ЗАДАЧА:
Вежливо и формально сообщи пользователю, что ты специализируешься на подборе автомобилей, и предложи помощь в этом направлении.

ВАЖНО:
- Будь вежливым, профессиональным и дружелюбным
- Используй формальный, но теплый тон
- НЕ извиняйся за то, что не можешь помочь с другими вопросами
- Просто вежливо сообщи о своей специализации
- Предложи помощь в подборе автомобиля

ПРИМЕРЫ ХОРОШИХ ОТВЕТОВ:
- "Я специализируюсь на подборе автомобилей и помощи в выборе подходящего транспортного средства. Если вам нужна помощь в подборе автомобиля по вашим критериям (бюджет, тип кузова, коробка передач и т.д.), я буду рад помочь!"
- "Я — ваш персональный ассистент по подбору автомобилей. Моя специализация — помощь в выборе подходящего автомобиля по вашим критериям. Чем могу помочь в подборе?"
- "Я помогаю клиентам подобрать автомобиль по их требованиям. Если вас интересует подбор автомобиля, уточните, пожалуйста, ваши критерии (бюджет, тип кузова, коробка передач и т.д.), и я найду подходящие варианты."

Сформируй краткий вежливый ответ (2-3 предложения):"""
                
                ai_response_text, model_info = await _generate_with_ai_settings(prompt)
                
                # Сохраняем сообщение в БД
                try:
                    from services.database_service import DatabaseService
                    db_service = DatabaseService(db)
                    db_service.save_chat_message(
                        user_id=user_id,
                        message=request.question,
                        response=ai_response_text,
                        related_article_ids=[]
                    )
                except Exception as e:
                    print(f"⚠️ Не удалось сохранить сообщение в БД: {e}")
                
                return SQLAgentResponse(
                    success=True,
                    answer=ai_response_text,
                    data=[],
                    row_count=0,
                    columns=[],
                    needs_clarification=False
                )
            except Exception as e:
                print(f"⚠️ Ошибка генерации ответа о специализации: {e}")
                # Fallback ответ
                return SQLAgentResponse(
                    success=True,
                    answer="Я специализируюсь на подборе автомобилей и помощи в выборе подходящего транспортного средства. Если вам нужна помощь в подборе автомобиля по вашим критериям, я буду рад помочь!",
                    data=[],
                    row_count=0,
                    columns=[],
                    needs_clarification=False
                )
        
        # Получаем последний ответ системы для проверки связанности (даже если нет сохраненных критериев)
        last_response_for_relevance = ""
        try:
            from models.database import ChatMessage
            from sqlalchemy import desc
            last_message = db.query(ChatMessage).filter(
                ChatMessage.user_id == user_id
            ).order_by(desc(ChatMessage.created_at)).first()
            if last_message and last_message.response:
                last_response_for_relevance = last_message.response
                print(f"📄 Получен последний ответ системы (первые 200 символов): {last_response_for_relevance[:200]}...")
        except Exception as e:
            print(f"⚠️ Не удалось получить последний ответ системы: {e}")
        
        # Проверяем явные команды очистки
        clear_commands = ["заново", "сначала", "очистить", "очисти", "новый поиск", "другой поиск", "начать заново", "сбросить", "сброс"]
        is_clear_command = any(cmd in query_lower for cmd in clear_commands)
        
        # Инициализируем переменную для результата проверки связанности
        relevance_result = {"is_related": False, "confidence": 0.0, "reasoning": ""}
        
        if is_clear_command:
            print(f"🔄 Обнаружена явная команда очистки - очищаю сохраненные критерии и диалог")
            dialog_state.clear_criteria()
            saved_criteria = {}
            dialogue_context = ""
        elif saved_criteria or dialogue_context or last_response_for_relevance:
            print(f"🔍 Проверяю связанность нового запроса с предыдущим контекстом подбора...")
            
            relevance_result = await _check_query_relevance_with_ai(
                user_query=request.question,
                dialogue_context=dialogue_context,
                saved_criteria=saved_criteria,
                last_response_text=last_response_for_relevance
            )
            print(f"📊 Связанность: {relevance_result['is_related']} (уверенность: {relevance_result['confidence']:.2f})")
            print(f"📝 Обоснование: {relevance_result['reasoning']}")
            
            # Если запрос не связан с подбором автомобилей - очищаем критерии и диалог
            if not relevance_result['is_related']:
                print(f"🔄 Новый запрос не связан с предыдущим контекстом подбора - очищаю сохраненные критерии и диалог")
                dialog_state.clear_criteria()
                saved_criteria = {}
                dialogue_context = ""  # Очищаем контекст диалога
            else:
                # Если запрос связан, добавляем последний ответ системы в контекст диалога
                if last_response_for_relevance:
                    # Добавляем последний ответ в начало контекста диалога
                    if dialogue_context:
                        dialogue_context = f"ПРЕДЫДУЩИЙ ОТВЕТ СИСТЕМЫ:\n{last_response_for_relevance[:1500]}\n\nКОНТЕКСТ ДИАЛОГА:\n{dialogue_context}"
                    else:
                        dialogue_context = f"ПРЕДЫДУЩИЙ ОТВЕТ СИСТЕМЫ:\n{last_response_for_relevance[:1500]}"
                    print(f"✅ Запрос связан с предыдущим диалогом - добавляю последний ответ системы в контекст")
        
        # Проверяем, был ли предыдущий ответ с needs_clarification (режим диалога)
        # Получаем последнее сообщение из истории через БД напрямую
        in_dialogue_mode = False
        last_response_text = ""
        
        try:
            from models.database import ChatMessage
            from sqlalchemy import desc
            # Получаем последнее сообщение пользователя (ответ AI)
            last_message = db.query(ChatMessage).filter(
                ChatMessage.user_id == user_id
            ).order_by(desc(ChatMessage.created_at)).first()
            
            if last_message and last_message.response:
                last_response_text = last_message.response
                response_lower = last_response_text.lower()
                
                # Проверяем признаки режима диалога:
                # 1. Содержит просьбу уточнить критерии
                # 2. Содержит список вопросов или критериев для уточнения
                # 3. Содержит фразы типа "уточните пожалуйста", "чтобы подобрать"
                dialogue_indicators = [
                    "уточните", "критерии", "бюджет", "кузов", "коробка", "год", "город",
                    "подбери", "подобрать", "уточнить", "вопрос", "уточните пожалуйста",
                    "чтобы подобрать", "максимальная цена", "тип кузова", "коробка передач",
                    "год выпуска", "где планируете", "предпочтения по марке", "с этими данными"
                ]
                
                # Также проверяем структуру ответа (список вопросов или критериев)
                response_lines = [s.strip() for s in last_message.response.split("\n") if s.strip()]
                question_count = len([s for s in response_lines if "?" in s])
                has_question_list = any([
                    question_count >= 2,  # Два или более вопроса
                    "бюджет" in response_lower and "кузов" in response_lower and "коробка" in response_lower,  # Список критериев
                    "коробка" in response_lower and "год" in response_lower and "город" in response_lower,  # Список критериев
                    "(" in last_message.response and ")" in last_message.response and len([s for s in response_lines if "(" in s and ")" in s]) >= 3,  # Список с пояснениями
                    "чтобы подобрать" in response_lower and ("уточните" in response_lower or "критерии" in response_lower)  # Явная просьба уточнить
                ])
                
                print(f"🔍 Анализ последнего ответа: вопросов={question_count}, keywords={any(keyword in response_lower for keyword in dialogue_indicators)}, has_questions={has_question_list}")
                
                if any(keyword in response_lower for keyword in dialogue_indicators) or has_question_list:
                    in_dialogue_mode = True
                    print(f"💬 ✅ Обнаружен режим диалога (последний ответ содержал уточняющие вопросы или просьбу уточнить)")
                    print(f"📝 Признаки: keywords={any(keyword in response_lower for keyword in dialogue_indicators)}, has_questions={has_question_list}")
                    print(f"📄 Последний ответ (первые 300 символов): {last_response_text[:300]}...")
                else:
                    print(f"❌ Режим диалога НЕ обнаружен. Признаки: keywords={any(keyword in response_lower for keyword in dialogue_indicators)}, has_questions={has_question_list}")
                    print(f"📄 Последний ответ (первые 300 символов): {last_response_text[:300]}...")
        except Exception as e:
            print(f"⚠️ Не удалось проверить режим диалога через БД: {e}")
            import traceback
            traceback.print_exc()
        
        # Дополнительная проверка через контекст диалога
        if not in_dialogue_mode and dialogue_context:
            context_lower = dialogue_context.lower()
            if any(keyword in context_lower for keyword in [
                "уточните", "критерии", "чтобы подобрать", "максимальная цена", "тип кузова"
            ]):
                in_dialogue_mode = True
                print(f"💬 Обнаружен режим диалога через контекст диалога")
        
        # ПЕРВЫМ ДЕЛОМ: Проверяем, если пользователь сразу прислал запрос с 3+ критериями и командой поиска
        # В этом случае ИГНОРИРУЕМ режим диалога и сразу начинаем поиск
        query_lower = request.question.lower()
        search_commands = ["покажи", "найди", "ищи", "подбери", "ищу", "хочу посмотреть", "хочу увидеть", "давай посмотрим", "начни", "начни поиск", "хочу"]
        has_search_command = any(cmd in query_lower for cmd in search_commands)
        
        # Извлекаем критерии из текущего запроса (AI с fallback на паттерны)
        current_filters = await _extract_filters_with_ai(request.question)
        current_criteria_count = sum([
            1 if current_filters.get("max_price") or current_filters.get("min_price") else 0,
            1 if current_filters.get("body_type") else 0,
            1 if current_filters.get("gear_box_type") else 0,
            1 if current_filters.get("min_year") or current_filters.get("max_year") else 0,
            1 if current_filters.get("city") else 0,
            1 if current_filters.get("mark") else 0,
            1 if current_filters.get("model") else 0,
            1 if current_filters.get("fuel_type") else 0,
        ])
        
        print(f"🔍 Анализ запроса: команда поиска={has_search_command}, критериев={current_criteria_count}, режим диалога={in_dialogue_mode}")
        print(f"   Извлеченные критерии: {current_filters}")
        
        # Инициализируем переменные
        should_check_intent = False
        should_continue_dialogue = False
        
        # Если есть команда поиска и 3+ критерия - ИГНОРИРУЕМ режим диалога и сразу начинаем поиск
        if has_search_command and current_criteria_count >= 3:
            print(f"✅ Обнаружен запрос с командой поиска и 3+ критериями - ИГНОРИРУЮ режим диалога и сразу начинаю поиск")
            print(f"   Команда поиска: {has_search_command}, критериев: {current_criteria_count}")
            in_dialogue_mode = False  # Принудительно отключаем режим диалога
            should_check_intent = False  # Не проверяем намерение, сразу идем к поиску
            should_continue_dialogue = False  # НЕ продолжаем диалог, начинаем поиск
            # Сохраняем критерии из запроса
            if current_filters:
                # ВАЖНО: Объединяем с уже сохраненными критериями, чтобы не потерять марку
                existing_criteria = dialog_state.get_criteria()
                # Если марка была сохранена ранее, но не в новых фильтрах - сохраняем её
                if existing_criteria.get("mark") and not current_filters.get("mark"):
                    current_filters["mark"] = existing_criteria["mark"]
                    print(f"✅ Сохраняю марку из существующих критериев: {existing_criteria['mark']}")
                # Объединяем критерии
                combined_for_save = {**existing_criteria, **current_filters}
                dialog_state.update_criteria(combined_for_save)
                saved_criteria = dialog_state.get_criteria()
                print(f"📋 Сохранены критерии из запроса: {saved_criteria}")
                if saved_criteria.get("mark"):
                    print(f"✅ Марка сохранена: {saved_criteria['mark']}")
        else:
            # Проверяем намерение пользователя через ИИ
            # ВСЕГДА проверяем, если режим диалога активен (предыдущий ответ был с уточняющими вопросами)
            # ИЛИ если есть сохраненные критерии или контекст диалога
            should_check_intent = in_dialogue_mode or saved_criteria or dialogue_context
            
            # В режиме диалога ВСЕГДА проверяем намерение, даже если нет сохраненных критериев
            if in_dialogue_mode:
                print(f"💬 Режим диалога активен - обязательно проверяю намерение пользователя")
        
        # Если не нужно проверять намерение (запрос с 3+ критериями и командой), сразу идем к поиску
        if not should_check_intent:
            print(f"🚀 Пропускаю проверку намерения - сразу начинаю поиск")
        elif should_check_intent:
            print(f"💬 Проверяю намерение пользователя (режим диалога: {in_dialogue_mode}, критерии: {bool(saved_criteria)}, контекст: {bool(dialogue_context)})...")
            intent_result = await _detect_search_intent_with_ai(
                user_query=request.question,
                dialogue_context=dialogue_context,
                saved_criteria=saved_criteria
            )
            
            print(f"🎯 Намерение: {intent_result['intent']} (уверенность: {intent_result['confidence']:.2f})")
            print(f"📝 Обоснование: {intent_result['reasoning']}")
            
            # Если пользователь просто уточняет критерии - сохраняем их и продолжаем диалог
            # В режиме диалога приоритет - продолжать диалог, если нет явной команды поиска с высокой уверенностью
            # Проверяем, был ли в предыдущем ответе вопрос о начале поиска
            last_response_has_search_question = False
            if last_response_text:
                search_question_keywords = [
                    "хотите начать поиск", "можете начать поиск", "могу начать поиск",
                    "начать поиск", "начать поиск автомобилей", "начать поиск подходящих"
                ]
                last_response_lower = last_response_text.lower()
                last_response_has_search_question = any(keyword in last_response_lower for keyword in search_question_keywords)
            
            # Если пользователь подтверждает начало поиска после вопроса о поиске
            query_lower_clean = request.question.lower().strip()
            confirmation_keywords = ["да", "да, хочу", "да хочу", "конечно", "начни", "начни поиск", "да, начни", "хочу", "готов", "готовы", "давай", "давай поиск", "ищу"]
            is_confirmation = any(keyword in query_lower_clean for keyword in confirmation_keywords) or query_lower_clean in confirmation_keywords
            
            # Проверяем, является ли ответ отказом
            denial_keywords = ["нет", "не хочу", "не нужно", "не надо", "не готов", "не готовы", "пока нет", "пока не хочу"]
            is_denial = any(keyword in query_lower_clean for keyword in denial_keywords) or query_lower_clean in denial_keywords
            
            if last_response_has_search_question and is_confirmation:
                print(f"✅ Пользователь подтвердил начало поиска после вопроса о поиске")
                should_continue_dialogue = False  # НЕ продолжаем диалог, начинаем поиск
            elif last_response_has_search_question and is_denial:
                print(f"❌ Пользователь отказался от начала поиска")
                should_continue_dialogue = True  # Продолжаем диалог, спрашиваем что-то еще
            elif intent_result['intent'] == 'start_search' and intent_result['confidence'] >= 0.7:
                # Если намерение start_search с высокой уверенностью, начинаем поиск
                print(f"✅ Высокая уверенность в намерении начать поиск ({intent_result['confidence']:.2f})")
                should_continue_dialogue = False
            elif intent_result['intent'] == 'clarify_criteria':
                # Если намерение - уточнение критериев, продолжаем диалог
                print(f"💬 Намерение: уточнение критериев - продолжаю диалог")
                should_continue_dialogue = True
            else:
                # Если режим диалога активен, продолжаем диалог, если:
                # 1. Намерение != start_search (любая уверенность)
                # 2. Намерение = start_search, но уверенность < 0.8 (низкая уверенность в команде поиска)
                should_continue_dialogue = (
                    (in_dialogue_mode and intent_result['intent'] != 'start_search') or
                    (in_dialogue_mode and intent_result['intent'] == 'start_search' and intent_result['confidence'] < 0.8)
                )
            
            if should_continue_dialogue:
                print(f"💾 Пользователь уточняет критерии - сохраняю и продолжаю диалог")
                print(f"📊 Режим диалога: {in_dialogue_mode}, намерение: {intent_result['intent']}, уверенность: {intent_result['confidence']:.2f}")
                print(f"✅ Принято решение: продолжить диалог (не начинать поиск)")
                
                # Извлекаем новые критерии из запроса (AI с fallback на паттерны)
                new_filters = await _extract_filters_with_ai(request.question)
                
                # Если пользователь просто сказал "да" или "нет" без критериев, не извлекаем фильтры
                query_lower_clean = request.question.lower().strip()
                simple_responses = ["да", "нет", "конечно", "не хочу", "не нужно", "готов", "готовы"]
                if query_lower_clean not in simple_responses and not any(resp in query_lower_clean for resp in simple_responses):
                    # Проверяем, есть ли описательные характеристики (AI сам определит наличие)
                    descriptive_result = await _interpret_descriptive_criteria_with_ai(
                        user_query=request.question,
                        saved_criteria=saved_criteria
                    )
                    
                    if descriptive_result.get("has_descriptive"):
                        print(f"🎨 Обнаружены описательные характеристики: {descriptive_result.get('reasoning', '')}")
                        
                        # Если нужны уточнения
                        if descriptive_result.get("clarification_needed") and descriptive_result.get("clarification_question"):
                            print(f"❓ Требуется уточнение: {descriptive_result['clarification_question']}")
                            # Добавляем интерпретированные критерии, если они есть
                            if descriptive_result.get("interpreted_criteria"):
                                interpreted = descriptive_result["interpreted_criteria"].copy()
                                # Нормализуем значения для совместимости с поиском
                                if interpreted.get("gear_box_type") == "automatic":
                                    interpreted["gear_box_type"] = "автомат"
                                elif interpreted.get("gear_box_type") == "manual":
                                    interpreted["gear_box_type"] = "механика"
                                new_filters.update(interpreted)
                        else:
                            # Добавляем интерпретированные критерии
                            if descriptive_result.get("interpreted_criteria"):
                                print(f"✅ Интерпретированные критерии: {descriptive_result['interpreted_criteria']}")
                                interpreted = descriptive_result["interpreted_criteria"].copy()
                                # Нормализуем значения для совместимости с поиском
                                if interpreted.get("gear_box_type") == "automatic":
                                    interpreted["gear_box_type"] = "автомат"
                                elif interpreted.get("gear_box_type") == "manual":
                                    interpreted["gear_box_type"] = "механика"
                                new_filters.update(interpreted)
                    
                    # Обновляем сохраненные критерии только если есть новые фильтры
                    if new_filters:
                        # ВАЖНО: Объединяем с уже сохраненными критериями, чтобы не потерять марку
                        current_criteria = dialog_state.get_criteria()
                        # Если марка была сохранена ранее, но не в новых фильтрах - сохраняем её
                        if current_criteria.get("mark") and not new_filters.get("mark"):
                            new_filters["mark"] = current_criteria["mark"]
                            print(f"✅ Сохраняю марку из существующих критериев: {current_criteria['mark']}")
                        # Объединяем критерии
                        combined_for_update = {**current_criteria, **new_filters}
                        dialog_state.update_criteria(combined_for_update)
                        updated_criteria = dialog_state.get_criteria()
                        print(f"✅ Критерии обновлены: {updated_criteria}")
                        if updated_criteria.get("mark"):
                            print(f"✅ Марка сохранена в обновленных критериях: {updated_criteria['mark']}")
                
                # Генерируем ответ для продолжения диалога
                try:
                    from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType, Complexity
                    orchestrator = AIModelOrchestratorService()
                    model_name = await orchestrator.select_model_for_task(TaskType.QUERY_ANALYSIS, Complexity.MEDIUM)
                    
                    llm_service = LangChainLLMService()
                    llm = llm_service.get_llm(model_name)
                    
                    # Формируем промпт для генерации ответа
                    updated_criteria = dialog_state.get_criteria()
                    criteria_summary = ""
                    if updated_criteria:
                        criteria_parts = []
                        if updated_criteria.get("mark"):
                            criteria_parts.append(f"Марка: {updated_criteria['mark']}")
                        if updated_criteria.get("max_price"):
                            criteria_parts.append(f"Бюджет: до {updated_criteria['max_price']} руб.")
                        if updated_criteria.get("body_type"):
                            criteria_parts.append(f"Кузов: {updated_criteria['body_type']}")
                        if updated_criteria.get("gear_box_type"):
                            criteria_parts.append(f"Коробка: {updated_criteria['gear_box_type']}")
                        if criteria_parts:
                            criteria_summary = "\nСохраненные критерии:\n" + "\n".join(criteria_parts)
                    
                    prompt = f"""Ты — вежливый ассистент по подбору автомобилей.

{criteria_summary}

Пользователь уточняет критерии поиска: "{request.question}"

Сформируй краткий вежливый ответ (1-2 предложения), подтверждающий, что критерии сохранены, и спроси, есть ли еще что-то, что нужно уточнить, или можно начать поиск."""
                    
                    from langchain_core.prompts import ChatPromptTemplate
                    prompt_template = ChatPromptTemplate.from_messages([
                        ("system", "Ты вежливый ассистент по подбору автомобилей. Отвечай кратко и по делу."),
                        ("human", "{prompt_text}")
                    ])
                    
                    chain = prompt_template | llm
                    response = await chain.ainvoke({"prompt_text": prompt})
                    ai_response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    print(f"✅ Сгенерирован ответ для продолжения диалога")
                    
                    return SQLAgentResponse(
                        success=True,
                        answer=ai_response_text,
                        data=[],
                        row_count=0,
                        columns=[],
                        needs_clarification=True
                    )
                except Exception as e:
                    print(f"⚠️ Ошибка генерации ответа для продолжения диалога: {e}")
                    # Fallback ответ
                    return SQLAgentResponse(
                        success=True,
                        answer="Понял, сохранил критерии. Есть еще что-то, что нужно уточнить, или можем начать поиск?",
                        data=[],
                        row_count=0,
                        columns=[],
                        needs_clarification=True
                    )
            else:
                print(f"✅ Принято решение: начать поиск (не продолжаю диалог)")
                
                # Инициализируем descriptive_result по умолчанию
                descriptive_result = {"has_descriptive": False}
                
                # ВАЖНО: Извлекаем критерии из запроса ПЕРЕД началом поиска
                # Это нужно для случаев, когда пользователь говорит "покажи машины бюджет 5 млн"
                # или "найди авто седан, автомат" - критерии должны быть сохранены
                # Используем AI с fallback на паттерны
                extracted_filters = await _extract_filters_with_ai(request.question)
                
                # Извлекаем новые критерии из запроса (если это не просто "да" или "нет")
                query_lower_clean = request.question.lower().strip()
                simple_responses = ["да", "нет", "конечно", "не хочу", "не нужно", "готов", "готовы"]
                new_filters = {}
                
                # Всегда пытаемся извлечь критерии из запроса, даже если это простой ответ
                # Это нужно для случаев, когда пользователь говорит "да, бюджет 5 млн" или "готов, седан"
                
                if query_lower_clean not in simple_responses and not any(resp in query_lower_clean for resp in simple_responses):
                    new_filters = extracted_filters
                    
                    # Проверяем, есть ли описательные характеристики (AI сам определит наличие)
                    descriptive_result = await _interpret_descriptive_criteria_with_ai(
                        user_query=request.question,
                        saved_criteria=saved_criteria
                    )
                    
                    if descriptive_result.get("has_descriptive"):
                        print(f"🎨 Обнаружены описательные характеристики: {descriptive_result.get('reasoning', '')}")
                        
                        # Если нужны уточнения
                        if descriptive_result.get("clarification_needed") and descriptive_result.get("clarification_question"):
                            print(f"❓ Требуется уточнение: {descriptive_result['clarification_question']}")
                            # Добавляем интерпретированные критерии, если они есть
                            if descriptive_result.get("interpreted_criteria"):
                                interpreted = descriptive_result["interpreted_criteria"].copy()
                                # Нормализуем значения для совместимости с поиском
                                if interpreted.get("gear_box_type") == "automatic":
                                    interpreted["gear_box_type"] = "автомат"
                                elif interpreted.get("gear_box_type") == "manual":
                                    interpreted["gear_box_type"] = "механика"
                                new_filters.update(interpreted)
                        else:
                            # Добавляем интерпретированные критерии
                            if descriptive_result.get("interpreted_criteria"):
                                print(f"✅ Интерпретированные критерии: {descriptive_result['interpreted_criteria']}")
                                interpreted = descriptive_result["interpreted_criteria"].copy()
                                # Нормализуем значения для совместимости с поиском
                                if interpreted.get("gear_box_type") == "automatic":
                                    interpreted["gear_box_type"] = "автомат"
                                elif interpreted.get("gear_box_type") == "manual":
                                    interpreted["gear_box_type"] = "механика"
                                new_filters.update(interpreted)
                else:
                    # Даже для простых ответов проверяем, есть ли критерии в запросе
                    # Например: "да, бюджет 5 млн" или "готов, седан"
                    if extracted_filters:
                        new_filters = extracted_filters
                        print(f"📋 Извлечены критерии из простого ответа: {new_filters}")
                    
                    # Для простых ответов тоже проверяем описательные характеристики, если есть текст
                    if request.question and len(request.question.strip()) > 2:
                        descriptive_result = await _interpret_descriptive_criteria_with_ai(
                            user_query=request.question,
                            saved_criteria=saved_criteria
                        )
                        
                        if descriptive_result.get("has_descriptive") and descriptive_result.get("interpreted_criteria"):
                            interpreted = descriptive_result["interpreted_criteria"].copy()
                            # Нормализуем значения для совместимости с поиском
                            if interpreted.get("gear_box_type") == "automatic":
                                interpreted["gear_box_type"] = "автомат"
                            elif interpreted.get("gear_box_type") == "manual":
                                interpreted["gear_box_type"] = "механика"
                            new_filters.update(interpreted)
                            print(f"✅ Добавлены интерпретированные критерии из простого ответа: {interpreted}")
                    
                    # Обновляем сохраненные критерии только если есть новые фильтры
                    # ВАЖНО: Объединяем с уже сохраненными критериями, а не перезаписываем
                    if new_filters:
                        current_criteria = dialog_state.get_criteria()
                        # Если марка была сохранена ранее, но не в новых фильтрах - сохраняем её
                        if current_criteria.get("mark") and not new_filters.get("mark"):
                            new_filters["mark"] = current_criteria["mark"]
                            print(f"✅ Сохраняю марку из существующих критериев: {current_criteria['mark']}")
                        # Объединяем критерии
                        combined_criteria = {**current_criteria, **new_filters}
                        dialog_state.update_criteria(combined_criteria)
                        updated_criteria = dialog_state.get_criteria()
                        print(f"✅ Критерии обновлены из простого ответа: {updated_criteria}")
                        if updated_criteria.get("mark"):
                            print(f"✅ Марка сохранена в обновленных критериях: {updated_criteria['mark']}")
                
                # ВАЖНО: Сохраняем критерии перед началом поиска, если они были извлечены из запроса
                # Это нужно для случаев, когда пользователь говорит "покажи машины бюджет 5 млн"
                # или "найди авто седан, автомат" - критерии должны быть сохранены перед поиском
                # Но только если они еще не были сохранены выше
                if extracted_filters and not new_filters:
                    # Критерии были извлечены, но не были сохранены (например, в запросе с командой поиска)
                    # Объединяем извлеченные критерии с уже сохраненными
                    current_criteria = dialog_state.get_criteria()
                    # Если марка была сохранена ранее, но не в извлеченных фильтрах - сохраняем её
                    if current_criteria.get("mark") and not extracted_filters.get("mark"):
                        extracted_filters["mark"] = current_criteria["mark"]
                        print(f"✅ Сохраняю марку из существующих критериев перед поиском: {current_criteria['mark']}")
                    combined_before_search = {**current_criteria, **extracted_filters}
                    dialog_state.update_criteria(combined_before_search)
                    updated_criteria = dialog_state.get_criteria()
                    print(f"✅ Критерии сохранены перед началом поиска: {updated_criteria}")
                    if updated_criteria.get("mark"):
                        print(f"✅ Марка сохранена перед поиском: {updated_criteria['mark']}")
                
                # ВАЖНО: Также проверяем, есть ли интерпретированные критерии, которые не были сохранены
                # Это нужно для случаев, когда интерпретированные критерии (например, год) не попали в new_filters
                if descriptive_result.get("interpreted_criteria"):
                    current_criteria = dialog_state.get_criteria()
                    interpreted = descriptive_result["interpreted_criteria"].copy()
                    # Нормализуем значения для совместимости с поиском
                    if interpreted.get("gear_box_type") == "automatic":
                        interpreted["gear_box_type"] = "автомат"
                    elif interpreted.get("gear_box_type") == "manual":
                        interpreted["gear_box_type"] = "механика"
                    
                    # ВАЖНО: Сохраняем марку из текущих критериев, если она есть
                    if current_criteria.get("mark") and not interpreted.get("mark"):
                        interpreted["mark"] = current_criteria["mark"]
                        print(f"✅ Сохраняю марку из существующих критериев при добавлении интерпретированных: {current_criteria['mark']}")
                    
                    # Проверяем, есть ли в интерпретированных критериях что-то, чего нет в сохраненных
                    has_new_interpreted = any(
                        k not in current_criteria or current_criteria[k] != interpreted[k]
                        for k in interpreted.keys()
                    )
                    
                    if has_new_interpreted:
                        # Объединяем интерпретированные критерии с уже сохраненными
                        combined_with_interpreted = {**current_criteria, **interpreted}
                        dialog_state.update_criteria(combined_with_interpreted)
                        updated_criteria = dialog_state.get_criteria()
                        print(f"✅ Добавлены интерпретированные критерии к сохраненным: {updated_criteria}")
                        if updated_criteria.get("mark"):
                            print(f"✅ Марка сохранена в интерпретированных критериях: {updated_criteria['mark']}")
                
                # Обновляем saved_criteria для использования в поиске
                saved_criteria = dialog_state.get_criteria()
                print(f"📋 Финальные сохраненные критерии для поиска: {saved_criteria}")
                
                # ВАЖНО: НЕ формируем ответ через AI здесь, так как принято решение начать поиск
                # Продолжаем выполнение дальше, где начинается поиск через SQL-агента
                print(f"🚀 Пропускаю формирование ответа - начинаю поиск с сохраненными критериями")
        
        # Если мы дошли сюда, значит либо не проверяли намерение, либо решили начать поиск
        # Логируем решение
        if should_continue_dialogue:
            # Это не должно произойти, так как если should_continue_dialogue = True, мы должны были вернуть ответ выше
            print(f"⚠️ ОШИБКА: should_continue_dialogue = True, но мы дошли до SQL-агента")
            print(f"   Возвращаю ответ с needs_clarification=True")
            # Возвращаем ответ с needs_clarification, чтобы не продолжать дальше
            return SQLAgentResponse(
                success=True,
                answer="Понял, продолжаю уточнение критериев. Есть еще что-то, что нужно уточнить?",
                data=[],
                row_count=0,
                columns=[],
                needs_clarification=True
            )
        elif should_check_intent:
            intent_info = intent_result.get('intent', 'unknown') if 'intent_result' in locals() else 'unknown'
            print(f"🔍 Принято решение начать поиск (режим диалога: {in_dialogue_mode}, намерение: {intent_info})")
        else:
            print(f"🔍 Не проверяли намерение - начинаю поиск сразу (запрос с 3+ критериями и командой)")
        
        sql_agent = SQLAgentService(db)
        
        if request.generate_only:
            # Только генерация SQL без выполнения
            result = await sql_agent.generate_sql_from_natural_language(request.question)
            return SQLAgentResponse(
                success=result.get("success", False),
                sql=result.get("sql"),
                error=result.get("error")
            )
        else:
            # Полный цикл: генерация + выполнение
            # Если есть сохраненные критерии, формируем запрос ТОЛЬКО из критериев
            if saved_criteria:
                print(f"📋 Использую сохраненные критерии: {saved_criteria}")
                # Объединяем сохраненные критерии с новыми из запроса (если есть)
                # Используем AI с fallback на паттерны
                new_filters = await _extract_filters_with_ai(request.question)
                print(f"📋 Извлеченные критерии из запроса: {new_filters}")
                
                # ВАЖНО: Проверяем, что марка не потерялась при объединении
                # Если марка была в сохраненных критериях, но не в новых - сохраняем её
                if saved_criteria.get("mark") and not new_filters.get("mark"):
                    # Марка была сохранена, но не извлечена из нового запроса - сохраняем старую
                    print(f"✅ Сохраняю марку из сохраненных критериев: {saved_criteria['mark']}")
                    new_filters["mark"] = saved_criteria["mark"]
                # Если марка есть в новых фильтрах - используем её (она имеет приоритет)
                elif new_filters.get("mark"):
                    print(f"✅ Использую марку из нового запроса: {new_filters['mark']}")
                
                combined_filters = {**saved_criteria, **new_filters}  # Новые критерии имеют приоритет
                print(f"📋 Объединенные критерии (до удаления служебных полей): {combined_filters}")
                
                # Проверяем, что марка присутствует в объединенных критериях
                if combined_filters.get("mark"):
                    print(f"✅ Марка в объединенных критериях: {combined_filters['mark']}")
                else:
                    print(f"⚠️ ВНИМАНИЕ: Марка отсутствует в объединенных критериях!")
                
                # Извлекаем сортировку через ИИ
                sort_orders = await _extract_sorting_with_ai(
                    user_query=request.question,
                    extracted_filters=combined_filters
                )
                
                # Добавляем сортировку в combined_filters
                if sort_orders:
                    combined_filters["sort_orders"] = sort_orders
                
                # Удаляем служебные поля
                combined_filters.pop("show_all", None)
                
                print(f"📋 Объединенные критерии для поиска: {combined_filters}")
                
                # Проверяем, является ли текущий запрос подтверждением начала поиска
                query_lower = request.question.lower().strip()
                is_search_confirmation = query_lower in ["да", "да, хочу", "да хочу", "конечно", "начни", "начни поиск", "да, начни", "хочу", "ищу", "давай", "давай поиск"]
                
                # Формируем запрос ТОЛЬКО из критериев для SQL-агента
                # SQL-агенту не нужен запрос пользователя, только критерии
                criteria_parts = []
                if combined_filters.get("max_price"):
                    criteria_parts.append(f"до {combined_filters['max_price']:,} рублей")
                if combined_filters.get("min_price"):
                    criteria_parts.append(f"от {combined_filters['min_price']:,} рублей")
                if combined_filters.get("body_type"):
                    criteria_parts.append(f"кузов {combined_filters['body_type']}")
                if combined_filters.get("gear_box_type"):
                    criteria_parts.append(f"коробка {combined_filters['gear_box_type']}")
                if combined_filters.get("min_year"):
                    criteria_parts.append(f"год от {combined_filters['min_year']}")
                if combined_filters.get("max_year"):
                    criteria_parts.append(f"год до {combined_filters['max_year']}")
                if combined_filters.get("city"):
                    criteria_parts.append(f"в городе {combined_filters['city']}")
                if combined_filters.get("mark"):
                    criteria_parts.append(f"марка {combined_filters['mark']}")
                if combined_filters.get("model"):
                    criteria_parts.append(f"модель {combined_filters['model']}")
                if combined_filters.get("fuel_type"):
                    criteria_parts.append(f"топливо {combined_filters['fuel_type']}")
                if combined_filters.get("driving_gear_type"):
                    criteria_parts.append(f"привод {combined_filters['driving_gear_type']}")
                if combined_filters.get("engine_vol"):
                    criteria_parts.append(f"объем двигателя {combined_filters['engine_vol']} л")
                if combined_filters.get("power") or combined_filters.get("min_power"):
                    power_val = combined_filters.get("power") or combined_filters.get("min_power")
                    criteria_parts.append(f"мощность {power_val} л.с.")
                if combined_filters.get("color"):
                    criteria_parts.append(f"цвет {combined_filters['color']}")
                if combined_filters.get("mileage") or combined_filters.get("min_mileage") or combined_filters.get("max_mileage"):
                    if combined_filters.get("mileage"):
                        criteria_parts.append(f"пробег {combined_filters['mileage']} км")
                    elif combined_filters.get("min_mileage") and combined_filters.get("max_mileage"):
                        criteria_parts.append(f"пробег от {combined_filters['min_mileage']} до {combined_filters['max_mileage']} км")
                    elif combined_filters.get("min_mileage"):
                        criteria_parts.append(f"пробег от {combined_filters['min_mileage']} км")
                    elif combined_filters.get("max_mileage"):
                        criteria_parts.append(f"пробег до {combined_filters['max_mileage']} км")
                if combined_filters.get("car_type"):
                    car_type_text = "новый" if combined_filters['car_type'] == 'car' else "б/у"
                    criteria_parts.append(f"тип: {car_type_text}")
                
                if criteria_parts:
                    # Добавляем информацию о сортировке, если она есть
                    if combined_filters.get("sort_orders"):
                        sort_parts = []
                        for sort_order in combined_filters["sort_orders"]:
                            field = sort_order.get("field", "")
                            direction = sort_order.get("direction", "desc")
                            if field == "price":
                                if direction == "desc":
                                    sort_parts.append("отсортировать по цене от дорогих к дешевым")
                                else:
                                    sort_parts.append("отсортировать по цене от дешевых к дорогим")
                            elif field == "year":
                                if direction == "desc":
                                    sort_parts.append("отсортировать по году от новых к старым")
                                else:
                                    sort_parts.append("отсортировать по году от старых к новым")
                            elif field == "mileage":
                                if direction == "asc":
                                    sort_parts.append("отсортировать по пробегу от меньшего к большему")
                                else:
                                    sort_parts.append("отсортировать по пробегу от большего к меньшему")
                            elif field == "power":
                                if direction == "desc":
                                    sort_parts.append("отсортировать по мощности от большей к меньшей")
                                else:
                                    sort_parts.append("отсортировать по мощности от меньшей к большей")
                            elif field == "engine_vol":
                                if direction == "desc":
                                    sort_parts.append("отсортировать по объему двигателя от большего к меньшему")
                                else:
                                    sort_parts.append("отсортировать по объему двигателя от меньшего к большему")
                        if sort_parts:
                            criteria_parts.extend(sort_parts)
                    
                    # Формируем запрос ТОЛЬКО из критериев (без запроса пользователя)
                    extended_query = f"Подбери автомобиль: {', '.join(criteria_parts)}"
                    print(f"✅ Формирую запрос для SQL-агента ТОЛЬКО из критериев: {extended_query}")
                    print(f"📋 Все критерии переданы: {combined_filters}")
                else:
                    extended_query = "Подбери автомобиль"
            else:
                extended_query = request.question
            
            # 🚨 КРИТИЧЕСКИ ВАЖНО: НЕ добавляем контекст с найденными данными в SQL Agent!
            # SQL Agent должен генерировать SQL с условиями WHERE, а не с хардкодными данными
            # Контекст диалога может содержать результаты предыдущего поиска, что приведет к генерации SQL с хардкодными значениями
            
            # Отключаем перегенерацию SQL при 0 результатах, чтобы сразу использовать Elasticsearch
            # Передаем ТОЛЬКО чистый запрос пользователя или запрос из критериев, БЕЗ контекста с данными
            print(f"🔍 Передаю в SQL Agent чистый запрос (БЕЗ контекста с данными): {extended_query[:200]}...")
            result = await sql_agent.process_question(extended_query, try_alternative_on_zero=False)
            
            # Проверяем, что result не None
            if result is None:
                print(f"⚠️ SQL-агент вернул None, используем fallback на Elasticsearch")
                result = {"success": False, "data": [], "row_count": 0}
            
            # Проверяем, нужно ли использовать fallback:
            # 1. SQL-агент завершился ошибкой
            # 2. SQL-агент вернул 0 результатов
            sql_failed = not result.get("success")
            sql_zero_results = result.get("success") and (result.get("row_count", 0) == 0 or not result.get("data") or len(result.get("data", [])) == 0)
            
            # Если SQL-агент не справился или вернул 0 результатов, пробуем векторный поиск (PGEmbedding)
            vector_search_success = False
            if (sql_failed or sql_zero_results) and settings.get("vector_search_enabled", True):
                print(f"🔍 ШАГ 2: SQL-агент не справился, пробуем векторный поиск (PGEmbedding)...")
                try:
                    from services.database_service import DatabaseService
                    vector_search_service = VectorSearchService(db_session=db)
                    
                    # Выполняем векторный поиск
                    vector_results = await vector_search_service.similarity_search(
                        query=request.question,
                        k=20,  # Ищем до 20 похожих автомобилей
                        collection_name="cars_collection"
                    )
                    
                    if vector_results and len(vector_results) > 0:
                        print(f"✅ Векторный поиск нашел {len(vector_results)} результатов")
                        
                        # Преобразуем результаты векторного поиска в формат, совместимый с остальной системой
                        db_service = DatabaseService(db)
                        vector_cars = []
                        
                        # Ограничиваем до 5 лучших результатов для загрузки полных данных
                        top_results = vector_results[:5]
                        
                        for doc, score in top_results:
                            # Извлекаем ID автомобиля из метаданных документа
                            metadata = doc.metadata if hasattr(doc, 'metadata') else {}
                            # 🚨 КРИТИЧЕСКИ ВАЖНО: Используем car_id и type из метаданных
                            car_id = metadata.get('car_id') or metadata.get('id')
                            car_type = metadata.get('type') or metadata.get('car_type', 'car')
                            
                            # Логируем для отладки
                            if not car_id:
                                print(f"⚠️ ВНИМАНИЕ: Документ из векторного поиска не содержит car_id! Метаданные: {metadata}")
                                continue
                            
                            try:
                                # Загружаем полный объект автомобиля из БД
                                if car_type == 'used_car':
                                    full_car = db_service.get_used_car(car_id)
                                else:
                                    full_car = db_service.get_car(car_id)
                                
                                if full_car:
                                    # Обновляем объект из БД, чтобы получить все поля
                                    try:
                                        db.refresh(full_car)
                                    except:
                                        pass
                                    
                                    # Преобразуем в словарь со всеми полями
                                    car_dict = {}
                                    try:
                                        mapper = sql_inspect(full_car)
                                        if hasattr(mapper, 'columns'):
                                            for column in mapper.columns:
                                                attr_name = column.name
                                                try:
                                                    value = getattr(full_car, attr_name)
                                                    # Пропускаем только None значения, но сохраняем 0, False, пустые строки
                                                    if value is not None:
                                                        car_dict[attr_name] = value
                                                except Exception as attr_error:
                                                    # Игнорируем ошибки доступа к атрибутам
                                                    pass
                                    except Exception as inspect_error:
                                        print(f"⚠️ Ошибка при inspect для автомобиля {car_id}: {inspect_error}")
                                        # Fallback: используем __table__ напрямую
                                        if hasattr(full_car, '__table__'):
                                            for column in full_car.__table__.columns:
                                                attr_name = column.name
                                                try:
                                                    value = getattr(full_car, attr_name)
                                                    if value is not None:
                                                        car_dict[attr_name] = value
                                                except:
                                                    pass
                                    
                                    # Проверяем, что словарь не пустой
                                    if len(car_dict) < 5:
                                        print(f"⚠️ Автомобиль {car_id} имеет мало полей ({len(car_dict)}), проверяю загрузку...")
                                        # Пробуем загрузить основные поля вручную
                                        for attr in ['id', 'mark', 'model', 'price', 'manufacture_year', 'body_type', 'fuel_type', 'gear_box_type', 'driving_gear_type', 'city', 'mileage']:
                                            try:
                                                if hasattr(full_car, attr):
                                                    value = getattr(full_car, attr)
                                                    # Сохраняем даже если None, чтобы поле было в словаре
                                                    car_dict[attr] = value
                                            except Exception as attr_load_error:
                                                print(f"  ⚠️ Ошибка загрузки поля {attr}: {attr_load_error}")
                                    
                                    # Добавляем тип и score из векторного поиска
                                    car_dict['type'] = car_type
                                    car_dict['vector_score'] = score
                                    
                                    # Логируем для отладки
                                    print(f"✅ Автомобиль {car_id} загружен: {len(car_dict)} полей")
                                    print(f"   Марка={car_dict.get('mark')}, Модель={car_dict.get('model')}, Цена={car_dict.get('price')}, Год={car_dict.get('manufacture_year')}")
                                    print(f"   Кузов={car_dict.get('body_type')}, Коробка={car_dict.get('gear_box_type')}, Привод={car_dict.get('driving_gear_type')}, Топливо={car_dict.get('fuel_type')}")
                                    if car_type == 'used_car':
                                        print(f"   Пробег={car_dict.get('mileage')}, Город={car_dict.get('city')}")
                                    
                                    # Загружаем опции для новых автомобилей (только для Car, не для UsedCar)
                                    if car_type == 'car' and hasattr(full_car, 'options'):
                                        try:
                                            # Загружаем опции через relationship
                                            options_list = []
                                            options_groups_list = []
                                            
                                            # Получаем опции
                                            if full_car.options:
                                                for option in full_car.options:
                                                    if option.description:
                                                        options_list.append(option.description)
                                            
                                            # Получаем группы опций с их опциями
                                            if hasattr(full_car, 'options_groups') and full_car.options_groups:
                                                for group in full_car.options_groups:
                                                    group_info = {
                                                        'name': group.name or '',
                                                        'code': group.code or '',
                                                        'options': []
                                                    }
                                                    # Получаем опции из группы
                                                    if hasattr(group, 'options') and group.options:
                                                        for opt in group.options:
                                                            if opt.description:
                                                                group_info['options'].append(opt.description)
                                                    if group_info['name'] or group_info['options']:
                                                        options_groups_list.append(group_info)
                                            
                                            # Добавляем опции в словарь
                                            if options_list:
                                                car_dict['options'] = ', '.join(options_list)
                                                car_dict['options_list'] = options_list
                                            
                                            if options_groups_list:
                                                car_dict['options_groups'] = options_groups_list
                                                
                                        except Exception as opt_error:
                                            print(f"⚠️ Ошибка при загрузке опций для автомобиля {car_id}: {opt_error}")
                                    
                                    vector_cars.append(car_dict)
                                else:
                                    print(f"⚠️ Не удалось загрузить автомобиль {car_id} из БД (full_car = None)")
                            except Exception as load_error:
                                print(f"⚠️ Ошибка загрузки автомобиля {car_id} из векторного поиска: {load_error}")
                                import traceback
                                traceback.print_exc()
                        
                        if vector_cars:
                            print(f"✅ Векторный поиск: загружено {len(vector_cars)} автомобилей из БД (максимум 5)")
                            # Проверяем, что данные полные
                            for i, car in enumerate(vector_cars, 1):
                                print(f"   Автомобиль {i}: {len(car)} полей, ID={car.get('id')}, Марка={car.get('mark')}, Модель={car.get('model')}, Цена={car.get('price')}, Год={car.get('manufacture_year')}")
                            
                            # Преобразуем в формат Elasticsearch для совместимости
                            es_result = {
                                "hits": [{"_source": car} for car in vector_cars],
                                "total": len(vector_cars)
                            }
                            vector_search_success = True
                            
                            # Формируем результат в формате SQL-агента
                            result = {
                                "success": True,
                                "sql": "",
                                "data": vector_cars,
                                "columns": list(vector_cars[0].keys()) if vector_cars else [],
                                "row_count": len(vector_cars),
                                "answer": f"Найдено {len(vector_cars)} автомобилей (векторный поиск)",
                                "is_alternatives": False,
                                "fallback_source": "vector_search"
                            }
                        else:
                            print(f"⚠️ Векторный поиск: не удалось загрузить ни одного автомобиля из БД")
                    else:
                        print(f"⚠️ Векторный поиск не нашел результатов")
                        
                except Exception as vector_error:
                    print(f"⚠️ Ошибка векторного поиска: {vector_error}")
                    # Продолжаем на Elasticsearch
            
            # Если векторный поиск не справился, пробуем fallback на интеллектуальный поиск/Elasticsearch
            if not vector_search_success and (sql_failed or sql_zero_results) and settings.get("es_fallback_enabled", False):
                print(f"⚠️ Векторный поиск не справился, используем интеллектуальный поиск (IntelligentSearchService)...")
                try:
                    # Используем IntelligentSearchService для интеллектуального поиска с ослаблением фильтров
                    intelligent_search_service = IntelligentSearchService()
                    
                    # Извлекаем параметры из естественного языка
                    # Объединяем сохраненные критерии с новыми из запроса
                    # Используем AI с fallback на паттерны
                    new_filters = await _extract_filters_with_ai(request.question)
                    filters = {**saved_criteria, **new_filters}  # Новые критерии имеют приоритет
                    print(f"🔍 Использую объединенные фильтры для поиска: {filters}")
                    
                    # Выполняем интеллектуальный поиск с ослаблением фильтров
                    intelligent_result = await intelligent_search_service.search_with_intelligence(
                        initial_params={k: v for k, v in filters.items() if v is not None},
                        user_query=request.question,
                        dialogue_context=""
                    )
                    
                    # Проверяем результаты
                    if intelligent_result.get("success") and intelligent_result.get("total", 0) > 0:
                        hits = intelligent_result.get("results", [])
                        total = intelligent_result.get("total", 0)
                        relaxation_applied = intelligent_result.get("relaxation_applied", False)
                        
                        if relaxation_applied:
                            print(f"✅ Интеллектуальный поиск нашел {total} автомобилей после ослабления фильтров")
                        else:
                            print(f"✅ Интеллектуальный поиск нашел {total} автомобилей (точное совпадение)")
                        
                        # Используем результаты интеллектуального поиска
                        es_result = {
                            "hits": hits,
                            "total": total
                        }
                    else:
                        # Если интеллектуальный поиск не дал результатов, пробуем обычный Elasticsearch
                        print(f"⚠️ Интеллектуальный поиск не дал результатов, пробуем обычный Elasticsearch...")
                        es_service = ElasticsearchService()
                        if es_service.is_available():
                            # Извлекаем sort_orders из filters, если есть
                            sort_orders = filters.pop("sort_orders", None)
                            es_result = es_service.search_cars(
                                query=request.question,
                                limit=500,
                                sort_orders=sort_orders,
                                **{k: v for k, v in filters.items() if v is not None}
                            )
                        else:
                            es_result = {"hits": [], "total": 0}
                    
                    # Обрабатываем результаты Elasticsearch/IntelligentSearch только если векторный поиск не был успешен
                    if not vector_search_success:
                    # Проверяем, является ли запрос общим (нет конкретных критериев)
                        # Используем AI с fallback на паттерны
                        filters = await _extract_filters_with_ai(request.question)
                    has_specific_criteria = any([
                        filters.get("mark"), filters.get("model"), filters.get("min_price"), 
                        filters.get("max_price"), filters.get("min_year"), filters.get("max_year"),
                        filters.get("body_type"), filters.get("fuel_type"), filters.get("gear_box_type"),
                        filters.get("city"), filters.get("min_mileage"), filters.get("max_mileage")
                    ])
                    
                    # Обрабатываем результаты Elasticsearch/IntelligentSearch
                    skip_data_processing = False
                    if es_result.get("hits") and es_result.get("total", 0) > 0:
                        hits = es_result.get("hits", [])
                        total = es_result.get("total", 0)
                        
                        # Если запрос общий и найдено слишком много результатов - ведем диалог
                        if not has_specific_criteria and total > 100:
                            print(f"⚠️ Общий запрос с {total} результатами - ведем диалог вместо показа всех")
                            # Не показываем все результаты, а ведем диалог
                            result = {
                                "success": True,
                                "sql": "",
                                "data": [],  # Не показываем данные
                                "columns": [],
                                "row_count": 0,
                                "answer": "",  # Будет сформирован AI
                                "is_alternatives": False,
                                "fallback_source": "elasticsearch",
                                "needs_clarification": True,  # Помечаем, что нужны уточнения
                                "query_too_general": True
                            }
                            # Пропускаем обработку данных и переходим к формированию диалога
                            skip_data_processing = True
                    
                    # ВАЖНО: Результаты уже отсортированы по релевантности (_score) в Elasticsearch
                    # Сохраняем порядок при обработке
                    if not skip_data_processing and es_result.get("hits") and es_result.get("total", 0) > 0:
                        hits = es_result.get("hits", [])
                        total = es_result.get("total", 0)
                        if hits and total > 0:
                            print(f"✅ Найдено {total} автомобилей (показано {len(hits)})")
                            
                            # Преобразуем результаты Elasticsearch в формат SQL-агента
                            # Включаем ВСЕ поля из таблиц cars, used_cars и опций:
                            #
                            # ОБЩИЕ ПОЛЯ (для cars и used_cars):
                            # - Основные: id, mark, model, vin, title, doc_num
                            # - Цена: price, sale_price, stock_qty (только cars)
                            # - Технические: manufacture_year, model_year, fuel_type, power, body_type,
                            #   gear_box_type, driving_gear_type, engine_vol, engine, fuel_consumption,
                            #   max_torque, acceleration, max_speed, eco_class
                            # - Внешний вид: color, interior_color (только cars), color_code, interior_code,
                            #   pts_colour, door_qty (cars), doors (used_cars)
                            # - Размеры: dimensions, weight, cargo_volume
                            # - Комплектация: compl_level, code_compl, car_order_int_status
                            # - Локация: city, dealer_center, region (used_cars)
                            #
                            # ТОЛЬКО ДЛЯ НОВЫХ АВТО (cars):
                            # - Скидки: max_additional_discount, max_discount_trade_in, max_discount_credit,
                            #   max_discount_casko, max_discount_extra_gear, max_discount_life_insurance
                            # - Опции: options (из car_options и car_options_groups через JOIN)
                            #
                            # ТОЛЬКО ДЛЯ ПОДЕРЖАННЫХ АВТО (used_cars):
                            # - История: mileage, owners, accident, certification_number
                            # - Дополнительно: category, car_type, wheel_type, street,
                            #   generation_id, modification_id
                            #
                            # ПОЛЕ type: автоматически определяется по наличию mileage
                            es_data = []
                            es_columns = [
                                # Основные идентификаторы
                                "id", "mark", "model", "vin", "title", "doc_num",
                                # Цена и наличие
                                "price", "sale_price", "stock_qty",
                                # Технические характеристики
                                "manufacture_year", "model_year", "fuel_type", "power", "body_type",
                                "gear_box_type", "driving_gear_type", "engine_vol", "engine",
                                "fuel_consumption", "max_torque", "acceleration", "max_speed", "eco_class",
                                # Внешний вид и интерьер
                                "color", "interior_color", "color_code", "interior_code", "pts_colour",
                                "door_qty", "doors",
                                # Размеры и вес
                                "dimensions", "weight", "cargo_volume",
                                # Комплектация
                                "compl_level", "code_compl", "car_order_int_status",
                                # Локация и дилер
                                "city", "dealer_center", "region",
                                # Скидки (только для новых авто)
                                "max_additional_discount", "max_discount_trade_in", "max_discount_credit",
                                "max_discount_casko", "max_discount_extra_gear", "max_discount_life_insurance",
                                # Только для подержанных авто
                                "mileage", "owners", "accident", "certification_number",
                                "category", "car_type", "wheel_type", "street",
                                "generation_id", "modification_id",
                                # Опции (из Elasticsearch может быть в поле options или description)
                                # Опции из car_options и car_options_groups объединены в поле options
                                "options",
                                # Тип автомобиля (car или used_car)
                                "type"
                            ]
                            
                            for hit in hits:
                                source = hit.get("_source", {})
                                row = {}
                                
                                # Автоматически извлекаем все поля из источника
                                for col in es_columns:
                                    # Специальная обработка для некоторых полей
                                    if col == "type":
                                        # Определяем тип по наличию поля mileage
                                        value = source.get("type") or ("used_car" if source.get("mileage") is not None else "car")
                                        row[col] = value
                                    elif col == "options":
                                        # Опции могут быть в разных полях Elasticsearch
                                        value = source.get("options") or source.get("description") or source.get("options_text")
                                        if value:
                                            row[col] = value
                                    else:
                                        # Прямое получение значения из source
                                        value = source.get(col)
                                        if value is not None:
                                            row[col] = value
                                
                                # Убеждаемся, что тип установлен
                                if "type" not in row:
                                    row["type"] = "used_car" if source.get("mileage") is not None else "car"
                                
                                # Добавляем информацию об опциях, если доступна
                                car_type = row.get("type", "car")
                                if car_type == "car" and (source.get("options") or source.get("description")):
                                    row["has_options"] = True
                                
                                es_data.append(row)
                            
                            # ВАЖНО: Загружаем полные объекты автомобилей из БД по ID
                            # чтобы передать ИИ ВСЕ поля, а не только из Elasticsearch
                            # ВАЖНО: Сохраняем порядок результатов из Elasticsearch (по релевантности)
                            from services.database_service import DatabaseService
                            db_service_temp = DatabaseService(db)
                            full_es_data = []
                            
                            # Обрабатываем результаты в том же порядке, в котором они пришли из Elasticsearch
                            # (отсортированы по релевантности _score)
                            for record in es_data:
                                car_id = record.get("id")
                                if car_id:
                                    # Определяем тип автомобиля
                                    car_type = record.get("type")
                                    has_mileage = record.get("mileage") is not None
                                    
                                    full_car = None
                                    try:
                                        if car_type == "used_car" or has_mileage:
                                            # Пробуем загрузить как подержанный
                                            full_car = db_service_temp.get_used_car(car_id)
                                            if not full_car:
                                                # Если не нашли, пробуем как новый
                                                full_car = db_service_temp.get_car(car_id)
                                        else:
                                            # Пробуем загрузить как новый
                                            full_car = db_service_temp.get_car(car_id)
                                            if not full_car:
                                                # Если не нашли, пробуем как подержанный
                                                full_car = db_service_temp.get_used_car(car_id)
                                        
                                        # Убеждаемся, что объект привязан к сессии
                                        if full_car:
                                            # Обновляем объект из БД, чтобы получить все поля
                                            db.refresh(full_car)
                                    except Exception as load_error:
                                        print(f"⚠️ Ошибка при загрузке автомобиля {car_id}: {load_error}")
                                        full_car = None
                                    
                                    if full_car:
                                        # Преобразуем объект SQLAlchemy в словарь со всеми полями
                                        car_dict = {}
                                        try:
                                            # Используем __table__.columns для получения всех колонок модели
                                            mapper = sql_inspect(full_car)
                                            if hasattr(mapper, 'columns'):
                                                for column in mapper.columns:
                                                    attr_name = column.name
                                                    try:
                                                        value = getattr(full_car, attr_name)
                                                        car_dict[attr_name] = value
                                                    except:
                                                        pass
                                            else:
                                                # Fallback: используем __table__ напрямую
                                                if hasattr(full_car, '__table__'):
                                                    for column in full_car.__table__.columns:
                                                        attr_name = column.name
                                                        try:
                                                            value = getattr(full_car, attr_name)
                                                            car_dict[attr_name] = value
                                                        except:
                                                            pass
                                        except Exception as inspect_error:
                                            # Если sql_inspect не работает, используем альтернативный способ
                                            print(f"⚠️ Ошибка при inspect для автомобиля {car_id}: {inspect_error}")
                                            # Используем __table__ напрямую
                                            if hasattr(full_car, '__table__'):
                                                for column in full_car.__table__.columns:
                                                    attr_name = column.name
                                                    try:
                                                        value = getattr(full_car, attr_name)
                                                        car_dict[attr_name] = value
                                                    except:
                                                        pass
                                        
                                        # Проверяем, что словарь не пустой
                                        if not car_dict or len(car_dict) < 3:
                                            print(f"⚠️ Автомобиль {car_id} имеет мало полей ({len(car_dict)}), используем исходные данные")
                                            # Если словарь почти пустой, используем исходные данные из ES
                                            car_dict = record.copy()
                                        else:
                                            # Объединяем с исходными данными, чтобы не потерять информацию
                                            for key, value in record.items():
                                                if key not in car_dict or (car_dict.get(key) is None and value is not None):
                                                    car_dict[key] = value
                                        
                                        # Добавляем тип автомобиля
                                        if hasattr(full_car, 'mileage') and full_car.mileage is not None:
                                            car_dict['type'] = 'used_car'
                                        else:
                                            car_dict['type'] = 'car'
                                        
                                        # Загружаем опции для новых автомобилей (только для Car, не для UsedCar)
                                        if car_dict['type'] == 'car' and hasattr(full_car, 'options'):
                                            try:
                                                # Загружаем опции через relationship
                                                options_list = []
                                                options_groups_list = []
                                                
                                                # Получаем опции
                                                if full_car.options:
                                                    for option in full_car.options:
                                                        if option.description:
                                                            options_list.append(option.description)
                                                
                                                # Получаем группы опций с их опциями
                                                if hasattr(full_car, 'options_groups') and full_car.options_groups:
                                                    for group in full_car.options_groups:
                                                        group_info = {
                                                            'name': group.name or '',
                                                            'code': group.code or '',
                                                            'options': []
                                                        }
                                                        # Получаем опции из группы
                                                        if hasattr(group, 'options') and group.options:
                                                            for opt in group.options:
                                                                if opt.description:
                                                                    group_info['options'].append(opt.description)
                                                        if group_info['name'] or group_info['options']:
                                                            options_groups_list.append(group_info)
                                                
                                                # Добавляем опции в словарь
                                                if options_list:
                                                    car_dict['options'] = ', '.join(options_list)
                                                    car_dict['options_list'] = options_list
                                                
                                                if options_groups_list:
                                                    car_dict['options_groups'] = options_groups_list
                                                    
                                            except Exception as opt_error:
                                                print(f"⚠️ Ошибка при загрузке опций для автомобиля {car_id}: {opt_error}")
                                        
                                        full_es_data.append(car_dict)
                                    else:
                                        # Если не удалось загрузить полный объект, используем данные из ES
                                        full_es_data.append(record)
                                else:
                                    # Если нет ID, используем данные как есть
                                    full_es_data.append(record)
                            
                            # Формируем результат в формате SQL-агента
                            # Проверяем, являются ли результаты альтернативами или точными совпадениями
                            # Если SQL-запрос был с ошибкой (неправильное поле), но Elasticsearch нашел результаты,
                            # это может быть точное совпадение, а не альтернатива
                            sql_had_error = not result.get("success", False) or (result.get("error") is not None)
                            is_alternatives = sql_had_error and total > 0  # Альтернативы только если SQL был с ошибкой
                            
                            result = {
                                "success": True,
                                "sql": result.get("sql", ""),  # Сохраняем исходный SQL, если был
                                "data": full_es_data,  # Используем полные данные из БД
                                "columns": es_columns,
                                "row_count": total,
                                "answer": f"Найдено {total} автомобилей",  # Будет переформатировано AI
                                "is_alternatives": False,  # Fallback после ошибки SQL - это точные совпадения, не альтернативы
                                "fallback_source": "elasticsearch"
                            }
                        else:
                            print(f"⚠️ Elasticsearch не нашел результатов")
                            # Если Elasticsearch не нашел результатов, все равно помечаем как альтернативы
                            # и используем AI для формирования ответа
                            if "is_alternatives" not in result:
                               result["is_alternatives"] = True
                            if "fallback_source" not in result:
                               result["fallback_source"] = "elasticsearch"
                    else:
                        print(f"⚠️ Elasticsearch недоступен")
                except Exception as es_error:
                    print(f"❌ Ошибка fallback на Elasticsearch: {es_error}")
                    # Продолжаем с ошибкой SQL-агента
            
            # Проверяем, нужно ли вести диалог для общего запроса
            # Если query_too_general = True, сразу формируем диалог, минуя обработку данных
            query_too_general = result.get("query_too_general", False)
            
            if result.get("success") and not query_too_general:
                print(f"✅ SQL-агент успешно обработал запрос. Найдено записей: {result.get('row_count', 0)}")
                
                result_data = result.get("data")
                row_count = result.get("row_count", 0)
                
                # 🚨 КРИТИЧЕСКИ ВАЖНО: Если SQL-агент успешно вернул результаты, НЕ делаем повторный поиск!
                # Данные уже получены из БД, не нужно обращаться к Elasticsearch повторно
                if result_data and len(result_data) > 0 and row_count > 0:
                    print(f"✅ SQL-агент вернул {row_count} результатов. Используем эти данные, НЕ делаем повторный поиск.")
                    # Продолжаем обработку результатов SQL-агента, пропуская fallback
                
                # Если SQL-агент вернул 0 результатов И еще не использовали Elasticsearch fallback,
                # пробуем найти альтернативы с ослабленными фильтрами
                # (fallback уже обработал случай ошибки SQL-агента)
                elif (result_data is None or len(result_data) == 0) and row_count == 0 and not result.get("is_alternatives"):
                    print(f"🔍 SQL-агент не нашел результатов, ищем альтернативы...")
                    
                    try:
                        # Извлекаем фильтры из исходного запроса
                        # Используем AI с fallback на паттерны
                        filters = await _extract_filters_with_ai(request.question)
                        
                        # Извлекаем сортировку через ИИ
                        sort_orders = await _extract_sorting_with_ai(
                            user_query=request.question,
                            extracted_filters=filters
                        )
                        
                        # Добавляем сортировку в filters
                        if sort_orders:
                            filters["sort_orders"] = sort_orders
                        
                        # Ослабляем фильтры для поиска альтернатив
                        relaxed_filters = _relax_filters_for_alternatives(filters, request.question)
                        
                        # Формируем новый запрос для поиска альтернатив
                        # Сначала пробуем через Elasticsearch с ослабленными фильтрами
                        es_service = ElasticsearchService()
                        if es_service.is_available():
                            print(f"🔍 Поиск альтернатив через Elasticsearch с ослабленными фильтрами...")
                            
                            # Формируем запрос для альтернатив
                            # Убираем строгие условия из исходного запроса
                            alternative_query = request.question
                            
                            # Пробуем найти через Elasticsearch с ослабленными фильтрами
                            # Извлекаем sort_orders из relaxed_filters, если есть
                            sort_orders = relaxed_filters.pop("sort_orders", None)
                            es_result = es_service.search_cars(
                                query=alternative_query,
                                limit=500,
                                sort_orders=sort_orders,
                                **{k: v for k, v in relaxed_filters.items() if v is not None}
                            )
                            
                            hits = es_result.get("hits", [])
                            total = es_result.get("total", 0)
                            
                            # ВАЖНО: Результаты уже отсортированы по релевантности (_score) в Elasticsearch
                            # Сохраняем порядок при обработке
                            if hits and total > 0:
                                print(f"✅ Найдено {total} альтернативных автомобилей через Elasticsearch")
                                
                                # Преобразуем результаты Elasticsearch в формат SQL-агента
                                # (используем ту же логику, что и для fallback)
                                from services.database_service import DatabaseService
                                db_service_alt = DatabaseService(db)
                                # ВАЖНО: Сохраняем порядок результатов из Elasticsearch (по релевантности)
                                full_es_data = []
                                
                                es_columns = [
                                    "id", "mark", "model", "vin", "title", "doc_num",
                                    "price", "sale_price", "stock_qty",
                                    "manufacture_year", "model_year", "fuel_type", "power", "body_type",
                                    "gear_box_type", "driving_gear_type", "engine_vol", "engine",
                                    "fuel_consumption", "max_torque", "acceleration", "max_speed", "eco_class",
                                    "color", "interior_color", "color_code", "interior_code", "pts_colour",
                                    "door_qty", "doors",
                                    "dimensions", "weight", "cargo_volume",
                                    "compl_level", "code_compl", "car_order_int_status",
                                    "city", "dealer_center", "region",
                                    "max_additional_discount", "max_discount_trade_in", "max_discount_credit",
                                    "max_discount_casko", "max_discount_extra_gear", "max_discount_life_insurance",
                                    "mileage", "owners", "accident", "certification_number",
                                    "category", "car_type", "wheel_type", "street",
                                    "generation_id", "modification_id",
                                    "options", "type"
                                ]
                                
                                # ВАЖНО: Сохраняем порядок результатов из Elasticsearch (по релевантности)
                                es_data = []
                                for hit in hits:
                                    source = hit.get("_source", {})
                                    row = {}
                                    
                                    for col in es_columns:
                                        if col == "type":
                                            value = source.get("type") or ("used_car" if source.get("mileage") is not None else "car")
                                            row[col] = value
                                        elif col == "options":
                                            value = source.get("options") or source.get("description") or source.get("options_text")
                                            if value:
                                                row[col] = value
                                        else:
                                            value = source.get(col)
                                            if value is not None:
                                                row[col] = value
                                    
                                    if "type" not in row:
                                        row["type"] = "used_car" if source.get("mileage") is not None else "car"
                                    
                                    es_data.append(row)
                                
                                # Загружаем полные объекты из БД (аналогично fallback логике)
                                for record in es_data:
                                    car_id = record.get("id")
                                    if car_id:
                                        car_type = record.get("type")
                                        has_mileage = record.get("mileage") is not None
                                        
                                        full_car = None
                                        try:
                                            if car_type == "used_car" or has_mileage:
                                                full_car = db_service_alt.get_used_car(car_id)
                                                if not full_car:
                                                    full_car = db_service_alt.get_car(car_id)
                                            else:
                                                full_car = db_service_alt.get_car(car_id)
                                                if not full_car:
                                                    full_car = db_service_alt.get_used_car(car_id)
                                            
                                            if full_car:
                                                db.refresh(full_car)
                                                # Преобразуем в словарь (упрощенная версия)
                                                car_dict = {}
                                                try:
                                                    mapper = sql_inspect(full_car)
                                                    if hasattr(mapper, 'columns'):
                                                        for column in mapper.columns:
                                                            attr_name = column.name
                                                            try:
                                                                value = getattr(full_car, attr_name)
                                                                car_dict[attr_name] = value
                                                            except:
                                                                pass
                                                    else:
                                                        if hasattr(full_car, '__table__'):
                                                            for column in full_car.__table__.columns:
                                                                attr_name = column.name
                                                                try:
                                                                    value = getattr(full_car, attr_name)
                                                                    car_dict[attr_name] = value
                                                                except:
                                                                    pass
                                                except:
                                                    if hasattr(full_car, '__table__'):
                                                        for column in full_car.__table__.columns:
                                                            attr_name = column.name
                                                            try:
                                                                value = getattr(full_car, attr_name)
                                                                car_dict[attr_name] = value
                                                            except:
                                                                pass
                                                
                                                if not car_dict or len(car_dict) < 3:
                                                    car_dict = record.copy()
                                                else:
                                                    for key, value in record.items():
                                                        if key not in car_dict or (car_dict.get(key) is None and value is not None):
                                                            car_dict[key] = value
                                                
                                                if hasattr(full_car, 'mileage') and full_car.mileage is not None:
                                                    car_dict['type'] = 'used_car'
                                                else:
                                                    car_dict['type'] = 'car'
                                                
                                                # Загружаем опции для новых автомобилей
                                                if car_dict['type'] == 'car' and hasattr(full_car, 'options'):
                                                    try:
                                                        options_list = []
                                                        if full_car.options:
                                                            for option in full_car.options:
                                                                if option.description:
                                                                    options_list.append(option.description)
                                                        
                                                        if options_list:
                                                            car_dict['options'] = ', '.join(options_list)
                                                            car_dict['options_list'] = options_list
                                                    except:
                                                        pass
                                                
                                                full_es_data.append(car_dict)
                                            else:
                                                full_es_data.append(record)
                                        except Exception as load_error:
                                            print(f"⚠️ Ошибка при загрузке альтернативного автомобиля {car_id}: {load_error}")
                                            full_es_data.append(record)
                                    else:
                                        full_es_data.append(record)
                                
                                # Обновляем результат с альтернативами
                                result = {
                                    "success": True,
                                    "sql": result.get("sql", ""),  # Сохраняем исходный SQL
                                    "data": full_es_data,
                                    "columns": es_columns,
                                    "row_count": total,
                                    "answer": f"По вашему запросу ничего не найдено, но мы нашли {total} похожих альтернатив",
                                    "is_alternatives": True,  # Пометка, что это альтернативы
                                    "fallback_source": "elasticsearch_alternatives"
                                }
                                
                                result_data = full_es_data
                                row_count = total
                                print(f"✅ Альтернативы найдены: {total} автомобилей")
                            else:
                                print(f"⚠️ Альтернативы не найдены даже с ослабленными фильтрами")
                        else:
                            print(f"⚠️ Elasticsearch недоступен для поиска альтернатив")
                    except Exception as alt_error:
                        print(f"❌ Ошибка при поиске альтернатив: {alt_error}")
                        # Продолжаем с исходным результатом (0 записей)
                
                # Если есть данные, отправляем первые 5 записей в AI для форматирования
                # Пропускаем, если это общий запрос (query_too_general) - он обрабатывается в блоке else
                if result.get("query_too_general"):
                    # Общий запрос - пропускаем обработку данных, формируем диалог в блоке else
                    # Устанавливаем result_data = None, чтобы попасть в блок else
                    result_data = None
                    row_count = 0
                elif result_data is not None and len(result_data) > 0:
                    try:
                        from services.database_service import DatabaseService
                        from services.rag_service import RAGService
                        
                        db_service = DatabaseService(db)
                        rag_service = RAGService(db_service)
                        
                        # Формируем контекст из данных (SQL-агент или Elasticsearch fallback)
                        # Для AI используем только первые 5, но для источников будут все данные
                        all_data = result_data if result_data is not None else []
                        # Ограничиваем до 5 для AI-форматирования, но загружаем полные данные для всех
                        data_records = all_data[:5] if all_data else []  # Ограничиваем до 5 для AI-форматирования
                        data_columns = result.get("columns", [])
                        query_info = result.get("sql", "")
                        total_count = result.get("row_count", len(all_data))
                        fallback_source = result.get("fallback_source")
                        
                        # ВАЖНО: Загружаем полные объекты автомобилей из БД по ID
                        # чтобы передать ИИ ВСЕ поля, а не только выбранные в SQL-запросе
                        full_car_records = []
                        for record in data_records:
                            # Проверяем, не загружены ли уже полные данные (из векторного поиска)
                            # Если в записи уже есть много полей (больше 10), значит данные уже полные
                            if len(record) > 10 and record.get("id") and record.get("mark"):
                                # Данные уже полные, используем их как есть
                                print(f"✅ Запись {record.get('id')} уже содержит полные данные ({len(record)} полей), пропускаем загрузку")
                                full_car_records.append(record)
                                continue
                            
                            car_id = record.get("id")
                            if car_id:
                                # Определяем тип автомобиля
                                car_type = record.get("type")
                                has_mileage = record.get("mileage") is not None
                                
                                full_car = None
                                try:
                                    if car_type == "used_car" or has_mileage:
                                        # Пробуем загрузить как подержанный
                                        full_car = db_service.get_used_car(car_id)
                                        if not full_car:
                                            # Если не нашли, пробуем как новый
                                            full_car = db_service.get_car(car_id)
                                    else:
                                        # Пробуем загрузить как новый
                                        full_car = db_service.get_car(car_id)
                                        if not full_car:
                                            # Если не нашли, пробуем как подержанный
                                            full_car = db_service.get_used_car(car_id)
                                    
                                    # Убеждаемся, что объект привязан к сессии
                                    if full_car:
                                        # Обновляем объект из БД, чтобы получить все поля
                                        db.refresh(full_car)
                                except Exception as load_error:
                                    print(f"⚠️ Ошибка при загрузке автомобиля {car_id}: {load_error}")
                                    full_car = None
                                
                                if full_car:
                                    # Преобразуем объект SQLAlchemy в словарь со всеми полями
                                    car_dict = {}
                                    try:
                                        # Используем __table__.columns для получения всех колонок модели
                                        mapper = sql_inspect(full_car)
                                        if hasattr(mapper, 'columns'):
                                            for column in mapper.columns:
                                                attr_name = column.name
                                                try:
                                                    value = getattr(full_car, attr_name)
                                                    car_dict[attr_name] = value
                                                except:
                                                    pass
                                        else:
                                            # Fallback: используем __table__ напрямую
                                            if hasattr(full_car, '__table__'):
                                                for column in full_car.__table__.columns:
                                                    attr_name = column.name
                                                    try:
                                                        value = getattr(full_car, attr_name)
                                                        car_dict[attr_name] = value
                                                    except:
                                                        pass
                                    except Exception as inspect_error:
                                        # Если sql_inspect не работает, используем альтернативный способ
                                        print(f"⚠️ Ошибка при inspect для автомобиля {car_id}: {inspect_error}")
                                        # Используем __table__ напрямую
                                        if hasattr(full_car, '__table__'):
                                            for column in full_car.__table__.columns:
                                                attr_name = column.name
                                                try:
                                                    value = getattr(full_car, attr_name)
                                                    car_dict[attr_name] = value
                                                except:
                                                    pass
                                    
                                    # Проверяем, что словарь не пустой
                                    if not car_dict or len(car_dict) < 3:
                                        print(f"⚠️ Автомобиль {car_id} имеет мало полей ({len(car_dict)}), используем исходные данные")
                                        # Если словарь почти пустой, используем исходные данные из SQL
                                        car_dict = record.copy()
                                    else:
                                        # Объединяем с исходными данными, чтобы не потерять информацию
                                        for key, value in record.items():
                                            if key not in car_dict or (car_dict.get(key) is None and value is not None):
                                                car_dict[key] = value
                                    
                                    # Добавляем тип автомобиля
                                    if hasattr(full_car, 'mileage') and full_car.mileage is not None:
                                        car_dict['type'] = 'used_car'
                                    else:
                                        car_dict['type'] = 'car'
                                    
                                    # Загружаем опции для новых автомобилей (только для Car, не для UsedCar)
                                    if car_dict['type'] == 'car' and hasattr(full_car, 'options'):
                                        try:
                                            # Загружаем опции через relationship
                                            options_list = []
                                            options_groups_list = []
                                            
                                            # Получаем опции
                                            if full_car.options:
                                                for option in full_car.options:
                                                    if option.description:
                                                        options_list.append(option.description)
                                            
                                            # Получаем группы опций с их опциями
                                            if hasattr(full_car, 'options_groups') and full_car.options_groups:
                                                for group in full_car.options_groups:
                                                    group_info = {
                                                        'name': group.name or '',
                                                        'code': group.code or '',
                                                        'options': []
                                                    }
                                                    # Получаем опции из группы
                                                    if hasattr(group, 'options') and group.options:
                                                        for opt in group.options:
                                                            if opt.description:
                                                                group_info['options'].append(opt.description)
                                                    if group_info['name'] or group_info['options']:
                                                        options_groups_list.append(group_info)
                                            
                                            # Добавляем опции в словарь
                                            if options_list:
                                                car_dict['options'] = ', '.join(options_list)
                                                car_dict['options_list'] = options_list
                                            
                                            if options_groups_list:
                                                car_dict['options_groups'] = options_groups_list
                                                
                                        except Exception as opt_error:
                                            print(f"⚠️ Ошибка при загрузке опций для автомобиля {car_id}: {opt_error}")
                                    
                                    full_car_records.append(car_dict)
                                else:
                                    # Если не удалось загрузить полный объект, используем данные из SQL
                                    full_car_records.append(record)
                            else:
                                # Если нет ID, используем данные как есть
                                full_car_records.append(record)
                        
                        # Используем полные данные вместо ограниченных
                        data_records = full_car_records
                        
                        # Логируем данные для отладки
                        print(f"📊 Данные для AI: {len(data_records)} записей из {total_count}")
                        print(f"🚨 КРИТИЧЕСКИ ВАЖНО: total_count = {total_count}, len(data_records) = {len(data_records)}")
                        if total_count > 0 and len(data_records) == 0:
                            print(f"⚠️ ВНИМАНИЕ: total_count > 0, но data_records пустой! Это может быть проблемой!")
                        if data_records:
                            first_record = data_records[0]
                            print(f"📋 Первая запись (ключи): {list(first_record.keys())}")
                            print(f"📋 Количество полей в первой записи: {len(first_record)}")
                            
                            # Проверяем наличие ключевых полей
                            key_fields = ['id', 'mark', 'model', 'price', 'manufacture_year', 'body_type', 'gear_box_type', 'fuel_type', 'driving_gear_type', 'city']
                            missing_fields = [field for field in key_fields if field not in first_record or first_record.get(field) is None]
                            if missing_fields:
                                print(f"⚠️ ВНИМАНИЕ: В первой записи отсутствуют поля: {missing_fields}")
                            else:
                                print(f"✅ Все ключевые поля присутствуют в первой записи")
                            
                            if 'mark' in first_record:
                                print(f"📋 Марка в первой записи: {first_record.get('mark')}")
                            if 'body_type' in first_record:
                                print(f"📋 Тип кузова в первой записи: {first_record.get('body_type')}")
                            if 'gear_box_type' in first_record:
                                print(f"📋 Коробка в первой записи: {first_record.get('gear_box_type')}")
                            if 'price' in first_record:
                                print(f"📋 Цена в первой записи: {first_record.get('price')}")
                            if 'manufacture_year' in first_record:
                                print(f"📋 Год в первой записи: {first_record.get('manufacture_year')}")
                            
                            # Проверяем, сколько записей соответствуют критериям
                            sedan_count = sum(1 for r in data_records if r.get('body_type') and ('седан' in str(r.get('body_type')).lower() or 'sedan' in str(r.get('body_type')).lower()))
                            auto_count = sum(1 for r in data_records if r.get('gear_box_type') and ('автомат' in str(r.get('gear_box_type')).lower() or 'automatic' in str(r.get('gear_box_type')).lower()))
                            bmw_count = sum(1 for r in data_records if r.get('mark') and ('bmw' in str(r.get('mark')).upper() or 'бмв' in str(r.get('mark')).lower()))
                            print(f"📊 В первых {len(data_records)} записях: седанов={sedan_count}, автоматов={auto_count}, BMW={bmw_count}")
                            
                            # Логируем все записи для отладки
                            for i, record in enumerate(data_records, 1):
                                print(f"📋 Запись {i}: ID={record.get('id')}, Марка={record.get('mark')}, Модель={record.get('model')}, Цена={record.get('price')}, Год={record.get('manufacture_year')}, Кузов={record.get('body_type')}, Коробка={record.get('gear_box_type')}, Пробег={record.get('mileage')}")
                        else:
                            print(f"⚠️ ВНИМАНИЕ: data_records пустой, хотя total_count = {total_count}!")
                        
                        # Определяем источник данных для промпта
                        is_alternatives = result.get("is_alternatives", False)
                        sql_had_error = result.get("error") is not None
                        
                        # Если SQL был с ошибкой, но Elasticsearch нашел результаты - это могут быть точные совпадения
                        # Помечаем как альтернативы только если действительно использовался ослабленный поиск
                        if sql_had_error and fallback_source == "elasticsearch" and result.get("row_count", 0) > 0:
                            # SQL не сработал, но Elasticsearch нашел результаты - скорее всего это точные совпадения
                            is_alternatives = False
                            print(f"✅ Elasticsearch fallback нашел {result.get('row_count', 0)} результатов - считаем точными совпадениями")
                        
                        if fallback_source == "elasticsearch" or fallback_source == "elasticsearch_alternatives":
                            data_source_text = "Elasticsearch поиск"
                            query_prefix = "Поисковый запрос"
                        else:
                            data_source_text = "SQL запрос"
                            query_prefix = "SQL"
                        
                        # Если это альтернативы, добавляем пометку
                        # Показываем предупреждение об альтернативах только если действительно это альтернативы
                        # Если fallback нашел результаты после ошибки SQL, но они соответствуют запросу - не показываем предупреждение
                        if is_alternatives and fallback_source == "elasticsearch":
                            # Проверяем, действительно ли это альтернативы или точные совпадения
                            # Если SQL был с ошибкой (неправильное поле), но результаты соответствуют запросу - это не альтернативы
                            if sql_had_error:
                                # SQL был с ошибкой, но результаты могут быть точными - не показываем предупреждение
                                alternatives_note = ""
                            else:
                                alternatives_note = "\n\n⚠️ ВАЖНО: По вашему точному запросу ничего не найдено. Ниже показаны похожие альтернативы с ослабленными критериями поиска. Эти автомобили могут отличаться от ваших требований, но могут быть интересны как варианты."
                        else:
                            alternatives_note = ""
                        
                        # Создаем текстовое представление данных для AI
                        context_text = f"Результаты {data_source_text}:\n"
                        if query_info:
                            context_text += f"{query_prefix}: {query_info}\n\n"
                        context_text += f"Найдено записей: {total_count}\n"
                        context_text += f"Показано первых {len(data_records)} записей:\n\n"
                        
                        # Добавляем пометку об альтернативах, если это альтернативы
                        if is_alternatives:
                            context_text += alternatives_note + "\n\n"
                        
                        # Форматируем данные в таблицу со ВСЕМИ полями
                        if data_records:
                            # Собираем все уникальные колонки из всех записей
                            all_columns = set()
                            for record in data_records:
                                all_columns.update(record.keys())
                            
                            # Сортируем колонки: сначала важные, потом остальные
                            priority_columns = [
                                "id", "type", "mark", "model", "price", "sale_price", "city", 
                                "body_type", "fuel_type", "manufacture_year", "model_year",
                                "gear_box_type", "driving_gear_type", "mileage", "color", 
                                "power", "engine_vol", "engine", "owners", "accident",
                                "vin", "dealer_center", "region", "stock_qty", 
                                "options", "options_list", "options_groups"  # Опции автомобиля
                            ]
                            
                            # Формируем список колонок: сначала приоритетные, потом остальные
                            display_columns = []
                            for col in priority_columns:
                                if col in all_columns:
                                    display_columns.append(col)
                            # Добавляем остальные колонки
                            for col in sorted(all_columns):
                                if col not in display_columns:
                                    display_columns.append(col)
                            
                            if display_columns:
                                context_text += "| " + " | ".join(str(col) for col in display_columns) + " |\n"
                                context_text += "|" + "|".join(["---" for _ in display_columns]) + "|\n"
                                for row in data_records:
                                    row_values = []
                                    for col in display_columns:
                                        value = row.get(col)
                                        if value is None:
                                            row_values.append("")
                                        elif isinstance(value, list):
                                            # Форматируем списки (например, options_list)
                                            if value and isinstance(value[0], dict):
                                                # Список словарей (например, options_groups)
                                                formatted = "; ".join([
                                                    f"{item.get('name', '')}: {', '.join(item.get('options', []))}"
                                                    if item.get('options') else item.get('name', '')
                                                    for item in value
                                                ])
                                                row_values.append(formatted)
                                            else:
                                                # Обычный список строк
                                                row_values.append(", ".join(str(v) for v in value))
                                        elif isinstance(value, dict):
                                            # Форматируем словари
                                            row_values.append(str(value))
                                        else:
                                            row_values.append(str(value))
                                    context_text += "| " + " | ".join(row_values) + " |\n"
                        
                        # Формируем промпт для AI в стиле автоэксперта
                        # Определяем, действительно ли это альтернативы
                        sql_had_error = result.get("error") is not None
                        
                        # Если SQL был с ошибкой, но Elasticsearch нашел результаты - это точные совпадения, не альтернативы
                        if sql_had_error and fallback_source == "elasticsearch" and result.get("row_count", 0) > 0:
                            is_alternatives = False
                            data_source_desc = "Elasticsearch поиска"
                            alternatives_warning = ""
                        elif is_alternatives and not sql_had_error:
                            # Это альтернативы (ослабленный поиск после 0 результатов)
                            data_source_desc = "поиска альтернатив (Elasticsearch)"
                            alternatives_warning = "\n\n⚠️ ВАЖНО: Это альтернативные варианты! По точному запросу пользователя ничего не найдено. Обязательно начни ответ с фразы: \"По вашему точному запросу ничего не найдено, но мы подобрали похожие альтернативы:\" и объясни, чем эти варианты отличаются от запроса пользователя."
                        elif fallback_source:
                            # Fallback нашел результаты после ошибки SQL - это могут быть точные совпадения
                            data_source_desc = "Elasticsearch поиска"
                            alternatives_warning = ""
                        else:
                            data_source_desc = "SQL-запроса"
                            alternatives_warning = ""
                        
                        ai_prompt = f"""Ты — автоэксперт и персональный помощник по подбору автомобиля.

🚨 КРИТИЧЕСКИ ВАЖНО: ВСЕГДА отвечай ТОЛЬКО на РУССКОМ языке! 
- НЕ используй английский язык в ответах!
- НЕ переключайся на английский!
- Все ответы должны быть на русском языке!

Твой стиль — кратко, по делу, профессионально. Избегай воды.

🚨 КРИТИЧЕСКИ ВАЖНО: ОСНОВЫВАЙСЯ ТОЛЬКО НА ДАННЫХ НИЖЕ! 
- НЕ придумывай автомобили, которых нет в таблице!
- НЕ указывай характеристики, которых нет в данных!
- НЕ упоминай марки/модели, которые не присутствуют в результатах {data_source_desc}!
- Используй ТОЛЬКО информацию из предоставленной таблицы!
- Если данных недостаточно — скажи об этом прямо, НЕ выдумывай!

📋 ИНСТРУКЦИИ ПО ТИПАМ ЗАПРОСОВ:

⚠️ ВАЖНО: Определяй тип запроса по СОДЕРЖАНИЮ, а не только по первым словам!

1. **Если запрос автомобильный** (просьба найти, подобрать, показать автомобили, вопросы о характеристиках, ценах, сравнении моделей и т.д.):
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Если в запросе есть критерии поиска (год, пробег, цена, тип коробки, марка, модель, кузов, топливо, привод и т.д.), то это АВТОМОБИЛЬНЫЙ запрос, даже если он начинается с приветствия!
   - Примеры автомобильных запросов: "привет, хочу автомат не старше 2013 года", "здравствуй, покажи машины до 1 млн", "добрый день, ищу седан с пробегом до 100 тыс"
   - Отвечай как эксперт по автомобилям
   - Если запрос начинается с приветствия, но содержит критерии поиска — НЕ показывай общую информацию о возможностях, а СРАЗУ дай рекомендации по найденным автомобилям!
   - Дай экспертную рекомендацию (ТОП‑3 варианта) с причинами выбора — используй ТОЛЬКО автомобили из таблицы ниже
   - Укажи ключевые характеристики (год, цена, пробег, город, кузов, коробка, привод, топливо) — ТОЛЬКО из данных в таблице
   - Добавь 2–3 альтернативы с короткими пояснениями — ТОЛЬКО из предоставленных данных
   - Отметь риски/особенности — ТОЛЬКО на основе реальных данных (пробег, год, цена из таблицы)
   - Дай практические советы по покупке (общие советы, не специфичные для конкретных авто из таблицы)
   - Предложи следующие шаги (сузить бюджет/год/пробег, выбрать город/кузов/коробку и т.п.)
   - Задай 2–4 уточняющих вопроса (приоритеты: бюджет, новый/с пробегом, кузов, привод, двигатель, год, пробег, город)

2. **Если это ТОЛЬКО приветствие БЕЗ критериев поиска** (привет, здравствуй, добрый день, начать и т.д., но БЕЗ упоминания года, цены, пробега, марки, модели, кузова и т.д.):
   - Поприветствуй пользователя дружелюбно
   - Уточни, что интересует пользователя
   - Спроси, какие автомобили его интересуют
   - Предложи помощь в подборе

3. **Если запрос НЕ автомобильный** (вопросы о погоде, политике, других товарах, общие вопросы и т.д.):
   - Строго отвечай, что ты эксперт по подбору автомобилей
   - Объясни, что можешь помочь только с вопросами, связанными с автомобилями
   - Вежливо предложи вернуться к теме автомобилей
   - НЕ отвечай на вопросы, не связанные с автомобилями

У тебя есть данные из базы данных (результаты {data_source_desc}) ниже. Если в данных есть автомобили, используй их для ответа согласно инструкциям выше.{alternatives_warning}

🚨 КРИТИЧЕСКИ ВАЖНО - ОБРАБОТКА РЕЗУЛЬТАТОВ:
- 🚨 ВАЖНО: В таблице ниже найдено {total_count} автомобилей!
- 🚨 ВАЖНО: Если в таблице есть данные (строки с автомобилями) - ОБЯЗАТЕЛЬНО используй их для ответа!
- 🚨 ВАЖНО: Если в таблице есть автомобили - НЕ говори, что ничего не найдено!
- 🚨 ВАЖНО: Если в таблице есть автомобили - НЕ извиняйся за отсутствие результатов!
- Если найдено записей: {total_count} > 0 - ОБЯЗАТЕЛЬНО используй ТОЛЬКО эти данные для ответа!
- Если найдено записей: {total_count} = 0 - ОБЯЗАТЕЛЬНО извинись и предложи альтернативы!
- НИКОГДА не придумывай автомобили, которых нет в таблице!
- НИКОГДА не говори, что нашел автомобили, если в таблице их нет!
- НИКОГДА не говори "не удалось найти" или "к сожалению, не удалось найти", если в таблице ЕСТЬ данные!

⚠️ ЕСЛИ РЕЗУЛЬТАТОВ НЕТ (total_count = 0):
1. ОБЯЗАТЕЛЬНО извинись: "К сожалению, по вашим критериям не найдено подходящих автомобилей."
2. Объясни, почему не нашлось (слишком строгие критерии, редкая комбинация параметров и т.д.)
3. Предложи альтернативы:
   - Расширить критерии поиска (увеличить бюджет, убрать ограничения по пробегу/году)
   - Изменить параметры (другой кузов, другая коробка передач)
   - Посмотреть похожие варианты (другие марки, другие модели)
4. Задай уточняющие вопросы для более точного подбора

⚠️ ЕСЛИ РЕЗУЛЬТАТЫ ЕСТЬ (total_count > 0):
- 🚨 КРИТИЧЕСКИ ВАЖНО: В таблице ниже ЕСТЬ {total_count} автомобилей!
- 🚨 КРИТИЧЕСКИ ВАЖНО: Если в таблице есть строки с данными - ОБЯЗАТЕЛЬНО используй их!
- 🚨 КРИТИЧЕСКИ ВАЖНО: НЕ говори "не удалось найти" или "к сожалению, не удалось найти", если в таблице ЕСТЬ данные!
- 🚨 КРИТИЧЕСКИ ВАЖНО: НЕ извиняйся за отсутствие результатов, если в таблице ЕСТЬ данные!
- Используй ТОЛЬКО данные из таблицы!
- Проверь соответствие данных критериям из запроса!
- Если в запросе указана марка (например, BMW) - проверь колонку mark в таблице!
- Если в запросе указан тип кузова (седан, кроссовер и т.д.) - проверь колонку body_type в таблице!
- Если в запросе указана коробка передач (автомат, механика) - проверь колонку gear_box_type в таблице!
- Если в запросе указан бюджет - проверь колонку price в таблице!
- НЕ говори, что данных нет, если они ЕСТЬ в таблице!
- ВСЕГДА используй ТОЧНЫЕ значения из таблицы, не выдумывай!
- ОБЯЗАТЕЛЬНО перечисли найденные автомобили из таблицы с их характеристиками!

Если записей больше, чем показано ({len(data_records)} из {total_count}), упомяни об этом и предложи уточнить критерии поиска.

Форматируй ответ структурированными пунктами. Числа (цены/пробег/год) пиши в человекочитаемом виде (например: "2 200 000 рублей" вместо "2200000.0"). 

⚠️ ЗАПРЕЩЕНО: Придумывать данные, которых нет в таблице! Если информация отсутствует — скажи "не указано" или "данные отсутствуют".

Данные из базы данных ({data_source_text} выполнен успешно):
Найдено записей: {total_count}
Показано первых {len(data_records)} записей:

{context_text}

Запрос пользователя: {request.question}

Сформируй ответ автоэксперта, используя ТОЛЬКО данные из таблицы выше. ВНИМАТЕЛЬНО проверь соответствие данных в таблице критериям из запроса пользователя!"""

                        # Генерируем ответ через AI напрямую по промпту, минуя обработку команд
                        # Используем _generate_with_ai_settings напрямую для SQL-агента
                        from services.rag_service import _generate_with_ai_settings
                        ai_response_text, model_info = await _generate_with_ai_settings(ai_prompt)
                        
                        # Сохраняем сообщение в БД
                        from services.database_service import DatabaseService
                        db_service_msg = DatabaseService(db)
                        chat_message = db_service_msg.save_chat_message(
                            user_id="sql-agent-user",
                            message=request.question,
                            response=ai_response_text,
                            related_article_ids=[]
                        )
                        
                        ai_response = {
                            "response": ai_response_text,
                            "message_id": chat_message.id if chat_message else None,
                            "model_info": model_info
                        }
                        
                        # Используем AI-ответ вместо простого answer
                        ai_formatted_response = ai_response.get("response", result.get("answer", "Запрос выполнен успешно."))
                        result["answer"] = ai_formatted_response
                        
                        # Сохраняем сообщение в БД через database_service
                        try:
                            message_id = ai_response.get("message_id")
                            if message_id:
                                result["message_id"] = message_id
                        except:
                            pass
                        
                        source_name = "Elasticsearch" if fallback_source == "elasticsearch" else "SQL-агента"
                        print(f"✅ AI сформировал ответ на основе данных {source_name} ({len(data_records)} из {total_count} записей)")
                        print(f"📝 Длина AI-ответа: {len(ai_formatted_response)} символов")
                        print(f"📤 Ответ будет передан в frontend через SQLAgentResponse.answer")
                        
                    except Exception as ai_error:
                        print(f"⚠️ Ошибка при форматировании через AI: {ai_error}")
                        # Используем обычный answer если AI не доступен
                        pass
            
            # Если данных нет или запрос слишком общий - формируем диалог
            if query_too_general or (result.get("success") and (result_data is None or len(result_data) == 0) and result.get("row_count", 0) == 0):
                # Если данных нет, но нужно сформировать ответ (приветствие, неавтомобильный запрос и т.д.)
                # Или если запрос слишком общий - ведем диалог
                try:
                    from services.database_service import DatabaseService
                    from services.rag_service import RAGService
                    
                    db_service = DatabaseService(db)
                    rag_service = RAGService(db_service)
                    
                    # Получаем is_alternatives из result, если он есть
                    is_alternatives = result.get("is_alternatives", False)
                    sql_had_error = result.get("error") is not None
                    # query_too_general уже определен выше
                    
                    # Формируем промпт для случая без данных или общего запроса
                    # Показываем предупреждение только если это действительно альтернативы (ослабленный поиск)
                    if query_too_general:
                        data_source_desc = "общего запроса"
                        alternatives_warning = "\n\n🚨 КРИТИЧЕСКИ ВАЖНО: Запрос пользователя слишком общий (нет конкретных критериев поиска). В базе очень много автомобилей (более 100), поэтому НЕ показывай все результаты! Вместо этого:\n1. Поприветствуй пользователя дружелюбно\n2. Объясни, что для точного подбора нужно уточнить критерии\n3. Задай 4-5 уточняющих вопросов о:\n   - Бюджете (максимальная цена)\n   - Типе кузова (седан, хэтчбек, универсал, кроссовер и т.д.)\n   - Коробке передач (автомат или механика)\n   - Годе выпуска (новый или с пробегом, если с пробегом - какой максимальный пробег)\n   - Городе (где искать)\n   - Марке/модели (если есть предпочтения)\n4. Предложи помощь в подборе после уточнения критериев\n5. НЕ показывай автомобили из базы, так как их слишком много!"
                    elif is_alternatives and not sql_had_error:
                        data_source_desc = "поиска альтернатив (Elasticsearch)"
                        alternatives_warning = "\n\n⚠️ ВАЖНО: Это альтернативные варианты! По точному запросу пользователя ничего не найдено. Обязательно начни ответ с фразы: \"По вашему точному запросу ничего не найдено, но мы подобрали похожие альтернативы:\" и объясни, чем эти варианты отличаются от запроса пользователя."
                    else:
                        data_source_desc = "SQL-запроса"
                        alternatives_warning = ""
                    
                    ai_prompt_no_data = f"""Ты — автоэксперт и персональный помощник по подбору автомобиля.

🚨 КРИТИЧЕСКИ ВАЖНО: ВСЕГДА отвечай ТОЛЬКО на РУССКОМ языке! 
- НЕ используй английский язык в ответах!
- НЕ переключайся на английский!
- Все ответы должны быть на русском языке!

Твой стиль — кратко, по делу, профессионально. Избегай воды.

📋 ИНСТРУКЦИИ ПО ТИПАМ ЗАПРОСОВ:

⚠️ ВАЖНО: Определяй тип запроса по СОДЕРЖАНИЮ, а не только по первым словам!

1. **Если запрос автомобильный** (просьба найти, подобрать, показать автомобили, вопросы о характеристиках, ценах, сравнении моделей и т.д.):
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Если в запросе есть критерии поиска (год, пробег, цена, тип коробки, марка, модель, кузов, топливо, привод и т.д.), то это АВТОМОБИЛЬНЫЙ запрос, даже если он начинается с приветствия!
   - Примеры автомобильных запросов: "привет, хочу автомат не старше 2013 года", "здравствуй, покажи машины до 1 млн", "добрый день, ищу седан с пробегом до 100 тыс"
   - Отвечай как эксперт по автомобилям
   - Если запрос начинается с приветствия, но содержит критерии поиска — НЕ показывай общую информацию о возможностях, а СРАЗУ объясни ситуацию с поиском!
   - Если данных нет, объясни почему (слишком строгие критерии, нет таких автомобилей в базе и т.д.)
   - Предложи ослабить критерии поиска
   - Задай уточняющие вопросы для лучшего подбора

2. **Если это ТОЛЬКО приветствие БЕЗ критериев поиска** (привет, здравствуй, добрый день, начать и т.д., но БЕЗ упоминания года, цены, пробега, марки, модели, кузова и т.д.):
   - Поприветствуй пользователя дружелюбно
   - Уточни, что интересует пользователя
   - Спроси, какие автомобили его интересуют
   - Предложи помощь в подборе

3. **Если запрос НЕ автомобильный** (вопросы о погоде, политике, других товарах, общие вопросы и т.д.):
   - Строго отвечай, что ты эксперт по подбору автомобилей
   - Объясни, что можешь помочь только с вопросами, связанными с автомобилями
   - Вежливо предложи вернуться к теме автомобилей
   - НЕ отвечай на вопросы, не связанные с автомобилями

Запрос пользователя: {request.question}

{alternatives_warning}

Сформируй ответ согласно инструкциям выше:"""

                    # Генерируем ответ через AI напрямую по промпту, минуя обработку команд
                    from services.rag_service import _generate_with_ai_settings
                    ai_response_text, model_info = await _generate_with_ai_settings(ai_prompt_no_data)
                    
                    # Сохраняем сообщение в БД
                    chat_message = db_service.save_chat_message(
                        user_id="sql-agent-user",
                        message=request.question,
                        response=ai_response_text,
                        related_article_ids=[]
                    )
                    
                    ai_formatted_response = ai_response_text
                    result["answer"] = ai_formatted_response
                    
                    try:
                        if chat_message:
                            result["message_id"] = chat_message.id
                    except:
                        pass
                    
                    print(f"✅ AI сформировал ответ без данных для запроса: {request.question}")
                    print(f"📝 Длина AI-ответа: {len(ai_formatted_response)} символов")
                    
                except Exception as ai_error:
                    print(f"⚠️ Ошибка при форматировании через AI (без данных): {ai_error}")
                    pass
            else:
                print(f"⚠️ SQL-агент не смог обработать запрос: {result.get('error')}")
            
            # Логируем финальный ответ перед возвратом
            final_answer = result.get("answer")
            if final_answer:
                print(f"✅ Финальный ответ готов для передачи в frontend: {len(final_answer)} символов")
                if result.get("fallback_source") == "elasticsearch":
                    print(f"🔄 Источник данных: Elasticsearch fallback")
            
            # Возвращаем все данные для источников (не только первые 5)
            all_data = result.get("data")
            if all_data is None:
                all_data = []
            
            # Формируем финальный ответ с учетом альтернатив
            final_answer = result.get("answer")
            if not final_answer:
                # Если есть данные от fallback, но они помечены как альтернативы - это альтернативы
                # Если есть данные и они НЕ помечены как альтернативы - это точные совпадения
                sql_had_error = result.get("error") is not None
                is_alternatives = result.get("is_alternatives", False)
                
                if is_alternatives and not sql_had_error and result.get("row_count", 0) > 0:
                    # Это действительно альтернативы (ослабленный поиск)
                    final_answer = f"По вашему запросу ничего не найдено, но мы нашли {result.get('row_count', 0)} похожих альтернатив"
                elif result.get("row_count", 0) > 0:
                    # Есть результаты, но они не альтернативы - значит точные совпадения
                    final_answer = f"Найдено {result.get('row_count', 0)} автомобилей"
                else:
                    final_answer = result.get("answer", "Результатов не найдено.")
            
            return SQLAgentResponse(
                success=result.get("success", False),
                sql=result.get("sql"),
                data=all_data,  # Все данные для источников (до 500 из sql_agent_service)
                columns=result.get("columns"),
                row_count=result.get("row_count"),
                answer=final_answer,
                error=result.get("error"),
                needs_clarification=result.get("needs_clarification", False),
                clarification_questions=result.get("clarification_questions"),
                query_analysis=result.get("query_analysis")
            )
            
    except Exception as e:
        print(f"❌ Ошибка SQL-агента: {str(e)}")
        return SQLAgentResponse(
            success=False,
            error=f"Ошибка обработки запроса: {str(e)}"
        )

@router.get("/sql-agent/schema")
async def get_database_schema(
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Получение схемы базы данных"""
    try:
        sql_agent = SQLAgentService(db)
        schema = sql_agent.get_database_schema()
        return {
            "success": True,
            "schema": schema
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения схемы: {str(e)}")


# ============================================================================
# AI Model Orchestrator Endpoints
# ============================================================================

@router.get("/orchestrator/models")
async def get_orchestrator_models(
    db: Session = Depends(get_db)
):
    """Получение списка доступных моделей для задач"""
    try:
        orchestrator = AIModelOrchestratorService()
        available_models = await orchestrator.get_available_models()
        
        # Получаем конфигурацию задач
        task_mapping = orchestrator.config.get("task_model_mapping", {})
        
        # Получаем пользовательские переопределения
        user_overrides = orchestrator._load_user_settings()
        
        # Определяем используемые задачи (исключаем отключенные)
        used_tasks = {
            "query_analysis": "Анализ запросов пользователя",
            "search_intent_analysis": "Анализ намерения поиска",
            "relation_analysis": "Анализ связанности запросов",
            "sql_generation": "Генерация SQL-запросов",
            "response_generation": "Генерация ответов пользователю",
            "query_refinement": "Уточнение запросов",
            "fuzzy_interpretation": "Интерпретация размытых запросов",
            "filter_relaxation": "Ослабление фильтров",
            "result_processing": "Обработка результатов поиска"
        }
        
        # Разделяем на пользовательские и внутренние задачи
        user_interaction_tasks = {
            "query_analysis": "Анализ запросов пользователя",
            "search_intent_analysis": "Анализ намерения поиска",
            "relation_analysis": "Анализ связанности запросов",
            "response_generation": "Генерация ответов пользователю",
            "query_refinement": "Уточнение запросов"
        }
        
        internal_tasks = {
            "sql_generation": "Генерация SQL-запросов",
            "fuzzy_interpretation": "Интерпретация размытых запросов",
            "filter_relaxation": "Ослабление фильтров",
            "result_processing": "Обработка результатов поиска"
        }
        
        # Объединяем task_mapping с user_overrides для отображения актуальных моделей
        actual_task_mapping = {}
        user_interaction_mapping = {}
        internal_mapping = {}
        
        for task_key, task_config in task_mapping.items():
            # Пропускаем неиспользуемые задачи
            if task_key not in used_tasks:
                continue
                
            # Определяем актуальную модель
            if task_key in user_overrides:
                model = user_overrides[task_key]
            else:
                if isinstance(task_config, dict):
                    model = task_config.get("primary", "")
                else:
                    model = task_config
            
            actual_task_mapping[task_key] = model
            
            # Разделяем на пользовательские и внутренние
            if task_key in user_interaction_tasks:
                user_interaction_mapping[task_key] = {
                    "model": model,
                    "name": user_interaction_tasks[task_key]
                }
            elif task_key in internal_tasks:
                internal_mapping[task_key] = {
                    "model": model,
                    "name": internal_tasks[task_key]
                }
        
        return {
            "success": True,
            "available_models": available_models,
            "task_mapping": actual_task_mapping,
            "user_interaction_tasks": user_interaction_mapping,
            "internal_tasks": internal_mapping,
            "user_overrides_enabled": orchestrator.config.get("user_overrides", {}).get("enabled", True)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения моделей: {str(e)}")


@router.post("/orchestrator/select", response_model=ModelSelectionResponse)
async def select_model_for_task(
    request: ModelSelectionRequest,
    db: Session = Depends(get_db)
):
    """Ручной выбор модели для задачи"""
    try:
        orchestrator = AIModelOrchestratorService()
        
        # Преобразуем строку в TaskType
        try:
            task_type = TaskType(request.task_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Неизвестный тип задачи: {request.task_type}")
        
        # Преобразуем complexity если указана
        complexity = None
        if request.task_complexity:
            try:
                complexity = Complexity(request.task_complexity)
            except ValueError:
                pass
        
        # Сохраняем модель если указана
        if request.user_override:
            orchestrator._save_user_settings(request.task_type, request.user_override)
            # Перезагружаем конфиг чтобы изменения сразу вступили в силу
            orchestrator.reload_config()
        
        # Выбираем модель
        selected_model = await orchestrator.select_model_for_task(
            task_type=task_type,
            task_complexity=complexity,
            user_override=request.user_override
        )
        
        # Определяем источник выбора
        user_overrides = orchestrator._load_user_settings()
        if request.user_override:
            source = "user_override"
        elif request.task_type in user_overrides:
            source = "user_settings"
        else:
            source = "config"
        
        return ModelSelectionResponse(
            selected_model=selected_model,
            task_type=request.task_type,
            source=source
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка выбора модели: {str(e)}")


@router.post("/orchestrator/bulk-update", response_model=BulkModelUpdateResponse)
async def bulk_update_models(
    request: BulkModelUpdateRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Массовое обновление моделей для задач"""
    try:
        orchestrator = AIModelOrchestratorService()
        
        results = orchestrator.save_multiple_models(request.models)
        
        # Перезагружаем конфиг чтобы изменения сразу вступили в силу
        orchestrator.reload_config()
        
        updated_tasks = [task for task, success in results.items() if success]
        failed_tasks = [task for task, success in results.items() if not success]
        
        return BulkModelUpdateResponse(
            success=len(failed_tasks) == 0,
            updated_tasks=updated_tasks,
            failed_tasks=failed_tasks
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка массового обновления моделей: {str(e)}")


@router.get("/orchestrator/performance", response_model=OrchestratorPerformanceResponse)
async def get_orchestrator_performance(
    model_name: Optional[str] = None,
    task_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Получение метрик производительности оркестратора"""
    try:
        orchestrator = AIModelOrchestratorService()
        
        # Преобразуем task_type если указан
        task_type_enum = None
        if task_type:
            try:
                task_type_enum = TaskType(task_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Неизвестный тип задачи: {task_type}")
        
        # Получаем метрики
        metrics = orchestrator.get_model_performance(
            model_name=model_name,
            task_type=task_type_enum
        )
        
        # Подсчитываем общую статистику
        total_requests = sum(m.get("total_requests", 0) for m in metrics.values())
        models_used = list(set([k.split(":")[0] for k in metrics.keys()]))
        
        return OrchestratorPerformanceResponse(
            metrics=metrics,
            total_requests=total_requests,
            models_used=models_used
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения метрик: {str(e)}")


@router.post("/orchestrator/reload-config")
async def reload_orchestrator_config(
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Перезагрузка конфигурации оркестратора"""
    try:
        orchestrator = AIModelOrchestratorService()
        orchestrator.reload_config()
        return {
            "success": True,
            "message": "Конфигурация оркестратора перезагружена"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка перезагрузки конфигурации: {str(e)}")


@router.post("/orchestrator/load-model")
async def load_model_manually(
    model_name: str,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Ручная загрузка модели Ollama"""
    try:
        orchestrator = AIModelOrchestratorService()
        
        # Проверяем доступность Ollama
        from services.ollama_utils import find_working_ollama_url
        working_url = await find_working_ollama_url(timeout=2.0)
        if not working_url:
            raise HTTPException(status_code=400, detail="Ollama недоступен")
        
        # Загружаем модель
        await orchestrator._auto_load_model(model_name, working_url)
        
        return {
            "success": True,
            "message": f"Модель {model_name} успешно загружена",
            "model": model_name
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка загрузки модели: {str(e)}")


# ============================================================================
# Fuzzy Query Interpreter Endpoints
# ============================================================================

@router.post("/interpret-query")
async def interpret_query(
    user_query: str,
    dialogue_context: Optional[str] = None,
    available_brands: Optional[List[str]] = None,
    available_categories: Optional[List[str]] = None,
    db: Session = Depends(get_db)
):
    """Интерпретация размытого запроса в структурированные параметры"""
    try:
        interpreter = FuzzyQueryInterpreter()
        result = await interpreter.interpret_fuzzy_query(
            user_query=user_query,
            dialogue_context=dialogue_context or "",
            available_brands=available_brands,
            available_categories=available_categories
        )
        return {
            "success": True,
            **result
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка интерпретации запроса: {str(e)}")


# ============================================================================
# Intelligent Search Endpoints
# ============================================================================

@router.post("/intelligent-search", response_model=IntelligentSearchResponse)
async def intelligent_search(
    request: IntelligentSearchRequest,
    db: Session = Depends(get_db)
):
    """Интеллектуальный поиск с автоматическим ослаблением фильтров"""
    try:
        search_service = IntelligentSearchService()
        
        # Преобразуем запрос в параметры поиска
        search_params = {
            "query": request.query or "",
            "mark": request.mark,
            "model": request.model,
            "city": request.city,
            "fuel_type": request.fuel_type,
            "body_type": request.body_type,
            "min_price": request.min_price,
            "max_price": request.max_price,
            "min_year": request.min_year,
            "max_year": request.max_year,
            "min_mileage": request.min_mileage,
            "max_mileage": request.max_mileage,
            "color": request.color,
            "interior_color": request.interior_color,
            "options": request.options,
            "car_type": request.car_type,
            "min_power": request.min_power,
            "max_power": request.max_power,
            "min_engine_vol": request.min_engine_vol,
            "max_engine_vol": request.max_engine_vol,
            "limit": request.limit,
            "offset": request.offset
        }
        
        # Удаляем None значения
        search_params = {k: v for k, v in search_params.items() if v is not None}
        
        # Выполняем интеллектуальный поиск
        result = await search_service.search_with_intelligence(
            initial_params=search_params,
            user_query=request.query or "",
            dialogue_context=request.dialogue_context or ""
        )
        
        # Убеждаемся, что все обязательные поля присутствуют
        if "message" not in result:
            result["message"] = None
        
        return IntelligentSearchResponse(**result)
        
    except Exception as e:
        print(f"❌ Ошибка интеллектуального поиска: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка интеллектуального поиска: {str(e)}")


@router.post("/recommendations")
async def get_recommendations(
    initial_params: Dict[str, Any],
    user_query: str,
    dialogue_context: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Получение рекомендаций при отсутствии результатов"""
    try:
        from services.recommendation_service import RecommendationService
        from services.elasticsearch_service import ElasticsearchService
        
        recommendation_service = RecommendationService()
        es_service = ElasticsearchService()
        
        # Получаем все доступные автомобили
        all_cars_result = es_service.search_cars(limit=500)
        available_cars = all_cars_result.get("hits", [])
        
        # Генерируем рекомендации
        recommendations = await recommendation_service.generate_recommendations(
            initial_params=initial_params,
            user_query=user_query,
            available_cars=available_cars,
            dialogue_context=dialogue_context or ""
        )
        
        return {
            "success": True,
            **recommendations
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка генерации рекомендаций: {str(e)}")


# ============================================================================
# Car Dealer Assistant Endpoints
# ============================================================================

@router.post("/car-dealer/query", response_model=CarDealerQueryResponse)
async def car_dealer_query(
    request: CarDealerQueryRequest,
    db: Session = Depends(get_db)
):
    """Главный endpoint ассистента автосалона - обрабатывает запросы клиентов"""
    try:
        assistant = CarDealerAssistantService(
            user_id=request.user_id,
            session_id=request.session_id
        )
        
        result = await assistant.process_query(request.user_query)
        
        return CarDealerQueryResponse(**result)
        
    except Exception as e:
        print(f"❌ Ошибка обработки запроса ассистента: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка обработки запроса: {str(e)}")


# ============================================================================
# Finance Endpoints
# ============================================================================

@router.post("/finance/calculate", response_model=FinanceCalculationResponse)
async def calculate_finance(
    request: FinanceCalculationRequest,
    db: Session = Depends(get_db)
):
    """Расчет параметров кредита или лизинга"""
    try:
        from services.finance_calculator_service import FinanceCalculatorService
        
        calculator = FinanceCalculatorService()
        
        # Определяем первоначальный взнос
        if request.down_payment is not None:
            down_payment = request.down_payment
        else:
            down_payment = request.car_price * (request.down_payment_percent / 100)
        
        result = {
            "success": True,
            "calculation_type": request.calculation_type
        }
        
        if request.calculation_type == "loan":
            # Расчет кредита
            interest_rate = request.interest_rate or 9.0  # Стандартная ставка
            loan_term = request.loan_term or 60
            
            loan_calc = calculator.calculate_loan(
                car_price=request.car_price,
                down_payment=down_payment,
                interest_rate=interest_rate,
                loan_term=loan_term
            )
            
            result["loan_calculation"] = loan_calc
            
        elif request.calculation_type == "lease":
            # Расчет лизинга
            residual_value = request.residual_value or (request.car_price * 0.3)
            lease_term = request.lease_term or request.loan_term or 60
            interest_rate = request.interest_rate or 8.0
            
            lease_calc = calculator.calculate_lease(
                car_price=request.car_price,
                residual_value=residual_value,
                lease_term=lease_term,
                interest_rate=interest_rate
            )
            
            result["lease_calculation"] = lease_calc
            
        elif request.calculation_type == "compare":
            # Сравнение кредита и лизинга
            comparison = calculator.compare_financing_options(
                car_price=request.car_price,
                down_payment=down_payment,
                loan_term=request.loan_term or 60
            )
            
            result["loan_calculation"] = comparison.get("loan")
            result["lease_calculation"] = comparison.get("lease")
            result["comparison"] = comparison.get("comparison")
        
        return FinanceCalculationResponse(**result)
        
    except Exception as e:
        print(f"❌ Ошибка расчета финансов: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка расчета финансов: {str(e)}")


# ============================================================================
# Dialogue Management Endpoints
# ============================================================================

@router.get("/dialogue/history", response_model=DialogueHistoryResponse)
async def get_dialogue_history(
    user_id: str,
    session_id: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Получение истории диалога"""
    try:
        from services.dialogue_history_service import DialogueHistoryService
        
        history_service = DialogueHistoryService(user_id, session_id)
        
        # Получаем все сообщения
        all_messages = history_service.get_all_messages()
        
        # Ограничиваем лимитом
        messages = all_messages[-limit:] if len(all_messages) > limit else all_messages
        
        # Получаем темы и интересы
        topics = history_service.get_already_covered_topics()
        interests = history_service.get_user_interests()
        
        return DialogueHistoryResponse(
            success=True,
            messages=messages,
            topics=topics,
            user_interests=interests,
            total_messages=len(all_messages)
        )
        
    except Exception as e:
        print(f"❌ Ошибка получения истории диалога: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка получения истории: {str(e)}")


@router.delete("/dialogue/history")
async def clear_dialogue_history(
    user_id: str,
    session_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Очистка истории диалога"""
    try:
        from services.dialogue_history_service import DialogueHistoryService
        
        history_service = DialogueHistoryService(user_id, session_id)
        history_service.clear_history()
        
        return {
            "success": True,
            "message": "История диалога очищена"
        }
        
    except Exception as e:
        print(f"❌ Ошибка очистки истории: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка очистки истории: {str(e)}")


@router.get("/dialogue/visualization", response_model=DialogueVisualizationResponse)
async def get_dialogue_visualization(
    user_id: str,
    session_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Получение визуализации структуры диалога"""
    try:
        from services.dialogue_history_service import DialogueHistoryService
        from services.dialogue_visualizer_service import DialogueVisualizerService
        
        history_service = DialogueHistoryService(user_id, session_id)
        visualizer = DialogueVisualizerService()
        
        dialogue_map = visualizer.create_dialogue_map(history_service)
        topic_transitions = visualizer.analyze_topic_transitions(history_service)
        key_moments = visualizer.get_key_moments(history_service)
        
        return DialogueVisualizationResponse(
            success=True,
            dialogue_map=dialogue_map,
            topic_transitions=topic_transitions,
            key_moments=key_moments
        )
        
    except Exception as e:
        print(f"❌ Ошибка получения визуализации: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка получения визуализации: {str(e)}")


# ============================================================================
# Quality Metrics Endpoints
# ============================================================================

@router.get("/quality/metrics", response_model=QualityMetricsResponse)
async def get_quality_metrics(
    model_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Получение метрик качества работы системы"""
    try:
        from services.quality_metrics_service import QualityMetricsService
        
        metrics_service = QualityMetricsService()
        
        performance_summary = metrics_service.get_performance_summary()
        
        result = {
            "success": True,
            "performance_summary": performance_summary
        }
        
        # Если указана модель, получаем метрики для неё
        if model_name:
            model_performance = metrics_service.get_model_performance(model_name)
            result["model_performance"] = model_performance
        
        return QualityMetricsResponse(**result)
        
    except Exception as e:
        print(f"❌ Ошибка получения метрик: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка получения метрик: {str(e)}")


@router.delete("/quality/metrics")
async def clear_quality_metrics(
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Очистка всех метрик качества (только для администраторов)"""
    try:
        from services.quality_metrics_service import QualityMetricsService
        
        metrics_service = QualityMetricsService()
        metrics_service.clear_metrics()
        
        return {
            "success": True,
            "message": "Метрики качества очищены"
        }
        
    except Exception as e:
        print(f"❌ Ошибка очистки метрик: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Ошибка очистки метрик: {str(e)}")
