#!/usr/bin/env python3
"""
Сервис для работы с Elasticsearch
"""
import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# Добавляем путь к модулям
sys.path.append(str(Path(__file__).parent.parent))

try:
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import bulk
    ELASTICSEARCH_AVAILABLE = True
except ImportError:
    ELASTICSEARCH_AVAILABLE = False

class ElasticsearchService:
    """Сервис для работы с Elasticsearch"""
    
    def __init__(self):
        self.es = None
        self.index_name = "cars"
        self._connect()
    
    def _connect(self):
        """Подключается к Elasticsearch"""
        if not ELASTICSEARCH_AVAILABLE:
            print("⚠️ Elasticsearch не установлен")
            return
        
        try:
            # Получаем хост и порт из переменных окружения (для Docker) или используем localhost
            es_host = os.environ.get("ELASTICSEARCH_HOST", "localhost")
            es_port = int(os.environ.get("ELASTICSEARCH_PORT", "9200"))
            
            self.es = Elasticsearch(
                hosts=[{"host": es_host, "port": es_port, "scheme": "http"}],
                request_timeout=30,
                max_retries=10,
                retry_on_timeout=True
            )
            
            if self.es.ping():
                print("✅ Подключение к Elasticsearch установлено")
            else:
                print("❌ Не удалось подключиться к Elasticsearch")
                self.es = None
                
        except Exception as e:
            print(f"❌ Ошибка подключения к Elasticsearch: {e}")
            self.es = None
    
    def is_available(self) -> bool:
        """Проверяет доступность Elasticsearch"""
        return self.es is not None and self.es.ping()
    
    def search_cars(self, 
                   query: str = "",
                   mark: Optional[str] = None,
                   model: Optional[str] = None,
                   city: Optional[str] = None,
                   fuel_type: Optional[str] = None,
                   body_type: Optional[str] = None,
                   gear_box_type: Optional[str] = None,
                   driving_gear_type: Optional[str] = None,
                   min_price: Optional[float] = None,
                   max_price: Optional[float] = None,
                   min_year: Optional[int] = None,
                   max_year: Optional[int] = None,
                   min_mileage: Optional[int] = None,
                   max_mileage: Optional[int] = None,
                   color: Optional[str] = None,
                   interior_color: Optional[str] = None,
                   options: Optional[str] = None,
                   car_type: Optional[str] = None,  # "car" или "used_car"
                   vin: Optional[str] = None,
                   engine: Optional[str] = None,
                   cargo_volume: Optional[str] = None,
                   door_qty: Optional[str] = None,
                   doors: Optional[str] = None,
                   fuel_consumption: Optional[str] = None,
                   max_torque: Optional[str] = None,
                   acceleration: Optional[str] = None,
                   max_speed: Optional[str] = None,
                   wheel_type: Optional[str] = None,
                   category: Optional[str] = None,
                   owners: Optional[int] = None,
                   accident: Optional[str] = None,
                   min_power: Optional[float] = None,
                   max_power: Optional[float] = None,
                   min_engine_vol: Optional[float] = None,
                   max_engine_vol: Optional[float] = None,
                   limit: int = 20,
                   offset: int = 0,
                   has_discount: Optional[bool] = None,
                   large_cargo: Optional[bool] = None,
                   small_cargo: Optional[bool] = None,
                   has_turbo: Optional[bool] = None,
                   min_clearance_cm: Optional[int] = None,
                   sport_style: Optional[bool] = None,
                   sort_by: Optional[str] = None,
                   superlative: Optional[str] = None,
                   show_all: bool = False,
                   sort_orders: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """Поиск автомобилей в Elasticsearch"""
        
        if not self.is_available():
            return {"hits": [], "total": 0, "error": "Elasticsearch недоступен"}
        
        # Строим запрос
        must_queries = []
        should_queries = []
        
        # Текстовый поиск (отключаем для запросов, которые содержат только фильтры)
        # Проверяем, является ли запрос только фильтром (без марки/модели для поиска)
        if query:
            # Проверяем, содержит ли запрос только фильтрующие слова
            filter_only_words = ['от', 'до', 'млн', 'миллион', 'тысяч', 'тыс', 'мощность', 'объем', 
                               'двигатель', 'л.с.', 'лс', 'год', 'старше', 'младше', 'больше', 'меньше',
                               'рублей', 'руб', 'автомобиль', 'машина', 'авто']
            query_lower = query.lower().strip()
            words_in_query = query_lower.split()
            
            # Проверяем, содержит ли запрос марки/модели (для текстового поиска)
            # Добавлены варианты транслитерации
            brand_words = ['toyota', 'тойота', 'тойот', 'bmw', 'бмв', 'бэмвэ', 'mercedes', 'мерседес', 'мерс',
                          'audi', 'ауди', 'volkswagen', 'фольксваген', 'фольк', 'volvo', 'вольво',
                          'hyundai', 'хёндай', 'хюндай', 'хендай', 'kia', 'киа', 'nissan', 'ниссан',
                          'mazda', 'мазда', 'мазд', 'ford', 'форд', 'honda', 'хонда', 'lexus', 'лексус',
                          'chevrolet', 'шевроле', 'шеви', 'opel', 'опель', 'peugeot', 'пежо', 'renault', 'рено',
                          'citroen', 'ситроен', 'ситрон', 'seat', 'сеат', 'skoda', 'скада', 'шкода',
                          'fiat', 'фиат', 'porsche', 'порше', 'geely', 'джили', 'гели',
                          'chery', 'чаери', 'черри', 'haval', 'хавал', 'great wall', 'gwm',
                          'dongfeng', 'донгфенг', 'донг фенг', 'omoda', 'омода', 'jac', 'як', 'джак',
                          'lada', 'ваз', 'лада', 'lifan', 'лифан', 'уаз', 'uaz', 'газ', 'gaz']
            has_brand = any(brand in query_lower for brand in brand_words)
            
            # Проверяем, содержит ли запрос только фильтры
            is_only_filter = (
                any(word in filter_only_words for word in words_in_query) and 
                not has_brand and
                not any(len(w) > 4 and w.isalpha() and w not in filter_only_words 
                       for w in words_in_query)
            )
            
            # Если это не только фильтр, добавляем текстовый поиск
            if not is_only_filter:
                # Используем улучшенный анализатор для текстового поиска
                should_queries.append({
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "mark^3",
                            "mark.autocomplete^2",
                            "model^3",
                            "model.autocomplete^2",
                            "description^1.5",
                            "city",
                            "color",
                            "interior_color",
                            "options",
                            "fuel_type",
                            "body_type",
                            "gear_box_type",
                            "driving_gear_type",
                            "vin",
                            "engine",
                            "cargo_volume",
                            "door_qty",
                            "doors",
                            "fuel_consumption",
                            "max_torque",
                            "acceleration",
                            "max_speed",
                            "wheel_type",
                            "category",
                            "dimensions"
                            # weight убран - это float поле, нельзя использовать fuzzy
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                        "operator": "or",
                        "minimum_should_match": "75%"
                    }
                })
                
                # Добавляем поиск по автодополнению для марок и моделей
                should_queries.append({
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "mark.autocomplete^1.5",
                            "model.autocomplete^1.5"
                        ],
                        "type": "phrase_prefix",
                        "fuzziness": "AUTO"
                    }
                })
        
        # Проверяем наличие строгих фильтров для логики minimum_should_match
        has_strict_filters = any([
            min_price is not None, max_price is not None,
            min_year is not None, max_year is not None,
            min_mileage is not None, max_mileage is not None,
            min_power is not None, max_power is not None,
            min_engine_vol is not None, max_engine_vol is not None,
            mark, model, city, fuel_type, body_type, gear_box_type, driving_gear_type,
            color, interior_color, vin, car_type
        ])
        
        # Фильтры по полям
        if mark:
            must_queries.append({
                "match": {
                    "mark": {
                        "query": mark,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if model:
            must_queries.append({
                "match": {
                    "model": {
                        "query": model,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if city:
            must_queries.append({
                "match": {
                    "city": {
                        "query": city,
                        "fuzziness": "AUTO"
                    }
                }
            })

        if color:
            # Цвет может быть в поле color или в description (если не указано явно "цвет кузова")
            # По умолчанию ищем в поле color
            must_queries.append({
                "match": {
                    "color": {
                        "query": color,
                        "fuzziness": "AUTO"
                    }
                }
            })
            # Также добавляем в should для поиска в description (на случай упоминания в тексте)
            should_queries.append({
                "match": {
                    "description": {
                        "query": color,
                        "fuzziness": "AUTO"
                    }
                }
            })

        if interior_color:
            must_queries.append({
                "match": {
                    "interior_color": {
                        "query": interior_color,
                        "fuzziness": "AUTO"
                    }
                }
            })
            # Также ищем в description
            should_queries.append({
                "match": {
                    "description": {
                        "query": interior_color,
                        "fuzziness": "AUTO"
                    }
                }
            })

        if options:
            # Опции могут быть в поле options или в description
            # Ищем в обоих местах
            should_queries.append({
                "match": {
                    "options": {
                        "query": options,
                        "fuzziness": "AUTO"
                    }
                }
            })
            should_queries.append({
                "match": {
                    "description": {
                        "query": options,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if fuel_type:
            # Тип топлива может быть в поле fuel_type или в description
            must_queries.append({
                "match": {
                    "fuel_type": {
                        "query": fuel_type,
                        "fuzziness": "AUTO"
                    }
                }
            })
            # Также ищем в description
            should_queries.append({
                "match": {
                    "description": {
                        "query": fuel_type,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if body_type:
            # Тип кузова может быть в поле body_type или в description
            # Сначала ищем в основном поле
            must_queries.append({
                "match": {
                    "body_type": {
                        "query": body_type,
                        "fuzziness": "AUTO"
                    }
                }
            })
            # Также ищем в description для случаев, когда кузов упоминается в тексте
            should_queries.append({
                "match": {
                    "description": {
                        "query": body_type,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if gear_box_type:
            # КПП может быть в поле gear_box_type или в description
            must_queries.append({
                "match": {
                    "gear_box_type": {
                        "query": gear_box_type,
                        "fuzziness": "AUTO"
                    }
                }
            })
            should_queries.append({
                "match": {
                    "description": {
                        "query": gear_box_type,
                        "fuzziness": "AUTO"
                    }
                }
            })

        if driving_gear_type:
            # Привод может быть в поле driving_gear_type или в description
            must_queries.append({
                "match": {
                    "driving_gear_type": {
                        "query": driving_gear_type,
                        "fuzziness": "AUTO"
                    }
                }
            })
            should_queries.append({
                "match": {
                    "description": {
                        "query": driving_gear_type,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if vin:
            must_queries.append({
                "wildcard": {
                    "vin": f"*{vin.upper()}*"
                }
            })
        
        # Фильтры по диапазонам (каждое поле отдельным range)
        if min_price is not None or max_price is not None:
            price_range = {}
            if min_price is not None:
                price_range["gte"] = float(min_price)
            if max_price is not None:
                price_range["lte"] = float(max_price)
            # Исключаем документы с null или нулевой ценой - используем exists для проверки наличия поля
            must_queries.append({
                "bool": {
                    "must": [
                        {"range": {"price": price_range}},
                        {"exists": {"field": "price"}}
                    ]
                }
            })

        if min_year is not None or max_year is not None:
            year_range = {}
            if min_year is not None:
                year_range["gte"] = min_year
            if max_year is not None:
                year_range["lte"] = max_year
            must_queries.append({"range": {"manufacture_year": year_range}})

        if min_mileage is not None or max_mileage is not None:
            mileage_range = {}
            if min_mileage is not None:
                mileage_range["gte"] = min_mileage
            if max_mileage is not None:
                mileage_range["lte"] = max_mileage
            must_queries.append({"range": {"mileage": mileage_range}})
        
        # Фильтр по типу автомобиля
        if car_type:
            must_queries.append({
                "term": {
                    "type": car_type
                }
            })
        
        # Фильтры по новым техническим полям
        if engine:
            must_queries.append({
                "match": {
                    "engine": {
                        "query": engine,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if cargo_volume:
            must_queries.append({
                "match": {
                    "cargo_volume": {
                        "query": cargo_volume,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if door_qty:
            must_queries.append({
                "match": {
                    "door_qty": door_qty
                }
            })
        
        if doors:
            must_queries.append({
                "match": {
                    "doors": doors
                }
            })
        
        if fuel_consumption:
            must_queries.append({
                "match": {
                    "fuel_consumption": {
                        "query": fuel_consumption,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if max_torque:
            must_queries.append({
                "match": {
                    "max_torque": {
                        "query": max_torque,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if acceleration:
            must_queries.append({
                "match": {
                    "acceleration": {
                        "query": acceleration,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if max_speed:
            must_queries.append({
                "match": {
                    "max_speed": {
                        "query": max_speed,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if wheel_type:
            must_queries.append({
                "match": {
                    "wheel_type": {
                        "query": wheel_type,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if category:
            must_queries.append({
                "match": {
                    "category": {
                        "query": category,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if accident:
            must_queries.append({
                "match": {
                    "accident": {
                        "query": accident,
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        if owners is not None:
            must_queries.append({
                "term": {
                    "owners": owners
                }
            })
        
        # Фильтры по диапазонам мощности и объема двигателя
        if min_power is not None or max_power is not None:
            power_range = {}
            if min_power is not None:
                power_range["gte"] = min_power
            if max_power is not None:
                power_range["lte"] = max_power
            must_queries.append({"range": {"power": power_range}})

        if min_engine_vol is not None or max_engine_vol is not None:
            # Учитываем, что данные могут быть в см³ (значения > 10), а фильтры в литрах
            engine_vol_range = {}
            if min_engine_vol is not None:
                # Конвертируем литры в см³ для фильтрации (если значение > 10, значит уже в см³)
                min_val_liters = min_engine_vol
                min_val_cc = min_val_liters * 1000  # минимальное значение в см³
                engine_vol_range["gte"] = min_val_cc * 0.9  # небольшой запас
            if max_engine_vol is not None:
                max_val_liters = max_engine_vol
                max_val_cc = max_val_liters * 1000  # максимальное значение в см³
                engine_vol_range["lte"] = max_val_cc * 1.1  # небольшой запас
            must_queries.append({"range": {"engine_vol": engine_vol_range}})
        
        # Новые фильтры
        
        # Фильтр по скидкам
        if has_discount:
            # Ищем автомобили с любыми скидками (хотя бы одно поле скидки > 0 или заполнено)
            discount_queries = []
            discount_fields = [
                "max_additional_discount", "max_discount_trade_in", "max_discount_credit",
                "max_discount_casko", "max_discount_extra_gear", "max_discount_life_insurance",
                "aaa_max_additional_discount", "aaa_max_discount_trade_in", "aaa_max_discount_credit",
                "aaa_max_discount_casko", "aaa_max_discount_extra_gear", "aaa_max_discount_life_insurance"
            ]
            for field in discount_fields:
                discount_queries.append({"exists": {"field": field}})
                # Также ищем упоминания скидок в description
            should_queries.append({
                "match": {
                    "description": {
                        "query": "скидка акция специальное предложение",
                        "operator": "or"
                    }
                }
            })
            # Добавляем хотя бы одно условие скидки
            must_queries.append({
                "bool": {
                    "should": discount_queries,
                    "minimum_should_match": 1
                }
            })
        
        # Фильтр по объему багажника
        if large_cargo:
            # Ищем упоминания большого багажника в description или cargo_volume
            should_queries.append({
                "match": {
                    "description": {
                        "query": "большой багажник просторный багажник большой объем багажника",
                        "operator": "or"
                    }
                }
            })
            should_queries.append({
                "wildcard": {
                    "cargo_volume": "*больш*"
                }
            })
        
        if small_cargo:
            should_queries.append({
                "match": {
                    "description": {
                        "query": "малый багажник небольшой багажник",
                        "operator": "or"
                    }
                }
            })
        
        # Фильтр по турбонаддуву
        if has_turbo:
            # Ищем в поле engine или description
            should_queries.append({
                "match": {
                    "engine": {
                        "query": "турбо наддув turbo",
                        "operator": "or",
                        "fuzziness": "AUTO"
                    }
                }
            })
            should_queries.append({
                "match": {
                    "description": {
                        "query": "турбонаддув турбо наддув turbo",
                        "operator": "or",
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        # Фильтр по клиренсу
        if min_clearance_cm is not None:
            # Ищем упоминания клиренса в description
            should_queries.append({
                "match": {
                    "description": {
                        "query": f"клиренс {min_clearance_cm} дорожный просвет {min_clearance_cm}",
                        "operator": "or"
                    }
                }
            })
        
        # Фильтр по спортивному стилю
        if sport_style:
            # Ищем в category или description
            should_queries.append({
                "match": {
                    "category": {
                        "query": "спортивный спорт",
                        "operator": "or",
                        "fuzziness": "AUTO"
                    }
                }
            })
            should_queries.append({
                "match": {
                    "description": {
                        "query": "спортивный спорт спортивная версия",
                        "operator": "or",
                        "fuzziness": "AUTO"
                    }
                }
            })
        
        # Строим финальный запрос
        bool_query = {}
        
        if must_queries:
            bool_query["must"] = must_queries
        
        # Добавляем should только если есть что добавлять
        if should_queries:
            bool_query["should"] = should_queries
            # Если есть строгие фильтры (цена, год, пробег и т.д.), текстовый поиск опционален
            # Если только текстовый поиск - требуется минимум 1 совпадение
            # Важно: если есть строгие фильтры, НЕ устанавливаем minimum_should_match
            # Это позволяет фильтрам работать строго, а текстовый поиск используется только для ранжирования
            if not has_strict_filters:
                # Если нет строгих фильтров, требуем совпадение текста
                bool_query["minimum_should_match"] = 1
        
        # Определяем сортировку
        # Если есть текстовый запрос - сортируем ТОЛЬКО по релевантности (_score)
        # Это гарантирует, что наиболее подходящие результаты будут первыми
        has_text_query = query and query.strip()
        
        # Определяем сортировку
        sort_order = []
        
        # Если есть явные sort_orders (из ИИ), используем их
        if sort_orders and isinstance(sort_orders, list):
            for sort_item in sort_orders:
                field = sort_item.get("field", "")
                direction = sort_item.get("direction", "desc")
                
                # Маппинг полей для Elasticsearch
                es_field_mapping = {
                    "price": "price",
                    "year": "manufacture_year",
                    "mileage": "mileage",
                    "power": "power",
                    "engine_vol": "engine_vol"
                }
                
                es_field = es_field_mapping.get(field, field)
                es_order = "desc" if direction == "desc" else "asc"
                
                sort_order.append({es_field: {"order": es_order}})
            
            # Добавляем сортировку по релевантности в конец, если есть текстовый запрос
            if has_text_query:
                sort_order.append({"_score": {"order": "desc"}})
        else:
            # Старая логика для обратной совместимости
            if has_text_query:
                # При текстовом запросе сортируем ТОЛЬКО по релевантности
                sort_order = [
                    {"_score": {"order": "desc"}}
                ]
            else:
                # Если нет текстового запроса, используем сортировку по цене по умолчанию
                sort_order = [
                    {"price": {"order": "asc"}}  # По умолчанию по возрастанию цены
                ]
            
            # Если запрошена явная сортировка по суперлативам - она имеет приоритет
            if sort_by == 'price_desc' or superlative == 'most_expensive':
                sort_order = [
                    {"price": {"order": "desc"}},  # Самые дорогие первые
                    {"_score": {"order": "desc"}} if has_text_query else None
                ]
                # Убираем None из списка
                sort_order = [s for s in sort_order if s is not None]
                if superlative == 'most_expensive':
                    limit = 1  # Только самая дорогая
            elif sort_by == 'price_asc' or superlative == 'cheapest':
                sort_order = [
                    {"price": {"order": "asc"}},  # Самые дешевые первые
                    {"_score": {"order": "desc"}} if has_text_query else None
                ]
                # Убираем None из списка
                sort_order = [s for s in sort_order if s is not None]
                if superlative == 'cheapest':
                    limit = 1  # Только самая дешевая
        
        search_body = {
            "query": {
                "bool": bool_query
            },
            "sort": sort_order,
            "from": offset,
            "size": limit,
            "_source": True
        }
        
        # Если запрос "покажи все" без фильтров - убираем все фильтры, показываем все
        if show_all and not bool_query.get("must") and not bool_query.get("should"):
            search_body["query"] = {"match_all": {}}
        
        try:
            response = self.es.search(
                index=self.index_name,
                body=search_body
            )
            
            hits = response['hits']['hits']
            total = response['hits']['total']['value']
            
            return {
                "hits": hits,
                "total": total,
                "took": response['took']
            }
            
        except Exception as e:
            return {
                "hits": [],
                "total": 0,
                "error": f"Ошибка поиска: {str(e)}"
            }
    
    def search_by_price_range(self, 
                            min_price: Optional[float] = None,
                            max_price: Optional[float] = None,
                            limit: int = 20) -> Dict[str, Any]:
        """Строгий поиск по диапазону цен"""
        
        if not self.is_available():
            return {"hits": [], "total": 0, "error": "Elasticsearch недоступен"}
        
        range_query = {}
        if min_price is not None:
            range_query["gte"] = min_price
        if max_price is not None:
            range_query["lte"] = max_price
        
        search_body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "range": {
                                "price": range_query
                            }
                        }
                    ]
                }
            },
            "sort": [
                {"price": {"order": "asc"}}
            ],
            "size": limit,
            "_source": True
        }
        
        try:
            response = self.es.search(
                index=self.index_name,
                body=search_body
            )
            
            hits = response['hits']['hits']
            total = response['hits']['total']['value']
            
            return {
                "hits": hits,
                "total": total,
                "took": response['took']
            }
            
        except Exception as e:
            return {
                "hits": [],
                "total": 0,
                "error": f"Ошибка поиска по цене: {str(e)}"
            }
    
    def search_by_vin(self, vin: str, limit: int = 10) -> Dict[str, Any]:
        """Поиск по VIN"""
        
        if not self.is_available():
            return {"hits": [], "total": 0, "error": "Elasticsearch недоступен"}
        
        # Нормализуем VIN
        normalized_vin = vin.strip().upper().replace(" ", "")
        
        search_body = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "term": {
                                "vin.keyword": normalized_vin
                            }
                        },
                        {
                            "wildcard": {
                                "vin": f"*{normalized_vin}*"
                            }
                        }
                    ]
                }
            },
            "size": limit,
            "_source": True
        }
        
        try:
            response = self.es.search(
                index=self.index_name,
                body=search_body
            )
            
            hits = response['hits']['hits']
            total = response['hits']['total']['value']
            
            return {
                "hits": hits,
                "total": total,
                "took": response['took']
            }
            
        except Exception as e:
            return {
                "hits": [],
                "total": 0,
                "error": f"Ошибка поиска по VIN: {str(e)}"
            }
    
    def get_aggregations(self, field: str, size: int = 20) -> Dict[str, Any]:
        """Получает агрегации по полю"""
        
        if not self.is_available():
            return {"buckets": [], "error": "Elasticsearch недоступен"}
        
        search_body = {
            "size": 0,
            "aggs": {
                "field_aggregation": {
                    "terms": {
                        "field": f"{field}.keyword",
                        "size": size
                    }
                }
            }
        }
        
        try:
            response = self.es.search(
                index=self.index_name,
                body=search_body
            )
            
            buckets = response['aggregations']['field_aggregation']['buckets']
            
            return {
                "buckets": buckets
            }
            
        except Exception as e:
            return {
                "buckets": [],
                "error": f"Ошибка получения агрегаций: {str(e)}"
            }
    
    def get_price_stats(self) -> Dict[str, Any]:
        """Получает статистику по ценам"""
        
        if not self.is_available():
            return {"error": "Elasticsearch недоступен"}
        
        search_body = {
            "size": 0,
            "aggs": {
                "price_stats": {
                    "stats": {
                        "field": "price"
                    }
                },
                "price_histogram": {
                    "histogram": {
                        "field": "price",
                        "interval": 500000
                    }
                }
            }
        }
        
        try:
            response = self.es.search(
                index=self.index_name,
                body=search_body
            )
            
            stats = response['aggregations']['price_stats']
            histogram = response['aggregations']['price_histogram']['buckets']
            
            return {
                "stats": stats,
                "histogram": histogram
            }
            
        except Exception as e:
            return {
                "error": f"Ошибка получения статистики: {str(e)}"
            }
    
    def suggest_queries(self, query: str, size: int = 5) -> List[str]:
        """Предлагает варианты запросов"""
        
        if not self.is_available():
            return []
        
        search_body = {
            "suggest": {
                "car_suggest": {
                    "prefix": query,
                    "completion": {
                        "field": "suggest",
                        "size": size
                    }
                }
            }
        }
        
        try:
            response = self.es.search(
                index=self.index_name,
                body=search_body
            )
            
            suggestions = response['suggest']['car_suggest'][0]['options']
            return [s['text'] for s in suggestions]
            
        except Exception as e:
            print(f"Ошибка получения предложений: {e}")
            return []
