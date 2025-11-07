#!/usr/bin/env python3
"""
Скрипт для создания администратора
Использование:
    python create_admin.py
    python create_admin.py admin@example.com admin123
    ADMIN_EMAIL=admin@test.com ADMIN_PASSWORD=test123 python create_admin.py
"""
import sys
import os
from pathlib import Path

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent))

from models import get_db
from models.database import User
from models.schemas import UserCreate
from services.database_service import DatabaseService
from app.api.auth import get_password_hash

def create_admin(email: str = None, password: str = None, full_name: str = None):
    """
    Создает администратора
    
    Args:
        email: Email администратора (по умолчанию из переменной окружения или admin@example.com)
        password: Пароль администратора (по умолчанию из переменной окружения или admin123)
        full_name: Полное имя администратора (по умолчанию Admin)
    """
    db = next(get_db())
    db_service = DatabaseService(db)
    
    # Получаем значения из аргументов, переменных окружения или используем значения по умолчанию
    admin_email = email or os.getenv('ADMIN_EMAIL', 'admin@example.com')
    admin_password = password or os.getenv('ADMIN_PASSWORD', 'admin123')
    admin_full_name = full_name or os.getenv('ADMIN_FULL_NAME', 'Администратор')
    
    print("=" * 60)
    print("🔐 Создание администратора")
    print("=" * 60)
    print(f"📧 Email: {admin_email}")
    print(f"👤 Имя: {admin_full_name}")
    print(f"🔑 Пароль: {admin_password}")
    print("-" * 60)
    
    # Проверяем, существует ли уже пользователь с таким email
    existing_user = db_service.get_user_by_email(admin_email)
    if existing_user:
        print(f"⚠️  Пользователь с email {admin_email} уже существует!")
        print(f"   ID: {existing_user.id}")
        print(f"   Роль: {existing_user.role}")
        print(f"   Активен: {'Да' if existing_user.is_active else 'Нет'}")
        
        # Спрашиваем, нужно ли обновить роль до admin
        if existing_user.role != 'admin':
            print(f"\n❓ Хотите обновить роль пользователя до 'admin'? (y/n): ", end='')
            response = input().strip().lower()
            if response == 'y':
                existing_user.role = 'admin'
                if admin_password != 'admin123':  # Обновляем пароль только если он не дефолтный
                    existing_user.hashed_password = get_password_hash(admin_password)
                db.commit()
                db.refresh(existing_user)
                print("✅ Роль пользователя обновлена до 'admin'")
                print(f"   Email: {existing_user.email}")
                print(f"   Роль: {existing_user.role}")
                return
            else:
                print("❌ Операция отменена")
                return
        else:
            print("\n✅ Пользователь уже является администратором")
            return
    
    # Создаем нового администратора
    try:
        user_data = UserCreate(
            email=admin_email,
            full_name=admin_full_name,
            password=admin_password,
            role="admin"
        )
        
        hashed_password = get_password_hash(admin_password)
        admin = db_service.create_user(user_data, hashed_password=hashed_password, role="admin")
        
        print("\n✅ Администратор успешно создан!")
        print("=" * 60)
        print("📋 Данные для входа:")
        print(f"   📧 Email: {admin.email}")
        print(f"   🔑 Пароль: {admin_password}")
        print(f"   👤 Имя: {admin.full_name}")
        print(f"   🎭 Роль: {admin.role}")
        print(f"   ✅ Активен: {'Да' if admin.is_active else 'Нет'}")
        print(f"   🆔 ID: {admin.id}")
        print("=" * 60)
        print("\n💡 Используйте эти данные для входа в систему")
        
    except Exception as e:
        print(f"\n❌ Ошибка при создании администратора: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    # Парсим аргументы командной строки
    if len(sys.argv) >= 3:
        email = sys.argv[1]
        password = sys.argv[2]
        full_name = sys.argv[3] if len(sys.argv) > 3 else None
        create_admin(email, password, full_name)
    elif len(sys.argv) == 2:
        print("⚠️  Недостаточно аргументов. Использование:")
        print("   python create_admin.py <email> <password> [full_name]")
        sys.exit(1)
    else:
        # Создаем админа с параметрами по умолчанию или из переменных окружения
        create_admin()
