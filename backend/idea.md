Отличный анализ! Вы предоставили очень подробный и структурированный документ. Давайте проведем критический разбор архитектуры, выявим проблемы, избыточность и наметим путь к созданию качественной, целостной системы.

### Общая Оценка

**Сильные стороны:**
*   **Полнота функционала:** Система пытается охватить все возможные аспекты: от простого поиска до сложного диалога с памятью.
*   **Использование современных технологий:** RAG, LangGraph, векторные БД — это верный выбор для подобных задач.
*   **Модульность:** Архитектура разделена на сервисы, что теоретически упрощает разработку и поддержку.

**Критические проблемы и избыточность:**

1.  **Архитектурная переусложненность ("Frankenstein Architecture"):** Система не имеет единого "мозга". Запрос пользователя может пойти по десятку разных, слабо связанных между собой путей (RAGService, SQLAgentService, LangGraphRAGService, IntelligentSearchService, CarDealerAssistantService). Это приводит к:
    *   **Противоречивым ответам.**
    *   **Сложности в поддержке и дебаге.**
    *   **Дублированию кода.**

2.  **Избыточность и конфликт хранилищ:**
    *   **Векторный поиск:** Зачем и `pgvector`, и `Qdrant`? Они решают одну и ту же задачу. `pgvector` проще (все в одной БД), `Qdrant` — возможно, производительнее для pure vector search. Наличие двух — источник проблем.
    *   **Поиск автомобилей:** Зачем и `Elasticsearch` (полнотекстовый), и `pgvector` (семантический), и прямое обращение к PostgreSQL? Это три разных способа найти один и тот же автомобиль. Нет четкой стратегии, когда что использовать.
    *   **Память:** Сложная схема с `Redis` (краткосрочная), `Mem0` (абстракция) и `Qdrant` (хранилище для Mem0). `Mem0` — это "черный ящик", усложняющий контроль над данными.

3.  **"Размазанная" логика диалога:** Состояние диалога хранится в `DialogStateService`, история — в `DialogueHistoryService`, долговременная память — в `Mem0Service`, а управление потоком — то в `LangGraphRAGService`, то в `RAGService`. Нет единого координатора.

4.  **Ошибка в модели данных `ChatMessage`:** Поле `chat_id` указано как `nullable`. Это архитектурная ошибка. Сообщение не может существовать без чата. Это нарушает целостность данных.

5.  **Слабая интеграция SQL-агента:** Он существует как отдельный "островок". Пользователь должен сам решить, использовать ли ему обычный чат или SQL-агента. В качественной системе агент должен быть *невидимой* частью ядра, которое само решает, нужен ли ему SQL для ответа на вопрос "Сколько у вас машин синего цвета?".

---

### Рекомендации по качественной реализации

Цель — создать **единую, целостную диалоговую систему** с памятью, где все компоненты работают согласованно для достижения одной цели: понять пользователя и найти ему лучший автомобиль.

#### 1. Упрощение и унификация архитектуры ("Единое ядро")

**Правильная архитектура должна быть построена вокруг `LangGraph` или аналогичного фреймворка для управления состоянием (Stateful Agent).**

**Устаревший (текущий) подход:**
`Запрос -> [Маршрутизатор] -> [Один из 5 сервисов] -> Ответ`

**Правильный подход:**
`Запрос -> [Единый Агент (LangGraph)] -> [Координирует работу всех инструментов] -> Ответ`

**Структура единого агента:**

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AgentState(TypedDict):
    user_input: str
    chat_history: list
    user_profile: dict
    current_dialogue_context: dict  # (интересы, бюджет, критерии)
    retrieved_cars: list
    retrieved_documents: list
    retrieved_memories: list
    response: str
    used_tools: list

def route_query(state: AgentState):
    """Определяет тип запроса и решает, какие инструменты использовать."""
    # Анализирует user_input и chat_history
    # Возвращает Next("search_cars") или Next("answer_general_question") и т.д.

def search_cars_tool(state: AgentState):
    """Использует УНИФИЦИРОВАННЫЙ поисковый движок."""
    # Внутри использует и Elasticsearch, и векторный поиск, но для пользователя это один инструмент
    state["retrieved_cars"] = unified_search_service.search(state)

