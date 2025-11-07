#!/usr/bin/env python3
"""
Скрипт для миграции данных из SQLite cars.db в новый PostgreSQL (postgres-pgvector на порту 5433)
Использует прямое подключение, обходя config.py
"""
import sqlite3
import sys
import os
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Добавляем путь к модулям
sys.path.append(str(Path(__file__).parent))

def get_db_url():
    """Получает URL базы данных из переменных окружения или использует значения по умолчанию"""
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url
    
    postgres_user = os.environ.get("POSTGRES_USER", "postgres")
    postgres_password = os.environ.get("POSTGRES_PASSWORD", "password")
    postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
    postgres_port = os.environ.get("POSTGRES_PORT", "5433")
    postgres_db = os.environ.get("POSTGRES_DB", "vectordb")
    
    return f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"

def find_cars_db():
    """Ищет файл cars.db в различных местах"""
    possible_paths = [
        Path(__file__).parent.parent / "sqlite" / "cars.db",
        Path(__file__).parent.parent / "cars.db",
        Path(__file__).parent / "sqlite" / "cars.db",
        Path(__file__).parent / "cars.db",
    ]
    
    for path in possible_paths:
        if path.exists():
            return str(path)
    
    return None

def convert_value(value, target_type):
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
        return str(value) if value else None
    
    return value

def migrate_cars():
    """Мигрирует данные из SQLite в PostgreSQL"""
    
    # Находим файл базы данных
    sqlite_path = find_cars_db()
    if not sqlite_path:
        print("❌ Файл cars.db не найден!")
        return False
    
    print(f"📊 Найден файл базы данных: {sqlite_path}")
    
    # Получаем URL базы данных
    db_url = get_db_url()
    print(f"🔗 Подключение к PostgreSQL: {db_url.split('@')[1] if '@' in db_url else 'скрыто'}")
    
    # Создаем движок и сессию напрямую
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20,
        echo=False
    )
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    # Подключаемся к SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    
    try:
        # Создаем таблицы в PostgreSQL используя SQLAlchemy модели
        print("\n📋 Создание таблиц в PostgreSQL...")
        from models.database import Base
        Base.metadata.create_all(bind=engine)
        print("✅ Таблицы созданы")
        
        # Импортируем модели
        from models.database import (
            Car, UsedCar, CarPicture, UsedCarPicture, 
            CarOptionsGroup, CarOption
        )
        
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
                    # ... остальные поля аналогично
                )
                db.add(car)
                imported_cars += 1
                
                if imported_cars % 50 == 0:
                    print(f"  Импортировано {imported_cars}/{len(cars_data)} новых автомобилей...")
            except Exception as e:
                print(f"  ⚠️ Ошибка при импорте автомобиля ID {car_row.get('id')}: {e}")
                continue
        
        print(f"✅ Импортировано новых автомобилей: {imported_cars}/{len(cars_data)}")
        
        # Сохраняем все изменения
        db.commit()
        print("\n💾 Данные сохранены в PostgreSQL")
        
        print("\n" + "=" * 80)
        print("🎉 МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 80)
        print(f"📊 Статистика:")
        print(f"  - Новых автомобилей: {imported_cars}")
        
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







