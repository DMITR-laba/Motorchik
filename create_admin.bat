@echo off
chcp 65001 >nul
echo 🚀 Создание администратора для AI-Портала техподдержки
echo ==================================================
echo.

REM Проверяем, что backend запущен
echo 🔍 Проверяем доступность API...
curl -s http://localhost:8000/docs >nul 2>&1
if errorlevel 1 (
    echo ❌ Ошибка: API сервер недоступен на http://localhost:8000
    echo    Убедитесь, что Docker контейнеры запущены:
    echo    docker-compose up -d
    pause
    exit /b 1
)

echo ✅ API сервер доступен

REM Создаем администратора
echo 👤 Создаем администратора...
for /f "delims=" %%i in ('curl -s -X POST http://localhost:8000/api/auth/bootstrap-admin') do set response=%%i

echo %response% | findstr "Admin created" >nul
if not errorlevel 1 (
    echo ✅ Администратор успешно создан!
    echo.
    echo 📋 Данные для входа:
    echo    🌐 URL: http://localhost:3000
    echo    📧 Email: admin@example.com
    echo    🔑 Пароль: admin
    echo.
    echo ⚠️  ВАЖНО: Смените пароль после первого входа!
    goto :check_auth
)

echo %response% | findstr "Admin already exists" >nul
if not errorlevel 1 (
    echo ℹ️  Администратор уже существует
    echo.
    echo 📋 Данные для входа:
    echo    🌐 URL: http://localhost:3000
    echo    📧 Email: admin@example.com
    echo    🔑 Пароль: admin
    goto :check_auth
)

echo ❌ Ошибка при создании администратора:
echo %response%
pause
exit /b 1

:check_auth
echo.
echo 🔐 Проверяем авторизацию...
for /f "delims=" %%i in ('curl -s -X POST http://localhost:8000/api/auth/token -H "Content-Type: application/x-www-form-urlencoded" -d "username=admin@example.com^&password=admin"') do set auth_response=%%i

echo %auth_response% | findstr "access_token" >nul
if not errorlevel 1 (
    echo ✅ Авторизация работает корректно
) else (
    echo ❌ Ошибка авторизации:
    echo %auth_response%
)

echo.
echo 🎉 Готово! Можете войти в систему по адресу http://localhost:3000
echo.
pause
