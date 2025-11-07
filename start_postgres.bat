@echo off
echo 🚀 Запуск Чат-помощника с PostgreSQL...

REM Проверяем наличие .env файла
if not exist .env (
    echo 📝 Создание .env файла из env.example...
    copy env.example .env
    echo ✅ Файл .env создан. Отредактируйте его при необходимости.
)

REM Проверяем наличие Docker
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker не найден. Установите Docker и попробуйте снова.
    pause
    exit /b 1
)

docker-compose --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker Compose не найден. Установите Docker Compose и попробуйте снова.
    pause
    exit /b 1
)

echo 🐳 Запуск сервисов с Docker Compose...

REM Останавливаем существующие контейнеры
docker-compose down

REM Запускаем сервисы
docker-compose up -d

echo ⏳ Ожидание запуска сервисов...

REM Ждем запуска PostgreSQL
echo 🔄 Ожидание PostgreSQL...
timeout /t 10 /nobreak >nul

REM Проверяем статус сервисов
echo 📊 Статус сервисов:
docker-compose ps

echo.
echo ✅ Сервисы запущены!
echo.
echo 🌐 Доступные сервисы:
echo    • Backend API: http://localhost:8000
echo    • Frontend: http://localhost:3000
echo    • API документация: http://localhost:8000/docs
echo    • PostgreSQL: localhost:5432
echo.
echo 📋 Полезные команды:
echo    • Просмотр логов: docker-compose logs -f
echo    • Остановка: docker-compose down
echo    • Перезапуск: docker-compose restart
echo.
echo 🔍 Для проверки подключения к БД:
echo    docker-compose exec backend python test_db_connection.py

pause

