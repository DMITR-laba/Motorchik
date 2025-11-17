from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table, Boolean, LargeBinary, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from models import Base

# Импорт для работы с pgvector
try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False
    # Заглушка для случаев, когда pgvector не установлен
    Vector = None

# Пользователи
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    role = Column(String(50), default="user")  # user | admin
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Связующие таблицы для many-to-many отношений
article_categories = Table(
    'article_categories',
    Base.metadata,
    Column('article_id', Integer, ForeignKey('articles.id'), primary_key=True),
    Column('category_id', Integer, ForeignKey('categories.id'), primary_key=True)
)

article_tags = Table(
    'article_tags',
    Base.metadata,
    Column('article_id', Integer, ForeignKey('articles.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)


class Article(Base):
    __tablename__ = "articles"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(1024), nullable=False, index=True)
    text = Column(Text, nullable=False)
    url = Column(String(1024), nullable=True)
    language = Column(String(10), default="ru")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Связи
    categories = relationship("Category", secondary=article_categories, back_populates="articles")
    tags = relationship("Tag", secondary=article_tags, back_populates="articles")


class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связи
    articles = relationship("Article", secondary=article_categories, back_populates="categories")


class Tag(Base):
    __tablename__ = "tags"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связи
    articles = relationship("Article", secondary=article_tags, back_populates="tags")


class Chat(Base):
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    title = Column(String(500), nullable=True)  # Автоматически генерируется или задается пользователем
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Связи
    messages = relationship("ChatMessage", back_populates="chat", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)  # Исправлено: NOT NULL
    user_id = Column(String(100), nullable=False, index=True)
    message = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    feedback = Column(Integer, nullable=True)  # 1 - полезно, -1 - неполезно
    feedback_comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связанные статьи (для RAG)
    related_article_ids = Column(Text, nullable=True)  # JSON строка с ID статей
    
    # Sources data (JSON) - сохраняет информацию о найденных автомобилях, документах и статьях
    sources_data = Column(Text, nullable=True)  # JSON строка с sources: {cars: [], articles: [], documents: []}
    
    # Связи
    chat = relationship("Chat", back_populates="messages")


# Связующие таблицы для документов
document_categories = Table(
    'document_categories',
    Base.metadata,
    Column('document_id', Integer, ForeignKey('documents.id'), primary_key=True),
    Column('category_id', Integer, ForeignKey('categories.id'), primary_key=True)
)

document_tags = Table(
    'document_tags',
    Base.metadata,
    Column('document_id', Integer, ForeignKey('documents.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)


class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(10), nullable=False)  # pdf, doc, docx, txt
    file_size = Column(Integer, nullable=False)
    file_content = Column(LargeBinary, nullable=True)  # Бинарные данные файла
    
    # Обработанный контент
    title = Column(String(1024), nullable=True, index=True)
    extracted_text = Column(Text, nullable=True)
    topic = Column(String(255), nullable=True, index=True)  # Сгенерированная тема
    summary = Column(Text, nullable=True)
    path = Column(String(512), nullable=True)  # Путь к файлу для контекста
    
    # Метаданные
    language = Column(String(10), default="ru")
    processing_status = Column(String(20), default="pending")  # pending, processing, completed, failed
    error_message = Column(Text, nullable=True)
    
    # Временные метки
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Связи
    categories = relationship("Category", secondary=document_categories, back_populates="documents")
    tags = relationship("Tag", secondary=document_tags, back_populates="documents")


# Обновляем связи для Category и Tag
Category.documents = relationship("Document", secondary=document_categories, back_populates="categories")
Tag.documents = relationship("Document", secondary=document_tags, back_populates="tags")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)  # Порядковый номер чанка
    text = Column(Text, nullable=False)  # Текст чанка
    embedding = Column(Text, nullable=True)  # JSON с эмбеддингом
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связь с документом
    document = relationship("Document", back_populates="chunks")


# Добавляем связь с чанками в модель Document
Document.chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


# ============================================================================
# МОДЕЛИ ДЛЯ АВТОМОБИЛЕЙ
# ============================================================================

class Car(Base):
    """Модель для новых автомобилей"""
    __tablename__ = "cars"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=True)
    doc_num = Column(String(50), nullable=True, index=True)
    stock_qty = Column(Integer, nullable=True)
    mark = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=True, index=True)
    code_compl = Column(String(100), nullable=True)
    vin = Column(String(50), nullable=True, index=True)
    color = Column(String(50), nullable=True)
    price = Column(String(50), nullable=True)  # FLOAT в SQLite, но может быть строкой
    city = Column(String(100), nullable=True, index=True)
    manufacture_year = Column(Integer, nullable=True, index=True)
    fuel_type = Column(String(50), nullable=True, index=True)
    power = Column(String(50), nullable=True)  # FLOAT в SQLite
    body_type = Column(String(50), nullable=True, index=True)
    gear_box_type = Column(String(50), nullable=True, index=True)
    driving_gear_type = Column(String(50), nullable=True)
    engine_vol = Column(Integer, nullable=True)
    dealer_center = Column(String(100), nullable=True)
    interior_color = Column(String(100), nullable=True)
    engine = Column(String(100), nullable=True)
    door_qty = Column(String(20), nullable=True)
    pts_colour = Column(String(50), nullable=True)
    model_year = Column(String(20), nullable=True)
    fuel_consumption = Column(String(50), nullable=True)
    max_torque = Column(String(50), nullable=True)
    acceleration = Column(String(20), nullable=True)
    max_speed = Column(String(20), nullable=True)
    eco_class = Column(String(20), nullable=True)
    dimensions = Column(String(50), nullable=True)
    weight = Column(String(20), nullable=True)
    cargo_volume = Column(String(50), nullable=True)
    compl_level = Column(String(100), nullable=True)
    interior_code = Column(String(50), nullable=True)
    color_code = Column(String(50), nullable=True)
    car_order_int_status = Column(String(20), nullable=True)
    sale_price = Column(String(50), nullable=True)  # FLOAT
    max_additional_discount = Column(String(50), nullable=True)  # FLOAT
    max_discount_trade_in = Column(String(50), nullable=True)  # FLOAT
    max_discount_credit = Column(String(50), nullable=True)  # FLOAT
    max_discount_casko = Column(String(50), nullable=True)  # FLOAT
    max_discount_extra_gear = Column(String(50), nullable=True)  # FLOAT
    max_discount_life_insurance = Column(String(50), nullable=True)  # FLOAT
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Связи
    pictures = relationship("CarPicture", back_populates="car", cascade="all, delete-orphan")
    options = relationship("CarOption", back_populates="car", cascade="all, delete-orphan")
    options_groups = relationship("CarOptionsGroup", back_populates="car", cascade="all, delete-orphan")


class UsedCar(Base):
    """Модель для подержанных автомобилей"""
    __tablename__ = "used_cars"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=True)
    doc_num = Column(String(50), nullable=True, index=True)
    mark = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=True, index=True)
    vin = Column(String(50), nullable=True, index=True)
    color = Column(String(50), nullable=True)
    price = Column(String(50), nullable=True)  # FLOAT
    city = Column(String(100), nullable=True, index=True)
    manufacture_year = Column(Integer, nullable=True, index=True)
    mileage = Column(Integer, nullable=True, index=True)
    body_type = Column(String(50), nullable=True, index=True)
    gear_box_type = Column(String(50), nullable=True, index=True)
    driving_gear_type = Column(String(50), nullable=True)
    engine_vol = Column(Integer, nullable=True)
    power = Column(String(50), nullable=True)  # FLOAT
    fuel_type = Column(String(50), nullable=True, index=True)
    dealer_center = Column(String(100), nullable=True)
    date_begin = Column(String(20), nullable=True)
    date_end = Column(String(20), nullable=True)
    ad_status = Column(String(50), nullable=True)
    allow_email = Column(String(10), nullable=True)
    company_name = Column(String(200), nullable=True)
    manager_name = Column(String(200), nullable=True)
    contact_phone = Column(String(20), nullable=True)
    category = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    car_type = Column(String(50), nullable=True)
    accident = Column(String(50), nullable=True)
    certification_number = Column(String(100), nullable=True)
    allow_avtokod_report_link = Column(String(10), nullable=True)
    doors = Column(String(20), nullable=True)
    wheel_type = Column(String(50), nullable=True)
    owners = Column(Integer, nullable=True)
    street = Column(String(200), nullable=True)
    sticker = Column(String(200), nullable=True)
    generation_id = Column(String(100), nullable=True)
    modification_id = Column(String(100), nullable=True)
    dimensions = Column(String(50), nullable=True)  # Габариты
    weight = Column(String(20), nullable=True)  # Вес
    cargo_volume = Column(String(50), nullable=True)  # Объем багажника
    aaa_max_additional_discount = Column(String(50), nullable=True)
    aaa_max_discount_trade_in = Column(String(50), nullable=True)
    aaa_max_discount_credit = Column(String(50), nullable=True)
    aaa_max_discount_casko = Column(String(50), nullable=True)
    aaa_max_discount_extra_gear = Column(String(50), nullable=True)
    aaa_max_discount_life_insurance = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Связи
    pictures = relationship("UsedCarPicture", back_populates="used_car", cascade="all, delete-orphan")


