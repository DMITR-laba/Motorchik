#!/usr/bin/env python3
"""
Скрипт для миграции данных из SQLite cars.db в PostgreSQL и ChromaDB
"""
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# Добавляем путь к модулям
sys.path.append(str(Path(__file__).parent))

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Создаем свой engine с учетом переменных окружения
def get_migration_db_url():
    """Получает URL базы данных для миграции"""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url
    
    postgres_user = os.environ.get("POSTGRES_USER", "postgres")
    postgres_password = os.environ.get("POSTGRES_PASSWORD", "password")
    postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
    postgres_port = os.environ.get("POSTGRES_PORT", "5433")
    postgres_db = os.environ.get("POSTGRES_DB", "vectordb")
    
    return f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"

# Создаем engine напрямую
migration_db_url = get_migration_db_url()
print(f"URL подключения: {migration_db_url.split('@')[1] if '@' in migration_db_url else 'скрыто'}")
migration_engine = create_engine(
    migration_db_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=20,
    echo=False
)

# Создаем Base и SessionLocal для миграции
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=migration_engine)

# Импортируем модели после создания engine
from models.database import (
    Car, UsedCar, CarPicture, UsedCarPicture, 
    CarOptionsGroup, CarOption
)
# Переопределяем Base для использования в создании таблиц
Base = Car.metadata  # Используем metadata из моделей
import chromadb
from chromadb.config import Settings as ChromaSettings

def find_cars_db():
    """Ищет файл cars.db в различных местах"""
    possible_paths = [
        Path("/app/sqlite/cars.db"),  # Docker путь
        Path(__file__).parent.parent / "sqlite" / "cars.db",
        Path(__file__).parent.parent / "cars.db",
        Path(__file__).parent / "sqlite" / "cars.db",
        Path(__file__).parent / "cars.db",
    ]
    
    for path in possible_paths:
        if path.exists():
            print(f"✅ Найден файл SQLite: {path}")
            return str(path)
    
    print("⚠️ Файл cars.db не найден ни в одном из возможных мест")
    return None

def convert_value(value, target_type, max_length=None):
    """Конвертирует значение в нужный тип"""
    if value is None:
        return None
    
    if target_type == "float":
        try:
            return str(float(value)) if value else None
        except (ValueError, TypeError):
            return None
    elif target_type == "int":
        try:
            return int(value) if value else None
        except (ValueError, TypeError):
            return None
    elif target_type == "str":
        result = str(value) if value else None
        if result and max_length and len(result) > max_length:
            # Обрезаем с предупреждением
            return result[:max_length]
        return result
    
    return value

