"""
Главный ИИ-оркестратор для автоматического выбора оптимальных моделей
для различных задач в системе автосалона
"""
from typing import Optional, Dict, Any, List
from enum import Enum
import json
import os
from datetime import datetime
from services.langchain_llm_service import LangChainLLMService
from services.ai_service import AIService
from services.ollama_utils import find_working_ollama_url
from app.core.config import settings


class TaskType(Enum):
    """Типы задач для выбора модели"""
    QUERY_ANALYSIS = "query_analysis"
    FUZZY_INTERPRETATION = "fuzzy_interpretation"
    FILTER_RELAXATION = "filter_relaxation"
    RECOMMENDATION = "recommendation"
    SQL_GENERATION = "sql_generation"
    RESPONSE_GENERATION = "response_generation"
    SEARCH_INTENT_ANALYSIS = "search_intent_analysis"
    QUERY_REFINEMENT = "query_refinement"
    RESULT_PROCESSING = "result_processing"
    RELATION_ANALYSIS = "relation_analysis"
    EMOTION_ANALYSIS = "emotion_analysis"
    QUESTION_GENERATION = "question_generation"
    ANSWER_GENERATION = "answer_generation"
    PROACTIVE_SUGGESTIONS = "proactive_suggestions"


class Complexity(Enum):
    """Уровень сложности задачи"""
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


