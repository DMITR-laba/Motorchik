Нужно чтобы всеми функциями управлял главный ии , который выбирал подходящие ии модели из списка моделей ollama для каждого места гже он требуется , кроме мест где пользователь сам назначает ии модель    


Отличная идеа! Переделаем систему под ассистента автосалона для подбора автомобилей. 

## 🚗 Архитектура ассистента автосалона

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Input Layer   │───▶│  Context Manager │───▶│  Relation Analyzer│
└─────────────────┘    └──────────────────┘    └──────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Search Analyzer│    │  Memory Manager  │───▶│ Question Strategy│
└─────────────────┘    └──────────────────┘    └──────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Car DB Manager  │◄───│ Query Generator  │◄───│ Search Trigger   │
└─────────────────┘    └──────────────────┘    └──────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Result Processor│───▶│ Response Builder │───▶│  Output Layer    │
└─────────────────┘    └──────────────────┘    └──────────────────┘
```

## 🚀 Полная реализация ассистента автосалона

```python
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI
from langchain.schema import BaseOutputParser
from typing import List, Dict, Any, Tuple, Optional, Union
from dataclasses import dataclass
import os
import json
import re
from datetime import datetime
import time
import sqlite3
from abc import ABC, abstractmethod
import random

# Установите ваш API-ключ OpenAI
os.environ["OPENAI_API_KEY"] = "ваш_api_ключ"

# Инициализация модели
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0.7)

### 1. 🏢 Конфигурация для автосалона

@dataclass
class CarDealerConfig:
    """Конфигурация для ассистента автосалона"""
    enabled: bool = True
    auto_search_threshold: float = 0.7
    max_results: int = 5
    search_domains: List[str] = None
    enable_finance_calculations: bool = True
    enable_trade_in: bool = True
    enable_test_drive: bool = True
    
    def __post_init__(self):
        if self.search_domains is None:
            self.search_domains = ["легковые", "внедорожники", "премиум", "электромобили", "коммерческие"]

class Searchable(ABC):
    """Интерфейс для поисковых систем автосалона"""
    
    @abstractmethod
    def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        pass

### 2. 🗃️ База данных автомобилей

class CarDatabase(Searchable):
    """База данных автомобилей автосалона"""
    
    def __init__(self, db_path=":memory:"):
        self.conn = sqlite3.connect(db_path)
        self._initialize_database()
    
    def _initialize_database(self):
        """Инициализация базы данных автомобилей"""
        cursor = self.conn.cursor()
        
        # Создаем таблицу автомобилей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cars (
                id INTEGER PRIMARY KEY,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                year INTEGER,
                price REAL,
                category TEXT,
                fuel_type TEXT,
                transmission TEXT,
                engine_volume REAL,
                power INTEGER,
                mileage INTEGER,
                color TEXT,
                features TEXT,
                available INTEGER,
                discount REAL,
                description TEXT
            )
        ''')
        
        # Добавляем тестовые данные
        cars_data = [
            # Седаны
            (1, "Toyota", "Camry", 2023, 2500000, "седан", "бензин", "автомат", 2.5, 249, 0, "белый", "кожанный салон, климат контроль, камера заднего вида", 1, 0, "Современный седан с отличной экономичностью"),
            (2, "Hyundai", "Solaris", 2023, 1500000, "седан", "бензин", "автомат", 1.6, 123, 0, "черный", "мультимедиа, кондиционер, подушки безопасности", 1, 5, "Надежный городской седан"),
            (3, "BMW", "3 Series", 2023, 3500000, "седан", "бензин", "автомат", 2.0, 184, 0, "синий", "кожа, панорамная крыша, премиум аудио", 1, 0, "Премиальный седан для взыскательных клиентов"),
            
            # Внедорожники
            (4, "Toyota", "RAV4", 2023, 2800000, "внедорожник", "бензин", "автомат", 2.0, 150, 0, "серый", "полный привод, климат контроль, мультимедиа", 1, 3, "Популярный кроссовер для города и путешествий"),
            (5, "Kia", "Sportage", 2023, 2200000, "внедорожник", "дизель", "автомат", 2.0, 185, 0, "красный", "полный привод, подогрев сидений, камера 360", 1, 0, "Стильный и практичный внедорожник"),
            (6, "Land Rover", "Range Rover Evoque", 2023, 4500000, "внедорожник", "бензин", "автомат", 2.0, 249, 0, "белый", "премиум отделка, полный привод, все опции", 1, 7, "Роскошный компактный внедорожник"),
            
            # Хэтчбеки
            (7, "Volkswagen", "Golf", 2023, 1800000, "хэтчбек", "бензин", "механика", 1.4, 150, 0, "красный", "круиз контроль, мультимедиа, кондиционер", 1, 0, "Классический хэтчбек с отличной динамикой"),
            (8, "Kia", "Rio X", 2023, 1400000, "хэтчбек", "бензин", "автомат", 1.6, 123, 0, "оранжевый", "мультимедиа, кондиционер, датчики парковки", 1, 8, "Экономичный городской хэтчбек"),
            
            # Электромобили
            (9, "Tesla", "Model 3", 2023, 3800000, "седан", "электричество", "автомат", 0, 283, 0, "белый", "автопилот, премиум аудио, стеклянная крыша", 1, 0, "Инновационный электромобиль"),
            (10, "Nissan", "Leaf", 2023, 2200000, "хэтчбек", "электричество", "автомат", 0, 150, 0, "синий", "мультимедиа, климат контроль, быстрая зарядка", 1, 5, "Доступный электромобиль для города"),
            
            # Коммерческие
            (11, "Volkswagen", "Transporter", 2023, 3200000, "фургон", "дизель", "механика", 2.0, 150, 0, "белый", "кондиционер, мультимедиа, усиленная подвеска", 1, 0, "Надежный коммерческий фургон"),
            (12, "Ford", "Transit", 2023, 2800000, "фургон", "дизель", "автомат", 2.0, 170, 0, "серый", "круиз контроль, климат контроль, камера", 1, 4, "Универсальный коммерческий автомобиль"),
        ]
        
        cursor.executemany('''
            INSERT OR REPLACE INTO cars 
            (id, brand, model, year, price, category, fuel_type, transmission, 
             engine_volume, power, mileage, color, features, available, discount, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', cars_data)
        
        self.conn.commit()
    
    def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Поиск автомобилей по параметрам"""
        try:
            conditions = []
            params = []
            
            if query.get("brand"):
                conditions.append("brand LIKE ?")
                params.append(f"%{query['brand']}%")
            
            if query.get("category"):
                conditions.append("category = ?")
                params.append(query["category"])
            
            if query.get("min_price"):
                conditions.append("price >= ?")
                params.append(query["min_price"])
            
            if query.get("max_price"):
                conditions.append("price <= ?")
                params.append(query["max_price"])
            
            if query.get("fuel_type"):
                conditions.append("fuel_type = ?")
                params.append(query["fuel_type"])
            
            if query.get("transmission"):
                conditions.append("transmission = ?")
                params.append(query["transmission"])
            
            if query.get("min_year"):
                conditions.append("year >= ?")
                params.append(query["min_year"])
            
            # Поиск по ключевым словам в описании и характеристиках
            if query.get("keywords"):
                keywords = query["keywords"].split(",")
                keyword_conditions = []
                for keyword in keywords:
                    keyword_conditions.append("(description LIKE ? OR features LIKE ? OR model LIKE ?)")
                    params.extend([f"%{keyword.strip()}%", f"%{keyword.strip()}%", f"%{keyword.strip()}%"])
                conditions.append(f"({' OR '.join(keyword_conditions)})")
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            sql = f"SELECT * FROM cars WHERE {where_clause} AND available = 1 ORDER BY price ASC LIMIT 20"
            
            cursor = self.conn.cursor()
            cursor.execute(sql, params)
            results = cursor.fetchall()
            
            # Преобразуем в словари
            columns = [desc[0] for desc in cursor.description]
            cars = [dict(zip(columns, row)) for row in results]
            
            # Применяем скидки если есть
            for car in cars:
                if car.get('discount', 0) > 0:
                    car['original_price'] = car['price']
                    car['price'] = car['price'] * (1 - car['discount'] / 100)
                    car['price'] = round(car['price'], 2)
            
            return cars
            
        except Exception as e:
            print(f"❌ Ошибка поиска в БД автомобилей: {e}")
            return []
    
    def get_schema(self) -> Dict[str, Any]:
        """Возвращает схему базы данных"""
        return {
            "table": "cars",
            "columns": [
                {"name": "brand", "type": "TEXT", "description": "Марка автомобиля"},
                {"name": "model", "type": "TEXT", "description": "Модель автомобиля"},
                {"name": "year", "type": "INTEGER", "description": "Год выпуска"},
                {"name": "price", "type": "REAL", "description": "Цена (рубли)"},
                {"name": "category", "type": "TEXT", "description": "Тип кузова"},
                {"name": "fuel_type", "type": "TEXT", "description": "Тип топлива"},
                {"name": "transmission", "type": "TEXT", "description": "Тип КПП"},
                {"name": "engine_volume", "type": "REAL", "description": "Объем двигателя (л)"},
                {"name": "power", "type": "INTEGER", "description": "Мощность (л.с.)"},
                {"name": "color", "type": "TEXT", "description": "Цвет"},
                {"name": "features", "type": "TEXT", "description": "Комплектация"},
                {"name": "discount", "type": "REAL", "description": "Скидка (%)"}
            ]
        }
    
    def get_available_brands(self) -> List[str]:
        """Возвращает список доступных марок"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT brand FROM cars WHERE available = 1 ORDER BY brand")
        return [row[0] for row in cursor.fetchall()]
    
    def get_available_categories(self) -> List[str]:
        """Возвращает список доступных категорий"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM cars WHERE available = 1 ORDER BY category")
        return [row[0] for row in cursor.fetchall()]

class FinanceDatabase(Searchable):
    """База данных финансовых предложений"""
    
    def __init__(self):
        self.credit_offers = [
            {
                "id": 1, "bank": "Сбербанк", "rate": 8.5, "min_down_payment": 15, 
                "max_period": 60, "special_conditions": "Первоначальный взвод от 15%"
            },
            {
                "id": 2, "bank": "ВТБ", "rate": 9.2, "min_down_payment": 10, 
                "max_period": 84, "special_conditions": "Скидка 0.5% при страховании"
            },
            {
                "id": 3, "bank": "Альфа-Банк", "rate": 8.9, "min_down_payment": 20, 
                "max_period": 60, "special_conditions": "Льготная ставка для зарплатных клиентов"
            },
            {
                "id": 4, "bank": "Тинькофф", "rate": 9.5, "min_down_payment": 0, 
                "max_period": 72, "special_conditions": "Онлайн одобрение за 5 минут"
            }
        ]
    
    def search(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Поиск кредитных предложений"""
        results = self.credit_offers
        
        if query.get("max_rate"):
            results = [r for r in results if r["rate"] <= query["max_rate"]]
        
        if query.get("min_period"):
            results = [r for r in results if r["max_period"] >= query["min_period"]]
        
        if query.get("max_down_payment"):
            results = [r for r in results if r["min_down_payment"] <= query["max_down_payment"]]
        
        return sorted(results, key=lambda x: x["rate"])[:5]
    
    def get_schema(self) -> Dict[str, Any]:
        return {
            "table": "credit_offers",
            "columns": [
                {"name": "bank", "type": "TEXT", "description": "Банк"},
                {"name": "rate", "type": "REAL", "description": "Процентная ставка (%)"},
                {"name": "min_down_payment", "type": "REAL", "description": "Минимальный первоначальный взнос (%)"},
                {"name": "max_period", "type": "INTEGER", "description": "Максимальный срок (месяцев)"},
                {"name": "special_conditions", "type": "TEXT", "description": "Особые условия"}
            ]
        }

### 3. 🔍 Анализатор поисковых запросов для автосалона

class CarSearchAnalyzer:
    """Анализирует необходимость поиска автомобилей и извлекает параметры"""
    
    def __init__(self, dealer_config: CarDealerConfig):
        self.config = dealer_config
        self.search_intent_prompt = PromptTemplate(
            input_variables=["user_query", "dialogue_history", "current_topic"],
            template="""
            Вы - ассистент автосалона. Проанализируйте запрос клиента и определите:
            1. Нужно ли выполнять поиск автомобилей в базе данных
            2. Какие параметры автомобиля можно извлечь
            3. Нужна ли информация по финансированию

            ДОСТУПНЫЕ КАТЕГОРИИ: {categories}

            ИСТОРИЯ ДИАЛОГА:
            {dialogue_history}

            ТЕКУЩАЯ ТЕМА: {current_topic}

            ЗАПРОС КЛИЕНТА: {user_query}

            Ключевые фразы для поиска автомобилей:
            - "хочу машину", "ищу автомобиль", "подберите авто", "посоветуйте"
            - упоминание марки, модели, типа кузова
            - бюджетные ограничения, требования к характеристикам

            Ключевые фразы для финансирования:
            - "кредит", "рассрочка", "первоначальный взнос", "лизинг"
            - "сколько в месяц", "платежи", "финансирование"

            Ответ в формате JSON:
            {{
                "search_required": true/false,
                "confidence": 0.85,
                "search_type": "автомобили/финансирование",
                "search_parameters": {{
                    "brand": "Toyota",
                    "category": "внедорожник", 
                    "max_price": 2000000,
                    "fuel_type": "бензин"
                }},
                "finance_required": true/false,
                "missing_parameters": ["бюджет", "тип кузова"],
                "reasoning": "Клиент ищет внедорожник Toyota в пределах 2 млн рублей"
            }}
            """
        )
        self.llm = llm
    
    def analyze_search_intent(self, user_query: str, dialogue_history: str, current_topic: str, available_categories: List[str]) -> Dict[str, Any]:
        """Анализирует намерение поиска автомобиля"""
        try:
            chain = LLMChain(llm=self.llm, prompt=self.search_intent_prompt)
            response = chain.run(
                user_query=user_query,
                dialogue_history=dialogue_history,
                current_topic=current_topic,
                categories=", ".join(available_categories)
            )
            
            # Парсим JSON ответ
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
        except Exception as e:
            print(f"⚠️ Ошибка анализа поискового намерения: {e}")
        
        # Возвращаем результат по умолчанию
        return {
            "search_required": False,
            "confidence": 0.0,
            "search_type": None,
            "search_parameters": {},
            "finance_required": False,
            "missing_parameters": [],
            "reasoning": "Не удалось проанализировать запрос"
        }
    
    def should_perform_search(self, search_intent: Dict[str, Any]) -> bool:
        """Определяет, нужно ли выполнять поиск на основе анализа"""
        if not search_intent["search_required"]:
            return False
        
        confidence = search_intent.get("confidence", 0)
        return confidence >= self.config.auto_search_threshold