def migrate_cars():
    """Мигрирует данные из SQLite в PostgreSQL и ChromaDB"""
    
    # Находим файл базы данных
    sqlite_path = find_cars_db()
    if not sqlite_path:
        print("❌ Файл cars.db не найден!")
        return False
    
    print(f"Найден файл базы данных: {sqlite_path}")
    
    # Подключаемся к SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    
    # Создаем таблицы в PostgreSQL
    print("\n📋 Создание таблиц в PostgreSQL...")
    from models.database import Base as ModelsBase
    ModelsBase.metadata.create_all(bind=migration_engine)
    print("✅ Таблицы созданы")
    
    # Подключаемся к PostgreSQL
    db = SessionLocal()
    
    try:
        # 1. Миграция новых автомобилей (car)
        print("\n🚗 Миграция новых автомобилей...")
        sqlite_cursor.execute("SELECT * FROM car")
        cars_data = sqlite_cursor.fetchall()
        
        imported_cars = 0
        for car_row in cars_data:
            try:
                car = Car(
                    id=car_row['id'],
                    title=convert_value(car_row['title'], "str"),
                    doc_num=convert_value(car_row['doc_num'], "str"),
                    stock_qty=convert_value(car_row['stock_qty'], "int"),
                    mark=convert_value(car_row['mark'], "str"),
                    model=convert_value(car_row['model'], "str"),
                    code_compl=convert_value(car_row['code_compl'], "str"),
                    vin=convert_value(car_row['vin'], "str"),
                    color=convert_value(car_row['color'], "str"),
                    price=convert_value(car_row['price'], "float"),
                    city=convert_value(car_row['city'], "str"),
                    manufacture_year=convert_value(car_row['manufacture_year'], "int"),
                    fuel_type=convert_value(car_row['fuel_type'], "str"),
                    power=convert_value(car_row['power'], "float"),
                    body_type=convert_value(car_row['body_type'], "str"),
                    gear_box_type=convert_value(car_row['gear_box_type'], "str"),
                    driving_gear_type=convert_value(car_row['driving_gear_type'], "str"),
                    engine_vol=convert_value(car_row['engine_vol'], "int"),
                    dealer_center=convert_value(car_row['dealer_center'], "str"),
                    interior_color=convert_value(car_row['interior_color'], "str"),
                    engine=convert_value(car_row['engine'], "str"),
                    door_qty=convert_value(car_row['door_qty'], "str"),
                    pts_colour=convert_value(car_row['pts_colour'], "str"),
                    model_year=convert_value(car_row['model_year'], "str"),
                    fuel_consumption=convert_value(car_row['fuel_consumption'], "str"),
                    max_torque=convert_value(car_row['max_torque'], "str"),
                    acceleration=convert_value(car_row['acceleration'], "str"),
                    max_speed=convert_value(car_row['max_speed'], "str"),
                    eco_class=convert_value(car_row['eco_class'], "str"),
                    dimensions=convert_value(car_row['dimensions'], "str"),
                    weight=convert_value(car_row['weight'], "str"),
                    cargo_volume=convert_value(car_row['cargo_volume'], "str"),
                    compl_level=convert_value(car_row['compl_level'], "str"),
                    interior_code=convert_value(car_row['interior_code'], "str"),
                    color_code=convert_value(car_row['color_code'], "str"),
                    car_order_int_status=convert_value(car_row['car_order_int_status'], "str"),
                    sale_price=convert_value(car_row['sale_price'], "float"),
                    max_additional_discount=convert_value(car_row['max_additional_discount'], "float"),
                    max_discount_trade_in=convert_value(car_row['max_discount_trade_in'], "float"),
                    max_discount_credit=convert_value(car_row['max_discount_credit'], "float"),
                    max_discount_casko=convert_value(car_row['max_discount_casko'], "float"),
                    max_discount_extra_gear=convert_value(car_row['max_discount_extra_gear'], "float"),
                    max_discount_life_insurance=convert_value(car_row['max_discount_life_insurance'], "float"),
                )
                db.merge(car)  # Используем merge для обновления существующих записей
                imported_cars += 1
                if imported_cars % 50 == 0:
                    print(f"  Импортировано {imported_cars}/{len(cars_data)} новых автомобилей...")
            except Exception as e:
                print(f"  ❌ Ошибка при импорте автомобиля ID {car_row['id']}: {e}")
                continue
        
        print(f"✅ Импортировано новых автомобилей: {imported_cars}/{len(cars_data)}")
        
        # 2. Миграция подержанных автомобилей (used_car)
        print("\n🚙 Миграция подержанных автомобилей...")
        sqlite_cursor.execute("SELECT * FROM used_car")
        used_cars_data = sqlite_cursor.fetchall()
        
        imported_used_cars = 0
        for used_car_row in used_cars_data:
            try:
                used_car = UsedCar(
                    id=used_car_row['id'],
                    title=convert_value(used_car_row['title'], "str", max_length=100),
                    doc_num=convert_value(used_car_row['doc_num'], "str"),
                    mark=convert_value(used_car_row['mark'], "str", max_length=100),
                    model=convert_value(used_car_row['model'], "str", max_length=100),
                    vin=convert_value(used_car_row['vin'], "str"),
                    color=convert_value(used_car_row['color'], "str"),
                    price=convert_value(used_car_row['price'], "float"),
                    city=convert_value(used_car_row['city'], "str", max_length=100),
                    manufacture_year=convert_value(used_car_row['manufacture_year'], "int"),
                    mileage=convert_value(used_car_row['mileage'], "int"),
                    body_type=convert_value(used_car_row['body_type'], "str"),
                    gear_box_type=convert_value(used_car_row['gear_box_type'], "str"),
                    driving_gear_type=convert_value(used_car_row['driving_gear_type'], "str"),
                    engine_vol=convert_value(used_car_row['engine_vol'], "int"),
                    power=convert_value(used_car_row['power'], "float"),
                    fuel_type=convert_value(used_car_row['fuel_type'], "str"),
                    dealer_center=convert_value(used_car_row['dealer_center'], "str", max_length=100),
                    date_begin=convert_value(used_car_row['date_begin'], "str"),
                    date_end=convert_value(used_car_row['date_end'], "str"),
                    ad_status=convert_value(used_car_row['ad_status'], "str", max_length=100),
                    allow_email=convert_value(used_car_row['allow_email'], "str"),
                    company_name=convert_value(used_car_row['company_name'], "str"),
                    manager_name=convert_value(used_car_row['manager_name'], "str"),
                    contact_phone=convert_value(used_car_row['contact_phone'], "str"),
                    category=convert_value(used_car_row['category'], "str", max_length=100),
                    region=convert_value(used_car_row['region'], "str", max_length=100),
                    car_type=convert_value(used_car_row['car_type'], "str"),
                    accident=convert_value(used_car_row['accident'], "str", max_length=100),
                    certification_number=convert_value(used_car_row['certification_number'], "str", max_length=100),
                    allow_avtokod_report_link=convert_value(used_car_row['allow_avtokod_report_link'], "str"),
                    doors=convert_value(used_car_row['doors'], "str"),
                    wheel_type=convert_value(used_car_row['wheel_type'], "str"),
                    owners=convert_value(used_car_row['owners'], "int"),
                    street=convert_value(used_car_row['street'], "str"),
                    sticker=convert_value(used_car_row['sticker'], "str"),
                    generation_id=convert_value(used_car_row['generation_id'], "str", max_length=100),
                    modification_id=convert_value(used_car_row['modification_id'], "str", max_length=100),
                    aaa_max_additional_discount=convert_value(used_car_row['aaa_max_additional_discount'], "str", max_length=100),
                    aaa_max_discount_trade_in=convert_value(used_car_row['aaa_max_discount_trade_in'], "str", max_length=100),
                    aaa_max_discount_credit=convert_value(used_car_row['aaa_max_discount_credit'], "str", max_length=100),
                    aaa_max_discount_casko=convert_value(used_car_row['aaa_max_discount_casko'], "str", max_length=100),
                    aaa_max_discount_extra_gear=convert_value(used_car_row['aaa_max_discount_extra_gear'], "str", max_length=100),
                    aaa_max_discount_life_insurance=convert_value(used_car_row['aaa_max_discount_life_insurance'], "str", max_length=100),
                )
                db.merge(used_car)
                imported_used_cars += 1
                if imported_used_cars % 50 == 0:
                    print(f"  Импортировано {imported_used_cars}/{len(used_cars_data)} подержанных автомобилей...")
            except Exception as e:
                print(f"  ❌ Ошибка при импорте подержанного автомобиля ID {used_car_row['id']}: {e}")
                continue
        
        print(f"✅ Импортировано подержанных автомобилей: {imported_used_cars}/{len(used_cars_data)}")
        
        # 3. Миграция фотографий новых автомобилей
        print("\n📸 Миграция фотографий новых автомобилей...")
        sqlite_cursor.execute("SELECT * FROM picture")
        pictures_data = sqlite_cursor.fetchall()
        
        imported_pictures = 0
        for pic_row in pictures_data:
            try:
                picture = CarPicture(
                    id=pic_row['id'],
                    car_id=pic_row['car_id'],
                    url=convert_value(pic_row['url'], "str"),
                    type=convert_value(pic_row['type'], "str"),
                    seqno=convert_value(pic_row['seqno'], "int"),
                )
                db.merge(picture)
                imported_pictures += 1
            except Exception as e:
                print(f"  ❌ Ошибка при импорте фото ID {pic_row['id']}: {e}")
                continue
        
        print(f"✅ Импортировано фотографий новых авто: {imported_pictures}/{len(pictures_data)}")
        
        # 4. Миграция фотографий подержанных автомобилей
        print("\n📸 Миграция фотографий подержанных автомобилей...")
        sqlite_cursor.execute("SELECT * FROM used_car_picture")
        used_pictures_data = sqlite_cursor.fetchall()
        
        imported_used_pictures = 0
        for used_pic_row in used_pictures_data:
            try:
                used_picture = UsedCarPicture(
                    id=used_pic_row['id'],
                    used_car_id=used_pic_row['used_car_id'],
                    url=convert_value(used_pic_row['url'], "str"),
                    type=convert_value(used_pic_row['type'], "str"),
                    seqno=convert_value(used_pic_row['seqno'], "int"),
                )
                db.merge(used_picture)
                imported_used_pictures += 1
            except Exception as e:
                print(f"  ❌ Ошибка при импорте фото подержанного авто ID {used_pic_row['id']}: {e}")
                continue
        
        print(f"✅ Импортировано фотографий подержанных авто: {imported_used_pictures}/{len(used_pictures_data)}")
        
        # 5. Миграция групп опций
        print("\n⚙️ Миграция групп опций...")
        sqlite_cursor.execute("SELECT * FROM options_group")
        options_groups_data = sqlite_cursor.fetchall()
        
        imported_groups = 0
        for group_row in options_groups_data:
            try:
                options_group = CarOptionsGroup(
                    id=group_row['id'],
                    car_id=group_row['car_id'],
                    code=convert_value(group_row['code'], "str"),
                    name=convert_value(group_row['name'], "str"),
                )
                db.merge(options_group)
                imported_groups += 1
            except Exception as e:
                print(f"  ❌ Ошибка при импорте группы опций ID {group_row['id']}: {e}")
                continue
        
        print(f"✅ Импортировано групп опций: {imported_groups}/{len(options_groups_data)}")
        
        # 6. Миграция опций
        print("\n⚙️ Миграция опций...")
        sqlite_cursor.execute("SELECT * FROM option")
        options_data = sqlite_cursor.fetchall()
        
        imported_options = 0
        for option_row in options_data:
            try:
                option = CarOption(
                    id=option_row['id'],
                    car_id=option_row['car_id'],
                    code=convert_value(option_row['code'], "str"),
                    description=convert_value(option_row['description'], "str"),
                    options_group_id=convert_value(option_row['options_group_id'], "int"),
                )
                db.merge(option)
                imported_options += 1
                if imported_options % 200 == 0:
                    print(f"  Импортировано {imported_options}/{len(options_data)} опций...")
            except Exception as e:
                print(f"  ❌ Ошибка при импорте опции ID {option_row['id']}: {e}")
                continue
        
        print(f"✅ Импортировано опций: {imported_options}/{len(options_data)}")
        
        # Коммитим все изменения
        print("\n💾 Сохранение данных в PostgreSQL...")
        db.commit()
        print("✅ Данные сохранены в PostgreSQL")
        
        # 7. Индексация в ChromaDB
        print("\n🔍 Индексация автомобилей в ChromaDB...")
        
        # Инициализация ChromaDB
        try:
            chroma_settings = ChromaSettings(anonymized_telemetry=False)
        except TypeError:
            chroma_settings = None
        
        if chroma_settings is not None:
            chroma_client = chromadb.PersistentClient(
                path="./chroma",
                settings=chroma_settings,
            )
        else:
            chroma_client = chromadb.PersistentClient(path="./chroma")
        
        # Удаляем старую коллекцию если есть
        try:
            chroma_client.delete_collection("kb_cars")
        except:
            pass
        
        # Создаем новую коллекцию для автомобилей
        cars_collection = chroma_client.create_collection(name="kb_cars")
        
        # Индексируем новые автомобили
        # DatabaseService не нужен для миграции, используем напрямую db
        all_cars = db.query(Car).all()
        
        batch_size = 50
        indexed_count = 0
        
        for i in range(0, len(all_cars), batch_size):
            batch_cars = all_cars[i:i + batch_size]
            ids = []
            documents = []
            metadatas = []
            
            for car in batch_cars:
                # Формируем текстовое описание автомобиля для поиска
                car_text = f"{car.mark or ''} {car.model or ''} {car.color or ''} {car.city or ''} {car.fuel_type or ''} {car.body_type or ''} {car.gear_box_type or ''} {car.manufacture_year or ''}"
                if car.price:
                    car_text += f" цена {car.price}"
                if car.power:
                    car_text += f" мощность {car.power}"
                
                ids.append(f"car_{car.id}")
                documents.append(car_text.strip())
                metadatas.append({
                    "type": "car",
                    "car_id": str(car.id),
                    "mark": car.mark or "",
                    "model": car.model or "",
                    "city": car.city or "",
                    "price": str(car.price) if car.price else "",
                })
            
            cars_collection.add(ids=ids, documents=documents, metadatas=metadatas)
            indexed_count += len(batch_cars)
            print(f"  Проиндексировано {indexed_count}/{len(all_cars)} новых автомобилей...")
        
        # Индексируем подержанные автомобили
        all_used_cars = db.query(UsedCar).all()
        
        try:
            chroma_client.delete_collection("kb_used_cars")
        except:
            pass
        
        used_cars_collection = chroma_client.create_collection(name="kb_used_cars")
        
        indexed_used_count = 0
        for i in range(0, len(all_used_cars), batch_size):
            batch_cars = all_used_cars[i:i + batch_size]
            ids = []
            documents = []
            metadatas = []
            
            for car in batch_cars:
                car_text = f"{car.mark or ''} {car.model or ''} {car.color or ''} {car.city or ''} {car.fuel_type or ''} {car.body_type or ''} {car.gear_box_type or ''} {car.manufacture_year or ''}"
                if car.mileage:
                    car_text += f" пробег {car.mileage}"
                if car.price:
                    car_text += f" цена {car.price}"
                if car.power:
                    car_text += f" мощность {car.power}"
                
                ids.append(f"used_car_{car.id}")
                documents.append(car_text.strip())
                metadatas.append({
                    "type": "used_car",
                    "used_car_id": str(car.id),
                    "mark": car.mark or "",
                    "model": car.model or "",
                    "city": car.city or "",
                    "mileage": str(car.mileage) if car.mileage else "",
                    "price": str(car.price) if car.price else "",
                })
            
            used_cars_collection.add(ids=ids, documents=documents, metadatas=metadatas)
            indexed_used_count += len(batch_cars)
            print(f"  Проиндексировано {indexed_used_count}/{len(all_used_cars)} подержанных автомобилей...")
        
        print("✅ Индексация в ChromaDB завершена")
        
        print("\n" + "=" * 80)
        print("🎉 МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 80)
        print(f"📊 Статистика:")
        print(f"  - Новых автомобилей: {imported_cars}")
        print(f"  - Подержанных автомобилей: {imported_used_cars}")
        print(f"  - Фотографий новых авто: {imported_pictures}")
        print(f"  - Фотографий подержанных авто: {imported_used_pictures}")
        print(f"  - Групп опций: {imported_groups}")
        print(f"  - Опций: {imported_options}")
        print(f"  - Проиндексировано в ChromaDB: {indexed_count} новых + {indexed_used_count} подержанных")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка при миграции: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()
        sqlite_conn.close()

if __name__ == "__main__":
    migrate_cars()