class CarPicture(Base):
    """Модель для фотографий новых автомобилей"""
    __tablename__ = "car_pictures"
    
    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False, index=True)
    url = Column(String(500), nullable=True)
    type = Column(String(50), nullable=True)
    seqno = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связь
    car = relationship("Car", back_populates="pictures")


class UsedCarPicture(Base):
    """Модель для фотографий подержанных автомобилей"""
    __tablename__ = "used_car_pictures"
    
    id = Column(Integer, primary_key=True, index=True)
    used_car_id = Column(Integer, ForeignKey("used_cars.id"), nullable=False, index=True)
    url = Column(String(500), nullable=True)
    type = Column(String(50), nullable=True)
    seqno = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связь
    used_car = relationship("UsedCar", back_populates="pictures")


class CarOptionsGroup(Base):
    """Модель для групп опций автомобиля"""
    __tablename__ = "car_options_groups"
    
    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False, index=True)
    code = Column(String(50), nullable=True)
    name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связи
    car = relationship("Car", back_populates="options_groups")
    options = relationship("CarOption", back_populates="options_group", cascade="all, delete-orphan")


class CarOption(Base):
    """Модель для опций автомобиля"""
    __tablename__ = "car_options"
    
    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("cars.id"), nullable=False, index=True)
    code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    options_group_id = Column(Integer, ForeignKey("car_options_groups.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связи
    car = relationship("Car", back_populates="options")
    options_group = relationship("CarOptionsGroup", back_populates="options")


class ParsedCar(Base):
    """Модель для парсинга автомобилей с aaa-motors.ru"""
    __tablename__ = "parsed_cars"
    
    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String(1024), nullable=False, unique=True, index=True)
    mark = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=True, index=True)
    city = Column(String(100), nullable=True, index=True)
    
    # Основные характеристики
    price = Column(String(50), nullable=True)
    manufacture_year = Column(Integer, nullable=True, index=True)
    body_type = Column(String(50), nullable=True)
    fuel_type = Column(String(50), nullable=True)
    gear_box_type = Column(String(50), nullable=True)
    driving_gear_type = Column(String(50), nullable=True)
    engine_vol = Column(Integer, nullable=True)
    power = Column(String(50), nullable=True)
    color = Column(String(50), nullable=True)
    mileage = Column(Integer, nullable=True)
    
    # Дополнительные характеристики (JSON)
    characteristics = Column(Text, nullable=True)  # JSON строка с дополнительными характеристиками
    
    # Метаданные парсинга
    parsed_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, default=True)  # Флаг активности объявления
    
    # Связи
    pictures = relationship("ParsedCarPicture", back_populates="parsed_car", cascade="all, delete-orphan")


