# PowerShell скрипт для создания самоподписанного SSL сертификата
$certDir = "certbot\conf\live\app.domain"
New-Item -ItemType Directory -Force -Path $certDir | Out-Null

# Проверяем наличие OpenSSL
$opensslPath = Get-Command openssl -ErrorAction SilentlyContinue

if ($opensslPath) {
    Write-Host "Создание самоподписанного сертификата через OpenSSL..."
    
    # Создаем приватный ключ
    & openssl genrsa -out "$certDir\privkey.pem" 4096
    
    # Создаем конфигурацию для SAN
    $config = @"
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
[v3_req]
subjectAltName = @alt_names
[alt_names]
DNS.1 = app.domain
DNS.2 = *.app.domain
IP.1 = 127.0.0.1
[req_distinguished_name]
CN = app.domain
O = Motorchik
C = RU
"@
    $config | Out-File -FilePath "$certDir\openssl.conf" -Encoding ASCII
    
    # Создаем сертификат
    & openssl req -new -x509 -key "$certDir\privkey.pem" -out "$certDir\fullchain.pem" -days 365 -config "$certDir\openssl.conf" -extensions v3_req -subj "/CN=app.domain/O=Motorchik/C=RU"
    
    Write-Host "✅ Сертификат создан: $certDir\fullchain.pem"
} else {
    Write-Host "OpenSSL не найден. Используем встроенные средства Windows..."
    
    # Используем New-SelfSignedCertificate (Windows)
    $cert = New-SelfSignedCertificate `
        -DnsName "app.domain", "*.app.domain", "localhost" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 4096 `
        -NotAfter (Get-Date).AddYears(1)
    
    # Экспортируем сертификат
    $certPath = "Cert:\CurrentUser\My\$($cert.Thumbprint)"
    $pwd = ConvertTo-SecureString -String "temp" -Force -AsPlainText
    
    # Экспортируем сертификат в PFX
    Export-PfxCertificate -Cert $certPath -FilePath "$certDir\temp.pfx" -Password $pwd | Out-Null
    
    # Конвертируем PFX в PEM (нужен OpenSSL или другой инструмент)
    Write-Host "⚠️  Для конвертации PFX в PEM нужен OpenSSL"
    Write-Host "   Или используйте Docker контейнер для создания сертификата"
    Write-Host "   Сертификат создан в Windows хранилище: $certPath"
}

