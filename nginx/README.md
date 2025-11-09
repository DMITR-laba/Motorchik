# Настройка Nginx с SSL для app.domain

## Требования

1. Доменное имя должно указывать на IP-адрес сервера
2. Порты 80 и 443 должны быть открыты в firewall
3. Docker и Docker Compose установлены

## Быстрая настройка

### 1. Замените доменное имя

В файле `nginx/conf.d/app.conf` замените `app.domain` на ваше реальное доменное имя:

```nginx
server_name your-domain.com;
```

### 2. Создайте директории для сертификатов

```bash
mkdir -p certbot/conf certbot/www
```

### 3. Инициализируйте Let's Encrypt сертификаты

```bash
cd nginx
chmod +x init-letsencrypt.sh
./init-letsencrypt.sh
```

Или вручную:

```bash
# Создайте временный сертификат
docker-compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:4096 -days 1\
    -keyout '/etc/letsencrypt/live/app.domain/privkey.pem' \
    -out '/etc/letsencrypt/live/app.domain/fullchain.pem' \
    -subj '/CN=localhost'" certbot

# Запустите nginx
docker-compose up -d nginx

# Получите реальный сертификат
docker-compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    --email your-email@example.com \
    -d app.domain \
    --rsa-key-size 4096 \
    --agree-tos \
    --force-renewal" certbot

# Перезагрузите nginx
docker-compose exec nginx nginx -s reload
```

### 4. Запустите все сервисы

```bash
docker-compose up -d
```

## Обновление сертификатов

Сертификаты автоматически обновляются каждые 12 часов через certbot контейнер.

Для ручного обновления:

```bash
docker-compose run --rm certbot renew
docker-compose exec nginx nginx -s reload
```

## Проверка

1. Откройте `https://app.domain` в браузере
2. Проверьте, что сертификат валиден (зеленый замочек)
3. Проверьте, что API доступен по `https://app.domain/api/`

## Troubleshooting

### Проблема: "Connection refused"

- Убедитесь, что домен указывает на правильный IP
- Проверьте, что порты 80 и 443 открыты

### Проблема: "Certificate not found"

- Проверьте пути к сертификатам в `nginx/conf.d/app.conf`
- Убедитесь, что certbot успешно создал сертификаты

### Проблема: "502 Bad Gateway"

- Проверьте, что backend и frontend контейнеры запущены
- Проверьте логи: `docker-compose logs nginx`

## Структура файлов

```
nginx/
├── Dockerfile              # Образ nginx
├── nginx.conf              # Основная конфигурация nginx
├── conf.d/
│   └── app.conf             # Конфигурация для app.domain
├── init-letsencrypt.sh     # Скрипт инициализации сертификатов
└── README.md               # Этот файл

certbot/
├── conf/                   # Сертификаты Let's Encrypt
└── www/                    # Webroot для проверки домена
```