# ============================================================================
# МОДЕЛИ ДЛЯ ИМПОРТА АВТОМОБИЛЕЙ
# ============================================================================

class ImportCar(Base):
    """Модель для импорта новых автомобилей"""
    __tablename__ = "import_cars"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=True)
    doc_num = Column(String(50), nullable=True, index=True)
    stock_qty = Column(Integer, nullable=True)
    mark = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=True, index=True)
    code_compl = Column(String(100), nullable=True)
    vin = Column(String(50), nullable=True, index=True)
    color = Column(String(50), nullable=True)
    price = Column(String(50), nullable=True)
    city = Column(String(100), nullable=True, index=True)
    manufacture_year = Column(Integer, nullable=True, index=True)
    fuel_type = Column(String(50), nullable=True, index=True)
    power = Column(String(50), nullable=True)
    body_type = Column(String(50), nullable=True, index=True)
    gear_box_type = Column(String(50), nullable=True, index=True)
    driving_gear_type = Column(String(50), nullable=True)
    engine_vol = Column(Integer, nullable=True)
    dealer_center = Column(String(100), nullable=True)
    interior_color = Column(String(100), nullable=True)
    engine = Column(String(100), nullable=True)
    door_qty = Column(String(20), nullable=True)
    pts_colour = Column(String(50), nullable=True)
    model_year = Column(String(20), nullable=True)
    fuel_consumption = Column(String(50), nullable=True)
    max_torque = Column(String(50), nullable=True)
    acceleration = Column(String(20), nullable=True)
    max_speed = Column(String(20), nullable=True)
    eco_class = Column(String(20), nullable=True)
    dimensions = Column(String(50), nullable=True)
    weight = Column(String(20), nullable=True)
    cargo_volume = Column(String(50), nullable=True)
    compl_level = Column(String(100), nullable=True)
    interior_code = Column(String(50), nullable=True)
    color_code = Column(String(50), nullable=True)
    car_order_int_status = Column(String(20), nullable=True)
    sale_price = Column(String(50), nullable=True)
    max_additional_discount = Column(String(50), nullable=True)
    max_discount_trade_in = Column(String(50), nullable=True)
    max_discount_credit = Column(String(50), nullable=True)
    max_discount_casko = Column(String(50), nullable=True)
    max_discount_extra_gear = Column(String(50), nullable=True)
    max_discount_life_insurance = Column(String(50), nullable=True)
    
    # Поля для импорта
    import_status = Column(String(20), default="pending", index=True)  # pending, imported, migrated, error
    import_source = Column(String(255), nullable=True)  # Имя файла или источник импорта
    import_error = Column(Text, nullable=True)  # Сообщение об ошибке
    imported_at = Column(DateTime(timezone=True), server_default=func.now())
    migrated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Связи
    pictures = relationship("ImportCarPicture", back_populates="car", cascade="all, delete-orphan")
    options = relationship("ImportCarOption", back_populates="car", cascade="all, delete-orphan")
    options_groups = relationship("ImportCarOptionsGroup", back_populates="car", cascade="all, delete-orphan")


