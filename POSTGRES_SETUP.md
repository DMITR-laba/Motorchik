# Чат-помощник с PostgreSQL

Этот проект настроен для работы с PostgreSQL базой данных в Docker контейнере.

## Быстрый запуск

### 1. Клонирование и настройка

```bash
# Клонируйте репозиторий
git clone <repository-url>
cd Чат-помощник

# Создайте файл .env на основе env.example
cp env.example .env

# Отредактируйте .env файл при необходимости
```

### 2. Запуск с Docker Compose

```bash
# Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка сервисов
docker-compose down
```

### 3. Проверка работы

- Backend API: http://localhost:8000
- Frontend: http://localhost:3000
- API документация: http://localhost:8000/docs
- PostgreSQL: localhost:5432

## Структура сервисов

### PostgreSQL
- **Порт**: 5432
- **База данных**: vectordb
- **Пользователь**: postgres
- **Пароль**: password
- **Данные**: Сохраняются в Docker volume `postgres_data`

### Backend (FastAPI)
- **Порт**: 8000
- **Автоматическое создание таблиц**: При запуске проверяется подключение к БД и создаются все необходимые таблицы
- **Retry логика**: До 30 попыток подключения с интервалом 2 секунды

### Frontend
- **Порт**: 3000
- **Зависит от**: Backend сервиса

## Автоматическое создание таблиц

При запуске backend сервиса автоматически:

1. Проверяется подключение к PostgreSQL
2. Если подключение успешно, создаются все таблицы из моделей SQLAlchemy
3. Если таблицы уже существуют, они не пересоздаются

### Создаваемые таблицы:
- `users` - пользователи системы
- `articles` - статьи базы знаний
- `categories` - категории
- `tags` - теги
- `article_categories` - связь статей и категорий
- `article_tags` - связь статей и тегов
- `chat_messages` - сообщения чата
- `documents` - загруженные документы
- `document_chunks` - чанки документов для RAG
- `document_categories` - связь документов и категорий
- `document_tags` - связь документов и тегов

## Тестирование подключения к БД

```bash
# Запуск теста подключения
cd backend
python test_db_connection.py
```

## Переменные окружения

Основные переменные в `.env`:

```env
# PostgreSQL
POSTGRES_DB=vectordb
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# API
API_HOST=0.0.0.0
API_PORT=8000
SECRET_KEY=your-secret-key-here
DEBUG=True

# AI сервисы
MISTRAL_API_KEY=your-mistral-key
MISTRAL_MODEL=mistral-large-latest
```

## Устранение неполадок

### Проблемы с подключением к БД

1. Убедитесь, что PostgreSQL контейнер запущен:
   ```bash
   docker-compose ps
   ```

2. Проверьте логи PostgreSQL:
   ```bash
   docker-compose logs postgres
   ```

3. Проверьте логи backend:
   ```bash
   docker-compose logs backend
   ```

### Пересоздание базы данных

```bash
# Остановка и удаление данных
docker-compose down -v

# Запуск заново
docker-compose up -d
```

### Ручное подключение к PostgreSQL

```bash
# Подключение к контейнеру PostgreSQL
docker-compose exec postgres psql -U postgres -d vectordb

# Просмотр таблиц
\dt

# Выход
\q
```

## Разработка

### Локальная разработка с PostgreSQL

Если вы хотите запустить только PostgreSQL локально:

```bash
# Запуск только PostgreSQL
docker-compose up postgres -d

# Запуск backend локально
cd backend
python main.py
```

### Миграции

Для изменения структуры БД используйте Alembic:

```bash
# Создание миграции
alembic revision --autogenerate -m "описание изменений"

# Применение миграций
alembic upgrade head
```

