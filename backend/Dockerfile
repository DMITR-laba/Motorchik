FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements и установка Python зависимостей
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r /app/requirements.txt

# Копирование кода приложения
COPY . /app

# Установка прав на entrypoint скрипт и исправление окончаний строк (CRLF -> LF)
RUN if [ ! -f /app/docker-entrypoint.sh ]; then \
        echo "ERROR: docker-entrypoint.sh not found!" && \
        ls -la /app/ | grep -E "(docker|entrypoint)" && \
        exit 1; \
    fi && \
    chmod +x /app/docker-entrypoint.sh && \
    sed -i 's/\r$//' /app/docker-entrypoint.sh && \
    echo "✅ docker-entrypoint.sh готов к использованию"

EXPOSE 8000

# Используем entrypoint скрипт
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]



