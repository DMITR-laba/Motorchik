#!/bin/bash

# Скрипт для создания администратора AI-Портала техподдержки
# Использование: ./create_admin.sh

echo "🚀 Создание администратора для AI-Портала техподдержки"
echo "=================================================="

# Проверяем, что backend запущен
echo "🔍 Проверяем доступность API..."
if ! curl -s http://localhost:8000/docs > /dev/null; then
    echo "❌ Ошибка: API сервер недоступен на http://localhost:8000"
    echo "   Убедитесь, что Docker контейнеры запущены:"
    echo "   docker-compose up -d"
    exit 1
fi

echo "✅ API сервер доступен"

# Создаем администратора
echo "👤 Создаем администратора..."
response=$(curl -s -X POST http://localhost:8000/api/auth/bootstrap-admin)

if echo "$response" | grep -q "Admin created"; then
    echo "✅ Администратор успешно создан!"
    echo ""
    echo "📋 Данные для входа:"
    echo "   🌐 URL: http://localhost:3000"
    echo "   📧 Email: admin@example.com"
    echo "   🔑 Пароль: admin"
    echo ""
    echo "⚠️  ВАЖНО: Смените пароль после первого входа!"
elif echo "$response" | grep -q "Admin already exists"; then
    echo "ℹ️  Администратор уже существует"
    echo ""
    echo "📋 Данные для входа:"
    echo "   🌐 URL: http://localhost:3000"
    echo "   📧 Email: admin@example.com"
    echo "   🔑 Пароль: admin"
else
    echo "❌ Ошибка при создании администратора:"
    echo "$response"
    exit 1
fi

# Проверяем авторизацию
echo ""
echo "🔐 Проверяем авторизацию..."
auth_response=$(curl -s -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=admin")

if echo "$auth_response" | grep -q "access_token"; then
    echo "✅ Авторизация работает корректно"
else
    echo "❌ Ошибка авторизации:"
    echo "$auth_response"
fi

echo ""
echo "🎉 Готово! Можете войти в систему по адресу http://localhost:3000"