def answer_general_question_tool(state: AgentState):
    """Использует RAG для ответа на общие вопросы."""
    state["retrieved_documents"] = rag_service.search(state)

def generate_response(state: AgentState):
    """Формирует финальный ответ, учитывая ВСЕ контексты."""
    context = {
        "cars": state["retrieved_cars"],
        "docs": state["retrieved_documents"],
        "memories": state["retrieved_memories"],
        "history": state["chat_history"],
        "user_context": state["current_dialogue_context"]
    }
    state["response"] = llm.invoke(construct_prompt(state["user_input"], context))

# Сборка графа
workflow = StateGraph(AgentState)
workflow.add_node("route", route_query)
workflow.add_node("search_cars", search_cars_tool)
workflow.add_node("answer_question", answer_general_question_tool)
workflow.add_node("generate", generate_response)

workflow.set_entry_point("route")
workflow.add_conditional_edges("route", ...) # Решает, куда идти дальше
workflow.add_edge("search_cars", "generate")
workflow.add_edge("answer_question", "generate")
workflow.add_edge("generate", END)
```

**Преимущества:**
*   **Единая точка принятия решений.** Агент сам решает, какие инструменты ему нужны.
*   **Согласованные ответы.** Ответ всегда генерируется с учетом всей собранной информации.
*   **Гибкость.** Легко добавлять новые инструменты (например, `calculate_payments_tool`).

#### 2. Унификация хранилищ данных

*   **Выберите ОДНО векторное хранилище.** **Рекомендация: `pgvector`**. Преимущества:
    *   **Простота:** Все данные (структурированные и векторные) в одном месте.
    *   **Согласованность:** Транзакции. Обновили автомобиль — его эмбеддинг обновился в той же транзакции.
    *   **Меньше операционных затрат:** Одна система вместо двух.
    *   **Откажитесь от Qdrant**, если нет конкретных требований к производительности, которые он не покрывает.

*   **Создайте Унифицированный сервис поиска.**
    *   Этот сервис внутри себя решает, как искать: для точных запросов ("синий Ford Focus") — `Elasticsearch`, для семантических ("надежный семейный автомобиль") — `pgvector`, а чаще — **гибридный поиск** (объединение и ранжирование результатов из обоих источников).
    *   **Уберите прямой поиск из `RAGService` и `SQLAgentService`.** Весь поиск должен идти через этот единый сервис.

*   **Упростите систему памяти.**
    *   **Используйте `pgvector` для долговременной памяти.** Сохраняйте туда эмбеддинги ключевых фактов о пользователе (бюджет, предпочтения, упомянутые ранее модели).
    *   **Используйте `Redis` ТОЛЬКО для временного кэша и состояния текущей сессии.**
    *   **Рассмотрите отказ от `Mem0`.** Это лишний абстрактный слой. Реализуйте логику извлечения и сохранения памяти напрямую, это даст вам полный контроль. Например, после каждого диалога сохраняйте в `pgvector` сущности типа `UserPreference(budget=..., preferred_brands=[...])`.

#### 3. Интеграция SQL-агента как инструмента

SQL-агент не должен быть отдельным endpoint. Он должен быть одним из "инструментов" (`tools`) вашего единого агента.

*   Агент анализирует запрос: "Покажи все автомобили до 1.5 млн".
*   Понимает, что это структурированный запрос к БД.
*   Вызывает `sql_agent_tool`, который генерирует и выполняет SQL.
*   Получает результат и передает его в `generate_response` для формирования человеческого ответа.

Пользователь об этом даже не догадывается.

#### 4. Качественная работа с диалогом и памятью

*   **Единый контекст диалога:** Храните в состоянии агента (`AgentState`) всю актуальную информацию: последние просмотренные машины, уточненные критерии (бюджет, тип кузова), интересы пользователя.
*   **Проактивность:** На основе контекста агент должен задавать уточняющие вопросы: "Вы смотрели Ford Focus, он вам подошел по цене? Или показать что-то подешевле?".
*   **Извлечение сущностей:** После каждого диалога запускайте легковесную LLM для извлечения ключевых фактов (бюджет, предпочтения, отвергнутые варианты) и сохраняйте их в векторную БД (`pgvector`). При новом диалоге эти факты будут подтягиваться в контекст.

---

### Итоговый Технологический Стек и Направление

1.  **Ядро:** **LangGraph**. Это не опция, а необходимость для построения сложного диалогового агента с памятью. Управление состоянием — ключ к качественному диалогу.

2.  **Хранилища:**
    *   **PostgreSQL + pgvector:** Единое хранилище для всего: структурированных данных, векторов (машин, документов, памяти пользователя).
    *   **Elasticsearch:** Только для полнотекстового поиска по автомобилям, интегрированный в единый поисковый сервис.
    *   **Redis:** Только для кэша и состояния активной сессии.

3.  **Архитектура:**
    *   **Единый Stateful Agent** на LangGraph.
    *   **Набор инструментов (Tools)**, которые агент использует: Унифицированный поиск, RAG по базе знаний, SQL-запросы, калькулятор платежей.
    *   **Упрощенная, но мощная система памяти** на основе `pgvector`, интегрированная в граф.

4.  **Отказ от:**
    *   Избыточных хранилищ (Qdrant, ChromaDB).
    *   "Волшебных" абстракций (Mem0), если они не дают явного преимущества.
    *   Разрозненных сервисов-обработчиков (`RAGService`, `SQLAgentService` и т.д.) в их текущем виде. Их логика должна стать "инструментами" агента.

**Заключение:**

Текущая архитектура — это набор мощных, но разрозненных компонентов. Вам нужно не добавлять новые, а **интегрировать существующие в единую, умную систему**. Фокус должен сместиться с "сколько всего мы можем сделать" на "как сделать так, чтобы все компоненты работали согласованно для создания иллюзии разговора с компетентным продавцом-консультантом, который помнит вас и ваши предпочтения".

Начните с проектирования `LangGraph` графа — это заставит вас продумать поток диалога и взаимодействие компонентов, а уже под эту архитектуру адаптируйте существующие сервисы.


Отлично! С добавленными данными по структуре хранения картина стала еще более ясной. Проведу углубленный анализ и предложу конкретный план рефакторинга.

## 🚨 Критические проблемы архитектуры

### 1. **Архитектурная шизофрения хранилищ**

**Проблема:** Данные об автомобилях хранятся в 4 местах одновременно:
- PostgreSQL (основные данные)
- Elasticsearch (поисковый индекс) 
- pgvector (векторные представления)
- Qdrant (векторы для Mem0)

**Пример противоречия:**
```sql
-- В PostgreSQL
UPDATE cars SET price = 3000000 WHERE id = 12345;

