#!/bin/bash
set -e

echo "🚀 Запуск backend контейнера..."

# Функция для ожидания готовности PostgreSQL
wait_for_postgres() {
    echo "⏳ Ожидание готовности PostgreSQL..."
    until PGPASSWORD=$POSTGRES_PASSWORD psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\q' 2>/dev/null; do
        echo "⏳ PostgreSQL еще не готов, ждем..."
        sleep 2
    done
    echo "✅ PostgreSQL готов!"
}

# Функция для ожидания готовности Elasticsearch
wait_for_elasticsearch() {
    echo "⏳ Ожидание готовности Elasticsearch..."
    ES_HOST=${ELASTICSEARCH_HOST:-elasticsearch}
    ES_PORT=${ELASTICSEARCH_PORT:-9200}
    until curl -f http://${ES_HOST}:${ES_PORT}/_cluster/health >/dev/null 2>&1; do
        echo "⏳ Elasticsearch еще не готов, ждем..."
        sleep 2
    done
    echo "✅ Elasticsearch готов!"
}

# Функция для проверки, нужно ли заполнять PostgreSQL
check_if_migration_needed() {
    echo "🔍 Проверка необходимости миграции данных..."
    
    # Проверяем, существует ли таблица cars
    TABLE_EXISTS=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'cars');" 2>/dev/null | tr -d ' ' || echo "f")
    
    if [ "$TABLE_EXISTS" != "t" ]; then
        echo "📊 Таблица cars не существует, требуется миграция из SQLite"
        return 0
    fi
    
    # Проверяем, есть ли данные в PostgreSQL
    COUNT=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM cars;" 2>/dev/null | tr -d ' ' || echo "0")
    
    if [ "$COUNT" = "0" ] || [ -z "$COUNT" ]; then
        echo "📊 PostgreSQL пуст, требуется миграция из SQLite"
        return 0
    else
        echo "✅ В PostgreSQL уже есть данные ($COUNT автомобилей), миграция не требуется"
        return 1
    fi
}

# Функция для заполнения PostgreSQL из SQLite
migrate_from_sqlite() {
    echo "📦 Начало миграции данных из SQLite в PostgreSQL..."
    
    SQLITE_PATH="/app/sqlite/cars.db"
    
    if [ ! -f "$SQLITE_PATH" ]; then
        echo "⚠️ Файл $SQLITE_PATH не найден, пропускаем миграцию"
        return 1
    fi
    
    echo "✅ Файл SQLite найден: $SQLITE_PATH"
    
    # Запускаем скрипт миграции
    python /app/migrate_cars_from_sqlite.py
    
    if [ $? -eq 0 ]; then
        echo "✅ Миграция данных завершена успешно!"
        return 0
    else
        echo "❌ Ошибка при миграции данных"
        return 1
    fi
}

# Функция для настройки Elasticsearch
setup_elasticsearch() {
    echo "🔧 Настройка Elasticsearch..."
    
    ES_HOST=${ELASTICSEARCH_HOST:-elasticsearch}
    ES_PORT=${ELASTICSEARCH_PORT:-9200}
    
    # Проверяем, существует ли индекс
    if curl -f http://${ES_HOST}:${ES_PORT}/cars >/dev/null 2>&1; then
        echo "✅ Индекс Elasticsearch уже существует"
        return 0
    fi
    
    echo "📊 Создание индексов в Elasticsearch..."
    python /app/elasticsearch_setup.py
    
    if [ $? -eq 0 ]; then
        echo "✅ Elasticsearch настроен успешно!"
        return 0
    else
        echo "⚠️ Ошибка при настройке Elasticsearch (может быть, индексы уже существуют)"
        return 0  # Не критично, продолжаем
    fi
}

# Функция для создания администратора
create_admin_user() {
    echo "🔐 Проверка наличия администратора..."
    
    ADMIN_EMAIL=${ADMIN_EMAIL:-admin@example.com}
    ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin123}
    
    # Запускаем скрипт создания администратора
    python /app/create_admin.py "${ADMIN_EMAIL}" "${ADMIN_PASSWORD}" "Администратор" 2>&1 | grep -E "(✅|⚠️|❌|📧|🔑)" || true
    
    if [ $? -eq 0 ]; then
        echo "✅ Проверка администратора завершена"
    else
        echo "⚠️ Ошибка при проверке администратора (может быть, он уже существует)"
    fi
}

# Основная логика
main() {
    # Ожидаем готовности сервисов
    wait_for_postgres
    wait_for_elasticsearch
    
    # Проверяем и выполняем миграцию, если нужно
    if check_if_migration_needed; then
        migrate_from_sqlite
    fi
    
    # Настраиваем Elasticsearch
    setup_elasticsearch
    
    # Создаем администратора, если его нет
    create_admin_user
    
    echo "✅ Все готово! Запускаем приложение..."
    
    # Если команда не передана, используем команду по умолчанию
    if [ $# -eq 0 ]; then
        echo "📝 Команда не передана, используем команду по умолчанию: python -m uvicorn main:app --host 0.0.0.0 --port 8000"
        exec python -m uvicorn main:app --host 0.0.0.0 --port 8000
    else
        echo "📝 Команда для запуска: $@"
        # Запускаем переданную команду
        exec "$@"
    fi
}

# Запускаем основную функцию
main "$@"

