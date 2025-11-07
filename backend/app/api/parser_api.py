"""
API endpoints для парсера автомобилей с aaa-motors.ru
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, Union
from models import get_db
from models.schemas import (
    ParserStartRequest, 
    ParserStatusResponse, 
    ParsedCar, 
    ParsedCarListResponse
)
from services.parser_service import AAAMotorsParser
from services.ai_parser_service import AIParser
from sqlalchemy import func
from models.database import ParsedCar as ParsedCarModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parser", tags=["parser"])

# Глобальное хранилище для парсеров (в production лучше использовать Redis или БД)
_active_parsers: Dict[str, Union[AAAMotorsParser, 'AIParser']] = {}


def _get_parser_id(user_id: str = "default") -> str:
    """Генерирует ID парсера для пользователя"""
    return f"parser_{user_id}"


@router.post("/start", response_model=ParserStatusResponse)
async def start_parser(
    request: ParserStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: str = "default"
):
    """
    Запускает парсинг автомобилей с aaa-motors.ru
    
    Парсит:
    - Марку
    - Модель
    - Город
    - Характеристики (цена, год, кузов, топливо, коробка, привод, объем, мощность, цвет, пробег)
    - Фотографии
    """
    parser_id = _get_parser_id(user_id)
    
    # Проверяем, не запущен ли уже парсер
    if parser_id in _active_parsers:
        active_parser = _active_parsers[parser_id]
        if active_parser.is_running:
            raise HTTPException(
                status_code=400,
                detail="Парсер уже запущен. Остановите текущий парсер перед запуском нового."
            )
    
    # Создаем парсер (ИИ или базовый)
    logger.info(f"📋 Параметры парсера из запроса:")
    logger.info(f"   - use_ai: {request.use_ai}")
    logger.info(f"   - use_ollama: {request.use_ollama}")
    logger.info(f"   - ollama_model: {request.ollama_model}")
    logger.info(f"   - clear_before: {request.clear_before}")
    
    if request.use_ai:
        parser = AIParser(
            db_session=db,
            base_url=request.base_url,
            ollama_model=request.ollama_model,
            use_ollama=request.use_ollama
        )
        if request.use_ollama:
            logger.info(f"✅ Используется ИИ-парсер с NLP, ML и Ollama (модель: {parser.ollama_model})")
        else:
            logger.info("✅ Используется ИИ-парсер с NLP и ML (без Ollama)")
    else:
        parser = AAAMotorsParser(
            db_session=db,
            base_url=request.base_url
        )
        logger.info("✅ Используется базовый парсер (БЕЗ ИИ)")
    
    # Сохраняем парсер
    _active_parsers[parser_id] = parser
    
    # Запускаем парсинг в фоне
    def run_parser():
        # КРИТИЧЕСКИ ВАЖНО: Создаем новую сессию БД для фонового потока
        # Сессия из FastAPI dependency может не работать корректно в фоновом потоке
        from models import SessionLocal
        background_db = SessionLocal()
        
        try:
            # Создаем новый парсер с новой сессией БД
            if request.use_ai:
                background_parser = AIParser(
                    db_session=background_db,
                    base_url=request.base_url,
                    ollama_model=request.ollama_model,
                    use_ollama=request.use_ollama
                )
            else:
                background_parser = AAAMotorsParser(
                    db_session=background_db,
                    base_url=request.base_url
                )
            
            # Обновляем парсер в глобальном хранилище
            _active_parsers[parser_id] = background_parser
            
            # Логируем параметры парсинга
            logger.info(f"🚀 Запуск парсинга с параметрами:")
            logger.info(f"   - max_pages: {request.max_pages}")
            logger.info(f"   - max_cars: {request.max_cars}")
            logger.info(f"   - delay: {request.delay}")
            logger.info(f"   - clear_before: {request.clear_before}")
            logger.info(f"   - use_ai: {request.use_ai}")
            logger.info(f"   - use_ollama: {request.use_ollama}")
            
            # КРИТИЧЕСКИ ВАЖНО: Убеждаемся что clear_before по умолчанию True
            # Проверяем что параметр действительно передан и не None
            clear_before_value = request.clear_before if hasattr(request, 'clear_before') and request.clear_before is not None else True
            logger.info(f"   ✅ clear_before из запроса: {request.clear_before}")
            logger.info(f"   ✅ clear_before финальное значение: {clear_before_value}")
            print(f"\n{'='*80}")
            print(f"📋 ПАРАМЕТРЫ ПАРСИНГА:")
            print(f"   - clear_before: {clear_before_value}")
            print(f"   - max_pages: {request.max_pages}")
            print(f"   - max_cars: {request.max_cars}")
            print(f"   - use_ai: {request.use_ai}")
            print(f"{'='*80}\n")
            
            # ПРИНУДИТЕЛЬНАЯ ОЧИСТКА ПЕРЕД ПАРСИНГОМ
            if clear_before_value:
                logger.info("🗑️ Принудительная очистка данных перед парсингом...")
                try:
                    deleted_count = background_parser.clear_all_data()
                    logger.info(f"✅ Очистка выполнена: удалено {deleted_count} автомобилей")
                    print(f"✅ Очистка выполнена: удалено {deleted_count} автомобилей\n")
                except Exception as e:
                    logger.error(f"❌ Ошибка при очистке данных: {e}", exc_info=True)
                    print(f"❌ Ошибка при очистке данных: {e}\n")
            
            result = background_parser.parse(
                max_pages=request.max_pages,
                max_cars=request.max_cars,
                delay=request.delay,
                clear_before=False  # Очистка уже выполнена выше, поэтому False
            )
            logger.info(f"✅ Парсинг завершен: {result}")
            print(f"\n{'='*80}")
            print(f"✅ ПАРСИНГ ЗАВЕРШЕН")
            print(f"{'='*80}")
            print(f"Статус: {result.get('status')}")
            print(f"Обработано: {result.get('total_parsed')} автомобилей")
            print(f"Ошибок: {result.get('total_errors')}")
            print(f"NLP извлечений: {result.get('nlp_extractions', 0)}")
            print(f"{'='*80}\n")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка парсинга: {e}", exc_info=True)
        finally:
            # Закрываем сессию БД
            background_db.close()
            # Удаляем парсер после завершения
            if parser_id in _active_parsers:
                del _active_parsers[parser_id]
    
    background_tasks.add_task(run_parser)
    
    return ParserStatusResponse(
        status="running",
        total_parsed=0,
        total_errors=0,
        current_page=0,
        message="Парсинг запущен"
    )


@router.post("/stop")
async def stop_parser(user_id: str = "default"):
    """Останавливает активный парсер"""
    parser_id = _get_parser_id(user_id)
    
    if parser_id not in _active_parsers:
        raise HTTPException(status_code=404, detail="Парсер не найден")
    
    parser = _active_parsers[parser_id]
    parser.stop()
    
    return {"message": "Парсер остановлен"}


@router.get("/status", response_model=ParserStatusResponse)
async def get_parser_status(user_id: str = "default"):
    """Получает статус парсера"""
    parser_id = _get_parser_id(user_id)
    
    if parser_id not in _active_parsers:
        # Проверяем, есть ли сохраненные автомобили
        return ParserStatusResponse(
            status="stopped",
            total_parsed=0,
            total_errors=0,
            current_page=None,
            message="Парсер не запущен"
        )
    
    parser = _active_parsers[parser_id]
    status = parser.get_status()
    
    return ParserStatusResponse(
        status=status["status"],
        total_parsed=status["total_parsed"],
        total_errors=status["total_errors"],
        current_page=status.get("current_page"),
        nlp_extractions=status.get("nlp_extractions", 0),
        ollama_extractions=status.get("ollama_extractions", 0),
        structure_changes_detected=status.get("structure_changes_detected", 0),
        message=f"Обработано {status['total_parsed']} автомобилей, ошибок: {status['total_errors']}"
    )


@router.get("/cars", response_model=ParsedCarListResponse)
async def get_parsed_cars(
    skip: int = 0,
    limit: int = 100,
    mark: Optional[str] = None,
    model: Optional[str] = None,
    city: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Получает список спарсенных автомобилей
    
    Параметры фильтрации:
    - mark: Марка автомобиля
    - model: Модель автомобиля
    - city: Город
    """
    query = db.query(ParsedCarModel)
    
    # Применяем фильтры
    if mark:
        query = query.filter(ParsedCarModel.mark.ilike(f"%{mark}%"))
    if model:
        query = query.filter(ParsedCarModel.model.ilike(f"%{model}%"))
    if city:
        query = query.filter(ParsedCarModel.city.ilike(f"%{city}%"))
    
    # Фильтр только активных
    query = query.filter(ParsedCarModel.is_active == True)
    
    # Получаем общее количество
    total = query.count()
    
    # Применяем пагинацию
    cars = query.order_by(ParsedCarModel.parsed_at.desc()).offset(skip).limit(limit).all()
    
    return ParsedCarListResponse(
        cars=[ParsedCar.model_validate(car) for car in cars],
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/cars/{car_id}", response_model=ParsedCar)
async def get_parsed_car(car_id: int, db: Session = Depends(get_db)):
    """Получает детальную информацию о спарсенном автомобиле"""
    car = db.query(ParsedCarModel).filter(ParsedCarModel.id == car_id).first()
    
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    return ParsedCar.model_validate(car)


@router.delete("/cars/{car_id}")
async def delete_parsed_car(car_id: int, db: Session = Depends(get_db)):
    """Удаляет спарсенный автомобиль"""
    car = db.query(ParsedCarModel).filter(ParsedCarModel.id == car_id).first()
    
    if not car:
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    
    # Мягкое удаление (помечаем как неактивный)
    car.is_active = False
    db.commit()
    
    return {"message": "Автомобиль удален"}


@router.get("/stats")
async def get_parser_stats(db: Session = Depends(get_db)):
    """Получает статистику по спарсенным автомобилям"""
    total_cars = db.query(func.count(ParsedCarModel.id)).filter(
        ParsedCarModel.is_active == True
    ).scalar()
    
    total_by_mark = db.query(
        ParsedCarModel.mark,
        func.count(ParsedCarModel.id).label('count')
    ).filter(
        ParsedCarModel.is_active == True,
        ParsedCarModel.mark.isnot(None)
    ).group_by(ParsedCarModel.mark).all()
    
    total_by_city = db.query(
        ParsedCarModel.city,
        func.count(ParsedCarModel.id).label('count')
    ).filter(
        ParsedCarModel.is_active == True,
        ParsedCarModel.city.isnot(None)
    ).group_by(ParsedCarModel.city).all()
    
    return {
        "total_cars": total_cars or 0,
        "by_mark": [{"mark": mark, "count": count} for mark, count in total_by_mark],
        "by_city": [{"city": city, "count": count} for city, count in total_by_city]
    }