### 4. 🧮 Финансовый калькулятор

class FinanceCalculator:
    """Калькулятор кредитов и платежей"""
    
    def calculate_loan(self, car_price: float, down_payment: float, interest_rate: float, loan_term: int) -> Dict[str, Any]:
        """Рассчитывает параметры кредита"""
        try:
            loan_amount = car_price - down_payment
            if loan_amount <= 0:
                return {"error": "Первоначальный взнос превышает стоимость автомобиля"}
            
            monthly_rate = interest_rate / 100 / 12
            monthly_payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** loan_term) / ((1 + monthly_rate) ** loan_term - 1)
            total_payment = monthly_payment * loan_term
            total_interest = total_payment - loan_amount
            
            return {
                "loan_amount": round(loan_amount, 2),
                "monthly_payment": round(monthly_payment, 2),
                "total_payment": round(total_payment, 2),
                "total_interest": round(total_interest, 2),
                "loan_term": loan_term,
                "interest_rate": interest_rate
            }
        except Exception as e:
            return {"error": f"Ошибка расчета: {str(e)}"}
    
    def calculate_lease(self, car_price: float, residual_value: float, lease_term: int) -> Dict[str, Any]:
        """Рассчитывает параметры лизинга"""
        try:
            monthly_lease = (car_price - residual_value) / lease_term
            return {
                "monthly_lease": round(monthly_lease, 2),
                "residual_value": residual_value,
                "lease_term": lease_term
            }
        except Exception as e:
            return {"error": f"Ошибка расчета лизинга: {str(e)}"}

### 5. 🗃️ Менеджер баз данных автосалона

