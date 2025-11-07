from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.inspection import inspect as sql_inspect
from typing import List, Dict, Any
import httpx
import os
import json
from datetime import datetime
from models import get_db
from models.schemas import (
    AIConnectionTest, AIModelSettings, OllamaModel,
    SQLAgentQuestionRequest, SQLAgentResponse, SQLAgentToggleRequest
)
from services.ai_service import AIService
from services.sql_agent_service import SQLAgentService
from services.elasticsearch_service import ElasticsearchService
from app.api.search_es import _extract_filters_from_text
from app.api.auth import require_admin

router = APIRouter()

# Файл для хранения состояния SQL-агента
SQL_AGENT_SETTINGS_FILE = "sql_agent_settings.json"

def _load_sql_agent_settings() -> Dict[str, Any]:
    """Загружает настройки SQL-агента"""
    try:
        if os.path.exists(SQL_AGENT_SETTINGS_FILE):
            with open(SQL_AGENT_SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
                # Добавляем значения по умолчанию для новых полей
                if "es_fallback_enabled" not in settings:
                    settings["es_fallback_enabled"] = False
                if "es_model" not in settings:
                    settings["es_model"] = "bert_spacy"
                return settings
    except Exception:
        pass
    return {
        "enabled": False,
        "es_fallback_enabled": False,
        "es_model": "bert_spacy"
    }

def _save_sql_agent_settings(settings: Dict[str, Any]):
    """Сохраняет настройки SQL-агента"""
    try:
        with open(SQL_AGENT_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise Exception(f"Ошибка сохранения настроек: {str(e)}")

def _relax_filters_for_alternatives(filters: Dict[str, Any], question: str) -> Dict[str, Any]:
    """
    Упрощает фильтры для поиска альтернатив.
    Убирает строгие ограничения, оставляя только основные критерии.
    """
    relaxed = {}
    question_lower = question.lower()
    
    # Сохраняем основные критерии (марка, модель, тип кузова, топливо)
    if filters.get("mark"):
        relaxed["mark"] = filters["mark"]
    if filters.get("model"):
        relaxed["model"] = filters["model"]
    
    # Ослабляем фильтры по цене (расширяем диапазон на 20-30%)
    if filters.get("max_price"):
        relaxed["max_price"] = int(filters["max_price"] * 1.3)  # Увеличиваем на 30%
    if filters.get("min_price"):
        relaxed["min_price"] = max(0, int(filters["min_price"] * 0.8))  # Уменьшаем на 20%
    
    # Ослабляем фильтры по году (расширяем диапазон)
    if filters.get("min_year"):
        relaxed["min_year"] = max(2000, filters["min_year"] - 2)  # Уменьшаем на 2 года
    if filters.get("max_year"):
        relaxed["max_year"] = min(2030, filters["max_year"] + 2)  # Увеличиваем на 2 года
    
    # Ослабляем фильтры по пробегу (увеличиваем максимальный пробег на 30%)
    if filters.get("max_mileage"):
        relaxed["max_mileage"] = int(filters["max_mileage"] * 1.3)
    
    # Сохраняем тип кузова и топливо, если они упоминаются в запросе
    if "седан" in question_lower or "sedan" in question_lower:
        relaxed["body_type"] = "Седан"
    elif "внедорожник" in question_lower or "suv" in question_lower:
        relaxed["body_type"] = "Внедорожник"
    elif "кроссовер" in question_lower or "crossover" in question_lower:
        relaxed["body_type"] = "Кроссовер"
    
    if "бензин" in question_lower or "petrol" in question_lower:
        relaxed["fuel_type"] = "бензин"
    elif "дизель" in question_lower or "diesel" in question_lower:
        relaxed["fuel_type"] = "дизель"
    
    # Убираем строгие фильтры (опции, цвет, город и т.д.)
    # Они могут быть слишком ограничивающими
    
    return relaxed

@router.post("/test-connection")
async def test_connection(
    request: AIConnectionTest,
    db: Session = Depends(get_db)
):
    """Тестирование подключения к внешнему API"""
    try:
        ai_service = AIService()
        result = await ai_service.test_api_connection(request.service, request.key)
        return {"success": True, "message": "Подключение успешно", "details": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка подключения: {str(e)}")

@router.get("/ollama/models")
async def get_ollama_models(db: Session = Depends(get_db), _: object = Depends(require_admin)):
    """Получение списка моделей Ollama"""
    try:
        ai_service = AIService()
        models = await ai_service.get_ollama_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения моделей: {str(e)}")

@router.post("/ollama/pull")
async def pull_ollama_model(
    model_name: str,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Загрузка модели в Ollama"""
    try:
        ai_service = AIService()
        result = await ai_service.pull_ollama_model(model_name)
        return {"success": True, "message": f"Модель {model_name} загружается", "details": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка загрузки модели: {str(e)}")

@router.get("/ollama/status")
async def get_ollama_status(db: Session = Depends(get_db)):
    """Проверка статуса Ollama"""
    try:
        ai_service = AIService()
        status = await ai_service.check_ollama_status()
        return {"status": status}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка проверки статуса: {str(e)}")

@router.post("/settings/save")
async def save_ai_settings(
    settings: AIModelSettings,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Сохранение настроек AI"""
    try:
        ai_service = AIService()
        # Преобразуем Pydantic модель в словарь
        settings_dict = {
            "response_model": settings.response_model,
            "embedding_model": settings.embedding_model,
            "api_service": settings.api_service,
            "api_key": settings.api_key,
            "updated_at": datetime.now().isoformat()
        }
        result = await ai_service.save_settings_dict(settings_dict)
        return {"success": True, "message": "Настройки сохранены", "settings": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка сохранения настроек: {str(e)}")

@router.get("/settings")
async def get_ai_settings(db: Session = Depends(get_db), _: object = Depends(require_admin)):
    """Получение текущих настроек AI"""
    try:
        ai_service = AIService()
        settings = await ai_service.get_settings()
        return {"settings": settings}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения настроек: {str(e)}")

@router.post("/test-model")
async def test_model(
    model_name: str,
    model_type: str,  # "response" или "embedding"
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Тестирование конкретной модели"""
    try:
        ai_service = AIService()
        
        if model_type == "response":
            result = await ai_service.test_response_model(model_name)
        elif model_type == "embedding":
            result = await ai_service.test_embedding_model(model_name)
        else:
            raise HTTPException(status_code=400, detail="Неверный тип модели")
        
        return {"success": True, "message": f"Модель {model_name} работает корректно", "details": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка тестирования модели: {str(e)}")

# ============================================================================
# SQL-АГЕНТ ЭНДПОИНТЫ
# ============================================================================

@router.get("/sql-agent/status")
async def get_sql_agent_status(db: Session = Depends(get_db)):
    """Получение статуса SQL-агента"""
    try:
        settings = _load_sql_agent_settings()
        return {
            "enabled": settings.get("enabled", False),
            "es_fallback_enabled": settings.get("es_fallback_enabled", False),
            "es_model": settings.get("es_model", "bert_spacy")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения статуса: {str(e)}")

@router.post("/sql-agent/settings/fallback")
async def update_sql_agent_fallback_settings(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Обновление настроек fallback для SQL-агента"""
    try:
        settings = _load_sql_agent_settings()
        if "es_fallback_enabled" in request:
            settings["es_fallback_enabled"] = request["es_fallback_enabled"]
        if "es_model" in request:
            settings["es_model"] = request["es_model"]
        _save_sql_agent_settings(settings)
        return {
            "success": True,
            "message": "Настройки fallback обновлены",
            "settings": {
                "es_fallback_enabled": settings.get("es_fallback_enabled", False),
                "es_model": settings.get("es_model", "bert_spacy")
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка обновления настроек: {str(e)}")

@router.post("/sql-agent/toggle")
async def toggle_sql_agent(
    request: SQLAgentToggleRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Включение/выключение SQL-агента"""
    try:
        settings = _load_sql_agent_settings()
        settings["enabled"] = request.enabled
        _save_sql_agent_settings(settings)
        return {
            "success": True,
            "message": f"SQL-агент {'включен' if request.enabled else 'выключен'}",
            "enabled": request.enabled
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка изменения статуса: {str(e)}")

@router.post("/sql-agent/query", response_model=SQLAgentResponse)
async def query_sql_agent(
    request: SQLAgentQuestionRequest,
    db: Session = Depends(get_db)
):
    """Обработка вопроса через SQL-агента
    
    ВАЖНО: SQL-агент работает изолированно и НЕ использует:
    - RAG сервис
    - Elasticsearch
    - Document service
    - Другие сервисы для поиска информации
    """
    try:
        # Проверяем, включен ли SQL-агент
        settings = _load_sql_agent_settings()
        if not settings.get("enabled", False):
            return SQLAgentResponse(
                success=False,
                error="SQL-агент выключен. Включите его в настройках AI."
            )
        
        print(f"🔍 SQL-агент обрабатывает запрос: {request.question}")
        if settings.get("es_fallback_enabled", False):
            print("✅ Fallback на Elasticsearch включен - будет использован при ошибках SQL-агента")
        
        sql_agent = SQLAgentService(db)
        
        if request.generate_only:
            # Только генерация SQL без выполнения
            result = await sql_agent.generate_sql_from_natural_language(request.question)
            return SQLAgentResponse(
                success=result.get("success", False),
                sql=result.get("sql"),
                error=result.get("error")
            )
        else:
            # Полный цикл: генерация + выполнение
            # Отключаем перегенерацию SQL при 0 результатах, чтобы сразу использовать Elasticsearch
            result = await sql_agent.process_question(request.question, try_alternative_on_zero=False)
            
            # Проверяем, нужно ли использовать Elasticsearch:
            # 1. SQL-агент завершился ошибкой
            # 2. SQL-агент вернул 0 результатов
            sql_failed = not result.get("success")
            sql_zero_results = result.get("success") and (result.get("row_count", 0) == 0 or not result.get("data") or len(result.get("data", [])) == 0)
            
            # Если SQL-агент не справился или вернул 0 результатов, пробуем fallback на Elasticsearch
            if (sql_failed or sql_zero_results) and settings.get("es_fallback_enabled", False):
                print(f"⚠️ SQL-агент не справился, используем fallback на Elasticsearch...")
                try:
                    es_service = ElasticsearchService()
                    if es_service.is_available():
                        # Извлекаем параметры из естественного языка
                        filters = _extract_filters_from_text(request.question)
                        
                        # Выполняем поиск через Elasticsearch
                        es_result = es_service.search_cars(
                            query=request.question,
                            limit=500,  # Увеличиваем до 500 для источников
                            **{k: v for k, v in filters.items() if v is not None}
                        )
                        
                        hits = es_result.get("hits", [])
                        total = es_result.get("total", 0)
                        
                        if hits and total > 0:
                            print(f"✅ Elasticsearch нашел {total} автомобилей (показано {len(hits)})")
                            
                            # Преобразуем результаты Elasticsearch в формат SQL-агента
                            # Включаем ВСЕ поля из таблиц cars, used_cars и опций:
                            #
                            # ОБЩИЕ ПОЛЯ (для cars и used_cars):
                            # - Основные: id, mark, model, vin, title, doc_num
                            # - Цена: price, sale_price, stock_qty (только cars)
                            # - Технические: manufacture_year, model_year, fuel_type, power, body_type,
                            #   gear_box_type, driving_gear_type, engine_vol, engine, fuel_consumption,
                            #   max_torque, acceleration, max_speed, eco_class
                            # - Внешний вид: color, interior_color (только cars), color_code, interior_code,
                            #   pts_colour, door_qty (cars), doors (used_cars)
                            # - Размеры: dimensions, weight, cargo_volume
                            # - Комплектация: compl_level, code_compl, car_order_int_status
                            # - Локация: city, dealer_center, region (used_cars)
                            #
                            # ТОЛЬКО ДЛЯ НОВЫХ АВТО (cars):
                            # - Скидки: max_additional_discount, max_discount_trade_in, max_discount_credit,
                            #   max_discount_casko, max_discount_extra_gear, max_discount_life_insurance
                            # - Опции: options (из car_options и car_options_groups через JOIN)
                            #
                            # ТОЛЬКО ДЛЯ ПОДЕРЖАННЫХ АВТО (used_cars):
                            # - История: mileage, owners, accident, certification_number
                            # - Дополнительно: category, car_type, wheel_type, street,
                            #   generation_id, modification_id
                            #
                            # ПОЛЕ type: автоматически определяется по наличию mileage
                            es_data = []
                            es_columns = [
                                # Основные идентификаторы
                                "id", "mark", "model", "vin", "title", "doc_num",
                                # Цена и наличие
                                "price", "sale_price", "stock_qty",
                                # Технические характеристики
                                "manufacture_year", "model_year", "fuel_type", "power", "body_type",
                                "gear_box_type", "driving_gear_type", "engine_vol", "engine",
                                "fuel_consumption", "max_torque", "acceleration", "max_speed", "eco_class",
                                # Внешний вид и интерьер
                                "color", "interior_color", "color_code", "interior_code", "pts_colour",
                                "door_qty", "doors",
                                # Размеры и вес
                                "dimensions", "weight", "cargo_volume",
                                # Комплектация
                                "compl_level", "code_compl", "car_order_int_status",
                                # Локация и дилер
                                "city", "dealer_center", "region",
                                # Скидки (только для новых авто)
                                "max_additional_discount", "max_discount_trade_in", "max_discount_credit",
                                "max_discount_casko", "max_discount_extra_gear", "max_discount_life_insurance",
                                # Только для подержанных авто
                                "mileage", "owners", "accident", "certification_number",
                                "category", "car_type", "wheel_type", "street",
                                "generation_id", "modification_id",
                                # Опции (из Elasticsearch может быть в поле options или description)
                                # Опции из car_options и car_options_groups объединены в поле options
                                "options",
                                # Тип автомобиля (car или used_car)
                                "type"
                            ]
                            
                            for hit in hits:
                                source = hit.get("_source", {})
                                row = {}
                                
                                # Автоматически извлекаем все поля из источника
                                for col in es_columns:
                                    # Специальная обработка для некоторых полей
                                    if col == "type":
                                        # Определяем тип по наличию поля mileage
                                        value = source.get("type") or ("used_car" if source.get("mileage") is not None else "car")
                                        row[col] = value
                                    elif col == "options":
                                        # Опции могут быть в разных полях Elasticsearch
                                        value = source.get("options") or source.get("description") or source.get("options_text")
                                        if value:
                                            row[col] = value
                                    else:
                                        # Прямое получение значения из source
                                        value = source.get(col)
                                        if value is not None:
                                            row[col] = value
                                
                                # Убеждаемся, что тип установлен
                                if "type" not in row:
                                    row["type"] = "used_car" if source.get("mileage") is not None else "car"
                                
                                # Добавляем информацию об опциях, если доступна
                                car_type = row.get("type", "car")
                                if car_type == "car" and (source.get("options") or source.get("description")):
                                    row["has_options"] = True
                                
                                es_data.append(row)
                            
                            # ВАЖНО: Загружаем полные объекты автомобилей из БД по ID
                            # чтобы передать ИИ ВСЕ поля, а не только из Elasticsearch
                            from services.database_service import DatabaseService
                            db_service_temp = DatabaseService(db)
                            full_es_data = []
                            
                            for record in es_data:
                                car_id = record.get("id")
                                if car_id:
                                    # Определяем тип автомобиля
                                    car_type = record.get("type")
                                    has_mileage = record.get("mileage") is not None
                                    
                                    full_car = None
                                    try:
                                        if car_type == "used_car" or has_mileage:
                                            # Пробуем загрузить как подержанный
                                            full_car = db_service_temp.get_used_car(car_id)
                                            if not full_car:
                                                # Если не нашли, пробуем как новый
                                                full_car = db_service_temp.get_car(car_id)
                                        else:
                                            # Пробуем загрузить как новый
                                            full_car = db_service_temp.get_car(car_id)
                                            if not full_car:
                                                # Если не нашли, пробуем как подержанный
                                                full_car = db_service_temp.get_used_car(car_id)
                                        
                                        # Убеждаемся, что объект привязан к сессии
                                        if full_car:
                                            # Обновляем объект из БД, чтобы получить все поля
                                            db.refresh(full_car)
                                    except Exception as load_error:
                                        print(f"⚠️ Ошибка при загрузке автомобиля {car_id}: {load_error}")
                                        full_car = None
                                    
                                    if full_car:
                                        # Преобразуем объект SQLAlchemy в словарь со всеми полями
                                        car_dict = {}
                                        try:
                                            # Используем __table__.columns для получения всех колонок модели
                                            mapper = sql_inspect(full_car)
                                            if hasattr(mapper, 'columns'):
                                                for column in mapper.columns:
                                                    attr_name = column.name
                                                    try:
                                                        value = getattr(full_car, attr_name)
                                                        car_dict[attr_name] = value
                                                    except:
                                                        pass
                                            else:
                                                # Fallback: используем __table__ напрямую
                                                if hasattr(full_car, '__table__'):
                                                    for column in full_car.__table__.columns:
                                                        attr_name = column.name
                                                        try:
                                                            value = getattr(full_car, attr_name)
                                                            car_dict[attr_name] = value
                                                        except:
                                                            pass
                                        except Exception as inspect_error:
                                            # Если sql_inspect не работает, используем альтернативный способ
                                            print(f"⚠️ Ошибка при inspect для автомобиля {car_id}: {inspect_error}")
                                            # Используем __table__ напрямую
                                            if hasattr(full_car, '__table__'):
                                                for column in full_car.__table__.columns:
                                                    attr_name = column.name
                                                    try:
                                                        value = getattr(full_car, attr_name)
                                                        car_dict[attr_name] = value
                                                    except:
                                                        pass
                                        
                                        # Проверяем, что словарь не пустой
                                        if not car_dict or len(car_dict) < 3:
                                            print(f"⚠️ Автомобиль {car_id} имеет мало полей ({len(car_dict)}), используем исходные данные")
                                            # Если словарь почти пустой, используем исходные данные из ES
                                            car_dict = record.copy()
                                        else:
                                            # Объединяем с исходными данными, чтобы не потерять информацию
                                            for key, value in record.items():
                                                if key not in car_dict or (car_dict.get(key) is None and value is not None):
                                                    car_dict[key] = value
                                        
                                        # Добавляем тип автомобиля
                                        if hasattr(full_car, 'mileage') and full_car.mileage is not None:
                                            car_dict['type'] = 'used_car'
                                        else:
                                            car_dict['type'] = 'car'
                                        
                                        # Загружаем опции для новых автомобилей (только для Car, не для UsedCar)
                                        if car_dict['type'] == 'car' and hasattr(full_car, 'options'):
                                            try:
                                                # Загружаем опции через relationship
                                                options_list = []
                                                options_groups_list = []
                                                
                                                # Получаем опции
                                                if full_car.options:
                                                    for option in full_car.options:
                                                        if option.description:
                                                            options_list.append(option.description)
                                                
                                                # Получаем группы опций с их опциями
                                                if hasattr(full_car, 'options_groups') and full_car.options_groups:
                                                    for group in full_car.options_groups:
                                                        group_info = {
                                                            'name': group.name or '',
                                                            'code': group.code or '',
                                                            'options': []
                                                        }
                                                        # Получаем опции из группы
                                                        if hasattr(group, 'options') and group.options:
                                                            for opt in group.options:
                                                                if opt.description:
                                                                    group_info['options'].append(opt.description)
                                                        if group_info['name'] or group_info['options']:
                                                            options_groups_list.append(group_info)
                                                
                                                # Добавляем опции в словарь
                                                if options_list:
                                                    car_dict['options'] = ', '.join(options_list)
                                                    car_dict['options_list'] = options_list
                                                
                                                if options_groups_list:
                                                    car_dict['options_groups'] = options_groups_list
                                                    
                                            except Exception as opt_error:
                                                print(f"⚠️ Ошибка при загрузке опций для автомобиля {car_id}: {opt_error}")
                                        
                                        full_es_data.append(car_dict)
                                    else:
                                        # Если не удалось загрузить полный объект, используем данные из ES
                                        full_es_data.append(record)
                                else:
                                    # Если нет ID, используем данные как есть
                                    full_es_data.append(record)
                            
                            # Формируем результат в формате SQL-агента
                            # Все результаты от Elasticsearch помечаем как альтернативные
                            result = {
                                "success": True,
                                "sql": result.get("sql", ""),  # Сохраняем исходный SQL, если был
                                "data": full_es_data,  # Используем полные данные из БД
                                "columns": es_columns,
                                "row_count": total,
                                "answer": f"Найдено {total} автомобилей",
                                "is_alternatives": True,  # Помечаем как альтернативные
                                "fallback_source": "elasticsearch"
                            }
                        else:
                            print(f"⚠️ Elasticsearch не нашел результатов")
                            # Если Elasticsearch не нашел результатов, все равно помечаем как альтернативы
                            # и используем AI для формирования ответа
                            result["is_alternatives"] = True
                            result["fallback_source"] = "elasticsearch"
                    else:
                        print(f"⚠️ Elasticsearch недоступен")
                except Exception as es_error:
                    print(f"❌ Ошибка fallback на Elasticsearch: {es_error}")
                    # Продолжаем с ошибкой SQL-агента
            
            if result.get("success"):
                print(f"✅ SQL-агент успешно обработал запрос. Найдено записей: {result.get('row_count', 0)}")
                
                result_data = result.get("data")
                row_count = result.get("row_count", 0)
                
                # Если SQL-агент вернул 0 результатов И еще не использовали Elasticsearch fallback,
                # пробуем найти альтернативы с ослабленными фильтрами
                # (fallback уже обработал случай ошибки SQL-агента)
                if (result_data is None or len(result_data) == 0) and row_count == 0 and not result.get("is_alternatives"):
                    print(f"🔍 SQL-агент не нашел результатов, ищем альтернативы...")
                    
                    try:
                        # Извлекаем фильтры из исходного запроса
                        filters = _extract_filters_from_text(request.question)
                        
                        # Ослабляем фильтры для поиска альтернатив
                        relaxed_filters = _relax_filters_for_alternatives(filters, request.question)
                        
                        # Формируем новый запрос для поиска альтернатив
                        # Сначала пробуем через Elasticsearch с ослабленными фильтрами
                        es_service = ElasticsearchService()
                        if es_service.is_available():
                            print(f"🔍 Поиск альтернатив через Elasticsearch с ослабленными фильтрами...")
                            
                            # Формируем запрос для альтернатив
                            # Убираем строгие условия из исходного запроса
                            alternative_query = request.question
                            
                            # Пробуем найти через Elasticsearch с ослабленными фильтрами
                            es_result = es_service.search_cars(
                                query=alternative_query,
                                limit=500,
                                **{k: v for k, v in relaxed_filters.items() if v is not None}
                            )
                            
                            hits = es_result.get("hits", [])
                            total = es_result.get("total", 0)
                            
                            if hits and total > 0:
                                print(f"✅ Найдено {total} альтернативных автомобилей через Elasticsearch")
                                
                                # Преобразуем результаты Elasticsearch в формат SQL-агента
                                # (используем ту же логику, что и для fallback)
                                from services.database_service import DatabaseService
                                db_service_alt = DatabaseService(db)
                                full_es_data = []
                                
                                es_columns = [
                                    "id", "mark", "model", "vin", "title", "doc_num",
                                    "price", "sale_price", "stock_qty",
                                    "manufacture_year", "model_year", "fuel_type", "power", "body_type",
                                    "gear_box_type", "driving_gear_type", "engine_vol", "engine",
                                    "fuel_consumption", "max_torque", "acceleration", "max_speed", "eco_class",
                                    "color", "interior_color", "color_code", "interior_code", "pts_colour",
                                    "door_qty", "doors",
                                    "dimensions", "weight", "cargo_volume",
                                    "compl_level", "code_compl", "car_order_int_status",
                                    "city", "dealer_center", "region",
                                    "max_additional_discount", "max_discount_trade_in", "max_discount_credit",
                                    "max_discount_casko", "max_discount_extra_gear", "max_discount_life_insurance",
                                    "mileage", "owners", "accident", "certification_number",
                                    "category", "car_type", "wheel_type", "street",
                                    "generation_id", "modification_id",
                                    "options", "type"
                                ]
                                
                                es_data = []
                                for hit in hits:
                                    source = hit.get("_source", {})
                                    row = {}
                                    
                                    for col in es_columns:
                                        if col == "type":
                                            value = source.get("type") or ("used_car" if source.get("mileage") is not None else "car")
                                            row[col] = value
                                        elif col == "options":
                                            value = source.get("options") or source.get("description") or source.get("options_text")
                                            if value:
                                                row[col] = value
                                        else:
                                            value = source.get(col)
                                            if value is not None:
                                                row[col] = value
                                    
                                    if "type" not in row:
                                        row["type"] = "used_car" if source.get("mileage") is not None else "car"
                                    
                                    es_data.append(row)
                                
                                # Загружаем полные объекты из БД (аналогично fallback логике)
                                for record in es_data:
                                    car_id = record.get("id")
                                    if car_id:
                                        car_type = record.get("type")
                                        has_mileage = record.get("mileage") is not None
                                        
                                        full_car = None
                                        try:
                                            if car_type == "used_car" or has_mileage:
                                                full_car = db_service_alt.get_used_car(car_id)
                                                if not full_car:
                                                    full_car = db_service_alt.get_car(car_id)
                                            else:
                                                full_car = db_service_alt.get_car(car_id)
                                                if not full_car:
                                                    full_car = db_service_alt.get_used_car(car_id)
                                            
                                            if full_car:
                                                db.refresh(full_car)
                                                # Преобразуем в словарь (упрощенная версия)
                                                car_dict = {}
                                                try:
                                                    mapper = sql_inspect(full_car)
                                                    if hasattr(mapper, 'columns'):
                                                        for column in mapper.columns:
                                                            attr_name = column.name
                                                            try:
                                                                value = getattr(full_car, attr_name)
                                                                car_dict[attr_name] = value
                                                            except:
                                                                pass
                                                    else:
                                                        if hasattr(full_car, '__table__'):
                                                            for column in full_car.__table__.columns:
                                                                attr_name = column.name
                                                                try:
                                                                    value = getattr(full_car, attr_name)
                                                                    car_dict[attr_name] = value
                                                                except:
                                                                    pass
                                                except:
                                                    if hasattr(full_car, '__table__'):
                                                        for column in full_car.__table__.columns:
                                                            attr_name = column.name
                                                            try:
                                                                value = getattr(full_car, attr_name)
                                                                car_dict[attr_name] = value
                                                            except:
                                                                pass
                                                
                                                if not car_dict or len(car_dict) < 3:
                                                    car_dict = record.copy()
                                                else:
                                                    for key, value in record.items():
                                                        if key not in car_dict or (car_dict.get(key) is None and value is not None):
                                                            car_dict[key] = value
                                                
                                                if hasattr(full_car, 'mileage') and full_car.mileage is not None:
                                                    car_dict['type'] = 'used_car'
                                                else:
                                                    car_dict['type'] = 'car'
                                                
                                                # Загружаем опции для новых автомобилей
                                                if car_dict['type'] == 'car' and hasattr(full_car, 'options'):
                                                    try:
                                                        options_list = []
                                                        if full_car.options:
                                                            for option in full_car.options:
                                                                if option.description:
                                                                    options_list.append(option.description)
                                                        
                                                        if options_list:
                                                            car_dict['options'] = ', '.join(options_list)
                                                            car_dict['options_list'] = options_list
                                                    except:
                                                        pass
                                                
                                                full_es_data.append(car_dict)
                                            else:
                                                full_es_data.append(record)
                                        except Exception as load_error:
                                            print(f"⚠️ Ошибка при загрузке альтернативного автомобиля {car_id}: {load_error}")
                                            full_es_data.append(record)
                                    else:
                                        full_es_data.append(record)
                                
                                # Обновляем результат с альтернативами
                                result = {
                                    "success": True,
                                    "sql": result.get("sql", ""),  # Сохраняем исходный SQL
                                    "data": full_es_data,
                                    "columns": es_columns,
                                    "row_count": total,
                                    "answer": f"По вашему запросу ничего не найдено, но мы нашли {total} похожих альтернатив",
                                    "is_alternatives": True,  # Пометка, что это альтернативы
                                    "fallback_source": "elasticsearch_alternatives"
                                }
                                
                                result_data = full_es_data
                                row_count = total
                                print(f"✅ Альтернативы найдены: {total} автомобилей")
                            else:
                                print(f"⚠️ Альтернативы не найдены даже с ослабленными фильтрами")
                        else:
                            print(f"⚠️ Elasticsearch недоступен для поиска альтернатив")
                    except Exception as alt_error:
                        print(f"❌ Ошибка при поиске альтернатив: {alt_error}")
                        # Продолжаем с исходным результатом (0 записей)
                
                # Если есть данные, отправляем первые 5 записей в AI для форматирования
                if result_data is not None and len(result_data) > 0:
                    try:
                        from services.database_service import DatabaseService
                        from services.rag_service import RAGService
                        
                        db_service = DatabaseService(db)
                        rag_service = RAGService(db_service)
                        
                        # Формируем контекст из данных (SQL-агент или Elasticsearch fallback)
                        # Для AI используем только первые 5, но для источников будут все данные
                        all_data = result_data if result_data is not None else []
                        data_records = all_data[:5] if all_data else []  # Ограничиваем до 5 для AI-форматирования
                        data_columns = result.get("columns", [])
                        query_info = result.get("sql", "")
                        total_count = result.get("row_count", len(all_data))
                        fallback_source = result.get("fallback_source")
                        
                        # ВАЖНО: Загружаем полные объекты автомобилей из БД по ID
                        # чтобы передать ИИ ВСЕ поля, а не только выбранные в SQL-запросе
                        full_car_records = []
                        for record in data_records:
                            car_id = record.get("id")
                            if car_id:
                                # Определяем тип автомобиля
                                car_type = record.get("type")
                                has_mileage = record.get("mileage") is not None
                                
                                full_car = None
                                try:
                                    if car_type == "used_car" or has_mileage:
                                        # Пробуем загрузить как подержанный
                                        full_car = db_service.get_used_car(car_id)
                                        if not full_car:
                                            # Если не нашли, пробуем как новый
                                            full_car = db_service.get_car(car_id)
                                    else:
                                        # Пробуем загрузить как новый
                                        full_car = db_service.get_car(car_id)
                                        if not full_car:
                                            # Если не нашли, пробуем как подержанный
                                            full_car = db_service.get_used_car(car_id)
                                    
                                    # Убеждаемся, что объект привязан к сессии
                                    if full_car:
                                        # Обновляем объект из БД, чтобы получить все поля
                                        db.refresh(full_car)
                                except Exception as load_error:
                                    print(f"⚠️ Ошибка при загрузке автомобиля {car_id}: {load_error}")
                                    full_car = None
                                
                                if full_car:
                                    # Преобразуем объект SQLAlchemy в словарь со всеми полями
                                    car_dict = {}
                                    try:
                                        # Используем __table__.columns для получения всех колонок модели
                                        mapper = sql_inspect(full_car)
                                        if hasattr(mapper, 'columns'):
                                            for column in mapper.columns:
                                                attr_name = column.name
                                                try:
                                                    value = getattr(full_car, attr_name)
                                                    car_dict[attr_name] = value
                                                except:
                                                    pass
                                        else:
                                            # Fallback: используем __table__ напрямую
                                            if hasattr(full_car, '__table__'):
                                                for column in full_car.__table__.columns:
                                                    attr_name = column.name
                                                    try:
                                                        value = getattr(full_car, attr_name)
                                                        car_dict[attr_name] = value
                                                    except:
                                                        pass
                                    except Exception as inspect_error:
                                        # Если sql_inspect не работает, используем альтернативный способ
                                        print(f"⚠️ Ошибка при inspect для автомобиля {car_id}: {inspect_error}")
                                        # Используем __table__ напрямую
                                        if hasattr(full_car, '__table__'):
                                            for column in full_car.__table__.columns:
                                                attr_name = column.name
                                                try:
                                                    value = getattr(full_car, attr_name)
                                                    car_dict[attr_name] = value
                                                except:
                                                    pass
                                    
                                    # Проверяем, что словарь не пустой
                                    if not car_dict or len(car_dict) < 3:
                                        print(f"⚠️ Автомобиль {car_id} имеет мало полей ({len(car_dict)}), используем исходные данные")
                                        # Если словарь почти пустой, используем исходные данные из SQL
                                        car_dict = record.copy()
                                    else:
                                        # Объединяем с исходными данными, чтобы не потерять информацию
                                        for key, value in record.items():
                                            if key not in car_dict or (car_dict.get(key) is None and value is not None):
                                                car_dict[key] = value
                                    
                                    # Добавляем тип автомобиля
                                    if hasattr(full_car, 'mileage') and full_car.mileage is not None:
                                        car_dict['type'] = 'used_car'
                                    else:
                                        car_dict['type'] = 'car'
                                    
                                    # Загружаем опции для новых автомобилей (только для Car, не для UsedCar)
                                    if car_dict['type'] == 'car' and hasattr(full_car, 'options'):
                                        try:
                                            # Загружаем опции через relationship
                                            options_list = []
                                            options_groups_list = []
                                            
                                            # Получаем опции
                                            if full_car.options:
                                                for option in full_car.options:
                                                    if option.description:
                                                        options_list.append(option.description)
                                            
                                            # Получаем группы опций с их опциями
                                            if hasattr(full_car, 'options_groups') and full_car.options_groups:
                                                for group in full_car.options_groups:
                                                    group_info = {
                                                        'name': group.name or '',
                                                        'code': group.code or '',
                                                        'options': []
                                                    }
                                                    # Получаем опции из группы
                                                    if hasattr(group, 'options') and group.options:
                                                        for opt in group.options:
                                                            if opt.description:
                                                                group_info['options'].append(opt.description)
                                                    if group_info['name'] or group_info['options']:
                                                        options_groups_list.append(group_info)
                                            
                                            # Добавляем опции в словарь
                                            if options_list:
                                                car_dict['options'] = ', '.join(options_list)
                                                car_dict['options_list'] = options_list
                                            
                                            if options_groups_list:
                                                car_dict['options_groups'] = options_groups_list
                                                
                                        except Exception as opt_error:
                                            print(f"⚠️ Ошибка при загрузке опций для автомобиля {car_id}: {opt_error}")
                                    
                                    full_car_records.append(car_dict)
                                else:
                                    # Если не удалось загрузить полный объект, используем данные из SQL
                                    full_car_records.append(record)
                            else:
                                # Если нет ID, используем данные как есть
                                full_car_records.append(record)
                        
                        # Используем полные данные вместо ограниченных
                        data_records = full_car_records
                        
                        # Определяем источник данных для промпта
                        is_alternatives = result.get("is_alternatives", False)
                        if fallback_source == "elasticsearch" or fallback_source == "elasticsearch_alternatives":
                            data_source_text = "Elasticsearch поиск"
                            query_prefix = "Поисковый запрос"
                        else:
                            data_source_text = "SQL запрос"
                            query_prefix = "SQL"
                        
                        # Если это альтернативы, добавляем пометку
                        if is_alternatives:
                            alternatives_note = "\n\n⚠️ ВАЖНО: По вашему точному запросу ничего не найдено. Ниже показаны похожие альтернативы с ослабленными критериями поиска. Эти автомобили могут отличаться от ваших требований, но могут быть интересны как варианты."
                        else:
                            alternatives_note = ""
                        
                        # Создаем текстовое представление данных для AI
                        context_text = f"Результаты {data_source_text}:\n"
                        if query_info:
                            context_text += f"{query_prefix}: {query_info}\n\n"
                        context_text += f"Найдено записей: {total_count}\n"
                        context_text += f"Показано первых {len(data_records)} записей:\n\n"
                        
                        # Добавляем пометку об альтернативах, если это альтернативы
                        if is_alternatives:
                            context_text += alternatives_note + "\n\n"
                        
                        # Форматируем данные в таблицу со ВСЕМИ полями
                        if data_records:
                            # Собираем все уникальные колонки из всех записей
                            all_columns = set()
                            for record in data_records:
                                all_columns.update(record.keys())
                            
                            # Сортируем колонки: сначала важные, потом остальные
                            priority_columns = [
                                "id", "type", "mark", "model", "price", "sale_price", "city", 
                                "body_type", "fuel_type", "manufacture_year", "model_year",
                                "gear_box_type", "driving_gear_type", "mileage", "color", 
                                "power", "engine_vol", "engine", "owners", "accident",
                                "vin", "dealer_center", "region", "stock_qty", 
                                "options", "options_list", "options_groups"  # Опции автомобиля
                            ]
                            
                            # Формируем список колонок: сначала приоритетные, потом остальные
                            display_columns = []
                            for col in priority_columns:
                                if col in all_columns:
                                    display_columns.append(col)
                            # Добавляем остальные колонки
                            for col in sorted(all_columns):
                                if col not in display_columns:
                                    display_columns.append(col)
                            
                            if display_columns:
                                context_text += "| " + " | ".join(str(col) for col in display_columns) + " |\n"
                                context_text += "|" + "|".join(["---" for _ in display_columns]) + "|\n"
                                for row in data_records:
                                    row_values = []
                                    for col in display_columns:
                                        value = row.get(col)
                                        if value is None:
                                            row_values.append("")
                                        elif isinstance(value, list):
                                            # Форматируем списки (например, options_list)
                                            if value and isinstance(value[0], dict):
                                                # Список словарей (например, options_groups)
                                                formatted = "; ".join([
                                                    f"{item.get('name', '')}: {', '.join(item.get('options', []))}"
                                                    if item.get('options') else item.get('name', '')
                                                    for item in value
                                                ])
                                                row_values.append(formatted)
                                            else:
                                                # Обычный список строк
                                                row_values.append(", ".join(str(v) for v in value))
                                        elif isinstance(value, dict):
                                            # Форматируем словари
                                            row_values.append(str(value))
                                        else:
                                            row_values.append(str(value))
                                    context_text += "| " + " | ".join(row_values) + " |\n"
                        
                        # Формируем промпт для AI в стиле автоэксперта
                        if is_alternatives:
                            data_source_desc = "поиска альтернатив (Elasticsearch)"
                            alternatives_warning = "\n\n⚠️ ВАЖНО: Это альтернативные варианты! По точному запросу пользователя ничего не найдено. Обязательно начни ответ с фразы: \"По вашему точному запросу ничего не найдено, но мы подобрали похожие альтернативы:\" и объясни, чем эти варианты отличаются от запроса пользователя."
                        elif fallback_source:
                            data_source_desc = "Elasticsearch поиска"
                            alternatives_warning = ""
                        else:
                            data_source_desc = "SQL-запроса"
                            alternatives_warning = ""
                        
                        ai_prompt = f"""Ты — автоэксперт и персональный помощник по подбору автомобиля. Отвечай на русском. 
Твой стиль — кратко, по делу, профессионально. Избегай воды.

🚨 КРИТИЧЕСКИ ВАЖНО: ОСНОВЫВАЙСЯ ТОЛЬКО НА ДАННЫХ НИЖЕ! 
- НЕ придумывай автомобили, которых нет в таблице!
- НЕ указывай характеристики, которых нет в данных!
- НЕ упоминай марки/модели, которые не присутствуют в результатах {data_source_desc}!
- Используй ТОЛЬКО информацию из предоставленной таблицы!
- Если данных недостаточно — скажи об этом прямо, НЕ выдумывай!

📋 ИНСТРУКЦИИ ПО ТИПАМ ЗАПРОСОВ:

⚠️ ВАЖНО: Определяй тип запроса по СОДЕРЖАНИЮ, а не только по первым словам!

1. **Если запрос автомобильный** (просьба найти, подобрать, показать автомобили, вопросы о характеристиках, ценах, сравнении моделей и т.д.):
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Если в запросе есть критерии поиска (год, пробег, цена, тип коробки, марка, модель, кузов, топливо, привод и т.д.), то это АВТОМОБИЛЬНЫЙ запрос, даже если он начинается с приветствия!
   - Примеры автомобильных запросов: "привет, хочу автомат не старше 2013 года", "здравствуй, покажи машины до 1 млн", "добрый день, ищу седан с пробегом до 100 тыс"
   - Отвечай как эксперт по автомобилям
   - Если запрос начинается с приветствия, но содержит критерии поиска — НЕ показывай общую информацию о возможностях, а СРАЗУ дай рекомендации по найденным автомобилям!
   - Дай экспертную рекомендацию (ТОП‑3 варианта) с причинами выбора — используй ТОЛЬКО автомобили из таблицы ниже
   - Укажи ключевые характеристики (год, цена, пробег, город, кузов, коробка, привод, топливо) — ТОЛЬКО из данных в таблице
   - Добавь 2–3 альтернативы с короткими пояснениями — ТОЛЬКО из предоставленных данных
   - Отметь риски/особенности — ТОЛЬКО на основе реальных данных (пробег, год, цена из таблицы)
   - Дай практические советы по покупке (общие советы, не специфичные для конкретных авто из таблицы)
   - Предложи следующие шаги (сузить бюджет/год/пробег, выбрать город/кузов/коробку и т.п.)
   - Задай 2–4 уточняющих вопроса (приоритеты: бюджет, новый/с пробегом, кузов, привод, двигатель, год, пробег, город)

2. **Если это ТОЛЬКО приветствие БЕЗ критериев поиска** (привет, здравствуй, добрый день, начать и т.д., но БЕЗ упоминания года, цены, пробега, марки, модели, кузова и т.д.):
   - Поприветствуй пользователя дружелюбно
   - Уточни, что интересует пользователя
   - Спроси, какие автомобили его интересуют
   - Предложи помощь в подборе

3. **Если запрос НЕ автомобильный** (вопросы о погоде, политике, других товарах, общие вопросы и т.д.):
   - Строго отвечай, что ты эксперт по подбору автомобилей
   - Объясни, что можешь помочь только с вопросами, связанными с автомобилями
   - Вежливо предложи вернуться к теме автомобилей
   - НЕ отвечай на вопросы, не связанные с автомобилями

У тебя есть данные из базы данных (результаты {data_source_desc}) ниже. Если в данных есть автомобили, используй их для ответа согласно инструкциям выше.{alternatives_warning}

Если записей больше, чем показано ({len(data_records)} из {total_count}), упомяни об этом и предложи уточнить критерии поиска.

Форматируй ответ структурированными пунктами. Числа (цены/пробег/год) пиши в человекочитаемом виде (например: "2 200 000 рублей" вместо "2200000.0"). 

⚠️ ЗАПРЕЩЕНО: Придумывать данные, которых нет в таблице! Если информация отсутствует — скажи "не указано" или "данные отсутствуют".

Данные из базы данных ({data_source_text} выполнен успешно):
Найдено записей: {total_count}
Показано первых {len(data_records)} записей:

{context_text}

Запрос пользователя: {request.question}

Сформируй ответ автоэксперта, используя ТОЛЬКО данные из таблицы выше:"""

                        # Генерируем ответ через AI напрямую по промпту, минуя обработку команд
                        # Используем _generate_with_ai_settings напрямую для SQL-агента
                        from services.rag_service import _generate_with_ai_settings
                        ai_response_text, model_info = await _generate_with_ai_settings(ai_prompt)
                        
                        # Сохраняем сообщение в БД
                        from services.database_service import DatabaseService
                        db_service_msg = DatabaseService(db)
                        chat_message = db_service_msg.save_chat_message(
                            user_id="sql-agent-user",
                            message=request.question,
                            response=ai_response_text,
                            related_article_ids=[]
                        )
                        
                        ai_response = {
                            "response": ai_response_text,
                            "message_id": chat_message.id if chat_message else None,
                            "model_info": model_info
                        }
                        
                        # Используем AI-ответ вместо простого answer
                        ai_formatted_response = ai_response.get("response", result.get("answer", "Запрос выполнен успешно."))
                        result["answer"] = ai_formatted_response
                        
                        # Сохраняем сообщение в БД через database_service
                        try:
                            message_id = ai_response.get("message_id")
                            if message_id:
                                result["message_id"] = message_id
                        except:
                            pass
                        
                        source_name = "Elasticsearch" if fallback_source == "elasticsearch" else "SQL-агента"
                        print(f"✅ AI сформировал ответ на основе данных {source_name} ({len(data_records)} из {total_count} записей)")
                        print(f"📝 Длина AI-ответа: {len(ai_formatted_response)} символов")
                        print(f"📤 Ответ будет передан в frontend через SQLAgentResponse.answer")
                        
                    except Exception as ai_error:
                        print(f"⚠️ Ошибка при форматировании через AI: {ai_error}")
                        # Используем обычный answer если AI не доступен
                        pass
                else:
                    # Если данных нет, но нужно сформировать ответ (приветствие, неавтомобильный запрос и т.д.)
                    # Используем AI для формирования ответа согласно инструкциям
                    try:
                        from services.database_service import DatabaseService
                        from services.rag_service import RAGService
                        
                        db_service = DatabaseService(db)
                        rag_service = RAGService(db_service)
                        
                        # Формируем промпт для случая без данных
                        if is_alternatives:
                            data_source_desc = "поиска альтернатив (Elasticsearch)"
                            alternatives_warning = "\n\n⚠️ ВАЖНО: Это альтернативные варианты! По точному запросу пользователя ничего не найдено. Обязательно начни ответ с фразы: \"По вашему точному запросу ничего не найдено, но мы подобрали похожие альтернативы:\" и объясни, чем эти варианты отличаются от запроса пользователя."
                        else:
                            data_source_desc = "SQL-запроса"
                            alternatives_warning = ""
                        
                        ai_prompt_no_data = f"""Ты — автоэксперт и персональный помощник по подбору автомобиля. Отвечай на русском. 
Твой стиль — кратко, по делу, профессионально. Избегай воды.

📋 ИНСТРУКЦИИ ПО ТИПАМ ЗАПРОСОВ:

⚠️ ВАЖНО: Определяй тип запроса по СОДЕРЖАНИЮ, а не только по первым словам!

1. **Если запрос автомобильный** (просьба найти, подобрать, показать автомобили, вопросы о характеристиках, ценах, сравнении моделей и т.д.):
   - ⚠️ КРИТИЧЕСКИ ВАЖНО: Если в запросе есть критерии поиска (год, пробег, цена, тип коробки, марка, модель, кузов, топливо, привод и т.д.), то это АВТОМОБИЛЬНЫЙ запрос, даже если он начинается с приветствия!
   - Примеры автомобильных запросов: "привет, хочу автомат не старше 2013 года", "здравствуй, покажи машины до 1 млн", "добрый день, ищу седан с пробегом до 100 тыс"
   - Отвечай как эксперт по автомобилям
   - Если запрос начинается с приветствия, но содержит критерии поиска — НЕ показывай общую информацию о возможностях, а СРАЗУ объясни ситуацию с поиском!
   - Если данных нет, объясни почему (слишком строгие критерии, нет таких автомобилей в базе и т.д.)
   - Предложи ослабить критерии поиска
   - Задай уточняющие вопросы для лучшего подбора

2. **Если это ТОЛЬКО приветствие БЕЗ критериев поиска** (привет, здравствуй, добрый день, начать и т.д., но БЕЗ упоминания года, цены, пробега, марки, модели, кузова и т.д.):
   - Поприветствуй пользователя дружелюбно
   - Уточни, что интересует пользователя
   - Спроси, какие автомобили его интересуют
   - Предложи помощь в подборе

3. **Если запрос НЕ автомобильный** (вопросы о погоде, политике, других товарах, общие вопросы и т.д.):
   - Строго отвечай, что ты эксперт по подбору автомобилей
   - Объясни, что можешь помочь только с вопросами, связанными с автомобилями
   - Вежливо предложи вернуться к теме автомобилей
   - НЕ отвечай на вопросы, не связанные с автомобилями

Запрос пользователя: {request.question}

Сформируй ответ согласно инструкциям выше:"""

                        # Генерируем ответ через AI напрямую по промпту, минуя обработку команд
                        from services.rag_service import _generate_with_ai_settings
                        ai_response_text, model_info = await _generate_with_ai_settings(ai_prompt_no_data)
                        
                        # Сохраняем сообщение в БД
                        chat_message = db_service.save_chat_message(
                            user_id="sql-agent-user",
                            message=request.question,
                            response=ai_response_text,
                            related_article_ids=[]
                        )
                        
                        ai_formatted_response = ai_response_text
                        result["answer"] = ai_formatted_response
                        
                        try:
                            if chat_message:
                                result["message_id"] = chat_message.id
                        except:
                            pass
                        
                        print(f"✅ AI сформировал ответ без данных для запроса: {request.question}")
                        print(f"📝 Длина AI-ответа: {len(ai_formatted_response)} символов")
                        
                    except Exception as ai_error:
                        print(f"⚠️ Ошибка при форматировании через AI (без данных): {ai_error}")
                        pass
            else:
                print(f"⚠️ SQL-агент не смог обработать запрос: {result.get('error')}")
            
            # Логируем финальный ответ перед возвратом
            final_answer = result.get("answer")
            if final_answer:
                print(f"✅ Финальный ответ готов для передачи в frontend: {len(final_answer)} символов")
                if result.get("fallback_source") == "elasticsearch":
                    print(f"🔄 Источник данных: Elasticsearch fallback")
            
            # Возвращаем все данные для источников (не только первые 5)
            all_data = result.get("data")
            if all_data is None:
                all_data = []
            
            # Формируем финальный ответ с учетом альтернатив
            final_answer = result.get("answer")
            if not final_answer:
                if result.get("is_alternatives"):
                    final_answer = f"По вашему запросу ничего не найдено, но мы нашли {result.get('row_count', 0)} похожих альтернатив"
                else:
                    final_answer = result.get("answer", "Результатов не найдено.")
            
            return SQLAgentResponse(
                success=result.get("success", False),
                sql=result.get("sql"),
                data=all_data,  # Все данные для источников (до 500 из sql_agent_service)
                columns=result.get("columns"),
                row_count=result.get("row_count"),
                answer=final_answer,
                error=result.get("error")
            )
            
    except Exception as e:
        print(f"❌ Ошибка SQL-агента: {str(e)}")
        return SQLAgentResponse(
            success=False,
            error=f"Ошибка обработки запроса: {str(e)}"
        )

@router.get("/sql-agent/schema")
async def get_database_schema(
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Получение схемы базы данных"""
    try:
        sql_agent = SQLAgentService(db)
        schema = sql_agent.get_database_schema()
        return {
            "success": True,
            "schema": schema
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка получения схемы: {str(e)}")
