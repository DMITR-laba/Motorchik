# PowerShell скрипт для создания администратора AI-Портала техподдержки
# Использование: .\create_admin.ps1

Write-Host "🚀 Создание администратора для AI-Портала техподдержки" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""

# Проверяем, что backend запущен
Write-Host "🔍 Проверяем доступность API..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/docs" -UseBasicParsing -TimeoutSec 5
    Write-Host "✅ API сервер доступен" -ForegroundColor Green
} catch {
    Write-Host "❌ Ошибка: API сервер недоступен на http://localhost:8000" -ForegroundColor Red
    Write-Host "   Убедитесь, что Docker контейнеры запущены:" -ForegroundColor Yellow
    Write-Host "   docker-compose up -d" -ForegroundColor Yellow
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# Создаем администратора
Write-Host "👤 Создаем администратора..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/auth/bootstrap-admin" -Method POST
    Write-Host "✅ Администратор успешно создан!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📋 Данные для входа:" -ForegroundColor Cyan
    Write-Host "   🌐 URL: http://localhost:3000" -ForegroundColor White
    Write-Host "   📧 Email: admin@example.com" -ForegroundColor White
    Write-Host "   🔑 Пароль: admin" -ForegroundColor White
    Write-Host ""
    Write-Host "⚠️  ВАЖНО: Смените пароль после первого входа!" -ForegroundColor Yellow
} catch {
    $errorResponse = $_.Exception.Response
    if ($errorResponse.StatusCode -eq 200) {
        Write-Host "ℹ️  Администратор уже существует" -ForegroundColor Blue
        Write-Host ""
        Write-Host "📋 Данные для входа:" -ForegroundColor Cyan
        Write-Host "   🌐 URL: http://localhost:3000" -ForegroundColor White
        Write-Host "   📧 Email: admin@example.com" -ForegroundColor White
        Write-Host "   🔑 Пароль: admin" -ForegroundColor White
    } else {
        Write-Host "❌ Ошибка при создании администратора:" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red
        Read-Host "Нажмите Enter для выхода"
        exit 1
    }
}

# Проверяем авторизацию
Write-Host ""
Write-Host "🔐 Проверяем авторизацию..." -ForegroundColor Yellow
try {
    $body = @{
        username = "admin@example.com"
        password = "admin"
    }
    $authResponse = Invoke-RestMethod -Uri "http://localhost:8000/api/auth/token" -Method POST -Body $body -ContentType "application/x-www-form-urlencoded"
    Write-Host "✅ Авторизация работает корректно" -ForegroundColor Green
} catch {
    Write-Host "❌ Ошибка авторизации:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "🎉 Готово! Можете войти в систему по адресу http://localhost:3000" -ForegroundColor Green
Write-Host ""
Read-Host "Нажмите Enter для выхода"
