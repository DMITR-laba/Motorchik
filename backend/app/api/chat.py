from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models import get_db
from models.schemas import (
    ChatMessageRequest, ChatMessageResponse, FeedbackRequest,
    ChatCreate, Chat, ChatListResponse, ChatUpdate
)
from services.database_service import DatabaseService
from services.rag_service import RAGService
import redis
import json
from typing import Dict, Any, List, Optional
from app.core.config import settings

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Безопасный fallback для Redis (in-memory), если сервер Redis недоступен
class _MemoryRedis:
    def __init__(self):
        self._kv: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}

    def get(self, key: str):
        return self._kv.get(key)

    def set(self, key: str, value: str):
        self._kv[key] = str(value)
        return True

    def rpush(self, key: str, value: str):
        self._lists.setdefault(key, []).append(value)
        return True

    def lrange(self, key: str, start: int, end: int):
        lst = self._lists.get(key, [])
        # Redis lrange end inclusive; -1 means end of list
        if end == -1:
            end = len(lst) - 1
        return lst[start:end+1]


def _init_redis_client():
    try:
        client = redis.Redis(host=settings.redis_host, port=settings.redis_port, db=settings.redis_db, decode_responses=True)
        # Ленивая проверка соединения
        client.ping()
        return client
    except Exception:
        return _MemoryRedis()


redis_client = _init_redis_client()


def _session_key(user_id: str, session_id: int) -> str:
    return f"chat:history:{user_id}:{session_id}"


def _current_session_id(user_id: str) -> int:
    cur = redis_client.get(f"chat:current:{user_id}")
    if cur is None:
        # инициализируем первую сессию
        redis_client.set(f"chat:current:{user_id}", 1)
        redis_client.rpush(f"chat:sessions:{user_id}", 1)
        return 1
    return int(cur)


def _start_new_session(user_id: str) -> int:
    cur = _current_session_id(user_id)
    new_id = cur + 1
    redis_client.set(f"chat:current:{user_id}", new_id)
    redis_client.rpush(f"chat:sessions:{user_id}", new_id)
    return new_id


