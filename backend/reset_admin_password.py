#!/usr/bin/env python3
"""
Скрипт для принудительного сброса пароля администратора
Использование:
    python reset_admin_password.py admin@example.com admin123
"""
import sys
import os
from pathlib import Path

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent))

from models import get_db
from models.database import User
from services.database_service import DatabaseService
from app.api.auth import get_password_hash

def reset_admin_password(email: str, new_password: str):
    """
    Принудительно сбрасывает пароль администратора
    
    Args:
        email: Email администратора
        new_password: Новый пароль
    """
    db = next(get_db())
    db_service = DatabaseService(db)
    
    print("=" * 60)
    print("🔐 Сброс пароля администратора")
    print("=" * 60)
    print(f"📧 Email: {email}")
    print(f"🔑 Новый пароль: {new_password}")
    print("-" * 60)
    
    # Находим пользователя
    user = db_service.get_user_by_email(email)
    if not user:
        print(f"❌ Пользователь с email {email} не найден!")
        return False
    
    print(f"✅ Пользователь найден:")
    print(f"   ID: {user.id}")
    print(f"   Роль: {user.role}")
    print(f"   Активен: {'Да' if user.is_active else 'Нет'}")
    
    # Обновляем пароль
    user.hashed_password = get_password_hash(new_password)
    # Убеждаемся, что пользователь активен и является администратором
    user.is_active = True
    user.role = 'admin'
    
    db.commit()
    db.refresh(user)
    
    print("\n✅ Пароль успешно обновлен!")
    print("=" * 60)
    print("📋 Данные для входа:")
    print(f"   📧 Email: {user.email}")
    print(f"   🔑 Пароль: {new_password}")
    print(f"   👤 Имя: {user.full_name}")
    print(f"   🎭 Роль: {user.role}")
    print(f"   ✅ Активен: {'Да' if user.is_active else 'Нет'}")
    print("=" * 60)
    print("\n💡 Теперь вы можете войти с новым паролем")
    
    return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("⚠️  Использование:")
        print("   python reset_admin_password.py <email> <password>")
        print("\nПример:")
        print("   python reset_admin_password.py admin@example.com admin123")
        sys.exit(1)
    
    email = sys.argv[1]
    password = sys.argv[2]
    reset_admin_password(email, password)

