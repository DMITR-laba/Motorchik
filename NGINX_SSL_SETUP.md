# Настройка Nginx с SSL для домена app.domain

## Обзор

Эта конфигурация настраивает Nginx как reverse proxy с SSL сертификатами от Let's Encrypt для доступа к приложению по доменному имени.

## Требования

1. **Доменное имя** должно указывать на IP-адрес вашего сервера (A-запись в DNS)
2. **Порты 80 и 443** должны быть открыты в firewall
3. Docker и Docker Compose установлены

## Шаг 1: Настройка доменного имени

В файле `nginx/conf.d/app.conf` замените `app.domain` на ваше реальное доменное имя:

```nginx
server_name your-domain.com;
```

Замените во всех местах:
- Строка 4: `server_name app.domain;`
- Строка 38: `server_name app.domain;`

## Шаг 2: Создание директорий для сертификатов

```bash
mkdir -p certbot/conf certbot/www
```

## Шаг 3: Запуск сервисов (без SSL)

Сначала запустите все сервисы для получения сертификата:

```bash
docker-compose up -d
```

## Шаг 4: Получение SSL сертификата

### Вариант 1: Автоматический (рекомендуется)

```bash
# Войдите в контейнер nginx
docker-compose exec nginx sh

# Получите сертификат
certbot certonly --webroot \
  -w /var/www/certbot \
  --email your-email@example.com \
  -d app.domain \
  --rsa-key-size 4096 \
  --agree-tos \
  --force-renewal

# Выйдите из контейнера
exit

# Перезагрузите nginx
docker-compose exec nginx nginx -s reload
```

### Вариант 2: Через certbot контейнер

```bash
docker-compose run --rm certbot certonly --webroot \
  -w /var/www/certbot \
  --email your-email@example.com \
  -d app.domain \
  --rsa-key-size 4096 \
  --agree-tos \
  --force-renewal

docker-compose exec nginx nginx -s reload
```

## Шаг 5: Включение HTTPS редиректа

После успешного получения сертификата, отредактируйте `nginx/conf.d/app.conf`:

1. Закомментируйте блок с `proxy_pass`:
```nginx
# location / {
#     proxy_pass http://motorchik-frontend:80;
#     ...
# }
```

2. Раскомментируйте редирект:
```nginx
location / {
    return 301 https://$host$request_uri;
}
```

3. Перезагрузите nginx:
```bash
docker-compose exec nginx nginx -s reload
```

## Шаг 6: Проверка

1. Откройте `https://app.domain` в браузере
2. Проверьте, что сертификат валиден (зеленый замочек)
3. Проверьте, что API доступен по `https://app.domain/api/`
4. Проверьте, что HTTP редиректит на HTTPS

## Автоматическое обновление сертификатов

Сертификаты автоматически обновляются каждые 12 часов через certbot контейнер.

Для ручного обновления:

```bash
docker-compose run --rm certbot renew
docker-compose exec nginx nginx -s reload
```

## Структура файлов

```
nginx/
├── Dockerfile              # Образ nginx
├── nginx.conf              # Основная конфигурация nginx
├── conf.d/
│   └── app.conf            # Конфигурация для домена
├── init-letsencrypt.sh     # Скрипт инициализации (опционально)
└── README.md               # Документация

certbot/
├── conf/                   # Сертификаты Let's Encrypt
│   └── live/
│       └── app.domain/
│           ├── fullchain.pem
│           └── privkey.pem
└── www/                    # Webroot для проверки домена
```

## Troubleshooting

### Проблема: "Connection refused"

**Решение:**
- Убедитесь, что домен указывает на правильный IP (проверьте: `nslookup app.domain`)
- Проверьте, что порты 80 и 443 открыты в firewall
- Проверьте, что nginx контейнер запущен: `docker-compose ps nginx`

### Проблема: "Certificate not found"

**Решение:**
- Проверьте пути к сертификатам в `nginx/conf.d/app.conf`
- Убедитесь, что certbot успешно создал сертификаты: `ls -la certbot/conf/live/app.domain/`
- Проверьте логи certbot: `docker-compose logs certbot`

### Проблема: "502 Bad Gateway"

**Решение:**
- Проверьте, что backend и frontend контейнеры запущены: `docker-compose ps`
- Проверьте логи nginx: `docker-compose logs nginx`
- Проверьте логи backend: `docker-compose logs motorchik-backend`
- Проверьте, что контейнеры в одной сети: `docker network inspect motorchik-net`

### Проблема: "Let's Encrypt validation failed"

**Решение:**
- Убедитесь, что домен доступен из интернета
- Проверьте, что порт 80 открыт (нужен для валидации)
- Проверьте, что `.well-known/acme-challenge/` доступен: `curl http://app.domain/.well-known/acme-challenge/test`

### Проблема: "Too many requests" от Let's Encrypt

**Решение:**
- Используйте `--staging` флаг для тестирования
- Подождите несколько часов перед повторной попыткой
- Проверьте лимиты на https://letsencrypt.org/docs/rate-limits/

## Дополнительные настройки

### Изменение таймаутов

В `nginx/conf.d/app.conf` можно настроить:
- `proxy_read_timeout` - таймаут чтения ответа
- `proxy_connect_timeout` - таймаут подключения
- `keepalive_timeout` - таймаут keep-alive соединений

### Добавление дополнительных доменов

Добавьте новый server блок в `nginx/conf.d/app.conf` или создайте отдельный файл конфигурации.

### Настройка rate limiting

Добавьте в `nginx/conf.d/app.conf`:

```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

server {
    ...
    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
        ...
    }
}
```

## Безопасность

- SSL сертификаты автоматически обновляются
- Включены security headers (HSTS, X-Frame-Options, etc.)
- Используются современные TLS протоколы (TLSv1.2, TLSv1.3)
- Все HTTP запросы редиректятся на HTTPS

## Поддержка

При возникновении проблем проверьте:
1. Логи nginx: `docker-compose logs nginx`
2. Логи certbot: `docker-compose logs certbot`
3. Конфигурацию nginx: `docker-compose exec nginx nginx -t`

