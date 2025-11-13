#!/usr/bin/env python3
"""
Настройка и интеграция Elasticsearch для улучшенного поиска автомобилей
"""
import sys
from pathlib import Path
import json
from datetime import datetime

# Добавляем путь к модулям
sys.path.append(str(Path(__file__).parent))

import re
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Используем прямое подключение к БД без настроек
def get_database_url():
    # ПРИОРИТЕТ: переменные окружения (установленные явно) > .env файл
    # Сначала проверяем переменные окружения (не перезаписываются .env)
    postgres_user = os.environ.get("POSTGRES_USER") or os.environ.get("POSTGRES_DB_USER")
    postgres_password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("POSTGRES_DB_PASSWORD")
    postgres_host = os.environ.get("POSTGRES_HOST") or os.environ.get("POSTGRES_DB_HOST")
    postgres_port = os.environ.get("POSTGRES_PORT") or os.environ.get("POSTGRES_DB_PORT")
    postgres_db = os.environ.get("POSTGRES_DB") or os.environ.get("POSTGRES_DB_NAME")
    db_url = os.environ.get("DATABASE_URL")
    
    # Если переменные окружения установлены, используем их
    if postgres_user and postgres_password and postgres_host:
        if db_url:
            return db_url
        return f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port or '5432'}/{postgres_db or 'vectordb'}"
    
    # Если переменные не установлены, загружаем .env (но override=False чтобы не перезаписать существующие)
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)  # override=False - не перезаписывает существующие
    
    # Повторно читаем (теперь из .env если не было в окружении)
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url
    
    postgres_user = os.getenv("POSTGRES_USER") or os.getenv("POSTGRES_DB_USER") or "postgres"
    postgres_password = os.getenv("POSTGRES_PASSWORD") or os.getenv("POSTGRES_DB_PASSWORD") or "password"
    postgres_host = os.getenv("POSTGRES_HOST") or os.getenv("POSTGRES_DB_HOST") or "localhost"
    postgres_port = os.getenv("POSTGRES_PORT") or os.getenv("POSTGRES_DB_PORT") or "5432"
    postgres_db = os.getenv("POSTGRES_DB") or os.getenv("POSTGRES_DB_NAME") or "vectordb"
    
    return f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"

def get_db_session():
    """Создает сессию БД с правильными настройками подключения"""
    db_url = get_database_url()
    host_info = db_url.split('@')[1] if '@' in db_url else 'скрыто'
    print(f"🔍 Подключение к БД: {host_info}")
    
    # Создаем свой engine с правильными настройками
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20,
        echo=False
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()

try:
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import bulk
    ELASTICSEARCH_AVAILABLE = True
except ImportError:
    ELASTICSEARCH_AVAILABLE = False
    print("⚠️ Elasticsearch не установлен. Установите: pip install elasticsearch")

def get_elasticsearch_client():
    """Создает клиент Elasticsearch с учетом переменных окружения"""
    es_host = os.environ.get("ELASTICSEARCH_HOST", "localhost")
    es_port = int(os.environ.get("ELASTICSEARCH_PORT", "9200"))
    
    return Elasticsearch(
        hosts=[{"host": es_host, "port": es_port, "scheme": "http"}],
        request_timeout=30,
        max_retries=10,
        retry_on_timeout=True
    )

# Импортируем модели ПОСЛЕ настройки подключения к БД
# Это важно, чтобы models не использовали неправильные настройки из config.py

def setup_elasticsearch():
    """Настраивает подключение к Elasticsearch"""
    if not ELASTICSEARCH_AVAILABLE:
        print("❌ Elasticsearch недоступен")
        return None
    
    try:
        # Подключение к Elasticsearch (используем функцию с поддержкой переменных окружения)
        es = get_elasticsearch_client()
        
        # Проверка подключения
        if es.ping():
            print("✅ Подключение к Elasticsearch установлено")
            return es
        else:
            print("❌ Не удалось подключиться к Elasticsearch")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка подключения к Elasticsearch: {e}")
        return None

