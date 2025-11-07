"""
API для импорта автомобилей из JSON/XML файлов
"""
import logging
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from models import get_db
from models.schemas import (
    ImportAnalysisResponse, ImportSaveRequest, ImportSaveResponse,
    ImportListResponse, MigrateRequest, MigrateResponse, ImportCar, ImportUsedCar
)
from pydantic import BaseModel
from services.import_service import ImportService
from models.database import ImportCar as ImportCarModel, ImportUsedCar as ImportUsedCarModel
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", response_model=ImportAnalysisResponse)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Загружает файл и анализирует его структуру
    """
    try:
        # Определяем тип файла (нечувствительно к регистру)
        filename_lower = file.filename.lower() if file.filename else ""
        
        if filename_lower.endswith(".xml"):
            file_type = "xml"
        elif filename_lower.endswith(".json"):
            file_type = "json"
        else:
            raise HTTPException(status_code=400, detail="Неподдерживаемый формат файла. Используйте JSON или XML")
        
        # Читаем содержимое файла
        content = await file.read()
        
        # Анализируем файл
        import_service = ImportService(db)
        analysis = import_service.analyze_file(content, file_type)
        
        return ImportAnalysisResponse(**analysis)
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке файла: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке файла: {str(e)}")


@router.post("/save", response_model=ImportSaveResponse)
async def save_import(
    file: UploadFile = File(...),
    file_type: str = None,
    car_type: str = "new",
    field_mapping: str = None,  # JSON строка
    db: Session = Depends(get_db)
):
    """
    Сохраняет импортированные данные в таблицы импорта
    """
    try:
        import json
        
        # Определяем тип файла из расширения, если не указан (нечувствительно к регистру)
        if not file_type:
            filename_lower = file.filename.lower() if file.filename else ""
            if filename_lower.endswith(".xml"):
                file_type = "xml"
            else:
                file_type = "json"
        
        # Парсим field_mapping из JSON строки
        if field_mapping:
            try:
                field_mapping_dict = json.loads(field_mapping)
            except:
                field_mapping_dict = {}
        else:
            field_mapping_dict = {}
        
        # Читаем содержимое файла
        content = await file.read()
        
        # Сохраняем импорт
        import_service = ImportService(db)
        result = import_service.save_import(
            content,
            file_type,
            field_mapping_dict,
            car_type
        )
        
        return ImportSaveResponse(**result)
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении импорта: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при сохранении импорта: {str(e)}")


@router.get("/list", response_model=ImportListResponse)
async def get_import_list(
    skip: int = 0,
    limit: int = 100,
    car_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Получает список импортированных автомобилей
    """
    try:
        if car_type == "new" or car_type is None:
            cars = db.query(ImportCarModel).offset(skip).limit(limit).all()
            total = db.query(ImportCarModel).count()
        else:
            cars = []
            total = 0
                
        if car_type == "used" or car_type is None:
            used_cars = db.query(ImportUsedCarModel).offset(skip).limit(limit).all()
            total_used = db.query(ImportUsedCarModel).count()
        else:
            used_cars = []
            total_used = 0
        
        # Конвертируем SQLAlchemy модели в Pydantic схемы
        from models.schemas import ImportCar, ImportUsedCar
        
        cars_list = []
        for c in cars:
            car_dict = {col.name: getattr(c, col.name) for col in ImportCarModel.__table__.columns}
            cars_list.append(ImportCar(**car_dict))
        
        used_cars_list = []
        for c in used_cars:
            used_car_dict = {col.name: getattr(c, col.name) for col in ImportUsedCarModel.__table__.columns}
            used_cars_list.append(ImportUsedCar(**used_car_dict))
        
        return ImportListResponse(
            cars=cars_list,
            used_cars=used_cars_list,
            total=total,
            total_used=total_used,
            skip=skip,
            limit=limit
        )
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка импорта: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при получении списка: {str(e)}")