class ImportUsedCar(Base):
    """Модель для импорта подержанных автомобилей"""
    __tablename__ = "import_used_cars"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=True)
    doc_num = Column(String(50), nullable=True, index=True)
    mark = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=True, index=True)
    vin = Column(String(50), nullable=True, index=True)
    color = Column(String(50), nullable=True)
    price = Column(String(50), nullable=True)
    city = Column(String(100), nullable=True, index=True)
    manufacture_year = Column(Integer, nullable=True, index=True)
    mileage = Column(Integer, nullable=True, index=True)
    body_type = Column(String(50), nullable=True, index=True)
    gear_box_type = Column(String(50), nullable=True, index=True)
    driving_gear_type = Column(String(50), nullable=True)
    engine_vol = Column(Integer, nullable=True)
    power = Column(String(50), nullable=True)
    fuel_type = Column(String(50), nullable=True, index=True)
    dealer_center = Column(String(100), nullable=True)
    date_begin = Column(String(20), nullable=True)
    date_end = Column(String(20), nullable=True)
    ad_status = Column(String(50), nullable=True)
    allow_email = Column(String(10), nullable=True)
    company_name = Column(String(200), nullable=True)
    manager_name = Column(String(200), nullable=True)
    contact_phone = Column(String(20), nullable=True)
    category = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    car_type = Column(String(50), nullable=True)
    accident = Column(String(50), nullable=True)
    certification_number = Column(String(100), nullable=True)
    allow_avtokod_report_link = Column(String(10), nullable=True)
    doors = Column(String(20), nullable=True)
    wheel_type = Column(String(50), nullable=True)
    owners = Column(Integer, nullable=True)
    street = Column(String(200), nullable=True)
    sticker = Column(String(200), nullable=True)
    generation_id = Column(String(100), nullable=True)
    modification_id = Column(String(100), nullable=True)
    aaa_max_additional_discount = Column(String(50), nullable=True)
    aaa_max_discount_trade_in = Column(String(50), nullable=True)
    aaa_max_discount_credit = Column(String(50), nullable=True)
    aaa_max_discount_casko = Column(String(50), nullable=True)
    aaa_max_discount_extra_gear = Column(String(50), nullable=True)
    aaa_max_discount_life_insurance = Column(String(50), nullable=True)
    
    # Поля для импорта
    import_status = Column(String(20), default="pending", index=True)
    import_source = Column(String(255), nullable=True)
    import_error = Column(Text, nullable=True)
    imported_at = Column(DateTime(timezone=True), server_default=func.now())
    migrated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Связи
    pictures = relationship("ImportUsedCarPicture", back_populates="used_car", cascade="all, delete-orphan")


