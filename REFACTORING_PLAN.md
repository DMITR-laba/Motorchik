# План рефакторинга архитектуры проекта

**Дата создания:** 2025-11-16  
**Основа:** Рекомендации из `idea.md`

---

## 📋 Содержание

1. [Анализ текущего состояния](#анализ-текущего-состояния)
2. [Критические проблемы](#критические-проблемы)
3. [План реализации](#план-реализации)
4. [Этапы миграции](#этапы-миграции)
5. [Детальная реализация](#детальная-реализация)

---

## 🔍 Анализ текущего состояния

### Что уже есть:

✅ **LangGraph** - частично реализован в `langgraph_rag_service.py` (обертка над RAGService)  
✅ **pgvector** - используется для векторного поиска  
✅ **Elasticsearch** - полнотекстовый поиск  
✅ **Mem0 + Qdrant** - долговременная память  
✅ **Redis** - кэш и состояние  
✅ **SQL Agent** - отдельный сервис  
✅ **RAG Service** - основной сервис генерации ответов  

### Проблемы:

❌ **Множественные пути обработки** - запрос может идти через 4+ разных сервиса  
❌ **Избыточность хранилищ** - pgvector + Qdrant для одной задачи  
❌ **Разрозненная логика** - нет единого координатора  
❌ **Сложная система памяти** - Redis → Mem0 → Qdrant  
❌ **SQL Agent изолирован** - не интегрирован в основной поток  
❌ **chat_id nullable** - архитектурная ошибка в модели данных  

---

## 🚨 Критические проблемы

### 1. Архитектурная переусложненность

**Текущая ситуация:**
```
Запрос → [Маршрутизатор] → [Один из 5 сервисов] → Ответ
```

**Проблемы:**
- Противоречивые ответы
- Сложность дебага
- Дублирование кода
- Нет единого контекста

### 2. Избыточность хранилищ

**Текущая ситуация:**
- PostgreSQL (основные данные)
- Elasticsearch (поиск)
- pgvector (векторы автомобилей)
- Qdrant (векторы для Mem0)
- Redis (кэш)

**Проблемы:**
- Рассинхронизация данных
- Сложность поддержки
- Избыточные ресурсы

### 3. Размазанная логика диалога

**Текущая ситуация:**
- `DialogStateService` - состояние
- `DialogueHistoryService` - история
- `Mem0Service` - долговременная память
- `LangGraphRAGService` - управление потоком
- `RAGService` - генерация ответов

**Проблемы:**
- Нет единого координатора
- Сложно отследить полный контекст
- Дублирование логики

---

## 🎯 План реализации

### Цель

Создать **единую, целостную диалоговую систему** с памятью, где все компоненты работают согласованно.

### Принципы

1. **Единое ядро** - LangGraph как центральный координатор
2. **Унификация хранилищ** - один источник истины
3. **Инструменты вместо сервисов** - все сервисы становятся инструментами агента
4. **Упрощение памяти** - прямое использование pgvector
5. **Проактивность** - агент сам решает, что нужно пользователю

---

## 📅 Этапы миграции

### Этап 1: Подготовка инфраструктуры (1 неделя)

#### 1.1. Создание таблицы для памяти пользователя

**Файл:** `backend/migrations/add_user_memories_table.py`

```sql
CREATE TABLE user_memories (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    memory_type VARCHAR(50) NOT NULL,  -- 'preference', 'rejection', 'interest', 'criteria'
    memory_text TEXT NOT NULL,
    embedding VECTOR(1024),
    metadata JSONB DEFAULT '{}',
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_memories_semantic 
ON user_memories 
USING ivfflat (embedding vector_cosine_ops) 
WHERE user_id IS NOT NULL;

CREATE INDEX idx_user_memories_user_type 
ON user_memories (user_id, memory_type);
```

#### 1.2. Исправление модели ChatMessage

**Файл:** `backend/models/database.py`

```python
class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)  # УБРАТЬ nullable=True
```

**Миграция:**
```sql
-- Обновить существующие записи без chat_id
UPDATE chat_messages SET chat_id = (SELECT id FROM chats WHERE user_id = chat_messages.user_id LIMIT 1) WHERE chat_id IS NULL;

-- Убрать nullable
ALTER TABLE chat_messages ALTER COLUMN chat_id SET NOT NULL;
```

#### 1.3. Создание UnifiedMemoryService

**Файл:** `backend/services/unified_memory_service.py`

**Основные методы:**
- `get_user_context(user_id, query)` - получение всего контекста
- `save_memory(user_id, memory_data)` - сохранение памяти
- `get_user_preferences(user_id, query)` - поиск предпочтений
- `extract_entities(messages)` - извлечение сущностей

**Зависимости:**
- PostgreSQL + pgvector
- Embedding service (Mistral/Ollama)

---

### Этап 2: Создание единого агента (2 недели)

#### 2.1. Создание CarDealerAgent

**Файл:** `backend/services/car_dealer_agent.py`

**Структура AgentState:**
```python
class AgentState(TypedDict):
    # Входные данные
    user_input: str
    user_id: str
    session_id: str
    
    # Контекст диалога
    chat_history: List[dict]
    dialogue_context: dict
    user_preferences: List[dict]
    
    # Поисковые результаты
    search_criteria: dict
    search_results: list
    knowledge_results: list
    
    # Состояние
    current_intent: str
    needs_clarification: bool
    clarification_questions: List[str]
    
    # Выходные данные
    response: str
    suggested_actions: List[str]
    memory_updates: List[dict]
    used_tools: List[str]
```

**Граф состояний:**
```
analyze_intent → [route_by_intent] → 
    ├─→ search_cars → extract_preferences → generate_response → update_memory → END
    ├─→ search_knowledge → extract_preferences → generate_response → update_memory → END
    ├─→ extract_parameters → search_cars → ...
    └─→ generate_response → update_memory → END
```

**Узлы графа:**
1. `analyze_intent` - анализ намерения пользователя
2. `extract_parameters` - извлечение параметров через LLM
3. `search_cars` - поиск автомобилей (через UnifiedSearchService)
4. `search_knowledge` - поиск в базе знаний (RAG)
5. `sql_query` - SQL запрос (как инструмент)
6. `extract_preferences` - извлечение предпочтений
7. `generate_response` - генерация ответа
8. `update_memory` - обновление памяти

#### 2.2. Создание UnifiedSearchService

**Файл:** `backend/services/unified_search_service.py`

**Основные методы:**
- `intelligent_search(query, user_context, filters)` - умный поиск
- `_hybrid_car_search(query, filters, user_context)` - гибридный поиск
- `_exact_search(query, criteria)` - точный поиск (Elasticsearch)
- `_semantic_search(query, criteria, user_context)` - семантический поиск (pgvector)
- `_merge_search_results(es_results, vector_results, user_context)` - объединение результатов

**Логика:**
1. Анализ запроса - определяет тип поиска
2. Параллельный поиск - Elasticsearch + pgvector
3. Объединение и переранжирование
4. Fallback - если результатов мало, расширяет критерии

#### 2.3. Интеграция SQL Agent как инструмента

**Файл:** `backend/services/car_dealer_agent.py` (узел `sql_query`)

**Логика:**
- Агент анализирует запрос
- Определяет, нужен ли SQL (структурированный запрос к БД)
- Вызывает SQL Agent как инструмент
- Получает результат и передает в `generate_response`

**Пример:**
```python
async def sql_query_node(self, state: AgentState) -> AgentState:
    """Узел для выполнения SQL запросов"""
    if state["current_intent"] != "structured_query":
        return state
    
    sql_agent = SQLAgentService()
    result = await sql_agent.process_question(
        state["user_input"],
        user_id=state["user_id"]
    )
    
    state["search_results"] = result.get("data", [])
    state["used_tools"].append("sql_agent")
    
    return state
```

---

### Этап 3: Миграция данных (1 неделя)

#### 3.1. Миграция памяти из Qdrant в PostgreSQL

**Файл:** `backend/scripts/migrate_memories_from_qdrant.py`

```python
async def migrate_memories():
    """Переносит память из Qdrant в PostgreSQL"""
    from qdrant_client import QdrantClient
    from services.unified_memory_service import UnifiedMemoryService
    
    qdrant = QdrantClient(url=os.getenv("QDRANT_URL"))
    memory_service = UnifiedMemoryService(db_session, embedding_service)
    
    # Получаем все коллекции пользователей
    collections = qdrant.get_collections().collections
    
    for collection in collections:
        if collection.name.startswith("user_"):
            user_id = collection.name.replace("user_", "").replace("_memories", "")
            
            # Получаем все точки из коллекции
            points = qdrant.scroll(
                collection_name=collection.name,
                limit=1000
            )[0]
            
            for point in points:
                await memory_service.save_memory(
                    user_id=user_id,
                    memory_data={
                        "memory_text": point.payload.get("memory", ""),
                        "metadata": point.payload.get("metadata", {}),
                        "embedding": point.vector,  # Используем существующий вектор
                        "memory_type": point.payload.get("memory_type", "preference")
                    }
                )
    
    print(f"✅ Миграция завершена")
```

#### 3.2. Обновление существующих записей ChatMessage

**SQL скрипт:**
```sql
-- Создаем чаты для сообщений без chat_id
INSERT INTO chats (user_id, title, created_at)
SELECT DISTINCT user_id, 'Миграция', NOW()
FROM chat_messages
WHERE chat_id IS NULL
ON CONFLICT DO NOTHING;

-- Обновляем chat_id
UPDATE chat_messages cm
SET chat_id = (
    SELECT id FROM chats c 
    WHERE c.user_id = cm.user_id 
    ORDER BY c.created_at DESC 
    LIMIT 1
)
WHERE cm.chat_id IS NULL;

-- Убираем nullable
ALTER TABLE chat_messages ALTER COLUMN chat_id SET NOT NULL;
```

---

### Этап 4: Рефакторинг API (1 неделя)

#### 4.1. Упрощение endpoint `/api/chat/message`

**Файл:** `backend/app/api/chat.py`

**Было:**
```python
@router.post("/message")
async def send_message(request: ChatMessageRequest, db: Session = Depends(get_db)):
    # Сложная логика выбора сервиса
    if use_langgraph and langgraph_service:
        result = await langgraph_service.generate_with_graph(...)
    elif use_sql_agent:
        result = await sql_agent.process_question(...)
    else:
        result = await rag_service.generate_response(...)
```

**Стало:**
```python
@router.post("/message")
async def send_message(request: ChatMessageRequest, db: Session = Depends(get_db)):
    """Отправка сообщения через единый агент"""
    from services.car_dealer_agent import CarDealerAgent
    
    agent = CarDealerAgent(db_session=db)
    
    result = await agent.process_message(
        user_input=request.message,
        user_id=request.user_id,
        session_id=request.session_id or _current_session_id(request.user_id),
        chat_id=request.chat_id
    )
    
    # Сохранение в БД
    chat_message = db_service.save_chat_message(
        user_id=request.user_id,
        message=request.message,
        response=result["response"],
        related_article_ids=result.get("related_articles", []),
        chat_id=result["chat_id"],
        sources_data=result.get("sources_data")
    )
    
    return ChatMessageResponse(
        response=result["response"],
        related_articles=result.get("related_articles", []),
        related_documents=result.get("related_documents", []),
        related_cars=result.get("related_cars", []),
        related_used_cars=result.get("related_used_cars", []),
        message_id=chat_message.id,
        chat_id=result["chat_id"]
    )
```

#### 4.2. Удаление избыточных endpoints

**Удалить:**
- `/api/ai/sql-agent/query` - теперь инструмент агента
- `/api/ai/car-dealer/query` - заменен единым агентом
- `/api/ai/intelligent-search` - заменен UnifiedSearchService

**Оставить:**
- `/api/chat/message` - основной endpoint
- `/api/ai/sql-agent/status` - для мониторинга
- `/api/ai/sql-agent/toggle` - для управления

---

### Этап 5: Улучшение диалоговых возможностей (2 недели)

#### 5.1. Извлечение параметров через LLM

**Файл:** `backend/services/parameter_extraction_service.py`

**Структура:**
```python
class CarSearchCriteria(BaseModel):
    brands: Optional[List[str]] = None
    models: Optional[List[str]] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    body_types: Optional[List[str]] = None
    fuel_types: Optional[List[str]] = None
    gearbox_types: Optional[List[str]] = None
    drive_types: Optional[List[str]] = None
    min_power: Optional[int] = None
    max_power: Optional[int] = None
    cities: Optional[List[str]] = None
    must_have_features: Optional[List[str]] = None
    exclude_features: Optional[List[str]] = None
    urgency: Optional[str] = None
    budget_flexibility: Optional[str] = None
```

**Методы:**
- `extract_parameters(query, context)` - извлечение через LLM
- `_enrich_with_context(query, context)` - обогащение контекстом
- `_merge_criteria(existing, new)` - объединение критериев

#### 5.2. Проактивные предложения

**Файл:** `backend/services/proactive_suggestions_service.py`

**Логика:**
- Анализ контекста пользователя
- Анализ результатов поиска
- Генерация релевантных предложений

**Примеры предложений:**
- "Хотите записаться на тест-драйв?"
- "Посмотреть аналоги подешевле?"
- "Рассчитать ежемесячный платеж?"
- "Показать варианты в кредит?"

#### 5.3. Извлечение сущностей после диалога

**Файл:** `backend/services/entity_extraction_service.py`

**Методы:**
- `extract_entities_from_dialog(messages)` - извлечение через LLM
- `save_extracted_entities(user_id, entities)` - сохранение в память

**Извлекаемые сущности:**
- Бренды и модели
- Бюджет (мин/макс)
- Предпочтения (тип кузова, привод, и т.д.)
- Отклоненные варианты
- Интересы

---

## 🔧 Детальная реализация

### 1. UnifiedMemoryService

**Полная реализация:**

```python
class UnifiedMemoryService:
    def __init__(self, db_session, embedding_service):
        self.db = db_session
        self.embeddings = embedding_service
    
    async def get_user_context(self, user_id: str, current_query: str) -> dict:
        """Получает ВСЕ релевантные данные пользователя"""
        
        # 1. История диалога (последние 10 сообщений)
        history = await self._get_recent_history(user_id)
        
        # 2. Долговременные предпочтения из pgvector
        preferences = await self._get_user_preferences(user_id, current_query)
        
        # 3. Извлеченные сущности из текущего диалога
        entities = await self._extract_entities(history + [current_query])
        
        return {
            "history": history,
            "preferences": preferences,
            "entities": entities,
            "inferred_criteria": self._infer_search_criteria(preferences, entities)
        }
    
    async def _get_user_preferences(self, user_id: str, query: str) -> List[dict]:
        """Семантический поиск предпочтений в pgvector"""
        query_embedding = await self.embeddings.embed_query(query)
        
        results = await self.db.execute(
            """
            SELECT memory_text, metadata, 
                   1 - (embedding <=> :embedding) as similarity
            FROM user_memories 
            WHERE user_id = :user_id 
            AND embedding <=> :embedding < 0.3
            ORDER BY embedding <=> :embedding
            LIMIT 5
            """,
            {"user_id": user_id, "embedding": query_embedding}
        )
        return [dict(row) for row in results]
    
    async def save_memory(self, user_id: str, memory_data: dict):
        """Сохраняет ключевые факты о пользователе"""
        memory_text = self._format_memory(memory_data)
        embedding = await self.embeddings.embed_query(memory_text)
        
        await self.db.execute(
            """
            INSERT INTO user_memories (user_id, memory_type, memory_text, embedding, metadata)
            VALUES (:user_id, :memory_type, :memory_text, :embedding, :metadata)
            """,
            {
                "user_id": user_id,
                "memory_type": memory_data.get("memory_type", "preference"),
                "memory_text": memory_text,
                "embedding": embedding,
                "metadata": json.dumps(memory_data.get("metadata", {}))
            }
        )
```

### 2. UnifiedSearchService

**Полная реализация:**

```python
class UnifiedSearchService:
    def __init__(self, elasticsearch_service, vector_search_service):
        self.es = elasticsearch_service
        self.vector = vector_search_service
    
    async def intelligent_search(self, query: str, user_context: dict, filters: dict = None) -> dict:
        """Умный поиск, который сам решает, какие источники использовать"""
        
        # Анализ запроса
        intent_analysis = await self._analyze_query_intent(query, user_context)
        
        results = {}
        
        # Параллельный поиск
        if intent_analysis["needs_car_search"]:
            results["cars"] = await self._hybrid_car_search(query, filters, user_context)
        
        if intent_analysis["needs_knowledge"]:
            results["knowledge"] = await self._knowledge_search(query, user_context)
        
        return self._rank_and_merge_results(results, intent_analysis)
    
    async def _hybrid_car_search(self, query: str, filters: dict, user_context: dict) -> List[dict]:
        """Гибридный поиск автомобилей"""
        
        # Параллельный поиск
        es_future = self._exact_search(query, filters)
        vector_future = self._semantic_search(query, filters, user_context)
        
        es_results, vector_results = await asyncio.gather(es_future, vector_future)
        
        # Объединение и переранжирование
        return await self._merge_search_results(es_results, vector_results, user_context)
    
    async def _exact_search(self, query: str, criteria: dict) -> List[dict]:
        """Поиск по точным совпадениям в Elasticsearch"""
        return await self.es.search_cars(
            query=query,
            mark=criteria.get("brands", [None])[0] if criteria.get("brands") else None,
            min_price=criteria.get("min_price"),
            max_price=criteria.get("max_price"),
            min_year=criteria.get("min_year"),
            max_year=criteria.get("max_year"),
            limit=20
        )
    
    async def _semantic_search(self, query: str, criteria: dict, user_context: dict) -> List[dict]:
        """Семантический поиск с учетом контекста"""
        semantic_query = self._prepare_semantic_query(query, user_context)
        
        vector_results = await self.vector.similarity_search(
            semantic_query,
            filters=criteria,
            limit=20
        )
        
        return vector_results
```

### 3. CarDealerAgent

**Полная реализация графа:**

```python
class CarDealerAgent:
    def __init__(self, db_session, memory_service, search_service, llm_service):
        self.db = db_session
        self.memory = memory_service
        self.search = search_service
        self.llm = llm_service
        self.graph = self._build_graph()
    
    def _build_graph(self):
        workflow = StateGraph(AgentState)
        
        # Узлы
        workflow.add_node("analyze_intent", self.analyze_intent)
        workflow.add_node("extract_parameters", self.extract_parameters)
        workflow.add_node("search_cars", self.search_cars)
        workflow.add_node("search_knowledge", self.search_knowledge)
        workflow.add_node("sql_query", self.sql_query)
        workflow.add_node("extract_preferences", self.extract_preferences)
        workflow.add_node("generate_response", self.generate_response)
        workflow.add_node("update_memory", self.update_memory)
        
        # Маршрутизация
        workflow.set_entry_point("analyze_intent")
        
        workflow.add_conditional_edges(
            "analyze_intent",
            self.route_by_intent,
            {
                "car_search": "extract_parameters",
                "knowledge_query": "search_knowledge",
                "structured_query": "sql_query",
                "clarification": "generate_response"
            }
        )
        
        workflow.add_edge("extract_parameters", "search_cars")
        workflow.add_edge("search_cars", "extract_preferences")
        workflow.add_edge("search_knowledge", "extract_preferences")
        workflow.add_edge("sql_query", "extract_preferences")
        workflow.add_edge("extract_preferences", "generate_response")
        workflow.add_edge("generate_response", "update_memory")
        workflow.add_edge("update_memory", END)
        
        return workflow.compile()
    
    async def process_message(self, user_input: str, user_id: str, session_id: str, chat_id: int = None) -> dict:
        """Обрабатывает сообщение пользователя"""
        
        # Получаем контекст пользователя
        user_context = await self.memory.get_user_context(user_id, user_input)
        
        # Инициализируем состояние
        initial_state: AgentState = {
            "user_input": user_input,
            "user_id": user_id,
            "session_id": session_id,
            "chat_history": user_context["history"],
            "dialogue_context": user_context,
            "user_preferences": user_context["preferences"],
            "search_criteria": user_context["inferred_criteria"],
            "search_results": [],
            "knowledge_results": [],
            "current_intent": "",
            "needs_clarification": False,
            "clarification_questions": [],
            "response": "",
            "suggested_actions": [],
            "memory_updates": [],
            "used_tools": []
        }
        
        # Запускаем граф
        final_state = await self.graph.ainvoke(initial_state)
        
        return {
            "response": final_state["response"],
            "related_cars": final_state.get("search_results", []),
            "related_articles": final_state.get("knowledge_results", []),
            "suggested_actions": final_state.get("suggested_actions", []),
            "chat_id": chat_id
        }
```

---

## 📊 Ожидаемые результаты

| Метрика | Сейчас | После рефакторинга |
|---------|--------|-------------------|
| Время ответа | 2-5 сек | 1-3 сек |
| Согласованность ответов | Низкая | Высокая |
| Качество диалога | Шаблонное | Персонализированное |
| Сложность поддержки | Высокая | Средняя |
| Количество хранилищ | 4 | 2.5 (Elasticsearch - читающая реплика) |
| Количество сервисов | 10+ | 3-4 (агент + инструменты) |

---

## 🚀 Приоритеты реализации

### Высокий приоритет (1-2 недели)

1. ✅ Создание таблицы `user_memories`
2. ✅ Исправление модели `ChatMessage` (chat_id NOT NULL)
3. ✅ Создание `UnifiedMemoryService`
4. ✅ Создание `UnifiedSearchService`
5. ✅ Создание базового `CarDealerAgent`

### Средний приоритет (2-3 недели)

6. ✅ Миграция памяти из Qdrant
7. ✅ Интеграция SQL Agent как инструмента
8. ✅ Рефакторинг API endpoint
9. ✅ Извлечение параметров через LLM

### Низкий приоритет (1-2 недели)

10. ✅ Проактивные предложения
11. ✅ Извлечение сущностей после диалога
12. ✅ Удаление избыточных компонентов (Mem0, Qdrant)

---

## ⚠️ Риски и митигация

### Риск 1: Потеря данных при миграции

**Митигация:**
- Полное резервное копирование перед миграцией
- Поэтапная миграция с проверкой
- Возможность отката

### Риск 2: Снижение производительности

**Митигация:**
- Постепенное внедрение (feature flags)
- Мониторинг производительности
- Оптимизация запросов

### Риск 3: Регрессии в функциональности

**Митигация:**
- Тестирование на каждом этапе
- Сохранение fallback механизмов
- Постепенный переход пользователей

---

## 📝 Чеклист реализации

### Этап 1: Подготовка
- [ ] Создать миграцию для `user_memories`
- [ ] Исправить модель `ChatMessage`
- [ ] Создать `UnifiedMemoryService`
- [ ] Написать тесты для `UnifiedMemoryService`

### Этап 2: Единый агент
- [ ] Создать `CarDealerAgent` с базовым графом
- [ ] Создать `UnifiedSearchService`
- [ ] Интегрировать SQL Agent как инструмент
- [ ] Написать тесты для агента

### Этап 3: Миграция
- [ ] Скрипт миграции памяти из Qdrant
- [ ] Обновление существующих ChatMessage
- [ ] Проверка целостности данных

### Этап 4: API
- [ ] Рефакторинг `/api/chat/message`
- [ ] Удаление избыточных endpoints
- [ ] Обновление документации

### Этап 5: Улучшения
- [ ] Извлечение параметров через LLM
- [ ] Проактивные предложения
- [ ] Извлечение сущностей
- [ ] Удаление Mem0 и Qdrant

---

## 🎯 Итоговый стек

1. **Ядро:** LangGraph + CarDealerAgent
2. **Хранилища:** PostgreSQL + pgvector (все данные), Elasticsearch (поиск), Redis (сессии)
3. **Поиск:** UnifiedSearchService с гибридным поиском
4. **Память:** UnifiedMemoryService с семантическим поиском предпочтений
5. **Диалог:** Proactive agent с извлечением сущностей и контекстными предложениями

---

**Статус:** 📋 План готов к реализации  
**Следующий шаг:** Начать с Этапа 1 - Подготовка инфраструктуры

