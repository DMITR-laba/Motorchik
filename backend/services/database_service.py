from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, cast, Float
from typing import List, Optional, Tuple, Dict, Any
from models.database import (
    Article, Category, Tag, ChatMessage, User,
    Car, UsedCar, CarPicture, UsedCarPicture, CarOption, CarOptionsGroup
)
from models.schemas import ArticleCreate, ArticleUpdate, CategoryCreate, TagCreate, UserCreate
import json


class DatabaseService:
    def __init__(self, db: Session):
        self.db = db
    
    # Статьи
    def get_articles(self, skip: int = 0, limit: int = 100, search: Optional[str] = None) -> Tuple[List[Article], int]:
        query = self.db.query(Article)
        
        if search:
            search_filter = or_(
                Article.title.ilike(f"%{search}%"),
                Article.text.ilike(f"%{search}%")
            )
            query = query.filter(search_filter)
        
        total = query.count()
        articles = query.offset(skip).limit(limit).all()
        return articles, total
    
    def get_article(self, article_id: int) -> Optional[Article]:
        return self.db.query(Article).filter(Article.id == article_id).first()
    
    def create_article(self, article_data: ArticleCreate) -> Article:
        # Создаем статью
        article = Article(
            title=article_data.title,
            text=article_data.text,
            url=article_data.url,
            language=article_data.language
        )
        self.db.add(article)
        self.db.flush()  # Получаем ID
        
        # Добавляем категории
        if article_data.category_ids:
            categories = self.db.query(Category).filter(Category.id.in_(article_data.category_ids)).all()
            article.categories.extend(categories)
        
        # Добавляем теги
        if article_data.tag_names:
            for tag_name in article_data.tag_names:
                tag = self.db.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    self.db.add(tag)
                    self.db.flush()
                article.tags.append(tag)
        
        self.db.commit()
        self.db.refresh(article)
        return article
    
    def update_article(self, article_id: int, article_data: ArticleUpdate) -> Optional[Article]:
        article = self.get_article(article_id)
        if not article:
            return None
        
        # Обновляем поля
        if article_data.title is not None:
            article.title = article_data.title
        if article_data.text is not None:
            article.text = article_data.text
        if article_data.url is not None:
            article.url = article_data.url
        if article_data.language is not None:
            article.language = article_data.language
        
        # Обновляем категории
        if article_data.category_ids is not None:
            article.categories.clear()
            categories = self.db.query(Category).filter(Category.id.in_(article_data.category_ids)).all()
            article.categories.extend(categories)
        
        # Обновляем теги
        if article_data.tag_names is not None:
            article.tags.clear()
            for tag_name in article_data.tag_names:
                tag = self.db.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    self.db.add(tag)
                    self.db.flush()
                article.tags.append(tag)
        
        self.db.commit()
        self.db.refresh(article)
        return article
    
    def delete_article(self, article_id: int) -> bool:
        article = self.get_article(article_id)
        if not article:
            return False
        
        self.db.delete(article)
        self.db.commit()
        return True
    
    # Категории
    def get_categories(self) -> List[Category]:
        return self.db.query(Category).all()
    
    def get_category(self, category_id: int) -> Optional[Category]:
        return self.db.query(Category).filter(Category.id == category_id).first()
    
    def create_category(self, category_data: CategoryCreate) -> Category:
        category = Category(name=category_data.name, description=category_data.description)
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category
    
    # Теги
    def get_tags(self) -> List[Tag]:
        return self.db.query(Tag).all()
    
    def get_tag(self, tag_id: int) -> Optional[Tag]:
        return self.db.query(Tag).filter(Tag.id == tag_id).first()
    
    def create_tag(self, tag_data: TagCreate) -> Tag:
        tag = Tag(name=tag_data.name)
        self.db.add(tag)
        self.db.commit()
        self.db.refresh(tag)
        return tag
    
    # Поиск статей для RAG
    def search_articles_for_rag(self, query: str, limit: int = 5) -> List[Article]:
        # Простой поиск по заголовку и тексту
        search_filter = or_(
            Article.title.ilike(f"%{query}%"),
            Article.text.ilike(f"%{query}%")
        )
        return self.db.query(Article).filter(search_filter).limit(limit).all()

    def search_articles_by_meta(self, tokens: List[str], limit: int = 5) -> List[Article]:
        """
        Поиск статей по совпадению токенов с тегами/категориями.
        """
        if not tokens:
            return []
        toks = [t.upper() for t in tokens if t and len(t) >= 2]
        if not toks:
            return []
        # Теги
        tag_q = (
            self.db.query(Article)
            .join(Article.tags)
            .filter(Tag.name.in_(toks))
        )
        # Категории
        cat_q = (
            self.db.query(Article)
            .join(Article.categories)
            .filter(Category.name.in_(tokens))
        )
        # Объединяем и ограничиваем
        ids = {a.id for a in tag_q.limit(limit * 2).all()}
        for a in cat_q.limit(limit * 2).all():
            ids.add(a.id)
        if not ids:
            return []
        return (
            self.db.query(Article)
            .filter(Article.id.in_(list(ids)))
            .limit(limit)
            .all()
        )
    
    # Чат сообщения
    def save_chat_message(self, user_id: str, message: str, response: str, related_article_ids: List[int], 
                         chat_id: Optional[int] = None, sources_data: Optional[Dict] = None) -> ChatMessage:
        chat_message = ChatMessage(
            chat_id=chat_id,
            user_id=user_id,
            message=message,
            response=response,
            related_article_ids=json.dumps(related_article_ids),
            sources_data=json.dumps(sources_data) if sources_data else None
        )
        self.db.add(chat_message)
        self.db.commit()
        self.db.refresh(chat_message)
        return chat_message
    
    # Чаты
    def create_chat(self, user_id: str, title: Optional[str] = None) -> 'Chat':
        from models.database import Chat
        chat = Chat(user_id=user_id, title=title)
        self.db.add(chat)
        self.db.commit()
        self.db.refresh(chat)
        return chat
    
    def get_chat(self, chat_id: int, user_id: str) -> Optional['Chat']:
        from models.database import Chat
        return self.db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
    
    def get_user_chats(self, user_id: str, skip: int = 0, limit: int = 50) -> List['Chat']:
        from models.database import Chat
        chats = self.db.query(Chat).filter(Chat.user_id == user_id).order_by(Chat.updated_at.desc()).offset(skip).limit(limit).all()
        # Добавляем количество сообщений для каждого чата
        from models.database import ChatMessage
        for chat in chats:
            chat.message_count = self.db.query(ChatMessage).filter(ChatMessage.chat_id == chat.id).count()
        return chats
    
    def get_chat_messages(self, chat_id: int, user_id: str, skip: int = 0, limit: int = 100) -> List['ChatMessage']:
        from models.database import ChatMessage
        return self.db.query(ChatMessage).filter(
            ChatMessage.chat_id == chat_id,
            ChatMessage.user_id == user_id
        ).order_by(ChatMessage.created_at.asc()).offset(skip).limit(limit).all()
    
    def update_chat_title(self, chat_id: int, user_id: str, title: str) -> bool:
        from models.database import Chat
        chat = self.db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
        if not chat:
            return False
        chat.title = title
        self.db.commit()
        return True
    
    def delete_chat(self, chat_id: int, user_id: str) -> bool:
        """Удаляет чат и все связанные сообщения"""
        from models.database import Chat, ChatMessage
        chat = self.db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == user_id).first()
        if not chat:
            return False
        
        # Удаляем все сообщения чата
        self.db.query(ChatMessage).filter(ChatMessage.chat_id == chat_id).delete()
        
        # Удаляем сам чат
        self.db.delete(chat)
        self.db.commit()
        return True
    
    def update_feedback(self, message_id: int, feedback: int, comment: Optional[str] = None) -> bool:
        chat_message = self.db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
        if not chat_message:
            return False
        
        chat_message.feedback = feedback
        chat_message.feedback_comment = comment
        self.db.commit()
        return True

    # Пользователи
    def get_user_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def create_user(self, user_data: UserCreate, hashed_password: str, role: str = "user") -> User:
        user = User(
            email=user_data.email,
            full_name=user_data.full_name,
            hashed_password=hashed_password,
            role=role,
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_all_users(self) -> List[User]:
        return self.db.query(User).all()
    
    # Автомобили
    def get_cars(self, skip: int = 0, limit: int = 100, search: Optional[str] = None,
                  mark: Optional[str] = None, model: Optional[str] = None,
                  city: Optional[str] = None, fuel_type: Optional[str] = None,
                  body_type: Optional[str] = None, min_price: Optional[float] = None,
                  max_price: Optional[float] = None, min_year: Optional[int] = None,
                  max_year: Optional[int] = None) -> Tuple[List[Car], int]:
        """Получает список новых автомобилей с фильтрацией"""
        query = self.db.query(Car)
        
        if search:
            search_filter = or_(
                Car.mark.ilike(f"%{search}%"),
                Car.model.ilike(f"%{search}%"),
                Car.vin.ilike(f"%{search}%"),
                Car.city.ilike(f"%{search}%")
            )
            query = query.filter(search_filter)
        
        if mark:
            query = query.filter(Car.mark.ilike(f"%{mark}%"))
        if model:
            query = query.filter(Car.model.ilike(f"%{model}%"))
        if city:
            query = query.filter(Car.city.ilike(f"%{city}%"))
        if fuel_type:
            query = query.filter(Car.fuel_type == fuel_type)
        if body_type:
            query = query.filter(Car.body_type == body_type)
        
        if min_year:
            query = query.filter(Car.manufacture_year >= min_year)
        if max_year:
            query = query.filter(Car.manufacture_year <= max_year)
        # Цена хранится как строка – аккуратно кастуем в FLOAT для фильтрации
        if min_price is not None:
            query = query.filter(cast(Car.price, Float) >= float(min_price))
        if max_price is not None:
            query = query.filter(cast(Car.price, Float) <= float(max_price))
        
        total = query.count()
        cars = query.order_by(Car.created_at.desc()).offset(skip).limit(limit).all()
        return cars, total
    
    def get_car(self, car_id: int) -> Optional[Car]:
        return self.db.query(Car).filter(Car.id == car_id).first()
    
    def search_cars_for_rag(self, query: str, limit: int = 5) -> List[Car]:
        """Поиск автомобилей для RAG"""
        search_filter = or_(
            Car.mark.ilike(f"%{query}%"),
            Car.model.ilike(f"%{query}%"),
            Car.city.ilike(f"%{query}%"),
            Car.body_type.ilike(f"%{query}%"),
            Car.fuel_type.ilike(f"%{query}%"),
            Car.gear_box_type.ilike(f"%{query}%")
        )
        return self.db.query(Car).filter(search_filter).limit(limit).all()
    
    def get_used_cars(self, skip: int = 0, limit: int = 100, search: Optional[str] = None,
                      mark: Optional[str] = None, model: Optional[str] = None,
                      city: Optional[str] = None, fuel_type: Optional[str] = None,
                      body_type: Optional[str] = None, min_price: Optional[float] = None,
                      max_price: Optional[float] = None, min_mileage: Optional[int] = None,
                      max_mileage: Optional[int] = None) -> Tuple[List[UsedCar], int]:
        """Получает список подержанных автомобилей с фильтрацией"""
        query = self.db.query(UsedCar)
        
        if search:
            search_filter = or_(
                UsedCar.mark.ilike(f"%{search}%"),
                UsedCar.model.ilike(f"%{search}%"),
                UsedCar.vin.ilike(f"%{search}%"),
                UsedCar.city.ilike(f"%{search}%")
            )
            query = query.filter(search_filter)
        
        if mark:
            query = query.filter(UsedCar.mark.ilike(f"%{mark}%"))
        if model:
            query = query.filter(UsedCar.model.ilike(f"%{model}%"))
        if city:
            query = query.filter(UsedCar.city.ilike(f"%{city}%"))
        if fuel_type:
            query = query.filter(UsedCar.fuel_type == fuel_type)
        if body_type:
            query = query.filter(UsedCar.body_type == body_type)
        
        if min_mileage:
            query = query.filter(UsedCar.mileage >= min_mileage)
        if max_mileage:
            query = query.filter(UsedCar.mileage <= max_mileage)
        # Фильтрация по цене
        if min_price is not None:
            query = query.filter(cast(UsedCar.price, Float) >= float(min_price))
        if max_price is not None:
            query = query.filter(cast(UsedCar.price, Float) <= float(max_price))
        
        total = query.count()
        cars = query.order_by(UsedCar.created_at.desc()).offset(skip).limit(limit).all()
        return cars, total
    
    def get_used_car(self, used_car_id: int) -> Optional[UsedCar]:
        return self.db.query(UsedCar).filter(UsedCar.id == used_car_id).first()
    
    def get_cars_statistics(self) -> Dict[str, Any]:
        """Получает статистику по автомобилям: уникальные марки, модели, количество"""
        from sqlalchemy import func, distinct
        
        # Количество новых автомобилей
        new_cars_count = self.db.query(func.count(Car.id)).scalar() or 0
        
        # Количество подержанных автомобилей
        used_cars_count = self.db.query(func.count(UsedCar.id)).scalar() or 0
        
        # Уникальные марки (новые)
        new_marks = self.db.query(distinct(Car.mark)).filter(Car.mark.isnot(None), Car.mark != '').all()
        new_marks_list = sorted([m[0] for m in new_marks if m[0]])
        
        # Уникальные марки (подержанные)
        used_marks = self.db.query(distinct(UsedCar.mark)).filter(UsedCar.mark.isnot(None), UsedCar.mark != '').all()
        used_marks_list = sorted([m[0] for m in used_marks if m[0]])
        
        # Объединенный список уникальных марок (все)
        all_marks = sorted(list(set(new_marks_list + used_marks_list)))
        
        # Уникальные модели (новые)
        new_models = self.db.query(distinct(Car.model)).filter(Car.model.isnot(None), Car.model != '').all()
        new_models_list = sorted([m[0] for m in new_models if m[0]])
        
        # Уникальные модели (подержанные)
        used_models = self.db.query(distinct(UsedCar.model)).filter(UsedCar.model.isnot(None), UsedCar.model != '').all()
        used_models_list = sorted([m[0] for m in used_models if m[0]])
        
        # Объединенный список уникальных моделей (все)
        all_models = sorted(list(set(new_models_list + used_models_list)))
        
        return {
            "new_cars_count": new_cars_count,
            "used_cars_count": used_cars_count,
            "total_cars_count": new_cars_count + used_cars_count,
            "unique_marks": all_marks,
            "unique_models": all_models,
            "new_marks": new_marks_list,
            "used_marks": used_marks_list,
            "new_models": new_models_list,
            "used_models": used_models_list,
        }

    # Точный поиск по VIN
    def get_car_by_vin(self, vin: str) -> Optional[Car]:
        """Получает новый автомобиль по VIN"""
        # Нормализация VIN (удаление пробелов, приведение к верхнему регистру)
        normalized_vin = vin.strip().upper().replace(" ", "")
        return self.db.query(Car).filter(Car.vin == normalized_vin).first()

    def get_used_car_by_vin(self, vin: str) -> Optional[UsedCar]:
        """Получает подержанный автомобиль по VIN"""
        # Нормализация VIN (удаление пробелов, приведение к верхнему регистру)
        normalized_vin = vin.strip().upper().replace(" ", "")
        return self.db.query(UsedCar).filter(UsedCar.vin == normalized_vin).first()
    
    def search_cars_by_vin_partial(self, vin: str, limit: int = 5) -> List[Car]:
        """Поиск новых автомобилей по частичному совпадению VIN"""
        normalized_vin = vin.strip().upper().replace(" ", "")
        return self.db.query(Car).filter(Car.vin.like(f"%{normalized_vin}%")).limit(limit).all()
    
    def search_used_cars_by_vin_partial(self, vin: str, limit: int = 5) -> List[UsedCar]:
        """Поиск подержанных автомобилей по частичному совпадению VIN"""
        normalized_vin = vin.strip().upper().replace(" ", "")
        return self.db.query(UsedCar).filter(UsedCar.vin.like(f"%{normalized_vin}%")).limit(limit).all()
    
    def search_used_cars_for_rag(self, query: str, limit: int = 5) -> List[UsedCar]:
        """Поиск подержанных автомобилей для RAG"""
        search_filter = or_(
            UsedCar.mark.ilike(f"%{query}%"),
            UsedCar.model.ilike(f"%{query}%"),
            UsedCar.city.ilike(f"%{query}%"),
            UsedCar.body_type.ilike(f"%{query}%"),
            UsedCar.fuel_type.ilike(f"%{query}%"),
            UsedCar.gear_box_type.ilike(f"%{query}%")
        )
        return self.db.query(UsedCar).filter(search_filter).limit(limit).all()
