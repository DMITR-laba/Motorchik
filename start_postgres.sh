#!/bin/bash

echo "🚀 Запуск Чат-помощника с PostgreSQL..."

# Проверяем наличие .env файла
if [ ! -f .env ]; then
    echo "📝 Создание .env файла из env.example..."
    cp env.example .env
    echo "✅ Файл .env создан. Отредактируйте его при необходимости."
fi

# Проверяем наличие Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker не найден. Установите Docker и попробуйте снова."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не найден. Установите Docker Compose и попробуйте снова."
    exit 1
fi

echo "🐳 Запуск сервисов с Docker Compose..."

# Останавливаем существующие контейнеры
docker-compose down

# Запускаем сервисы
docker-compose up -d

echo "⏳ Ожидание запуска сервисов..."

# Ждем запуска PostgreSQL
echo "🔄 Ожидание PostgreSQL..."
sleep 10

# Проверяем статус сервисов
echo "📊 Статус сервисов:"
docker-compose ps

echo ""
echo "✅ Сервисы запущены!"
echo ""
echo "🌐 Доступные сервисы:"
echo "   • Backend API: http://localhost:8000"
echo "   • Frontend: http://localhost:3000"
echo "   • API документация: http://localhost:8000/docs"
echo "   • PostgreSQL: localhost:5432"
echo ""
echo "📋 Полезные команды:"
echo "   • Просмотр логов: docker-compose logs -f"
echo "   • Остановка: docker-compose down"
echo "   • Перезапуск: docker-compose restart"
echo ""
echo "🔍 Для проверки подключения к БД:"
echo "   docker-compose exec backend python test_db_connection.py"

