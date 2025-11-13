"""
LangChain интеграция для SQL-агента
Обеспечивает единый интерфейс для работы с различными LLM через LangChain
"""
from typing import Optional, Dict, Any
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
from app.core.config import settings

# Импорты LangChain провайдеров (с обработкой ошибок)
try:
    from langchain_community.chat_models import ChatOllama
except ImportError:
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        ChatOllama = None

try:
    from langchain_mistralai import ChatMistralAI
except ImportError:
    try:
        from langchain_community.chat_models import ChatMistralAI
    except ImportError:
        ChatMistralAI = None

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    try:
        from langchain_community.chat_models import ChatOpenAI
    except ImportError:
        ChatOpenAI = None

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    try:
        from langchain_community.chat_models import ChatAnthropic
    except ImportError:
        ChatAnthropic = None


class LangChainLLMService:
    """Сервис для работы с LLM через LangChain"""
    
    def __init__(self):
        self._llm_cache: Dict[str, BaseChatModel] = {}
    
    def get_llm(self, model_config: str, api_key: Optional[str] = None) -> BaseChatModel:
        """
        Получает LLM из кэша или создает новый
        
        Args:
            model_config: Конфигурация модели в формате "provider:model_name"
            api_key: API ключ (если требуется)
        
        Returns:
            BaseChatModel: LangChain LLM объект
        """
        # Проверяем кэш
        cache_key = f"{model_config}:{api_key or 'no_key'}"
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]
        
        # Создаем новый LLM
        if model_config.startswith("ollama:"):
            model_name = model_config.replace("ollama:", "")
            llm = self._create_ollama_llm(model_name)
        elif model_config.startswith("mistral:"):
            model_name = model_config.replace("mistral:", "")
            llm = self._create_mistral_llm(model_name, api_key)
        elif model_config.startswith("openai:"):
            model_name = model_config.replace("openai:", "")
            llm = self._create_openai_llm(model_name, api_key)
        elif model_config.startswith("anthropic:"):
            model_name = model_config.replace("anthropic:", "")
            llm = self._create_anthropic_llm(model_name, api_key)
        else:
            # Fallback на Ollama
            llm = self._create_ollama_llm("llama3:8b")
        
        # Кэшируем
        self._llm_cache[cache_key] = llm
        return llm
    
    def _create_ollama_llm(self, model_name: str) -> BaseChatModel:
        """Создает Ollama LLM через LangChain"""
        if ChatOllama is None:
            raise ImportError("ChatOllama не доступен. Установите langchain-community или langchain-ollama")
        
        # Пробуем найти рабочий URL через утилиту (проверяет host.docker.internal и localhost)
        base_url = "http://host.docker.internal:11434"  # Дефолт для Docker
        try:
            from services.ollama_utils import find_working_ollama_url
            import asyncio
            # Пытаемся найти рабочий URL синхронно
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            if loop.is_running():
                # Если цикл уже запущен, используем дефолтный URL (приоритет Docker)
                base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
            else:
                working_url = loop.run_until_complete(find_working_ollama_url(timeout=2.0))
                if working_url:
                    base_url = working_url
                else:
                    # Если не нашли рабочий, используем приоритет Docker
                    base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        except Exception:
            # Если не удалось найти, используем дефолтный (приоритет Docker) или из переменной окружения
            base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        
        return ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=0.1,
            num_predict=16384,
            timeout=180
        )
    
    def _create_mistral_llm(self, model_name: str, api_key: Optional[str]) -> BaseChatModel:
        """Создает Mistral LLM через LangChain"""
        if ChatMistralAI is None:
            raise ImportError("ChatMistralAI не доступен. Установите langchain-mistralai")
        key = api_key or settings.mistral_api_key
        
        # Правильная конфигурация для Mistral API через LangChain
        # Проблема: LangChain ChatMistralAI по умолчанию может использовать неправильный endpoint
        # Решение: Используем правильный endpoint через параметр endpoint или base_url
        base_url = getattr(settings, 'mistral_base_url', 'https://api.mistral.ai')
        
        # Пробуем разные варианты конфигурации в зависимости от версии langchain-mistralai
        # ВАЖНО: LangChain ChatMistralAI автоматически добавляет /chat/completions к base_url
        # Поэтому НЕ нужно указывать полный путь, только базовый URL
        try:
            # Вариант 1: Используем base_url с /v1 (LangChain добавит /chat/completions)
            # Это правильный способ - LangChain сам добавит /chat/completions
            return ChatMistralAI(
                model=model_name,
                mistral_api_key=key,
                temperature=0.1,
                max_tokens=8192,
                base_url=f"{base_url}/v1"  # Только базовый путь, LangChain добавит /chat/completions
            )
        except (TypeError, ValueError, AttributeError) as e1:
            try:
                # Вариант 2: Используем endpoint с /v1 (без /chat/completions)
                return ChatMistralAI(
                    model=model_name,
                    mistral_api_key=key,
                    temperature=0.1,
                    max_tokens=8192,
                    endpoint=f"{base_url}/v1"  # Только /v1, LangChain должен добавить /chat/completions
                )
            except (TypeError, ValueError, AttributeError) as e2:
                # Вариант 3: Стандартная конфигурация (LangChain должен использовать правильный endpoint по умолчанию)
                print(f"⚠️ Использую стандартную конфигурацию ChatMistralAI")
                print(f"   Ошибки при попытке настроить base_url/endpoint: {e1}, {e2}")
                # Стандартная конфигурация должна использовать https://api.mistral.ai/v1/chat/completions
                return ChatMistralAI(
                    model=model_name,
                    mistral_api_key=key,
                    temperature=0.1,
                    max_tokens=8192
                )
    
    def _create_openai_llm(self, model_name: str, api_key: Optional[str]) -> BaseChatModel:
        """Создает OpenAI LLM через LangChain"""
        if ChatOpenAI is None:
            raise ImportError("ChatOpenAI не доступен. Установите langchain-openai")
        key = api_key or os.getenv("OPENAI_API_KEY", "")
        return ChatOpenAI(
            model=model_name,
            api_key=key,
            temperature=0.1,
            max_tokens=8192
        )
    
    def _create_anthropic_llm(self, model_name: str, api_key: Optional[str]) -> BaseChatModel:
        """Создает Anthropic LLM через LangChain"""
        if ChatAnthropic is None:
            raise ImportError("ChatAnthropic не доступен. Установите langchain-anthropic")
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        return ChatAnthropic(
            model=model_name,
            api_key=key,
            temperature=0.1,
            max_tokens=8192
        )
    
    def create_sql_prompt_template(self, generated_params_section: str = "") -> ChatPromptTemplate:
        """
        Создает шаблон промпта для SQL-генерации через LangChain
        
        Returns:
            ChatPromptTemplate: Шаблон промпта
        """
        system_template = """Ты — эксперт по SQL для PostgreSQL. База данных содержит таблицы cars (новые авто) и used_cars (подержанные).

🚨 КРИТИЧЕСКИ ВАЖНО:
- НИКОГДА не используй JOIN между cars и used_cars - они НЕ связаны!
- Для марок используй поле 'mark', НЕ 'code' или 'model'!
- Всегда используй UPPER(mark) LIKE '%МАРКА%' для поиска марок
- Для объединения используй UNION ALL
- Цена хранится как VARCHAR - используй CAST для сравнения с числом
- ❌ НИКОГДА не используй SELECT * в UNION ALL - всегда указывай явные колонки!
- ✅ Для сортировки по цене ВСЕГДА создай псевдоним numeric_price в SELECT ОБЕИХ частей UNION ALL, затем используй его в ORDER BY
- ❌ НИКОГДА не используй CAST/REPLACE/функции напрямую в ORDER BY после UNION ALL - это вызовет ошибку "invalid UNION/INTERSECT/EXCEPT ORDER BY clause"!
- ❌ ОШИБКА: ORDER BY CAST(REPLACE(...) AS NUMERIC) - PostgreSQL не позволяет использовать выражения в ORDER BY после UNION!
- ⚠️ КРИТИЧЕСКИ ВАЖНО: Если в SELECT есть колонки из used_cars (mileage, power, driving_gear_type, engine_vol и т.д.):
   - В первой части (FROM cars) используй NULL AS mileage, NULL AS power и т.д.
   - Во второй части (FROM used_cars) используй реальные поля: mileage, power и т.д.
   - НИКОГДА не используй mileage в SELECT из cars - это вызовет ошибку "column mileage does not exist"!

Генерируй ТОЛЬКО валидный SQL без объяснений, без markdown."""

        few_shot_examples = """
═══════════════════════════════════════════════════════════════════════════════
ПРИМЕРЫ ЗАПРОСОВ И ОТВЕТОВ (ИСПОЛЬЗУЙ КАК ОБРАЗЕЦ):
═══════════════════════════════════════════════════════════════════════════════

⚠️ КРИТИЧЕСКИ ВАЖНО: НИКОГДА не используй SELECT * в UNION ALL!
⚠️ ВСЕГДА указывай явные колонки: mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type
⚠️ Для used_cars добавляй mileage: mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, mileage
⚠️ Если нужна сортировка по цене - ВСЕГДА создай псевдоним numeric_price в SELECT ОБЕИХ частей UNION ALL, затем используй его в ORDER BY
⚠️ НИКОГДА не используй CAST/REPLACE/функции напрямую в ORDER BY после UNION ALL - это вызовет ошибку "invalid UNION/INTERSECT/EXCEPT ORDER BY clause"!
⚠️ ОШИБКА: ORDER BY CAST(REPLACE(...) AS NUMERIC) - PostgreSQL не позволяет использовать выражения в ORDER BY после UNION!
⚠️ ПРАВИЛЬНО: Создай псевдоним в SELECT, затем ORDER BY numeric_price

Вопрос: "тойота"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage FROM used_cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND price IS NOT NULL AND price != ''

Вопрос: "BMW"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%BMW%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage FROM used_cars WHERE UPPER(mark) LIKE '%BMW%' AND price IS NOT NULL AND price != ''

Вопрос: "бмв 3 серии"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%BMW%' AND UPPER(model) LIKE '%3%' AND UPPER(model) LIKE '%СЕРИИ%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage FROM used_cars WHERE UPPER(mark) LIKE '%BMW%' AND UPPER(model) LIKE '%3%' AND UPPER(model) LIKE '%СЕРИИ%' AND price IS NOT NULL AND price != ''

Вопрос: "Toyota Camry"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND UPPER(model) LIKE '%CAMRY%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage FROM used_cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND UPPER(model) LIKE '%CAMRY%' AND price IS NOT NULL AND price != ''

Вопрос: "BMW дешевле 5000000"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price FROM cars WHERE UPPER(mark) LIKE '%BMW%' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) < 5000000 AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price FROM used_cars WHERE UPPER(mark) LIKE '%BMW%' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) < 5000000 AND price IS NOT NULL AND price != ''

Вопрос: "седан автомат до 5 млн, отсортировать по цене от дорогих к дешевым"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price FROM cars WHERE (LOWER(body_type) LIKE '%седан%' OR LOWER(body_type) LIKE '%sedan%') AND (LOWER(gear_box_type) LIKE '%автомат%' OR LOWER(gear_box_type) LIKE '%automatic%') AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) <= 5000000 AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price FROM used_cars WHERE (LOWER(body_type) LIKE '%седан%' OR LOWER(body_type) LIKE '%sedan%') AND (LOWER(gear_box_type) LIKE '%автомат%' OR LOWER(gear_box_type) LIKE '%automatic%') AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) <= 5000000 AND price IS NOT NULL AND price != '' ORDER BY numeric_price DESC

═══════════════════════════════════════════════════════════════════════════════
"""

        # Если есть сгенерированные параметры, добавляем их в начало
        params_header = ""
        if generated_params_section:
            # Извлекаем SQL условия из параметров для примера
            sql_conditions = []
            if "→ SQL:" in generated_params_section:
                # Извлекаем все SQL условия
                lines = generated_params_section.split('\n')
                for line in lines:
                    if "→ SQL:" in line:
                        sql_part = line.split("→ SQL:")[1].strip()
                        if sql_part and not sql_part.startswith("CAST(REPLACE(REPLACE..."):
                            sql_conditions.append(sql_part)
            
            # Формируем пример SQL с параметрами
            example_sql = ""
            if sql_conditions:
                conditions_str = " AND ".join(sql_conditions)
                example_sql = f"""
ПРИМЕР ПРАВИЛЬНОГО SQL С ЭТИМИ ПАРАМЕТРАМИ:
SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, power
FROM cars 
WHERE {conditions_str}
AND price IS NOT NULL AND price != ''
UNION ALL
SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, power
FROM used_cars 
WHERE {conditions_str}
AND price IS NOT NULL AND price != '';

"""
            
            params_header = f"""
🚨🚨🚨🚨🚨 КРИТИЧЕСКИ ВАЖНО - ПРОЧИТАЙ ПЕРВЫМ! 🚨🚨🚨🚨🚨

СГЕНЕРИРОВАННЫЕ ПАРАМЕТРЫ (ОБЯЗАТЕЛЬНО ИСПОЛЬЗУЙ В SQL):
{generated_params_section}

{example_sql}
⚠️⚠️⚠️ КРИТИЧЕСКИ ВАЖНО: Выше указаны ОБЯЗАТЕЛЬНЫЕ параметры для SQL WHERE условий!
⚠️⚠️⚠️ НЕ игнорируй их! НЕ заменяй на другие условия!
⚠️⚠️⚠️ НЕ добавляй условия для марок/моделей, которые НЕ были указаны в запросе!
⚠️⚠️⚠️ ВСЕ эти параметры ДОЛЖНЫ быть включены в SQL запрос!

═══════════════════════════════════════════════════════════════════════════════
"""
        
        user_template = params_header + """{few_shot_examples}
🚨🚨🚨 КРИТИЧЕСКИ ВАЖНО - ПРОЧИТАЙ ПЕРВЫМ! 🚨🚨🚨

⚠️ ЗАПРЕЩЕНО: НИКОГДА не используй JOIN между таблицами cars и used_cars!
   - Эти таблицы НЕ СВЯЗАНЫ между собой!
   - cars = новые автомобили, used_cars = подержанные автомобили
   - Это РАЗНЫЕ автомобили, они НЕ связаны через внешние ключи!
   - ❌ ЗАПРЕЩЕНО: SELECT ... FROM cars c JOIN used_cars u ON c.id = u.car_id
   - ❌ ЗАПРЕЩЕНО: SELECT ... FROM used_cars u JOIN cars c ON u.id = c.used_car_id
   - ✅ ПРАВИЛЬНО: Используй UNION ALL для объединения результатов

⚠️ ДЛЯ ПРОСТОГО ПОИСКА ПО МАРКЕ (например: "тойота", "bmw"):
   - Используй ПРОСТОЙ SELECT из cars или used_cars БЕЗ JOIN!
   - ✅ ПРАВИЛЬНО: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM used_cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND price IS NOT NULL AND price != '';

⚠️ НЕ ДОБАВЛЯЙ условия, которые НЕ были запрошены пользователем!
   - Если пользователь не указал город - НЕ добавляй условие для города!
   - Если пользователь не указал модель - НЕ добавляй условие для модели!
   - Если пользователь не указал цену - НЕ добавляй условие для цены!

⚠️ КРИТИЧЕСКИ ВАЖНО - ORDER BY В UNION ALL:
   - ❌ НИКОГДА не используй вычисляемые поля (CAST, REPLACE, функции) напрямую в ORDER BY после UNION ALL!
   - ❌ ОШИБКА: ORDER BY CAST(REPLACE(...) AS NUMERIC) - вызовет "invalid UNION/INTERSECT/EXCEPT ORDER BY clause"
   - ✅ ВСЕГДА создавай псевдоним в SELECT обеих частей UNION ALL, затем используй его в ORDER BY
   - ✅ ПРАВИЛЬНО: SELECT ..., CAST(...) AS numeric_price FROM cars ... UNION ALL SELECT ..., CAST(...) AS numeric_price FROM used_cars ... ORDER BY numeric_price DESC

═══════════════════════════════════════════════════════════════════════════════
КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ДЛЯ PostgreSQL:
═══════════════════════════════════════════════════════════════════════════════

1. БЕЗОПАСНОСТЬ:
   - Используй ТОЛЬКО оператор SELECT
   - НЕ используй: DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, EXEC, EXECUTE
   - Запрещены любые операции изменения данных

2. PostgreSQL ОСОБЕННОСТИ:
   - PostgreSQL поддерживает регулярные выражения (SIMILAR TO, ~)
   - Для очистки строк используй вложенные REPLACE(): REPLACE(REPLACE(REPLACE(...)))
   - Используй стандартные SQL функции: UPPER(), LOWER(), LIKE, CAST()
   - Для приведения типов используй CAST(... AS NUMERIC) или ::NUMERIC

3. РЕГИСТРОНЕЗАВИСИМЫЙ ПОИСК МАРОК И ГОРОДОВ:
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Различай МАРКУ и МОДЕЛЬ! 'mark' - МАРКА (Toyota, BMW), 'model' - МОДЕЛЬ (Camry, X5)
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Если запрос про марку (Toyota, тойота) → используй 'mark', НЕ 'model'!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Для поиска МАРОК автомобилей используй поле 'mark', НЕ 'code'!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Поле 'code' существует ТОЛЬКО в таблице car_options (код опции), НЕ в таблице cars!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: В таблице cars НЕТ поля 'code' - используй 'mark' для поиска марок!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: ВСЕГДА используй UPPER() с LIKE для поиска марок!
   - ⚠️ НЕ используй просто LIKE без UPPER() - это может не найти все варианты!
   - ⚠️ НЕ используй = для поиска марок - это не найдет варианты с пробелами или разным регистром!
   
   ✅ ПРАВИЛЬНО (МАРКА): WHERE UPPER(mark) LIKE '%TOYOTA%'  -- найдет Toyota, TOYOTA, toyota
   ✅ ПРАВИЛЬНО (МАРКА): WHERE UPPER(mark) LIKE '%BMW%'      -- найдет BMW, bmw, Bmw
   ✅ ПРАВИЛЬНО (МОДЕЛЬ): SELECT * FROM cars WHERE UPPER(model) LIKE '%CAMRY%'
   
   ❌ НЕПРАВИЛЬНО: WHERE model = 'Тойота'  -- ОШИБКА! "Тойота" - это МАРКА, используй 'mark'!
   ❌ НЕПРАВИЛЬНО: WHERE code = 'toyota'  -- ОШИБКА! Поле 'code' не существует в таблице cars!
   ❌ НЕПРАВИЛЬНО: WHERE mark = 'Toyota'  -- ОШИБКА! Используй UPPER(mark) LIKE '%TOYOTA%'!

3.1. ПОИСК ПО ЦВЕТУ - КРИТИЧЕСКИ ВАЖНО:
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Если запрос про ЦВЕТ (красный, синий, черный, "красненький", red, blue, black) → используй поле 'color'!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Для ЦВЕТА ВСЕГДА учитывай РУССКИЙ И АНГЛИЙСКИЙ языки!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: НЕ используй поле 'mark' для поиска цветов - это поле для марок!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: ВСЕГДА используй OR для объединения русского и английского вариантов!
   
   ✅ ПРАВИЛЬНО (красный/красненький): WHERE (UPPER(color) LIKE '%КРАСН%' OR UPPER(color) LIKE '%RED%')
   ✅ ПРАВИЛЬНО (синий): WHERE (UPPER(color) LIKE '%СИНИЙ%' OR UPPER(color) LIKE '%СИН%' OR UPPER(color) LIKE '%BLUE%')
   ✅ ПРАВИЛЬНО (черный): WHERE (UPPER(color) LIKE '%ЧЕРН%' OR UPPER(color) LIKE '%BLACK%')
   ✅ ПРАВИЛЬНО (белый): WHERE (UPPER(color) LIKE '%БЕЛ%' OR UPPER(color) LIKE '%WHITE%')
   
   ❌ НЕПРАВИЛЬНО: WHERE mark LIKE '%RED%'  -- ОШИБКА! RED - это цвет, используй поле 'color', не 'mark'!
   ❌ НЕПРАВИЛЬНО: WHERE color = 'красный'  -- ОШИБКА! Используй LIKE с OR для обоих языков!
   ❌ НЕПРАВИЛЬНО: WHERE UPPER(color) LIKE '%RED%'  -- ОШИБКА! Нужно учитывать и русский язык!

4. РАБОТА С ЦЕНАМИ (PostgreSQL) - КРИТИЧЕСКИ ВАЖНО:
   - ⚠️ Цена хранится как VARCHAR (character varying) и может содержать: пробелы, запятые, символ ₽
   - ⚠️ PostgreSQL ТРЕБУЕТ явного приведения типа при сравнении строки с числом!
   - Очистка и приведение цены: CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC)
   
   ✅ ПРАВИЛЬНО: WHERE CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) < 50000
   ❌ НЕПРАВИЛЬНО: WHERE price < 50000  -- ОШИБКА! PostgreSQL не может сравнить VARCHAR с INTEGER

5. ПОИСК ПО ТИПАМ (КПП, топливо, кузов, город, привод) - КРИТИЧЕСКИ ВАЖНО:
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Для ВСЕХ текстовых полей (КПП, топливо, кузов, город, привод) учитывай РУССКИЙ И АНГЛИЙСКИЙ языки!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: "автомат", "механика" - это про КПП (gear_box_type), НЕ про марку (mark)!
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: НЕ путай "автомат" (КПП) с маркой автомобиля!
   
   - Для КПП (gear_box_type):
     ✅ ПРАВИЛЬНО: WHERE (LOWER(gear_box_type) LIKE '%автомат%' OR LOWER(gear_box_type) LIKE '%automatic%')
     ✅ ПРАВИЛЬНО: WHERE (LOWER(gear_box_type) LIKE '%механик%' OR LOWER(gear_box_type) LIKE '%manual%')
     ❌ НЕПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%AUTOMAT%'  -- ОШИБКА! "автомат" - это КПП, не марка!
   
   - Для топлива (fuel_type):
     ✅ ПРАВИЛЬНО: WHERE (LOWER(fuel_type) LIKE '%бензин%' OR LOWER(fuel_type) LIKE '%petrol%' OR LOWER(fuel_type) LIKE '%gasoline%')
     ✅ ПРАВИЛЬНО: WHERE (LOWER(fuel_type) LIKE '%дизель%' OR LOWER(fuel_type) LIKE '%diesel%')
   
   - Для кузова (body_type):
     ✅ ПРАВИЛЬНО: WHERE (LOWER(body_type) LIKE '%седан%' OR LOWER(body_type) LIKE '%sedan%')
     ✅ ПРАВИЛЬНО: WHERE (LOWER(body_type) LIKE '%кроссовер%' OR LOWER(body_type) LIKE '%suv%' OR LOWER(body_type) LIKE '%crossover%')
   
   - Для города (city):
     ✅ ПРАВИЛЬНО: WHERE (UPPER(city) LIKE '%МОСКВА%' OR UPPER(city) LIKE '%MOSCOW%')
     ✅ ПРАВИЛЬНО: WHERE (UPPER(city) LIKE '%САНКТ-ПЕТЕРБУРГ%' OR UPPER(city) LIKE '%SAINT%PETERSBURG%' OR UPPER(city) LIKE '%SPB%')
   
   - Для привода (driving_gear_type):
     ✅ ПРАВИЛЬНО: WHERE (LOWER(driving_gear_type) LIKE '%полный%' OR LOWER(driving_gear_type) LIKE '%all%wheel%' OR LOWER(driving_gear_type) LIKE '%4wd%')
     ✅ ПРАВИЛЬНО: WHERE (LOWER(driving_gear_type) LIKE '%передний%' OR LOWER(driving_gear_type) LIKE '%front%wheel%' OR LOWER(driving_gear_type) LIKE '%fwd%')

═══════════════════════════════════════════════════════════════════════════════
СХЕМА БАЗЫ ДАННЫХ:
═══════════════════════════════════════════════════════════════════════════════
{schema}
═══════════════════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════════════════
АЛГОРИТМ ПОСТРОЕНИЯ SQL ЗАПРОСА (ВЫПОЛНЯЙ ПОШАГОВО):
═══════════════════════════════════════════════════════════════════════════════

ШАГ 1: ОПРЕДЕЛИ ТИП ЗАПРОСА
  - Если упоминается МАРКА (Toyota, BMW, тойота, бмв) → используй поле 'mark'
  - Если упоминается МОДЕЛЬ (Camry, X5, "3 серии") → используй поле 'model'
  - ⚠️ ВАЖНО: Если упоминается И МАРКА И МОДЕЛЬ → используй ОБА поля через AND
  - Если упоминается ЦВЕТ (красный, синий, черный, red, blue, black, "красненький") → используй поле 'color'
  - ⚠️ КРИТИЧЕСКИ ВАЖНО: Для ЦВЕТА учитывай РУССКИЙ И АНГЛИЙСКИЙ языки!
    Примеры: "красный" = RED, "синий" = BLUE, "черный" = BLACK, "белый" = WHITE
  - Если упоминается КПП (автомат, механика, автоматическая, механическая, automatic, manual) → используй поле 'gear_box_type'
    ⚠️ КРИТИЧЕСКИ ВАЖНО: "автомат", "механика" - это про КПП, НЕ про марку!
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Для КПП учитывай РУССКИЙ И АНГЛИЙСКИЙ языки!
    ❌ НЕПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%AUTOMAT%'  -- ОШИБКА! "автомат" - это КПП, не марка!
    ✅ ПРАВИЛЬНО: WHERE (LOWER(gear_box_type) LIKE '%автомат%' OR LOWER(gear_box_type) LIKE '%automatic%')
  - Если упоминается ТОПЛИВО (бензин, дизель, petrol, diesel) → используй поле 'fuel_type'
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Для топлива учитывай РУССКИЙ И АНГЛИЙСКИЙ языки!
  - Если упоминается КУЗОВ (седан, кроссовер, sedan, suv) → используй поле 'body_type'
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Для кузова учитывай РУССКИЙ И АНГЛИЙСКИЙ языки!
  - Если упоминается ГОРОД (Москва, Санкт-Петербург, Moscow, Saint-Petersburg) → используй поле 'city'
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Для города учитывай РУССКИЙ И АНГЛИЙСКИЙ языки!
  - Если упоминается ПРИВОД (полный, передний, задний, all-wheel, front-wheel) → используй поле 'driving_gear_type'
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Для привода учитывай РУССКИЙ И АНГЛИЙСКИЙ языки!
  - Если упоминается ПРОБЕГ (с пробегом, меньше 10000, до 50000 км) → используй поле 'mileage'
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Поле 'mileage' существует ТОЛЬКО в таблице 'used_cars'!
    ❌ НЕПРАВИЛЬНО: SELECT * FROM cars WHERE mileage < 10000  -- ОШИБКА! В cars НЕТ mileage!
    ✅ ПРАВИЛЬНО: SELECT * FROM used_cars WHERE mileage < 10000  -- ПРАВИЛЬНО!

ШАГ 2: ВЫБЕРИ ТАБЛИЦУ
  - Если про новые авто → 'cars'
  - Если про подержанные → 'used_cars'
  - Если не указано → используй ОБЕ таблицы через UNION ALL

ШАГ 3: ПОСТРОЙ WHERE УСЛОВИЕ
  - Для МАРКИ: UPPER(mark) LIKE '%МАРКА%' (НЕ model, НЕ code!)
  - Для МОДЕЛИ: UPPER(model) LIKE '%МОДЕЛЬ%'
  - Для ЦВЕТА: (UPPER(color) LIKE '%РУССКИЙ_ЦВЕТ%' OR UPPER(color) LIKE '%ENGLISH_COLOR%')
    Примеры:
    - Красный: (UPPER(color) LIKE '%КРАСН%' OR UPPER(color) LIKE '%RED%')
    - Синий: (UPPER(color) LIKE '%СИНИЙ%' OR UPPER(color) LIKE '%СИН%' OR UPPER(color) LIKE '%BLUE%')
    - Черный: (UPPER(color) LIKE '%ЧЕРН%' OR UPPER(color) LIKE '%BLACK%')
    - Белый: (UPPER(color) LIKE '%БЕЛ%' OR UPPER(color) LIKE '%WHITE%')
  - Для КПП: (LOWER(gear_box_type) LIKE '%РУССКИЙ_КПП%' OR LOWER(gear_box_type) LIKE '%ENGLISH_GEARBOX%')
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Всегда учитывай ОБА языка (русский И английский)!
    Примеры:
    - Автомат: (LOWER(gear_box_type) LIKE '%автомат%' OR LOWER(gear_box_type) LIKE '%automatic%')
    - Механика: (LOWER(gear_box_type) LIKE '%механик%' OR LOWER(gear_box_type) LIKE '%manual%')
  - Для ТОПЛИВА: (LOWER(fuel_type) LIKE '%РУССКИЙ_ТОПЛИВО%' OR LOWER(fuel_type) LIKE '%ENGLISH_FUEL%')
    Примеры:
    - Бензин: (LOWER(fuel_type) LIKE '%бензин%' OR LOWER(fuel_type) LIKE '%petrol%' OR LOWER(fuel_type) LIKE '%gasoline%')
    - Дизель: (LOWER(fuel_type) LIKE '%дизель%' OR LOWER(fuel_type) LIKE '%diesel%')
  - Для КУЗОВА: (LOWER(body_type) LIKE '%РУССКИЙ_КУЗОВ%' OR LOWER(body_type) LIKE '%ENGLISH_BODY%')
    Примеры:
    - Седан: (LOWER(body_type) LIKE '%седан%' OR LOWER(body_type) LIKE '%sedan%')
    - Кроссовер: (LOWER(body_type) LIKE '%кроссовер%' OR LOWER(body_type) LIKE '%suv%' OR LOWER(body_type) LIKE '%crossover%')
  - Для ГОРОДА: (UPPER(city) LIKE '%РУССКИЙ_ГОРОД%' OR UPPER(city) LIKE '%ENGLISH_CITY%')
    Примеры:
    - Москва: (UPPER(city) LIKE '%МОСКВА%' OR UPPER(city) LIKE '%MOSCOW%')
    - Санкт-Петербург: (UPPER(city) LIKE '%САНКТ-ПЕТЕРБУРГ%' OR UPPER(city) LIKE '%SAINT%PETERSBURG%' OR UPPER(city) LIKE '%SPB%')
  - Для ПРИВОДА: (LOWER(driving_gear_type) LIKE '%РУССКИЙ_ПРИВОД%' OR LOWER(driving_gear_type) LIKE '%ENGLISH_DRIVE%')
    Примеры:
    - Полный: (LOWER(driving_gear_type) LIKE '%полный%' OR LOWER(driving_gear_type) LIKE '%all%wheel%' OR LOWER(driving_gear_type) LIKE '%4wd%')
    - Передний: (LOWER(driving_gear_type) LIKE '%передний%' OR LOWER(driving_gear_type) LIKE '%front%wheel%' OR LOWER(driving_gear_type) LIKE '%fwd%')
  - Для ПРОБЕГА: mileage < ЧИСЛО (ТОЛЬКО в used_cars, НЕ в cars!)
    ⚠️ КРИТИЧЕСКИ ВАЖНО: Если запрос про пробег - используй ТОЛЬКО таблицу 'used_cars'!
    ❌ НЕПРАВИЛЬНО: SELECT * FROM cars WHERE mileage < 10000  -- ОШИБКА!
    ❌ НЕПРАВИЛЬНО: SELECT * FROM cars WHERE mileage < 10000 UNION ALL SELECT * FROM used_cars WHERE mileage < 10000  -- ОШИБКА! В cars нет mileage!
    ✅ ПРАВИЛЬНО: SELECT * FROM used_cars WHERE mileage < 10000  -- ТОЛЬКО used_cars!
  - Для ЦЕНЫ: CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC)

ШАГ 4: СОРТИРОВКА (ORDER BY) - КРИТИЧЕСКИ ВАЖНО:
  ⚠️ КРИТИЧЕСКИ ВАЖНО: PostgreSQL НЕ ПОЗВОЛЯЕТ использовать вычисляемые поля (CAST, REPLACE, функции) напрямую в ORDER BY после UNION ALL!
  ⚠️ КРИТИЧЕСКИ ВАЖНО: Ошибка "invalid UNION/INTERSECT/EXCEPT ORDER BY clause" возникает, если в ORDER BY используется выражение вместо имени колонки!
  ⚠️ КРИТИЧЕСКИ ВАЖНО: Если нужна сортировка по цене в UNION ALL - ВСЕГДА создай псевдоним numeric_price в SELECT обеих частей!
  ⚠️ КРИТИЧЕСКИ ВАЖНО: НИКОГДА не используй SELECT * вместе с дополнительными колонками в UNION ALL!
  ⚠️ КРИТИЧЕСКИ ВАЖНО: В обеих частях UNION ALL должно быть ОДИНАКОВОЕ количество колонок!
  
  ❌ НЕПРАВИЛЬНО - ORDER BY с вычисляемым полем (ВЫЗОВЕТ ОШИБКУ):
  SELECT mark, model, price FROM cars WHERE ...
  UNION ALL
  SELECT mark, model, price FROM used_cars WHERE ...
  ORDER BY CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) DESC;
  -- ОШИБКА: "invalid UNION/INTERSECT/EXCEPT ORDER BY clause - Only result column names can be used, not expressions or functions"
  
  ❌ НЕПРАВИЛЬНО - SELECT * с дополнительными колонками:
  SELECT *, CAST(...) AS numeric_price FROM cars ... UNION ALL SELECT *, CAST(...) AS numeric_price FROM used_cars ...
  -- ОШИБКА! SELECT * уже включает все колонки, а потом добавляется numeric_price - разное количество колонок!
  
  ✅ ПРАВИЛЬНО - сортировка по цене с псевдонимом (если нужны дополнительные колонки из used_cars):
  SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, 
         NULL AS mileage, NULL AS power, NULL AS driving_gear_type, NULL AS engine_vol,
         CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price
  FROM cars WHERE ...
  UNION ALL
  SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type,
         mileage, power, driving_gear_type, engine_vol,
         CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price
  FROM used_cars WHERE ...
  ORDER BY numeric_price DESC;
  
  ✅ ПРАВИЛЬНО - сортировка по цене БЕЗ дополнительных колонок (только базовые):
  SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type,
         CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price
  FROM cars WHERE ...
  UNION ALL
  SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type,
         CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price
  FROM used_cars WHERE ...
  ORDER BY numeric_price DESC;
  -- ПРАВИЛЬНО! Используем псевдоним numeric_price, который определен в SELECT обеих частей
  
  ✅ ПРАВИЛЬНО - сортировка по простому полю (без вычислений):
  SELECT mark, model, price, manufacture_year FROM cars WHERE ...
  UNION ALL
  SELECT mark, model, price, manufacture_year FROM used_cars WHERE ...
  ORDER BY manufacture_year DESC, mark ASC;
  -- ПРАВИЛЬНО! Простые поля можно использовать напрямую в ORDER BY

ШАГ 5: ПРОВЕРЬ ПЕРЕД ГЕНЕРАЦИЕЙ
  ✓ Используешь 'mark' для марок, а не 'model' или 'code'?
  ✓ Если запрос про "автомат" или "механика" - используешь поле 'gear_box_type', НЕ 'mark'?
  ✓ Если запрос про ЦВЕТ - используешь поле 'color' с учетом русского И английского?
  ✓ Если запрос про КПП, ТОПЛИВО, КУЗОВ, ГОРОД, ПРИВОД - учитываешь русский И английский языки?
  ✓ Если запрос про ПРОБЕГ - используешь ТОЛЬКО таблицу 'used_cars', НЕ cars и НЕ UNION?
  ✓ Используешь UPPER() с LIKE для марок и городов?
  ✓ Используешь LOWER() с LIKE для КПП, топлива, кузова, привода?
  ✓ Используешь CAST для цены?
  ✓ Используешь правильную таблицу (cars или used_cars)?
  ✓ НЕ используешь SELECT * в UNION ALL?
  ✓ Если нужна сортировка по цене - создал псевдоним numeric_price в SELECT ОБЕИХ частей UNION ALL?
  ✓ В обеих частях UNION ALL одинаковое количество колонок?
  ✓ НЕ используешь CAST/REPLACE/функции напрямую в ORDER BY после UNION ALL?
  ✓ Если в ORDER BY используется вычисляемое поле - создал псевдоним в SELECT и используешь его в ORDER BY?

═══════════════════════════════════════════════════════════════════════════════
ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}
═══════════════════════════════════════════════════════════════════════════════

ВАЖНО: Используй примеры выше как образец. Сгенерируй ТОЛЬКО SQL запрос (без объяснений, без markdown, без дополнительного текста):
SQL запрос:"""

        prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_template),
            HumanMessagePromptTemplate.from_template(user_template)
        ])
        
        return prompt
    
    async def generate_sql(
        self,
        question: str,
        schema: str,
        model_config: str,
        api_key: Optional[str] = None
    ) -> str:
        """
        Генерирует SQL запрос используя LangChain
        
        Args:
            question: Вопрос пользователя
            schema: Схема базы данных
            model_config: Конфигурация модели (например, "ollama:llama3:8b")
            api_key: API ключ (если требуется)
        
        Returns:
            str: Сгенерированный SQL запрос
        """
        # Получаем LLM
        llm = self.get_llm(model_config, api_key)
        
        # Очищаем вопрос от параметров, если они есть (но не используем их)
        if "🚨🚨🚨 КРИТИЧЕСКИ ВАЖНО: В запросе есть расплывчатые компоненты" in question:
            params_start = question.find("СГЕНЕРИРОВАННЫЕ ПАРАМЕТРЫ (ОБЯЗАТЕЛЬНО ИСПОЛЬЗУЙ В SQL):")
            if params_start != -1:
                # Удаляем секцию с параметрами из вопроса
                question = question[:params_start].strip()
        
        # Создаем промпт без параметров
        prompt_template = self.create_sql_prompt_template("")
        
        # Создаем цепочку
        few_shot_examples = """
═══════════════════════════════════════════════════════════════════════════════
ПРИМЕРЫ ЗАПРОСОВ И ОТВЕТОВ (ИСПОЛЬЗУЙ КАК ОБРАЗЕЦ):
═══════════════════════════════════════════════════════════════════════════════

⚠️ КРИТИЧЕСКИ ВАЖНО: НИКОГДА не используй SELECT * в UNION ALL!
⚠️ ВСЕГДА указывай явные колонки: mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type
⚠️ КРИТИЧЕСКИ ВАЖНО: Если в SELECT есть колонки из used_cars (mileage, power, driving_gear_type, engine_vol и т.д.):
   - В первой части (FROM cars) используй NULL AS mileage, NULL AS power, NULL AS driving_gear_type, NULL AS engine_vol и т.д.
   - Во второй части (FROM used_cars) используй реальные поля: mileage, power, driving_gear_type, engine_vol и т.д.
   - НИКОГДА не используй mileage, power и т.д. в SELECT из cars - это вызовет ошибку "column does not exist"!
⚠️ Если нужна сортировка по цене - ВСЕГДА создай псевдоним numeric_price в SELECT ОБЕИХ частей UNION ALL, затем используй его в ORDER BY
⚠️ НИКОГДА не используй CAST/REPLACE/функции напрямую в ORDER BY после UNION ALL - это вызовет ошибку "invalid UNION/INTERSECT/EXCEPT ORDER BY clause"!
⚠️ ОШИБКА: ORDER BY CAST(REPLACE(...) AS NUMERIC) - PostgreSQL не позволяет использовать выражения в ORDER BY после UNION!
⚠️ ПРАВИЛЬНО: Создай псевдоним в SELECT, затем ORDER BY numeric_price

Вопрос: "тойота"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage FROM used_cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND price IS NOT NULL AND price != ''

Вопрос: "BMW"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%BMW%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage FROM used_cars WHERE UPPER(mark) LIKE '%BMW%' AND price IS NOT NULL AND price != ''

Вопрос: "бмв 3 серии"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%BMW%' AND UPPER(model) LIKE '%3%' AND UPPER(model) LIKE '%СЕРИИ%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage FROM used_cars WHERE UPPER(mark) LIKE '%BMW%' AND UPPER(model) LIKE '%3%' AND UPPER(model) LIKE '%СЕРИИ%' AND price IS NOT NULL AND price != ''

Вопрос: "Toyota Camry"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type FROM cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND UPPER(model) LIKE '%CAMRY%' AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage FROM used_cars WHERE UPPER(mark) LIKE '%TOYOTA%' AND UPPER(model) LIKE '%CAMRY%' AND price IS NOT NULL AND price != ''

Вопрос: "BMW дешевле 5000000"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price FROM cars WHERE UPPER(mark) LIKE '%BMW%' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) < 5000000 AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price FROM used_cars WHERE UPPER(mark) LIKE '%BMW%' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) < 5000000 AND price IS NOT NULL AND price != ''

Вопрос: "седан автомат до 5 млн, отсортировать по цене от дорогих к дешевым"
SQL: SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price FROM cars WHERE (LOWER(body_type) LIKE '%седан%' OR LOWER(body_type) LIKE '%sedan%') AND (LOWER(gear_box_type) LIKE '%автомат%' OR LOWER(gear_box_type) LIKE '%automatic%') AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) <= 5000000 AND price IS NOT NULL AND price != '' UNION ALL SELECT mark, model, price, manufacture_year, city, body_type, fuel_type, gear_box_type, NULL AS mileage, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) AS numeric_price FROM used_cars WHERE (LOWER(body_type) LIKE '%седан%' OR LOWER(body_type) LIKE '%sedan%') AND (LOWER(gear_box_type) LIKE '%автомат%' OR LOWER(gear_box_type) LIKE '%automatic%') AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS NUMERIC) <= 5000000 AND price IS NOT NULL AND price != '' ORDER BY numeric_price DESC

═══════════════════════════════════════════════════════════════════════════════
"""
        
        # Формируем входные данные для промпта
        prompt_input = {
            "few_shot_examples": few_shot_examples,
            "schema": schema,
            "question": question
        }
        
        # Создаем цепочку
        chain = prompt_template | llm | StrOutputParser()
        
        # Выполняем цепочку асинхронно
        result = await chain.ainvoke(prompt_input)
        
        return result