@router.post("/migrate", response_model=MigrateResponse)
async def migrate_data(
    request: MigrateRequest,
    db: Session = Depends(get_db)
):
    """
    Мигрирует данные из импортных таблиц в основные таблицы
    """
    try:
        from models.database import (
            Car, UsedCar, CarPicture, UsedCarPicture,
            CarOption, CarOptionsGroup
        )
        from services.elasticsearch_agent_service import ElasticSearchAgentService
        
        migrated_cars = 0
        migrated_used_cars = 0
        migrated_pictures = 0
        migrated_options = 0
        deleted_old_cars = 0
        deleted_old_used_cars = 0
        errors = []
        
        # Удаляем старые данные, если нужно
        if request.delete_old:
            if request.car_type == "new" or request.car_type is None:
                # Удаляем старые фотографии и опции
                db.query(CarPicture).delete()
                db.query(CarOption).delete()
                db.query(CarOptionsGroup).delete()
                deleted_old_cars = db.query(Car).delete()
                db.commit()
            
            if request.car_type == "used" or request.car_type is None:
                deleted_old_used_cars = db.query(UsedCarPicture).delete()
                db.query(UsedCar).delete()
                db.commit()
        
        # Мигрируем новые автомобили
        if request.car_type == "new" or request.car_type is None:
            import_cars = db.query(ImportCarModel).filter(
                ImportCarModel.import_status == "imported"
            ).all()
            
            for import_car in import_cars:
                try:
                    # Создаем новый Car из ImportCar
                    car_data = {}
                    for column in ImportCarModel.__table__.columns:
                        if column.name not in ['id', 'import_status', 'import_source', 
                                              'import_error', 'imported_at', 'migrated_at',
                                              'created_at', 'updated_at']:
                            value = getattr(import_car, column.name, None)
                            if value is not None:
                                car_data[column.name] = value
                    
                    car = Car(**car_data)
                    db.add(car)
                    db.flush()
                    migrated_cars += 1
                    
                    # Мигрируем фотографии
                    import_pictures = import_car.pictures
                    for import_pic in import_pictures:
                        pic = CarPicture(
                            car_id=car.id,
                            url=import_pic.url,
                            type=import_pic.type,
                            seqno=import_pic.seqno
                        )
                        db.add(pic)
                        migrated_pictures += 1
                    
                    # Мигрируем опции
                    import_options = import_car.options
                    for import_option in import_options:
                        option = CarOption(
                            car_id=car.id,
                            code=import_option.code,
                            description=import_option.description,
                            options_group_id=None  # Можно добавить логику для групп
                        )
                        db.add(option)
                        migrated_options += 1
                    
                    # Обновляем статус импорта
                    import_car.import_status = "migrated"
                    import_car.migrated_at = datetime.now()
                    
                except Exception as e:
                    error_msg = f"Ошибка при миграции автомобиля {import_car.id}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    import_car.import_status = "error"
                    import_car.import_error = error_msg
        
        # Мигрируем подержанные автомобили
        if request.car_type == "used" or request.car_type is None:
            import_used_cars = db.query(ImportUsedCarModel).filter(
                ImportUsedCarModel.import_status == "imported"
            ).all()
            
            for import_used_car in import_used_cars:
                try:
                    # Создаем новый UsedCar из ImportUsedCar
                    used_car_data = {}
                    for column in ImportUsedCarModel.__table__.columns:
                        if column.name not in ['id', 'import_status', 'import_source',
                                              'import_error', 'imported_at', 'migrated_at',
                                              'created_at', 'updated_at']:
                            value = getattr(import_used_car, column.name, None)
                            if value is not None:
                                used_car_data[column.name] = value
                    
                    used_car = UsedCar(**used_car_data)
                    db.add(used_car)
                    db.flush()
                    migrated_used_cars += 1
                    
                    # Мигрируем фотографии
                    import_pictures = import_used_car.pictures
                    for import_pic in import_pictures:
                        pic = UsedCarPicture(
                            used_car_id=used_car.id,
                            url=import_pic.url,
                            type=import_pic.type,
                            seqno=import_pic.seqno
                        )
                        db.add(pic)
                        migrated_pictures += 1
                    
                    # Обновляем статус импорта
                    import_used_car.import_status = "migrated"
                    import_used_car.migrated_at = datetime.now()
                    
                except Exception as e:
                    error_msg = f"Ошибка при миграции подержанного автомобиля {import_used_car.id}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    import_used_car.import_status = "error"
                    import_used_car.import_error = error_msg
        
        db.commit()
        
        # Обновляем эмбеддинги и индексы Elasticsearch
        try:
            from services.elasticsearch_agent_service import ElasticSearchAgentService
            # Здесь можно добавить логику обновления Elasticsearch
            # Например, переиндексация всех автомобилей
            agent = ElasticSearchAgentService.get_agent("bert_spacy")
            if agent:
                # Можно вызвать переиндексацию
                logger.info("Elasticsearch агент найден, но переиндексация требует дополнительной реализации")
        except ImportError:
            logger.warning("Elasticsearch агент не доступен")
        except Exception as e:
            logger.warning(f"Не удалось обновить Elasticsearch: {e}")
        
        return MigrateResponse(
            success=True,
            migrated_cars=migrated_cars,
            migrated_used_cars=migrated_used_cars,
            migrated_pictures=migrated_pictures,
            migrated_options=migrated_options,
            deleted_old_cars=deleted_old_cars,
            deleted_old_used_cars=deleted_old_used_cars,
            errors=errors
        )
        
    except Exception as e:
        logger.error(f"Ошибка при миграции данных: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при миграции: {str(e)}")