class AIModelOrchestratorService:
    """Главный оркестратор для выбора моделей LLM"""
    
    def __init__(self, config_path: str = "backend/ai_model_config.json"):
        self.config_path = config_path
        self.langchain_service = LangChainLLMService()
        self.ai_service = AIService()
        self.config = self._load_config()
        self._model_cache: Dict[str, Any] = {}
        self._performance_metrics: Dict[str, Dict[str, Any]] = {}
        self._available_models: List[str] = []
    
    def _load_config(self) -> Dict[str, Any]:
        """Загружает конфигурацию моделей"""
        default_config = {
            "task_model_mapping": {
                "query_analysis": {
                    "primary": "ollama:llama3:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "light"
                },
                "fuzzy_interpretation": {
                    "primary": "ollama:mixtral:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "medium"
                },
                "filter_relaxation": {
                    "primary": "ollama:mixtral:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "medium"
                },
                "recommendation": {
                    "primary": "ollama:llama3:70b",
                    "fallback": "ollama:mixtral:8b",
                    "complexity": "heavy"
                },
                "sql_generation": {
                    "primary": "ollama:codellama:34b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "medium"
                },
                "response_generation": {
                    "primary": "ollama:llama3:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "light"
                },
                "search_intent_analysis": {
                    "primary": "ollama:llama3:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "light"
                },
                "query_refinement": {
                    "primary": "ollama:mixtral:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "medium"
                },
                "result_processing": {
                    "primary": "ollama:mixtral:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "medium"
                },
                "relation_analysis": {
                    "primary": "ollama:llama3:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "light"
                },
                "emotion_analysis": {
                    "primary": "ollama:llama3:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "light"
                },
                "question_generation": {
                    "primary": "ollama:mixtral:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "medium"
                },
                "answer_generation": {
                    "primary": "ollama:llama3:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "light"
                },
                "proactive_suggestions": {
                    "primary": "ollama:mixtral:8b",
                    "fallback": "ollama:llama3:8b",
                    "complexity": "medium"
                }
            },
            "user_overrides": {
                "enabled": True,
                "respect_user_settings": True
            },
            "performance_tracking": {
                "enabled": True,
                "cache_size": 100,
                "track_success_rate": True,
                "track_response_time": True
            },
            "model_availability_check": {
                "enabled": True,
                "check_interval_seconds": 300,
                "auto_fallback": True
            }
        }
        
        try:
            # Используем правильный путь (без backend/ если работаем из контейнера)
            config_file = self.config_path
            if config_file.startswith("backend/") and not os.path.exists("backend"):
                config_file = config_file.replace("backend/", "")
            
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    # Объединяем с дефолтной конфигурацией
                    default_config.update(user_config)
                    # Обновляем task_model_mapping если есть пользовательские настройки
                    if "task_model_mapping" in user_config:
                        default_config["task_model_mapping"].update(user_config["task_model_mapping"])
        except Exception as e:
            print(f"⚠️ Ошибка загрузки конфигурации: {e}, используем настройки по умолчанию")
        
        return default_config
    
    def _load_user_settings(self) -> Dict[str, str]:
        """Загружает пользовательские настройки моделей из ai_settings.json и sql_agent_settings.json"""
        user_overrides = {}
        
        # Загружаем из ai_settings.json
        try:
            if os.path.exists("backend/ai_settings.json"):
                with open("backend/ai_settings.json", "r", encoding="utf-8") as f:
                    ai_settings = json.load(f)
                    response_model = ai_settings.get("response_model", "")
                    if response_model:
                        user_overrides["response_generation"] = response_model
        except Exception as e:
            print(f"⚠️ Ошибка загрузки ai_settings.json: {e}")
        
        # Загружаем из sql_agent_settings.json
        try:
            if os.path.exists("backend/sql_agent_settings.json"):
                with open("backend/sql_agent_settings.json", "r", encoding="utf-8") as f:
                    sql_settings = json.load(f)
                    sql_model = sql_settings.get("sql_model", "")
                    if sql_model:
                        user_overrides["sql_generation"] = sql_model
        except Exception as e:
            print(f"⚠️ Ошибка загрузки sql_agent_settings.json: {e}")
        
        # Загружаем из ai_model_config.json (если есть user_model_overrides)
        try:
            if "user_model_overrides" in self.config:
                user_overrides.update(self.config["user_model_overrides"])
        except Exception:
            pass
        
        return user_overrides
    
    def _save_user_settings(self, task_type: str, model: str) -> bool:
        """Сохраняет пользовательские настройки модели в ai_model_config.json"""
        try:
            # Загружаем текущий конфиг
            config = self._load_config()
            
            # Инициализируем user_model_overrides если его нет
            if "user_model_overrides" not in config:
                config["user_model_overrides"] = {}
            
            # Сохраняем модель для задачи
            config["user_model_overrides"][task_type] = model
            
            # Создаем директорию если нужно
            config_dir = os.path.dirname(self.config_path)
            if config_dir:
                os.makedirs(config_dir, exist_ok=True)
            
            # Используем правильный путь (без backend/ если работаем из контейнера)
            config_file = self.config_path
            if config_file.startswith("backend/") and not os.path.exists("backend"):
                config_file = config_file.replace("backend/", "")
            
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            # Обновляем текущий конфиг
            self.config = config
            
            # Обновляем user_model_overrides в конфиге для немедленного использования
            if "user_model_overrides" not in self.config:
                self.config["user_model_overrides"] = {}
            self.config["user_model_overrides"][task_type] = model
            
            print(f"✅ Сохранена модель {model} для задачи {task_type}")
            return True
        except Exception as e:
            print(f"⚠️ Ошибка сохранения настроек модели: {e}")
            return False
    
    def save_multiple_models(self, models: Dict[str, str]) -> Dict[str, bool]:
        """Сохраняет несколько моделей для разных задач"""
        results = {}
        for task_type, model in models.items():
            results[task_type] = self._save_user_settings(task_type, model)
        return results
    
    async def select_model_for_task(
        self,
        task_type: TaskType,
        task_complexity: Optional[Complexity] = None,
        user_override: Optional[str] = None
    ) -> str:
        """
        Выбирает оптимальную модель для задачи с учетом приоритета:
        1. user_override (если передан)
        2. Настройки из ai_settings.json (высший приоритет для пользовательских настроек)
        3. Пользовательские настройки из файлов конфигурации
        4. Оркестратор (конфигурация задач)
        
        Args:
            task_type: Тип задачи
            task_complexity: Уровень сложности (опционально)
            user_override: Пользовательское переопределение модели
        
        Returns:
            str: Конфигурация модели в формате "provider:model_name"
        """
        task_key = task_type.value
        
        # 1. Проверяем пользовательское переопределение (высший приоритет)
        if user_override and user_override.strip():
            # Проверяем и загружаем модель если нужно
            await self._ensure_model_available(user_override)
            return user_override
        
        # 2. ПРИОРИТЕТ: Проверяем настройки из ai_settings.json (высший приоритет для настроек)
        try:
            import os
            import json
            ai_settings_paths = [
                "backend/ai_settings.json",
                "ai_settings.json",
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "ai_settings.json")
            ]
            
            for settings_path in ai_settings_paths:
                if os.path.exists(settings_path):
                    with open(settings_path, "r", encoding="utf-8") as f:
                        ai_settings = json.load(f)
                        response_model = ai_settings.get("response_model", "")
                        
                        # Для response_generation используем response_model из настроек
                        if task_key == "response_generation" and response_model and response_model.strip():
                            print(f"✅ Используется модель из ai_settings.json для {task_key}: {response_model}")
                            await self._ensure_model_available(response_model)
                            return response_model
                        
                        # Для других задач можно добавить специальные настройки
                        # Пока используем response_model как общую настройку
                        break
        except Exception as e:
            print(f"⚠️ Ошибка загрузки ai_settings.json: {e}")
        
        # 3. Проверяем пользовательские настройки из файлов конфигурации
        user_overrides = self._load_user_settings()
        if self.config.get("user_overrides", {}).get("enabled", True):
            if task_key in user_overrides:
                user_model = user_overrides[task_key]
                if user_model and user_model.strip():
                    print(f"✅ Используется пользовательская модель для {task_key}: {user_model}")
                    # Проверяем и загружаем модель если нужно
                    await self._ensure_model_available(user_model)
                    return user_model
        
        # 4. Используем оркестратор (конфигурация задач) - только если настройки не указаны
        selected_model = await self._ai_select_model(task_type, task_complexity)
        
        # 5. Проверяем и загружаем модель если нужно
        await self._ensure_model_available(selected_model)
        
        return selected_model
    
    async def _ai_select_model(
        self,
        task_type: TaskType,
        task_complexity: Optional[Complexity] = None
    ) -> str:
        """
        Использует ИИ для выбора оптимальной модели на основе задачи и доступных моделей
        """
        try:
            # Получаем доступные модели
            available_models = await self.get_available_models()
            
            # Получаем конфигурацию задачи
            task_key = task_type.value
            task_config = self.config.get("task_model_mapping", {}).get(task_key, {})
            if not task_config:
                task_config = self.config.get("task_model_mapping", {}).get("response_generation", {})
            
            primary_model = task_config.get("primary", "ollama:llama3:8b")
            fallback_model = task_config.get("fallback", "ollama:llama3:8b")
            complexity = task_complexity.value if task_complexity else task_config.get("complexity", "light")
            
            # Проверяем, включен ли ИИ выбор моделей
            ai_selection_config = self.config.get("ai_model_selection", {})
            if not ai_selection_config.get("enabled", True) or not ai_selection_config.get("use_ai_for_selection", True):
                return primary_model
            
            min_models = ai_selection_config.get("min_models_for_ai", 3)
            
            # Если доступных моделей мало или это простая задача - используем конфигурацию
            if len(available_models) < min_models or complexity == "light":
                return primary_model
            
            # Используем легкую модель для выбора модели (чтобы не было рекурсии)
            try:
                llm = self.langchain_service.get_llm("ollama:llama3:8b", None)
            except:
                # Если даже легкая модель недоступна, используем конфигурацию
                return primary_model
            
            # Формируем промпт для ИИ
            prompt = f"""Ты - эксперт по выбору LLM моделей для различных задач.

ЗАДАЧА: {task_key}
СЛОЖНОСТЬ: {complexity}
ДОСТУПНЫЕ МОДЕЛИ: {', '.join(available_models[:10])}  # Ограничиваем до 10 для промпта
РЕКОМЕНДУЕМАЯ МОДЕЛЬ: {primary_model}
FALLBACK МОДЕЛЬ: {fallback_model}

Выбери оптимальную модель для задачи, учитывая:
1. Сложность задачи ({complexity})
2. Доступность моделей
3. Производительность и скорость
4. Требования к качеству ответа

Если задача легкая - выбери легкую модель (llama3:8b, mixtral:8b)
Если задача средняя - выбери среднюю модель (mixtral:8b, codellama:34b)
Если задача тяжелая - выбери тяжелую модель (llama3:70b, mistral-large)

Верни только название модели в формате "ollama:model_name" или "mistral:model_name" и т.д.
Если рекомендованная модель доступна - используй её, иначе выбери лучшую альтернативу из доступных."""
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты - эксперт по выбору LLM моделей. Выбираешь оптимальную модель для задачи."),
                ("human", prompt)
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            # Парсим ответ
            ai_selected = response.strip()
            
            # Валидация выбранной модели
            if ai_selected and (ai_selected in available_models or ai_selected == primary_model):
                print(f"🤖 ИИ выбрал модель: {ai_selected}")
                return ai_selected
            else:
                # Если ИИ выбрал недоступную модель, используем рекомендованную
                print(f"⚠️ ИИ выбрал недоступную модель {ai_selected}, используем рекомендованную: {primary_model}")
                return primary_model
                
        except Exception as e:
            print(f"⚠️ Ошибка ИИ выбора модели: {e}, используем конфигурацию")
            # Fallback на конфигурацию
            task_key = task_type.value
            task_config = self.config.get("task_model_mapping", {}).get(task_key, {})
            if not task_config:
                task_config = self.config.get("task_model_mapping", {}).get("response_generation", {})
            return task_config.get("primary", "ollama:llama3:8b")
    
    async def _ensure_model_available(self, model_config: str):
        """
        Проверяет доступность модели и загружает её при необходимости
        ВАЖНО: Автоматическая загрузка отключена по умолчанию.
        Модели загружаются только по требованию пользователя через API.
        """
        # Проверяем, включена ли автоматическая загрузка
        # По умолчанию отключена (False), чтобы не загружать модели без разрешения пользователя
        auto_load_config = self.config.get("auto_model_loading", {})
        if not auto_load_config.get("enabled", False) or not auto_load_config.get("auto_load_missing_models", False):
            # Автоматическая загрузка отключена - просто проверяем доступность
            if model_config.startswith("ollama:"):
                model_name = model_config.replace("ollama:", "")
                available_models = await self.get_available_models()
                if model_config not in available_models:
                    print(f"⚠️ Модель {model_name} недоступна. Используйте API /api/models/load для ручной загрузки.")
            return
        
        if not model_config.startswith("ollama:"):
            # Для не-Ollama моделей просто проверяем доступность
            return
        
        model_name = model_config.replace("ollama:", "")
        
        # Проверяем доступность Ollama
        working_url = await find_working_ollama_url(timeout=2.0)
        if not working_url:
            print(f"⚠️ Ollama недоступен, не можем проверить модель {model_name}")
            return
        
        # Проверяем, есть ли модель в списке доступных
        available_models = await self.get_available_models()
        model_full_name = f"ollama:{model_name}"
        
        if model_full_name in available_models:
            print(f"✅ Модель {model_name} доступна")
            return
        
        # Модель недоступна - пытаемся загрузить
        print(f"📥 Модель {model_name} недоступна, начинаем автоматическую загрузку...")
        try:
            timeout = auto_load_config.get("load_timeout_seconds", 300)
            await self._auto_load_model(model_name, working_url, timeout)
        except Exception as e:
            print(f"⚠️ Ошибка автоматической загрузки модели {model_name}: {e}")
            # Продолжаем работу с fallback моделью
    
    async def _auto_load_model(self, model_name: str, ollama_url: str, timeout: float = 300.0):
        """
        Автоматически загружает модель через Ollama API с отслеживанием прогресса
        
        Args:
            model_name: Название модели (например, "llama3:8b")
            ollama_url: URL Ollama сервера
            timeout: Таймаут загрузки в секундах
        """
        import httpx
        
        try:
            print(f"🚀 Начинаем загрузку модели {model_name}...")
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                # Начинаем загрузку
                async with client.stream(
                    "POST",
                    f"{ollama_url}/api/pull",
                    json={"name": model_name},
                    timeout=timeout
                ) as response:
                    if response.status_code != 200:
                        raise Exception(f"HTTP {response.status_code}: {await response.aread()}")
                    
                    # Отслеживаем прогресс загрузки
                    last_percent = -1
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                status = data.get("status", "")
                                
                                if status == "success":
                                    print(f"✅ Модель {model_name} успешно загружена и готова к использованию")
                                    # Обновляем кэш доступных моделей
                                    self._available_models = await self.get_available_models()
                                    break
                                elif status == "downloading" or status == "pulling":
                                    completed = data.get("completed", 0)
                                    total = data.get("total", 0)
                                    if total > 0:
                                        percent = int((completed / total) * 100)
                                        # Показываем прогресс только при изменении на 5% или больше
                                        if percent - last_percent >= 5 or percent == 100:
                                            print(f"📥 Загрузка {model_name}: {percent}% ({self._format_size(completed)} / {self._format_size(total)})")
                                            last_percent = percent
                                elif status == "error":
                                    error_msg = data.get("error", "Неизвестная ошибка")
                                    raise Exception(f"Ошибка загрузки: {error_msg}")
                                    
                            except json.JSONDecodeError:
                                continue
                            except Exception as e:
                                if "Ошибка загрузки" in str(e):
                                    raise
                                continue
                    
        except httpx.TimeoutException:
            print(f"⏱️ Таймаут загрузки модели {model_name} (>{timeout} сек), продолжаем работу")
            raise Exception(f"Таймаут загрузки модели {model_name}")
        except Exception as e:
            raise Exception(f"Ошибка загрузки модели {model_name}: {str(e)}")
    
    def _format_size(self, size_bytes: int) -> str:
        """Форматирует размер в читаемый формат"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"
    
    async def get_llm_for_task_async(
        self,
        task_type: TaskType,
        task_complexity: Optional[Complexity] = None,
        user_override: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        """
        Получает LLM объект для задачи через LangChainLLMService (асинхронная версия)
        
        Args:
            task_type: Тип задачи
            task_complexity: Уровень сложности
            user_override: Пользовательское переопределение
            api_key: API ключ (если требуется)
        
        Returns:
            BaseChatModel: LangChain LLM объект
        """
        model_config = await self.select_model_for_task(task_type, task_complexity, user_override)
        
        # Получаем API ключ если нужен
        if not api_key and (model_config.startswith("mistral:") or 
                           model_config.startswith("openai:") or 
                           model_config.startswith("anthropic:")):
            # Загружаем API ключ из настроек
            try:
                if os.path.exists("backend/ai_settings.json"):
                    with open("backend/ai_settings.json", "r", encoding="utf-8") as f:
                        ai_settings = json.load(f)
                        api_key = ai_settings.get("api_key", "")
            except Exception:
                pass
        
        return self.langchain_service.get_llm(model_config, api_key)
    
    def get_llm_for_task(
        self,
        task_type: TaskType,
        task_complexity: Optional[Complexity] = None,
        user_override: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        """
        Получает LLM объект для задачи через LangChainLLMService (синхронная версия)
        
        Args:
            task_type: Тип задачи
            task_complexity: Уровень сложности
            user_override: Пользовательское переопределение
            api_key: API ключ (если требуется)
        
        Returns:
            BaseChatModel: LangChain LLM объект
        """
        import asyncio
        try:
            # Пытаемся получить текущий event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если цикл уже запущен, используем дефолтную модель
                print("⚠️ Event loop уже запущен, используем модель по умолчанию")
                model_config = user_override or "ollama:llama3:8b"
            else:
                model_config = loop.run_until_complete(
                    self.select_model_for_task(task_type, task_complexity, user_override)
                )
        except RuntimeError:
            # Нет event loop, создаем новый
            model_config = asyncio.run(
                self.select_model_for_task(task_type, task_complexity, user_override)
            )
        except Exception as e:
            print(f"⚠️ Ошибка получения модели: {e}, используем модель по умолчанию")
            model_config = user_override or "ollama:llama3:8b"
        
        # Получаем API ключ если нужен
        if not api_key and (model_config.startswith("mistral:") or 
                           model_config.startswith("openai:") or 
                           model_config.startswith("anthropic:")):
            # Загружаем API ключ из настроек
            try:
                if os.path.exists("backend/ai_settings.json"):
                    with open("backend/ai_settings.json", "r", encoding="utf-8") as f:
                        ai_settings = json.load(f)
                        api_key = ai_settings.get("api_key", "")
            except Exception:
                pass
        
        return self.langchain_service.get_llm(model_config, api_key)
    
    async def register_model_usage(
        self,
        model_name: str,
        task_type: TaskType,
        success: bool,
        response_time: Optional[float] = None
    ):
        """Регистрирует использование модели для метрик"""
        if not self.config.get("performance_tracking", {}).get("enabled", True):
            return
        
        metric_key = f"{model_name}:{task_type.value}"
        
        if metric_key not in self._performance_metrics:
            self._performance_metrics[metric_key] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_response_time": 0.0,
                "average_response_time": 0.0,
                "success_rate": 0.0
            }
        
        metrics = self._performance_metrics[metric_key]
        metrics["total_requests"] += 1
        
        if success:
            metrics["successful_requests"] += 1
        else:
            metrics["failed_requests"] += 1
        
        if response_time is not None:
            metrics["total_response_time"] += response_time
            metrics["average_response_time"] = metrics["total_response_time"] / metrics["total_requests"]
        
        metrics["success_rate"] = metrics["successful_requests"] / metrics["total_requests"] if metrics["total_requests"] > 0 else 0.0
    
    def get_model_performance(self, model_name: Optional[str] = None, task_type: Optional[TaskType] = None) -> Dict[str, Any]:
        """Получает метрики производительности модели"""
        if model_name and task_type:
            metric_key = f"{model_name}:{task_type.value}"
            return self._performance_metrics.get(metric_key, {})
        elif model_name:
            # Все метрики для модели
            return {k: v for k, v in self._performance_metrics.items() if k.startswith(f"{model_name}:")}
        elif task_type:
            # Все метрики для задачи
            return {k: v for k, v in self._performance_metrics.items() if k.endswith(f":{task_type.value}")}
        else:
            # Все метрики
            return self._performance_metrics
    
    async def get_available_models(self) -> List[str]:
        """Получает список доступных моделей (Ollama + API)"""
        available_models = []
        
        # Получаем модели Ollama
        try:
            ollama_models = await self.ai_service.get_ollama_models()
            available_models.extend([f"ollama:{model.get('name', '')}" for model in ollama_models if model.get('name')])
        except Exception as e:
            print(f"⚠️ Ошибка получения списка моделей Ollama: {e}")
        
        # Добавляем стандартные API модели
        api_models = [
            # Mistral
            "mistral:mistral-small-latest",
            "mistral:mistral-medium-latest",
            "mistral:mistral-large-latest",
            # OpenAI
            "openai:gpt-4",
            "openai:gpt-4-turbo",
            "openai:gpt-3.5-turbo",
            # Anthropic
            "anthropic:claude-3-opus-20240229",
            "anthropic:claude-3-sonnet-20240229",
            "anthropic:claude-3-haiku-20240307",
            # DeepSeek (если поддерживается)
            "deepseek:deepseek-chat",
            "deepseek:deepseek-reasoner"
        ]
        
        available_models.extend(api_models)
        
        return available_models
    
    def reload_config(self):
        """Перезагружает конфигурацию"""
        self.config = self._load_config()
        print("✅ Конфигурация оркестратора перезагружена")

