from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from models import get_db
from models.schemas import (
    Car, UsedCar, CarListResponse, UsedCarListResponse,
    CarPicture, UsedCarPicture, CarOption, CarOptionsGroup
)
from services.database_service import DatabaseService
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/cars", tags=["cars"])


@router.get("/", response_model=CarListResponse)
async def get_cars(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    mark: Optional[str] = None,
    model: Optional[str] = None,
    city: Optional[str] = None,
    fuel_type: Optional[str] = None,
    body_type: Optional[str] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user)
):
    """Получает список новых автомобилей с фильтрацией"""
    db_service = DatabaseService(db)
    skip = (page - 1) * size
    cars, total = db_service.get_cars(
        skip=skip,
        limit=size,
        search=search,
        mark=mark,
        model=model,
        city=city,
        fuel_type=fuel_type,
        body_type=body_type,
        min_year=min_year,
        max_year=max_year
    )
    return CarListResponse(cars=cars, total=total, page=page, size=size)


@router.get("/{car_id}", response_model=Car)
async def get_car(
    car_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user)
):
    """Получает информацию о новом автомобиле"""
    db_service = DatabaseService(db)
    car = db_service.get_car(car_id)
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Автомобиль не найден")
    return car


@router.get("/{car_id}/pictures", response_model=List[CarPicture])
async def get_car_pictures(
    car_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user)
):
    """Получает фотографии нового автомобиля"""
    from models.database import CarPicture
    pictures = db.query(CarPicture).filter(CarPicture.car_id == car_id).order_by(CarPicture.seqno).all()
    return pictures


@router.get("/{car_id}/options", response_model=List[CarOption])
async def get_car_options(
    car_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user)
):
    """Получает опции нового автомобиля"""
    from models.database import CarOption
    options = db.query(CarOption).filter(CarOption.car_id == car_id).all()
    return options


@router.get("/{car_id}/options-groups", response_model=List[CarOptionsGroup])
async def get_car_options_groups(
    car_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user)
):
    """Получает группы опций нового автомобиля"""
    from models.database import CarOptionsGroup
    groups = db.query(CarOptionsGroup).filter(CarOptionsGroup.car_id == car_id).all()
    return groups


# ============================================================================
# ЭНДПОИНТЫ ДЛЯ ПОДЕРЖАННЫХ АВТОМОБИЛЕЙ
# ============================================================================

@router.get("/used/", response_model=UsedCarListResponse)
async def get_used_cars(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    mark: Optional[str] = None,
    model: Optional[str] = None,
    city: Optional[str] = None,
    fuel_type: Optional[str] = None,
    body_type: Optional[str] = None,
    min_mileage: Optional[int] = None,
    max_mileage: Optional[int] = None,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user)
):
    """Получает список подержанных автомобилей с фильтрацией"""
    db_service = DatabaseService(db)
    skip = (page - 1) * size
    used_cars, total = db_service.get_used_cars(
        skip=skip,
        limit=size,
        search=search,
        mark=mark,
        model=model,
        city=city,
        fuel_type=fuel_type,
        body_type=body_type,
        min_mileage=min_mileage,
        max_mileage=max_mileage
    )
    return UsedCarListResponse(used_cars=used_cars, total=total, page=page, size=size)


@router.get("/used/{used_car_id}", response_model=UsedCar)
async def get_used_car(
    used_car_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user)
):
    """Получает информацию о подержанном автомобиле"""
    db_service = DatabaseService(db)
    used_car = db_service.get_used_car(used_car_id)
    if not used_car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Подержанный автомобиль не найден")
    return used_car


@router.get("/used/{used_car_id}/pictures", response_model=List[UsedCarPicture])
async def get_used_car_pictures(
    used_car_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user)
):
    """Получает фотографии подержанного автомобиля"""
    from models.database import UsedCarPicture
    pictures = db.query(UsedCarPicture).filter(
        UsedCarPicture.used_car_id == used_car_id
    ).order_by(UsedCarPicture.seqno).all()
    return pictures



