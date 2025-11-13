from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime


# Базовые схемы
class ArticleBase(BaseModel):
    title: str
    text: str
    url: Optional[str] = None
    language: str = "ru"


class ArticleCreate(ArticleBase):
    category_ids: List[int] = []
    tag_names: List[str] = []


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    text: Optional[str] = None
    url: Optional[str] = None
    language: Optional[str] = None
    category_ids: Optional[List[int]] = None
    tag_names: Optional[List[str]] = None


class CategoryOut(BaseModel):
    id: int
    name: str
    
    class Config:
        from_attributes = True


class TagOut(BaseModel):
    id: int
    name: str
    
    class Config:
        from_attributes = True


class Article(ArticleBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    categories: List[CategoryOut] = []
    tags: List[TagOut] = []
    
    class Config:
        from_attributes = True


# Схемы для импорта статей
class ImportFieldMapping(BaseModel):
    json_field: str
    db_field: str
    required: bool = False


class ImportPreview(BaseModel):
    total_records: int
    sample_records: List[dict]
    available_fields: List[str]
    required_fields: List[str]
    field_mappings: List[ImportFieldMapping]


class ImportRequest(BaseModel):
    json_data: List[dict]
    field_mappings: List[ImportFieldMapping]
    default_language: str = "ru"


class ImportResult(BaseModel):
    success_count: int
    error_count: int
    errors: List[str]
    imported_ids: List[int]


class CategoryBase(BaseModel):
    name: str
    description: Optional[str] = None


class CategoryCreate(CategoryBase):
    pass


class Category(CategoryBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# Схемы для SQL-агента
class SQLAgentQuestionRequest(BaseModel):
    question: str
    generate_only: bool = False  # Если True, только генерирует SQL без выполнения
    clarification: Optional[Dict[str, Any]] = None  # Уточняющая информация от пользователя

class SQLAgentResponse(BaseModel):
    success: bool
    sql: Optional[str] = None
    data: Optional[List[Dict]] = None
    columns: Optional[List[str]] = None
    row_count: Optional[int] = None
    answer: Optional[str] = None
    needs_clarification: Optional[bool] = False  # Требуется ли уточнение
    clarification_questions: Optional[List[str]] = None  # Вопросы для уточнения
    query_analysis: Optional[Dict[str, Any]] = None  # Результат анализа запроса
    error: Optional[str] = None
    fallback_source: Optional[str] = None  # Источник данных: "elasticsearch" или None

class SQLAgentToggleRequest(BaseModel):
    enabled: bool

class TagBase(BaseModel):
    name: str


class TagCreate(TagBase):
    pass


class Tag(TagBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# Схемы для чата
class ChatBase(BaseModel):
    user_id: str
    title: Optional[str] = None


class ChatCreate(ChatBase):
    pass


class ChatUpdate(BaseModel):
    title: Optional[str] = None


class Chat(ChatBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    message_count: Optional[int] = 0  # Количество сообщений в чате
    
    class Config:
        from_attributes = True


class ChatListResponse(BaseModel):
    chats: List[Chat]
    total: int


class ChatMessageRequest(BaseModel):
    use_intelligent_search: Optional[bool] = False  # Использовать интеллектуальный поиск
    message: str
    user_id: str
    chat_id: Optional[int] = None  # ID чата, если None - создается новый чат
    sql_agent_response: Optional[str] = None  # Готовый ответ от SQL-агента для сохранения
    sources_data: Optional[Dict[str, Any]] = None  # Данные источников: {cars: [], articles: [], documents: []}
    deep_thinking_enabled: Optional[bool] = False  # Включено ли размышление для этого запроса


class ChatMessageResponse(BaseModel):
    response: str
    related_articles: List[Article] = []
    related_documents: List['Document'] = []
    related_cars: List['Car'] = []
    related_used_cars: List['UsedCar'] = []
    model_info: Dict[str, str] = {}
    message_id: int
    chat_id: Optional[int] = None  # ID чата, в который сохранено сообщение


class FeedbackRequest(BaseModel):
    message_id: int
    feedback: int  # 1 - полезно, -1 - неполезно
    comment: Optional[str] = None


# Схемы для админки
class ArticleListResponse(BaseModel):
    articles: List[Article]
    total: int
    page: int
    size: int


class ArticleImportRequest(BaseModel):
    mode: str  # "add", "update", "replace"
    data: List[ArticleCreate]


# Схемы для документов
class DocumentBase(BaseModel):
    original_filename: str
    file_type: str
    language: str = "ru"
    path: Optional[str] = None


class DocumentCreate(DocumentBase):
    category_ids: List[int] = []
    tag_names: List[str] = []


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    topic: Optional[str] = None
    summary: Optional[str] = None
    path: Optional[str] = None
    category_ids: Optional[List[int]] = None
    tag_names: Optional[List[str]] = None


class Document(DocumentBase):
    id: int
    filename: str
    file_size: int
    title: Optional[str] = None
    extracted_text: Optional[str] = None
    topic: Optional[str] = None
    summary: Optional[str] = None
    processing_status: str
    error_message: Optional[str] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    categories: List[CategoryOut] = []
    tags: List[TagOut] = []
    
    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[Document]
    total: int
    page: int
    size: int


class DocumentUploadResponse(BaseModel):
    document_id: int
    message: str
    processing_status: str


# Обновляем forward references
Article.model_rebuild()
Category.model_rebuild()
Tag.model_rebuild()
Document.model_rebuild()


# Пользователи / аутентификация
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    sub: Optional[str] = None
    role: Optional[str] = None


class UserBase(BaseModel):
    email: str
    full_name: Optional[str] = None
    role: str = "user"
    is_active: bool = True


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Схемы для чанков документов
class DocumentChunkBase(BaseModel):
    chunk_index: int
    text: str
    embedding: Optional[str] = None


class DocumentChunkCreate(DocumentChunkBase):
    document_id: int


class DocumentChunkUpdate(BaseModel):
    text: Optional[str] = None
    embedding: Optional[str] = None


class DocumentChunk(DocumentChunkBase):
    id: int
    document_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentChunkListResponse(BaseModel):
    chunks: List[DocumentChunk]
    total: int


# ============================================================================
# СХЕМЫ ДЛЯ АВТОМОБИЛЕЙ
# ============================================================================

class CarBase(BaseModel):
    title: Optional[str] = None
    doc_num: Optional[str] = None
    stock_qty: Optional[int] = None
    mark: Optional[str] = None
    model: Optional[str] = None
    code_compl: Optional[str] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    manufacture_year: Optional[int] = None
    fuel_type: Optional[str] = None
    power: Optional[str] = None
    body_type: Optional[str] = None
    gear_box_type: Optional[str] = None
    driving_gear_type: Optional[str] = None
    engine_vol: Optional[int] = None
    dealer_center: Optional[str] = None


class Car(CarBase):
    id: int
    interior_color: Optional[str] = None
    engine: Optional[str] = None
    door_qty: Optional[str] = None
    pts_colour: Optional[str] = None
    model_year: Optional[str] = None
    fuel_consumption: Optional[str] = None
    max_torque: Optional[str] = None
    acceleration: Optional[str] = None
    max_speed: Optional[str] = None
    eco_class: Optional[str] = None
    dimensions: Optional[str] = None
    weight: Optional[str] = None
    cargo_volume: Optional[str] = None
    compl_level: Optional[str] = None
    interior_code: Optional[str] = None
    color_code: Optional[str] = None
    car_order_int_status: Optional[str] = None
    sale_price: Optional[str] = None
    max_additional_discount: Optional[str] = None
    max_discount_trade_in: Optional[str] = None
    max_discount_credit: Optional[str] = None
    max_discount_casko: Optional[str] = None
    max_discount_extra_gear: Optional[str] = None
    max_discount_life_insurance: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class UsedCarBase(BaseModel):
    title: Optional[str] = None
    doc_num: Optional[str] = None
    mark: Optional[str] = None
    model: Optional[str] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    manufacture_year: Optional[int] = None
    mileage: Optional[int] = None
    body_type: Optional[str] = None
    gear_box_type: Optional[str] = None
    driving_gear_type: Optional[str] = None
    engine_vol: Optional[int] = None
    power: Optional[str] = None
    fuel_type: Optional[str] = None


class UsedCar(UsedCarBase):
    id: int
    dealer_center: Optional[str] = None
    date_begin: Optional[str] = None
    date_end: Optional[str] = None
    ad_status: Optional[str] = None
    allow_email: Optional[str] = None
    company_name: Optional[str] = None
    manager_name: Optional[str] = None
    contact_phone: Optional[str] = None
    category: Optional[str] = None
    region: Optional[str] = None
    car_type: Optional[str] = None
    accident: Optional[str] = None
    certification_number: Optional[str] = None
    allow_avtokod_report_link: Optional[str] = None
    doors: Optional[str] = None
    wheel_type: Optional[str] = None
    owners: Optional[int] = None
    street: Optional[str] = None
    sticker: Optional[str] = None
    generation_id: Optional[str] = None
    modification_id: Optional[str] = None
    aaa_max_additional_discount: Optional[str] = None
    aaa_max_discount_trade_in: Optional[str] = None
    aaa_max_discount_credit: Optional[str] = None
    aaa_max_discount_casko: Optional[str] = None
    aaa_max_discount_extra_gear: Optional[str] = None
    aaa_max_discount_life_insurance: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class CarListResponse(BaseModel):
    cars: List[Car]
    total: int
    page: int
    size: int


class UsedCarListResponse(BaseModel):
    used_cars: List[UsedCar]
    total: int
    page: int
    size: int


# Схемы для AI Model Orchestrator
class ModelSelectionRequest(BaseModel):
    task_type: str
    user_override: Optional[str] = None
    task_complexity: Optional[str] = None  # "light", "medium", "heavy"


class ModelSelectionResponse(BaseModel):
    selected_model: str
    task_type: str
    source: str  # "user_override", "user_settings", "config", "fallback"


class OrchestratorPerformanceResponse(BaseModel):
    metrics: Dict[str, Any]
    total_requests: int
    models_used: List[str]


class BulkModelUpdateRequest(BaseModel):
    models: Dict[str, str]  # task_type -> model_name


class BulkModelUpdateResponse(BaseModel):
    success: bool
    updated_tasks: List[str]
    failed_tasks: List[str]


# Схемы для интеллектуального поиска
class IntelligentSearchRequest(BaseModel):
    query: Optional[str] = None
    mark: Optional[str] = None
    model: Optional[str] = None
    city: Optional[str] = None
    fuel_type: Optional[str] = None
    body_type: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    min_mileage: Optional[int] = None
    max_mileage: Optional[int] = None
    color: Optional[str] = None
    interior_color: Optional[str] = None
    options: Optional[str] = None
    car_type: Optional[str] = None
    min_power: Optional[float] = None
    max_power: Optional[float] = None
    min_engine_vol: Optional[float] = None
    max_engine_vol: Optional[float] = None
    dialogue_context: Optional[str] = ""
    limit: int = 20
    offset: int = 0


class IntelligentSearchResponse(BaseModel):
    success: bool
    results: List[Dict[str, Any]]
    total: int
    relaxation_applied: bool
    relaxation_steps: int
    relaxed_params: Optional[Dict[str, Any]] = None
    original_params: Optional[Dict[str, Any]] = None
    recommendations: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error: Optional[str] = None


# Схемы для главного ассистента автосалона
class CarDealerQueryRequest(BaseModel):
    user_query: str
    user_id: str
    session_id: Optional[int] = None


class CarDealerQueryResponse(BaseModel):
    user_query: str
    query_topic: str
    is_related: bool
    relation_type: str
    relation_confidence: float
    search_performed: bool
    search_results: Optional[Dict[str, Any]] = None
    clarifying_questions: List[Dict[str, Any]] = []
    proactive_suggestions: List[Dict[str, Any]] = []
    finance_calculation: Optional[Dict[str, Any]] = None
    response: str
    emotion_data: Optional[Dict[str, Any]] = None
    response_time: float
    error: Optional[str] = None


# Схемы для финансовых расчетов
class FinanceCalculationRequest(BaseModel):
    car_price: float
    down_payment: Optional[float] = None
    down_payment_percent: Optional[float] = 20.0
    interest_rate: Optional[float] = None
    loan_term: Optional[int] = 60  # в месяцах
    calculation_type: str = "loan"  # "loan", "lease", "compare"
    residual_value: Optional[float] = None  # для лизинга
    lease_term: Optional[int] = None  # для лизинга


class FinanceCalculationResponse(BaseModel):
    success: bool
    calculation_type: str
    loan_calculation: Optional[Dict[str, Any]] = None
    lease_calculation: Optional[Dict[str, Any]] = None
    comparison: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# Схемы для истории диалога
class DialogueHistoryRequest(BaseModel):
    user_id: str
    session_id: Optional[int] = None
    limit: Optional[int] = 50


class DialogueHistoryResponse(BaseModel):
    success: bool
    messages: List[Dict[str, Any]]
    topics: List[str]
    user_interests: List[str]
    total_messages: int
    error: Optional[str] = None


# Схемы для визуализации диалога
class DialogueVisualizationResponse(BaseModel):
    success: bool
    dialogue_map: Dict[str, Any]
    topic_transitions: List[Dict[str, Any]]
    key_moments: List[Dict[str, Any]]
    error: Optional[str] = None


# Схемы для метрик качества
class QualityMetricsResponse(BaseModel):
    success: bool
    performance_summary: Dict[str, Any]
    model_performance: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class CarPicture(BaseModel):
    id: int
    car_id: int
    url: Optional[str] = None
    type: Optional[str] = None
    seqno: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class UsedCarPicture(BaseModel):
    id: int
    used_car_id: int
    url: Optional[str] = None
    type: Optional[str] = None
    seqno: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class CarOption(BaseModel):
    id: int
    car_id: int
    code: Optional[str] = None
    description: Optional[str] = None
    options_group_id: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class CarOptionsGroup(BaseModel):
    id: int
    car_id: int
    code: Optional[str] = None
    name: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# Обновляем forward references для автомобилей
Car.model_rebuild()
UsedCar.model_rebuild()
ChatMessageResponse.model_rebuild()

# AI API Schemas
class AIConnectionTest(BaseModel):
    service: str
    key: str

class AIModelSettings(BaseModel):
    response_model: str
    embedding_model: str
    api_service: Optional[str] = None
    api_key: Optional[str] = None
    deep_thinking_model: Optional[str] = ""  # Модель для режима размышления
    deepseek_api_key: Optional[str] = ""  # API ключ для DeepSeek (если используется)

class OllamaModel(BaseModel):
    name: str
    size: Optional[str] = None
    modified_at: Optional[str] = None


class ParsedCarBase(BaseModel):
    source_url: str
    mark: Optional[str] = None
    model: Optional[str] = None
    city: Optional[str] = None
    price: Optional[str] = None
    manufacture_year: Optional[int] = None
    body_type: Optional[str] = None
    fuel_type: Optional[str] = None
    gear_box_type: Optional[str] = None
    driving_gear_type: Optional[str] = None
    engine_vol: Optional[int] = None
    power: Optional[str] = None
    color: Optional[str] = None
    mileage: Optional[int] = None
    characteristics: Optional[str] = None  # JSON строка


class ParsedCarPictureBase(BaseModel):
    image_url: str
    local_path: Optional[str] = None
    seqno: int = 0


class ParsedCarCreate(ParsedCarBase):
    pictures: List[ParsedCarPictureBase] = []


class ParsedCarPicture(ParsedCarPictureBase):
    id: int
    parsed_car_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ParsedCar(ParsedCarBase):
    id: int
    parsed_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True
    pictures: List[ParsedCarPicture] = []

    class Config:
        from_attributes = True


class ParsedCarListResponse(BaseModel):
    cars: List[ParsedCar]
    total: int
    skip: int = 0
    limit: int = 100


# ============================================================================
# СХЕМЫ ДЛЯ ИМПОРТА АВТОМОБИЛЕЙ
# ============================================================================

class ImportCarBase(BaseModel):
    """Базовая схема для импорта нового автомобиля"""
    title: Optional[str] = None
    doc_num: Optional[str] = None
    stock_qty: Optional[int] = None
    mark: Optional[str] = None
    model: Optional[str] = None
    code_compl: Optional[str] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    manufacture_year: Optional[int] = None
    fuel_type: Optional[str] = None
    power: Optional[str] = None
    body_type: Optional[str] = None
    gear_box_type: Optional[str] = None
    driving_gear_type: Optional[str] = None
    engine_vol: Optional[int] = None
    dealer_center: Optional[str] = None
    interior_color: Optional[str] = None
    engine: Optional[str] = None
    door_qty: Optional[str] = None
    pts_colour: Optional[str] = None
    model_year: Optional[str] = None
    fuel_consumption: Optional[str] = None
    max_torque: Optional[str] = None
    acceleration: Optional[str] = None
    max_speed: Optional[str] = None
    eco_class: Optional[str] = None
    dimensions: Optional[str] = None
    weight: Optional[str] = None
    cargo_volume: Optional[str] = None
    compl_level: Optional[str] = None
    interior_code: Optional[str] = None
    color_code: Optional[str] = None
    car_order_int_status: Optional[str] = None
    sale_price: Optional[str] = None
    max_additional_discount: Optional[str] = None
    max_discount_trade_in: Optional[str] = None
    max_discount_credit: Optional[str] = None
    max_discount_casko: Optional[str] = None
    max_discount_extra_gear: Optional[str] = None
    max_discount_life_insurance: Optional[str] = None


class ImportCar(ImportCarBase):
    id: int
    import_status: str
    import_source: Optional[str] = None
    import_error: Optional[str] = None
    imported_at: datetime
    migrated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ImportUsedCarBase(BaseModel):
    """Базовая схема для импорта подержанного автомобиля"""
    title: Optional[str] = None
    doc_num: Optional[str] = None
    mark: Optional[str] = None
    model: Optional[str] = None
    vin: Optional[str] = None
    color: Optional[str] = None
    price: Optional[str] = None
    city: Optional[str] = None
    manufacture_year: Optional[int] = None
    mileage: Optional[int] = None
    body_type: Optional[str] = None
    gear_box_type: Optional[str] = None
    driving_gear_type: Optional[str] = None
    engine_vol: Optional[int] = None
    power: Optional[str] = None
    fuel_type: Optional[str] = None
    dealer_center: Optional[str] = None
    date_begin: Optional[str] = None
    date_end: Optional[str] = None
    ad_status: Optional[str] = None
    allow_email: Optional[str] = None
    company_name: Optional[str] = None
    manager_name: Optional[str] = None
    contact_phone: Optional[str] = None
    category: Optional[str] = None
    region: Optional[str] = None
    car_type: Optional[str] = None
    accident: Optional[str] = None
    certification_number: Optional[str] = None
    allow_avtokod_report_link: Optional[str] = None
    doors: Optional[str] = None
    wheel_type: Optional[str] = None
    owners: Optional[int] = None
    street: Optional[str] = None
    sticker: Optional[str] = None
    generation_id: Optional[str] = None
    modification_id: Optional[str] = None
    aaa_max_additional_discount: Optional[str] = None
    aaa_max_discount_trade_in: Optional[str] = None
    aaa_max_discount_credit: Optional[str] = None
    aaa_max_discount_casko: Optional[str] = None
    aaa_max_discount_extra_gear: Optional[str] = None
    aaa_max_discount_life_insurance: Optional[str] = None


class ImportUsedCar(ImportUsedCarBase):
    id: int
    import_status: str
    import_source: Optional[str] = None
    import_error: Optional[str] = None
    imported_at: datetime
    migrated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ImportCarPicture(BaseModel):
    id: int
    car_id: int
    url: Optional[str] = None
    type: Optional[str] = None
    seqno: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ImportUsedCarPicture(BaseModel):
    id: int
    used_car_id: int
    url: Optional[str] = None
    type: Optional[str] = None
    seqno: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ImportCarOption(BaseModel):
    id: int
    car_id: int
    code: Optional[str] = None
    description: Optional[str] = None
    options_group_id: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ImportCarOptionsGroup(BaseModel):
    id: int
    car_id: int
    code: Optional[str] = None
    name: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# Схемы для загрузки и анализа файлов
class ImportFileUploadRequest(BaseModel):
    """Запрос на загрузку файла для импорта"""
    filename: str
    file_type: str  # "json" или "xml"


class FieldMapping(BaseModel):
    """Сопоставление поля из файла с полем таблицы"""
    source_field: str  # Поле из файла
    target_field: Optional[str] = None  # Поле в таблице (None = не импортировать)


class ImportAnalysisResponse(BaseModel):
    """Ответ с анализом файла и автоматическим сопоставлением полей"""
    file_type: str
    total_records: int
    sample_records: List[Dict[str, Any]]  # Первые несколько записей для примера
    available_fields: List[str]  # Все доступные поля в файле
    auto_mapping: Dict[str, Optional[str]]  # Автоматическое сопоставление: {source_field: target_field}
    suggestions: Dict[str, List[str]]  # Предложения для каждого поля: {source_field: [possible_targets]}


class ImportSaveRequest(BaseModel):
    """Запрос на сохранение импортированных данных"""
    file_type: str
    field_mapping: Dict[str, Optional[str]]  # {source_field: target_field}
    car_type: str = "new"  # "new" или "used"


class ImportSaveResponse(BaseModel):
    """Ответ о результате сохранения импорта"""
    success: bool
    imported_cars: int
    imported_pictures: int
    imported_options: int
    imported_used_cars: int = 0  # Для обратной совместимости
    errors: List[str] = []


class ImportListResponse(BaseModel):
    """Список импортированных автомобилей"""
    cars: List[ImportCar]
    used_cars: List[ImportUsedCar]
    total: int
    total_used: int
    skip: int = 0
    limit: int = 100


class MigrateRequest(BaseModel):
    """Запрос на миграцию данных"""
    car_type: Optional[str] = None  # "new", "used" или None (все)
    delete_old: bool = True  # Удалять старые данные перед миграцией


class MigrateResponse(BaseModel):
    """Ответ о результате миграции"""
    success: bool
    migrated_cars: int
    migrated_used_cars: int
    migrated_pictures: int
    migrated_options: int
    deleted_old_cars: int
    deleted_old_used_cars: int
    errors: List[str] = []


class ParserStartRequest(BaseModel):
    base_url: str = "https://aaa-motors.ru"
    max_pages: Optional[int] = None  # Максимальное количество страниц для парсинга
    max_cars: Optional[int] = None  # Максимальное количество автомобилей
    delay: float = 1.0  # Задержка между запросами (секунды)
    use_ai: bool = True  # Использовать ИИ-парсер (NLP, ML компоненты)
    use_ollama: bool = True  # Использовать Ollama для извлечения данных
    ollama_model: Optional[str] = None  # Модель Ollama (по умолчанию из настроек)
    clear_before: bool = True  # Очистить все данные перед парсингом


class ParserStatusResponse(BaseModel):
    status: str  # "running", "completed", "error", "stopped"
    total_parsed: int
    total_errors: int
    current_page: Optional[int] = None
    message: Optional[str] = None
    nlp_extractions: Optional[int] = None  # Количество NLP извлечений
    ollama_extractions: Optional[int] = None  # Количество Ollama извлечений
    structure_changes_detected: Optional[int] = None  # Обнаруженные изменения структуры


# ========== СХЕМЫ ДЛЯ РАСПОЗНАВАНИЯ РЕЧИ ==========

class VoiceSettingsRequest(BaseModel):
    """Запрос на обновление настроек голосового ввода"""
    enabled: Optional[bool] = False
    model: Optional[str] = "base"  # tiny, base, small, medium, large
    autoDetectLanguage: Optional[bool] = True
    language: Optional[str] = "ru"  # ru, en, uk, de, fr, es и т.д.
    silenceThreshold: Optional[int] = 500
    minSpeechDuration: Optional[float] = 1.0

class VoiceSettingsResponse(BaseModel):
    """Ответ с настройками голосового ввода"""
    enabled: bool = False
    model: str = "base"
    autoDetectLanguage: bool = True
    language: str = "ru"
    silenceThreshold: int = 500
    minSpeechDuration: float = 1.0

class VoiceTranscribeResponse(BaseModel):
    """Ответ с результатом транскрибации"""
    text: str
    language: str
    confidence: Optional[float] = None
