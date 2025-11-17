# API для управления моделями AI

**Дата:** 2025-11-16

---

## 📋 Обзор

API для управления моделями AI из интерфейса. Позволяет:
- Просматривать текущую конфигурацию моделей
- Обновлять модели для конкретных задач
- Тестировать модели
- Просматривать метрики производительности
- Управлять основными настройками AI

---

## 🔗 Endpoints

### 1. Получение конфигурации моделей

**GET** `/api/models/config`

Получает текущую конфигурацию всех моделей.

**Ответ:**
```json
{
  "task_model_mapping": {
    "query_analysis": {
      "primary": "ollama:llama3:8b",
      "fallback": "ollama:llama3:8b",
      "complexity": "light"
    },
    "response_generation": {
      "primary": "mistral:mistral-large-latest",
      "fallback": "ollama:llama3:8b",
      "complexity": "light"
    }
  },
  "available_models": [
    "ollama:llama3:8b",
    "mistral:mistral-large-latest",
    "openai:gpt-4"
  ],
  "current_ai_settings": {
    "response_model": "mistral:mistral-large-latest",
    "embedding_model": "",
    "api_service": "mistral",
    "api_key": "..."
  }
}
```

---

### 2. Обновление модели для задачи

**PUT** `/api/models/config/task` (требует админ-прав)

Обновляет модель для конкретной задачи.

**Запрос:**
```json
{
  "task_type": "response_generation",
  "primary": "mistral:mistral-large-latest",
  "fallback": "ollama:llama3:8b",
  "complexity": "light"
}
```

**Ответ:**
```json
{
  "success": true,
  "message": "Модель для задачи 'response_generation' обновлена",
  "task_config": {
    "primary": "mistral:mistral-large-latest",
    "fallback": "ollama:llama3:8b",
    "complexity": "light"
  }
}
```

---

### 3. Массовое обновление моделей

**PUT** `/api/models/config/bulk` (требует админ-прав)

Обновляет модели для нескольких задач одновременно.

**Запрос:**
```json
{
  "updates": [
    {
      "task_type": "response_generation",
      "primary": "mistral:mistral-large-latest"
    },
    {
      "task_type": "sql_generation",
      "primary": "ollama:codellama:34b"
    }
  ]
}
```

**Ответ:**
```json
{
  "success": true,
  "updated_tasks": ["response_generation", "sql_generation"],
  "errors": []
}
```

---

### 4. Обновление основных настроек AI

**PUT** `/api/models/settings` (требует админ-прав)

Обновляет основные настройки AI (response_model, api_key и т.д.).

**Запрос:**
```json
{
  "response_model": "mistral:mistral-large-latest",
  "embedding_model": "",
  "api_service": "mistral",
  "api_key": "your-api-key",
  "deep_thinking_model": "",
  "deepseek_api_key": ""
}
```

**Ответ:**
```json
{
  "success": true,
  "message": "Настройки AI обновлены",
  "settings": {
    "response_model": "mistral:mistral-large-latest",
    "updated_at": "2025-11-16T12:00:00"
  }
}
```

---

### 5. Тестирование модели

**POST** `/api/models/test` (требует админ-прав)

Тестирует модель с заданным промптом.

**Запрос:**
```json
{
  "model_name": "mistral:mistral-large-latest",
  "task_type": "response_generation",
  "test_prompt": "Привет! Это тестовое сообщение."
}
```

**Ответ:**
```json
{
  "success": true,
  "response": "Привет! Чем могу помочь?",
  "response_time": 1.23,
  "model_info": {
    "model": "mistral-large-latest",
    "provider": "mistral"
  }
}
```

---

### 6. Получение метрик производительности

**GET** `/api/models/performance` (требует админ-прав)

Получает метрики производительности моделей.

**Параметры запроса:**
- `model_name` (опционально) - фильтр по модели
- `task_type` (опционально) - фильтр по типу задачи

**Ответ:**
```json
[
  {
    "model_name": "mistral:mistral-large-latest",
    "task_type": "response_generation",
    "success_rate": 0.95,
    "avg_response_time": 1.23,
    "total_requests": 100,
    "last_used": "2025-11-16T12:00:00"
  }
]
```

---

### 7. Получение списка доступных моделей

**GET** `/api/models/available`

Получает список всех доступных моделей, сгруппированных по провайдерам.

**Ответ:**
```json
{
  "all_models": [
    "ollama:llama3:8b",
    "mistral:mistral-large-latest",
    "openai:gpt-4"
  ],
  "grouped_by_provider": {
    "ollama": ["llama3:8b", "mixtral:8b"],
    "mistral": ["mistral-large-latest", "mistral-medium-latest"],
    "openai": ["gpt-4", "gpt-3.5-turbo"],
    "anthropic": ["claude-3-opus-20240229"],
    "deepseek": [],
    "other": []
  },
  "total_count": 15
}
```

---

## 📝 Типы задач

Доступные типы задач для настройки моделей:

- `query_analysis` - Анализ запросов пользователя
- `search_intent_analysis` - Анализ намерения поиска
- `relation_analysis` - Анализ связанности запросов
- `sql_generation` - Генерация SQL-запросов
- `response_generation` - Генерация ответов пользователю
- `query_refinement` - Уточнение запросов
- `fuzzy_interpretation` - Интерпретация размытых запросов
- `filter_relaxation` - Ослабление фильтров
- `result_processing` - Обработка результатов поиска
- `recommendation` - Рекомендации
- `emotion_analysis` - Анализ эмоций
- `question_generation` - Генерация вопросов
- `proactive_suggestions` - Проактивные предложения

---

## 🔒 Безопасность

Большинство endpoints требуют админ-прав (`require_admin`). Только просмотр конфигурации и списка моделей доступны всем пользователям.

---

## ✅ Статус

**API готов к использованию!**  
**Все endpoints реализованы и протестированы!**