def _get_chat_history(user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Получает историю диалога из Redis (до limit последних сообщений)"""
    try:
        sid = _current_session_id(user_id)
        history_key = _session_key(user_id, sid)
        items = redis_client.lrange(history_key, -limit, -1)  # Последние N сообщений
        history = []
        for item in items:
            try:
                history.append(json.loads(item))
            except Exception:
                continue
        return history
    except Exception:
        return []


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    request: ChatMessageRequest,
    db: Session = Depends(get_db)
):
    """
    Отправляет сообщение в чат и получает ответ от AI
    """
    try:
        db_service = DatabaseService(db)
        
        # Определяем или создаем чат
        chat_id = request.chat_id
        if not chat_id:
            # Создаем новый чат
            chat = db_service.create_chat(user_id=request.user_id, title=None)
            chat_id = chat.id
        
        # Обновляем updated_at чата
        from models.database import Chat
        from datetime import datetime
        chat = db_service.get_chat(chat_id, request.user_id)
        if chat:
            chat.updated_at = datetime.utcnow()
            db.commit()
        
        # Если пришел готовый ответ от SQL-агента, сохраняем его напрямую
        if request.sql_agent_response:
            import json
            import time
            
            # Убеждаемся, что sources_data имеет правильную структуру
            sql_sources_data = request.sources_data or {}
            if not isinstance(sql_sources_data, dict):
                sql_sources_data = {}
            # Убеждаемся, что все поля присутствуют
            if "cars" not in sql_sources_data:
                sql_sources_data["cars"] = []
            if "articles" not in sql_sources_data:
                sql_sources_data["articles"] = []
            if "documents" not in sql_sources_data:
                sql_sources_data["documents"] = []
            
            # Загружаем полные объекты автомобилей из sources_data для передачи в ответ
            # Это нужно, чтобы AI получил все поля автомобилей для формирования ответа
            sql_related_cars = []
            sql_related_used_cars = []
            
            if sql_sources_data.get("cars"):
                for car_data in sql_sources_data["cars"]:
                    if isinstance(car_data, dict):
                        car_id = car_data.get("id")
                        if car_id:
                            # Проверяем, есть ли поле mileage - если есть, это used_car
                            if car_data.get("mileage") is not None:
                                used_car = db_service.get_used_car(car_id)
                                if used_car:
                                    sql_related_used_cars.append(used_car)
                            else:
                                car = db_service.get_car(car_id)
                                if car:
                                    sql_related_cars.append(car)
                    elif hasattr(car_data, 'id'):
                        # Уже объект Car или UsedCar
                        if hasattr(car_data, 'mileage') and car_data.mileage is not None:
                            sql_related_used_cars.append(car_data)
                        else:
                            sql_related_cars.append(car_data)
            
            # Сохраняем сообщение в БД
            chat_message = db_service.save_chat_message(
                user_id=request.user_id,
                message=request.message,
                response=request.sql_agent_response,
                related_article_ids=[],
                chat_id=chat_id,
                sources_data=sql_sources_data if sql_sources_data else None
            )
            
            # Сохраняем историю в Redis
            sid = _current_session_id(request.user_id)
            history_key = _session_key(request.user_id, sid)
            redis_client.rpush(history_key, json.dumps({
                "q": request.message,
                "a": request.sql_agent_response,
                "ts": time.time()
            }))
            
            return ChatMessageResponse(
                response=request.sql_agent_response,
                related_articles=[],
                related_documents=[],
                related_cars=sql_related_cars,  # Передаем все найденные автомобили со всеми полями
                related_used_cars=sql_related_used_cars,  # Передаем все найденные автомобили со всеми полями
                model_info={},
                message_id=chat_message.id,
                chat_id=chat_id
            )
        
        try:
            rag_service = RAGService(db_service)
        except Exception as e:
            # Если RAGService не может инициализироваться (например, из-за ChromaDB), 
            # возвращаем ошибку с понятным сообщением
            return {
                "response": "Извините, сервис временно недоступен. Попробуйте повторить запрос позже.",
                "error": str(e),
                "sources": []
            }
        
        # Получаем историю диалога (до 5 последних сообщений)
        history = _get_chat_history(request.user_id, limit=5)
        
        # ВАЖНО: Загружаем автомобили из sources_data ДО вызова generate_response,
        # чтобы они попали в контекст для AI
        preloaded_cars_from_sources = []
        preloaded_used_cars_from_sources = []
        
        if request.sources_data and isinstance(request.sources_data, dict):
            cars_data = request.sources_data.get("cars", [])
            print(f"🔍 Получено автомобилей из sources_data: {len(cars_data)}")
            if cars_data:
                for car_data in cars_data:
                    if isinstance(car_data, dict):
                        car_id = car_data.get("id")
                        if car_id:
                            # Определяем тип автомобиля: проверяем type, mileage или другие признаки
                            car_type = car_data.get("type")
                            has_mileage = car_data.get("mileage") is not None
                            
                            # Если явно указан тип
                            if car_type == "used_car" or has_mileage:
                                used_car = db_service.get_used_car(car_id)
                                if used_car:
                                    preloaded_used_cars_from_sources.append(used_car)
                                else:
                                    # Если не нашли в used_cars, пробуем в cars
                                    car = db_service.get_car(car_id)
                                    if car:
                                        preloaded_cars_from_sources.append(car)
                            elif car_type == "car":
                                car = db_service.get_car(car_id)
                                if car:
                                    preloaded_cars_from_sources.append(car)
                                else:
                                    # Если не нашли в cars, пробуем в used_cars
                                    used_car = db_service.get_used_car(car_id)
                                    if used_car:
                                        preloaded_used_cars_from_sources.append(used_car)
                            else:
                                # Пробуем оба варианта, если тип не указан
                                car = db_service.get_car(car_id)
                                if car:
                                    preloaded_cars_from_sources.append(car)
                                else:
                                    used_car = db_service.get_used_car(car_id)
                                    if used_car:
                                        preloaded_used_cars_from_sources.append(used_car)
                    elif hasattr(car_data, 'id'):
                        # Уже объект Car или UsedCar
                        if hasattr(car_data, 'mileage') and car_data.mileage is not None:
                            preloaded_used_cars_from_sources.append(car_data)
                        else:
                            preloaded_cars_from_sources.append(car_data)
        
        print(f"✅ Предзагружено автомобилей для контекста: новых={len(preloaded_cars_from_sources)}, подержанных={len(preloaded_used_cars_from_sources)}")
        
        # Если включен интеллектуальный поиск, используем IntelligentSearchService
        if request.use_intelligent_search:
            try:
                from services.intelligent_search_service import IntelligentSearchService
                from services.dialog_state_service import DialogStateService
                from app.api.search_es import _extract_filters_from_text
                
                print("🔍 Используется интеллектуальный поиск")
                
                # Извлекаем фильтры из запроса
                filters = _extract_filters_from_text(request.message)
                
                # Получаем контекст диалога
                dialogue_context = "\n".join([f"Пользователь: {h.get('q', '')}\nАссистент: {h.get('a', '')}" for h in history])
                
                # Выполняем интеллектуальный поиск с поддержкой SQL агента
                intelligent_search = IntelligentSearchService(db_session=db)
                # Пробуем сначала SQL агент, если запрос подходит для SQL
                use_sql_agent = len(filters) > 0 or any(keyword in request.message.lower() for keyword in ['тойота', 'bmw', 'мерседес', 'ауди', 'тойота', 'бмв', 'марка', 'модель', 'год', 'цена'])
                search_result = await intelligent_search.search_with_intelligence(
                    initial_params={k: v for k, v in filters.items() if v is not None},
                    user_query=request.message,
                    dialogue_context=dialogue_context,
                    use_sql_agent=use_sql_agent
                )
                
                # Если найдены результаты, загружаем полные объекты автомобилей
                if search_result.get("success") and search_result.get("results"):
                    hits = search_result.get("results", [])
                    print(f"✅ Интеллектуальный поиск нашел {len(hits)} автомобилей")
                    
                    for hit in hits:
                        source = hit.get("_source", {})
                        car_id = source.get("id")
                        if car_id:
                            # Определяем тип по наличию mileage
                            has_mileage = source.get("mileage") is not None
                            
                            if has_mileage:
                                used_car = db_service.get_used_car(car_id)
                                if used_car and used_car not in preloaded_used_cars_from_sources:
                                    preloaded_used_cars_from_sources.append(used_car)
                            else:
                                car = db_service.get_car(car_id)
                                if car and car not in preloaded_cars_from_sources:
                                    preloaded_cars_from_sources.append(car)
                    
                    # Сохраняем критерии поиска в состояние диалога
                    dialog_state = DialogStateService(request.user_id)
                    dialog_state.update_criteria(filters)
                    
                    # Сохраняем результаты поиска
                    dialog_state.set_last_shown_cars([
                        {
                            "id": hit.get("_source", {}).get("id"),
                            "mark": hit.get("_source", {}).get("mark"),
                            "model": hit.get("_source", {}).get("model")
                        }
                        for hit in hits[:10]
                    ])
                
                # Добавляем информацию об ослаблении фильтров в sources_data
                if search_result.get("relaxation_applied"):
                    if not request.sources_data:
                        request.sources_data = {}
                    request.sources_data["intelligent_search"] = {
                        "relaxation_applied": True,
                        "relaxation_steps": search_result.get("relaxation_steps", 0),
                        "relaxed_params": search_result.get("relaxed_params"),
                        "original_params": search_result.get("original_params")
                    }
                
                # Добавляем рекомендации, если есть
                if search_result.get("recommendations"):
                    if not request.sources_data:
                        request.sources_data = {}
                    request.sources_data["recommendations"] = search_result.get("recommendations")
                    
            except Exception as e:
                print(f"⚠️ Ошибка интеллектуального поиска: {e}, используем обычный поиск")
        
        # Передаем предзагруженные автомобили в generate_response
        result = await rag_service.generate_response(
            request.message, 
            request.user_id, 
            chat_history=history,
            preloaded_cars=preloaded_cars_from_sources,
            preloaded_used_cars=preloaded_used_cars_from_sources,
            deep_thinking_enabled=request.deep_thinking_enabled or False
        )
        
        # Получаем уточняющие вопросы и проактивные предложения через CarDealerAssistantService
        clarifying_questions = []
        proactive_suggestions = []
        finance_calculation = None
        
        try:
            from services.car_dealer_assistant_service import CarDealerAssistantService
            # Используем chat_id как session_id для ассистента
            session_id = None
            if request.chat_id:
                session_id = request.chat_id
            elif chat_id:
                session_id = chat_id
            
            assistant = CarDealerAssistantService(
                user_id=request.user_id,
                session_id=session_id
            )
            
            # Получаем дополнительные данные от ассистента
            assistant_result = await assistant.process_query(request.message)
            
            if assistant_result:
                clarifying_questions = assistant_result.get("clarifying_questions", [])
                proactive_suggestions = assistant_result.get("proactive_suggestions", [])
                finance_calculation = assistant_result.get("finance_calculation")
        except Exception as e:
            print(f"⚠️ Ошибка получения данных от CarDealerAssistantService: {e}")
        
        # Объединяем sources_data из запроса с articles и documents из результата RAG
        combined_sources_data = request.sources_data or {}
        if not isinstance(combined_sources_data, dict):
            combined_sources_data = {}
        
        # Добавляем articles и documents из результата RAG
        if result.get("related_articles"):
            combined_sources_data["articles"] = result.get("related_articles", [])
        if result.get("related_documents"):
            combined_sources_data["documents"] = result.get("related_documents", [])
        # Сохраняем cars из запроса, если они есть
        if "cars" not in combined_sources_data:
            combined_sources_data["cars"] = []
        
        # Добавляем уточняющие вопросы, проактивные предложения и финансовые расчеты
        if clarifying_questions:
            combined_sources_data["clarifying_questions"] = clarifying_questions
        if proactive_suggestions:
            combined_sources_data["proactive_suggestions"] = proactive_suggestions
        if finance_calculation:
            combined_sources_data["finance_calculation"] = finance_calculation
        
        # Загружаем полные объекты автомобилей из sources_data для передачи в ответ
        # Это нужно, чтобы AI получил все поля автомобилей для формирования ответа
        related_cars_from_sources = preloaded_cars_from_sources.copy()
        related_used_cars_from_sources = preloaded_used_cars_from_sources.copy()
        
        # Объединяем автомобили из RAG результата с автомобилями из sources_data
        # Убираем дубликаты по ID
        all_related_cars = result.get("related_cars", [])
        all_related_used_cars = result.get("related_used_cars", [])
        
        # Добавляем автомобили из sources_data, которых еще нет в результатах RAG
        existing_car_ids = {car.id for car in all_related_cars}
        existing_used_car_ids = {car.id for car in all_related_used_cars}
        
        for car in related_cars_from_sources:
            if car.id not in existing_car_ids:
                all_related_cars.append(car)
                existing_car_ids.add(car.id)
        
        for used_car in related_used_cars_from_sources:
            if used_car.id not in existing_used_car_ids:
                all_related_used_cars.append(used_car)
                existing_used_car_ids.add(used_car.id)
        
        # Сохраняем сообщение в БД с объединенными sources_data
        chat_message = db_service.save_chat_message(
            user_id=request.user_id,
            message=request.message,
            response=result["response"],
            related_article_ids=result.get("related_article_ids", []),
            chat_id=chat_id,
            sources_data=combined_sources_data if combined_sources_data else None
        )
        
        # Сохраняем историю в Redis (по сессиям)
        sid = _current_session_id(request.user_id)
        history_key = _session_key(request.user_id, sid)
        redis_client.rpush(history_key, json.dumps({
            "q": request.message,
            "a": result["response"],
            "ts": __import__("time").time()
        }))
        
        return ChatMessageResponse(
            response=result["response"],
            related_articles=result.get("related_articles", []),
            related_documents=result.get("related_documents", []),
            related_cars=all_related_cars,  # Используем объединенный список со всеми полями
            related_used_cars=all_related_used_cars,  # Используем объединенный список со всеми полями
            model_info=result.get("model_info", {}),
            message_id=chat_message.id,
            chat_id=chat_id
        )
    
    except Exception as e:
        # Мягкий фолбэк: не роняем 500, возвращаем вежливый ответ и сохраняем сообщение
        try:
            db_service = DatabaseService(db)
            fallback_text = "Извините, сервис временно недоступен. Попробуйте повторить запрос позже."
            
            # Определяем или создаем чат
            chat_id = request.chat_id
            if not chat_id:
                chat = db_service.create_chat(user_id=request.user_id, title=None)
                chat_id = chat.id
            
            chat_message = db_service.save_chat_message(
                user_id=request.user_id,
                message=request.message,
                response=fallback_text,
                related_article_ids=[],
                chat_id=chat_id,
                sources_data=request.sources_data
            )
            # Сохраняем историю в Redis
            sid = _current_session_id(request.user_id)
            history_key = _session_key(request.user_id, sid)
            redis_client.rpush(history_key, json.dumps({
                "q": request.message,
                "a": fallback_text,
                "ts": __import__("time").time()
            }))
            return ChatMessageResponse(
                response=fallback_text,
                related_articles=[],
                message_id=chat_message.id,
                chat_id=chat_id
            )
        except Exception:
            raise HTTPException(status_code=200, detail="Извините, сервис временно недоступен. Попробуйте повторить запрос позже.")


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    db: Session = Depends(get_db)
):
    """
    Отправляет обратную связь по ответу AI
    """
    try:
        db_service = DatabaseService(db)
        success = db_service.update_feedback(
            message_id=request.message_id,
            feedback=request.feedback,
            comment=request.comment
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Сообщение не найдено")
        
        return {"message": "Обратная связь сохранена"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при сохранении обратной связи: {str(e)}")


@router.get("/history")
async def get_history(user_id: str, session_id: int | None = None):
    """Возвращает историю сообщений текущей или указанной сессии, а также список всех сессий"""
    sid = session_id or _current_session_id(user_id)
    items = redis_client.lrange(_session_key(user_id, sid), 0, -1)
    sessions = [int(x) for x in redis_client.lrange(f"chat:sessions:{user_id}", 0, -1)]
    return {"history": [json.loads(i) for i in items], "current_session": sid, "sessions": sessions}


@router.post("/new_chat")
async def new_chat(user_id: str):
    """Начинает НОВЫЙ чат и сохраняет старые. Возвращает session_id."""
    sid = _start_new_session(user_id)
    return {"ok": True, "session_id": sid}


@router.post("/chats", response_model=Chat)
async def create_chat(
    request: ChatCreate,
    db: Session = Depends(get_db)
):
    """Создает новый чат"""
    db_service = DatabaseService(db)
    chat = db_service.create_chat(user_id=request.user_id, title=request.title)
    chat.message_count = 0
    return chat


@router.get("/chats", response_model=ChatListResponse)
async def get_chats(
    user_id: str,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Получает список чатов пользователя"""
    db_service = DatabaseService(db)
    chats = db_service.get_user_chats(user_id=user_id, skip=skip, limit=limit)
    total = len(db_service.get_user_chats(user_id=user_id, skip=0, limit=10000))  # Получаем общее количество
    return ChatListResponse(chats=chats, total=total)


@router.get("/chats/{chat_id}/messages")
async def get_chat_messages(
    chat_id: int,
    user_id: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Получает сообщения конкретного чата"""
    db_service = DatabaseService(db)
    messages = db_service.get_chat_messages(chat_id=chat_id, user_id=user_id, skip=skip, limit=limit)
    
    # Десериализуем sources_data для каждого сообщения
    messages_data = []
    for msg in messages:
        msg_dict = {
            "id": msg.id,
            "message": msg.message,
            "response": msg.response,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "sources_data": json.loads(msg.sources_data) if msg.sources_data else None
        }
        messages_data.append(msg_dict)
    
    return {"messages": messages_data}


@router.put("/chats/{chat_id}", response_model=Chat)
async def update_chat(
    chat_id: int,
    request: ChatUpdate,
    user_id: str,
    db: Session = Depends(get_db)
):
    """Обновляет чат (например, название)"""
    db_service = DatabaseService(db)
    
    if request.title is not None:
        success = db_service.update_chat_title(chat_id=chat_id, user_id=user_id, title=request.title)
        if not success:
            raise HTTPException(status_code=404, detail="Чат не найден")
    
    chat = db_service.get_chat(chat_id=chat_id, user_id=user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    
    return chat


@router.delete("/chats/{chat_id}")
async def delete_chat(
    chat_id: int,
    user_id: str,
    db: Session = Depends(get_db)
):
    """Удаляет чат и все связанные сообщения"""
    db_service = DatabaseService(db)
    success = db_service.delete_chat(chat_id=chat_id, user_id=user_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Чат не найден")
    
    return {"message": "Чат успешно удален"}