-- В Elasticsearch (может быть рассинхронизация)
{
  "_id": "12345", 
  "price": 3500000  # Старая цена!
}

-- В pgvector (эмбеддинг сгенерирован от старого описания)
"document": "Audi A4 2.0 TDI, 2024, Краснодар, 3500000 руб"
```

### 2. **Некорректная модель данных**

```sql
-- ОШИБКА: сообщение без чата
CREATE TABLE chat_messages (
    chat_id INTEGER REFERENCES chats(id) ON DELETE CASCADE,  -- NULLABLE!
);
```
Это архитектурная ошибка. Сообщение должно всегда принадлежать чату.

### 3. **Избыточность поисковых путей**

Один запрос "Audi до 3 млн" может пройти через:
- `RAGService` → поиск в PostgreSQL + Elasticsearch + pgvector
- `SQLAgentService` → генерация SQL → PostgreSQL  
- `IntelligentSearchService` → анализ → Elasticsearch + pgvector
- `LangGraphRAGService` → свой поиск

**Результат:** 4 разных ответа, конкурирующие ресурсы, несогласованные результаты.

### 4. **Сложность системы памяти**

```
Диалог → Redis → Mem0 → Qdrant → Mem0 → Диалог
```
Слишком много слоев абстракции для простой задачи "запомнить предпочтения пользователя".

## 🎯 Рекомендуемая архитектура

### Ядро: Stateful Agent на LangGraph

```python
from typing import TypedDict, List, Optional, Annotated
from langgraph.graph import StateGraph, END
import operator

