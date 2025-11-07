from typing import Dict, Any, List, Optional, Tuple
import re
import httpx
import time
import asyncio
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
import json
import os
from app.core.config import settings
from services.ai_service import AIService

# Запрещенные SQL ключевые слова для безопасности
FORBIDDEN_KEYWORDS = [
    'DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'CREATE', 
    'INSERT', 'UPDATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
    'MERGE', 'CALL', 'LOCK', 'UNLOCK'
]

# Разрешенные только SELECT операции
ALLOWED_OPERATIONS = ['SELECT']


class SQLAgentService:
    """Сервис для генерации SQL-запросов через LLM и их безопасного выполнения"""
    
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.engine = db_session.bind
        self.ai_service = AIService()
        self.retry_delay = 1  # Начальная задержка для retry
        
    def get_database_schema(self) -> str:
        """Получает детальную схему базы данных для промпта LLM с примерами данных"""
        inspector = inspect(self.engine)
        schema_info = []
        
        # Фокус на таблицах с автомобилями
        car_tables = ['cars', 'used_cars', 'car_pictures', 'used_car_pictures', 
                     'car_options', 'car_options_groups']
        tables = [t for t in inspector.get_table_names() if t in car_tables] or inspector.get_table_names()
        
        for table_name in tables:
            columns = inspector.get_columns(table_name)
            primary_keys = inspector.get_pk_constraint(table_name)
            foreign_keys = inspector.get_foreign_keys(table_name)
            
            table_info = f"\n{'='*80}\n"
            table_info += f"ТАБЛИЦА: {table_name}\n"
            table_info += f"{'='*80}\n"
            
            # Описание таблицы
            if table_name == 'cars':
                table_info += "ОПИСАНИЕ: Таблица новых автомобилей (автомобили из салона)\n"
            elif table_name == 'used_cars':
                table_info += "ОПИСАНИЕ: Таблица подержанных автомобилей (автомобили с пробегом)\n"
            elif table_name in ['car_pictures', 'used_car_pictures']:
                table_info += f"ОПИСАНИЕ: Фотографии автомобилей (связь через {table_name.split('_')[0]}_id)\n"
            elif table_name == 'car_options':
                table_info += "ОПИСАНИЕ: Опции/комплектация новых автомобилей (связь через car_id)\n"
            elif table_name == 'car_options_groups':
                table_info += "ОПИСАНИЕ: Группы опций для новых автомобилей (связь через car_id)\n"
            
            table_info += "\nКОЛОНКИ:\n"
            
            for col in columns:
                col_type = str(col['type'])
                nullable = "NULL" if col['nullable'] else "NOT NULL"
                indexed = "INDEXED" if col['name'] in ['mark', 'model', 'city', 'fuel_type', 
                                                       'body_type', 'gear_box_type', 'manufacture_year', 
                                                       'vin', 'mileage', 'car_id'] else ""
                table_info += f"  • {col['name']}: {col_type} {nullable} {indexed}\n"
                
                # Добавляем пояснения для важных полей
                field_descriptions = {
                    'mark': 'МАРКА автомобиля (например: Toyota, BMW, Chery, OMODA, DONGFENG, Hongqi, AITO, Москвич, CHANGAN, JAC, Belgee)',
                    'model': 'МОДЕЛЬ автомобиля',
                    'price': 'ЦЕНА (строка в формате "1234567.0", может содержать пробелы, запятые, символ ₽)',
                    'city': 'ГОРОД (например: Москва, Санкт-Петербург, Краснодар, Ростов-на-Дону, Воронеж)',
                    'fuel_type': 'ТИП ТОПЛИВА (например: бензин, дизель, гибрид, электрический, Бензин, Дизель)',
                    'body_type': 'ТИП КУЗОВА (например: Кроссовер, Внедорожник, Седан, Пикап, Хетчбэк, Седан)',
                    'gear_box_type': 'ТИП КПП (например: автомат, механика, автоматическая, Механика, Automatic, automatic, автомат)',
                    'driving_gear_type': 'ТИП ПРИВОДА (например: передний, полный, задний, Передний, Полный)',
                    'manufacture_year': 'ГОД ВЫПУСКА (целое число, например: 2023, 2024)',
                    'engine_vol': 'ОБЪЕМ ДВИГАТЕЛЯ в литрах (целое число, например: 1499 = 1.5л, 2000 = 2.0л)',
                    'power': 'МОЩНОСТЬ в л.с. (строка, например: "145.0", "169.0")',
                    'color': 'ЦВЕТ кузова',
                    'mileage': 'ПРОБЕГ в км (только в used_cars, целое число)',
                    'stock_qty': 'КОЛИЧЕСТВО НА СКЛАДЕ (только в cars)',
                    'owners': 'КОЛИЧЕСТВО ВЛАДЕЛЬЦЕВ (только в used_cars)',
                    'vin': 'VIN номер автомобиля',
                    'dealer_center': 'ДИЛЕРСКИЙ ЦЕНТР',
                    'car_id': 'ID автомобиля (для связи с опциями в таблице car_options)',
                    'description': 'Описание опции (например: "Антиблокировочная система (ABS)", "Круиз-контроль")',
                    'code': 'Код опции',
                    'name': 'Название группы опций (например: "Безопасность", "Комфорт")',
                }
                
                if col['name'] in field_descriptions:
                    table_info += f"    └─ {field_descriptions[col['name']]}\n"
            
            if primary_keys.get('constrained_columns'):
                table_info += f"\nПЕРВИЧНЫЙ КЛЮЧ: {', '.join(primary_keys['constrained_columns'])}\n"
            
            if foreign_keys:
                table_info += "\nВНЕШНИЕ КЛЮЧИ:\n"
                for fk in foreign_keys:
                    table_info += f"  • {', '.join(fk['constrained_columns'])} -> {fk['referred_table']}({', '.join(fk['referred_columns'])})\n"
            
            # Получаем примеры данных для ключевых таблиц
            if table_name in ['cars', 'used_cars']:
                try:
                    with self.engine.connect() as conn:
                        # Примеры марок
                        marks_result = conn.execute(text(
                            f"SELECT DISTINCT mark FROM {table_name} WHERE mark IS NOT NULL AND mark != '' LIMIT 10"
                        ))
                        marks = [r[0] for r in marks_result.fetchall()]
                        
                        # Примеры городов
                        cities_result = conn.execute(text(
                            f"SELECT DISTINCT city FROM {table_name} WHERE city IS NOT NULL AND city != '' LIMIT 10"
                        ))
                        cities = [r[0] for r in cities_result.fetchall()]
                        
                        # Примеры типов кузова
                        body_types_result = conn.execute(text(
                            f"SELECT DISTINCT body_type FROM {table_name} WHERE body_type IS NOT NULL AND body_type != '' LIMIT 10"
                        ))
                        body_types = [r[0] for r in body_types_result.fetchall()]
                        
                        # Примеры типов топлива
                        fuel_types_result = conn.execute(text(
                            f"SELECT DISTINCT fuel_type FROM {table_name} WHERE fuel_type IS NOT NULL AND fuel_type != '' LIMIT 5"
                        ))
                        fuel_types = [r[0] for r in fuel_types_result.fetchall()]
                        
                        table_info += "\nПРИМЕРЫ ДАННЫХ:\n"
                        if marks:
                            table_info += f"  Марки: {', '.join(marks[:10])}\n"
                        if cities:
                            table_info += f"  Города: {', '.join(cities[:10])}\n"
                        if body_types:
                            table_info += f"  Типы кузова: {', '.join(body_types[:10])}\n"
                        if fuel_types:
                            table_info += f"  Типы топлива: {', '.join(fuel_types[:5])}\n"
                except Exception as e:
                    # Если не удалось получить примеры, продолжаем
                    pass
            
            # Получаем примеры опций для таблицы car_options
            if table_name == 'car_options':
                try:
                    with self.engine.connect() as conn:
                        # Примеры описаний опций
                        options_result = conn.execute(text(
                            "SELECT DISTINCT description FROM car_options WHERE description IS NOT NULL AND description != '' LIMIT 15"
                        ))
                        options = [r[0] for r in options_result.fetchall()]
                        
                        table_info += "\nПРИМЕРЫ ОПЦИЙ:\n"
                        if options:
                            table_info += f"  Опции: {', '.join(options[:15])}\n"
                        
                        # Примеры групп опций
                        groups_result = conn.execute(text(
                            "SELECT DISTINCT name FROM car_options_groups WHERE name IS NOT NULL AND name != '' LIMIT 10"
                        ))
                        groups = [r[0] for r in groups_result.fetchall()]
                        
                        if groups:
                            table_info += f"  Группы опций: {', '.join(groups[:10])}\n"
                except Exception as e:
                    # Если не удалось получить примеры, продолжаем
                    pass
            
            schema_info.append(table_info)
        
        return "\n".join(schema_info)
    
    def validate_sql_query(self, sql_query: str) -> Tuple[bool, str]:
        """
        Валидация SQL запроса на безопасность
        Возвращает (is_valid, error_message)
        """
        if not sql_query:
            return False, "Пустой SQL запрос"
        
        # Удаляем комментарии
        sql_clean = re.sub(r'--.*$', '', sql_query, flags=re.MULTILINE)
        sql_clean = re.sub(r'/\*.*?\*/', '', sql_clean, flags=re.DOTALL)
        
        # Приводим к верхнему регистру для проверки
        sql_upper = sql_clean.upper().strip()
        
        # Проверяем на запрещенные ключевые слова
        for keyword in FORBIDDEN_KEYWORDS:
            # Используем word boundary для точного совпадения
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, sql_upper):
                return False, f"Запрещено использование ключевого слова: {keyword}"
        
        # Проверяем, что запрос начинается с разрешенной операции
        first_word = sql_upper.split()[0] if sql_upper.split() else ""
        if first_word not in ALLOWED_OPERATIONS:
            return False, f"Разрешены только операции: {', '.join(ALLOWED_OPERATIONS)}"
        
        # Дополнительная проверка на попытки выполнения функций
        dangerous_patterns = [
            r'INTO\s+OUTFILE',
            r'INTO\s+DUMPFILE',
            r'LOAD_FILE',
            r'LOAD_DATA',
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, sql_upper):
                return False, "Обнаружен опасный паттерн в SQL запросе"
        
        return True, ""
    
    async def generate_sql_from_natural_language(
        self, 
        question: str,
        use_ai_settings: bool = True
    ) -> Dict[str, Any]:
        """
        Генерирует SQL запрос из естественного языка с помощью LLM
        """
        try:
            # Получаем схему БД
            schema = self.get_database_schema()
            
            # Формируем улучшенный промпт для LLM
            prompt = f"""Ты — эксперт по SQL для автомобильной базы данных. База данных использует SQLite.

═══════════════════════════════════════════════════════════════════════════════
КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ДЛЯ SQLite:
═══════════════════════════════════════════════════════════════════════════════

1. БЕЗОПАСНОСТЬ:
   - Используй ТОЛЬКО оператор SELECT
   - НЕ используй: DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, EXEC, EXECUTE
   - Запрещены любые операции изменения данных

2. SQLite ОГРАНИЧЕНИЯ:
   - SQLite НЕ поддерживает регулярные выражения (REGEXP, REGEXP_LIKE)
   - SQLite НЕ поддерживает сложные регулярные выражения в REPLACE()
   - Для очистки строк используй вложенные REPLACE(): REPLACE(REPLACE(REPLACE(...)))
   - Используй стандартные SQL функции: UPPER(), LOWER(), LIKE, CAST()

3. РЕГИСТРОНЕЗАВИСИМЫЙ ПОИСК МАРОК И ГОРОДОВ:
   - ВСЕГДА используй UPPER() с LIKE для поиска марок (НЕ используй =):
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%TOYOTA%'  -- найдет Toyota, TOYOTA, toyota
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%BMW%'      -- найдет BMW, bmw, Bmw
     ❌ НЕПРАВИЛЬНО: WHERE UPPER(mark) = 'BMW'        -- может не найти из-за пробелов
     ❌ НЕПРАВИЛЬНО: WHERE mark = 'Toyota'           -- не найдет варианты регистра
   
   - Для городов тоже используй регистронезависимый поиск с LIKE:
     ✅ ПРАВИЛЬНО: WHERE UPPER(city) LIKE '%МОСКВА%'
     ✅ ПРАВИЛЬНО: WHERE UPPER(city) LIKE '%РОСТОВ%'
   
   - ВАЖНО: В базе могут быть пробелы или различия в регистре, поэтому ВСЕГДА используй LIKE, а не =

4. РАБОТА С ЦЕНАМИ (SQLite):
   - Цена хранится как STRING и может содержать: пробелы, запятые, символ ₽
   - Очистка цены для SQLite (используй вложенные REPLACE):
     ✅ ПРАВИЛЬНО: CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL)
     ✅ ПРАВИЛЬНО: CAST(REPLACE(REPLACE(price, ' ', ''), ',', '.') AS REAL)
     ❌ НЕПРАВИЛЬНО: REPLACE(price, '[^0-9]', '') (SQLite не поддерживает regex)
   
   - Всегда проверяй наличие цены:
     ✅ ПРАВИЛЬНО: WHERE price IS NOT NULL AND price != ''

5. ПОИСК ПО ТИПАМ (КПП, топливо, кузов):
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: В SQLite UPPER() с кириллицей работает НЕКОРРЕКТНО!
     ❌ НЕ используй: UPPER(fuel_type) LIKE '%БЕНЗИН%' (НЕ РАБОТАЕТ в SQLite!)
   
   - В базе РАЗНЫЕ варианты написания в таблицах cars и used_cars:
     - Топливо в cars: 'бензин' (маленькими), в used_cars: 'Бензин' (с заглавной)
     - Топливо в cars: 'дизель' (маленькими), в used_cars: 'Дизель' (с заглавной)
     - Кузов в cars: 'Седан', в used_cars: 'Седан' (оба с заглавной)
   
   - ✅ ИСПОЛЬЗУЙ LOWER() для кириллицы:
     ✅ ПРАВИЛЬНО: WHERE LOWER(fuel_type) LIKE '%бензин%'  -- найдет и 'бензин' и 'Бензин'
     ✅ ПРАВИЛЬНО: WHERE LOWER(body_type) LIKE '%седан%'    -- найдет 'Седан'
   
   - ✅ ИЛИ используй комбинацию точных значений с OR:
     ✅ ПРАВИЛЬНО: WHERE fuel_type = 'бензин' OR fuel_type = 'Бензин' OR LOWER(fuel_type) LIKE '%бензин%'
     ✅ ПРАВИЛЬНО: WHERE (fuel_type = 'бензин' OR fuel_type = 'Бензин') AND ...
   
   - ✅ Для латиницы можно использовать UPPER():
     ✅ ПРАВИЛЬНО: WHERE UPPER(gear_box_type) LIKE '%AUTOMATIC%'  -- для английских значений
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%BMW%'                  -- для марок

5.1. РАБОТА С ПОЛЕМ dimensions (ГАБАРИТЫ):
   🚨 КРИТИЧЕСКИ ВАЖНО: Поле 'dimensions' хранит ГАБАРИТЫ автомобиля в формате "длина*ширина*высота" (например: "4665*1900*1668")
   ⚠️ ВАЖНО: В базе используется символ * (звездочка), а НЕ × (крестик)!
   
   - Формат данных: "длина*ширина*высота" (разделитель - символ * (звездочка))
   - Примеры: "4665*1900*1668", "4985*1865*1465", "5416*1947*1884"
   - Длина: общая длина автомобиля (обычно 4000-5500 мм)
   - Ширина: общая ширина автомобиля (обычно 1700-2000 мм)
   - Высота: общая высота автомобиля до крыши (обычно 1400-2000 мм)
   
   ⚠️ ВАЖНО: dimensions - это ГАБАРИТЫ, а НЕ клиренс!
   - Клиренс (дорожный просвет) - это расстояние от земли до нижней точки автомобиля (обычно 15-25 см)
   - Высота в dimensions - это высота автомобиля до крыши (обычно 140-200 см)
   - Это РАЗНЫЕ параметры! Высота автомобиля НЕ равна клиренсу!
   
   🚨 КРИТИЧЕСКИ ВАЖНО: Клиренс (дорожный просвет) ОТСУТСТВУЕТ в базе данных!
   - Клиренс НЕ хранится в поле dimensions
   - Клиренс НЕ найден в опциях автомобилей (car_options.description)
   - Для запросов о клиренсе НЕВОЗМОЖНО использовать SQL-запросы к базе данных
   - Рекомендуется использовать Elasticsearch для поиска по текстовым описаниям, если там есть информация о клиренсе
   
   ✅ ПРАВИЛЬНО - извлечение высоты из dimensions (для работы с габаритами):
   SELECT mark, model, dimensions,
          CAST(REPLACE(REPLACE(TRIM(SUBSTR(
              SUBSTR(dimensions, INSTR(dimensions, '*') + 1),
              INSTR(SUBSTR(dimensions, INSTR(dimensions, '*') + 1), '*') + 1
          )), ' ', ''), ',', '.') AS REAL) AS height_cm
   FROM cars
   WHERE dimensions IS NOT NULL AND dimensions != ''
   AND dimensions LIKE '%*%*%';
   
   ⚠️ ВАЖНО: Если используешь dimensions в UNION, создай псевдоним в SELECT:
   ✅ ПРАВИЛЬНО:
   SELECT mark, model, dimensions, 
          CAST(REPLACE(REPLACE(TRIM(SUBSTR(
              SUBSTR(dimensions, INSTR(dimensions, '*') + 1),
              INSTR(SUBSTR(dimensions, INSTR(dimensions, '*') + 1), '*') + 1
          )), ' ', ''), ',', '.') AS REAL) AS height_cm
   FROM cars WHERE dimensions IS NOT NULL AND dimensions LIKE '%*%*%'
   UNION ALL
   SELECT mark, model, dimensions,
          CAST(REPLACE(REPLACE(TRIM(SUBSTR(
              SUBSTR(dimensions, INSTR(dimensions, '*') + 1),
              INSTR(SUBSTR(dimensions, INSTR(dimensions, '*') + 1), '*') + 1
          )), ' ', ''), ',', '.') AS REAL) AS height_cm
   FROM used_cars WHERE dimensions IS NOT NULL AND dimensions LIKE '%*%*%'
   ORDER BY height_cm DESC;  -- используй псевдоним height_cm, НЕ c.dimensions или uc.dimensions!
   
   ❌ НЕПРАВИЛЬНО - использование префиксов таблиц в ORDER BY:
   SELECT ... c.dimensions ... FROM cars c
   UNION ALL
   SELECT ... uc.dimensions ... FROM used_cars uc
   ORDER BY CASE WHEN c.dimensions IS NOT NULL THEN ... -- ОШИБКА: c.dimensions нет в SELECT!
   
   ✅ ПРАВИЛЬНО - создай псевдоним и используй его:
   SELECT ... dimensions, ... AS height_cm FROM cars
   UNION ALL
   SELECT ... dimensions, ... AS height_cm FROM used_cars
   ORDER BY height_cm DESC;  -- используй псевдоним!

6. ОБЪЕДИНЕНИЕ ТАБЛИЦ cars И used_cars:
   ⚠️ КРИТИЧЕСКИ ВАЖНО: Таблицы cars и used_cars имеют РАЗНОЕ количество колонок!
   
   ❌ НИКОГДА не используй SELECT * в UNION между cars и used_cars!
   ❌ НЕПРАВИЛЬНО: SELECT * FROM cars UNION ALL SELECT * FROM used_cars;
   
   ⚠️ УТОЧНЕНИЯ ПО СХЕМЕ ТАБЛИЦ:
   - Таблица 'cars' (новые авто): НЕТ колонки 'mileage' (пробега нет у новых авто)
   - Таблица 'used_cars' (подержанные): ЕСТЬ колонка 'mileage' (пробег есть у подержанных)
   - В запросах с UNION ВСЕГДА проверяй наличие колонок в обеих таблицах!
   - Если колонка есть только в одной таблице, используй NULL для другой
   - ❌ НИКОГДА не используй колонку mileage в таблице cars - её там НЕТ!
   - ❌ НИКОГДА не используй CASE WHEN mileage IS NULL в таблице cars - mileage не существует!
   
   ✅ ВСЕГДА указывай явные колонки при UNION:
   ✅ ПРАВИЛЬНО: SELECT mark, model, price, manufacture_year, city FROM cars
                  UNION ALL
                  SELECT mark, model, price, manufacture_year, city FROM used_cars;
   
   ✅ Для отсутствующих колонок используй NULL:
   ✅ ПРАВИЛЬНО: SELECT mark, model, price, NULL AS mileage FROM cars
                  UNION ALL
                  SELECT mark, model, price, mileage FROM used_cars;
   
   ⚠️ ВАЖНО: Не пытайся использовать колонки из одной таблицы в другой через CASE или другие способы!
   ❌ НЕПРАВИЛЬНО: SELECT ... CASE WHEN mileage IS NULL THEN 'new' ELSE 'used' END FROM cars
                  -- ОШИБКА: mileage не существует в cars! Нельзя проверять несуществующую колонку!
   
   ❌ НЕПРАВИЛЬНО: SELECT mark, model, CASE WHEN mileage IS NULL THEN 'new' ELSE 'used' END AS car_type, mileage
                  FROM cars WHERE ...
                  -- ОШИБКА: mileage не существует в cars!
   
   ✅ ПРАВИЛЬНО - если нужно определить тип:
   SELECT mark, model, price, 'new' AS car_type, NULL AS mileage FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, 'used' AS car_type, mileage FROM used_cars WHERE condition;
   
   ✅ При объединении убедись, что:
     - Количество колонок одинаково в обеих частях UNION
     - Порядок колонок одинаков
     - Типы колонок совместимы
     - НЕ используй колонки, которые есть только в одной таблице, в обеих частях UNION
     - Если нужна колонка mileage - используй NULL в cars, а в used_cars бери реальное значение
   
   - Для новых авто: используй таблицу 'cars' (БЕЗ mileage!)
   - Для подержанных: используй таблицу 'used_cars' (С mileage)
   - Для всех: используй UNION с явными колонками и NULL для отсутствующих
   
   ⚠️ КРИТИЧЕСКИ ВАЖНО ПРО ORDER BY С UNION:
   
   ═══════════════════════════════════════════════════════════════════════════════
   ПРАВИЛО ДЛЯ UNION И ORDER BY (КРИТИЧЕСКИ ВАЖНО!):
   ═══════════════════════════════════════════════════════════════════════════════
   
   - ❌ ORDER BY НЕЛЬЗЯ использовать в отдельных частях UNION!
   - ✅ ORDER BY должен быть ТОЛЬКО ПОСЛЕ всего UNION запроса!
   - ❌ НЕПРАВИЛЬНО: SELECT ... ORDER BY ... UNION ALL SELECT ... ORDER BY ... (ОШИБКА!)
   - ✅ ПРАВИЛЬНО: SELECT ... UNION ALL SELECT ... ORDER BY ... (ORDER BY после UNION)
   
   - В UNION запросах ORDER BY может ссылаться ТОЛЬКО на колонки, присутствующие в SELECT
   - ❌ НЕЛЬЗЯ использовать выражения или вычисляемые поля напрямую в ORDER BY UNION!
   - ❌ ЗАПРЕЩЕНО использовать вычисляемые выражения напрямую в ORDER BY после UNION:
     ❌ CAST(...) в ORDER BY
     ❌ REPLACE(...) в ORDER BY
     ❌ CASE WHEN ... THEN ... ELSE ... END в ORDER BY (если не создан псевдоним!)
     ❌ Любые функции в ORDER BY
     ❌ Любые вычисления в ORDER BY
   
   ✅ ПРАВИЛО: Если нужна сортировка по вычисляемому значению:
     1) СОЗДАЙ вычисляемое поле в SELECT с псевдонимом (AS alias_name)
     2) СОЗДАЙ этот псевдоним в ОБЕИХ частях UNION
     3) Используй этот псевдоним в ORDER BY ПОСЛЕ UNION
   
   ⚠️ ДЛЯ CASE В ORDER BY:
   - Если нужна сортировка по CASE выражению - СОЗДАЙ ПСЕВДОНИМ в SELECT для обеих частей UNION!
   - ❌ НИКОГДА не используй CASE напрямую в ORDER BY после UNION без псевдонима
   - ❌ НИКОГДА не используй CASE WHEN city IS NULL THEN ... в ORDER BY без создания псевдонима в SELECT!
   
   ⚠️ ДЛЯ CAST В ORDER BY:
   - Если нужна сортировка по цене - СОЗДАЙ ПСЕВДОНИМ price_num в SELECT!
   - ❌ НИКОГДА не используй CAST(REPLACE(...)) напрямую в ORDER BY после UNION!
   - ✅ СОЗДАЙ: CAST(REPLACE(...) AS REAL) AS price_num в SELECT, затем ORDER BY price_num
   
   ❌ НЕПРАВИЛЬНО - CAST напрямую в ORDER BY:
   SELECT mark, model, price FROM cars WHERE ... 
   UNION ALL 
   SELECT mark, model, price FROM used_cars WHERE ... 
   ORDER BY CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) ASC;
   -- ОШИБКА: вычисляемое поле в ORDER BY после UNION!
   
   ✅ ПРАВИЛЬНО - Создай псевдоним price_num в SELECT:
   SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
   FROM cars WHERE price IS NOT NULL AND price != '' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) < 1000000
   UNION ALL
   SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
   FROM used_cars WHERE price IS NOT NULL AND price != '' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) < 1000000
   ORDER BY price_num ASC;  -- используем псевдоним price_num!
   
   ✅ ПРАВИЛЬНО - с вычислением цены:
   SELECT mark, model, price, CAST(REPLACE(REPLACE(price, ' ', ''), '₽', '') AS REAL) AS price_num 
   FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, CAST(REPLACE(REPLACE(price, ' ', ''), '₽', '') AS REAL) AS price_num 
   FROM used_cars WHERE condition
   ORDER BY price_num ASC;  -- используем псевдоним price_num
   
   ✅ ПРАВИЛЬНО - с CASE для сортировки:
   SELECT mark, model, CASE WHEN city IS NULL THEN 1 ELSE 0 END AS city_null_flag
   FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, CASE WHEN city IS NULL THEN 1 ELSE 0 END AS city_null_flag
   FROM used_cars WHERE condition
   ORDER BY city_null_flag ASC, mark ASC;  -- используем псевдоним city_null_flag
   
   ✅ ПРАВИЛЬНО - с типом автомобиля:
   SELECT mark, model, 'new' AS car_type FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, 'used' AS car_type FROM used_cars WHERE condition
   ORDER BY car_type DESC, mark ASC;  -- используем псевдоним car_type
   
   ❌ НЕПРАВИЛЬНО - вычисление в ORDER BY:
   SELECT mark, model, price FROM cars UNION ALL SELECT mark, model, price FROM used_cars
   ORDER BY CAST(REPLACE(price, ' ', '') AS REAL) ASC;  -- ОШИБКА: вычисление в ORDER BY
   
   ❌ НЕПРАВИЛЬНО - CASE в ORDER BY:
   SELECT mark, model FROM cars UNION ALL SELECT mark, model FROM used_cars
   ORDER BY CASE WHEN city IS NULL THEN 1 ELSE 0 END;  -- ОШИБКА: CASE в ORDER BY
   
   ❌ НЕПРАВИЛЬНО - CASE и CAST в ORDER BY:
   SELECT mark, model FROM cars UNION ALL SELECT mark, model FROM used_cars
   ORDER BY CASE WHEN city IS NULL THEN 1 ELSE 0 END, CAST(REPLACE(price, ' ', '') AS REAL);  -- ОШИБКА
   
   ❌ НЕПРАВИЛЬНО - ORDER BY в отдельных частях UNION:
   SELECT ... FROM cars ORDER BY ... LIMIT 10 UNION ALL SELECT ... FROM used_cars ORDER BY ... LIMIT 10;
   -- ОШИБКА: ORDER BY должен быть только ПОСЛЕ UNION! Нельзя использовать ORDER BY в отдельных частях!
   
   ✅ ПРАВИЛЬНО - ORDER BY после UNION (простой случай):
   SELECT ... FROM cars UNION ALL SELECT ... FROM used_cars ORDER BY ... LIMIT 20;
   
   ✅ ПРАВИЛЬНО - Если нужно ORDER BY с LIMIT в каждой части, используй подзапросы:
   SELECT * FROM (
       SELECT ... FROM cars ORDER BY ... LIMIT 10
   )
   UNION ALL
   SELECT * FROM (
       SELECT ... FROM used_cars ORDER BY ... LIMIT 10
   )
   ORDER BY вычисляемое_поле;
   
   ✅ ПРАВИЛЬНО - Если нужна сортировка по цене с подзапросами:
   SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
   FROM (
       SELECT mark, model, price FROM cars WHERE price IS NOT NULL ORDER BY CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) LIMIT 10
   )
   UNION ALL
   SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
   FROM (
       SELECT mark, model, price FROM used_cars WHERE price IS NOT NULL ORDER BY CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) LIMIT 10
   )
   ORDER BY price_num ASC;
   
   ✅ ПРАВИЛЬНЫЕ ПРИМЕРЫ UNION:
   -- Простой подсчет из обеих таблиц:
   SELECT COUNT(*) FROM cars UNION ALL SELECT COUNT(*) FROM used_cars;
   
   -- Объединение с явными колонками и правильным ORDER BY (простые колонки):
   SELECT mark, model, price, manufacture_year FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, manufacture_year FROM used_cars WHERE condition
   ORDER BY manufacture_year DESC, mark ASC;  -- простые колонки - можно использовать напрямую
   
   -- С вычисляемым полем для сортировки по цене:
   SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS numeric_price
   FROM cars WHERE price IS NOT NULL AND price != ''
   UNION ALL
   SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS numeric_price
   FROM used_cars WHERE price IS NOT NULL AND price != ''
   ORDER BY numeric_price ASC;  -- сортировка по псевдониму numeric_price
   
   -- С CASE для сложной сортировки:
   SELECT mark, model, city, 
          CASE WHEN city IS NULL THEN 1 ELSE 0 END AS city_priority,
          CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
   FROM cars WHERE price IS NOT NULL AND price != ''
   UNION ALL
   SELECT mark, model, city,
          CASE WHEN city IS NULL THEN 1 ELSE 0 END AS city_priority,
          CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
   FROM used_cars WHERE price IS NOT NULL AND price != ''
   ORDER BY city_priority ASC, price_num ASC;  -- используем псевдонимы city_priority и price_num
   
   -- С типом автомобиля для сортировки:
   SELECT mark, model, price, 'new' AS car_type FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, 'used' AS car_type FROM used_cars WHERE condition
   ORDER BY car_type DESC, mark ASC;  -- используем псевдоним car_type

7. ПОИСК ПО ОПЦИЯМ АВТОМОБИЛЕЙ:
   ⚠️ ВАЖНО: Опции хранятся в отдельной таблице 'car_options' (только для новых автомобилей в таблице 'cars')!
   🚨 КРИТИЧЕСКИ ВАЖНО: Если пользователь спрашивает про опции (ABS, круиз-контроль, кожаный салон, подогрев и т.д.), 
       ТЫ ОБЯЗАН использовать JOIN с таблицей car_options! НЕ ИЩИ опции в основной таблице cars!
   
   - Таблица 'car_options':
     • car_id - связь с автомобилем из таблицы 'cars' (INDEXED)
     • code - код опции
     • description - описание опции (например: "Антиблокировочная система (ABS)", "Круиз-контроль", "Кожаный салон", "Обогрев передних сидений")
     • options_group_id - связь с группой опций
   
   - Таблица 'car_options_groups':
     • car_id - связь с автомобилем
     • name - название группы опций (например: "Безопасность", "Внешний вид", "Комфорт")
   
   ✅ ПРАВИЛЬНО - поиск автомобилей с определенной опцией (ОБЯЗАТЕЛЬНО используй JOIN!):
   SELECT DISTINCT c.id, c.mark, c.model, c.price, c.city, c.body_type, c.fuel_type
   FROM cars c
   INNER JOIN car_options co ON c.id = co.car_id
   WHERE LOWER(co.description) LIKE '%круиз-контроль%'
   AND c.price IS NOT NULL AND c.price != '';
   
   ✅ ПРАВИЛЬНО - поиск автомобилей с опцией (аббревиатура):
   SELECT DISTINCT c.id, c.mark, c.model, c.price
   FROM cars c
   INNER JOIN car_options co ON c.id = co.car_id
   WHERE (LOWER(co.description) LIKE '%антиблокировочная%' OR LOWER(co.description) LIKE '%abs%')
   AND c.price IS NOT NULL AND c.price != '';
   
   ✅ ПРАВИЛЬНО - поиск автомобилей с несколькими опциями:
   SELECT DISTINCT c.id, c.mark, c.model, c.price
   FROM cars c
   WHERE c.id IN (
       SELECT car_id FROM car_options WHERE LOWER(description) LIKE '%кожаный салон%'
   )
   AND c.id IN (
       SELECT car_id FROM car_options WHERE LOWER(description) LIKE '%круиз-контроль%'
   )
   AND c.price IS NOT NULL AND c.price != '';
   
   ✅ ПРАВИЛЬНО - поиск автомобилей с опцией из группы:
   SELECT DISTINCT c.id, c.mark, c.model, c.price
   FROM cars c
   INNER JOIN car_options co ON c.id = co.car_id
   INNER JOIN car_options_groups cog ON co.options_group_id = cog.id
   WHERE LOWER(cog.name) LIKE '%безопасность%'
   AND c.price IS NOT NULL AND c.price != '';
   
   ✅ ПРАВИЛЬНО - комбинированный запрос (марка + опция):
   SELECT DISTINCT c.id, c.mark, c.model, c.price
   FROM cars c
   INNER JOIN car_options co ON c.id = co.car_id
   WHERE UPPER(c.mark) LIKE '%TOYOTA%'
   AND LOWER(co.description) LIKE '%кожаный салон%'
   AND c.price IS NOT NULL AND c.price != '';
   
   ✅ ПРАВИЛЬНО - подсчет автомобилей с опцией:
   SELECT COUNT(DISTINCT c.id) as car_count
   FROM cars c
   INNER JOIN car_options co ON c.id = co.car_id
   WHERE LOWER(co.description) LIKE '%круиз-контроль%'
   AND c.price IS NOT NULL AND c.price != '';
   
   ⚠️ ВАЖНО:
   - 🚨 ЕСЛИ В ЗАПРОСЕ ЕСТЬ УПОМИНАНИЕ ОПЦИЙ (ABS, круиз-контроль, кожа, подогрев, парктроник, камера и т.д.), 
     ТЫ ОБЯЗАН ИСПОЛЬЗОВАТЬ JOIN С car_options!
   - Для поиска по опциям ОБЯЗАТЕЛЬНО используй JOIN между cars и car_options (не ищи в основной таблице!)
   - Используй LOWER() для регистронезависимого поиска в описаниях опций
   - Используй LIKE '%текст%' для поиска по части описания
   - Для поиска нескольких опций используй несколько подзапросов с IN или несколько JOIN
   - ПОДЕРЖАННЫЕ автомобили (used_cars) НЕ имеют опций в таблице car_options!
   - При поиске по опциям используй DISTINCT, чтобы избежать дублирования
   
   🚨 КРИТИЧЕСКИ ВАЖНО - ЗАПРЕЩЕНО В ТАБЛИЦЕ cars:
   - ❌ ЗАПРЕЩЕНО: Использовать колонку c.mileage в запросах к таблице cars!
   - ✅ ПРАВИЛЬНО: В таблице cars НЕТ колонки mileage - используй только колонки из cars!
   - ❌ ЗАПРЕЩЕНО: SELECT c.mileage FROM cars c ...
   - ✅ ПРАВИЛЬНО: SELECT c.id, c.mark, c.model, c.price, c.city, c.body_type, c.fuel_type, c.manufacture_year, c.gear_box_type FROM cars c ...
   - ❌ ЗАПРЕЩЕНО: ORDER BY c.mileage в запросах к cars
   - ✅ ПРАВИЛЬНО: ORDER BY c.price, c.mark, c.model, c.manufacture_year
   
   ⚠️ ДОСТУПНЫЕ КОЛОНКИ В cars (для SELECT):
   - id, mark, model, price, city, body_type, fuel_type, gear_box_type, manufacture_year
   - power, engine_vol, color, dealer_center, driving_gear_type, vin, code_compl
   - ❌ НЕТ: mileage, owners, accident, certification_number
   
   🎯 ОПТИМАЛЬНЫЕ ШАБЛОНЫ ДЛЯ ПОПУЛЯРНЫХ ОПЦИЙ:
   - Круиз-контроль: LIKE '%круиз%'
   - Кожаный салон: LIKE '%кожа%'
   - Подогрев сидений: LIKE '%подогрев%' OR LIKE '%обогрев%'
   - Безопасность: LIKE '%безопасность%'
   - Камера: LIKE '%камера%' OR LIKE '%вида%'
   - Парктроник: LIKE '%парктроник%' OR LIKE '%парковки%'
   - Bluetooth: LIKE '%bluetooth%' OR LIKE '%блют%'
   - Панорама (панорамная крыша/люк): LIKE '%панорам%' OR LIKE '%люк%' OR LIKE '%sunroof%' OR LIKE '%panoramic%' OR LIKE '%крыша%'
     ⚠️ ВАЖНО: В БД опции могут быть с заглавной буквы ("Панорамный люк"), поэтому ВСЕГДА используй LOWER()!
     ✅ ПРАВИЛЬНО: WHERE LOWER(co.description) LIKE '%панорам%' OR LOWER(co.description) LIKE '%люк%'
     ❌ НЕПРАВИЛЬНО: WHERE co.description LIKE '%панорам%' (может не найти "Панорамный люк")
   
   🚨 КРИТИЧЕСКИ ВАЖНО - GROUP_CONCAT В SQLITE:
   - ❌ ЗАПРЕЩЕНО: GROUP_CONCAT(DISTINCT co.description, ', ') - SQLite НЕ поддерживает DISTINCT с несколькими аргументами!
   - ✅ ПРАВИЛЬНО: GROUP_CONCAT(co.description) - используй без DISTINCT и разделителя
   - ✅ ПРАВИЛЬНО: GROUP_CONCAT(DISTINCT co.description) - только один аргумент для DISTINCT
   - ❌ НЕПРАВИЛЬНО: GROUP_CONCAT(DISTINCT co.description, ', ') AS options
   - ✅ ПРАВИЛЬНО: GROUP_CONCAT(co.description) AS options
   
   🚨 КРИТИЧЕСКИ ВАЖНО - UNION С ОПЦИЯМИ И mileage:
   - ❌ ЗАПРЕЩЕНО: UNION между cars и used_cars с ORDER BY по mileage без правильного алиаса!
   - ✅ ПРАВИЛЬНО: Если используешь UNION между cars (с NULL AS mileage) и used_cars (с c.mileage), 
     в ORDER BY используй алиас mileage (не c.mileage!)
   - ✅ ПРАВИЛЬНО: SELECT ..., c.mileage FROM used_cars ... UNION ALL SELECT ..., NULL AS mileage FROM cars ... ORDER BY mileage ASC
   - ❌ НЕПРАВИЛЬНО: ORDER BY CASE WHEN c.mileage IS NULL ... - используй просто mileage (алиас из SELECT!)

8. АГРЕГАЦИЯ:
   - COUNT(*) - подсчет записей
   - AVG() - среднее значение (используй CAST для цен!)
   - SUM() - сумма
   - MIN(), MAX() - минимум/максимум
   - GROUP BY - группировка
   - ORDER BY - сортировка (DESC для убывания, ASC для возрастания)
   
   ✅ При агрегации по маркам из обеих таблиц:
   ✅ ПРАВИЛЬНО: SELECT mark, AVG(price) FROM (
                     SELECT mark, price FROM cars WHERE price IS NOT NULL
                     UNION ALL
                     SELECT mark, price FROM used_cars WHERE price IS NOT NULL
                  ) GROUP BY mark;
   
   ❌ НЕ используй CTE или псевдонимы для подзапросов, которые SQLite может не поддержать
   ❌ НЕПРАВИЛЬНО: WITH combined AS (...) SELECT ... FROM combined;

═══════════════════════════════════════════════════════════════════════════════
ПРИМЕРЫ КОРРЕКТНЫХ SQL ЗАПРОСОВ:
═══════════════════════════════════════════════════════════════════════════════

-- Поиск марки (регистронезависимый) - ВСЕГДА используй LIKE, не =:
SELECT COUNT(*) FROM cars WHERE UPPER(mark) LIKE '%TOYOTA%';
SELECT COUNT(*) FROM used_cars WHERE UPPER(mark) LIKE '%BMW%';  -- найдет и BMW и bmw

-- Средняя цена (корректно для SQLite):
SELECT AVG(CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL)) AS avg_price
FROM cars WHERE price IS NOT NULL AND price != '';

-- Поиск по городу (регистронезависимый):
SELECT * FROM cars WHERE UPPER(city) LIKE '%РОСТОВ%' OR UPPER(city) LIKE '%МОСКВА%';

-- Автоматическая КПП (с учетом вариантов):
SELECT * FROM cars WHERE UPPER(gear_box_type) LIKE '%АВТОМАТ%' OR gear_box_type = 'автомат';

-- Поиск топлива (регистронезависимый) - ИСПОЛЬЗУЙ LOWER для кириллицы:
SELECT COUNT(*) FROM cars WHERE LOWER(fuel_type) LIKE '%бензин%';
SELECT COUNT(*) FROM used_cars WHERE LOWER(fuel_type) LIKE '%бензин%';
-- ИЛИ с комбинацией:
SELECT COUNT(*) FROM cars WHERE fuel_type = 'бензин' OR fuel_type = 'Бензин';
SELECT COUNT(*) FROM used_cars WHERE fuel_type = 'бензин' OR fuel_type = 'Бензин';

-- Поиск кузова (регистронезависимый) - ИСПОЛЬЗУЙ LOWER для кириллицы:
SELECT * FROM cars WHERE LOWER(body_type) LIKE '%седан%';

-- Объединение таблиц:
SELECT DISTINCT mark FROM cars WHERE mark IS NOT NULL
UNION
SELECT DISTINCT mark FROM used_cars WHERE mark IS NOT NULL;

-- Объединение с сортировкой по цене (ПРАВИЛЬНО - псевдоним в SELECT):
SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
FROM cars WHERE price IS NOT NULL AND price != ''
UNION ALL
SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
FROM used_cars WHERE price IS NOT NULL AND price != ''
ORDER BY price_num ASC;

-- Объединение с фильтром по цене и сортировкой (ПРАВИЛЬНО - псевдоним price_num):
SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
FROM cars WHERE price IS NOT NULL AND price != '' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) < 1000000
UNION ALL
SELECT mark, model, price, CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
FROM used_cars WHERE price IS NOT NULL AND price != '' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) < 1000000
ORDER BY price_num ASC;

-- Объединение с CASE для сортировки (ПРАВИЛЬНО - псевдоним в SELECT):
SELECT mark, model, city, CASE WHEN city IS NULL THEN 1 ELSE 0 END AS city_sort
FROM cars WHERE condition
UNION ALL
SELECT mark, model, city, CASE WHEN city IS NULL THEN 1 ELSE 0 END AS city_sort
FROM used_cars WHERE condition
ORDER BY city_sort ASC, mark ASC;

-- ВАЖНО: Для сортировки по цене с CASE (если нужна сложная логика):
SELECT mark, model, price, city,
       CASE WHEN city IS NULL THEN 1 ELSE 0 END AS city_priority,
       CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
FROM cars WHERE price IS NOT NULL AND price != ''
UNION ALL
SELECT mark, model, price, city,
       CASE WHEN city IS NULL THEN 1 ELSE 0 END AS city_priority,
       CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
FROM used_cars WHERE price IS NOT NULL AND price != ''
ORDER BY city_priority ASC, price_num ASC;

-- Фильтр по цене:
SELECT * FROM cars 
WHERE CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) < 2000000
AND price IS NOT NULL AND price != '';

-- Поиск по опциям (автомобили с ABS):
SELECT DISTINCT c.id, c.mark, c.model, c.price, c.city, c.body_type
FROM cars c
INNER JOIN car_options co ON c.id = co.car_id
WHERE LOWER(co.description) LIKE '%антиблокировочная%' 
OR LOWER(co.description) LIKE '%abs%'
AND c.price IS NOT NULL AND c.price != '';

-- Поиск по опциям (автомобили с круиз-контролем):
SELECT DISTINCT c.id, c.mark, c.model, c.price
FROM cars c
INNER JOIN car_options co ON c.id = co.car_id
WHERE LOWER(co.description) LIKE '%круиз-контроль%'
AND c.price IS NOT NULL AND c.price != '';

-- Поиск по опциям (автомобили с несколькими опциями):
SELECT DISTINCT c.id, c.mark, c.model, c.price
FROM cars c
WHERE c.id IN (SELECT car_id FROM car_options WHERE LOWER(description) LIKE '%кожаный салон%')
AND c.id IN (SELECT car_id FROM car_options WHERE LOWER(description) LIKE '%подогрев сидений%')
AND c.price IS NOT NULL AND c.price != '';

-- ПРАВИЛЬНО ДЛЯ КРУИЗ-КОНТРОЛЯ (БЕЗ mileage):
SELECT DISTINCT c.id, c.mark, c.model, c.price, c.city, c.body_type, c.fuel_type, c.manufacture_year, c.gear_box_type 
FROM cars c 
INNER JOIN car_options co ON c.id = co.car_id 
WHERE (LOWER(co.description) LIKE '%круиз%контроль%' OR LOWER(co.description) LIKE '%круиз-контроль%') 
AND c.price IS NOT NULL AND c.price != '' 
ORDER BY CAST(REPLACE(REPLACE(REPLACE(c.price, ' ', ''), '₽', ''), ',', '.') AS REAL) ASC;

-- ПРАВИЛЬНО ДЛЯ НЕСКОЛЬКИХ ОПЦИЙ (БЕЗ mileage):
SELECT DISTINCT c.id, c.mark, c.model, c.price, c.city, c.body_type, c.fuel_type, c.manufacture_year, c.gear_box_type 
FROM cars c 
INNER JOIN car_options co1 ON c.id = co1.car_id 
INNER JOIN car_options co2 ON c.id = co2.car_id 
WHERE (LOWER(co1.description) LIKE '%кожаный%салон%' OR LOWER(co1.description) LIKE '%кожа%салон%') 
AND (LOWER(co2.description) LIKE '%круиз%контроль%' OR LOWER(co2.description) LIKE '%круиз-контроль%') 
AND c.price IS NOT NULL AND c.price != '' 
ORDER BY CAST(REPLACE(REPLACE(REPLACE(c.price, ' ', ''), '₽', ''), ',', '.') AS REAL) ASC;

═══════════════════════════════════════════════════════════════════════════════
🚨 КРИТИЧЕСКИ ВАЖНЫЕ ИСПРАВЛЕНИЯ ДЛЯ ТЕСТОВ 11 И 13:
═══════════════════════════════════════════════════════════════════════════════

🚫 ЗАПРЕЩЕНО: ORDER BY в отдельных частях UNION до UNION ALL!
✅ РЕШЕНИЕ: Используй подзапросы для ORDER BY + LIMIT в каждой части:

-- ❌ НЕПРАВИЛЬНО ДЛЯ "САМЫЕ ДЕШЕВЫЕ АВТОМОБИЛИ":
SELECT ... ORDER BY ... LIMIT 10 UNION ALL SELECT ... ORDER BY ... LIMIT 10

-- ✅ ПРАВИЛЬНО ДЛЯ "САМЫЕ ДЕШЕВЫЕ АВТОМОБИЛИ" (ТЕСТ 11):
SELECT * FROM (
    SELECT mark, model, price, city, manufacture_year, 
           CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num,
           'new' AS car_type, NULL AS mileage 
    FROM cars 
    WHERE price IS NOT NULL AND price != '' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) > 0 
    ORDER BY price_num ASC 
    LIMIT 10
)
UNION ALL
SELECT * FROM (
    SELECT mark, model, price, city, manufacture_year,
           CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num,
           'used' AS car_type, mileage 
    FROM used_cars 
    WHERE price IS NOT NULL AND price != '' AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) > 0 
    ORDER BY price_num ASC 
    LIMIT 10
)
ORDER BY price_num ASC;

🚫 ЗАПРЕЩЕНО: ORDER BY с вычисляемым полем напрямую в UNION!
✅ РЕШЕНИЕ: Создай псевдоним для вычисляемого поля в SELECT обеих частей:

-- ❌ НЕПРАВИЛЬНО ДЛЯ "АВТОМОБИЛИ ДЕШЕВЛЕ 1000000":
SELECT ... UNION ALL SELECT ... ORDER BY CAST(REPLACE(...) AS REAL)

-- ✅ ПРАВИЛЬНО ДЛЯ "АВТОМОБИЛИ ДЕШЕВЛЕ 1000000" (ТЕСТ 13):
SELECT mark, model, price, manufacture_year, city, 'new' AS car_type, NULL AS mileage,
       CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
FROM cars 
WHERE price IS NOT NULL AND price != '' 
AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) < 1000000
UNION ALL
SELECT mark, model, price, manufacture_year, city, 'used' AS car_type, mileage,
       CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
FROM used_cars 
WHERE price IS NOT NULL AND price != '' 
AND CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) < 1000000
ORDER BY car_type ASC, price_num ASC;

   ═══════════════════════════════════════════════════════════════════════════════
   🚨 КРИТИЧЕСКИ ВАЖНО - ПРОВЕРКА КОЛИЧЕСТВА КОЛОНОК В UNION:
   ═══════════════════════════════════════════════════════════════════════════════
   
   ❌ ОШИБКА: "SELECTs to the left and right of UNION ALL do not have the same number of result columns"
   ✅ РЕШЕНИЕ: ВСЕГДА проверяй, что количество колонок в обеих частях UNION ОДИНАКОВО!
   
   ✅ ПРАВИЛО: Перед отправкой SQL запроса:
   1. Подсчитай количество колонок в первой части SELECT (до UNION ALL)
   2. Подсчитай количество колонок во второй части SELECT (после UNION ALL)
   3. Если количество РАЗНОЕ - добавь NULL AS column_name в часть с меньшим количеством
   4. Убедись, что порядок колонок одинаков (например, если в первой части: mark, model, price, то во второй тоже: mark, model, price)
   
   ✅ ПРАВИЛЬНО - одинаковое количество колонок:
   SELECT mark, model, price, manufacture_year, city, 'new' AS car_type, NULL AS mileage
   FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, manufacture_year, city, 'used' AS car_type, mileage
   FROM used_cars WHERE condition;
   -- Обе части имеют 7 колонок: mark, model, price, manufacture_year, city, car_type, mileage
   
   ❌ НЕПРАВИЛЬНО - разное количество колонок:
   SELECT mark, model, price, manufacture_year, city FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, manufacture_year, city, mileage FROM used_cars WHERE condition;
   -- ОШИБКА: первая часть имеет 5 колонок, вторая - 6!
   
   ✅ ИСПРАВЛЕНО:
   SELECT mark, model, price, manufacture_year, city, NULL AS mileage FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, manufacture_year, city, mileage FROM used_cars WHERE condition;
   -- Теперь обе части имеют 6 колонок
   
   ⚠️ ВАЖНО: Если используешь вычисляемые поля (CAST, CASE WHEN), они тоже считаются как колонки!
   ✅ ПРАВИЛЬНО - с вычисляемыми полями:
   SELECT mark, model, price, CAST(...) AS price_num, 'new' AS car_type, NULL AS mileage
   FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, CAST(...) AS price_num, 'used' AS car_type, mileage
   FROM used_cars WHERE condition;
   -- Обе части имеют 6 колонок: mark, model, price, price_num, car_type, mileage
   
   ═══════════════════════════════════════════════════════════════════════════════
   🚨 КРИТИЧЕСКИ ВАЖНО - CASE WHEN ВЫРАЖЕНИЯ ДОЛЖНЫ БЫТЬ ПОЛНЫМИ:
   ═══════════════════════════════════════════════════════════════════════════════
   
   ❌ ОШИБКА: "near 'AS': syntax error" или "near ',': syntax error"
   ✅ РЕШЕНИЕ: CASE WHEN выражения должны быть ПОЛНЫМИ и ЗАВЕРШЕННЫМИ!
   
   ❌ НЕПРАВИЛЬНО - обрезанное CASE WHEN:
   SELECT mark, model, CASE WHEN cargo_volume LIKE '%л%' THEN CAST(REPLACE(cargo_volume AS cargo_volume_num
   -- ОШИБКА: CASE WHEN не завершен! Нет THEN, нет ELSE, нет END!
   
   ✅ ПРАВИЛЬНО - полное CASE WHEN:
   SELECT mark, model, 
          CASE 
              WHEN cargo_volume LIKE '%л%' THEN CAST(REPLACE(REPLACE(cargo_volume, ' л', ''), ',', '.') AS REAL)
              WHEN cargo_volume LIKE '%L%' THEN CAST(REPLACE(REPLACE(cargo_volume, ' L', ''), ',', '.') AS REAL)
              ELSE CAST(REPLACE(REPLACE(REPLACE(cargo_volume, ' ', ''), ',', '.'), 'л', '') AS REAL)
          END AS cargo_volume_num
   FROM cars WHERE cargo_volume IS NOT NULL;
   
   ✅ ПРАВИЛЬНО - CASE WHEN для сортировки (с псевдонимом):
   SELECT mark, model, price,
          CASE 
              WHEN sale_price IS NOT NULL AND sale_price != '' 
                   AND CAST(REPLACE(REPLACE(REPLACE(sale_price, ' ', ''), '₽', ''), ',', '.') AS REAL) 
                   < CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL)
              THEN ROUND(100.0 - (CAST(REPLACE(REPLACE(REPLACE(sale_price, ' ', ''), '₽', ''), ',', '.') AS REAL) 
                   / CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL)) * 100, 2)
              ELSE 0
          END AS discount_percentage
   FROM cars WHERE condition;
   
   ⚠️ ВАЖНО: Все скобки должны быть закрыты! Все THEN должны иметь значения! Все CASE должны иметь END!
   
   ═══════════════════════════════════════════════════════════════════════════════
   🚨 КРИТИЧЕСКИ ВАЖНО - ОГРАНИЧЕНИЕ ДЛИНЫ SQL ЗАПРОСОВ:
   ═══════════════════════════════════════════════════════════════════════════════
   
   ❌ ОШИБКА: "incomplete input" - SQL запрос слишком длинный или обрезан
   ✅ РЕШЕНИЕ: НЕ создавай запросы с сотнями OR условий! Используй более эффективные подходы!
   
   ❌ НЕПРАВИЛЬНО - слишком много OR условий (сотни):
   WHERE (LOWER(co.description) LIKE '%кожа%' OR LOWER(co.description) LIKE '%кожаный%') 
   OR (LOWER(co.description) LIKE '%мультимедиа%' OR ...) 
   OR (LOWER(co.description) LIKE '%парктроник%' OR ...)
   ... (еще 100+ условий)
   -- ОШИБКА: запрос слишком длинный, может быть обрезан!
   
   ✅ ПРАВИЛЬНО - используй подзапросы или ограничивай количество условий:
   -- Вариант 1: Используй подзапросы для нескольких опций
   SELECT DISTINCT c.id, c.mark, c.model, c.price, c.city, c.body_type, c.fuel_type
   FROM cars c
   WHERE c.id IN (
       SELECT car_id FROM car_options 
       WHERE LOWER(description) LIKE '%кожа%' 
          OR LOWER(description) LIKE '%круиз%'
          OR LOWER(description) LIKE '%парктроник%'
          OR LOWER(description) LIKE '%камера%'
          OR LOWER(description) LIKE '%подогрев%'
   )
   AND c.price IS NOT NULL AND c.price != '';
   
   -- Вариант 2: Ограничь количество условий (максимум 10-15 OR условий)
   SELECT DISTINCT c.id, c.mark, c.model, c.price
   FROM cars c
   INNER JOIN car_options co ON c.id = co.car_id
   WHERE (LOWER(co.description) LIKE '%кожа%' 
       OR LOWER(co.description) LIKE '%круиз%'
       OR LOWER(co.description) LIKE '%парктроник%'
       OR LOWER(co.description) LIKE '%камера%'
       OR LOWER(co.description) LIKE '%подогрев%'
       OR LOWER(co.description) LIKE '%климат%'
       OR LOWER(co.description) LIKE '%ксенон%'
       OR LOWER(co.description) LIKE '%навигаци%'
       OR LOWER(co.description) LIKE '%премиум%'
       OR LOWER(co.description) LIKE '%люкс%')
   AND c.price IS NOT NULL AND c.price != '';
   
   ⚠️ ВАЖНО: Если нужно найти "красивые" или "интересные" автомобили, используй:
   - Ограниченный набор ключевых опций (5-10 самых важных)
   - Или используй подзапросы для группировки условий
   - НЕ создавай запросы с 50+ OR условиями!
   
   ═══════════════════════════════════════════════════════════════════════════════
   🚨 КРИТИЧЕСКИ ВАЖНО - ORDER BY В UNION С НЕСКОЛЬКИМИ ПОЛЯМИ:
   ═══════════════════════════════════════════════════════════════════════════════
   
   ❌ ОШИБКА: "1st ORDER BY term does not match any column" или "2nd ORDER BY term does not match any column"
   ✅ РЕШЕНИЕ: В ORDER BY после UNION можно использовать ТОЛЬКО колонки или псевдонимы, которые есть в SELECT обеих частей!
   
   ❌ НЕПРАВИЛЬНО - ORDER BY с полем, которого нет в SELECT:
   SELECT mark, model, price FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price FROM used_cars WHERE condition
   ORDER BY car_type ASC, price_num ASC;
   -- ОШИБКА: car_type и price_num не определены в SELECT!
   
   ✅ ПРАВИЛЬНО - ORDER BY только с полями из SELECT:
   SELECT mark, model, price, 'new' AS car_type, 
          CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
   FROM cars WHERE condition
   UNION ALL
   SELECT mark, model, price, 'used' AS car_type,
          CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL) AS price_num
   FROM used_cars WHERE condition
   ORDER BY car_type ASC, price_num ASC;
   -- ПРАВИЛЬНО: car_type и price_num определены в SELECT обеих частей!
   
   ⚠️ ВАЖНО: Если используешь ORDER BY с несколькими полями, ВСЕ они должны быть в SELECT обеих частей UNION!
   
   ═══════════════════════════════════════════════════════════════════════════════
   ЗАПОМНИ ЭТИ 4 ПРАВИЛА ДЛЯ 100% УСПЕХА:
   1. ДЛЯ ORDER BY + LIMIT В UNION: используй подзапросы
   2. ДЛЯ ORDER BY ПО ВЫЧИСЛЯЕМОМУ ПОЛЮ В UNION: создай псевдоним в SELECT
   3. ДЛЯ UNION: ВСЕГДА проверяй, что количество колонок одинаково в обеих частях
   4. ДЛЯ CASE WHEN: ВСЕГДА используй полные выражения с THEN, ELSE, END
   ═══════════════════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════════════════
СХЕМА БАЗЫ ДАННЫХ:
═══════════════════════════════════════════════════════════════════════════════
{schema}
═══════════════════════════════════════════════════════════════════════════════

ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}

{'🚨 КРИТИЧЕСКИ ВАЖНО: В запросе упоминаются опции автомобилей! ОБЯЗАТЕЛЬНО используй JOIN с таблицей car_options! НЕ ИЩИ опции в таблице cars!' if any(kw in question.lower() for kw in ['опция', 'abs', 'круиз', 'кожа', 'подогрев', 'парктроник', 'камера', 'bluetooth', 'безопасность', 'комфорт', 'детский замок', 'антиблокировочная', 'иммобилайзер', 'климат-контроль', 'парковка', 'панорам', 'люк', 'sunroof', 'panoramic']) else ''}
{'🚨🚨🚨 КРИТИЧЕСКИ ВАЖНО: В запросе упоминается клиренс! Клиренс (дорожный просвет) ОТСУТСТВУЕТ в базе данных! НЕ ГЕНЕРИРУЙ SQL ЗАПРОС! НЕ используй поле dimensions - dimensions содержит ГАБАРИТЫ (длина*ширина*высота), а не клиренс! Высота автомобиля (140-200 см) НЕ равна клиренсу (15-25 см)! ВЕРНИ ТОЛЬКО: SELECT NULL WHERE 1=0; -- Клиренс отсутствует в базе данных' if any(kw in question.lower() for kw in ['клиренс', 'дорожный просвет']) else ''}

Сгенерируй ТОЛЬКО SQL запрос (без объяснений, без markdown, без дополнительного текста):
SQL запрос:"""

            # Генерируем SQL через LLM с обработкой rate limits
            max_retries = 3
            last_exception = None
            sql_response = None
            
            for attempt in range(max_retries):
                try:
                    if use_ai_settings:
                        ai_settings = self._load_ai_settings()
                        response_model = ai_settings.get("response_model", "")
                        
                        if response_model.startswith("ollama:"):
                            model_name = response_model.replace("ollama:", "")
                            sql_response = await self._generate_with_ollama(model_name, prompt)
                        elif response_model.startswith("mistral:"):
                            model_name = response_model.replace("mistral:", "")
                            api_key = ai_settings.get("api_key", settings.mistral_api_key)
                            sql_response = await self._generate_with_mistral(model_name, api_key, prompt)
                        elif response_model.startswith("openai:"):
                            model_name = response_model.replace("openai:", "")
                            api_key = ai_settings.get("api_key", "")
                            sql_response = await self._generate_with_openai(model_name, api_key, prompt)
                        elif response_model.startswith("anthropic:"):
                            model_name = response_model.replace("anthropic:", "")
                            api_key = ai_settings.get("api_key", "")
                            sql_response = await self._generate_with_anthropic(model_name, api_key, prompt)
                        else:
                            # Фолбэк на Mistral
                            api_key = settings.mistral_api_key
                            sql_response = await self._generate_with_mistral(settings.mistral_model, api_key, prompt)
                    else:
                        # Используем настройки по умолчанию
                        api_key = settings.mistral_api_key
                        sql_response = await self._generate_with_mistral(settings.mistral_model, api_key, prompt)
                    
                    # Если успешно, сбрасываем задержку
                    self.retry_delay = 1
                    break
                    
                except Exception as e:
                    last_exception = e
                    error_str = str(e)
                    
                    # Rate limit теперь обрабатывается внутри _generate_with_mistral
                    # Здесь обрабатываем только другие ошибки
                    if attempt < max_retries - 1:
                        wait_time = self.retry_delay * (2 ** attempt)  # Экспоненциальная задержка
                        print(f"⚠️ Ошибка генерации SQL при попытке {attempt + 1}/{max_retries}: {str(e)[:100]}")
                        await asyncio.sleep(wait_time)
                        self.retry_delay *= 2
                        continue
                    else:
                        # Другие ошибки не требуют retry
                        raise e
            
            if last_exception and not sql_response:
                raise last_exception
            
            # Извлекаем SQL из ответа (убираем markdown код блоки если есть)
            sql_query = self._extract_sql_from_response(sql_response)
            
            # Валидируем SQL
            is_valid, error_message = self.validate_sql_query(sql_query)
            
            if not is_valid:
                return {
                    "success": False,
                    "error": f"Сгенерированный SQL не прошел валидацию: {error_message}",
                    "sql": sql_query,
                    "raw_response": sql_response
                }
            
            return {
                "success": True,
                "sql": sql_query,
                "raw_response": sql_response
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Ошибка генерации SQL: {str(e)}",
                "sql": None
            }
    
    def _extract_sql_from_response(self, response: str) -> str:
        """Извлекает SQL запрос из ответа LLM"""
        # Убираем markdown код блоки
        sql = re.sub(r'```sql\s*\n?', '', response, flags=re.IGNORECASE)
        sql = re.sub(r'```\s*\n?', '', sql)
        
        # Ищем SQL запрос (от SELECT до ;)
        match = re.search(r'SELECT.*?;', sql, re.DOTALL | re.IGNORECASE)
        if match:
            sql = match.group(0)
        
        # Очищаем от лишних пробелов и переносов
        sql = sql.strip()
        
        # Убираем лишние пробелы
        sql = re.sub(r'\s+', ' ', sql)
        
        return sql
    
    def _fix_union_order_by_errors(self, sql: str) -> str:
        """
        Автоматически исправляет ошибки ORDER BY в UNION запросах
        """
        sql_upper = sql.upper()
        original_sql = sql
        
        # Исправление 0: ORDER BY с полями, которых нет в результатах UNION
        # Если ORDER BY использует поля с префиксом таблицы (c.city, uc.city), но в SELECT их нет
        if 'UNION ALL' in sql_upper and 'ORDER BY' in sql_upper:
            order_by_match = re.search(r'ORDER BY\s+(.+?)(?:\s+ASC|\s+DESC)?\s*$', sql, re.IGNORECASE)
            if order_by_match:
                order_expr = order_by_match.group(1).strip()
                
                # Исправление 0.1: CASE WHEN с префиксами таблиц в ORDER BY
                # Если ORDER BY содержит CASE WHEN c.field или CASE WHEN uc.field
                if 'CASE WHEN' in order_expr.upper() and re.search(r'\b(c|uc)\.\w+', order_expr, re.IGNORECASE):
                    # Извлекаем все поля с префиксами
                    fields_with_prefix = re.findall(r'\b(c|uc)\.(\w+)', order_expr, re.IGNORECASE)
                    union_parts = sql.split('UNION ALL')
                    if len(union_parts) == 2:
                        first_part = union_parts[0].strip()
                        second_part = union_parts[1].strip()
                        first_select = first_part.upper()
                        second_select = second_part.upper()
                        
                        # Заменяем все префиксы на просто имена полей, если они есть в SELECT
                        fixed_order = order_expr
                        for prefix, field_name in fields_with_prefix:
                            # Проверяем, есть ли поле в SELECT обеих частей (как простое имя или в выражении)
                            # Ищем поле в SELECT списке (до FROM)
                            first_select_match = re.search(r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM', first_part, re.IGNORECASE | re.DOTALL)
                            second_select_match = re.search(r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM', second_part, re.IGNORECASE | re.DOTALL)
                            
                            if first_select_match and second_select_match:
                                first_select_list = first_select_match.group(1).upper()
                                second_select_list = second_select_match.group(1).upper()
                                
                                # Проверяем, есть ли поле (без префикса) в SELECT обеих частей
                                if field_name.upper() in first_select_list and field_name.upper() in second_select_list:
                                    # Заменяем c.field_name или uc.field_name на просто field_name
                                    fixed_order = re.sub(r'\b' + re.escape(prefix) + r'\.' + re.escape(field_name) + r'\b', field_name, fixed_order, flags=re.IGNORECASE)
                        
                        if fixed_order != order_expr:
                            # Заменяем ORDER BY в SQL
                            sql = re.sub(
                                r'ORDER BY\s+' + re.escape(order_expr) + r'(?:\s+ASC|\s+DESC)?\s*$',
                                f'ORDER BY {fixed_order}',
                                sql,
                                flags=re.IGNORECASE
                            )
                            return sql
                
                # Исправление 0.2: Простые поля с префиксами
                if re.search(r'\b(c|uc)\.\w+', order_expr, re.IGNORECASE):
                    # Извлекаем имя поля без префикса
                    field_match = re.search(r'\.(\w+)', order_expr)
                    if field_match:
                        field_name = field_match.group(1)
                        # Проверяем, есть ли это поле в SELECT обеих частей UNION
                        union_parts = sql.split('UNION ALL')
                        if len(union_parts) == 2:
                            first_select = union_parts[0].upper()
                            second_select = union_parts[1].upper()
                            # Если поле есть в SELECT, заменяем префикс на просто имя поля
                            if field_name.upper() in first_select and field_name.upper() in second_select:
                                # Заменяем c.field_name или uc.field_name на просто field_name
                                fixed_order = re.sub(r'\b(c|uc)\.' + field_name + r'\b', field_name, order_expr, flags=re.IGNORECASE)
                                sql = sql.replace(order_expr, fixed_order)
                                return sql
        
        # Исправление 1: ORDER BY + LIMIT в отдельных частях UNION
        if 'UNION ALL' in sql_upper and 'ORDER BY' in sql_upper and 'LIMIT' in sql_upper:
            union_parts = sql.split('UNION ALL')
            if len(union_parts) == 2:
                first_part = union_parts[0].strip()
                second_part = union_parts[1].strip()
                
                # Проверяем, есть ли ORDER BY + LIMIT в обеих частях до UNION ALL
                first_has_order_limit = 'ORDER BY' in first_part.upper() and 'LIMIT' in first_part.upper()
                second_has_order_limit = 'ORDER BY' in second_part.upper() and 'LIMIT' in second_part.upper()
                
                # НЕ исправляем, если уже есть подзапросы (SELECT * FROM уже есть)
                # Проверяем более точно - есть ли уже обертка SELECT * FROM (SELECT ...)
                first_has_subquery = re.search(r'SELECT\s+\*\s+FROM\s*\(', first_part, re.IGNORECASE)
                second_has_subquery = re.search(r'SELECT\s+\*\s+FROM\s*\(', second_part, re.IGNORECASE)
                
                # Также проверяем, что ORDER BY и LIMIT идут последовательно в конце (не внутри подзапроса)
                first_has_direct_order = re.search(r'ORDER BY.*LIMIT\s+\d+\s*$', first_part, re.IGNORECASE)
                second_has_direct_order = re.search(r'ORDER BY.*LIMIT\s+\d+\s*$', second_part, re.IGNORECASE)
                
                if first_has_order_limit and second_has_order_limit and not first_has_subquery and not second_has_subquery and first_has_direct_order and second_has_direct_order:
                    # Извлекаем ORDER BY и LIMIT из обеих частей
                    # Ищем ORDER BY ... LIMIT в конце каждой части
                    first_order_match = re.search(r'(.+?)\s+ORDER BY\s+(.+?)\s+LIMIT\s+(\d+)\s*$', first_part, re.IGNORECASE | re.DOTALL)
                    second_order_match = re.search(r'(.+?)\s+ORDER BY\s+(.+?)\s+LIMIT\s+(\d+)\s*$', second_part, re.IGNORECASE | re.DOTALL)
                    
                    if first_order_match and second_order_match:
                        first_main = first_order_match.group(1).strip()
                        first_order_by = first_order_match.group(2).strip()
                        first_limit = first_order_match.group(3).strip()
                        second_main = second_order_match.group(1).strip()
                        second_order_by = second_order_match.group(2).strip()
                        second_limit = second_order_match.group(3).strip()
                        
                        # Создаем новый SQL с подзапросами
                        fixed_sql = f"SELECT * FROM ({first_main} ORDER BY {first_order_by} LIMIT {first_limit}) UNION ALL SELECT * FROM ({second_main} ORDER BY {second_order_by} LIMIT {second_limit})"
                        
                        # Добавляем общий ORDER BY если он есть в конце (и он не повторяется)
                        last_part_upper = sql_upper.split('UNION ALL')[-1]
                        if 'ORDER BY' in last_part_upper and 'LIMIT' not in last_part_upper.split('ORDER BY')[0]:
                            order_match = re.search(r'ORDER BY\s+(.+?)(?:\s+ASC|\s+DESC)?\s*$', sql, re.IGNORECASE)
                            if order_match:
                                order_expr = order_match.group(1).strip()
                                # Добавляем ORDER BY только если его нет в подзапросах
                                if order_expr.upper() not in first_order_by.upper() and order_expr.upper() not in second_order_by.upper():
                                    fixed_sql += f" ORDER BY {order_expr}"
                        
                        return fixed_sql
        
        # Исправление 2: ORDER BY с вычисляемым полем в UNION (без псевдонима в SELECT)
        if 'UNION ALL' in sql_upper and 'ORDER BY' in sql_upper:
            union_parts = sql.split('UNION ALL')
            if len(union_parts) == 2:
                first_part = union_parts[0].strip()
                second_part = union_parts[1].strip()
                
                # Исправление 2.1: ORDER BY перед UNION ALL (недопустимо в SQLite)
                # Проверяем, есть ли ORDER BY в первой части (до UNION ALL)
                # Также проверяем, есть ли ORDER BY во второй части до UNION ALL
                first_has_order = 'ORDER BY' in first_part.upper() and 'UNION ALL' not in first_part.upper()
                second_has_order_before_union = 'ORDER BY' in second_part.upper().split('UNION ALL')[0] if 'UNION ALL' in second_part.upper() else False
                
                if first_has_order or second_has_order_before_union:
                    # Извлекаем ORDER BY и LIMIT из первой части
                    if first_has_order:
                        order_limit_match = re.search(r'(.+?)\s+ORDER BY\s+(.+?)(?:\s+LIMIT\s+\d+)?\s*$', first_part, re.IGNORECASE | re.DOTALL)
                        if order_limit_match:
                            first_main = order_limit_match.group(1).strip()
                            first_order = order_limit_match.group(2).strip()
                            first_limit = ""
                            limit_match = re.search(r'LIMIT\s+(\d+)', first_part, re.IGNORECASE)
                            if limit_match:
                                first_limit = f" LIMIT {limit_match.group(1)}"
                            # Убираем ORDER BY и LIMIT из первой части
                            first_part = first_main
                            
                            # Извлекаем ORDER BY и LIMIT из второй части, если есть
                            second_main = second_part
                            second_order = ""
                            second_limit = ""
                            if 'ORDER BY' in second_part.upper():
                                second_order_limit_match = re.search(r'(.+?)\s+ORDER BY\s+(.+?)(?:\s+LIMIT\s+\d+)?\s*$', second_part, re.IGNORECASE | re.DOTALL)
                                if second_order_limit_match:
                                    second_main = second_order_limit_match.group(1).strip()
                                    second_order = second_order_limit_match.group(2).strip()
                                    second_limit_match = re.search(r'LIMIT\s+(\d+)', second_part, re.IGNORECASE)
                                    if second_limit_match:
                                        second_limit = f" LIMIT {second_limit_match.group(1)}"
                            
                            # Добавляем ORDER BY в конец всего запроса
                            fixed_sql = f"{first_part} UNION ALL {second_main}"
                            # Используем ORDER BY из первой части, если он есть, иначе из второй
                            final_order = first_order if first_order else second_order
                            if final_order:
                                fixed_sql += f" ORDER BY {final_order}"
                            # Добавляем LIMIT если был
                            if first_limit:
                                fixed_sql += first_limit
                            elif second_limit:
                                fixed_sql += second_limit
                            return fixed_sql
                
                # Исправление 2.2: ORDER BY с вычисляемыми полями (CAST, REPLACE, CASE WHEN)
                # Ищем ORDER BY в конце (только если не было исправления выше)
                order_by_match = re.search(r'ORDER BY\s+(.+?)(?:\s+ASC|\s+DESC)?(?:\s+LIMIT\s+\d+)?\s*$', sql, re.IGNORECASE)
                if order_by_match:
                    order_expr = order_by_match.group(1).strip()
                    # Разбиваем ORDER BY на части (могут быть несколько полей через запятую)
                    # Учитываем, что запятые могут быть внутри выражений
                    order_parts = []
                    current_part = ""
                    paren_depth = 0
                    for char in order_expr:
                        if char == '(':
                            paren_depth += 1
                            current_part += char
                        elif char == ')':
                            paren_depth -= 1
                            current_part += char
                        elif char == ',' and paren_depth == 0:
                            if current_part.strip():
                                order_parts.append(current_part.strip())
                            current_part = ""
                        else:
                            current_part += char
                    if current_part.strip():
                        order_parts.append(current_part.strip())
                    
                    # Определяем first_select и second_select заранее для использования во всех блоках
                    first_select = union_parts[0].upper()
                    second_select = union_parts[1].upper()
                    
                    # Проверяем каждую часть ORDER BY
                    for order_part in order_parts:
                        # Если в ORDER BY есть CAST, REPLACE, CASE - это вычисляемое поле
                        if any(op in order_part.upper() for op in ['CAST', 'REPLACE']) and 'AS' not in order_part.upper():
                            
                            # Извлекаем имя поля из CAST/REPLACE выражения для создания псевдонима
                            # Ищем поле типа CAST(REPLACE(power, ' ', '') AS REAL)
                            field_match = re.search(r'CAST.*?\(([^,]+?)\)', order_part, re.IGNORECASE)
                            if field_match:
                                field_expr = field_match.group(1).strip()
                                # Создаем псевдоним на основе имени поля
                                if 'power' in field_expr.lower():
                                    alias_name = "power_num"
                                elif 'price' in field_expr.lower():
                                    alias_name = "price_num"
                                else:
                                    alias_name = "order_field"
                                
                                # Проверяем, есть ли уже этот псевдоним в SELECT
                                if alias_name.upper() not in first_select or alias_name.upper() not in second_select:
                                    # Находим позицию после SELECT в первой части
                                    first_part = union_parts[0].strip()
                                    select_match = re.search(r'(SELECT\s+(?:DISTINCT\s+)?)(.*?)(\s+FROM)', first_part, re.IGNORECASE | re.DOTALL)
                                    if select_match:
                                        select_cols = select_match.group(2).strip()
                                        # Добавляем вычисляемое поле с псевдонимом если его еще нет
                                        if f'AS {alias_name}' not in select_cols.upper():
                                            # Добавляем запятую если нужно
                                            if not select_cols.endswith(',') and select_cols:
                                                select_cols += ', '
                                            first_part = first_part.replace(
                                                select_match.group(0),
                                                f"{select_match.group(1)}{select_cols}{order_part} AS {alias_name} {select_match.group(3)}"
                                            )
                                    
                                    # То же самое для второй части
                                    second_part = union_parts[1].strip()
                                    select_match = re.search(r'(SELECT\s+(?:DISTINCT\s+)?)(.*?)(\s+FROM)', second_part, re.IGNORECASE | re.DOTALL)
                                    if select_match:
                                        select_cols = select_match.group(2).strip()
                                        if f'AS {alias_name}' not in select_cols.upper():
                                            # Добавляем запятую если нужно
                                            if not select_cols.endswith(',') and select_cols:
                                                select_cols += ', '
                                            second_part = second_part.replace(
                                                select_match.group(0),
                                                f"{select_match.group(1)}{select_cols}{order_part} AS {alias_name} {select_match.group(3)}"
                                            )
                                    
                                    # Заменяем ORDER BY на использование псевдонима
                                    fixed_sql = f"{first_part} UNION ALL {second_part}"
                                    # Заменяем только эту часть ORDER BY на псевдоним
                                    fixed_order = order_expr.replace(order_part, alias_name)
                                    fixed_sql = re.sub(r'ORDER BY\s+.+?(?:\s+ASC|\s+DESC)?\s*$', f'ORDER BY {fixed_order}', fixed_sql, flags=re.IGNORECASE)
                                    
                                    return fixed_sql
                            break  # Обработали первую часть с CAST, выходим
                        
                        # Исправление 2.3: ORDER BY с CASE WHEN выражениями
                        # Если ORDER BY содержит CASE WHEN, нужно добавить псевдоним в SELECT
                        if 'CASE WHEN' in order_part.upper() or ('CASE' in order_part.upper() and 'WHEN' in order_part.upper()):
                            # Создаем псевдоним для CASE WHEN выражения
                            if 'cargo_volume' in order_part.lower():
                                alias_name = "cargo_volume_num"
                            elif 'id' in order_part.lower():
                                alias_name = "id_order"
                            else:
                                alias_name = "order_field"
                            
                            # Проверяем, есть ли уже этот псевдоним в SELECT
                            # first_select и second_select уже определены выше
                            if alias_name.upper() not in first_select or alias_name.upper() not in second_select:
                                # Находим позицию после SELECT в первой части
                                first_part = union_parts[0].strip()
                                # Ищем конец SELECT списка (до FROM, но после всех колонок)
                                # Нужно найти последнюю запятую или конец списка колонок
                                select_match = re.search(r'(SELECT\s+(?:DISTINCT\s+)?)(.*?)(\s+FROM)', first_part, re.IGNORECASE | re.DOTALL)
                                if select_match:
                                    select_cols = select_match.group(2).strip()
                                    # Проверяем, что CASE WHEN выражение еще не добавлено
                                    if f'AS {alias_name}' not in select_cols.upper():
                                        # Добавляем запятую если нужно
                                        if not select_cols.endswith(',') and select_cols:
                                            select_cols += ', '
                                        # Добавляем полное CASE WHEN выражение с псевдонимом
                                        first_part = first_part.replace(
                                            select_match.group(0),
                                            f"{select_match.group(1)}{select_cols}{order_part} AS {alias_name} {select_match.group(3)}"
                                        )
                                
                                # То же самое для второй части
                                second_part = union_parts[1].strip()
                                select_match = re.search(r'(SELECT\s+(?:DISTINCT\s+)?)(.*?)(\s+FROM)', second_part, re.IGNORECASE | re.DOTALL)
                                if select_match:
                                    select_cols = select_match.group(2).strip()
                                    if f'AS {alias_name}' not in select_cols.upper():
                                        # Добавляем запятую если нужно
                                        if not select_cols.endswith(',') and select_cols:
                                            select_cols += ', '
                                        second_part = second_part.replace(
                                            select_match.group(0),
                                            f"{select_match.group(1)}{select_cols}{order_part} AS {alias_name} {select_match.group(3)}"
                                        )
                                
                                # Заменяем ORDER BY на использование псевдонима
                                fixed_sql = f"{first_part} UNION ALL {second_part}"
                                # Заменяем только эту часть ORDER BY на псевдоним
                                fixed_order = order_expr.replace(order_part, alias_name)
                                fixed_sql = re.sub(r'ORDER BY\s+.+?(?:\s+ASC|\s+DESC)?\s*$', f'ORDER BY {fixed_order}', fixed_sql, flags=re.IGNORECASE)
                                
                                return fixed_sql
                            break  # Обработали CASE WHEN, выходим
                        
                        # Исправление 2.4: ORDER BY с псевдонимом, который используется до определения
                        # Например: ORDER BY original_price, но original_price определен как AS original_price в SELECT
                        # Проверяем, есть ли в ORDER BY имя, которое выглядит как псевдоним, но не определено в SELECT
                        if re.match(r'^[a-z_]+$', order_part, re.IGNORECASE) and order_part.upper() not in first_select and order_part.upper() not in second_select:
                            # Это может быть псевдоним, который используется до определения
                            # Ищем, где он определен в SELECT
                            alias_pattern = rf'\b{re.escape(order_part)}\s+AS\s+(\w+)'
                            alias_match = re.search(alias_pattern, sql, re.IGNORECASE)
                            if alias_match:
                                # Псевдоним определен, но в ORDER BY используется неправильное имя
                                # Заменяем на правильное имя колонки или псевдоним
                                # Пока просто пропускаем, так как это сложная логика
                                pass
        
        return original_sql
    
    def _fix_options_sql_errors(self, sql: str) -> str:
        """
        Автоматически исправляет ошибки в SQL запросах для опций
        """
        original_sql = sql
        sql_upper = sql.upper()
        
        # Исправление 1: Удаление mileage из SELECT для cars (более агрессивное исправление)
        if 'FROM cars' in sql_upper or 'FROM cars c' in sql_upper:
            # Убираем c.mileage из SELECT (все варианты)
            sql = re.sub(r'c\.mileage\s*,?\s*', '', sql, flags=re.IGNORECASE)
            sql = re.sub(r',\s*c\.mileage\s*', '', sql, flags=re.IGNORECASE)
            sql = re.sub(r',\s*mileage\s*,?', ',', sql, flags=re.IGNORECASE)
            sql = re.sub(r',\s*mileage\s*', '', sql, flags=re.IGNORECASE)
            # Исправляем SELECT ..., c.mileage в конце и в середине
            sql = re.sub(r'SELECT\s+(.*?),\s*c\.mileage(\s|,|$)', r'SELECT \1\2', sql, flags=re.IGNORECASE | re.DOTALL)
            sql = re.sub(r'SELECT\s+(.*?),\s*mileage(\s|,|$)', r'SELECT \1\2', sql, flags=re.IGNORECASE | re.DOTALL)
            # Исправляем если mileage стоит в середине списка
            sql = re.sub(r',\s*c\.mileage\s*,', ',', sql, flags=re.IGNORECASE)
            sql = re.sub(r',\s*mileage\s*,', ',', sql, flags=re.IGNORECASE)
        
        # Исправление 2: Удаление ORDER BY с mileage для cars
        if ('FROM cars' in sql_upper or 'FROM cars c' in sql_upper) and 'ORDER BY' in sql_upper and 'mileage' in sql_upper:
            # Заменяем ORDER BY с mileage на ORDER BY price
            sql = re.sub(r'ORDER BY\s+.*?mileage.*?(,|\s+ASC|\s+DESC|$)', 'ORDER BY c.price ASC', sql, flags=re.IGNORECASE)
            sql = re.sub(r'ORDER BY\s+.*?c\.mileage.*?(,|\s+ASC|\s+DESC|$)', 'ORDER BY c.price ASC', sql, flags=re.IGNORECASE)
        
        # Исправление 3: Улучшение шаблонов поиска для подогрева
        if 'подогрев' in sql.lower() or 'обогрев' in sql.lower():
            # Убедимся, что используется оба варианта
            if 'подогрев' in sql.lower() and 'обогрев' not in sql.lower():
                sql = re.sub(
                    r"LOWER\(co\.description\) LIKE '%подогрев%'",
                    "LOWER(co.description) LIKE '%подогрев%' OR LOWER(co.description) LIKE '%обогрев%'",
                    sql,
                    flags=re.IGNORECASE
                )
        
        # Исправление 4: Улучшение поиска камеры
        if 'камера' in sql.lower() and 'вида' not in sql.lower():
            if 'LOWER(co.description) LIKE' in sql and 'камера' in sql:
                sql = re.sub(
                    r"LOWER\(co\.description\) LIKE '%камера%'",
                    "LOWER(co.description) LIKE '%камера%' OR LOWER(co.description) LIKE '%вида%'",
                    sql,
                    flags=re.IGNORECASE
                )
        
        # Исправление 5: Исправление GROUP_CONCAT(DISTINCT ...) для SQLite
        # SQLite требует один аргумент для DISTINCT в GROUP_CONCAT
        if 'GROUP_CONCAT(DISTINCT' in sql_upper:
            # Заменяем GROUP_CONCAT(DISTINCT co.description, ', ') на GROUP_CONCAT(DISTINCT co.description || ', ')
            sql = re.sub(
                r"GROUP_CONCAT\(DISTINCT\s+([^,]+),\s*'([^']+)'\)",
                r"GROUP_CONCAT(DISTINCT \1)",
                sql,
                flags=re.IGNORECASE
            )
            # Или заменяем на просто GROUP_CONCAT без DISTINCT и конкатенируем вручную
            sql = re.sub(
                r"GROUP_CONCAT\(DISTINCT\s+co\.description\s*,\s*'[^']+'\)",
                r"GROUP_CONCAT(co.description)",
                sql,
                flags=re.IGNORECASE
            )
        
        # Исправление 6: Исправление ORDER BY в UNION с mileage
        # Если в ORDER BY используется CASE WHEN mileage с c.mileage, нужно заменить на алиас mileage
        if 'UNION ALL' in sql_upper and 'ORDER BY' in sql_upper and 'mileage' in sql_upper:
            # Проверяем, есть ли mileage в SELECT обеих частей UNION
            union_parts = sql.split('UNION ALL')
            if len(union_parts) == 2:
                first_part = union_parts[0].upper()
                second_part = union_parts[1].upper()
                order_by_part = sql.split('ORDER BY')[-1] if 'ORDER BY' in sql else ''
                
                # Если в ORDER BY используется c.mileage, но в SELECT есть mileage (алиас) - заменяем на mileage
                if 'c.mileage' in order_by_part and ('NULL AS mileage' in second_part or 'mileage' in first_part or 'mileage AS' in first_part):
                    # Заменяем все c.mileage в ORDER BY на просто mileage (алиас)
                    sql = re.sub(
                        r'c\.mileage',
                        'mileage',
                        sql,
                        flags=re.IGNORECASE
                    )
                
                # Если в ORDER BY есть CASE WHEN mileage, но mileage не имеет алиаса в SELECT
                if 'CASE WHEN mileage' in order_by_part.upper() or 'CASE WHEN c.mileage' in order_by_part.upper():
                    # Проверяем, есть ли mileage как алиас во второй части (NULL AS mileage)
                    if 'NULL AS mileage' in second_part or 'mileage' in sql_upper:
                        # Заменяем ORDER BY на использование алиаса mileage (убираем c.)
                        sql = re.sub(
                            r'ORDER BY\s+CASE\s+WHEN\s+c\.mileage\s+IS\s+NULL',
                            'ORDER BY CASE WHEN mileage IS NULL',
                            sql,
                            flags=re.IGNORECASE | re.DOTALL
                        )
                        sql = re.sub(
                            r'CASE\s+WHEN\s+c\.mileage\s+IS\s+NULL\s+THEN\s+\d+\s+ELSE\s+\d+\s+END',
                            'CASE WHEN mileage IS NULL THEN 0 ELSE 1 END',
                            sql,
                            flags=re.IGNORECASE | re.DOTALL
                        )
        
        if sql != original_sql:
            return sql
        
        return original_sql

    def _fix_union_column_count(self, sql: str) -> str:
        """
        Исправляет ошибки разного количества колонок в UNION ALL
        """
        if 'UNION ALL' not in sql.upper():
            return sql
        
        union_parts = sql.split('UNION ALL')
        if len(union_parts) != 2:
            return sql
        
        first_part = union_parts[0].strip()
        second_part = union_parts[1].strip()
        
        # Извлекаем SELECT части (учитываем DISTINCT)
        first_select_match = re.search(r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM', first_part, re.IGNORECASE | re.DOTALL)
        second_select_match = re.search(r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM', second_part, re.IGNORECASE | re.DOTALL)
        
        if not first_select_match or not second_select_match:
            return sql
        
        # Умное разбиение колонок с учетом вложенных выражений
        def split_columns(select_str):
            """Разбивает колонки, учитывая вложенные SELECT, функции, скобки"""
            cols = []
            current_col = ""
            paren_depth = 0
            for char in select_str:
                if char == '(':
                    paren_depth += 1
                    current_col += char
                elif char == ')':
                    paren_depth -= 1
                    current_col += char
                elif char == ',' and paren_depth == 0:
                    if current_col.strip():
                        cols.append(current_col.strip())
                    current_col = ""
                else:
                    current_col += char
            if current_col.strip():
                cols.append(current_col.strip())
            return cols
        
        first_cols = split_columns(first_select_match.group(1))
        second_cols = split_columns(second_select_match.group(1))
        
        # Если количество колонок разное
        if len(first_cols) != len(second_cols):
            # Проверяем, есть ли mileage только в одной части
            first_has_mileage = any('mileage' in col.upper() and 'NULL' not in col.upper() for col in first_cols)
            second_has_mileage = any('mileage' in col.upper() and 'NULL' not in col.upper() for col in second_cols)
            
            # Также проверяем другие возможные различия в колонках
            # Сравниваем количество колонок и находим, какая часть имеет больше
            if len(first_cols) < len(second_cols):
                # Первая часть имеет меньше колонок - добавляем недостающие
                if second_has_mileage and not first_has_mileage:
                    first_cols.append('NULL AS mileage')
                # Если все еще разное количество, добавляем NULL для выравнивания
                while len(first_cols) < len(second_cols):
                    first_cols.append('NULL AS extra_col')
            elif len(second_cols) < len(first_cols):
                # Вторая часть имеет меньше колонок - добавляем недостающие
                if first_has_mileage and not second_has_mileage:
                    second_cols.append('NULL AS mileage')
                # Если все еще разное количество, добавляем NULL для выравнивания
                while len(second_cols) < len(first_cols):
                    second_cols.append('NULL AS extra_col')
            
            # Обновляем SQL с выровненными колонками
            if len(first_cols) != len(second_cols):
                # Если все еще разное, просто добавляем mileage где нужно
                if second_has_mileage and not first_has_mileage:
                    first_cols.append('NULL AS mileage')
                elif first_has_mileage and not second_has_mileage:
                    second_cols.append('NULL AS mileage')
            
            # Пересобираем SELECT части
            first_select_str = ', '.join(first_cols)
            second_select_str = ', '.join(second_cols)
            
            # Сохраняем DISTINCT если был
            if 'DISTINCT' in first_part.upper()[:20]:
                first_part = re.sub(
                    r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM',
                    f'SELECT DISTINCT {first_select_str} FROM',
                    first_part,
                    count=1,
                    flags=re.IGNORECASE | re.DOTALL
                )
            else:
                first_part = first_part.replace(first_select_match.group(0), f"SELECT {first_select_str} FROM")
            
            if 'DISTINCT' in second_part.upper()[:20]:
                second_part = re.sub(
                    r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM',
                    f'SELECT DISTINCT {second_select_str} FROM',
                    second_part,
                    count=1,
                    flags=re.IGNORECASE | re.DOTALL
                )
            else:
                second_part = second_part.replace(second_select_match.group(0), f"SELECT {second_select_str} FROM")
            
            # Пересобираем SQL
            fixed_sql = f"{first_part} UNION ALL {second_part}"
            return fixed_sql
        
        return sql
    
    async def execute_sql_query(self, sql_query: str, auto_fix: bool = True) -> Dict[str, Any]:
        """
        Безопасное выполнение SQL запроса с автоматическим исправлением UNION ошибок
        """
        original_sql = sql_query
        max_fix_attempts = 3
        fix_attempt = 0
        
        while fix_attempt < max_fix_attempts:
            fix_attempt += 1
            current_sql = sql_query
            
            # Автоматическое исправление опций перед другими исправлениями
            if auto_fix and ('car_options' in sql_query.upper() or any(kw in sql_query.lower() for kw in ['опция', 'abs', 'круиз', 'кожа', 'подогрев', 'парктроник', 'камера', 'bluetooth'])):
                sql_query = self._fix_options_sql_errors(sql_query)
            
            # Исправление разного количества колонок в UNION (критически важно!)
            if auto_fix and 'UNION ALL' in sql_query.upper():
                sql_query = self._fix_union_column_count(sql_query)
            
            # Автоматическое исправление UNION проблем перед выполнением
            # Не исправляем если уже есть подзапросы (чтобы избежать двойного оборачивания)
            if auto_fix and 'UNION' in sql_query.upper() and 'SELECT * FROM (' not in sql_query.upper():
                fixed_sql = self._fix_union_order_by_errors(sql_query)
                # Используем исправленный SQL только если он отличается и не содержит ошибок вложенности
                if fixed_sql != sql_query and fixed_sql.count('SELECT * FROM (') <= 2:
                    sql_query = fixed_sql
            
            # Дополнительное исправление: использование псевдонимов в ORDER BY до их определения
            if auto_fix and 'UNION ALL' in sql_query.upper() and 'ORDER BY' in sql_query.upper():
                # Ищем случаи, когда в ORDER BY используется псевдоним, который определен в SELECT
                # но используется в ORDER BY до UNION ALL
                order_by_match = re.search(r'ORDER BY\s+(.+?)(?:\s+ASC|\s+DESC)?\s*$', sql_query, re.IGNORECASE)
                if order_by_match:
                    order_expr = order_by_match.group(1).strip()
                    # Проверяем, есть ли в ORDER BY псевдонимы, которые не определены в результатах UNION
                    order_fields = [f.strip() for f in order_expr.split(',')]
                    for field in order_fields:
                        # Если это просто имя без точек и скобок, может быть псевдоним
                        if re.match(r'^[a-z_]+$', field, re.IGNORECASE):
                            # Проверяем, определен ли этот псевдоним в SELECT
                            if f'AS {field}' not in sql_query.upper() and f'{field} AS' not in sql_query.upper():
                                # Псевдоним не определен, но используется в ORDER BY
                                # Это может быть ошибка - используем имя колонки вместо псевдонима
                                # Пока просто пропускаем, так как это требует сложного анализа
                                pass
            
            # Если SQL не изменился после исправлений, выходим из цикла
            if sql_query == current_sql:
                break
        
        try:
            # Дополнительная валидация перед выполнением
            is_valid, error_message = self.validate_sql_query(sql_query)
            
            if not is_valid:
                return {
                    "success": False,
                    "error": error_message,
                    "data": None,
                    "sql": sql_query
                }
            
            # Выполняем запрос
            with self.engine.connect() as connection:
                result = connection.execute(text(sql_query))
                
                # Получаем колонки
                columns = list(result.keys())
                
                # Получаем данные
                rows = result.fetchall()
                
                # Преобразуем в список словарей
                data = []
                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        value = row[i]
                        # Преобразуем специальные типы в строки
                        if hasattr(value, 'isoformat'):  # datetime
                            value = value.isoformat()
                        row_dict[col] = value
                    data.append(row_dict)
                
                # Ограничиваем данные до 5 записей для отправки в AI, но для источников отправляем все (до 500)
                limited_data = data[:5]  # Для AI-форматирования
                all_data = data[:500]  # Для источников (Search found/Results) - до 500 записей
                total_count = len(data)
                
                return {
                    "success": True,
                    "data": all_data,  # Все данные для источников (до 500)
                    "columns": columns,
                    "row_count": total_count,  # Общее количество записей
                    "limited_row_count": len(limited_data),  # Количество записей для AI (до 5)
                    "sql": sql_query
                }
                
        except SQLAlchemyError as e:
            error_str = str(e)
            
            # Критически важное исправление: UNION ALL с разным количеством колонок
            if auto_fix and ('SELECTs to the left and right of UNION ALL do not have the same number' in error_str or 
                           'do not have the same number of result columns' in error_str):
                print(f"⚠️ Обнаружена ошибка UNION: разное количество колонок. Пытаюсь исправить...")
                fixed_sql = self._fix_union_column_count(sql_query)
                if fixed_sql != sql_query:
                    try:
                        print(f"✅ Применяю исправление UNION...")
                        result = self.db_session.execute(text(fixed_sql))
                        rows = result.fetchall()
                        columns = result.keys() if rows else []
                        data = [dict(zip(columns, row)) for row in rows]
                        all_data = data[:500]
                        return {
                            "success": True,
                            "data": all_data,
                            "columns": list(columns),
                            "row_count": len(data),
                            "error": None,
                            "sql": fixed_sql
                        }
                    except Exception as retry_e:
                        print(f"⚠️ Исправление UNION не помогло: {str(retry_e)[:100]}")
                        # Пробуем более агрессивное исправление - убираем ORDER BY если он вызывает проблемы
                        if 'ORDER BY' in fixed_sql.upper():
                            try:
                                # Убираем ORDER BY из запроса
                                no_order_sql = re.sub(r'\s+ORDER BY\s+.*$', '', fixed_sql, flags=re.IGNORECASE)
                                result = self.db_session.execute(text(no_order_sql))
                                rows = result.fetchall()
                                columns = result.keys() if rows else []
                                data = [dict(zip(columns, row)) for row in rows]
                                all_data = data[:500]
                                return {
                                    "success": True,
                                    "data": all_data,
                                    "columns": list(columns),
                                    "row_count": len(data),
                                    "error": None,
                                    "sql": no_order_sql
                                }
                            except:
                                pass
            
            # Исправление ORDER BY ошибок
            if auto_fix and ('ORDER BY term does not match' in error_str or 'ORDER BY' in error_str):
                print(f"⚠️ Обнаружена ошибка ORDER BY. Пытаюсь исправить...")
                fixed_sql = self._fix_union_order_by_errors(sql_query)
                if fixed_sql != sql_query:
                    try:
                        print(f"✅ Применяю исправление ORDER BY...")
                        result = self.db_session.execute(text(fixed_sql))
                        rows = result.fetchall()
                        columns = result.keys() if rows else []
                        data = [dict(zip(columns, row)) for row in rows]
                        all_data = data[:500]
                        return {
                            "success": True,
                            "data": all_data,
                            "columns": list(columns),
                            "row_count": len(data),
                            "error": None,
                            "sql": fixed_sql
                        }
                    except Exception as retry_e:
                        print(f"⚠️ Исправление ORDER BY не помогло: {str(retry_e)[:100]}")
                        # Пробуем убрать ORDER BY полностью
                        try:
                            no_order_sql = re.sub(r'\s+ORDER BY\s+.*$', '', sql_query, flags=re.IGNORECASE)
                            result = self.db_session.execute(text(no_order_sql))
                            rows = result.fetchall()
                            columns = result.keys() if rows else []
                            data = [dict(zip(columns, row)) for row in rows]
                            all_data = data[:500]
                            return {
                                "success": True,
                                "data": all_data,
                                "columns": list(columns),
                                "row_count": len(data),
                                "error": None,
                                "sql": no_order_sql
                            }
                        except:
                            pass
            
            # Автоматическое исправление ошибок опций (mileage)
            if auto_fix and 'mileage' in error_str.lower() and ('cars' in sql_query.lower() or 'FROM cars' in sql_query.lower()):
                fixed_sql = self._fix_options_sql_errors(sql_query)
                if fixed_sql != sql_query:
                    try:
                        result = self.db_session.execute(text(fixed_sql))
                        rows = result.fetchall()
                        columns = result.keys() if rows else []
                        data = [dict(zip(columns, row)) for row in rows]
                        all_data = data[:500]  # До 500 записей для источников
                        return {
                            "success": True,
                            "data": all_data,
                            "columns": list(columns),
                            "row_count": len(data),
                            "error": None,
                            "sql": fixed_sql
                        }
                    except Exception as retry_e:
                        # Если исправление не помогло, продолжаем с исходной ошибкой
                        pass
            
            # Автоматическое исправление GROUP_CONCAT ошибок
            if auto_fix and ('DISTINCT aggregates' in error_str or ('GROUP_CONCAT' in sql_query.upper() and 'DISTINCT' in sql_query.upper())):
                fixed_sql = self._fix_options_sql_errors(sql_query)
                if fixed_sql != sql_query:
                    try:
                        result = self.db_session.execute(text(fixed_sql))
                        rows = result.fetchall()
                        columns = result.keys() if rows else []
                        data = [dict(zip(columns, row)) for row in rows]
                        all_data = data[:500]  # До 500 записей для источников
                        return {
                            "success": True,
                            "data": all_data,
                            "columns": list(columns),
                            "row_count": len(data),
                            "error": None,
                            "sql": fixed_sql
                        }
                    except Exception as retry_e:
                        # Если исправление не помогло, продолжаем с исходной ошибкой
                        pass
            
            # Автоматическое исправление ORDER BY ошибок в UNION с опциями
            if auto_fix and ('ORDER BY term does not match' in error_str or 'ORDER BY' in error_str) and ('UNION' in sql_query.upper() and ('car_options' in sql_query.upper() or 'mileage' in sql_query.lower())):
                fixed_sql = self._fix_options_sql_errors(sql_query)
                if fixed_sql != sql_query:
                    try:
                        result = self.db_session.execute(text(fixed_sql))
                        rows = result.fetchall()
                        columns = result.keys() if rows else []
                        data = [dict(zip(columns, row)) for row in rows]
                        all_data = data[:500]  # До 500 записей для источников
                        return {
                            "success": True,
                            "data": all_data,
                            "columns": list(columns),
                            "row_count": len(data),
                            "error": None,
                            "sql": fixed_sql
                        }
                    except Exception as retry_e:
                        # Если исправление не помогло, продолжаем с исходной ошибкой
                        pass
            # Если ошибка связана с ORDER BY в UNION и еще не пробовали исправлять, пытаемся автоматически исправить
            if auto_fix and ('ORDER BY' in error_str.upper() or 'UNION' in error_str.upper()) and 'UNION' in sql_query.upper() and sql_query == original_sql:
                # Пытаемся исправить еще раз
                fixed_sql = self._fix_union_order_by_errors(original_sql)
                if fixed_sql != original_sql:
                    try:
                        # Выполняем исправленный запрос рекурсивно (но уже без auto_fix чтобы избежать бесконечной рекурсии)
                        return await self.execute_sql_query(fixed_sql, auto_fix=False)
                    except:
                        pass
            
            return {
                "success": False,
                "error": f"Ошибка выполнения SQL: {error_str}",
                "data": None,
                "sql": sql_query
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Неожиданная ошибка: {str(e)}",
                "data": None
            }
    
    async def process_question(self, question: str, try_alternative_on_zero: bool = True) -> Dict[str, Any]:
        """
        Полный цикл обработки вопроса: генерация SQL и выполнение
        
        Args:
            question: Вопрос пользователя
            try_alternative_on_zero: Если True, при 0 результатах пытается перегенерировать SQL через альтернативный агент
        """
        # Проверка: если запрос о клиренсе, сразу возвращаем пустой результат
        question_lower = question.lower()
        if any(kw in question_lower for kw in ['клиренс', 'дорожный просвет']):
            return {
                "success": True,
                "sql": "SELECT NULL WHERE 1=0; -- Клиренс отсутствует в базе данных",
                "data": [],
                "columns": [],
                "row_count": 0,
                "answer": "К сожалению, информация о клиренсе (дорожном просвете) отсутствует в базе данных. Поле dimensions содержит габариты автомобиля (длина*ширина*высота), а не клиренс. Клиренс - это расстояние от земли до нижней точки автомобиля (обычно 15-25 см), а высота в dimensions - это высота автомобиля до крыши (обычно 140-200 см)."
            }
        
        # Генерируем SQL
        sql_result = await self.generate_sql_from_natural_language(question)
        
        if not sql_result.get("success"):
            return {
                "success": False,
                "error": sql_result.get("error", "Не удалось сгенерировать SQL"),
                "sql": sql_result.get("sql"),
                "data": None
            }
        
        sql_query = sql_result["sql"]
        used_alternative_agent = False
        
        # Выполняем SQL (с автоматическим исправлением UNION ошибок)
        execution_result = await self.execute_sql_query(sql_query, auto_fix=True)
        
        # Если есть ошибка выполнения SQL или 0 результатов, пытаемся использовать альтернативный агент
        should_try_alternative = False
        original_error = None
        
        if not execution_result.get("success"):
            original_error = execution_result.get("error", "Не удалось выполнить SQL")
            if try_alternative_on_zero:
                print(f"⚠️ Ошибка выполнения SQL: {original_error[:200]}...")
                print(f"⚠️ Пытаюсь перегенерировать SQL через альтернативный агент...")
                should_try_alternative = True
            else:
                return {
                    "success": False,
                    "error": original_error,
                    "sql": sql_query,
                    "data": None
                }
        
        # Если найдено 0 результатов и включена опция попытки альтернативного агента
        row_count = execution_result.get("row_count", 0)
        if row_count == 0 and try_alternative_on_zero and not should_try_alternative:
            # НЕ пытаемся перегенерировать SQL - вместо этого будет использован Elasticsearch fallback
            # в ai.py при обработке результата с 0 записями
            print(f"⚠️ Найдено 0 результатов. Переходим к Elasticsearch fallback (перегенерация SQL отключена)...")
            # Не устанавливаем should_try_alternative = True, чтобы не пытаться перегенерировать
        
        # Пытаемся использовать альтернативный агент
        if should_try_alternative:
            
            # Получаем текущие настройки AI
            ai_settings = self._load_ai_settings()
            current_model = ai_settings.get("response_model", "")
            
            # Определяем альтернативный агент
            alternative_model = None
            if current_model.startswith("mistral:"):
                # Переключаемся на Ollama
                alternative_model = "ollama:llama3:8b"
                print(f"🔄 Переключение с Mistral на Ollama (llama3:8b)...")
            elif current_model.startswith("openai:"):
                # Переключаемся на Ollama
                alternative_model = "ollama:llama3:8b"
                print(f"🔄 Переключение с OpenAI на Ollama (llama3:8b)...")
            elif current_model.startswith("anthropic:"):
                # Переключаемся на Ollama
                alternative_model = "ollama:llama3:8b"
                print(f"🔄 Переключение с Anthropic на Ollama (llama3:8b)...")
            elif current_model.startswith("ollama:"):
                # Переключаемся на Mistral (если доступен)
                alternative_model = "mistral:mistral-small-latest"
                print(f"🔄 Переключение с Ollama на Mistral...")
            else:
                # По умолчанию пробуем Ollama
                alternative_model = "ollama:llama3:8b"
                print(f"🔄 Использую альтернативный агент: Ollama (llama3:8b)...")
            
            # Временно переключаем настройки для альтернативного агента
            original_settings = ai_settings.copy()
            if alternative_model:
                # Генерируем SQL через альтернативный агент
                try:
                    schema = self.get_database_schema()
                    # Используем полный промпт из generate_sql_from_natural_language
                    prompt = f"""Ты — эксперт по SQL для автомобильной базы данных. База данных использует SQLite.

═══════════════════════════════════════════════════════════════════════════════
КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ДЛЯ SQLite:
═══════════════════════════════════════════════════════════════════════════════

1. БЕЗОПАСНОСТЬ:
   - Используй ТОЛЬКО оператор SELECT
   - НЕ используй: DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, EXEC, EXECUTE
   - Запрещены любые операции изменения данных

2. SQLite ОГРАНИЧЕНИЯ:
   - SQLite НЕ поддерживает регулярные выражения (REGEXP, REGEXP_LIKE)
   - SQLite НЕ поддерживает сложные регулярные выражения в REPLACE()
   - Для очистки строк используй вложенные REPLACE(): REPLACE(REPLACE(REPLACE(...)))
   - Используй стандартные SQL функции: UPPER(), LOWER(), LIKE, CAST()

3. РЕГИСТРОНЕЗАВИСИМЫЙ ПОИСК МАРОК И ГОРОДОВ:
   - ВСЕГДА используй UPPER() с LIKE для поиска марок (НЕ используй =):
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%TOYOTA%'  -- найдет Toyota, TOYOTA, toyota
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%BMW%'      -- найдет BMW, bmw, Bmw
     ❌ НЕПРАВИЛЬНО: WHERE UPPER(mark) = 'BMW'        -- может не найти из-за пробелов
     ❌ НЕПРАВИЛЬНО: WHERE mark = 'Toyota'           -- не найдет варианты регистра
   
   - Для городов тоже используй регистронезависимый поиск с LIKE:
     ✅ ПРАВИЛЬНО: WHERE UPPER(city) LIKE '%МОСКВА%'
     ✅ ПРАВИЛЬНО: WHERE UPPER(city) LIKE '%РОСТОВ%'
   
   - ВАЖНО: В базе могут быть пробелы или различия в регистре, поэтому ВСЕГДА используй LIKE, а не =

4. РАБОТА С ЦЕНАМИ (SQLite):
   - Цена хранится как STRING и может содержать: пробелы, запятые, символ ₽
   - Очистка цены для SQLite (используй вложенные REPLACE):
     ✅ ПРАВИЛЬНО: CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL)
     ✅ ПРАВИЛЬНО: CAST(REPLACE(REPLACE(price, ' ', ''), ',', '.') AS REAL)
     ❌ НЕПРАВИЛЬНО: REPLACE(price, '[^0-9]', '') (SQLite не поддерживает regex)
   
   - Всегда проверяй наличие цены:
     ✅ ПРАВИЛЬНО: WHERE price IS NOT NULL AND price != ''

5. ПОИСК ПО ТИПАМ (КПП, топливо, кузов):
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: В SQLite UPPER() с кириллицей работает НЕКОРРЕКТНО!
     ❌ НЕ используй: UPPER(fuel_type) LIKE '%БЕНЗИН%' (НЕ РАБОТАЕТ в SQLite!)
   
   - В базе РАЗНЫЕ варианты написания в таблицах cars и used_cars:
     - Топливо в cars: 'бензин' (маленькими), в used_cars: 'Бензин' (с заглавной)
     - Топливо в cars: 'дизель' (маленькими), в used_cars: 'Дизель' (с заглавной)
     - Кузов в cars: 'Седан', в used_cars: 'Седан' (оба с заглавной)
   
   - ✅ ИСПОЛЬЗУЙ LOWER() для кириллицы:
     ✅ ПРАВИЛЬНО: WHERE LOWER(fuel_type) LIKE '%бензин%'  -- найдет и 'бензин' и 'Бензин'
     ✅ ПРАВИЛЬНО: WHERE LOWER(body_type) LIKE '%седан%'    -- найдет 'Седан'
   
   - ✅ ИЛИ используй комбинацию точных значений с OR:
     ✅ ПРАВИЛЬНО: WHERE fuel_type = 'бензин' OR fuel_type = 'Бензин' OR LOWER(fuel_type) LIKE '%бензин%'
     ✅ ПРАВИЛЬНО: WHERE (fuel_type = 'бензин' OR fuel_type = 'Бензин') AND ...
   
   - ✅ Для латиницы можно использовать UPPER():
     ✅ ПРАВИЛЬНО: WHERE UPPER(gear_box_type) LIKE '%AUTOMATIC%'  -- для английских значений
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%BMW%'                  -- для марок

═══════════════════════════════════════════════════════════════════════════════
СХЕМА БАЗЫ ДАННЫХ:
═══════════════════════════════════════════════════════════════════════════════
{schema}
═══════════════════════════════════════════════════════════════════════════════

ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}

Сгенерируй ТОЛЬКО SQL запрос (без объяснений, без markdown, без дополнительного текста):
SQL запрос:"""
                    
                    alternative_sql_response = None
                    if alternative_model.startswith("ollama:"):
                        model_name = alternative_model.replace("ollama:", "")
                        alternative_sql_response = await self._generate_with_ollama(model_name, prompt)
                    elif alternative_model.startswith("mistral:"):
                        model_name = alternative_model.replace("mistral:", "")
                        api_key = ai_settings.get("api_key", settings.mistral_api_key)
                        alternative_sql_response = await self._generate_with_mistral(model_name, api_key, prompt)
                    
                    if alternative_sql_response:
                        alternative_sql = self._extract_sql_from_response(alternative_sql_response)
                        
                        # Валидируем альтернативный SQL
                        is_valid, error_message = self.validate_sql_query(alternative_sql)
                        if is_valid and alternative_sql != sql_query:
                            print(f"✅ Альтернативный SQL сгенерирован: {alternative_sql[:100]}...")
                            sql_query = alternative_sql
                            used_alternative_agent = True
                            
                            # Выполняем альтернативный SQL
                            execution_result = await self.execute_sql_query(alternative_sql, auto_fix=True)
                            row_count = execution_result.get("row_count", 0)
                            
                            if not execution_result.get("success"):
                                print(f"⚠️ Альтернативный SQL не выполнился: {execution_result.get('error')}")
                                # Возвращаемся к исходному результату
                                execution_result = await self.execute_sql_query(sql_result["sql"], auto_fix=True)
                                used_alternative_agent = False
                        else:
                            print(f"⚠️ Альтернативный SQL не прошел валидацию: {error_message}")
                    else:
                        print(f"⚠️ Альтернативный SQL не был сгенерирован")
                except Exception as e:
                    print(f"⚠️ Ошибка при генерации альтернативного SQL: {str(e)[:100]}")
                    # Если была исходная ошибка, возвращаем её
                    if original_error:
                        return {
                            "success": False,
                            "error": f"Ошибка выполнения SQL: {original_error}. Попытка использовать альтернативный агент не удалась: {str(e)[:100]}",
                            "sql": sql_query,
                            "data": None
                        }
                    # Иначе возвращаемся к исходному результату
                    execution_result = await self.execute_sql_query(sql_result["sql"], auto_fix=True)
                    used_alternative_agent = False
        
        # Если после всех попыток все еще есть ошибка, возвращаем её
        if not execution_result.get("success") and original_error:
            return {
                "success": False,
                "error": original_error,
                "sql": sql_query,
                "data": None
            }
        
        # Формируем понятный ответ для пользователя
        answer = self._format_answer(execution_result)
        
        result = {
            "success": True,
            "sql": sql_query,
            "data": execution_result.get("data"),
            "columns": execution_result.get("columns"),
            "row_count": execution_result.get("row_count"),
            "answer": answer
        }
        
        if used_alternative_agent:
            result["used_alternative_agent"] = True
            result["alternative_agent"] = alternative_model
        
        return result
    
    def _build_sql_prompt(self, question: str, schema: str) -> str:
        """Строит промпт для генерации SQL запроса"""
        prompt = f"""Ты — эксперт по SQL для автомобильной базы данных. База данных использует SQLite.

═══════════════════════════════════════════════════════════════════════════════
КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ДЛЯ SQLite:
═══════════════════════════════════════════════════════════════════════════════

1. БЕЗОПАСНОСТЬ:
   - Используй ТОЛЬКО оператор SELECT
   - НЕ используй: DROP, DELETE, INSERT, UPDATE, ALTER, CREATE, EXEC, EXECUTE
   - Запрещены любые операции изменения данных

2. SQLite ОГРАНИЧЕНИЯ:
   - SQLite НЕ поддерживает регулярные выражения (REGEXP, REGEXP_LIKE)
   - SQLite НЕ поддерживает сложные регулярные выражения в REPLACE()
   - Для очистки строк используй вложенные REPLACE(): REPLACE(REPLACE(REPLACE(...)))
   - Используй стандартные SQL функции: UPPER(), LOWER(), LIKE, CAST()

3. РЕГИСТРОНЕЗАВИСИМЫЙ ПОИСК МАРОК И ГОРОДОВ:
   - ВСЕГДА используй UPPER() с LIKE для поиска марок (НЕ используй =):
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%TOYOTA%'  -- найдет Toyota, TOYOTA, toyota
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%BMW%'      -- найдет BMW, bmw, Bmw
     ❌ НЕПРАВИЛЬНО: WHERE UPPER(mark) = 'BMW'        -- может не найти из-за пробелов
     ❌ НЕПРАВИЛЬНО: WHERE mark = 'Toyota'           -- не найдет варианты регистра
   
   - Для городов тоже используй регистронезависимый поиск с LIKE:
     ✅ ПРАВИЛЬНО: WHERE UPPER(city) LIKE '%МОСКВА%'
     ✅ ПРАВИЛЬНО: WHERE UPPER(city) LIKE '%РОСТОВ%'
   
   - ВАЖНО: В базе могут быть пробелы или различия в регистре, поэтому ВСЕГДА используй LIKE, а не =

4. РАБОТА С ЦЕНАМИ (SQLite):
   - Цена хранится как STRING и может содержать: пробелы, запятые, символ ₽
   - Очистка цены для SQLite (используй вложенные REPLACE):
     ✅ ПРАВИЛЬНО: CAST(REPLACE(REPLACE(REPLACE(price, ' ', ''), '₽', ''), ',', '.') AS REAL)
     ✅ ПРАВИЛЬНО: CAST(REPLACE(REPLACE(price, ' ', ''), ',', '.') AS REAL)
     ❌ НЕПРАВИЛЬНО: REPLACE(price, '[^0-9]', '') (SQLite не поддерживает regex)
   
   - Всегда проверяй наличие цены:
     ✅ ПРАВИЛЬНО: WHERE price IS NOT NULL AND price != ''

5. ПОИСК ПО ТИПАМ (КПП, топливо, кузов):
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: В SQLite UPPER() с кириллицей работает НЕКОРРЕКТНО!
     ❌ НЕ используй: UPPER(fuel_type) LIKE '%БЕНЗИН%' (НЕ РАБОТАЕТ в SQLite!)
   
   - В базе РАЗНЫЕ варианты написания в таблицах cars и used_cars:
     - Топливо в cars: 'бензин' (маленькими), в used_cars: 'Бензин' (с заглавной)
     - Топливо в cars: 'дизель' (маленькими), в used_cars: 'Дизель' (с заглавной)
     - Кузов в cars: 'Седан', в used_cars: 'Седан' (оба с заглавной)
   
   - ✅ ИСПОЛЬЗУЙ LOWER() для кириллицы:
     ✅ ПРАВИЛЬНО: WHERE LOWER(fuel_type) LIKE '%бензин%'  -- найдет и 'бензин' и 'Бензин'
     ✅ ПРАВИЛЬНО: WHERE LOWER(body_type) LIKE '%седан%'    -- найдет 'Седан'
   
   - ✅ ИЛИ используй комбинацию точных значений с OR:
     ✅ ПРАВИЛЬНО: WHERE fuel_type = 'бензин' OR fuel_type = 'Бензин' OR LOWER(fuel_type) LIKE '%бензин%'
     ✅ ПРАВИЛЬНО: WHERE (fuel_type = 'бензин' OR fuel_type = 'Бензин') AND ...
   
   - ✅ Для латиницы можно использовать UPPER():
     ✅ ПРАВИЛЬНО: WHERE UPPER(gear_box_type) LIKE '%AUTOMATIC%'  -- для английских значений
     ✅ ПРАВИЛЬНО: WHERE UPPER(mark) LIKE '%BMW%'                  -- для марок

═══════════════════════════════════════════════════════════════════════════════
СХЕМА БАЗЫ ДАННЫХ:
═══════════════════════════════════════════════════════════════════════════════
{schema}
═══════════════════════════════════════════════════════════════════════════════

ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}

Сгенерируй ТОЛЬКО SQL запрос (без объяснений, без markdown, без дополнительного текста):
SQL запрос:"""
        return prompt
    
    def _format_answer(self, execution_result: Dict[str, Any]) -> str:
        """Форматирует результат выполнения SQL в понятный ответ"""
        row_count = execution_result.get("row_count", 0)
        data = execution_result.get("data", [])
        columns = execution_result.get("columns", [])
        
        if row_count == 0:
            return "Результатов не найдено."
        
        if row_count == 1:
            # Если один результат, показываем его подробно
            row = data[0]
            answer_parts = []
            for col in columns:
                value = row.get(col, "")
                answer_parts.append(f"{col}: {value}")
            return "\n".join(answer_parts)
        else:
            # Если много результатов, показываем количество и первые несколько
            preview_count = min(5, row_count)
            answer = f"Найдено записей: {row_count}\n\n"
            answer += "Первые результаты:\n"
            
            for i in range(preview_count):
                row = data[i]
                answer += f"\n{i+1}. "
                row_parts = []
                for col in columns:
                    value = row.get(col, "")
                    row_parts.append(f"{col}={value}")
                answer += ", ".join(row_parts)
            
            if row_count > preview_count:
                answer += f"\n\n... и еще {row_count - preview_count} записей"
            
            return answer
    
    def _load_ai_settings(self) -> Dict[str, Any]:
        """Загружает настройки AI из файла"""
        try:
            if os.path.exists("ai_settings.json"):
                with open("ai_settings.json", "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки настроек AI: {e}")
        
        # Возвращаем настройки по умолчанию
        return {
            "response_model": "",
            "embedding_model": "",
            "api_service": "mistral",
            "api_key": "",
            "updated_at": None
        }
    
    async def _generate_with_ollama(self, model_name: str, prompt: str, system_prompt: str = None) -> str:
        """Генерация через Ollama с поддержкой chat API"""
        ollama_urls = [
            "http://localhost:11434",  # Приоритет localhost
            f"http://{settings.ollama_host}:{settings.ollama_port}",
            "http://host.docker.internal:11434"
        ]
        
        # Используем chat API для лучшей поддержки system prompt
        if system_prompt is None:
            system_prompt = "Ты — эксперт по SQL. Генерируй только валидные SQL запросы без объяснений."
        
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 8192
            }
        }
        
        for url in ollama_urls:
            try:
                async with httpx.AsyncClient() as client:
                    # Пробуем chat API сначала
                    try:
                        resp = await client.post(f"{url}/api/chat", json=payload, timeout=180)
                        resp.raise_for_status()
                        data = resp.json()
                        message = data.get("message", {})
                        if message:
                            return message.get("content", "")
                        return data.get("response", "")
                    except:
                        # Fallback на старый generate API
                        old_payload = {
                            "model": model_name,
                            "prompt": f"{system_prompt}\n\n{prompt}",
                            "stream": False
                        }
                        resp = await client.post(f"{url}/api/generate", json=old_payload, timeout=180)
                        resp.raise_for_status()
                        data = resp.json()
                        return data.get("response", "")
            except Exception as e:
                print(f"⚠️ Ollama недоступен по адресу {url}: {str(e)[:100]}")
                continue
        
        raise Exception("Не удается подключиться к Ollama")
    
    async def _generate_with_mistral(self, model_name: str, api_key: str, prompt: str) -> str:
        """Генерация через Mistral API с автоматическим переключением на Llama 3:8b при rate limit"""
        url = f"{settings.mistral_base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "Ты — эксперт по SQL. Генерируй только валидные SQL запросы без объяснений."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 8192,  # Увеличено для полных ответов
            "stream": False,
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, headers=headers, json=payload, timeout=120)
                    
                    # Проверяем rate limit
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", 1))
                        if attempt < max_retries - 1:
                            print(f"⚠️ Rate limit detected, waiting {retry_after}s before retry {attempt + 1}/{max_retries}...")
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            # Достигнут rate limit, переключаемся на Llama 3:8b
                            print(f"⚠️ Rate limit exceeded after {max_retries} attempts. Переключение на Llama 3:8b...")
                            return await self._generate_with_ollama("llama3:8b", prompt, "Ты — эксперт по SQL. Генерируй только валидные SQL запросы без объяснений.")
                    
                    resp.raise_for_status()
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        message = choices[0].get("message", {}).get("content", "")
                        return message or ""
                    return ""
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    if attempt < max_retries - 1:
                        retry_after = int(e.response.headers.get("Retry-After", 1))
                        print(f"⚠️ Rate limit detected, waiting {retry_after}s before retry {attempt + 1}/{max_retries}...")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        # Достигнут rate limit, переключаемся на Llama 3:8b
                        print(f"⚠️ Rate limit exceeded after {max_retries} attempts. Переключение на Llama 3:8b...")
                        return await self._generate_with_ollama("llama3:8b", prompt, "Ты — эксперт по SQL. Генерируй только валидные SQL запросы без объяснений.")
                else:
                    raise
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"⚠️ Ошибка Mistral API при попытке {attempt + 1}/{max_retries}: {str(e)[:100]}")
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                else:
                    # При последней попытке переключаемся на Llama 3:8b
                    print(f"⚠️ Mistral API недоступен после {max_retries} попыток. Переключение на Llama 3:8b...")
                    return await self._generate_with_ollama("llama3:8b", prompt, "Ты — эксперт по SQL. Генерируй только валидные SQL запросы без объяснений.")
        
        # Если все попытки исчерпаны, переключаемся на Llama 3:8b
        print("🔄 Переключение на Llama 3:8b...")
        return await self._generate_with_ollama("llama3:8b", prompt, "Ты — эксперт по SQL. Генерируй только валидные SQL запросы без объяснений.")
    
    async def _generate_with_openai(self, model_name: str, api_key: str, prompt: str) -> str:
        """Генерация через OpenAI API"""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "Ты — эксперт по SQL. Генерируй только валидные SQL запросы без объяснений."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 8192,  # Увеличено для полных ответов
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {}).get("content", "")
                return message or ""
            return ""
    
    async def _generate_with_anthropic(self, model_name: str, api_key: str, prompt: str) -> str:
        """Генерация через Anthropic API"""
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        payload = {
            "model": model_name,
            "max_tokens": 8192,  # Увеличено для полных ответов
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", [])
            if content:
                return content[0].get("text", "")
            return ""

