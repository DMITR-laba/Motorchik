# Настройка ИИ-парсера

## Установка зависимостей

### Базовые зависимости
```bash
pip install beautifulsoup4 httpx
```

### ИИ-компоненты (опционально, но рекомендуется)

#### 1. Ollama для LLM извлечения данных ⭐ **РЕКОМЕНДУЕТСЯ**
```bash
# Установка Ollama (см. https://ollama.ai)
# После установки загрузите модель:
ollama pull llama3:8b
# Или другую модель:
ollama pull mistral
ollama pull qwen2:7b
```

#### 2. spaCy для NLP
```bash
# Установка spaCy
pip install spacy

# Загрузка русской модели
python -m spacy download ru_core_news_md
# Или меньшая модель
python -m spacy download ru_core_news_sm
```

#### 3. Transformers для анализа тональности
```bash
pip install transformers torch
```

## Возможности ИИ-парсера

### 1. ⭐ Ollama LLM извлечение данных (НОВОЕ)
- **Структурированное извлечение** - LLM анализирует текст страницы и извлекает все данные в JSON
- **Высокая точность** - понимает контекст и различные форматы данных
- **Адаптивность** - работает с разными структурами страниц
- **Поддержка моделей** - llama3, mistral, qwen2 и другие модели Ollama

### 2. NLP извлечение сущностей
- **Даты** - автоматическое извлечение года выпуска
- **Организации** - марки автомобилей
- **Локации** - города расположения
- **Деньги** - цены в различных форматах
- **Продукты** - модели автомобилей

### 3. Классификация элементов
Автоматическая классификация элементов страницы:
- Цена
- Год выпуска
- Тип кузова
- Тип топлива
- Коробка передач
- Привод
- Объем двигателя
- Мощность
- Пробег
- Цвет
- Локация

### 4. Анализ тональности
Оценка тональности описаний автомобилей (положительная/отрицательная).

### 5. Обнаружение изменений структуры
Автоматическое обнаружение изменений в структуре сайта для адаптации парсера.

## Использование

### Через API

#### ИИ-парсер с Ollama (рекомендуется)
```bash
curl -X POST "http://localhost:8000/api/parser/start" \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://aaa-motors.ru",
    "max_pages": 5,
    "max_cars": 50,
    "delay": 1.0,
    "use_ai": true,
    "use_ollama": true,
    "ollama_model": "llama3:8b"
  }'
```

#### ИИ-парсер без Ollama
```bash
curl -X POST "http://localhost:8000/api/parser/start" \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://aaa-motors.ru",
    "max_pages": 5,
    "max_cars": 50,
    "delay": 1.0,
    "use_ai": true,
    "use_ollama": false
  }'
```

#### Базовый парсер (без ИИ)
```bash
curl -X POST "http://localhost:8000/api/parser/start" \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://aaa-motors.ru",
    "max_pages": 5,
    "max_cars": 50,
    "delay": 1.0,
    "use_ai": false
  }'
```

### Программно

```python
from services.ai_parser_service import AIParser
from models import get_db

db = next(get_db())
parser = AIParser(db_session=db, base_url="https://aaa-motors.ru")

result = parser.parse(
    max_pages=5,
    max_cars=50,
    delay=1.0
)

print(result)
```

## Статистика ИИ-парсера

Парсер отслеживает:
- `total_parsed` - количество успешно обработанных автомобилей
- `total_errors` - количество ошибок
- `nlp_extractions` - количество успешных NLP извлечений
- `ollama_extractions` - количество успешных извлечений через Ollama
- `structure_changes_detected` - обнаруженные изменения структуры страниц

## Преимущества ИИ-парсера

1. ⭐ **Высокая точность с Ollama** - LLM понимает контекст и извлекает данные даже из неструктурированного текста
2. **NLP извлечение** - spaCy извлечение сущностей более точно, чем регулярные выражения
3. **Адаптивность** - автоматическое обнаружение изменений структуры
4. **Гибкость** - классификация элементов позволяет находить данные в разных форматах
5. **Анализ** - дополнительная информация о тональности и сущностях
6. **Комбинированный подход** - Ollama + NLP + классификация для максимальной точности

## Производительность

- **Базовый парсер**: ~2-3 страницы/сек
- **ИИ-парсер (без Ollama)**: ~1-2 страницы/сек (из-за NLP обработки)
- **ИИ-парсер (с Ollama)**: ~0.5-1 страница/сек (из-за LLM обработки)

Рекомендуется использовать задержку `delay >= 1.0` для избежания блокировок.

**Примечание:** Ollama может работать медленнее, но обеспечивает более высокую точность извлечения данных.

## Troubleshooting

### spaCy модель не найдена
```bash
python -m spacy download ru_core_news_md
```

### Transformers требует много памяти
Используйте меньшую модель или отключите анализ тональности:
```python
parser = AIParser(...)
parser.sentiment_analyzer = None  # Отключить анализ тональности
```

### Ollama недоступен
1. Убедитесь, что Ollama запущен:
```bash
ollama serve
```

2. Проверьте доступность модели:
```bash
ollama list
```

3. Если модель не установлена, загрузите её:
```bash
ollama pull llama3:8b
```

4. В API запросе можно отключить Ollama:
```json
{
  "use_ollama": false
}
```

### Медленная работа
- Уменьшите `max_pages` и `max_cars`
- Увеличьте `delay`
- Используйте базовый парсер (`use_ai: false`)

