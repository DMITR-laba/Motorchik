# SSL настроен для https://app.domain ✅

## Статус

✅ SSL сертификаты созданы и настроены  
✅ HTTPS работает на порту 443  
✅ HTTP автоматически редиректит на HTTPS  
✅ Nginx конфигурация валидна  

## Доступ к приложению

- **HTTPS**: https://localhost
- **HTTPS**: https://app.domain (если настроен DNS)
- **HTTP**: http://localhost → автоматически редиректит на HTTPS

## Текущая конфигурация

### Используется самоподписанный сертификат

Сертификат создан для тестирования и включает:
- Домен: `app.domain`
- Wildcard: `*.app.domain`
- Localhost: `127.0.0.1`

**Расположение сертификатов:**
- `certbot/conf/live/app.domain/fullchain.pem` - сертификат
- `certbot/conf/live/app.domain/privkey.pem` - приватный ключ

### Важно

⚠️ **Браузер покажет предупреждение о безопасности** - это нормально для самоподписанного сертификата.

Для принятия сертификата в браузере:
1. Откройте https://localhost
2. Нажмите "Дополнительно" / "Advanced"
3. Нажмите "Перейти на сайт" / "Proceed to localhost"

## Для продакшена

Для замены на Let's Encrypt сертификат:

1. Убедитесь, что домен `app.domain` указывает на IP сервера
2. Выполните команды из `NGINX_SSL_SETUP.md`
3. Или используйте:

```bash
docker-compose run --rm certbot certonly --webroot \
  -w /var/www/certbot \
  --email your-email@example.com \
  -d app.domain \
  --rsa-key-size 4096 \
  --agree-tos

docker-compose exec nginx nginx -s reload
```

## Проверка работы

```bash
# Проверка конфигурации
docker-compose exec nginx nginx -t

# Проверка сертификатов
docker-compose exec nginx ls -lh /etc/letsencrypt/live/app.domain/

# Проверка HTTPS
curl -k https://localhost
```

## Структура

```
certbot/
└── conf/
    └── live/
        └── app.domain/
            ├── fullchain.pem  (сертификат)
            └── privkey.pem    (приватный ключ)
```

nginx/
└── conf.d/
    └── app.conf  (конфигурация с SSL)
```

## Безопасность

- ✅ TLS 1.2 и TLS 1.3 включены
- ✅ Современные шифры настроены
- ✅ Security headers добавлены (HSTS, X-Frame-Options, etc.)
- ✅ HTTP → HTTPS редирект настроен
- ⚠️ Самоподписанный сертификат (для продакшена замените на Let's Encrypt)

