# 🚀 Основные команды для работы с AI-Порталом техподдержки

## 📦 Управление Docker контейнерами

### Запуск системы
```bash
# Сборка и запуск всех сервисов
docker-compose up -d --build

# Только запуск (без пересборки)
docker-compose up -d
```

### Остановка системы
```bash
# Остановка всех сервисов
docker-compose down

# Остановка с удалением данных
docker-compose down -v
```

### Перезапуск сервисов
```bash
# Перезапуск всех сервисов
docker-compose restart

# Перезапуск конкретного сервиса
docker-compose restart backend
docker-compose restart frontend
docker-compose restart postgres
```

### Просмотр логов
```bash
# Логи всех сервисов
docker-compose logs

# Логи конкретного сервиса
docker-compose logs backend
docker-compose logs frontend
docker-compose logs postgres

# Логи в реальном времени
docker-compose logs -f backend
```

### Статус контейнеров
```bash
# Проверка статуса
docker-compose ps

# Использование ресурсов
docker stats
```

## 👤 Управление пользователями

### Создание администратора
```bash
# Через API
curl -X POST http://localhost:8000/api/auth/bootstrap-admin

# Через скрипты
./create_admin.sh          # Linux/Mac
create_admin.bat           # Windows
create_admin.ps1           # Windows PowerShell
```

### Авторизация
```bash
# Получение токена
curl -X POST http://localhost:8000/api/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=admin"
```

### Управление пользователями через API
```bash
# Получение списка пользователей
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/auth/users

# Создание пользователя
curl -X POST http://localhost:8000/api/auth/users \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "full_name": "Пользователь",
    "password": "password123",
    "role": "user"
  }'

# Удаление пользователя
curl -X DELETE http://localhost:8000/api/auth/users/USER_ID \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 🗄️ Работа с базой данных

### Подключение к PostgreSQL
```bash
# Подключение к базе данных
docker-compose exec postgres psql -U postgres -d vectordb

# Проверка таблиц
\dt

# Проверка пользователей
SELECT id, email, role, created_at FROM users;

# Выход
\q
```

### Резервное копирование
```bash
# Создание бэкапа
docker-compose exec postgres pg_dump -U postgres vectordb > backup.sql

# Восстановление из бэкапа
docker-compose exec -T postgres psql -U postgres vectordb < backup.sql
```

## 📊 Импорт данных

### Импорт статей
```bash
# Через API (требует токен администратора)
curl -X POST http://localhost:8000/api/admin/import/articles \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d @articles.json
```

### Импорт документов
```bash
# Загрузка документа через API
curl -X POST http://localhost:8000/api/documents/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@document.pdf" \
  -F "language=ru" \
  -F "category_id=1"
```

## 🔧 Отладка и устранение неполадок

### Проверка доступности сервисов
```bash
# Проверка API
curl http://localhost:8000/docs

# Проверка frontend
curl http://localhost:3000

# Проверка базы данных
docker-compose exec postgres pg_isready -U postgres
```

### Очистка системы
```bash
# Очистка неиспользуемых образов
docker system prune -a

# Очистка volumes
docker volume prune

# Полная очистка
docker system prune -a --volumes
```

### Пересборка контейнеров
```bash
# Пересборка всех контейнеров
docker-compose build --no-cache

# Пересборка конкретного сервиса
docker-compose build --no-cache backend
docker-compose build --no-cache frontend
```

## 🌐 Доступ к сервисам

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API документация**: http://localhost:8000/docs
- **База данных**: localhost:5432 (postgres/password)

## 📝 Полезные файлы

- **Конфигурация**: `.env`
- **Docker Compose**: `docker-compose.yml`
- **Логи**: `docker-compose logs`
- **Бэкапы**: `backup.sql`

---

**💡 Совет**: Используйте `docker-compose logs -f` для мониторинга логов в реальном времени при отладке.