class AgentState(TypedDict):
    # Входные данные
    user_input: str
    user_id: str
    session_id: str
    
    # Контекст диалога
    chat_history: List[dict]
    dialogue_context: Annotated[dict, operator.add]  # Автоматически мержится
    
    # Поисковые результаты
    search_results: Annotated[list, operator.add]
    knowledge_results: Annotated[list, operator.add]
    
    # Состояние
    current_intent: str
    needs_clarification: bool
    clarification_questions: List[str]
    
    # Выходные данные
    response: str
    suggested_actions: List[str]
    memory_updates: List[dict]

class CarDealerAgent:
    def __init__(self):
        self.graph = StateGraph(AgentState)
        self._build_graph()
    
    def _build_graph(self):
        # Узлы графа
        self.graph.add_node("analyze_intent", self.analyze_intent)
        self.graph.add_node("search_cars", self.search_cars)
        self.graph.add_node("search_knowledge", self.search_knowledge)
        self.graph.add_node("extract_preferences", self.extract_preferences)
        self.graph.add_node("generate_response", self.generate_response)
        self.graph.add_node("update_memory", self.update_memory)
        
        # Маршрутизация
        self.graph.set_entry_point("analyze_intent")
        
        self.graph.add_conditional_edges(
            "analyze_intent",
            self.route_by_intent,
            {
                "car_search": "search_cars",
                "knowledge_query": "search_knowledge", 
                "clarification": "generate_response",
                "general": "generate_response"
            }
        )
        
        self.graph.add_edge("search_cars", "extract_preferences")
        self.graph.add_edge("search_knowledge", "extract_preferences")
        self.graph.add_edge("extract_preferences", "generate_response")
        self.graph.add_edge("generate_response", "update_memory")
        self.graph.add_edge("update_memory", END)
