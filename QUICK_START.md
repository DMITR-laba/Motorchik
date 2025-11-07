# 🚀 Быстрый старт - AI-Портал техподдержки

## ⚡ Установка за 5 минут

### 1. Установите Docker Desktop
- Скачайте с [docker.com](https://www.docker.com/products/docker-desktop/)
- Установите и запустите Docker Desktop

### 2. Клонируйте проект
```bash
git clone <URL_РЕПОЗИТОРИЯ> chat-assistant
cd chat-assistant
```

### 3. Настройте окружение
```bash
# Скопируйте конфигурацию
cp env.example .env

# Отредактируйте .env файл
# Обязательно укажите MISTRAL_API_KEY=your-key-here
```

### 4. Запустите систему
```bash
docker-compose up -d --build
```

### 5. Создайте администратора
```bash
curl -X POST http://localhost:8000/api/auth/bootstrap-admin
```

### 6. Войдите в систему
- **URL**: http://localhost:3000
- **Email**: admin@example.com
- **Пароль**: admin

---

## 🔑 Получение API ключа Mistral

1. Зайдите на [console.mistral.ai](https://console.mistral.ai/)
2. Зарегистрируйтесь или войдите
3. Создайте новый API ключ
4. Скопируйте ключ в файл `.env`:
```ini
MISTRAL_API_KEY=your-actual-key-here
```

---

## ✅ Проверка работы

### Веб-интерфейс:
- http://localhost:3000 - главная страница
- Войдите как admin@example.com / admin
- Нажмите ⚙️ для открытия админ панели

### API документация:
- http://localhost:8000/docs - Swagger UI

### Статус контейнеров:
```bash
docker-compose ps
```

---

## 🆘 Если что-то не работает

### Перезапуск:
```bash
docker-compose down
docker-compose up -d --build
```

### Логи:
```bash
docker-compose logs backend
docker-compose logs frontend
```

### Полная переустановка:
```bash
docker-compose down -v
docker-compose up -d --build
```

---

**🎉 Готово! Система запущена и готова к работе!**

Для подробной инструкции см. [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)
