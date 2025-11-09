#!/bin/sh
# Скрипт для создания самоподписанного SSL сертификата для тестирования

DOMAIN="app.domain"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
WWW_DIR="/var/www/certbot"

# Создаем директории
mkdir -p "${CERT_DIR}"
mkdir -p "${WWW_DIR}"

# Генерируем самоподписанный сертификат
openssl req -x509 -nodes -newkey rsa:4096 \
  -days 365 \
  -keyout "${CERT_DIR}/privkey.pem" \
  -out "${CERT_DIR}/fullchain.pem" \
  -subj "/CN=${DOMAIN}/O=Motorchik/C=RU" \
  -addext "subjectAltName=DNS:${DOMAIN},DNS:*.${DOMAIN},IP:127.0.0.1"

echo "✅ Самоподписанный SSL сертификат создан для ${DOMAIN}"
echo "📁 Сертификат: ${CERT_DIR}/fullchain.pem"
echo "🔑 Ключ: ${CERT_DIR}/privkey.pem"
echo ""
echo "⚠️  ВНИМАНИЕ: Это самоподписанный сертификат для тестирования!"
echo "   Браузер будет показывать предупреждение о безопасности."
echo "   Для продакшена используйте Let's Encrypt (см. NGINX_SSL_SETUP.md)"