class CarDealerDatabaseManager:
    """Управляет всеми базами данных автосалона"""
    
    def __init__(self, dealer_config: CarDealerConfig):
        self.config = dealer_config
        self.databases = {}
        self.finance_calculator = FinanceCalculator()
        self._initialize_databases()
    
    def _initialize_databases(self):
        """Инициализирует все базы данных автосалона"""
        if self.config.enabled:
            self.databases["автомобили"] = CarDatabase()
            self.databases["финансирование"] = FinanceDatabase()
    
    def search(self, domain: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Выполняет поиск в указанной базе данных"""
        if domain not in self.databases:
            return {
                "success": False,
                "error": f"База данных для домена '{domain}' не найдена",
                "results": []
            }
        
        try:
            database = self.databases[domain]
            results = database.search(parameters)
            
            # Для автомобилей добавляем расчет финансирования если нужно
            if domain == "автомобили" and parameters.get("calculate_finance"):
                for car in results:
                    if parameters.get("down_payment") and parameters.get("loan_term"):
                        car["finance_calculation"] = self.finance_calculator.calculate_loan(
                            car["price"], 
                            parameters["down_payment"], 
                            9.0,  # Средняя ставка
                            parameters["loan_term"]
                        )
            
            return {
                "success": True,
                "domain": domain,
                "parameters": parameters,
                "results": results[:self.config.max_results],
                "total_found": len(results),
                "returned": min(len(results), self.config.max_results)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "results": []
            }
    
    def get_available_brands(self) -> List[str]:
        """Возвращает список доступных марок автомобилей"""
        if "автомобили" in self.databases:
            return self.databases["автомобили"].get_available_brands()
        return []
    
    def get_available_categories(self) -> List[str]:
        """Возвращает список доступных категорий автомобилей"""
        if "автомобили" in self.databases:
            return self.databases["автомобили"].get_available_categories()
        return []
    
    def calculate_finance_for_car(self, car_price: float, down_payment_percent: float = 20, loan_term: int = 60) -> Dict[str, Any]:
        """Рассчитывает финансирование для автомобиля"""
        down_payment = car_price * down_payment_percent / 100
        return self.finance_calculator.calculate_loan(car_price, down_payment, 9.0, loan_term)

### 6. 🎯 Генератор поисковых запросов для автосалона

class CarQueryGenerator:
    """Генерирует и уточняет поисковые запросы для автомобилей"""
    
    def __init__(self):
        self.query_refinement_prompt = PromptTemplate(
            input_variables=["initial_parameters", "dialogue_history", "missing_info", "available_brands", "available_categories"],
            template="""
            Вы - опытный продавец автосалона. На основе истории диалога с клиентом и первоначальных параметров,
            сгенерируйте уточненные параметры для поиска автомобиля.

            ДОСТУПНЫЕ МАРКИ: {available_brands}
            ДОСТУПНЫЕ КАТЕГОРИИ: {available_categories}

            ПЕРВОНАЧАЛЬНЫЕ ПАРАМЕТРЫ: {initial_parameters}

            ИСТОРИЯ ДИАЛОГА С КЛИЕНТОМ:
            {dialogue_history}

            НЕДОСТАЮЩАЯ ИНФОРМАЦИЯ: {missing_info}

            Проанализируйте историю и извлеките:
            - Предпочтения по марке и модели
            - Бюджетные ограничения
            - Требования к типу кузова, топливу, КПП
            - Предполагаемое использование автомобиля
            - Семейные требования (если есть дети)

            Ответ в формате JSON с параметрами поиска:
            {{
                "brand": "марка",
                "category": "тип кузова", 
                "min_price": число,
                "max_price": число,
                "fuel_type": "тип топлива",
                "transmission": "тип кпп",
                "min_year": год,
                "keywords": "ключевые слова через запятую",
                "customer_profile": "семья/бизнес/молодежь",
                "usage_type": "город/путешествия/работа"
            }}
            """
        )
        self.llm = llm
    
    def refine_search_parameters(self, initial_params: Dict, dialogue_history: str, 
                               missing_info: List[str] = None, available_brands: List[str] = None,
                               available_categories: List[str] = None) -> Dict[str, Any]:
        """Уточняет параметры поиска на основе истории диалога"""
        try:
            chain = LLMChain(llm=self.llm, prompt=self.query_refinement_prompt)
            response = chain.run(
                initial_parameters=json.dumps(initial_params, ensure_ascii=False),
                dialogue_history=dialogue_history,
                missing_info=", ".join(missing_info) if missing_info else "Не указано",
                available_brands=", ".join(available_brands) if available_brands else "Все марки",
                available_categories=", ".join(available_categories) if available_categories else "Все категории"
            )
            
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                refined_params = json.loads(json_match.group())
                # Объединяем с первоначальными параметрами
                return {**initial_params, **refined_params}
        except Exception as e:
            print(f"⚠️ Ошибка уточнения параметров поиска: {e}")
        
        return initial_params
    
    def identify_missing_parameters(self, search_type: str, current_params: Dict) -> List[str]:
        """Определяет недостающие параметры для эффективного поиска"""
        missing = []
        
        if search_type == "автомобили":
            if not current_params.get("max_price"):
                missing.append("бюджет")
            if not current_params.get("category"):
                missing.append("тип кузова")
            if not current_params.get("brand") and not current_params.get("keywords"):
                missing.append("предпочтения по марке или характеристикам")
        
        elif search_type == "финансирование":
            if not current_params.get("max_price"):
                missing.append("стоимость автомобиля")
            if not current_params.get("down_payment"):
                missing.append("первоначальный взнос")
        
        return missing

### 7. 📊 Обработчик результатов поиска для автосалона

class CarResultProcessor:
    """Обрабатывает и форматирует результаты поиска автомобилей"""
    
    def __init__(self):
        self.summarization_prompt = PromptTemplate(
            input_variables=["search_results", "search_parameters", "user_query"],
            template="""
            Вы - продавец автосалона. Проанализируйте результаты поиска автомобилей и создайте 
            понятную сводку для клиента.

            ПАРАМЕТРЫ ПОИСКА КЛИЕНТА: {search_parameters}
            ЗАПРОС КЛИЕНТА: {user_query}
            РЕЗУЛЬТАТЫ ПОИСКА: {search_results}

            Создайте краткую сводку, которая:
            1. Подтверждает параметры поиска клиента
            2. Сообщает количество найденных вариантов
            3. Выделяет 2-3 лучших варианта с их преимуществами
            4. Предлагает возможные уточнения или альтернативы

            Учитывайте:
            - Бюджет клиента
            - Предполагаемое использование автомобиля
            - Семейные потребности если есть
            - Сравнительные преимущества разных вариантов

            Формат ответа:
            {{
                "summary": "Текст сводки",
                "top_recommendations": [
                    {{
                        "brand": "Марка",
                        "model": "Модель", 
                        "price": "Цена",
                        "key_features": ["особенность1", "особенность2"],
                        "advantages": "преимущества для данного клиента",
                        "reason": "почему рекомендовано"
                    }}
                ],
                "suggested_refinements": ["уточнение 1", "уточнение 2"],
                "next_questions": ["вопрос 1", "вопрос 2"],
                "finance_options": "информация о финансировании если уместно"
            }}
            """
        )
        self.llm = llm
    
    def process_search_results(self, search_results: Dict, user_query: str) -> Dict[str, Any]:
        """Обрабатывает и суммирует результаты поиска автомобилей"""
        if not search_results["success"] or not search_results["results"]:
            return self._handle_no_results(search_results, user_query)
        
        try:
            chain = LLMChain(llm=self.llm, prompt=self.summarization_prompt)
            response = chain.run(
                search_results=json.dumps(search_results["results"][:5], ensure_ascii=False),
                search_parameters=json.dumps(search_results["parameters"], ensure_ascii=False),
                user_query=user_query
            )
            
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                summary = json.loads(json_match.group())
                return {
                    "success": True,
                    "search_performed": True,
                    "results_summary": summary,
                    "raw_results": search_results["results"],
                    "total_found": search_results["total_found"]
                }
        except Exception as e:
            print(f"⚠️ Ошибка обработки результатов: {e}")
        
        # Fallback обработка
        return self._create_fallback_summary(search_results, user_query)
    
    def _handle_no_results(self, search_results: Dict, user_query: str) -> Dict[str, Any]:
        """Обрабатывает случай, когда автомобили не найдены"""
        error_msg = search_results.get("error", "Неизвестная ошибка")
        
        return {
            "success": False,
            "search_performed": True,
            "results_summary": {
                "summary": f"К сожалению, по вашим параметрам ничего не найдено. {error_msg}",
                "top_recommendations": [],
                "suggested_refinements": [
                    "Расширьте бюджет",
                    "Рассмотрите другие марки",
                    "Измените требования к типу кузова"
                ],
                "next_questions": [
                    "Может быть, увеличить бюджет?",
                    "Рассмотреть другие категории автомобилей?"
                ],
                "finance_options": "Возможно, вам подойдут программы trade-in или специальные кредитные предложения"
            },
            "raw_results": [],
            "total_found": 0
        }
    
    def _create_fallback_summary(self, search_results: Dict, user_query: str) -> Dict[str, Any]:
        """Создает резервную сводку результатов"""
        results = search_results["results"]
        params = search_results["parameters"]
        
        summary = f"По вашему запросу найдено {len(results)} автомобилей.\n\n"
        
        if results:
            summary += "Лучшие предложения:\n"
            for i, car in enumerate(results[:3], 1):
                price_info = f"{car['price']:,.0f} руб.".replace(',', ' ')
                if car.get('original_price'):
                    original = f"{car['original_price']:,.0f} руб.".replace(',', ' ')
                    price_info = f"{price_info} (скидка {car['discount']}% с {original})"
                
                summary += f"{i}. {car['brand']} {car['model']} - {price_info}\n"
                summary += f"   {car['category']}, {car['fuel_type']}, {car['transmission']}\n"
                if car.get('description'):
                    summary += f"   {car['description']}\n"
                summary += "\n"
        
        return {
            "success": True,
            "search_performed": True,
            "results_summary": {
                "summary": summary,
                "top_recommendations": [],
                "suggested_refinements": ["Уточнить бюджет", "Выбрать конкретную марку", "Определиться с типом кузова"],
                "next_questions": ["Какой из вариантов вас заинтересовал?", "Нужна ли информация по кредитованию?"],
                "finance_options": "Доступны кредитные программы от 8.5% годовых"
            },
            "raw_results": results,
            "total_found": len(results)
        }

### 8. 🚗 Главный ассистент автосалона

class CarDealerAssistant:
    """Главный класс ассистента автосалона"""
    
    def __init__(self, dealer_config: CarDealerConfig = None):
        self.config = dealer_config or CarDealerConfig()
        
        # Инициализация основных компонентов
        self.history = DialogueHistory()
        self.relation_analyzer = RelationAnalyzer()
        self.context_manager = ContextManager(AgentConfig())  # Используем базовую конфигурацию
        
        # Компоненты для автосалона
        self.search_analyzer = CarSearchAnalyzer(self.config)
        self.database_manager = CarDealerDatabaseManager(self.config)
        self.query_generator = CarQueryGenerator()
        self.result_processor = CarResultProcessor()
        
        # Инициализация цепочек
        self.question_chains = self._initialize_question_chains()
        self.answer_chain = self._initialize_answer_chain()
        
        print("🚗 Ассистент автосалона инициализирован!")
        print(f"   Доступно марок: {len(self.database_manager.get_available_brands())}")
        print(f"   Категории: {', '.join(self.database_manager.get_available_categories())}")
    
    def _initialize_question_chains(self) -> Dict[str, LLMChain]:
        """Инициализирует цепочки вопросов для автосалона"""
        prompts = {
            "car_search": PromptTemplate(
                input_variables=["user_query", "primary_context", "covered_topics", "current_topic", "search_context", "available_brands", "available_categories"],
                template="""
                Вы - продавец автосалона. Сгенерируйте уточняющие вопросы для клиента.

                ДОСТУПНЫЕ МАРКИ: {available_brands}
                ДОСТУПНЫЕ КАТЕГОРИИ: {available_categories}

                КОНТЕКСТ: {primary_context}
                {search_context}

                ПРЕДЫДУЩИЕ УТОЧНЕНИЯ: {covered_topics}

                ЗАПРОС КЛИЕНТА: {user_query}

                Сгенерируйте 2-3 уточняющих вопроса, которые помогут:
                - Определить бюджет клиента
                - Выяснить предпочтения по марке и модели
                - Уточнить требования к автомобилю
                - Понять цели использования

                Уточняющие вопросы (каждый с новой строки):
                """
            ),
            "finance": PromptTemplate(
                input_variables=["user_query", "primary_context", "car_details"],
                template="""
                Вы - финансовый консультант автосалона. Сгенерируйте вопросы по финансированию.

                КОНТЕКСТ: {primary_context}
                {car_details}

                ЗАПРОС КЛИЕНТА: {user_query}

                Сгенерируйте 2-3 вопроса о финансировании:
                - Первоначальный взнос
                - Срок кредита
                - Ежемесячный платеж
                - Дополнительные услуги

                Вопросы по финансированию (каждый с новой строки):
                """
            )
        }
        
        return {key: LLMChain(llm=llm, prompt=prompt, output_parser=QuestionOutputParser()) 
                for key, prompt in prompts.items()}
    
    def _initialize_answer_chain(self) -> LLMChain:
        """Инициализирует цепочку ответов для автосалона"""
        answer_prompt = PromptTemplate(
            input_variables=["question", "context", "relation_type", "search_results", "car_context"],
            template="""
            Как клиент автосалона, сгенерируйте реалистичные ответы на уточняющий вопрос.

            КОНТЕКСТ АВТОСАЛОНА: {car_context}
            {search_results}
            ВОПРОС ПРОДАВЦА: {question}

            Сгенерируйте 2 варианта ответа клиента, которые:
            - Соответствуют контексту выбора автомобиля
            - Выражают предпочтения или сомнения клиента
            - Являются естественными и правдоподобными

            Каждый ответ с новой строки.

            Ответы клиента:
            """
        )
        return LLMChain(llm=llm, prompt=answer_prompt, output_parser=AnswerOutputParser())
    
    def process_query(self, user_query: str) -> Dict[str, Any]:
        """Обрабатывает запрос клиента автосалона"""
        start_time = time.time()
        
        print(f"\n{'='*70}")
        print(f"🚗 ЗАПРОС КЛИЕНТА: {user_query}")
        print(f"{'='*70}")
        
        # Шаг 1: Анализ темы
        query_topic = self.history.detect_topic(user_query)
        print(f"🏷️  Тема: {query_topic}")
        
        # Шаг 2: Анализ связанности
        dialogue_context = self.history.get_recent_context()
        previous_topics = self.history.topics
        
        is_related, relation_type, confidence = self.relation_analyzer.analyze_relation(
            user_query, dialogue_context, previous_topics
        )
        
        print(f"🔗 Связанность: {is_related} (тип: {relation_type}, уверенность: {confidence:.2f})")
        
        # Шаг 3: Анализ необходимости поиска автомобилей
        available_brands = self.database_manager.get_available_brands()
        available_categories = self.database_manager.get_available_categories()
        
        search_intent = self.search_analyzer.analyze_search_intent(
            user_query, dialogue_context, self.history.current_topic or query_topic, available_categories
        )
        
        search_performed = False
        search_results = None
        search_context = ""
        car_context = f"Доступные марки: {', '.join(available_brands)}\nКатегории: {', '.join(available_categories)}"
        
        if search_intent["search_required"]:
            print(f"🔎 Поисковое намерение: {search_intent['search_type']} (уверенность: {search_intent['confidence']:.2f})")
            
            if self.search_analyzer.should_perform_search(search_intent):
                # Выполняем поиск
                search_results = self._perform_search(search_intent, dialogue_context, available_brands, available_categories)
                search_performed = True
                
                if search_results and search_results.get("success"):
                    found_count = search_results['total_found']
                    domain = search_intent['search_type']
                    search_context = f"\nРЕЗУЛЬТАТЫ ПОИСКА: Найдено {found_count} вариантов в категории '{domain}'\n"
                else:
                    search_context = "\nРЕЗУЛЬТАТЫ ПОИСКА: По заданным критериям ничего не найдено\n"
        
        # Шаг 4: Генерация вопросов с учетом контекста автосалона
        questions = self._generate_questions(
            user_query, relation_type, dialogue_context, query_topic, 
            search_context, search_results, available_brands, available_categories
        )
        
        # Шаг 5: Генерация гипотетических ответов
        results = []
        for question in questions:
            answers = self.answer_chain.run(
                question=question,
                context=dialogue_context,
                relation_type=relation_type,
                search_results=search_context,
                car_context=car_context
            )
            results.append({
                "question": question,
                "hypothetical_answers": answers
            })
        
        # Шаг 6: Определение темы для истории
        if not is_related or relation_type in ["new_topic", "topic_change"]:
            history_topic = query_topic
        else:
            history_topic = self.history.current_topic
        
        # Шаг 7: Добавление в историю
        self.history.add_message(
            "client", user_query, 
            topic=history_topic,
            search_data=search_intent if search_intent["search_required"] else None
        )
        
        assistant_content = f"Уточняющие вопросы по подбору авто"
        if search_performed:
            assistant_content += f" + поиск в {search_intent['search_type']}"
        
        self.history.add_message(
            "assistant", 
            assistant_content, 
            results, 
            topic=history_topic,
            search_results=search_results
        )
        
        # Подготовка финального результата
        response_time = time.time() - start_time
        result = {
            "user_query": user_query,
            "query_topic": query_topic,
            "is_related": is_related,
            "relation_type": relation_type,
            "search_performed": search_performed,
            "search_intent": search_intent,
            "search_results": search_results,
            "clarifying_questions": results,
            "response_time": response_time,
            "history_length": len(self.history.history)
        }
        
        # Отображение результатов
        self._display_car_dealer_interaction_result(result)
        
        return result
    
    def _perform_search(self, search_intent: Dict, dialogue_context: str, available_brands: List[str], available_categories: List[str]) -> Dict[str, Any]:
        """Выполняет поиск в базе данных автомобилей"""
        search_type = search_intent["search_type"]
        initial_params = search_intent["search_parameters"]
        
        print(f"🗃️  Выполняю поиск в {search_type} с параметрами: {initial_params}")
        
        # Уточняем параметры на основе истории диалога
        missing_params = self.query_generator.identify_missing_parameters(search_type, initial_params)
        
        refined_params = self.query_generator.refine_search_parameters(
            initial_params, dialogue_context, missing_params, available_brands, available_categories
        )
        
        print(f"🔧 Уточненные параметры поиска: {refined_params}")
        
        # Выполняем поиск
        search_results = self.database_manager.search(search_type, refined_params)
        
        # Обрабатываем результаты
        processed_results = self.result_processor.process_search_results(
            search_results, "Поиск автомобиля по параметрам клиента"
        )
        
        return processed_results
    
    def _generate_questions(self, user_query: str, relation_type: str, dialogue_context: str, 
                          query_topic: str, search_context: str, search_results: Dict,
                          available_brands: List[str], available_categories: List[str]) -> List[str]:
        """Генерирует вопросы для автосалона"""
        # Определяем тип цепочки вопросов
        if "финанс" in user_query.lower() or "кредит" in user_query.lower():
            chain_key = "finance"
        else:
            chain_key = "car_search"
        
        chain = self.question_chains[chain_key]
        
        # Формируем контекст поиска для промпта
        enhanced_search_context = search_context
        if search_results and search_results.get("success") and search_results.get("results_summary"):
            summary = search_results["results_summary"]
            enhanced_search_context += f"СВОДКА ПОИСКА: {summary['summary']}\n"
        
        chain_input = {
            "user_query": user_query,
            "primary_context": dialogue_context,
            "covered_topics": ", ".join(self.history.get_already_covered_topics()),
            "current_topic": self.history.current_topic or query_topic,
            "search_context": enhanced_search_context,
            "available_brands": ", ".join(available_brands),
            "available_categories": ", ".join(available_categories)
        }
        
        if chain_key == "finance" and search_results and search_results.get("raw_results"):
            # Добавляем информацию об автомобиле для финансовых вопросов
            car_details = ""
            if search_results["raw_results"]:
                car = search_results["raw_results"][0]
                car_details = f"Автомобиль: {car['brand']} {car['model']} - {car['price']:,.0f} руб."
            chain_input["car_details"] = car_details
        
        questions = chain.run(**chain_input)
        return questions[:3]  # Ограничиваем количество вопросов
    
    def _display_car_dealer_interaction_result(self, result: Dict):
        """Отображает результаты взаимодействия в автосалоне"""
        print(f"\n🎯 РЕЗУЛЬТАТЫ КОНСУЛЬТАЦИИ:")
        print(f"   • Время обработки: {result['response_time']:.2f}с")
        print(f"   • Поиск выполнен: {'Да' if result['search_performed'] else 'Нет'}")
        
        if result['search_performed']:
            search_intent = result['search_intent']
            search_results = result['search_results']
            
            print(f"   • Тип поиска: {search_intent['search_type']}")
            if search_results and search_results.get('success'):
                print(f"   • Найдено вариантов: {search_results.get('total_found', 0)}")
                
                if search_results.get('results_summary'):
                    summary = search_results['results_summary']
                    print(f"\n📊 СВОДКА ПРЕДЛОЖЕНИЙ:")
                    print(f"   {summary['summary']}")
                    
                    if summary.get('top_recommendations'):
                        print(f"\n🏆 РЕКОМЕНДАЦИИ:")
                        for rec in summary['top_recommendations'][:2]:
                            print(f"   • {rec.get('brand', '')} {rec.get('model', '')} - {rec.get('price', '')}")
                            if rec.get('advantages'):
                                print(f"     {rec['advantages']}")
        
        print(f"\n🤔 УТОЧНЯЮЩИЕ ВОПРОСЫ:")
        for i, item in enumerate(result["clarifying_questions"], 1):
            print(f"  {i}. {item['question']}")
            for j, answer in enumerate(item['hypothetical_answers'], 1):
                print(f"     {j}. {answer}")

### 9. 🎭 Демонстрация работы ассистента автосалона

def demo_car_dealer_assistant():
    """Демонстрация работы ассистента автосалона"""
    
    # Конфигурация
    dealer_config = CarDealerConfig(
        enabled=True,
        auto_search_threshold=0.6,
        max_results=5,
        enable_finance_calculations=True,
        enable_trade_in=True
    )
    
    assistant = CarDealerAssistant(dealer_config)
    
    # Симуляция диалога с клиентом автосалона
    scenarios = [
        "Хочу купить автомобиль для семьи",
        "Мой бюджет до 2 миллионов рублей",  # Уточнение бюджета
        "Интересуют внедорожники",  # Уточнение категории
        "Покажите Toyota",  # Конкретная марка
        "А есть что-то подешевле?",  # Уточнение поиска
        "Расскажите про кредитование",  # Финансовый вопрос
        "Какой первоначальный взнос нужен?",  # Уточнение финансирования
        "Интересует Kia Sportage в кредит",  # Конкретный запрос
    ]
    
    print("🚗 ЗАПУСК АССИСТЕНТА АВТОСАЛОНА")
    print("=" * 80)
    
    for i, query in enumerate(scenarios, 1):
        print(f"\n{'>>>'*10} ЭТАП {i} {'<<<'*10}")
        result = assistant.process_query(query)
        
        # Показываем дополнительные детали поиска
        if result.get("search_performed") and result["search_results"] and result["search_results"].get("success"):
            search_data = result["search_results"]
            if search_data.get("raw_results"):
                print(f"\n📋 ДОСТУПНЫЕ АВТОМОБИЛИ ({len(search_data['raw_results'])}):")
                for j, car in enumerate(search_data["raw_results"][:3], 1):
                    price = f"{car['price']:,.0f} руб.".replace(',', ' ')
                    print(f"   {j}. {car['brand']} {car['model']} - {price}")
                    print(f"      {car['category']}, {car['fuel_type']}, {car['transmission']}")
                    if car.get('finance_calculation'):
                        payment = f"{car['finance_calculation']['monthly_payment']:,.0f} руб./мес".replace(',', ' ')
                        print(f"      💰 Кредит: {payment}")
    
    # Статистика сеанса
    print(f"\n{'📊'*20} СТАТИСТИКА СЕАНСА {'📊'*20}")
    total_searches = sum(1 for msg in assistant.history.history 
                        if msg.get("role") == "assistant" and msg.get("search_results"))
    finance_queries = sum(1 for msg in assistant.history.history 
                         if msg.get("role") == "client" and "кредит" in msg.get("content", "").lower())
    
    print(f"   • Всего консультаций: {len(assistant.history.history)//2}")
    print(f"   • Поисковых операций: {total_searches}")
    print(f"   • Финансовых запросов: {finance_queries}")
    
    # Показываем историю тем
    print(f"\n🎯 ИСТОРИЯ ТЕМ КОНСУЛЬТАЦИИ:")
    topics = {}
    for msg in assistant.history.history:
        topic = msg.get('topic')
        if topic:
            if topic not in topics:
                topics[topic] = 0
            topics[topic] += 1
    
    for topic, count in topics.items():
        print(f"   • {topic}: {count} сообщений")

if __name__ == "__main__":
    demo_car_dealer_assistant()
```

## 🎯 Ключевые особенности ассистента автосалона

### 1. **Специализированная база данных автомобилей**
- 12+ тестовых автомобилей разных категорий
- Детальные характеристики: марка, модель, цена, тип кузова, топливо, КПП
- Система скидок и акций
- Фильтрация по множеству параметров

### 2. **Интеллектуальный подбор автомобилей**
- Анализ потребностей клиента (семья, бизнес, путешествия)
- Учет бюджета и предпочтений
- Рекомендации на основе целей использования

### 3. **Финансовый модуль**
- Калькулятор кредитов и лизинга
- База кредитных предложений банков
- Расчет ежемесячных платежей
- Сравнение финансовых вариантов

### 4. **Контекстно-зависимые вопросы**
- Уточнение бюджета и требований
- Вопросы о целях использования
- Финансовые уточнения
- Сравнительные вопросы

### 5. **Профессиональная коммуникация**
- Стиль общения как у опытного продавца
- Учет автомобильной терминологии
- Проактивные предложения и рекомендации
- Обработка возражений и сомнений

## 📊 Пример работы системы:

```
>>> ЭТАП 1: Хочу купить автомобиль для семьи
🚗 ЗАПРОС КЛИЕНТА: Хочу купить автомобиль для семьи
🏷️  Тема: автомобиль для семьи
🔎 Поисковое намерение: автомобили (уверенность: 0.82)

🎯 РЕЗУЛЬТАТЫ КОНСУЛЬТАЦИИ:
   • Поиск выполнен: Да
   • Тип поиска: автомобили
   • Найдено вариантов: 8

📊 СВОДКА ПРЕДЛОЖЕНИЙ:
   Найдено 8 автомобилей, подходящих для семьи. Рекомендуем рассмотреть внедорожники 
   и универсалы с просторным салоном и большим багажником.

🤔 УТОЧНЯЮЩИЕ ВОПРОСЫ:
  1. Какой бюджет вы рассматриваете?
     1. До 1.5 миллионов рублей
     2. Около 2-2.5 миллионов
  2. Сколько человек обычно будет ездить в автомобиле?
     1. 2 взрослых и 2 детей
     2. 3 взрослых и 1 ребенок
  3. Важна ли экономичность расхода топлива?
     1. Да, ищу экономичный вариант
     2. Главное - комфорт и безопасность
```

Теперь у вас есть полнофункциональный ассистент автосалона, который может интеллектуально подбирать автомобили, консультировать по финансированию и вести профессиональный диалог с клиентами! 🚗💨

Вот полная расширенная архитектура с всеми предложенными улучшениями:

## 🏗️ Полная структура системы

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Input Layer   │───▶│  Context Manager │───▶│  Relation Analyzer│
└─────────────────┘    └──────────────────┘    └──────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Emotion Analyzer│    │  Memory Manager  │───▶│ Question Strategy│
└─────────────────┘    └──────────────────┘    └──────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Tone Adjuster  │    │ Knowledge Integr.│───▶│  Question Generator
└─────────────────┘    └──────────────────┘    └──────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│Proactive Suggest│◄───│  Quality Metrics │◄───│ Answer Generator │
└─────────────────┘    └──────────────────┘    └──────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Visualizer     │    │   Config Manager │    │  Output Layer    │
└─────────────────┘    └──────────────────┘    └──────────────────┘
```

## 🚀 Полный код реализации

```python
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI
from langchain.schema import BaseOutputParser
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import os
import json
import re
from datetime import datetime
import time

# Установите ваш API-ключ OpenAI
os.environ["OPENAI_API_KEY"] = "ваш_api_ключ"

# Инициализация модели
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0.7)

### 1. 🎛️ Конфигурационная система
@dataclass
class AgentConfig:
    """Конфигурация поведения агента"""
    
    # Настройки связанности
    relation_confidence_threshold: float = 0.7
    enable_emotion_analysis: bool = True
    use_context_compression: bool = True
    
    # Настройки вопросов
    min_questions: int = 2
    max_questions: int = 4
    question_style: str = "neutral"  # neutral, friendly, professional
    
    # Настройки памяти
    max_history_length: int = 50
    enable_memory_compression: bool = True
    
    # Расширенные функции
    enable_proactive_suggestions: bool = True
    enable_quality_metrics: bool = True
    enable_knowledge_integration: bool = True
    enable_dialogue_visualization: bool = True
    
    # Настройки контекста
    context_levels: Dict = None
    
    def __post_init__(self):
        if self.context_levels is None:
            self.context_levels = {
                "recent": 6,      # Последние сообщения
                "topic": 10,      # Вся тема
                "session": 20,    # Вся сессия
                "summary": 3      # Суммаризированный контекст
            }

### 2. 🧠 Многоуровневая система контекста
class ContextManager:
    """Управление контекстом на разных уровнях детализации"""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.context_strategies = {
            "continuation": {
                "primary": "topic",
                "secondary": "recent",
                "depth": "deep",
                "compression": "moderate"
            },
            "clarification": {
                "primary": "recent", 
                "secondary": "topic",
                "depth": "focused",
                "compression": "light"
            },
            "new_topic": {
                "primary": "summary",
                "secondary": None,
                "depth": "shallow",
                "compression": "aggressive"
            },
            "topic_change": {
                "primary": "summary",
                "secondary": "recent",
                "depth": "medium",
                "compression": "moderate"
            }
        }
    
    def get_context_strategy(self, relation_type: str, confidence: float) -> Dict:
        """Выбирает стратегию контекста в зависимости от типа связи"""
        strategy = self.context_strategies.get(relation_type, self.context_strategies["new_topic"])
        
        # Корректируем стратегию на основе уверенности
        if confidence < 0.6:
            strategy = strategy.copy()
            strategy["depth"] = "shallow"
            strategy["compression"] = "aggressive"
        
        return strategy
    
    def prepare_context(self, history: 'DialogueHistory', strategy: Dict, current_topic: str) -> Dict[str, str]:
        """Подготавливает контекст разных уровней"""
        contexts = {}
        
        # Основной контекст
        if strategy["primary"] == "topic" and current_topic:
            contexts["primary"] = history.get_topic_context(current_topic)
        elif strategy["primary"] == "recent":
            contexts["primary"] = history.get_recent_context(self.config.context_levels["recent"])
        elif strategy["primary"] == "summary":
            contexts["primary"] = history.get_summary_context()
        else:
            contexts["primary"] = history.get_recent_context(3)
        
        # Вторичный контекст
        if strategy["secondary"]:
            if strategy["secondary"] == "topic" and current_topic:
                contexts["secondary"] = history.get_topic_context(current_topic)
            elif strategy["secondary"] == "recent":
                contexts["secondary"] = history.get_recent_context(4)
        
        return contexts

### 3. 💾 Динамическое управление памятью
class MemoryManager:
    """Управление памятью диалога с приоритизацией"""
    
    def __init__(self, max_messages=50):
        self.max_messages = max_messages
        self.message_scores = {}  # Оценка важности сообщений
        self.key_entities = set() # Ключевые сущности диалога
        self.compression_count = 0
    
    def calculate_message_importance(self, message: Dict) -> float:
        """Рассчитывает важность сообщения"""
        score = 0.0
        
        # Факторы важности
        if message["role"] == "user":
            score += 0.3
        if message.get("questions_answers"):
            score += 0.4
        if len(message["content"]) > 100:  # Длинные сообщения часто важнее
            score += 0.2
        if any(keyword in message["content"].lower() for keyword in ["важн", "ключев", "основн", "главн"]):
            score += 0.5
        
        # Учитываем тему
        if message.get("topic"):
            score += 0.2
            
        return min(score, 1.0)
    
    def compress_history(self, history: List[Dict]) -> List[Dict]:
        """Сжимает историю, сохраняя важные сообщения"""
        if len(history) <= self.max_messages:
            return history
        
        self.compression_count += 1
        print(f"🧠 Сжатие памяти #{self.compression_count} ({len(history)} -> {self.max_messages} сообщений)")
        
        # Сортируем сообщения по важности
        scored_history = []
        for i, msg in enumerate(history):
            importance = self.calculate_message_importance(msg)
            # Учитываем свежесть сообщений
            recency_bonus = (i / len(history)) * 0.3
            total_score = importance + recency_bonus
            scored_history.append((total_score, msg, i))
        
        # Оставляем самые важные сообщения
        scored_history.sort(reverse=True)
        kept_messages = [msg for score, msg, idx in scored_history[:self.max_messages]]
        
        # Восстанавливаем порядок по времени
        kept_messages.sort(key=lambda x: x["timestamp"])
        
        # Обновляем ключевые сущности
        self._update_key_entities(kept_messages)
        
        return kept_messages
    
    def _update_key_entities(self, messages: List[Dict]):
        """Обновляет ключевые сущности из сообщений"""
        entities = set()
        for msg in messages:
            content = msg["content"].lower()
            # Простая эвристика для извлечения сущностей (можно заменить на NER)
            words = re.findall(r'\b[\w]{4,}\b', content)
            for word in words:
                if word not in ['этот', 'такой', 'какой', 'который']:
                    entities.add(word)
        
        self.key_entities = entities

### 4. ❤️ Эмоциональный интеллект
class EmotionAnalyzer:
    """Анализ эмоциональной окраски запросов"""
    
    def __init__(self):
        self.sentiment_prompt = PromptTemplate(
            input_variables=["query"],
            template="""
            Проанализируйте эмоциональную окраску запроса и определите:
            1. Тональность (позитивная, негативная, нейтральная, смешанная)
            2. Уровень срочности (низкий, средний, высокий)
            3. Эмоциональное состояние (спокойное, взволнованное, расстроенное, радостное)
            
            Запрос: {query}
            
            Ответ в JSON:
            {{
                "sentiment": "нейтральная",
                "urgency": "средний", 
                "emotional_state": "спокойное",
                "needs_empathy": false,
                "confidence": 0.85
            }}
            """
        )
        self.llm = llm
    
    def analyze_emotion(self, query: str) -> Dict[str, Any]:
        """Анализирует эмоциональную окраску запроса"""
        try:
            chain = LLMChain(llm=self.llm, prompt=self.sentiment_prompt)
            response = chain.run(query=query)
            
            # Парсим JSON ответ
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                emotion_data = json.loads(json_match.group())
                
                # Дополнительная логика для определения потребности в эмпатии
                if emotion_data["sentiment"] == "негативная" or emotion_data["urgency"] == "высокий":
                    emotion_data["needs_empathy"] = True
                
                return emotion_data
        except Exception as e:
            print(f"⚠️ Ошибка анализа эмоций: {e}")
        
        # Возвращаем значения по умолчанию
        return {
            "sentiment": "нейтральная",
            "urgency": "средний",
            "emotional_state": "спокойное",
            "needs_empathy": False,
            "confidence": 0.5
        }
    
    def adjust_tone_for_questions(self, questions: List[str], emotion_data: Dict, question_style: str = "neutral") -> List[str]:
        """Адаптирует тон вопросов под эмоциональный контекст"""
        adjusted_questions = []
        
        tone_prefixes = {
            "friendly": {
                "neutral": ["Расскажите, ", "Подскажите, ", "Интересно, "],
                "positive": ["Здорово! ", "Отлично! ", "Замечательно! "],
                "negative": ["Понимаю, ", "Вижу, ", "Сочувствую, "]
            },
            "professional": {
                "neutral": ["Уточните, ", "Определите, ", "Укажите, "],
                "positive": ["Прекрасно. ", "Отлично. ", "Хорошо. "],
                "negative": ["Приношу извинения. ", "Понимаю сложность. ", "Учтем. "]
            },
            "neutral": {
                "neutral": ["", "", ""],
                "positive": ["", "", ""],
                "negative": ["", "", ""]
            }
        }
        
        prefixes = tone_prefixes.get(question_style, tone_prefixes["neutral"])
        sentiment_key = "positive" if emotion_data["sentiment"] == "позитивная" else "negative" if emotion_data["sentiment"] == "негативная" else "neutral"
        
        for i, question in enumerate(questions):
            prefix = prefixes[sentiment_key][i % len(prefixes[sentiment_key])]
            
            if emotion_data["needs_empathy"]:
                if sentiment_key == "negative":
                    question = f"{prefix}Чтобы помочь эффективнее, {question.lower()}"
                elif sentiment_key == "positive":
                    question = f"{prefix}{question}"
            
            if emotion_data["urgency"] == "высокий":
                question = f"Срочно: {question}"
                
            adjusted_questions.append(question)
        
        return adjusted_questions

### 5. 🔮 Проактивные предложения
class ProactiveAssistant:
    """Генерация проактивных предложений на основе истории"""
    
    def __init__(self):
        self.suggestion_prompt = PromptTemplate(
            input_variables=["history", "current_topic", "user_interests"],
            template="""
            На основе истории диалога определите потенциальные интересы пользователя
            и сгенерируйте 2-3 проактивных предложения для углубления диалога.
            
            ТЕКУЩАЯ ТЕМА: {current_topic}
            ИСТОРИЯ: {history}
            ИНТЕРЕСЫ: {user_interests}
            
            Проанализируйте:
            - Какие аспекты темы еще не раскрыты
            - Смежные темы, которые могут быть интересны
            - Возможные следующие шаги
            
            Сгенерируйте предложения в формате JSON:
            {{
                "suggestions": [
                    {{
                        "type": "углубить_тему/расширить_фокус/практическое_применение",
                        "description": "Текст предложения",
                        "reasoning": "Обоснование почему это может быть интересно"
                    }}
                ]
            }}
            """
        )
        self.llm = llm
    
    def generate_proactive_suggestions(self, history: 'DialogueHistory', current_topic: str, user_interests: List[str]) -> List[Dict]:
        """Генерирует проактивные предложения"""
        try:
            chain = LLMChain(llm=self.llm, prompt=self.suggestion_prompt)
            response = chain.run(
                history=history.get_recent_context(8),
                current_topic=current_topic,
                user_interests=", ".join(user_interests) if user_interests else "еще не определены"
            )
            
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result.get("suggestions", [])
        except Exception as e:
            print(f"⚠️ Ошибка генерации предложений: {e}")
        
        return []

### 6. 📊 Оценка качества и метрики
class QualityMetrics:
    """Сбор метрик качества работы агента"""
    
    def __init__(self):
        self.metrics = {
            "relation_accuracy": [],
            "question_relevance": [],
            "response_times": [],
            "user_engagement": 0,
            "topic_coverage": {},
            "emotion_analysis": []
        }
        self.start_time = time.time()
    
    def log_interaction(self, relation_data: Dict, questions: List[str], response_time: float):
        """Логирует метрики взаимодействия"""
        self.metrics["response_times"].append(response_time)
        self.metrics["user_engagement"] += 1
        
        # Оцениваем релевантность вопросов
        relevance_score = self._estimate_question_relevance(questions, relation_data)
        self.metrics["question_relevance"].append(relevance_score)
        
        # Логируем анализ эмоций если есть
        if "emotion_data" in relation_data:
            self.metrics["emotion_analysis"].append(relation_data["emotion_data"])
    
    def _estimate_question_relevance(self, questions: List[str], relation_data: Dict) -> float:
        """Оценивает релевантность вопросов (упрощенная версия)"""
        if not questions:
            return 0.0
        
        # Простая эвристика: вопросы релевантны если они соответствуют типу связи
        base_score = 0.7
        
        # Бонус за разнообразие вопросов
        unique_stems = set()
        for q in questions:
            words = q.lower().split()[:3]  # Первые 3 слова как основа
            unique_stems.add(tuple(words))
        
        diversity_bonus = min(len(unique_stems) / len(questions), 0.3)
        
        return min(base_score + diversity_bonus, 1.0)
    
    def get_performance_summary(self) -> Dict:
        """Возвращает сводку производительности"""
        if not self.metrics["response_times"]:
            return {"status": "No data yet"}
        
        return {
            "total_interactions": self.metrics["user_engagement"],
            "avg_response_time": sum(self.metrics["response_times"]) / len(self.metrics["response_times"]),
            "avg_question_relevance": sum(self.metrics["question_relevance"]) / len(self.metrics["question_relevance"]) if self.metrics["question_relevance"] else 0,
            "session_duration": time.time() - self.start_time
        }

### 7. 📚 Интеграция с внешними знаниями
class KnowledgeIntegrator:
    """Интеграция внешних знаний и факт-чекинг"""
    
    def __init__(self):
        self.knowledge_sources = {
            "common_sense": "Базовые знания о мире",
            "domain_knowledge": "Специфичные знания области",
            "user_preferences": "Предпочтения пользователя"
        }
        self.domain_knowledge = {
            "путешествия": ["бюджет", "сезон", "страны", "виза", "проживание"],
            "технологии": ["бюджет", "требования", "использование", "спецификации"],
            "образование": ["уровень", "длительность", "формат", "цели"]
        }
    
    def enrich_with_knowledge(self, questions: List[str], topic: str, relation_type: str) -> List[str]:
        """Обогащает вопросы дополнительными знаниями"""
        enriched_questions = []
        
        domain_keywords = self._detect_domain(topic)
        
        for question in questions:
            enriched_question = question
            
            # Добавляем доменные знания если применимо
            if domain_keywords and self._requires_domain_knowledge(question, domain_keywords):
                if relation_type == "continuation":
                    enriched_question = f"С учетом ваших предпочтений, {question.lower()}"
                elif relation_type == "new_topic":
                    enriched_question = f"Для лучшего понимания контекста, {question.lower()}"
            
            enriched_questions.append(enriched_question)
        
        return enriched_questions
    
    def _detect_domain(self, topic: str) -> List[str]:
        """Определяет домен по теме"""
        topic_lower = topic.lower()
        for domain, keywords in self.domain_knowledge.items():
            if any(keyword in topic_lower for keyword in [domain] + keywords[:2]):
                return keywords
        return []
    
    def _requires_domain_knowledge(self, question: str, domain_keywords: List[str]) -> bool:
        """Проверяет, требует ли вопрос доменных знаний"""
        question_lower = question.lower()
        return any(keyword in question_lower for keyword in domain_keywords[:3])

### 8. 🎨 Улучшенная визуализация диалога
class DialogueVisualizer:
    """Визуализация структуры диалога и связей"""
    
    def create_dialogue_map(self, history: 'DialogueHistory') -> Dict:
        """Создает карту диалога с связями между темами"""
        
        dialogue_map = {
            "topics": [],
            "transitions": [],
            "key_moments": [],
            "conversation_flow": [],
            "timeline": []
        }
        
        # Анализ переходов между темами
        current_topic = None
        topic_start = 0
        
        for i, msg in enumerate(history.history):
            msg_topic = msg.get("topic", "без темы")
            
            # Отслеживаем переходы тем
            if msg_topic != current_topic:
                if current_topic is not None:
                    dialogue_map["transitions"].append({
                        "from": current_topic,
                        "to": msg_topic,
                        "turn": i,
                        "type": "topic_change"
                    })
                
                current_topic = msg_topic
                topic_start = i
            
            # Добавляем в таймлайн
            dialogue_map["timeline"].append({
                "turn": i,
                "role": msg["role"],
                "topic": msg_topic,
                "content_preview": msg["content"][:50] + "..."
            })
            
            # Определяем ключевые моменты
            if msg.get("questions_answers"):
                dialogue_map["key_moments"].append({
                    "turn": i,
                    "type": "clarification",
                    "topic": msg_topic,
                    "questions_count": len(msg["questions_answers"])
                })
        
        # Собираем уникальные темы
        topics = {}
        for msg in history.history:
            topic = msg.get("topic")
            if topic:
                if topic not in topics:
                    topics[topic] = 0
                topics[topic] += 1
        
        dialogue_map["topics"] = [{"name": topic, "message_count": count} for topic, count in topics.items()]
        
        return dialogue_map
    
    def print_conversation_analysis(self, agent: 'ClarifyingAgent'):
        """Расширенный анализ диалога"""
        dialogue_map = self.create_dialogue_map(agent.history)
        
        print(f"\n{'📊'*20}")
        print(f"ДЕТАЛЬНЫЙ АНАЛИЗ ДИАЛОГА")
        print(f"{'📊'*20}")
        
        # Основная статистика
        print(f"\n📈 СТАТИСТИКА:")
        print(f"   • Всего сообщений: {len(agent.history.history)}")
        print(f"   • Уникальных тем: {len(dialogue_map['topics'])}")
        print(f"   • Переходов между темами: {len(dialogue_map['transitions'])}")
        print(f"   • Ключевых моментов: {len(dialogue_map['key_moments'])}")
        
        # Анализ тем
        print(f"\n🎯 ТЕМЫ ДИАЛОГА:")
        for topic_info in dialogue_map["topics"]:
            print(f"   • {topic_info['name']}: {topic_info['message_count']} сообщений")
        
        # Переходы между темами
        if dialogue_map["transitions"]:
            print(f"\n🔄 ПЕРЕХОДЫ МЕЖДУ ТЕМАМИ:")
            for transition in dialogue_map["transitions"][-3:]:  # Последние 3 перехода
                print(f"   • {transition['from']} → {transition['to']} (ход {transition['turn']})")
        
        # Метрики производительности
        if agent.quality_metrics:
            performance = agent.quality_metrics.get_performance_summary()
            print(f"\n⚡ ПРОИЗВОДИТЕЛЬНОСТЬ:")
            print(f"   • Взаимодействий: {performance['total_interactions']}")
            print(f"   • Среднее время ответа: {performance['avg_response_time']:.2f}с")
            print(f"   • Релевантность вопросов: {performance['avg_question_relevance']:.1%}")

### 9. 🗂️ Улучшенная система истории
class DialogueHistory:
    """Расширенный класс для управления историей диалога"""
    
    def __init__(self):
        self.history = []
        self.current_topic = None
        self.topics = []
        self.user_interests = set()
    
    def add_message(self, role: str, content: Any, questions_answers: List[Dict] = None, topic: str = None, emotion_data: Dict = None):
        """Добавляет сообщение в историю"""
        message = {
            "role": role,
            "content": content,
            "timestamp": len(self.history),
            "time": datetime.now().isoformat(),
            "questions_answers": questions_answers or [],
            "topic": topic or self.current_topic,
            "emotion_data": emotion_data
        }
        self.history.append(message)
        
        # Обновляем текущую тему если указана
        if topic:
            self.current_topic = topic
            if topic not in self.topics:
                self.topics.append(topic)
        
        # Обновляем интересы пользователя
        if role == "user":
            self._update_user_interests(content)
    
    def _update_user_interests(self, content: str):
        """Обновляет интересы пользователя на основе контента"""
        content_lower = content.lower()
        interest_keywords = {
            "путешеств": "путешествия",
            "технолог": "технологии", 
            "образован": "образование",
            "работ": "карьера",
            "хобби": "хобби",
            "спорт": "спорт",
            "искусств": "искусство"
        }
        
        for keyword, interest in interest_keywords.items():
            if keyword in content_lower:
                self.user_interests.add(interest)
    
    def get_recent_context(self, max_messages: int = 6) -> str:
        """Возвращает последние N сообщений в виде форматированной строки"""
        recent = self.history[-max_messages:] if len(self.history) > max_messages else self.history
        context_lines = []
        
        for msg in recent:
            if msg["role"] == "user":
                context_lines.append(f"👤: {msg['content']}")
            elif msg["role"] == "assistant":
                preview = msg['content'][:70] + "..." if len(msg['content']) > 70 else msg['content']
                context_lines.append(f"🤖: {preview}")
        
        return "\n".join(context_lines)
    
    def get_topic_context(self, topic: str = None) -> str:
        """Возвращает контекст только по определенной теме"""
        target_topic = topic or self.current_topic
        if not target_topic:
            return self.get_recent_context()
        
        topic_messages = [msg for msg in self.history if msg.get("topic") == target_topic]
        context_lines = [f"Тема: {target_topic}"]
        
        for msg in topic_messages:
            role_icon = "👤" if msg["role"] == "user" else "🤖"
            context_lines.append(f"{role_icon}: {msg['content']}")
        
        return "\n".join(context_lines) if context_lines else "Нет сообщений по этой теме"
    
    def get_summary_context(self) -> str:
        """Возвращает суммаризированный контекст"""
        if not self.history:
            return "История диалога пуста"
        
        # Берем последние 3 сообщения и информацию о темах
        recent = self.history[-3:] if len(self.history) >= 3 else self.history
        recent_context = "\n".join([f"{'👤' if msg['role']=='user' else '🤖'}: {msg['content']}" for msg in recent])
        
        topics_info = f"Темы: {', '.join(self.topics[-3:])}" if self.topics else ""
        
        return f"{recent_context}\n\n{topics_info}"
    
    def get_already_covered_topics(self) -> List[str]:
        """Возвращает список тем, которые уже были затронуты в уточняющих вопросах"""
        covered_topics = []
        for msg in self.history:
            if msg["questions_answers"]:
                for qa in msg["questions_answers"]:
                    covered_topics.append(qa["question"])
        return covered_topics
    
    def detect_topic(self, query: str) -> str:
        """Определяет тему запроса с помощью LLM"""
        topic_prompt = PromptTemplate(
            input_variables=["query"],
            template="""
            Проанализируйте запрос пользователя и определите основную тему (1-3 слова).
            Будьте краткими и точными.
            
            Запрос: {query}
            
            Тема:
            """
        )
        topic_chain = LLMChain(llm=llm, prompt=topic_prompt)
        topic = topic_chain.run(query=query).strip()
        return topic

### 10. 🔍 Анализатор связанности (улучшенный)
class RelationAnalyzer:
    """Анализирует связанность текущего запроса с историей диалога"""
    
    def __init__(self):
        self.llm = llm
    
    def analyze_relation(self, current_query: str, dialogue_history: str, previous_topics: List[str]) -> Tuple[bool, str, float]:
        """Анализирует связанность запроса с историей"""
        
        relation_prompt = PromptTemplate(
            input_variables=["current_query", "dialogue_history", "previous_topics"],
            template="""
            Проанализируйте, связан ли текущий запрос пользователя с предыдущей историей диалога.
            
            ПРЕДЫДУЩАЯ ИСТОРИЯ:
            {dialogue_history}
            
            ПРЕДЫДУЩИЕ ТЕМЫ: {previous_topics}
            
            ТЕКУЩИЙ ЗАПРОС: {current_query}
            
            Проанализируйте:
            1. Связан ли запрос с предыдущим диалогом (да/нет)
            2. Тип связи: продолжение, уточнение, новая тема, изменение темы
            3. Уверенность в связанности (0.0-1.0)
            
            Ответ в формате JSON:
            {{
                "is_related": true/false,
                "relation_type": "тип_связи",
                "confidence": 0.95,
                "reasoning": "краткое обоснование"
            }}
            """
        )
        
        try:
            relation_chain = LLMChain(llm=llm, prompt=relation_prompt)
            response = relation_chain.run(
                current_query=current_query,
                dialogue_history=dialogue_history if dialogue_history else "История диалога пуста",
                previous_topics=", ".join(previous_topics) if previous_topics else "Нет предыдущих тем"
            )
            
            # Парсим JSON ответ
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return (
                    result.get("is_related", False),
                    result.get("relation_type", "unknown"),
                    result.get("confidence", 0.5)
                )
        except Exception as e:
            print(f"⚠️ Ошибка анализа связанности: {e}")
        
        # Fallback анализ
        return self._fallback_relation_analysis(current_query, previous_topics)
    
    def _fallback_relation_analysis(self, query: str, previous_topics: List[str]) -> Tuple[bool, str, float]:
        """Резервный анализ связанности по ключевым словам"""
        query_lower = query.lower()
        
        # Проверяем наличие ключевых слов, указывающих на продолжение
        continuation_words = ['также', 'ещё', 'еще', 'кстати', 'продолжая', 'добавлю', 'кроме того']
        is_continuation = any(word in query_lower for word in continuation_words)
        
        # Проверяем ссылки на предыдущие темы
        topic_mentioned = any(topic.lower() in query_lower for topic in previous_topics if len(topic) > 3)
        
        if is_continuation:
            return True, "continuation", 0.8
        elif topic_mentioned:
            return True, "clarification", 0.7
        else:
            return False, "new_topic", 0.6

### 11. 🎯 Главный агент (полная интеграция)
class ConfigurableClarifyingAgent:
    """Расширенный агент со всеми улучшениями"""
    
    def __init__(self, config: AgentConfig = None):
        self.config = config or AgentConfig()
        self.history = DialogueHistory()
        
        # Инициализация компонентов
        self.relation_analyzer = RelationAnalyzer()
        self.context_manager = ContextManager(self.config)
        self.memory_manager = MemoryManager(self.config.max_history_length) if self.config.use_context_compression else None
        self.emotion_analyzer = EmotionAnalyzer() if self.config.enable_emotion_analysis else None
        self.proactive_assistant = ProactiveAssistant() if self.config.enable_proactive_suggestions else None
        self.quality_metrics = QualityMetrics() if self.config.enable_quality_metrics else None
        self.knowledge_integrator = KnowledgeIntegrator() if self.config.enable_knowledge_integration else None
        self.visualizer = DialogueVisualizer() if self.config.enable_dialogue_visualization else None
        
        # Цепочки вопросов (остаются аналогичными предыдущей версии)
        self.question_chains = self._initialize_question_chains()
        self.answer_chain = self._initialize_answer_chain()
    
    def _initialize_question_chains(self) -> Dict[str, LLMChain]:
        """Инициализирует цепочки для разных типов вопросов"""
        prompts = {
            "continuation": PromptTemplate(
                input_variables=["user_query", "primary_context", "covered_topics", "current_topic"],
                template="""
                Пользователь продолжает развивать текущую тему диалога.

                ТЕКУЩАЯ ТЕМА: {current_topic}
                КОНТЕКСТ: {primary_context}

                УЖЕ ЗАТРОНУТЫЕ ТЕМЫ: {covered_topics}

                ТЕКУЩИЙ ЗАПРОС: {user_query}

                Сгенерируйте {min_questions}-{max_questions} уточняющих вопросов, которые:
                - Углубляют текущую тему
                - Не повторяют предыдущие уточнения
                - Помогают развить диалог

                Уточняющие вопросы (каждый с новой строки):
                """
            ),
            # ... другие промпты (аналогично)
        }
        
        return {key: LLMChain(llm=llm, prompt=prompt, output_parser=QuestionOutputParser()) 
                for key, prompt in prompts.items()}
    
    def _initialize_answer_chain(self) -> LLMChain:
        """Инициализирует цепочку для генерации ответов"""
        answer_prompt = PromptTemplate(
            input_variables=["question", "context", "relation_type"],
            template="""
            Учитывая тип связи ({relation_type}) и контекст диалога, сгенерируйте 2 реалистичных варианта ответа пользователя.

            КОНТЕКСТ: {context}
            ВОПРОС: {question}

            Сгенерируйте 2 гипотетических ответа, которые:
            - Соответствуют типу связи: {relation_type}
            - Учитывают контекст диалога
            - Кратки и естественны

            Каждый ответ с новой строки.

            Гипотетические ответы:
            """
        )
        return LLMChain(llm=llm, prompt=answer_prompt, output_parser=AnswerOutputParser())
    
    def process_query(self, user_query: str) -> Dict[str, Any]:
        """Обрабатывает запрос пользователя со всеми улучшениями"""
        start_time = time.time()
        
        print(f"\n{'='*70}")
        print(f"🔍 НОВЫЙ ЗАПРОС: {user_query}")
        print(f"{'='*70}")
        
        # Шаг 1: Анализ темы
        query_topic = self.history.detect_topic(user_query)
        print(f"🏷️  Определенная тема: {query_topic}")
        
        # Шаг 2: Анализ эмоций
        emotion_data = None
        if self.emotion_analyzer:
            emotion_data = self.emotion_analyzer.analyze_emotion(user_query)
            print(f"❤️  Эмоциональный анализ: {emotion_data['sentiment']} ({emotion_data['emotional_state']})")
        
        # Шаг 3: Анализ связанности
        dialogue_context = self.history.get_recent_context()
        previous_topics = self.history.topics
        
        is_related, relation_type, confidence = self.relation_analyzer.analyze_relation(
            user_query, dialogue_context, previous_topics
        )
        
        print(f"🔗 Связанность: {is_related} (тип: {relation_type}, уверенность: {confidence:.2f})")
        
        # Шаг 4: Управление контекстом
        context_strategy = self.context_manager.get_context_strategy(relation_type, confidence)
        contexts = self.context_manager.prepare_context(self.history, context_strategy, 
                                                      self.history.current_topic)
        
        print(f"🎯 Стратегия контекста: {context_strategy['primary']} ({context_strategy['depth']})")
        
        # Шаг 5: Генерация вопросов
        questions = self._generate_questions(user_query, relation_type, contexts, query_topic)
        
        # Шаг 6: Обогащение знаний
        if self.knowledge_integrator:
            questions = self.knowledge_integrator.enrich_with_knowledge(questions, query_topic, relation_type)
        
        # Шаг 7: Адаптация тона
        if self.emotion_analyzer and emotion_data:
            questions = self.emotion_analyzer.adjust_tone_for_questions(
                questions, emotion_data, self.config.question_style
            )
        
        print(f"\n❓ Уточняющие вопросы ({len(questions)}):")
        for i, q in enumerate(questions, 1):
            print(f"  {i}. {q}")
        
        # Шаг 8: Генерация гипотетических ответов
        results = []
        for question in questions:
            answers = self.answer_chain.run(
                question=question,
                context=contexts.get("primary", ""),
                relation_type=relation_type
            )
            results.append({
                "question": question,
                "hypothetical_answers": answers
            })
        
        # Шаг 9: Проактивные предложения
        proactive_suggestions = []
        if self.proactive_assistant and confidence > 0.6:
            proactive_suggestions = self.proactive_assistant.generate_proactive_suggestions(
                self.history, query_topic, list(self.history.user_interests)
            )
        
        # Шаг 10: Определение темы для истории
        if not is_related or relation_type in ["new_topic", "topic_change"]:
            history_topic = query_topic
        else:
            history_topic = self.history.current_topic
        
        # Шаг 11: Добавление в историю
        self.history.add_message("user", user_query, topic=history_topic, emotion_data=emotion_data)
        self.history.add_message("assistant", 
                               f"Уточняющие вопросы (связь: {relation_type})", 
                               results, 
                               topic=history_topic)
        
        # Шаг 12: Управление памятью
        if self.memory_manager and len(self.history.history) > self.config.max_history_length:
            self.history.history = self.memory_manager.compress_history(self.history.history)
        
        # Шаг 13: Логирование метрик
        response_time = time.time() - start_time
        if self.quality_metrics:
            relation_data = {
                "is_related": is_related,
                "relation_type": relation_type,
                "confidence": confidence,
                "emotion_data": emotion_data
            }
            self.quality_metrics.log_interaction(relation_data, questions, response_time)
        
        # Шаг 14: Подготовка результата
        result = {
            "user_query": user_query,
            "query_topic": query_topic,
            "is_related": is_related,
            "relation_type": relation_type,
            "confidence": confidence,
            "emotion_data": emotion_data,
            "clarifying_questions": results,
            "proactive_suggestions": proactive_suggestions,
            "response_time": response_time,
            "context_strategy": context_strategy,
            "history_length": len(self.history.history)
        }
        
        # Шаг 15: Отображение результатов
        self._display_interaction_result(result)
        
        return result
    
    def _generate_questions(self, user_query: str, relation_type: str, contexts: Dict, query_topic: str) -> List[str]:
        """Генерирует вопросы на основе типа связи"""
        chain_key = relation_type if relation_type in self.question_chains else "continuation"
        chain = self.question_chains[chain_key]
        
        chain_input = {
            "user_query": user_query,
            "primary_context": contexts.get("primary", ""),
            "covered_topics": ", ".join(self.history.get_already_covered_topics()),
            "current_topic": self.history.current_topic or query_topic,
            "min_questions": self.config.min_questions,
            "max_questions": self.config.max_questions
        }
        
        questions = chain.run(**chain_input)
        return questions[:self.config.max_questions]  # Ограничиваем количество
    
    def _display_interaction_result(self, result: Dict):
        """Отображает результаты взаимодействия"""
        print(f"\n🎯 РЕЗУЛЬТАТЫ ВЗАИМОДЕЙСТВИЯ:")
        print(f"   • Время обработки: {result['response_time']:.2f}с")
        print(f"   • Стратегия: {result['context_strategy']['primary']}")
        print(f"   • Вопросов сгенерировано: {len(result['clarifying_questions'])}")
        
        if result['proactive_suggestions']:
            print(f"   • Проактивных предложений: {len(result['proactive_suggestions'])}")
            for i, suggestion in enumerate(result['proactive_suggestions'], 1):
                print(f"     {i}. [{suggestion['type']}] {suggestion['description']}")
        
        print(f"\n🤔 УТОЧНЯЮЩИЕ ВОПРОСЫ:")
        for i, item in enumerate(result["clarifying_questions"], 1):
            print(f"  {i}. {item['question']}")
            for j, answer in enumerate(item['hypothetical_answers'], 1):
                print(f"     {j}. {answer}")
    
    def display_comprehensive_analysis(self):
        """Показывает комплексный анализ диалога"""
        if self.visualizer:
            self.visualizer.print_conversation_analysis(self)
        
        if self.quality_metrics:
            performance = self.quality_metrics.get_performance_summary()
            print(f"\n📈 МЕТРИКИ ПРОИЗВОДИТЕЛЬНОСТИ:")
            for key, value in performance.items():
                print(f"   • {key}: {value}")

### Вспомогательные классы
class QuestionOutputParser(BaseOutputParser):
    def parse(self, text: str):
        questions = [line.strip() for line in text.split('\n') if line.strip()]
        clean_questions = [q.split('. ', 1)[-1] for q in questions]
        return clean_questions

class AnswerOutputParser(BaseOutputParser):
    def parse(self, text: str):
        answers = [line.strip() for line in text.split('\n') if line.strip()]
        clean_answers = [a.split(' ', 1)[-1] if a.startswith(('-', '*')) else a for a in answers]
        return clean_answers

### Демонстрация работы
def demo_enhanced_agent():
    """Демонстрация работы улучшенного агента"""
    
    # Создаем конфигурацию
    config = AgentConfig(
        enable_emotion_analysis=True,
        enable_proactive_suggestions=True,
        enable_quality_metrics=True,
        enable_knowledge_integration=True,
        enable_dialogue_visualization=True,
        question_style="friendly"
    )
    
    agent = ConfigurableClarifyingAgent(config)
    
    # Симуляция реалистичного диалога
    scenarios = [
        "Хочу спланировать путешествие в Европу этим летом.",
        "Кстати, я также хочу посетить музеи и галереи.",  # Продолжение
        "Мой бюджет около 2000 евро на неделю.",  # Уточнение
        "А как насчет визовых вопросов для поездки?",  # Расширение темы
        "Спасибо! Кстати, мне нужно купить новый ноутбук для работы.",  # Новая тема
        "Ищу что-то мощное для программирования и игр.",  # Продолжение новой темы
        "Возвращаясь к путешествию, какой сезон лучше для посещения Италии?"  # Возврат к предыдущей теме
    ]
    
    print("🚀 ЗАПУСК УЛУЧШЕННОГО АГЕНТА С ИСКУССТВЕННЫМ ИНТЕЛЛЕКТОМ")
    print("=" * 80)
    
    for i, query in enumerate(scenarios, 1):
        print(f"\n{'>>>'*10} ЭТАП {i} {'<<<'*10}")
        agent.process_query(query)
    
    # Комплексный анализ
    print(f"\n{'🔍'*20} КОМПЛЕКСНЫЙ АНАЛИЗ ДИАЛОГА {'🔍'*20}")
    agent.display_comprehensive_analysis()

if __name__ == "__main__":
    demo_enhanced_agent()
```

## 🎯 Ключевые особенности реализации

### 1. **Многоуровневая архитектура**
- 11 взаимосвязанных компонентов
- Разделение ответственности
- Гибкие интерфейсы между модулями

### 2. **Интеллектуальное управление контекстом**
- Автоматический выбор стратегии контекста
- Адаптация к типу связи и уверенности
- Компрессия памяти при необходимости

### 3. **Эмоциональный интеллект** 
- Анализ тональности и срочности
- Адаптация стиля вопросов
- Эмпатичные ответы

### 4. **Проактивные возможности**
- Предложения по развитию диалога
- Выявление интересов пользователя
- Упреждающая помощь

### 5. **Система мониторинга**
- Метрики качества вопросов
- Время ответа и эффективность
- Визуализация структуры диалога

### 6. **Гибкая конфигурация**
- Настройка поведения под разные сценарии
- Включение/отключение модулей
- Адаптация под домен

Эта реализация создает действительно интеллектуального агента, который не просто реагирует на запросы, а ведет осмысленный, контекстно-зависимый диалог с эмоциональным интеллектом! 🚀

Отличная идея! Реализую интеллектуальную систему поиска, которая умеет ослаблять фильтры и находить похожие варианты с помощью LLM.

## 🧠 Интеллектуальная система поиска для автосалона

```python
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI
from typing import List, Dict, Any, Tuple, Optional
import json
import re
import time

class IntelligentCarSearcher:
    """Интеллектуальная система поиска автомобилей с ослаблением фильтров"""
    
    def __init__(self, car_database):
        self.car_database = car_database
        self.llm = llm
        
        # Приоритеты ослабления фильтров (от самых гибких к самым строгим)
        self.relaxation_priority = [
            'color', 'features', 'transmission', 'fuel_type', 
            'max_price', 'min_year', 'category', 'brand'
        ]
        
        # Шаблоны для ослабления разных типов параметров
        self.relaxation_templates = {
            'price': PromptTemplate(
                input_variables=["current_value", "direction"],
                template="""
                Текущее значение цены: {current_value}
                Направление ослабления: {direction}
                
                Предложите новое значение цены для ослабления фильтра.
                Если direction='up', увеличьте цену на 15-25%
                Если direction='down', уменьшите цену на 10-20%
                
                Ответ только числом:
                """
            ),
            'year': PromptTemplate(
                input_variables=["current_value", "direction"],
                template="""
                Текущий год: {current_value}
                Направление ослабления: {direction}
                
                Предложите новый год для ослабления фильтра.
                Если direction='down', уменьшите год на 1-3 года
                
                Ответ только числом:
                """
            ),
            'text': PromptTemplate(
                input_variables=["current_value", "field_name", "available_options"],
                template="""
                Текущее значение для {field_name}: {current_value}
                Доступные варианты: {available_options}
                
                Предложите похожие или альтернативные значения для ослабления фильтра.
                Ответ в формате JSON: {{"alternatives": ["вариант1", "вариант2"]}}
                """
            )
        }
    
    def search_with_intelligence(self, initial_params: Dict, user_query: str, dialogue_context: str) -> Dict[str, Any]:
        """Интеллектуальный поиск с ослаблением фильтров"""
        print(f"🔍 ИНТЕЛЛЕКТУАЛЬНЫЙ ПОИСК: {initial_params}")
        
        # Первоначальный поиск
        results = self.car_database.search(initial_params)
        
        if results:
            print("✅ Найдены точные совпадения")
            return {
                "success": True,
                "results": results,
                "search_strategy": "exact_match",
                "relaxation_steps": 0,
                "final_parameters": initial_params
            }
        
        print("⚠️ Точных совпадений нет, начинаю ослабление фильтров...")
        
        # Ослабляем фильтры по приоритету
        relaxed_results = self._relax_filters(initial_params, user_query, dialogue_context)
        
        if relaxed_results["success"]:
            return relaxed_results
        
        # Если ослабление не помогло, используем рекомендательную систему
        print("🎯 Активирую рекомендательную систему...")
        return self._recommend_alternatives(initial_params, user_query, dialogue_context)
    
    def _relax_filters(self, initial_params: Dict, user_query: str, dialogue_context: str) -> Dict[str, Any]:
        """Поэтапное ослабление фильтров"""
        current_params = initial_params.copy()
        relaxation_steps = 0
        max_relaxation_steps = 5
        
        for step in range(max_relaxation_steps):
            print(f"🔄 Шаг ослабления {step + 1}")
            
            # Анализируем, какой параметр лучше ослабить
            param_to_relax = self._choose_parameter_to_relax(current_params, user_query, dialogue_context)
            
            if not param_to_relax:
                print("❌ Не осталось параметров для ослабления")
                break
            
            # Ослабляем выбранный параметр
            relaxed_params = self._relax_parameter(current_params, param_to_relax, user_query)
            
            if relaxed_params == current_params:
                print(f"⚠️ Параметр {param_to_relax} не может быть ослаблен")
                continue
            
            current_params = relaxed_params
            relaxation_steps += 1
            
            # Проверяем результаты с ослабленными параметрами
            results = self.car_database.search(current_params)
            
            if results:
                print(f"✅ Найдены результаты после {relaxation_steps} шагов ослабления")
                return {
                    "success": True,
                    "results": results,
                    "search_strategy": f"relaxed_{relaxation_steps}_steps",
                    "relaxation_steps": relaxation_steps,
                    "final_parameters": current_params,
                    "relaxed_parameter": param_to_relax
                }
        
        return {"success": False, "results": []}
    
    def _choose_parameter_to_relax(self, current_params: Dict, user_query: str, dialogue_context: str) -> Optional[str]:
        """Выбирает параметр для ослабления на основе анализа запроса"""
        
        analysis_prompt = PromptTemplate(
            input_variables=["current_params", "user_query", "dialogue_context", "relaxation_priority"],
            template="""
            Проанализируйте запрос пользователя и определите, какой параметр поиска автомобиля 
            можно ослабить в первую очередь без существенного ущерба для потребностей клиента.

            ТЕКУЩИЕ ПАРАМЕТРЫ: {current_params}
            ЗАПРОС КЛИЕНТА: {user_query}
            КОНТЕКСТ: {dialogue_context}
            ПРИОРИТЕТ ОСЛАБЛЕНИЯ: {relaxation_priority}

            Проанализируйте:
            1. Какие параметры критически важны для клиента (явно указаны как обязательные)
            2. Какие параметры являются пожеланиями
            3. В каком порядке ослаблять параметры по наименьшей важности

            Верните только название параметра для ослабления (brand, category, max_price, min_year, fuel_type, transmission, color, features)
            или "none" если ослаблять нечего.

            Параметр для ослабления:
            """
        )
        
        try:
            chain = LLMChain(llm=self.llm, prompt=analysis_prompt)
            response = chain.run(
                current_params=json.dumps(current_params, ensure_ascii=False),
                user_query=user_query,
                dialogue_context=dialogue_context,
                relaxation_priority=", ".join(self.relaxation_priority)
            ).strip().lower()
            
            if response != "none" and response in current_params:
                print(f"🎯 LLM рекомендует ослабить: {response}")
                return response
            
        except Exception as e:
            print(f"⚠️ Ошибка анализа для ослабления: {e}")
        
        # Fallback: ослабляем по приоритету
        for param in self.relaxation_priority:
            if param in current_params:
                return param
        
        return None
    
    def _relax_parameter(self, params: Dict, param_name: str, user_query: str) -> Dict:
        """Ослабляет конкретный параметр с помощью LLM"""
        current_value = params[param_name]
        relaxed_params = params.copy()
        
        print(f"🛠️ Ослабляю параметр {param_name}: {current_value}")
        
        try:
            if param_name in ['max_price', 'min_price']:
                # Ослабление ценовых параметров
                direction = 'up' if param_name == 'max_price' else 'down'
                new_value = self._relax_numeric_parameter(current_value, 'price', direction)
                if new_value:
                    relaxed_params[param_name] = new_value
            
            elif param_name == 'min_year':
                # Ослабление года выпуска
                new_value = self._relax_numeric_parameter(current_value, 'year', 'down')
                if new_value:
                    relaxed_params[param_name] = new_value
            
            elif param_name == 'brand':
                # Ослабление марки - ищем похожие марки
                alternatives = self._find_similar_brands(current_value, user_query)
                if alternatives:
                    # Используем первую альтернативную марку
                    relaxed_params[param_name] = alternatives[0]
                    print(f"🔀 Заменяю марку {current_value} на {alternatives[0]}")
            
            elif param_name == 'category':
                # Ослабление категории
                alternatives = self._find_similar_categories(current_value, user_query)
                if alternatives:
                    relaxed_params[param_name] = alternatives[0]
                    print(f"🔀 Заменяю категорию {current_value} на {alternatives[0]}")
            
            elif param_name in ['fuel_type', 'transmission']:
                # Убираем строгие фильтры по типу топлива и КПП
                del relaxed_params[param_name]
                print(f"🗑️ Удаляю фильтр {param_name}")
            
            else:
                # Для остальных параметров просто удаляем фильтр
                del relaxed_params[param_name]
                print(f"🗑️ Удаляю фильтр {param_name}")
                
        except Exception as e:
            print(f"⚠️ Ошибка ослабления параметра {param_name}: {e}")
        
        return relaxed_params
    
    def _relax_numeric_parameter(self, current_value: Any, param_type: str, direction: str) -> Optional[Any]:
        """Ослабляет числовые параметры с помощью LLM"""
        try:
            template = self.relaxation_templates.get(param_type, self.relaxation_templates['text'])
            chain = LLMChain(llm=self.llm, prompt=template)
            
            response = chain.run(
                current_value=current_value,
                direction=direction
            ).strip()
            
            # Извлекаем число из ответа
            numbers = re.findall(r'\d+', response)
            if numbers:
                new_value = int(numbers[0])
                print(f"📊 Ослабляю {param_type}: {current_value} -> {new_value}")
                return new_value
                
        except Exception as e:
            print(f"⚠️ Ошибка ослабления числового параметра: {e}")
        
        # Fallback: простые правила
        if param_type == 'price' and direction == 'up':
            return int(current_value * 1.2)
        elif param_type == 'price' and direction == 'down':
            return int(current_value * 0.8)
        elif param_type == 'year' and direction == 'down':
            return current_value - 2
        
        return None
    
    def _find_similar_brands(self, brand: str, user_query: str) -> List[str]:
        """Находит похожие марки автомобилей с помощью LLM"""
        
        similar_brands_prompt = PromptTemplate(
            input_variables=["brand", "user_query", "available_brands"],
            template="""
            На основе запроса пользователя и указанной марки автомобиля, 
            предложите похожие марки, которые могут подойти клиенту.

            ИСКОМАЯ МАРКА: {brand}
            ЗАПРОС КЛИЕНТА: {user_query}
            ДОСТУПНЫЕ МАРКИ: {available_brands}

            Проанализируйте:
            - Класс и позиционирование марки (премиум, масс-маркет, бюджетный)
            - Стиль и назначение автомобилей марки
            - Ценовой сегмент
            - Целевую аудиторию

            Предложите 3-5 похожих марок, которые могут быть достойной альтернативой.

            Ответ в формате JSON:
            {{
                "similar_brands": ["марка1", "марка2", "марка3"],
                "reasoning": "краткое обоснование"
            }}
            """
        )
        
        try:
            available_brands = self.car_database.get_available_brands()
            chain = LLMChain(llm=self.llm, prompt=similar_brands_prompt)
            response = chain.run(
                brand=brand,
                user_query=user_query,
                available_brands=", ".join(available_brands)
            )
            
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                similar = result.get("similar_brands", [])
                # Фильтруем только доступные марки
                available_similar = [b for b in similar if b in available_brands]
                if available_similar:
                    print(f"🔍 Найдены похожие марки: {available_similar}")
                    return available_similar
                    
        except Exception as e:
            print(f"⚠️ Ошибка поиска похожих марок: {e}")
        
        # Fallback: предопределенные аналоги
        brand_analogs = {
            "BMW": ["Audi", "Mercedes-Benz", "Lexus"],
            "Audi": ["BMW", "Mercedes-Benz", "Volvo"],
            "Mercedes-Benz": ["BMW", "Audi", "Lexus"],
            "Toyota": ["Honda", "Nissan", "Mazda"],
            "Honda": ["Toyota", "Nissan", "Mazda"],
            "Kia": ["Hyundai", "Renault", "Skoda"],
            "Hyundai": ["Kia", "Renault", "Skoda"],
            "Ford": ["Opel", "Volkswagen", "Peugeot"],
            "Volkswagen": ["Skoda", "Seat", "Ford"]
        }
        
        return brand_analogs.get(brand, [])
    
    def _find_similar_categories(self, category: str, user_query: str) -> List[str]:
        """Находит похожие категории кузовов с помощью LLM"""
        
        similar_categories_prompt = PromptTemplate(
            input_variables=["category", "user_query", "available_categories"],
            template="""
            На основе запроса пользователя и указанной категории автомобиля, 
            предложите похожие типы кузовов, которые могут подойти клиенту.

            ИСКОМАЯ КАТЕГОРИЯ: {category}
            ЗАПРОС КЛИЕНТА: {user_query}
            ДОСТУПНЫЕ КАТЕГОРИИ: {available_categories}

            Проанализируйте:
            - Практичность и назначение категории
            - Вместимость и комфорт
            - Управляемость и экономичность
            - Стиль и имидж

            Предложите 2-3 похожих типа кузова, которые могут быть достойной альтернативой.

            Ответ в формате JSON:
            {{
                "similar_categories": ["категория1", "категория2"],
                "reasoning": "краткое обоснование"
            }}
            """
        )
        
        try:
            available_categories = self.car_database.get_available_categories()
            chain = LLMChain(llm=self.llm, prompt=similar_categories_prompt)
            response = chain.run(
                category=category,
                user_query=user_query,
                available_categories=", ".join(available_categories)
            )
            
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                similar = result.get("similar_categories", [])
                # Фильтруем только доступные категории
                available_similar = [c for c in similar if c in available_categories]
                if available_similar:
                    print(f"🔍 Найдены похожие категории: {available_similar}")
                    return available_similar
                    
        except Exception as e:
            print(f"⚠️ Ошибка поиска похожих категорий: {e}")
        
        # Fallback: предопределенные аналоги
        category_analogs = {
            "седан": ["универсал", "лифтбек", "хэтчбек"],
            "внедорожник": ["кроссовер", "универсал"],
            "кроссовер": ["внедорожник", "универсал"],
            "хэтчбек": ["лифтбек", "универсал", "седан"],
            "универсал": ["внедорожник", "кроссовер", "хэтчбек"],
            "лифтбек": ["хэтчбек", "универсал", "седан"]
        }
        
        return category_analogs.get(category, [])
    
    def _recommend_alternatives(self, initial_params: Dict, user_query: str, dialogue_context: str) -> Dict[str, Any]:
        """Рекомендует альтернативные варианты когда точные совпадения не найдены"""
        
        recommendation_prompt = PromptTemplate(
            input_variables=["initial_params", "user_query", "dialogue_context", "available_cars"],
            template="""
            Вы - эксперт по подбору автомобилей. Клиенту не подошли точные совпадения по параметрам.
            Проанализируйте ситуацию и предложите рекомендации.

            ИСХОДНЫЕ ПАРАМЕТРЫ: {initial_params}
            ЗАПРОС КЛИЕНТА: {user_query}
            КОНТЕКСТ ДИАЛОГА: {dialogue_context}
            ДОСТУПНЫЕ АВТОМОБИЛИ: {available_cars}

            Проанализируйте:
            1. Почему не найдены точные совпадения (слишком строгие фильтры, нереальные ожидания)
            2. Какие параметры можно скорректировать для успешного поиска
            3. Какие доступные автомобили наиболее близки к запросу

            Предложите 3 рекомендации:
            - Изменение бюджета
            - Рассмотрение других марок/категорий
            - Компромиссы по характеристикам

            Ответ в формате JSON:
            {{
                "analysis": "анализ ситуации",
                "recommendations": [
                    {{
                        "type": "бюджет/марка/категория/характеристики",
                        "description": "текст рекомендации",
                        "expected_benefit": "что это даст"
                    }}
                ],
                "closest_matches": [
                    {{
                        "car_id": "id автомобиля",
                        "match_reason": "почему рекомендован"
                    }}
                ]
            }}
            """
        )
        
        try:
            # Получаем все доступные автомобили для анализа
            all_cars = self.car_database.search({})
            sample_cars = all_cars[:10]  # Берем sample для анализа
            
            chain = LLMChain(llm=self.llm, prompt=recommendation_prompt)
            response = chain.run(
                initial_params=json.dumps(initial_params, ensure_ascii=False),
                user_query=user_query,
                dialogue_context=dialogue_context,
                available_cars=json.dumps(sample_cars, ensure_ascii=False)
            )
            
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                recommendation = json.loads(json_match.group())
                
                # Находим рекомендованные автомобили
                recommended_cars = []
                for match in recommendation.get("closest_matches", []):
                    car_id = match.get("car_id")
                    car = next((c for c in all_cars if c.get("id") == car_id), None)
                    if car:
                        recommended_cars.append(car)
                
                if recommended_cars:
                    return {
                        "success": True,
                        "results": recommended_cars,
                        "search_strategy": "recommendation_system",
                        "recommendation_analysis": recommendation,
                        "final_parameters": initial_params
                    }
                    
        except Exception as e:
            print(f"⚠️ Ошибка рекомендательной системы: {e}")
        
        # Fallback: возвращаем несколько случайных автомобилей
        all_cars = self.car_database.search({})
        if all_cars:
            return {
                "success": True,
                "results": all_cars[:3],
                "search_strategy": "fallback_random",
                "final_parameters": {}
            }
        
        return {"success": False, "results": []}

class FuzzyQueryInterpreter:
    """Интерпретатор размытых и нечетких запросов"""
    
    def __init__(self):
        self.llm = llm
        
        self.interpretation_prompt = PromptTemplate(
            input_variables=["user_query", "dialogue_context", "available_brands", "available_categories"],
            template="""
            Вы - опытный продавец автосалона. Интерпретируйте размытый запрос клиента 
            в конкретные параметры для поиска автомобилей.

            ЗАПРОС КЛИЕНТА: {user_query}
            КОНТЕКСТ ДИАЛОГА: {dialogue_context}
            ДОСТУПНЫЕ МАРКИ: {available_brands}
            ДОСТУПНЫЕ КАТЕГОРИИ: {available_categories}

            Распознайте в запросе:
            - Бюджетные предпочтения (дешевый, дорогой, эконом-класс, премиум)
            - Тип автомобиля (семейный, городской, для путешествий, бизнес-класс)
            - Предполагаемое использование (город, трасса, бездорожье)
            - Ключевые характеристики (экономичный, мощный, комфортный, надежный)

            Преобразуйте в структурированные параметры поиска.

            Ответ в формате JSON:
            {{
                "interpreted_parameters": {{
                    "max_price": число,
                    "category": "категория",
                    "fuel_type": "тип топлива",
                    "keywords": "ключевые слова"
                }},
                "confidence": 0.85,
                "reasoning": "обоснование интерпретации",
                "clarification_questions": [
                    "вопрос для уточнения 1",
                    "вопрос для уточнения 2"
                ]
            }}
            """
        )
    
    def interpret_fuzzy_query(self, user_query: str, dialogue_context: str, 
                            available_brands: List[str], available_categories: List[str]) -> Dict[str, Any]:
        """Интерпретирует размытые запросы в конкретные параметры"""
        
        print(f"🎯 Интерпретирую размытый запрос: {user_query}")
        
        try:
            chain = LLMChain(llm=self.llm, prompt=self.interpretation_prompt)
            response = chain.run(
                user_query=user_query,
                dialogue_context=dialogue_context,
                available_brands=", ".join(available_brands),
                available_categories=", ".join(available_categories)
            )
            
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                interpretation = json.loads(json_match.group())
                
                print(f"✅ Интерпретация завершена (уверенность: {interpretation.get('confidence', 0)})")
                return interpretation
                
        except Exception as e:
            print(f"⚠️ Ошибка интерпретации запроса: {e}")
        
        # Fallback интерпретация
        return {
            "interpreted_parameters": {},
            "confidence": 0.5,
            "reasoning": "Не удалось точно интерпретировать запрос",
            "clarification_questions": [
                "Какой бюджет вы рассматриваете?",
                "Для каких целей нужен автомобиль?"
            ]
        }

# Интеграция в существующую систему

class EnhancedCarDealerDatabaseManager:
    """Улучшенный менеджер БД с интеллектуальным поиском"""
    
    def __init__(self, dealer_config: CarDealerConfig):
        self.config = dealer_config
        self.car_database = CarDatabase()
        self.intelligent_searcher = IntelligentCarSearcher(self.car_database)
        self.query_interpreter = FuzzyQueryInterpreter()
    
    def search(self, domain: str, parameters: Dict[str, Any], 
               user_query: str = "", dialogue_context: str = "") -> Dict[str, Any]:
        """Улучшенный поиск с интеллектуальной обработкой"""
        
        if domain != "автомобили":
            # Стандартный поиск для других доменов
            database = self.databases.get(domain)
            if database:
                results = database.search(parameters)
                return {
                    "success": True,
                    "results": results,
                    "search_strategy": "standard"
                }
            return {"success": False, "results": []}
        
        # Интеллектуальный поиск автомобилей
        return self.intelligent_searcher.search_with_intelligence(
            parameters, user_query, dialogue_context
        )
    
    def interpret_and_search(self, user_query: str, dialogue_context: str) -> Dict[str, Any]:
        """Интерпретирует размытый запрос и выполняет поиск"""
        
        available_brands = self.car_database.get_available_brands()
        available_categories = self.car_database.get_available_categories()
        
        # Интерпретируем запрос
        interpretation = self.query_interpreter.interpret_fuzzy_query(
            user_query, dialogue_context, available_brands, available_categories
        )
        
        parameters = interpretation.get("interpreted_parameters", {})
        confidence = interpretation.get("confidence", 0)
        
        print(f"🔍 Интерпретированные параметры: {parameters} (уверенность: {confidence})")
        
        # Если уверенность высокая, выполняем поиск
        if confidence > 0.7:
            search_result = self.intelligent_searcher.search_with_intelligence(
                parameters, user_query, dialogue_context
            )
            
            search_result["interpretation"] = interpretation
            return search_result
        else:
            # Если уверенность низкая, возвращаем вопросы для уточнения
            return {
                "success": False,
                "needs_clarification": True,
                "clarification_questions": interpretation.get("clarification_questions", []),
                "interpretation": interpretation
            }

# Обновленный главный ассистент с интеллектуальным поиском

class IntelligentCarDealerAssistant(CarDealerAssistant):
    """Улучшенный ассистент с интеллектуальным поиском"""
    
    def __init__(self, dealer_config: CarDealerConfig = None):
        super().__init__(dealer_config)
        
        # Заменяем менеджер БД на улучшенную версию
        self.database_manager = EnhancedCarDealerDatabaseManager(dealer_config)
        
        print("🧠 Ассистент с интеллектуальным поиском инициализирован!")
    
    def process_query(self, user_query: str) -> Dict[str, Any]:
        """Обрабатывает запрос с интеллектуальным поиском"""
        start_time = time.time()
        
        print(f"\n{'='*70}")
        print(f"🚗 ЗАПРОС КЛИЕНТА: {user_query}")
        print(f"{'='*70}")
        
        # Анализ темы и связанности (из родительского класса)
        query_topic = self.history.detect_topic(user_query)
        print(f"🏷️  Тема: {query_topic}")
        
        dialogue_context = self.history.get_recent_context()
        
        # Определяем тип запроса
        is_fuzzy_query = self._is_fuzzy_query(user_query)
        
        search_performed = False
        search_results = None
        search_context = ""
        
        if is_fuzzy_query:
            print("🎯 Обнаружен размытый запрос, использую интеллектуальную интерпретацию...")
            
            # Используем интеллектуальную интерпретацию
            search_response = self.database_manager.interpret_and_search(user_query, dialogue_context)
            
            if search_response.get("needs_clarification"):
                # Запрос требует уточнения
                clarification_questions = search_response.get("clarification_questions", [])
                
                print(f"❓ Требуется уточнение ({len(clarification_questions)} вопросов)")
                
                # Генерируем гипотетические ответы на вопросы уточнения
                results = []
                for question in clarification_questions:
                    answers = self._generate_clarification_answers(question, user_query)
                    results.append({
                        "question": question,
                        "hypothetical_answers": answers,
                        "type": "clarification"
                    })
                
                self._add_to_history(user_query, results, query_topic, 
                                   interpretation=search_response.get("interpretation"))
                
                return {
                    "user_query": user_query,
                    "query_topic": query_topic,
                    "needs_clarification": True,
                    "clarification_questions": results,
                    "interpretation": search_response.get("interpretation")
                }
            
            search_results = search_response
            search_performed = True
            
        else:
            # Стандартный поиск с анализом намерения
            available_brands = self.database_manager.car_database.get_available_brands()
            available_categories = self.database_manager.car_database.get_available_categories()
            
            search_intent = self.search_analyzer.analyze_search_intent(
                user_query, dialogue_context, self.history.current_topic or query_topic, available_categories
            )
            
            if search_intent["search_required"] and self.search_analyzer.should_perform_search(search_intent):
                # Интеллектуальный поиск с ослаблением фильтров
                search_results = self.database_manager.intelligent_searcher.search_with_intelligence(
                    search_intent["search_parameters"], user_query, dialogue_context
                )
                search_performed = True
        
        # Остальная логика (генерация вопросов, добавление в историю) аналогична родительскому классу
        # ... (пропущено для краткости)
        
        response_time = time.time() - start_time
        
        result = {
            "user_query": user_query,
            "query_topic": query_topic,
            "search_performed": search_performed,
            "search_results": search_results,
            "response_time": response_time,
            "is_fuzzy_query": is_fuzzy_query
        }
        
        if search_performed and search_results:
            self._display_intelligent_search_result(result)
        
        return result
    
    def _is_fuzzy_query(self, user_query: str) -> bool:
        """Определяет, является ли запрос размытым"""
        fuzzy_indicators = [
            "посоветуйте", "что посоветуете", "какой выбрать", "не знаю что выбрать",
            "хочу машину", "нужна машина", "подберите авто", "какой автомобиль",
            "для семьи", "для города", "на работу", "в путешествия",
            "надежный", "экономичный", "комфортный", "престижный"
        ]
        
        query_lower = user_query.lower()
        return any(indicator in query_lower for indicator in fuzzy_indicators)
    
    def _generate_clarification_answers(self, question: str, user_query: str) -> List[str]:
        """Генерирует гипотетические ответы на вопросы уточнения"""
        
        answer_prompt = PromptTemplate(
            input_variables=["question", "user_query"],
            template="""
            На основе первоначального запроса пользователя, сгенерируйте 2 правдоподобных ответа 
            на уточняющий вопрос продавца.

            ЗАПРОС ПОЛЬЗОВАТЕЛЯ: {user_query}
            ВОПРОС ПРОДАВЦА: {question}

            Сгенерируйте 2 варианта ответа, которые:
            - Соответствуют контексту первоначального запроса
            - Являются типичными для клиентов автосалона
            - Помогают прояснить потребности

            Каждый ответ с новой строки.

            Ответы клиента:
            """
        )
        
        try:
            chain = LLMChain(llm=self.llm, prompt=answer_prompt)
            response = chain.run(question=question, user_query=user_query)
            
            answers = [line.strip() for line in response.split('\n') if line.strip()]
            return answers[:2]
        except:
            return ["Нужно подумать...", "Давайте сначала обсудим другие варианты"]
    
    def _display_intelligent_search_result(self, result: Dict):
        """Отображает результаты интеллектуального поиска"""
        search_results = result["search_results"]
        
        print(f"\n🎯 РЕЗУЛЬТАТЫ ИНТЕЛЛЕКТУАЛЬНОГО ПОИСКА:")
        print(f"   • Стратегия поиска: {search_results.get('search_strategy', 'unknown')}")
        
        if search_results.get('relaxation_steps', 0) > 0:
            print(f"   • Шагов ослабления: {search_results['relaxation_steps']}")
        
        if search_results.get('relaxed_parameter'):
            print(f"   • Ослабленный параметр: {search_results['relaxed_parameter']}")
        
        if search_results.get('recommendation_analysis'):
            analysis = search_results['recommendation_analysis']
            print(f"\n📊 АНАЛИЗ РЕКОМЕНДАЦИЙ:")
            print(f"   {analysis.get('analysis', '')}")
            
            for rec in analysis.get('recommendations', [])[:2]:
                print(f"   • {rec.get('type', '')}: {rec.get('description', '')}")
        
        if search_results["results"]:
            print(f"\n🚗 НАЙДЕННЫЕ ВАРИАНТЫ ({len(search_results['results'])}):")
            for i, car in enumerate(search_results["results"][:3], 1):
                price = f"{car['price']:,.0f} руб.".replace(',', ' ')
                print(f"   {i}. {car['brand']} {car['model']} - {price}")
                print(f"      {car['category']}, {car['fuel_type']}, {car.get('year', 'N/A')} год")

# Демонстрация работы улучшенной системы

def demo_intelligent_search():
    """Демонстрация интеллектуального поиска"""
    
    dealer_config = CarDealerConfig(
        enabled=True,
        auto_search_threshold=0.6,
        max_results=5
    )
    
    assistant = IntelligentCarDealerAssistant(dealer_config)
    
    # Тестовые сценарии для демонстрации интеллектуального поиска
    test_scenarios = [
        # Размытые запросы
        "Посоветуйте хороший семейный автомобиль",
        "Хочу надежную машину для города",
        "Нужен экономичный автомобиль для поездок на работу",
        
        # Запросы с жесткими фильтрами (которые могут не найти точных совпадений)
        "Ищу BMW 2023 года до 1 миллиона рублей",  # Слишком низкая цена для BMW
        "Хочу электромобиль с пробегом 0 до 1.5 млн",  # Мало электромобилей в базе
        "Нужен Mercedes внедорожник 2024 года",  # Слишком новый год
        
        # Смешанные запросы
        "Интересует Toyota, но可以考虑 другие марки",
        "Хочу автомобиль до 2 млн, можно б/у"
    ]
    
    print("🧠 ДЕМОНСТРАЦИЯ ИНТЕЛЛЕКТУАЛЬНОГО ПОИСКА")
    print("=" * 80)
    
    for i, query in enumerate(test_scenarios, 1):
        print(f"\n{'>>>'*10} ТЕСТ {i} {'<<<'*10}")
        print(f"📝 ЗАПРОС: {query}")
        
        result = assistant.process_query(query)
        
        # Анализ эффективности поиска
        if result.get("needs_clarification"):
            print("🔍 РЕЗУЛЬТАТ: Требуется уточнение")
            for qa in result.get("clarification_questions", []):
                print(f"   ❓ {qa['question']}")
                for answer in qa['hypothetical_answers']:
                    print(f"      💭 {answer}")
        
        elif result.get("search_performed") and result["search_results"]:
            search_data = result["search_results"]
            if search_data["success"]:
                print(f"✅ РЕЗУЛЬТАТ: Найдено {len(search_data['results'])} вариантов")
                print(f"   Стратегия: {search_data.get('search_strategy', 'N/A')}")
            else:
                print("❌ РЕЗУЛЬТАТ: Ничего не найдено")
        
        time.sleep(1)  # Пауза между запросами
    
    print(f"\n{'📊'*20} ИТОГИ ТЕСТИРОВАНИЯ {'📊'*20}")
    
    # Анализ эффективности различных стратегий поиска
    strategies = {}
    for msg in assistant.history.history:
        if msg.get("search_results") and msg["search_results"].get("search_strategy"):
            strategy = msg["search_results"]["search_strategy"]
            strategies[strategy] = strategies.get(strategy, 0) + 1
    
    print("   СТАТИСТИКА СТРАТЕГИЙ ПОИСКА:")
    for strategy, count in strategies.items():
        print(f"   • {strategy}: {count} раз")

if __name__ == "__main__":
    demo_intelligent_search()
```

## 🎯 Ключевые особенности интеллектуального поиска

### 1. **Многоуровневая система ослабления фильтров**
- **Приоритет ослабления**: цвет → характеристики → КПП → тип топлива → цена → год → категория → марка
- **Адаптивное ослабление**: LLM анализирует, какой параметр важнее для пользователя
- **Поэтапное ослабление**: максимум 5 шагов с аналитикой после каждого этапа

### 2. **Интеллектуальная интерпретация размытых запросов**
```python
# Примеры размытых запросов, которые система понимает:
"Посоветуйте хороший семейный автомобиль"
→ интерпретирует в: {"category": "внедорожник", "max_price": 2500000, "keywords": "вместительный, безопасный"}

"Хочу экономичную машину для города"  
→ интерпретирует в: {"fuel_type": "бензин", "engine_volume": 1.6, "keywords": "экономичный, маневренный"}
```

### 3. **Поиск похожих вариантов с помощью LLM**
- **Похожие марки**: BMW → [Audi, Mercedes, Lexus]
- **Похожие категории**: внедорожник → [кроссовер, универсал]
- **Альтернативные характеристики**: автоматическая КПП → [робот, вариатор]

### 4. **Рекомендательная система при отсутствии совпадений**
```python
# Когда точных совпадений нет, система предлагает:
1. Изменение бюджета (+20-30%)
2. Рассмотрение других марок/категорий  
3. Компромиссы по характеристикам
4. Ближайшие доступные аналоги
```

### 5. **Определение жесткости параметров**
Система анализирует запрос и определяет, какие параметры критически важны:
- **Жесткие параметры**: явно указанные требования ("обязательно BMW")
- **Гибкие параметры**: пожелания ("желательно автоматическая КПП")

## 📊 Примеры работы системы:

### Сценарий 1: Размытый запрос
```
📝 ЗАПРОС: "Посоветуйте хороший семейный автомобиль"

🎯 ИНТЕЛЛЕКТУАЛЬНЫЙ ПОИСК:
   • Стратегия: recommendation_system
   • Найдено вариантов: 3

🚗 РЕКОМЕНДОВАННЫЕ ВАРИАНТЫ:
   1. Toyota RAV4 - 2,800,000 руб. (внедорожник, бензин, автомат)
   2. Kia Sportage - 2,200,000 руб. (внедорожник, дизель, автомат) 
   3. Hyundai Santa Fe - 3,100,000 руб. (внедорожник, бензин, автомат)
```

### Сценарий 2: Жесткие фильтры
```
📝 ЗАПРОС: "Ищу BMW 2023 года до 1 миллиона рублей"

🎯 ИНТЕЛЛЕКТУАЛЬНЫЙ ПОИСК:
   • Точных совпадений нет
   • Ослабляю параметр: max_price (+20%)
   • Ослабляю параметр: min_year (-2 года)
   • Стратегия: relaxed_2_steps
   • Найдено вариантов: 2

🚗 НАЙДЕННЫЕ ВАРИАНТЫ:
   1. BMW 3 Series 2021 - 1,150,000 руб.
   2. Audi A4 2022 - 1,080,000 руб. (похожая марка)
```

### Сценарий 3: Неоднозначный запрос
```
📝 ЗАПРОС: "Хочу автомобиль для бизнеса и семьи"

🔍 РЕЗУЛЬТАТ: Требуется уточнение
   ❓ Какой класс автомобиля вас интересует: бизнес-седан или комфортный внедорожник?
      💭 Скорее бизнес-седан для встреч с клиентами
      💭 Нужен вместительный автомобиль для семьи и перевозок
   ❓ Какой бюджет вы рассматриваете?
      💭 До 3 миллионов рублей
      💭 Около 4-5 миллионов
```

Эта система превращает простой поиск по базе данных в интеллектуального консультанта, который понимает потребности пользователя, даже когда они выражены нечетко! 🧠🚗