class ImportCarPicture(Base):
    """Модель для импорта фотографий новых автомобилей"""
    __tablename__ = "import_car_pictures"
    
    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("import_cars.id"), nullable=False, index=True)
    url = Column(String(500), nullable=True)
    type = Column(String(50), nullable=True)
    seqno = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связь
    car = relationship("ImportCar", back_populates="pictures")


class ImportUsedCarPicture(Base):
    """Модель для импорта фотографий подержанных автомобилей"""
    __tablename__ = "import_used_car_pictures"
    
    id = Column(Integer, primary_key=True, index=True)
    used_car_id = Column(Integer, ForeignKey("import_used_cars.id"), nullable=False, index=True)
    url = Column(String(500), nullable=True)
    type = Column(String(50), nullable=True)
    seqno = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связь
    used_car = relationship("ImportUsedCar", back_populates="pictures")


class ImportCarOptionsGroup(Base):
    """Модель для импорта групп опций автомобиля"""
    __tablename__ = "import_car_options_groups"
    
    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("import_cars.id"), nullable=False, index=True)
    code = Column(String(50), nullable=True)
    name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связи
    car = relationship("ImportCar", back_populates="options_groups")
    options = relationship("ImportCarOption", back_populates="options_group", cascade="all, delete-orphan")


class ImportCarOption(Base):
    """Модель для импорта опций автомобиля"""
    __tablename__ = "import_car_options"
    
    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("import_cars.id"), nullable=False, index=True)
    code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    options_group_id = Column(Integer, ForeignKey("import_car_options_groups.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связи
    car = relationship("ImportCar", back_populates="options")
    options_group = relationship("ImportCarOptionsGroup", back_populates="options")


class ParsedCarPicture(Base):
    """Модель для фотографий парсенных автомобилей"""
    __tablename__ = "parsed_car_pictures"
    
    id = Column(Integer, primary_key=True, index=True)
    parsed_car_id = Column(Integer, ForeignKey("parsed_cars.id"), nullable=False, index=True)
    image_url = Column(String(1024), nullable=False)
    local_path = Column(String(1024), nullable=True)  # Путь к локально сохраненному файлу
    seqno = Column(Integer, default=0)  # Порядковый номер фото
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Связи
    parsed_car = relationship("ParsedCar", back_populates="pictures")


# ============================================================================
# МОДЕЛЬ ДЛЯ ДОЛГОВРЕМЕННОЙ ПАМЯТИ ПОЛЬЗОВАТЕЛЯ
# ============================================================================

class UserMemory(Base):
    """Модель для долговременной памяти пользователя (предпочтения, интересы, критерии)"""
    __tablename__ = "user_memories"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    memory_type = Column(String(50), nullable=False, index=True)  # 'preference', 'rejection', 'interest', 'criteria'
    memory_text = Column(Text, nullable=False)  # Человекочитаемое описание
    
    # Векторное представление для семантического поиска
    if PGVECTOR_AVAILABLE and Vector:
        embedding = Column(Vector(1024), nullable=True)
    else:
        embedding = Column(Text, nullable=True)  # Fallback если pgvector не доступен
    
    # Структурированные данные в JSON
    memory_metadata = Column(Text, nullable=True)  # JSON строка с метаданными (переименовано из metadata, т.к. зарезервировано)
    
    # Уверенность в извлеченной информации
    confidence = Column(Float, default=1.0)
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