```

### Упрощенная, но мощная система памяти

```python
class UnifiedMemoryService:
    def __init__(self, db_session, embedding_service):
        self.db = db_session
        self.embeddings = embedding_service
    
    async def get_user_context(self, user_id: str, current_query: str) -> dict:
        """Получает ВСЕ релевантные данные пользователя за один запрос"""
        
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
            SELECT memory_text, metadata, similarity
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
            INSERT INTO user_memories (user_id, memory_text, embedding, metadata)
            VALUES (:user_id, :memory_text, :embedding, :metadata)
            """,
            {
                "user_id": user_id, 
                "memory_text": memory_text,
                "embedding": embedding,
                "metadata": memory_data.get("metadata", {})
            }
        )
```

### Унифицированный поисковый движок

```python
class UnifiedSearchService:
    async def intelligent_search(self, query: str, user_context: dict, filters: dict = None) -> dict:
        """Умный поиск, который сам решает, какие источники использовать"""
        
        # Анализ запроса
        intent_analysis = await self._analyze_query_intent(query, user_context)
        
        results = {}
        
        # Параллельный поиск по всем источникам
        if intent_analysis["needs_car_search"]:
            results["cars"] = await self._hybrid_car_search(query, filters, user_context)
        
        if intent_analysis["needs_knowledge"]:
            results["knowledge"] = await self._knowledge_search(query, user_context)
        
        if intent_analysis["needs_comparison"]:
            results["comparisons"] = await self._find_comparisons(results.get("cars", []))
        
        return self._rank_and_merge_results(results, intent_analysis)

    async def _hybrid_car_search(self, query: str, filters: dict, user_context: dict) -> List[dict]:
        """Гибридный поиск автомобилей"""
        
        # 1. Полнотекстовый поиск для точных совпадений
        es_results = await self.elasticsearch.search({
            "query": self._build_es_query(query, filters),
            "size": 20
        })
        
        # 2. Векторный поиск для семантических совпадений
        vector_results = await self.vector_search.similarity_search(
            query, 
            filters=filters,
            limit=20
        )
        
        # 3. Объединение и переранжирование
        return await self._merge_search_results(es_results, vector_results, user_context)
```

## 🗃️ Упрощенная структура хранения

### Единая таблица для памяти пользователя

```sql
CREATE TABLE user_memories (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    memory_type VARCHAR(50) NOT NULL,  -- 'preference', 'rejection', 'interest', 'criteria'
    memory_text TEXT NOT NULL,          -- Человекочитаемое описание
    embedding VECTOR(1024),            -- Векторное представление
    metadata JSONB DEFAULT '{}',       -- Структурированные данные
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Индекс для быстрого поиска по пользователю и семантике
CREATE INDEX idx_user_memories_semantic 
ON user_memories 
USING ivfflat (embedding vector_cosine_ops) 
WHERE user_id IS NOT NULL;

CREATE INDEX idx_user_memories_user_type 
ON user_memories (user_id, memory_type);
```

### Примеры данных в памяти:

```json
{
  "id": 1,
  "user_id": "user-123",
  "memory_type": "preference",
  "memory_text": "Пользователь предпочитает автомобили Audi с полным приводом бюджетом до 3 миллионов рублей",
  "embedding": [0.123, -0.456, ...],
  "metadata": {
    "brands": ["Audi"],
    "driving_gear_type": ["Полный"],
    "max_price": 3000000,
    "source_messages": [1001, 1002],
    "inferred_confidence": 0.9
  }
}
```

```json
{
  "id": 2, 
  "user_id": "user-123",
  "memory_type": "rejection",
  "memory_text": "Пользователь отказался от BMW X5 из-за высокого расхода топлива",
  "embedding": [0.456, -0.789, ...],
  "metadata": {
    "rejected_car_id": 67890,
    "rejection_reason": "high_fuel_consumption",
    "learned_criteria": {"max_fuel_consumption": 8.0}
  }
}
```

## 🔧 Конкретный план миграции

### Этап 1: Создание единого агента (1-2 недели)

1. **Реализовать `CarDealerAgent`** на LangGraph с базовой маршрутизацией
2. **Создать `UnifiedMemoryService`** с хранением в pgvector
3. **Написать `UnifiedSearchService`** с гибридным поиском

### Этап 2: Миграция данных (1 неделя)

1. **Перенести память из Qdrant в PostgreSQL**:
```python
async def migrate_memories():
    qdrant_memories = await qdrant_client.scroll(collection_name="user_memories")
    for memory in qdrant_memories:
        await unified_memory.save_memory(
            user_id=memory.payload["user_id"],
            memory_data={
                "memory_text": memory.payload["memory"],
                "metadata": memory.payload.get("metadata", {}),
                "embedding": memory.vector  # Используем существующий вектор
            }
        )
```

2. **Обновить модель `ChatMessage`** - убрать `nullable` с `chat_id`

### Этап 3: Рефакторинг API (1 неделя)

**Было:**
```python
@router.post("/chat/message")
async def send_message(request: ChatMessageRequest):
    # Сложная логика выбора сервиса
    if use_langgraph:
        result = await langgraph_service.generate_with_graph(request)
    elif use_sql_agent:
        result = await sql_agent.process_question(request)
    else:
        result = await rag_service.generate_response(request)
```

**Стало:**
```python
@router.post("/chat/message")
async def send_message(request: ChatMessageRequest):
    # Вся логика внутри агента
    result = await car_dealer_agent.process_message(
        user_input=request.message,
        user_id=request.user_id,
        session_id=request.session_id
    )
    return result
```

### Этап 4: Улучшение диалоговых возможностей (2 недели)

1. **Реализовать проактивные предложения**:
```python
class ProactiveSuggestions:
    async def generate_suggestions(self, user_context: dict, search_results: list) -> List[str]:
        suggestions = []
        
        # На основе истории и предпочтений
        if self._should_suggest_test_drive(user_context):
            suggestions.append("Хотите записаться на тест-драйв?")
        
        if self._has_comparable_alternatives(search_results, user_context):
            suggestions.append("Посмотреть аналоги подешевле?")
            
        if self._needs_financial_calculation(user_context):
            suggestions.append("Рассчитать ежемесячный платеж?")
        
        return suggestions
```

2. **Добавить извлечение сущностей** после каждого диалога:
```python
async def extract_entities_from_dialog(messages: List[dict]) -> dict:
    """Извлекает структурированные данные из диалога"""
    prompt = f"""
    Извлеки сущности из диалога:
    {json.dumps(messages, ensure_ascii=False)}
    
    Верни JSON: {{"brands": [], "budget": {{"min": null, "max": null}}, "preferences": []}}
    """
    
    return await llm.invoke_structured(prompt, schema=EntitiesSchema)
```

## 🎯 Ключевые улучшения

### 1. **Качественный диалог через единый контекст**

```python
# Агент всегда имеет полный контекст
state = await agent.process({
    "user_input": "А есть что-то похожее, но с меньшим расходом?",
    "user_id": "user-123",
    "session_id": "session-456",
    # Автоматически подтягивается из памяти:
    # - История предыдущего запроса про Audi
    # - Предпочтения по маркам и бюджету  
    # - Отказ от BMW из-за расхода
})
```

### 2. **Проактивность вместо шаблонов**

**Вместо:** "Чем еще могу помочь?"
**Лучше:** "Нашел BMW 3-series с расходом 6.2л/100км - показать? Или рассмотреть варианты в кредит?"

### 3. **Единый источник истины**

- **PostgreSQL + pgvector** - все данные и векторы
- **Elasticsearch** - только полнотекстовый поиск (читающая реплика)
- **Redis** - только сессия и кэш

### 4. **Умное управление состоянием**

```python
class DialogueStateManager:
    async def update_state(self, user_id: str, agent_state: AgentState):
        """Сохраняет только существенные изменения состояния"""
        if agent_state.get("current_intent") == "car_selection":
            await self.redis.setex(
                f"dialogue:criteria:{user_id}", 
                3600,  # 1 час
                json.dumps(agent_state["inferred_criteria"])
            )
```

## 📊 Ожидаемые результаты после рефакторинга

| Метрика | Сейчас | После рефакторинга |
|---------|--------|-------------------|
| Время ответа | 2-5 сек | 1-3 сек |
| Согласованность ответов | Низкая | Высокая |
| Качество диалога | Шаблонное | Персонализированное |
| Сложность поддержки | Высокая | Средняя |
| Количество хранилищ | 4 | 2.5 (Elasticsearch - читающая реплика) |

## 🚀 Итоговый стек для качественного решения

1. **Ядро:** LangGraph + Custom Stateful Agent
2. **Хранилища:** PostgreSQL + pgvector (все данные), Elasticsearch (поиск), Redis (сессии)
3. **Поиск:** UnifiedSearchService с гибридным поиском
4. **Память:** UnifiedMemoryService с семантическим поиском предпочтений
5. **Диалог:** Proactive agent с извлечением сущностей и контекстными предложениями

Такой подход даст действительно качественный диалог, где бот будет вести себя как опытный продавец-консультант, который помнит ваши предпочтения и проактивно предлагает релевантные варианты.




🤖 Извлечение параметров с помощью LLM + LangGraph
Архитектура узла извлечения параметров:
python
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

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
    urgency: Optional[str] = None  # "immediate", "soon", "exploring"
    budget_flexibility: Optional[str] = None  # "strict", "flexible", "premium"

class ParameterExtractionNode:
    def __init__(self, llm_service):
        self.llm = llm_service
        self.system_prompt = self._create_system_prompt()
    
    def _create_system_prompt(self) -> str:
        return """
        Ты - экспертный ассистент по подбору автомобилей. Извлекай параметры из запросов пользователей.
        
        Важные правила:
        1. Цены: "3 миллиона" = 3000000, "полтора миллиона" = 1500000
        2. Года: "машина 2020 года" → min_year=2020, max_year=2020
        3. Марки: нормализуй к английским названиям (Ауди → Audi)
        4. Неявные параметры: "семейный автомобиль" → body_types=["универсал", "внедорожник"]
        5. Относительные параметры: "подешевле" → уменьшай max_price на 20%
        
        Отвечай ТОЛЬКО в формате JSON.
        """
    
    async def extract_parameters(self, state: AgentState) -> AgentState:
        user_input = state["user_input"]
        context = state.get("dialogue_context", {})
        
        # Обогащаем запрос контекстом
        enriched_query = self._enrich_with_context(user_input, context)
        
        # Извлекаем параметры через LLM
        criteria = await self._call_llm_for_extraction(enriched_query)
        
        # Обновляем состояние
        state["search_criteria"] = self._merge_criteria(
            state.get("search_criteria", {}),
            criteria.model_dump()
        )
        
        return state
    
    def _enrich_with_context(self, query: str, context: dict) -> str:
        """Обогащает запрос контекстом диалога"""
        context_parts = []
        
        if context.get("previous_criteria"):
            context_parts.append(f"Ранее обсуждали: {context['previous_criteria']}")
        
        if context.get("rejected_cars"):
            context_parts.append(f"Отклоненные варианты: {context['rejected_cars']}")
        
        if context_parts:
            return f"{query} [Контекст: {'; '.join(context_parts)}]"
        
        return query
    
    async def _call_llm_for_extraction(self, query: str) -> CarSearchCriteria:
        prompt = f"""
        Запрос пользователя: {query}
        
        Извлеки параметры поиска. Учитывай:
        - Числа и их контекст (цена, год, мощность)
        - Неявные предпочтения ("надежный" → марки с хорошей репутацией)
        - Относительные выражения ("подешевле", "посвежее")
        - Исключения ("кроме BMW")
        
        JSON:
        """
        
        response = await self.llm.generate_structured(
            prompt=prompt,
            system_prompt=self.system_prompt,
            response_model=CarSearchCriteria
        )
        
        return response
    
    def _merge_criteria(self, existing: dict, new: dict) -> dict:
        """Объединяет старые и новые критерии поиска"""
        merged = existing.copy()
        
        for key, value in new.items():
            if value is not None:
                if isinstance(value, list) and key in merged and merged[key] is not None:
                    # Объединяем списки, убирая дубликаты
                    merged[key] = list(set(merged[key] + value))
                else:
                    merged[key] = value
        
        return merged
Интеграция в LangGraph граф:
python
class EnhancedCarDealerAgent:
    def _build_graph(self):
        # Существующие узлы
        self.graph.add_node("analyze_intent", self.analyze_intent)
        self.graph.add_node("extract_parameters", self.parameter_extractor.extract_parameters)
        self.graph.add_node("search_cars", self.search_cars)
        self.graph.add_node("generate_response", self.generate_response)
        
        # Условные переходы с учетом извлеченных параметров
        self.graph.add_conditional_edges(
            "analyze_intent",
            self.route_after_intent_analysis,
            {
                "needs_parameter_extraction": "extract_parameters",
                "has_sufficient_parameters": "search_cars",
                "needs_clarification": "generate_response"
            }
        )
        
        self.graph.add_edge("extract_parameters", "search_cars")
        self.graph.add_edge("search_cars", "generate_response")
    
    def route_after_intent_analysis(self, state: AgentState) -> str:
        """Решает, нужно ли извлекать параметры"""
        intent = state["current_intent"]
        
        if intent in ["car_search", "refine_search"]:
            # Проверяем, достаточно ли параметров для поиска
            criteria = state.get("search_criteria", {})
            
            if self._has_sufficient_search_parameters(criteria, state["user_input"]):
                return "has_sufficient_parameters"
            else:
                return "needs_parameter_extraction"
        
        elif intent == "clarification":
            return "needs_clarification"
        
        return "generate_response"
    
    def _has_sufficient_search_parameters(self, criteria: dict, user_input: str) -> bool:
        """Проверяет, достаточно ли параметров для осмысленного поиска"""
        # Хотя бы один четкий критерий
        clear_indicators = [
            criteria.get("brands"),
            criteria.get("min_price") or criteria.get("max_price"),
            criteria.get("min_year") or criteria.get("max_year"),
            "vin" in user_input.lower(),
            any(word in user_input for word in ["цена", "бюджет", "стоимость"])
        ]
        
        return any(clear_indicators)
🎯 Улучшенный гибридный поиск
python
class EnhancedHybridSearch:
    async def search(self, query: str, criteria: CarSearchCriteria, user_context: dict) -> dict:
        # 1. Быстрый поиск по точным совпадениям (Elasticsearch)
        exact_results = await self._exact_search(query, criteria)
        
        if len(exact_results) >= 5:  # Достаточно точных результатов
            return {
                "results": exact_results,
                "search_type": "exact",
                "confidence": 0.9
            }
        
        # 2. Гибридный поиск для большего охвата
        hybrid_results = await self._hybrid_search(query, criteria, user_context)
        
        # 3. Семантический поиск как fallback
        if len(hybrid_results) < 3:
            semantic_results = await self._semantic_search(query, criteria, user_context)
            hybrid_results.extend(semantic_results)
        
        return {
            "results": self._deduplicate_and_rank(hybrid_results),
            "search_type": "hybrid",
            "confidence": 0.7 if len(hybrid_results) >= 5 else 0.5
        }
    
    async def _exact_search(self, query: str, criteria: dict) -> List[dict]:
        """Поиск по точным совпадениям в Elasticsearch"""
        es_query = self._build_elasticsearch_query(query, criteria)
        return await self.elasticsearch.search(es_query)
    
    async def _hybrid_search(self, query: str, criteria: dict, user_context: dict) -> List[dict]:
        """Гибридный поиск: точный + семантический"""
        # Параллельный поиск
        exact_future = self._exact_search(query, criteria)
        semantic_future = self._semantic_search(query, criteria, user_context)
        
        exact_results, semantic_results = await asyncio.gather(exact_future, semantic_future)
        
        # Объединение с приоритетом точных результатов
        combined = exact_results + semantic_results
        return self._rerank_hybrid_results(combined, query, criteria)
    
    async def _semantic_search(self, query: str, criteria: dict, user_context: dict) -> List[dict]:
        """Семантический поиск с учетом контекста пользователя"""
        # Нормализация запроса для семантического поиска
        semantic_query = self._prepare_semantic_query(query, user_context)
        
        # Векторный поиск
        vector_results = await self.vector_search.similarity_search(
            semantic_query,
            filters=criteria,
            limit=20
        )
        
        return vector_results
    
    def _prepare_semantic_query(self, query: str, user_context: dict) -> str:
        """Подготавливает запрос для семантического поиска"""
        # Удаляем числовые параметры (они уже в фильтрах)
        cleaned_query = re.sub(r'\d+', '', query)
        
        # Добавляем контекст пользователя
        if user_context.get("preferred_features"):
            cleaned_query += " " + " ".join(user_context["preferred_features"])
        
        return cleaned_query.strip()
📊 Пример работы системы
Входной запрос: "Ищу Audi A4 до 3 миллионов, с полным приводом, не старше 2020 года"

Извлеченные параметры:

json
{
  "brands": ["Audi"],
  "models": ["A4"],
  "max_price": 3000000,
  "min_year": 2020,
  "drive_types": ["полный"],
  "urgency": "soon",
  "budget_flexibility": "strict"
}
Поисковые запросы:

Elasticsearch: mark:"Audi" AND model:"A4" AND price:[0 TO 3000000] AND manufacture_year:[2020 TO *]

Векторный поиск: эмбеддинг для "Audi A4 полный привод премиум"

Результат: Высокая релевантность + семантическое понимание "премиум" характеристик.

🚀 Рекомендации по реализации
1. Многоуровневый поиск:
python
search_strategy = [
    ("exact", 1.0),      # Точные совпадения VIN, марка-модель
    ("numeric", 0.9),    # Числовые фильтры (цена, год)
    ("hybrid", 0.7),     # Гибридный поиск
    ("semantic", 0.5)    # Семантический поиск
]
2. Кэширование эмбеддингов:
python
# Кэшируем эмбеддинги для частых запросов
@lru_cache(maxsize=1000)
def get_cached_embedding(text: str) -> List[float]:
    return model.encode(text)
3. Постепенное уточнение:
python
# При недостаточных результатах автоматически расширяем критерии
async def expand_search_criteria(self, criteria: dict, results_count: int) -> dict:
    if results_count < 3:
        expanded = criteria.copy()
        if criteria.get("max_price"):
            expanded["max_price"] = int(criteria["max_price"] * 1.2)  # +20%
        if criteria.get("min_year"):
            expanded["min_year"] = criteria["min_year"] - 2  # На 2 года старше
        return expanded
    return criteria
✅ Вывод
Такая архитектура будет хорошо работать потому что:

Числа обрабатываются структурно через извлечение параметров, а не векторно

Русские термины нормализуются к единому стандарту

Гибридный подход сочетает точность Elasticsearch и семантику векторного поиска

LangGraph управляет контекстом, позволяя уточнять параметры в диалоге

Поиск адаптируется под количество результатов

Это даст действительно качественный диалог, где бот будет понимать:

"машина за 2 ляма" = бюджет 2,000,000 руб

"после 2020 года" = min_year 2020

"полный привод" = drive_types ["4WD", "AWD"]

"кроме BMW" = exclude_brands ["BMW"]

И все это - без шаблонных ответов, с настоящим пониманием контекста!