def create_cars_index(es):
    """Создает индекс для автомобилей в Elasticsearch с улучшенными анализаторами"""
    if not es:
        return False
    
    index_name = "cars"
    
    # Импортируем Path для работы с файлами
    from pathlib import Path
    
    # Маппинг полей для автомобилей
    mapping = {
        "mappings": {
            "properties": {
                "id": {"type": "integer"},
                "mark": {
                    "type": "text",
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "autocomplete": {
                            "type": "text",
                            "analyzer": "ru_en_analyzer_autocomplete",
                            "search_analyzer": "ru_en_analyzer"
                        }
                    }
                },
                "model": {
                    "type": "text", 
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "autocomplete": {
                            "type": "text",
                            "analyzer": "ru_en_analyzer_autocomplete",
                            "search_analyzer": "ru_en_analyzer"
                        }
                    }
                },
                "manufacture_year": {"type": "integer"},
                "price": {"type": "float"},
                "city": {
                    "type": "text",
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "fuel_type": {
                    "type": "text",
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "body_type": {
                    "type": "text",
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "gear_box_type": {
                    "type": "text",
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "driving_gear_type": {
                    "type": "text",
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "engine_vol": {"type": "float"},
                "power": {"type": "float"},
                "color": {
                    "type": "text",
                    "analyzer": "russian",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "interior_color": {
                    "type": "text",
                    "analyzer": "russian",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "vin": {
                    "type": "text",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "dealer_center": {
                    "type": "text",
                    "analyzer": "russian",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "compl_level": {
                    "type": "text",
                    "analyzer": "russian"
                },
                "eco_class": {
                    "type": "text",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "weight": {"type": "float"},
                "dimensions": {"type": "text"},
                "cargo_volume": {"type": "text"},
                "door_qty": {"type": "text"},
                "doors": {"type": "text"},
                "engine": {"type": "text", "analyzer": "russian"},
                "fuel_consumption": {"type": "text"},
                "max_torque": {"type": "text"},
                "acceleration": {"type": "text"},
                "max_speed": {"type": "text"},
                "wheel_type": {"type": "text", "analyzer": "russian"},
                "category": {"type": "text", "analyzer": "russian"},
                "owners": {"type": "integer"},
                "accident": {"type": "text", "analyzer": "russian"},
                "type": {"type": "keyword"},  # "car" или "used_car"
                "created_at": {"type": "date"},
                "description": {
                    "type": "text",
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "options": {
                    "type": "text",
                    "analyzer": "ru_en_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"}
                    }
                },
                "embedding": {
                    "type": "dense_vector",
                    "dims": 384,
                    "index": True,
                    "similarity": "cosine"
                }
            }
        },
        "settings": {
            "analysis": {
                "analyzer": {
                    "russian": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "russian_stop",
                            "russian_stemmer"
                        ]
                    },
                    "ru_en_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "russian_stop",
                            "english_stop",
                            "russian_stemmer",
                            "english_stemmer",
                            "ru_en_synonyms"
                        ]
                    },
                    "ru_en_analyzer_autocomplete": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "russian_stop",
                            "english_stop",
                            "russian_stemmer",
                            "english_stemmer",
                            "ru_en_synonyms",
                            "autocomplete_filter"
                        ]
                    }
                },
                "filter": {
                    "russian_stop": {
                        "type": "stop",
                        "stopwords": "_russian_"
                    },
                    "english_stop": {
                        "type": "stop",
                        "stopwords": "_english_"
                    },
                    "russian_stemmer": {
                        "type": "stemmer",
                        "language": "russian"
                    },
                    "english_stemmer": {
                        "type": "stemmer",
                        "language": "english"
                    },
                    "ru_en_synonyms": {
                        "type": "synonym_graph",
                        "synonyms": [
                            "bmw, бмв, beemer, beamer, бэмвэ",
                            "mercedes, мерседес, мерс, mercedes-benz",
                            "audi, ауди",
                            "volkswagen, фольксваген, фольк, vw",
                            "toyota, тойота, тойот",
                            "hyundai, хёндай, хюндай, хендай",
                            "kia, киа",
                            "nissan, ниссан",
                            "mazda, мазда, мазд",
                            "ford, форд",
                            "honda, хонда",
                            "lexus, лексус",
                            "lada, ваз, лада",
                            "gaz, газ",
                            "uaz, уаз",
                            "седан, sedan",
                            "хэтчбек, хетчбек, hatchback",
                            "кроссовер, crossover, suv",
                            "внедорожник, внедорож, off-road, 4x4",
                            "универсал, wagon, estate",
                            "автомат, автоматическая, акпп, automatic, at",
                            "механика, механическая, мкпп, manual, mt",
                            "бензин, petrol, gasoline, gas",
                            "дизель, diesel",
                            "гибрид, hybrid",
                            "электрический, electric, ev",
                            "полный, 4wd, awd, all-wheel drive, полный привод",
                            "передний, fwd, front-wheel drive, передний привод",
                            "задний, rwd, rear-wheel drive, задний привод"
                        ],
                        "expand": True,
                        "lenient": True
                    },
                    "autocomplete_filter": {
                        "type": "edge_ngram",
                        "min_gram": 2,
                        "max_gram": 20
                    }
                }
            }
        }
    }
    
    try:
        # Загружаем файл синонимов в Elasticsearch
        # Создаем директорию для анализаторов, если её нет
        synonyms_content = ""
        try:
            synonyms_path = Path(__file__).parent / "elasticsearch" / "synonyms.txt"
            if synonyms_path.exists():
                with open(synonyms_path, "r", encoding="utf-8") as f:
                    synonyms_content = f.read()
                print(f"✅ Загружен файл синонимов: {synonyms_path}")
            else:
                print(f"⚠️ Файл синонимов не найден: {synonyms_path}, создаю базовый файл")
                # Создаем базовый файл синонимов
                synonyms_path.parent.mkdir(exist_ok=True)
                with open(synonyms_path, "w", encoding="utf-8") as f:
                    f.write("# Синонимы для марок автомобилей\n")
                    f.write("bmw, бмв, beemer\n")
                    f.write("mercedes, мерседес, мерс\n")
                synonyms_content = "bmw, бмв, beemer\nmercedes, мерседес, мерс"
        except Exception as e:
            print(f"⚠️ Ошибка загрузки файла синонимов: {e}, используем встроенные синонимы")
        
        # Удаляем индекс если существует
        if es.indices.exists(index=index_name):
            es.indices.delete(index=index_name)
            print(f"✅ Удален существующий индекс {index_name}")
        
        # Создаем новый индекс
        es.indices.create(index=index_name, body=mapping)
        print(f"✅ Создан индекс {index_name} с улучшенными анализаторами (ru_en_analyzer)")
        
        # Если есть файл синонимов, загружаем его через API
        # Примечание: Elasticsearch требует, чтобы файл синонимов был в конфигурационной директории
        # Для Docker это может быть сложнее, поэтому используем inline синонимы
        if synonyms_content:
            try:
                # Обновляем настройки индекса с inline синонимами (если файл недоступен)
                # Это временное решение - в продакшене лучше использовать файл
                print(f"ℹ️ Для использования синонимов убедитесь, что файл synonyms.txt находится в конфигурационной директории Elasticsearch")
            except Exception as e:
                print(f"⚠️ Не удалось настроить синонимы: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания индекса: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_car_options(engine, car_id):
    """Получает опции автомобиля через raw SQL"""
    from sqlalchemy import text
    if not car_id:
        return ""
    with engine.connect() as conn:
        options = [opt[0] or "" for opt in conn.execute(text(
            "SELECT description FROM car_options WHERE car_id = :car_id"
        ), {"car_id": car_id}).fetchall()]
        groups = [grp[0] or "" for grp in conn.execute(text(
            "SELECT name FROM car_options_groups WHERE car_id = :car_id"
        ), {"car_id": car_id}).fetchall()]
        return " ".join(options + groups).strip()

def _to_float_or_none(value):
    """Пытается привести значение к float.
    Поддерживает строки с диапазонами и нецифровыми символами: '1655–1690', '1,5 л', '1499'.
    Возвращает первое найденное число, иначе None.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).replace(',', '.')
        # Заменяем длинные тире на дефис
        text = text.replace('–', '-').replace('—', '-')
        # Ищем первое число (целое или с точкой)
        match = re.search(r"(\d+\.?\d*)", text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

def index_cars_to_elasticsearch(es):
    """Индексирует автомобили в Elasticsearch"""
    if not es:
        return False
    
    print("🚀 ИНДЕКСАЦИЯ АВТОМОБИЛЕЙ В ELASTICSEARCH")
    print("=" * 50)
    
    # Подключение к БД (создаем свой engine напрямую)
    db_url = get_database_url()
    print(f"🔍 Подключение к БД: {db_url.split('@')[1] if '@' in db_url else 'скрыто'}")
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20,
        echo=False
    )
    
    try:
        # Используем raw SQL чтобы избежать проблем с импортом моделей
        from sqlalchemy import text
        
        # Проверяем существование таблиц и получаем данные через raw SQL
        with engine.connect() as conn:
            # Проверяем существование таблиц (учитываем схему public)
            check_cars = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'cars'
                )
            """)).scalar()
            check_used_cars = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'used_cars'
                )
            """)).scalar()
            
            if not check_cars or not check_used_cars:
                print(f"❌ Таблицы не найдены! cars={check_cars}, used_cars={check_used_cars}")
                print("   Нужно сначала запустить миграцию данных!")
                # Проверим, какие таблицы вообще есть
                try:
                    existing_tables = conn.execute(text("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public'
                        ORDER BY table_name
                    """)).fetchall()
                    if existing_tables:
                        print(f"   Найденные таблицы: {[t[0] for t in existing_tables]}")
                except:
                    pass
                return False
            
            # Получаем данные через raw SQL
            cars_result = conn.execute(text("SELECT * FROM cars"))
            cars_data = cars_result.fetchall()
            # Получаем имена колонок из метаданных результата
            cars_columns = list(cars_result.keys()) if hasattr(cars_result, 'keys') else [desc[0] for desc in cars_result.cursor.description]
            total_cars = len(cars_data)
            
            used_cars_result = conn.execute(text("SELECT * FROM used_cars"))
            used_cars_data = used_cars_result.fetchall()
            used_cars_columns = list(used_cars_result.keys()) if hasattr(used_cars_result, 'keys') else [desc[0] for desc in used_cars_result.cursor.description]
            total_used_cars = len(used_cars_data)
        
        print(f"📊 Найдено автомобилей:")
        print(f"   - Новых: {total_cars}")
        print(f"   - Подержанных: {total_used_cars}")
        print(f"   - Всего: {total_cars + total_used_cars}")
        
        # Подготавливаем данные для индексации
        documents = []
        
        # Новые автомобили
        print("\n🚗 Индексация новых автомобилей...")
        
        # Создаем словарь для быстрого доступа к колонкам
        cars_col_dict = {col: idx for idx, col in enumerate(cars_columns)}
        
        for car_row in cars_data:
            # Преобразуем row в словарь
            car = {col: car_row[cars_col_dict[col]] for col in cars_columns}
            doc = {
                "_index": "cars",
                "_id": f"car_{car.get('id')}",
                "_source": {
                    "id": car.get('id'),
                    "mark": car.get('mark') or "",
                    "model": car.get('model') or "",
                    "manufacture_year": car.get('manufacture_year'),
                    "price": _to_float_or_none(car.get('price')),
                    "city": car.get('city') or "",
                    "fuel_type": car.get('fuel_type') or "",
                    "body_type": car.get('body_type') or "",
                    "gear_box_type": car.get('gear_box_type') or "",
                    "driving_gear_type": car.get('driving_gear_type') or "",
                    "engine_vol": _to_float_or_none(car.get('engine_vol')),
                    "power": _to_float_or_none(car.get('power')),
                    "color": car.get('color') or "",
                    "interior_color": car.get('interior_color') or "",
                    "vin": car.get('vin') or "",
                    "dealer_center": car.get('dealer_center') or "",
                    "compl_level": car.get('compl_level') or "",
                    "eco_class": car.get('eco_class') or "",
                    "weight": _to_float_or_none(car.get('weight')),
                    "dimensions": car.get('dimensions') or "",
                    "cargo_volume": car.get('cargo_volume') or "",
                    "door_qty": car.get('door_qty') or "",
                    "engine": car.get('engine') or "",
                    "fuel_consumption": car.get('fuel_consumption') or "",
                    "max_torque": car.get('max_torque') or "",
                    "acceleration": car.get('acceleration') or "",
                    "max_speed": car.get('max_speed') or "",
                    "type": "car",
                    "created_at": datetime.now().isoformat(),
                    "description": create_car_description_from_dict(car),
                    "options": get_car_options(engine, car.get('id'))
                }
            }
            documents.append(doc)
        
        # Подержанные автомобили
        print("🚙 Индексация подержанных автомобилей...")
        
        used_cars_col_dict = {col: idx for idx, col in enumerate(used_cars_columns)}
        
        for car_row in used_cars_data:
            car = {col: car_row[used_cars_col_dict[col]] for col in used_cars_columns}
            doc = {
                "_index": "cars",
                "_id": f"used_car_{car.get('id')}",
                "_source": {
                    "id": car.get('id'),
                    "mark": car.get('mark') or "",
                    "model": car.get('model') or "",
                    "manufacture_year": car.get('manufacture_year'),
                    "price": _to_float_or_none(car.get('price')),
                    "city": car.get('city') or "",
                    "fuel_type": car.get('fuel_type') or "",
                    "body_type": car.get('body_type') or "",
                    "gear_box_type": car.get('gear_box_type') or "",
                    "driving_gear_type": car.get('driving_gear_type') or "",
                    "engine_vol": _to_float_or_none(car.get('engine_vol')),
                    "power": _to_float_or_none(car.get('power')),
                    "color": car.get('color') or "",
                    "vin": car.get('vin') or "",
                    "dealer_center": car.get('dealer_center') or "",
                    "compl_level": car.get('compl_level') or "",
                    "eco_class": car.get('eco_class') or "",
                    "weight": _to_float_or_none(car.get('weight')),
                    "dimensions": car.get('dimensions') or "",
                    "doors": car.get('doors') or "",
                    "wheel_type": car.get('wheel_type') or "",
                    "category": car.get('category') or "",
                    "type": "used_car",
                    "mileage": car.get('mileage'),
                    "owners": car.get('owners'),
                    "accident": car.get('accident') or "",
                    "certification_number": car.get('certification_number') or "",
                    "region": car.get('region') or "",
                    "created_at": datetime.now().isoformat(),
                    "description": create_used_car_description_from_dict(car)
                }
            }
            documents.append(doc)
        
        # Массовая индексация
        print(f"\n📤 Загрузка {len(documents)} документов в Elasticsearch...")
        
        success_count, failed_items = bulk(es, documents, chunk_size=100, refresh=True)
        
        print(f"✅ Успешно проиндексировано: {success_count} документов")
        if failed_items:
            print(f"❌ Ошибок: {len(failed_items)}")
            for item in failed_items[:5]:  # Показываем первые 5 ошибок
                print(f"   - {item}")
        
        # Обновляем индекс и проверяем количество документов
        try:
            es.indices.refresh(index="cars")
        except Exception:
            pass
        count_result = es.count(index="cars")
        print(f"📊 Всего документов в индексе: {count_result['count']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка индексации: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_car_description_from_dict(car):
    """Создает подробное описание автомобиля для поиска из словаря"""
    parts = []
    
    # Марка и модель
    if car.get('mark') and car.get('model'):
        parts.append(f"{car.get('mark')} {car.get('model')}")
    elif car.get('mark'):
        parts.append(car.get('mark'))
    
    # Год выпуска
    if car.get('manufacture_year'):
        parts.append(f"{car.get('manufacture_year')} года")
    
    # Цена
    if car.get('price'):
        try:
            price_val = float(car.get('price'))
            if price_val >= 1_000_000:
                parts.append(f"цена {price_val/1_000_000:.1f} миллион рублей")
            else:
                parts.append(f"цена {price_val:,.0f} рублей")
        except:
            parts.append(f"цена {car.get('price')} рублей")
    
    # Цвет
    if car.get('color'):
        parts.append(f"цвет {car.get('color')}")
    
    if car.get('interior_color'):
        parts.append(f"салон {car.get('interior_color')}")
    
    # Топливо
    fuel_type_raw = car.get('fuel_type')
    fuel = str(fuel_type_raw).lower() if fuel_type_raw else ''
    if fuel and fuel != 'none':
        parts.append(f"топливо {fuel}")
        if 'бензин' in fuel or 'petrol' in fuel:
            parts.append("бензиновый")
        elif 'дизель' in fuel or 'diesel' in fuel:
            parts.append("дизельный")
        elif 'электр' in fuel or 'electric' in fuel:
            parts.append("электрический электромобиль")
        elif 'гибрид' in fuel or 'hybrid' in fuel:
            parts.append("гибридный")
    
    # Кузов
    if car.get('body_type'):
        body = car.get('body_type').lower()
        parts.append(f"кузов {body}")
        # Синонимы
        if 'внедорожник' in body or 'suv' in body:
            parts.append("внедорожник SUV")
        elif 'кроссовер' in body:
            parts.append("кроссовер")
        elif 'седан' in body:
            parts.append("седан")
        elif 'хэтчбек' in body or 'хетчбек' in body:
            parts.append("хэтчбек")
        elif 'универсал' in body:
            parts.append("универсал")
        elif 'купе' in body:
            parts.append("купе")
    
    # Коробка передач
    if car.get('gear_box_type'):
        gear = car.get('gear_box_type').lower()
        parts.append(f"коробка {gear}")
        if 'автомат' in gear or 'automatic' in gear:
            parts.append("автоматическая коробка автомат")
        elif 'механик' in gear or 'manual' in gear:
            parts.append("механическая коробка механика")
        elif 'вариатор' in gear or 'cvt' in gear:
            parts.append("вариатор CVT")
        elif 'робот' in gear or 'robot' in gear:
            parts.append("роботизированная коробка робот")
    
    # Привод
    if car.get('driving_gear_type'):
        drive = car.get('driving_gear_type').lower()
        parts.append(f"привод {drive}")
        if 'полн' in drive or 'full' in drive or '4wd' in drive or 'awd' in drive:
            parts.append("полный привод 4WD AWD")
        elif 'передн' in drive or 'front' in drive:
            parts.append("передний привод FWD")
        elif 'задн' in drive or 'rear' in drive or 'rwd' in drive:
            parts.append("задний привод RWD")
    
    # Объем двигателя (конвертируем из см³ в литры если нужно)
    engine_vol = car.get('engine_vol')
    if engine_vol:
        try:
            vol_val = float(engine_vol)
            # Если значение больше 10, вероятно это см³, конвертируем в литры
            if vol_val > 10:
                vol_liters = vol_val / 1000.0
                parts.append(f"двигатель {vol_liters:.1f} литр {vol_liters:.1f}л")
                parts.append(f"объем {vol_liters:.1f} литр")
            else:
                parts.append(f"двигатель {vol_val:.1f} литр {vol_val:.1f}л")
                parts.append(f"объем {vol_val:.1f} литр")
        except:
            parts.append(f"двигатель {engine_vol}")
    
    # Мощность
    if car.get('power'):
        try:
            power_val = float(car.get('power'))
            parts.append(f"мощность {power_val:.0f} л.с. {power_val:.0f}лс")
            parts.append(f"{power_val:.0f} лошадиных сил")
        except:
            parts.append(f"мощность {car.get('power')}лс")
    
    # Город
    if car.get('city'):
        parts.append(f"город {car.get('city')}")
    
    # VIN
    if car.get('vin'):
        parts.append(f"VIN {car.get('vin')}")
    
    # Дополнительные поля
    if car.get('weight'):
        parts.append(f"вес {car.get('weight')}")
    
    if car.get('dimensions'):
        parts.append(f"размеры {car.get('dimensions')}")
    
    if car.get('cargo_volume'):
        parts.append(f"объем багажника {car.get('cargo_volume')}")
    
    if car.get('door_qty') or car.get('doors'):
        doors = car.get('door_qty') or car.get('doors')
        parts.append(f"дверей {doors}")
    
    if car.get('fuel_consumption'):
        parts.append(f"расход {car.get('fuel_consumption')}")
    
    if car.get('max_torque'):
        parts.append(f"крутящий момент {car.get('max_torque')}")
    
    if car.get('acceleration'):
        parts.append(f"разгон {car.get('acceleration')}")
    
    if car.get('max_speed'):
        parts.append(f"максимальная скорость {car.get('max_speed')}")
    
    if car.get('wheel_type'):
        parts.append(f"руль {car.get('wheel_type')}")
    
    if car.get('compl_level'):
        parts.append(f"комплектация {car.get('compl_level')}")
    
    if car.get('eco_class'):
        parts.append(f"экокласс {car.get('eco_class')}")
    
    if car.get('engine'):
        parts.append(f"мотор {car.get('engine')}")
    
    return " ".join(parts)

def create_car_description(car):
    """Создает описание автомобиля для поиска (старая версия для совместимости)"""
    if isinstance(car, dict):
        return create_car_description_from_dict(car)
    parts = []
    
    if car.mark and car.model:
        parts.append(f"{car.mark} {car.model}")
    elif car.mark:
        parts.append(car.mark)
    
    if car.manufacture_year:
        parts.append(f"{car.manufacture_year} года")
    
    if car.color:
        parts.append(f"цвет {car.color}")
    
    if car.fuel_type:
        parts.append(f"топливо {car.fuel_type}")
    
    if car.body_type:
        parts.append(f"кузов {car.body_type}")
    
    if car.gear_box_type:
        parts.append(f"коробка {car.gear_box_type}")
    
    if car.driving_gear_type:
        parts.append(f"привод {car.driving_gear_type}")
    
    if car.engine_vol:
        parts.append(f"двигатель {car.engine_vol}л")
    
    if car.power:
        parts.append(f"мощность {car.power}лс")
    
    if car.price:
        parts.append(f"цена {car.price} рублей")
    
    if car.city:
        parts.append(f"город {car.city}")
    
    if car.vin:
        parts.append(f"VIN {car.vin}")
    
    return " ".join(parts)

def create_used_car_description_from_dict(car):
    """Создает подробное описание подержанного автомобиля для поиска из словаря"""
    parts = []
    
    # Марка и модель
    if car.get('mark') and car.get('model'):
        parts.append(f"{car.get('mark')} {car.get('model')}")
    
    # Год выпуска
    if car.get('manufacture_year'):
        parts.append(f"{car.get('manufacture_year')} года")
    
    # Пробег
    if car.get('mileage'):
        try:
            mileage_val = int(car.get('mileage'))
            if mileage_val >= 1000:
                parts.append(f"пробег {mileage_val//1000} тысяч км {mileage_val}км")
            else:
                parts.append(f"пробег {mileage_val}км")
        except:
            parts.append(f"пробег {car.get('mileage')}км")
    
    # Цена
    if car.get('price'):
        try:
            price_val = float(car.get('price'))
            if price_val >= 1_000_000:
                parts.append(f"цена {price_val/1_000_000:.1f} миллион рублей")
            else:
                parts.append(f"цена {price_val:,.0f} рублей")
        except:
            parts.append(f"цена {car.get('price')} рублей")
    
    # Цвет
    if car.get('color'):
        parts.append(f"цвет {car.get('color')}")
    
    # Топливо
    fuel_type_raw = car.get('fuel_type')
    fuel = str(fuel_type_raw).lower() if fuel_type_raw else ''
    if fuel and fuel != 'none':
        parts.append(f"топливо {fuel}")
        if 'бензин' in fuel or 'petrol' in fuel:
            parts.append("бензиновый")
        elif 'дизель' in fuel or 'diesel' in fuel:
            parts.append("дизельный")
        elif 'электр' in fuel or 'electric' in fuel:
            parts.append("электрический электромобиль")
        elif 'гибрид' in fuel or 'hybrid' in fuel:
            parts.append("гибридный")
    
    # Кузов
    if car.get('body_type'):
        body = car.get('body_type').lower()
        parts.append(f"кузов {body}")
        # Синонимы
        if 'внедорожник' in body or 'suv' in body:
            parts.append("внедорожник SUV")
        elif 'кроссовер' in body:
            parts.append("кроссовер")
        elif 'седан' in body:
            parts.append("седан")
        elif 'хэтчбек' in body or 'хетчбек' in body:
            parts.append("хэтчбек")
        elif 'универсал' in body:
            parts.append("универсал")
        elif 'купе' in body:
            parts.append("купе")
    
    # Коробка передач
    if car.get('gear_box_type'):
        gear = car.get('gear_box_type').lower()
        parts.append(f"коробка {gear}")
        if 'автомат' in gear or 'automatic' in gear:
            parts.append("автоматическая коробка автомат")
        elif 'механик' in gear or 'manual' in gear:
            parts.append("механическая коробка механика")
        elif 'вариатор' in gear or 'cvt' in gear:
            parts.append("вариатор CVT")
        elif 'робот' in gear or 'robot' in gear:
            parts.append("роботизированная коробка робот")
    
    # Привод
    if car.get('driving_gear_type'):
        drive = car.get('driving_gear_type').lower()
        parts.append(f"привод {drive}")
        if 'полн' in drive or 'full' in drive or '4wd' in drive or 'awd' in drive:
            parts.append("полный привод 4WD AWD")
        elif 'передн' in drive or 'front' in drive:
            parts.append("передний привод FWD")
        elif 'задн' in drive or 'rear' in drive or 'rwd' in drive:
            parts.append("задний привод RWD")
    
    # Объем двигателя (конвертируем из см³ в литры если нужно)
    engine_vol = car.get('engine_vol')
    if engine_vol:
        try:
            vol_val = float(engine_vol)
            # Если значение больше 10, вероятно это см³, конвертируем в литры
            if vol_val > 10:
                vol_liters = vol_val / 1000.0
                parts.append(f"двигатель {vol_liters:.1f} литр {vol_liters:.1f}л")
                parts.append(f"объем {vol_liters:.1f} литр")
            else:
                parts.append(f"двигатель {vol_val:.1f} литр {vol_val:.1f}л")
                parts.append(f"объем {vol_val:.1f} литр")
        except:
            parts.append(f"двигатель {engine_vol}")
    
    # Мощность
    if car.get('power'):
        try:
            power_val = float(car.get('power'))
            parts.append(f"мощность {power_val:.0f} л.с. {power_val:.0f}лс")
            parts.append(f"{power_val:.0f} лошадиных сил")
        except:
            parts.append(f"мощность {car.get('power')}лс")
    
    # Город и регион
    if car.get('city'):
        parts.append(f"город {car.get('city')}")
    
    if car.get('region'):
        parts.append(f"регион {car.get('region')}")
    
    # VIN
    if car.get('vin'):
        parts.append(f"VIN {car.get('vin')}")
    
    # Специфичные для подержанных авто поля
    if car.get('owners'):
        parts.append(f"владельцев {car.get('owners')}")
    
    if car.get('accident'):
        acc = str(car.get('accident')).lower()
        if 'нет' not in acc and 'не было' not in acc and acc.strip():
            parts.append(f"дтп {car.get('accident')}")
    
    if car.get('certification_number'):
        parts.append(f"сертификат {car.get('certification_number')}")
    
    # Дополнительные поля
    if car.get('weight'):
        parts.append(f"вес {car.get('weight')}")
    
    if car.get('dimensions'):
        parts.append(f"размеры {car.get('dimensions')}")
    
    if car.get('doors'):
        parts.append(f"дверей {car.get('doors')}")
    
    if car.get('wheel_type'):
        parts.append(f"руль {car.get('wheel_type')}")
    
    if car.get('category'):
        parts.append(f"категория {car.get('category')}")
    
    if car.get('dealer_center'):
        parts.append(f"дилер {car.get('dealer_center')}")
    
    return " ".join(parts)

def create_used_car_description(car):
    """Создает описание подержанного автомобиля для поиска (старая версия для совместимости)"""
    if isinstance(car, dict):
        return create_used_car_description_from_dict(car)
    parts = []
    
    if car.mark and car.model:
        parts.append(f"{car.mark} {car.model}")
    
    if car.manufacture_year:
        parts.append(f"{car.manufacture_year} года")
    
    if car.mileage:
        parts.append(f"пробег {car.mileage}км")
    
    if car.color:
        parts.append(f"цвет {car.color}")
    
    if car.fuel_type:
        parts.append(f"топливо {car.fuel_type}")
    
    if car.body_type:
        parts.append(f"кузов {car.body_type}")
    
    if car.gear_box_type:
        parts.append(f"коробка {car.gear_box_type}")
    
    if car.driving_gear_type:
        parts.append(f"привод {car.driving_gear_type}")
    
    if car.engine_vol:
        parts.append(f"двигатель {car.engine_vol}л")
    
    if car.power:
        parts.append(f"мощность {car.power}лс")
    
    if car.price:
        parts.append(f"цена {car.price} рублей")
    
    if car.city:
        parts.append(f"город {car.city}")
    
    if car.vin:
        parts.append(f"VIN {car.vin}")
    
    return " ".join(parts)

def test_elasticsearch_search(es):
    """Тестирует поиск в Elasticsearch"""
    if not es:
        return
    
    print("\n🔍 ТЕСТИРОВАНИЕ ПОИСКА В ELASTICSEARCH")
    print("=" * 50)
    
    test_queries = [
        {
            "query": "до 2 миллионов",
            "description": "Поиск автомобилей до 2 миллионов рублей",
            "body": {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "range": {
                                    "price": {
                                        "lte": 2000000
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        },
        {
            "query": "дизель",
            "description": "Поиск дизельных автомобилей",
            "body": {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "match": {
                                    "fuel_type": "дизель"
                                }
                            }
                        ]
                    }
                }
            }
        },
        {
            "query": "внедорожник",
            "description": "Поиск внедорожников",
            "body": {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "match": {
                                    "body_type": "внедорожник"
                                }
                            }
                        ]
                    }
                }
            }
        },
        {
            "query": "Краснодар",
            "description": "Поиск автомобилей в Краснодаре",
            "body": {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "match": {
                                    "city": "Краснодар"
                                }
                            }
                        ]
                    }
                }
            }
        },
        {
            "query": "комбинированный поиск",
            "description": "Дизельные внедорожники до 3 млн в Краснодаре",
            "body": {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "match": {
                                    "fuel_type": "дизель"
                                }
                            },
                            {
                                "match": {
                                    "body_type": "внедорожник"
                                }
                            },
                            {
                                "match": {
                                    "city": "Краснодар"
                                }
                            },
                            {
                                "range": {
                                    "price": {
                                        "lte": 3000000
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
    ]
    
    for i, test in enumerate(test_queries, 1):
        print(f"\n{i}. {test['description']}")
        print(f"   Запрос: '{test['query']}'")
        
        try:
            response = es.search(
                index="cars",
                body=test['body'],
                size=10
            )
            
            hits = response['hits']['hits']
            total = response['hits']['total']['value']
            
            print(f"   Найдено: {total} автомобилей")
            
            if hits:
                print("   Примеры:")
                for hit in hits[:3]:
                    source = hit['_source']
                    price = source.get('price', 0)
                    price_str = f"{price:,.0f} ₽" if price else "не указана"
                    print(f"     - {source.get('mark', '')} {source.get('model', '')} ({source.get('manufacture_year', '')}) - {price_str}")
            
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

def main():
    """Основная функция"""
    print("🚀 НАСТРОЙКА ELASTICSEARCH ДЛЯ ПОИСКА АВТОМОБИЛЕЙ")
    print("=" * 60)
    
    if not ELASTICSEARCH_AVAILABLE:
        print("❌ Elasticsearch не установлен")
        print("Установите: pip install elasticsearch")
        return
    
    # Настройка подключения
    es = setup_elasticsearch()
    if not es:
        return
    
    # Создание индекса
    if not create_cars_index(es):
        return
    
    # Индексация данных
    if not index_cars_to_elasticsearch(es):
        return
    
    # Тестирование поиска
    test_elasticsearch_search(es)
    
    print("\n✅ НАСТРОЙКА ELASTICSEARCH ЗАВЕРШЕНА!")

if __name__ == "__main__":
    main()