class DeleteImportRequest(BaseModel):
    car_ids: List[int] = []
    used_car_ids: List[int] = []


class DeleteImportResponse(BaseModel):
    success: bool
    deleted_cars: int = 0
    deleted_used_cars: int = 0
    deleted_pictures: int = 0
    deleted_options: int = 0
    message: str


@router.delete("/delete", response_model=DeleteImportResponse)
async def delete_import_records(
    request: DeleteImportRequest,
    db: Session = Depends(get_db)
):
    """
    Удаляет импортированные записи (все или выбранные)
    """
    try:
        deleted_cars = 0
        deleted_used_cars = 0
        deleted_pictures = 0
        deleted_options = 0
        
        # Удаляем новые автомобили
        if request.car_ids:
            # Удаляем выбранные автомобили
            cars_to_delete = db.query(ImportCarModel).filter(ImportCarModel.id.in_(request.car_ids)).all()
            for car in cars_to_delete:
                # Удаляем связанные фотографии
                from models.database import ImportCarPicture
                pictures = db.query(ImportCarPicture).filter(ImportCarPicture.car_id == car.id).all()
                for pic in pictures:
                    db.delete(pic)
                    deleted_pictures += 1
                
                # Удаляем связанные опции
                from models.database import ImportCarOption
                options = db.query(ImportCarOption).filter(ImportCarOption.car_id == car.id).all()
                for opt in options:
                    db.delete(opt)
                    deleted_options += 1
                
                db.delete(car)
                deleted_cars += 1
        else:
            # Удаляем все новые автомобили
            from models.database import ImportCarPicture, ImportCarOption
            all_cars = db.query(ImportCarModel).all()
            for car in all_cars:
                # Удаляем связанные фотографии
                pictures = db.query(ImportCarPicture).filter(ImportCarPicture.car_id == car.id).all()
                for pic in pictures:
                    db.delete(pic)
                    deleted_pictures += 1
                
                # Удаляем связанные опции
                options = db.query(ImportCarOption).filter(ImportCarOption.car_id == car.id).all()
                for opt in options:
                    db.delete(opt)
                    deleted_options += 1
                
                db.delete(car)
                deleted_cars += 1
        
        # Удаляем подержанные автомобили
        if request.used_car_ids:
            # Удаляем выбранные автомобили
            used_cars_to_delete = db.query(ImportUsedCarModel).filter(ImportUsedCarModel.id.in_(request.used_car_ids)).all()
            for car in used_cars_to_delete:
                # Удаляем связанные фотографии
                from models.database import ImportUsedCarPicture
                pictures = db.query(ImportUsedCarPicture).filter(ImportUsedCarPicture.car_id == car.id).all()
                for pic in pictures:
                    db.delete(pic)
                    deleted_pictures += 1
                
                # Удаляем связанные опции
                from models.database import ImportCarOption
                options = db.query(ImportCarOption).filter(ImportCarOption.car_id == car.id).all()
                for opt in options:
                    db.delete(opt)
                    deleted_options += 1
                
                db.delete(car)
                deleted_used_cars += 1
        else:
            # Удаляем все подержанные автомобили
            from models.database import ImportUsedCarPicture, ImportCarOption
            all_used_cars = db.query(ImportUsedCarModel).all()
            for car in all_used_cars:
                # Удаляем связанные фотографии
                pictures = db.query(ImportUsedCarPicture).filter(ImportUsedCarPicture.car_id == car.id).all()
                for pic in pictures:
                    db.delete(pic)
                    deleted_pictures += 1
                
                # Удаляем связанные опции
                options = db.query(ImportCarOption).filter(ImportCarOption.car_id == car.id).all()
                for opt in options:
                    db.delete(opt)
                    deleted_options += 1
                
                db.delete(car)
                deleted_used_cars += 1
        
        db.commit()
        
        message = f"Удалено автомобилей: новых {deleted_cars}, подержанных {deleted_used_cars}, фотографий {deleted_pictures}, опций {deleted_options}"
        
        return DeleteImportResponse(
            success=True,
            deleted_cars=deleted_cars,
            deleted_used_cars=deleted_used_cars,
            deleted_pictures=deleted_pictures,
            deleted_options=deleted_options,
            message=message
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при удалении импортированных записей: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении: {str(e)}")
