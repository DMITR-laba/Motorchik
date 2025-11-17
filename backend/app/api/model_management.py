"""
API для управления моделями AI из интерфейса
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import json
import os
from datetime import datetime
from models import get_db
from models.schemas import (
    AIModelSettings, TaskModelConfig, TaskModelUpdate,
    ModelConfigResponse, ModelTestRequest, ModelTestResponse,
    ModelPerformanceMetrics, BulkModelUpdateRequest, BulkModelUpdateResponse
)
from services.ai_service import AIService
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType
from services.rag_service import _generate_with_ai_settings
from app.api.auth import require_admin

router = APIRouter(prefix="/api/models", tags=["model-management"])


@router.get("/config", response_model=ModelConfigResponse)
async def get_model_config(
    db: Session = Depends(get_db)
):
    """
    Получает текущую конфигурацию моделей
    """
    try:
        orchestrator = AIModelOrchestratorService()
        
        # Получаем конфигурацию задач
        task_mapping = orchestrator.config.get("task_model_mapping", {})
        
        # Преобразуем в формат ответа
        task_model_config = {}
        for task, config in task_mapping.items():
            task_model_config[task] = TaskModelConfig(
                primary=config.get("primary", ""),
                fallback=config.get("fallback", ""),
                complexity=config.get("complexity", "light")
            )
        
        # Получаем доступные модели
        available_models = await orchestrator.get_available_models()
        
        # Получаем текущие настройки AI
        ai_settings = _load_ai_settings()
        current_settings = AIModelSettings(
            response_model=ai_settings.get("response_model", ""),
            embedding_model=ai_settings.get("embedding_model", ""),
            api_service=ai_settings.get("api_service"),
            api_key=ai_settings.get("api_key"),
            deep_thinking_model=ai_settings.get("deep_thinking_model", ""),
            deepseek_api_key=ai_settings.get("deepseek_api_key", "")
        )
        
        return ModelConfigResponse(
            task_model_mapping=task_model_config,
            available_models=available_models,
            current_ai_settings=current_settings
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения конфигурации: {str(e)}")


@router.put("/config/task", response_model=Dict[str, Any])
async def update_task_model(
    update: TaskModelUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """
    Обновляет модель для конкретной задачи
    """
    try:
        # Определяем путь к конфигурации
        config_paths = [
            "backend/ai_model_config.json",
            "ai_model_config.json",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ai_model_config.json")
        ]
        
        config_path = None
        for path in config_paths:
            if os.path.exists(path):
                config_path = path
                break
        
        if not config_path:
            config_path = config_paths[0]  # Используем первый путь по умолчанию
        
        # Загружаем текущую конфигурацию
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {"task_model_mapping": {}}
        
        # Обновляем конфигурацию задачи
        if "task_model_mapping" not in config:
            config["task_model_mapping"] = {}
        
        if update.task_type not in config["task_model_mapping"]:
            config["task_model_mapping"][update.task_type] = {
                "primary": "",
                "fallback": "",
                "complexity": "light"
            }
        
        task_config = config["task_model_mapping"][update.task_type]
        
        if update.primary is not None:
            task_config["primary"] = update.primary
        if update.fallback is not None:
            task_config["fallback"] = update.fallback
        if update.complexity is not None:
            task_config["complexity"] = update.complexity
        
        # Сохраняем конфигурацию
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        # Перезагружаем конфигурацию в оркестраторе
        # Создаем новый экземпляр, чтобы применить изменения
        orchestrator = AIModelOrchestratorService()
        orchestrator.reload_config()
        
        # Проверяем, что изменения применились
        updated_config = orchestrator.config.get("task_model_mapping", {}).get(update.task_type, {})
        
        return {
            "success": True,
            "message": f"Модель для задачи '{update.task_type}' обновлена и применена",
            "task_config": task_config,
            "applied_config": updated_config,
            "note": "Изменения применены немедленно. Автоматическая загрузка моделей отключена - используйте /api/models/load для загрузки моделей Ollama."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обновления модели: {str(e)}")


@router.put("/config/bulk", response_model=BulkModelUpdateResponse)
async def bulk_update_models(
    request: BulkModelUpdateRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """
    Массовое обновление моделей для нескольких задач
    """
    try:
        # Определяем путь к конфигурации
        config_paths = [
            "backend/ai_model_config.json",
            "ai_model_config.json",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ai_model_config.json")
        ]
        
        config_path = None
        for path in config_paths:
            if os.path.exists(path):
                config_path = path
                break
        
        if not config_path:
            config_path = config_paths[0]  # Используем первый путь по умолчанию
        
        # Загружаем текущую конфигурацию
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {"task_model_mapping": {}}
        
        if "task_model_mapping" not in config:
            config["task_model_mapping"] = {}
        
        updated_tasks = []
        errors = []
        
        for update in request.updates:
            try:
                if update.task_type not in config["task_model_mapping"]:
                    config["task_model_mapping"][update.task_type] = {
                        "primary": "",
                        "fallback": "",
                        "complexity": "light"
                    }
                
                task_config = config["task_model_mapping"][update.task_type]
                
                if update.primary is not None:
                    task_config["primary"] = update.primary
                if update.fallback is not None:
                    task_config["fallback"] = update.fallback
                if update.complexity is not None:
                    task_config["complexity"] = update.complexity
                
                updated_tasks.append(update.task_type)
            except Exception as e:
                errors.append(f"{update.task_type}: {str(e)}")
        
        # Сохраняем конфигурацию
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        # Перезагружаем конфигурацию в оркестраторе
        # Создаем новый экземпляр, чтобы применить изменения
        orchestrator = AIModelOrchestratorService()
        orchestrator.reload_config()
        
        # Проверяем, что изменения применились
        applied_configs = {}
        for task in updated_tasks:
            applied_configs[task] = orchestrator.config.get("task_model_mapping", {}).get(task, {})
        
        return BulkModelUpdateResponse(
            success=len(errors) == 0,
            updated_tasks=updated_tasks,
            errors=errors
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка массового обновления: {str(e)}")


@router.put("/settings", response_model=Dict[str, Any])
async def update_ai_settings(
    settings: AIModelSettings,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """
    Обновляет основные настройки AI
    """
    try:
        # Определяем путь к настройкам
        settings_paths = [
            "backend/ai_settings.json",
            "ai_settings.json",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ai_settings.json")
        ]
        
        settings_path = None
        for path in settings_paths:
            if os.path.exists(path):
                settings_path = path
                break
        
        if not settings_path:
            settings_path = settings_paths[0]  # Используем первый путь по умолчанию
        
        # Загружаем текущие настройки
        current_settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                current_settings = json.load(f)
        
        # Обновляем настройки
        current_settings["response_model"] = settings.response_model
        current_settings["embedding_model"] = settings.embedding_model
        if settings.api_service:
            current_settings["api_service"] = settings.api_service
        if settings.api_key:
            current_settings["api_key"] = settings.api_key
        if settings.deep_thinking_model:
            current_settings["deep_thinking_model"] = settings.deep_thinking_model
        if settings.deepseek_api_key:
            current_settings["deepseek_api_key"] = settings.deepseek_api_key
        
        current_settings["updated_at"] = datetime.utcnow().isoformat()
        
        # Сохраняем настройки
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(current_settings, f, indent=2, ensure_ascii=False)
        
        return {
            "success": True,
            "message": "Настройки AI обновлены",
            "settings": current_settings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка обновления настроек: {str(e)}")


@router.post("/test", response_model=ModelTestResponse)
async def test_model(
    request: ModelTestRequest,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """
    Тестирует модель с заданным промптом
    """
    try:
        import time
        
        test_prompt = request.test_prompt or "Привет! Это тестовое сообщение."
        
        start_time = time.time()
        
        try:
            # Используем функцию генерации с указанной моделью
            # Временно переопределяем модель в настройках
            original_settings = _load_ai_settings()
            temp_settings = original_settings.copy()
            temp_settings["response_model"] = request.model_name
            
            # Определяем путь к настройкам
            settings_paths = [
                "backend/ai_settings.json",
                "ai_settings.json",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ai_settings.json")
            ]
            
            settings_path = None
            for path in settings_paths:
                if os.path.exists(path):
                    settings_path = path
                    break
            
            if not settings_path:
                settings_path = settings_paths[0]  # Используем первый путь по умолчанию
            
            # Сохраняем временные настройки
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(temp_settings, f, indent=2, ensure_ascii=False)
            
            try:
                response, model_info = await _generate_with_ai_settings(
                    prompt=test_prompt,
                    deep_thinking_enabled=False
                )
                
                response_time = time.time() - start_time
                
                # Восстанавливаем оригинальные настройки
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(original_settings, f, indent=2, ensure_ascii=False)
                
                return ModelTestResponse(
                    success=True,
                    response=response,
                    response_time=response_time,
                    model_info=model_info
                )
            except Exception as e:
                # Восстанавливаем оригинальные настройки
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(original_settings, f, indent=2, ensure_ascii=False)
                raise e
                
        except Exception as e:
            response_time = time.time() - start_time
            return ModelTestResponse(
                success=False,
                response_time=response_time,
                error=str(e)
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка тестирования модели: {str(e)}")


@router.get("/performance", response_model=List[ModelPerformanceMetrics])
async def get_model_performance(
    model_name: Optional[str] = None,
    task_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """
    Получает метрики производительности моделей
    """
    try:
        orchestrator = AIModelOrchestratorService()
        
        # Получаем метрики
        metrics = orchestrator.get_model_performance(
            model_name=model_name,
            task_type=TaskType(task_type) if task_type else None
        )
        
        # Преобразуем в формат ответа
        result = []
        for model, data in metrics.items():
            result.append(ModelPerformanceMetrics(
                model_name=model,
                task_type=data.get("task_type"),
                success_rate=data.get("success_rate"),
                avg_response_time=data.get("avg_response_time"),
                total_requests=data.get("total_requests"),
                last_used=data.get("last_used")
            ))
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения метрик: {str(e)}")


@router.get("/available")
async def get_available_models(
    db: Session = Depends(get_db)
):
    """
    Получает список всех доступных моделей
    """
    try:
        orchestrator = AIModelOrchestratorService()
        available_models = await orchestrator.get_available_models()
        
        # Группируем по провайдерам
        grouped = {
            "ollama": [],
            "mistral": [],
            "openai": [],
            "anthropic": [],
            "deepseek": [],
            "other": []
        }
        
        for model in available_models:
            if model.startswith("ollama:"):
                grouped["ollama"].append(model.replace("ollama:", ""))
            elif model.startswith("mistral:"):
                grouped["mistral"].append(model.replace("mistral:", ""))
            elif model.startswith("openai:"):
                grouped["openai"].append(model.replace("openai:", ""))
            elif model.startswith("anthropic:"):
                grouped["anthropic"].append(model.replace("anthropic:", ""))
            elif model.startswith("deepseek:"):
                grouped["deepseek"].append(model.replace("deepseek:", ""))
            else:
                grouped["other"].append(model)
        
        return {
            "all_models": available_models,
            "grouped_by_provider": grouped,
            "total_count": len(available_models)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения списка моделей: {str(e)}")


@router.post("/load", response_model=Dict[str, Any])
async def load_model_manually(
    model_name: str,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """
    Ручная загрузка модели Ollama по требованию пользователя
    """
    try:
        # Проверяем, что это модель Ollama
        if not model_name.startswith("ollama:"):
            raise HTTPException(
                status_code=400,
                detail="Ручная загрузка доступна только для моделей Ollama. Для других провайдеров используйте их API."
            )
        
        # Извлекаем имя модели
        actual_model_name = model_name.replace("ollama:", "")
        
        # Проверяем доступность Ollama
        from services.ollama_utils import find_working_ollama_url
        working_url = await find_working_ollama_url(timeout=2.0)
        if not working_url:
            raise HTTPException(status_code=400, detail="Ollama недоступен. Убедитесь, что Ollama запущен.")
        
        # Проверяем, не загружена ли модель уже
        orchestrator = AIModelOrchestratorService()
        available_models = await orchestrator.get_available_models()
        
        if model_name in available_models:
            return {
                "success": True,
                "message": f"Модель {actual_model_name} уже загружена",
                "model": actual_model_name,
                "status": "already_loaded"
            }
        
        # Загружаем модель
        print(f"📥 Пользователь запросил загрузку модели {actual_model_name}")
        await orchestrator._auto_load_model(actual_model_name, working_url, timeout=300.0)
        
        return {
            "success": True,
            "message": f"Модель {actual_model_name} успешно загружена",
            "model": actual_model_name,
            "status": "loaded"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки модели: {str(e)}")


def _load_ai_settings() -> Dict[str, Any]:
    """Загружает настройки AI"""
    default_settings = {
        "response_model": "mistral:mistral-large-latest",
        "embedding_model": "",
        "api_service": "mistral",
        "api_key": "",
        "deep_thinking_model": "",
        "deepseek_api_key": ""
    }
    
    # Определяем путь к настройкам
    settings_paths = [
        "backend/ai_settings.json",
        "ai_settings.json",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ai_settings.json")
    ]
    
    for settings_path in settings_paths:
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    default_settings.update(settings)
                break
            except Exception:
                continue
    
    return default_settings

