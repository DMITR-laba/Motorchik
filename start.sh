#!/bin/bash

echo "Запуск AI-Портала техподдержки..."

# Проверяем наличие .env файла
if [ ! -f .env ]; then
    echo "Создаем .env файл из примера..."
    cp env.example .env
    echo "ВНИМАНИЕ: Не забудьте настроить переменные в .env файле!"
    echo "Особенно OPENAI_API_KEY для работы AI-ассистента"
    read -p "Нажмите Enter для продолжения..."
fi

# Запускаем Docker Compose
echo "Запуск сервисов..."
docker-compose up -d

echo ""
echo "Сервисы запущены:"
echo "- Frontend: http://localhost:3000"
echo "- Backend API: http://localhost:8000"
echo "- API Docs: http://localhost:8000/docs"
echo "- PostgreSQL: localhost:5432"
echo ""
echo "Для остановки используйте: docker-compose down"



