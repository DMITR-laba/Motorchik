# Отдельный PostgreSQL с pgvector (standalone)

## Описание

Создан отдельный контейнер PostgreSQL с расширением pgvector, который не связан с внутренней сетью Docker и доступен напрямую через localhost.

## Запуск

```bash
docker-compose -f docker-compose.postgres.yml up -d
```

## Параметры подключения

- **Хост:** `localhost` или `127.0.0.1`
- **Порт:** `5433` (чтобы не конфликтовать с существующим PostgreSQL на порту 5432)
- **База данных:** `vectordb`
- **Пользователь:** `postgres`
- **Пароль:** `password`

## URL подключения

```
postgresql://postgres:password@localhost:5433/vectordb
```

## Проверка подключения

```bash
# Из Python
python backend/test_postgres_connection.py "postgresql://postgres:password@127.0.0.1:5433/vectordb"

# Из Docker контейнера
docker exec -it postgres-pgvector psql -U postgres -d vectordb
```

## Остановка

```bash
docker-compose -f docker-compose.postgres.yml down
```

## Удаление данных

```bash
docker-compose -f docker-compose.postgres.yml down -v
```

## Настройка для использования в проекте

Для использования этого PostgreSQL в скриптах проекта (например, `elasticsearch_setup.py`), установите переменную окружения:

```bash
# Windows PowerShell
$env:POSTGRES_PORT="5433"

# Linux/Mac
export POSTGRES_PORT=5433
```

Или добавьте в файл `.env`:
```
POSTGRES_PORT=5433
DATABASE_URL=postgresql://postgres:password@localhost:5433/vectordb
```

## Особенности

- Контейнер не использует внутреннюю сеть Docker
- Доступен напрямую через localhost:5433
- Изолирован от других Docker-контейнеров
- Имеет собственный volume для данных
- Использует образ `ankane/pgvector:latest` с поддержкой векторных операций

