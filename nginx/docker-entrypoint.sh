#!/bin/sh
set -e

DOMAIN="app.domain"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
WWW_DIR="/var/www/certbot"

# Создаем директории если их нет
mkdir -p "${CERT_DIR}"
mkdir -p "${WWW_DIR}"

# Проверяем наличие сертификатов
if [ ! -f "${CERT_DIR}/fullchain.pem" ] || [ ! -f "${CERT_DIR}/privkey.pem" ]; then
    echo "⚠️  SSL сертификаты не найдены. Генерирую самоподписанный сертификат..."
    
    # Генерируем самоподписанный сертификат
    openssl req -x509 -nodes -newkey rsa:4096 \
        -days 365 \
        -keyout "${CERT_DIR}/privkey.pem" \
        -out "${CERT_DIR}/fullchain.pem" \
        -subj "/CN=${DOMAIN}/O=Motorchik/C=RU" \
        -addext "subjectAltName=DNS:${DOMAIN},DNS:*.${DOMAIN},DNS:localhost,IP:127.0.0.1,IP:0.0.0.0" 2>/dev/null || \
    openssl req -x509 -nodes -newkey rsa:4096 \
        -days 365 \
        -keyout "${CERT_DIR}/privkey.pem" \
        -out "${CERT_DIR}/fullchain.pem" \
        -subj "/CN=${DOMAIN}/O=Motorchik/C=RU"
    
    echo "✅ Самоподписанный SSL сертификат создан для ${DOMAIN}"
    echo "📁 Сертификат: ${CERT_DIR}/fullchain.pem"
    echo "🔑 Ключ: ${CERT_DIR}/privkey.pem"
    echo ""
    echo "⚠️  ВНИМАНИЕ: Это самоподписанный сертификат для тестирования!"
    echo "   Браузер будет показывать предупреждение о безопасности."
    echo "   Для продакшена используйте Let's Encrypt (см. NGINX_SSL_SETUP.md)"
else
    echo "✅ SSL сертификаты найдены: ${CERT_DIR}/fullchain.pem"
fi

# Проверяем конфигурацию nginx
echo "🔍 Проверяю конфигурацию nginx..."
nginx -t

# Запускаем nginx
echo "🚀 Запускаю nginx..."
exec "$@"


