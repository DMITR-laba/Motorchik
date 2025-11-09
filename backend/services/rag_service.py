from typing import List, Dict, Any, Tuple, Optional
import time
import os
import re
from app.core.config import settings
from services.database_service import DatabaseService
from services.document_service import DocumentService
from services.elasticsearch_service import ElasticsearchService
from models.database import Article, Car, UsedCar
import json
# ChromaDB отключена - используем только PostgreSQL и Elasticsearch
# import chromadb
# from chromadb.config import Settings as ChromaSettings
import requests
import httpx
try:
    import spacy  # optional NER for cities
except Exception:
    spacy = None

# Для автоматической транслитерации
try:
    from transliterate import translit
    TRANSLITERATE_AVAILABLE = True
except ImportError:
    try:
        # Fallback на unidecode
        from unidecode import unidecode
        TRANSLITERATE_AVAILABLE = "unidecode"
    except ImportError:
        TRANSLITERATE_AVAILABLE = False


def _load_ai_settings() -> Dict[str, Any]:
    """Загружает настройки AI из файла"""
    try:
        if os.path.exists("ai_settings.json"):
            with open("ai_settings.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Ошибка загрузки настроек AI: {e}")
    
    # Возвращаем настройки по умолчанию
    return {
        "response_model": "",
        "embedding_model": "",
        "api_service": "mistral",
        "api_key": "",
        "updated_at": None
    }

def _get_current_model_info() -> Dict[str, str]:
    """Возвращает информацию о текущей модели для ответов"""
    ai_settings = _load_ai_settings()
    response_model = ai_settings.get("response_model", "")
    
    if not response_model:
        return {
            "model_name": settings.mistral_model,
            "model_type": "mistral",
            "display_name": f"Mistral: {settings.mistral_model}"
        }
    
    if response_model.startswith("ollama:"):
        model_name = response_model.replace("ollama:", "")
        return {
            "model_name": model_name,
            "model_type": "ollama",
            "display_name": f"Ollama: {model_name}"
        }
    elif response_model.startswith("mistral:"):
        model_name = response_model.replace("mistral:", "")
        return {
            "model_name": model_name,
            "model_type": "mistral",
            "display_name": f"Mistral: {model_name}"
        }
    elif response_model.startswith("openai:"):
        model_name = response_model.replace("openai:", "")
        return {
            "model_name": model_name,
            "model_type": "openai",
            "display_name": f"OpenAI: {model_name}"
        }
    elif response_model.startswith("anthropic:"):
        model_name = response_model.replace("anthropic:", "")
        return {
            "model_name": model_name,
            "model_type": "anthropic",
            "display_name": f"Anthropic: {model_name}"
        }
    else:
        return {
            "model_name": response_model,
            "model_type": "unknown",
            "display_name": response_model
        }

async def _generate_with_ai_settings(prompt: str) -> tuple[str, Dict[str, str]]:
    """Генерирует ответ используя настройки AI и возвращает информацию о модели"""
    ai_settings = _load_ai_settings()
    response_model = ai_settings.get("response_model", "")
    model_info = _get_current_model_info()
    
    # Если модель не настроена, используем Mistral по умолчанию
    if not response_model:
        try:
            response = _generate_with_mistral(prompt)
            return response, model_info
        except Exception as e:
            return f"Ошибка генерации ответа: {str(e)}", model_info
    
    # Генерируем ответ в зависимости от типа модели
    try:
        if response_model.startswith("ollama:"):
            model_name = response_model.replace("ollama:", "")
            response = await _generate_with_ollama_async(model_name, prompt)
            return response, model_info
        elif response_model.startswith("mistral:"):
            model_name = response_model.replace("mistral:", "")
            api_key = ai_settings.get("api_key", settings.mistral_api_key)
            response = await _generate_with_mistral_async(model_name, api_key, prompt)
            return response, model_info
        elif response_model.startswith("openai:"):
            model_name = response_model.replace("openai:", "")
            api_key = ai_settings.get("api_key", "")
            response = await _generate_with_openai_async(model_name, api_key, prompt)
            return response, model_info
        elif response_model.startswith("anthropic:"):
            model_name = response_model.replace("anthropic:", "")
            api_key = ai_settings.get("api_key", "")
            response = await _generate_with_anthropic_async(model_name, api_key, prompt)
            return response, model_info
        else:
            # Фолбэк на Mistral
            response = _generate_with_mistral(prompt)
            return response, model_info
    except Exception as e:
        # Фолбэк на Mistral при ошибке
        try:
            response = _generate_with_mistral(prompt)
            return response, model_info
        except Exception as fallback_e:
            return f"Ошибка генерации ответа: {str(e)}", model_info

async def _generate_with_ollama_async(model_name: str, prompt: str) -> str:
    """Генерация ответа через Ollama"""
    from services.ollama_utils import find_working_ollama_url
    
    # Находим рабочий URL для Ollama
    working_url = await find_working_ollama_url(timeout=2.0)
    if not working_url:
        raise Exception("Не удается подключиться к Ollama. Проверьте, что Ollama запущен.")

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{working_url}/api/generate", json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
    except Exception as e:
        raise Exception(f"Ошибка при обращении к Ollama по адресу {working_url}: {str(e)}")

async def _generate_with_mistral_async(model_name: str, api_key: str, prompt: str) -> str:
    """Генерация ответа через Mistral API"""
    url = f"{settings.mistral_base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "Ты — полезный ассистент, отвечай кратко и по-русски."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 8192,  # Увеличено для полных ответов
        "stream": False,
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {}).get("content", "")
            return message or ""
        return ""

async def _generate_with_openai_async(model_name: str, api_key: str, prompt: str) -> str:
    """Генерация ответа через OpenAI API"""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "Ты — полезный ассистент, отвечай кратко и по-русски."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 3072,
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {}).get("content", "")
            return message or ""
        return ""

async def _generate_with_anthropic_async(model_name: str, api_key: str, prompt: str) -> str:
    """Генерация ответа через Anthropic API"""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01"
    }
    payload = {
        "model": model_name,
        "max_tokens": 3072,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        if content:
            return content[0].get("text", "")
        return ""

def _generate_with_mistral(prompt: str) -> str:
    """
    Генерация ответа через Mistral API с автоматическим переключением на Ollama при ошибках
    """
    url = f"{settings.mistral_base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.mistral_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.mistral_model,
        "messages": [
            {"role": "system", "content": "Ты — полезный ассистент, отвечай кратко и по-русски."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 8192,  # Увеличено для полных ответов
        "stream": False,
    }
    last_err = None
    rate_limit_hit = False
    
    for attempt in range(3):  # до 3 попыток с экспоненциальной задержкой
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            
            # Специальная обработка 429 (Rate Limit)
            if resp.status_code == 429:
                rate_limit_hit = True
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                        print(f"⚠️ Mistral AI: Rate limit достигнут. Retry-After: {delay} сек. Переключение на Ollama...")
                    except:
                        delay = 0.5 * (2 ** attempt)
                else:
                    delay = 0.5 * (2 ** attempt)
                    print(f"⚠️ Mistral AI: Rate limit достигнут. Переключение на Ollama...")
                
                # Если задержка слишком большая (>30 сек) или это последняя попытка, сразу переключаемся на Ollama
                if delay > 30 or attempt >= 2:
                    break
                
                time.sleep(min(delay, 30.0))
                continue
            
            # Обработка других ошибок
            if resp.status_code != 200:
                error_text = resp.text[:200] if resp.text else "Неизвестная ошибка"
                print(f"⚠️ Mistral AI: HTTP {resp.status_code} - {error_text}")
                if resp.status_code == 401:
                    print("❌ Ошибка авторизации Mistral AI. Проверьте API ключ.")
                elif resp.status_code >= 500:
                    print(f"⚠️ Mistral AI: Серверная ошибка. Попытка {attempt + 1}/3")
                    if attempt < 2:
                        time.sleep(0.5 * (2 ** attempt))
                        continue
                # Для других ошибок переключаемся на Ollama
                break
            
            # Успешный ответ
            resp.raise_for_status()
            data = resp.json() or {}
            choices = data.get("choices") or []
            if choices:
                message = (choices[0].get("message") or {}).get("content", "")
                if message:
                    return message
            
            print("⚠️ Mistral AI: Получен пустой ответ")
            break
            
        except requests.exceptions.Timeout:
            print(f"⚠️ Mistral AI: Таймаут при попытке {attempt + 1}/3")
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            break
        except requests.exceptions.ConnectionError:
            print(f"⚠️ Mistral AI: Ошибка подключения при попытке {attempt + 1}/3")
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            break
        except Exception as e:
            last_err = e
            print(f"⚠️ Mistral AI: Ошибка {type(e).__name__}: {str(e)[:100]}")
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            break
    
    # Фолбэк на локальный Ollama при ошибке/лимите Mistral
    print("🔄 Переключение на Ollama...")
    try:
        ollama_response = _generate_with_ollama_standalone(prompt)
        if ollama_response:
            print("✅ Ollama успешно сгенерировал ответ")
            return ollama_response
        else:
            print("❌ Ollama вернул пустой ответ")
    except Exception as ollama_err:
        print(f"❌ Ollama недоступен: {type(ollama_err).__name__}: {str(ollama_err)[:100]}")
    
    # Если и Ollama не работает, возвращаем вежливый ответ
    error_msg = "Извините, временно недоступен сервис генерации. Повторите попытку позже."
    if rate_limit_hit:
        error_msg += " (Превышен лимит запросов к Mistral AI)"
    return error_msg


def _generate_with_ollama_standalone(prompt: str) -> str:
    """
    Standalone функция для генерации через Ollama (для использования в _generate_with_mistral)
    """
    import requests
    import asyncio
    from services.ollama_utils import find_working_ollama_url
    
    # Используем async функцию для поиска рабочего URL
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    working_url = loop.run_until_complete(find_working_ollama_url(timeout=2.0))
    if not working_url:
        raise Exception("Не удается подключиться к Ollama. Проверьте, что Ollama запущен.")
    
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False
    }
    
    try:
        resp = requests.post(f"{working_url}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        response_text = data.get("response", "")
        if response_text:
            return response_text
        raise Exception("Пустой ответ от Ollama")
    except Exception as e:
        raise Exception(f"Ошибка при обращении к Ollama по адресу {working_url}: {str(e)}")


class RAGService:
    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
        self.doc_service = DocumentService(db_service.db)
        # Elasticsearch (опционально)
        try:
            self.es_service = ElasticsearchService()
        except Exception:
            self.es_service = None
        # ChromaDB отключена - используем только PostgreSQL и Elasticsearch
        self.chroma_client = None
        self.collection = None
        self.cars_collection = None
        self.used_cars_collection = None
        print("ℹ️ ChromaDB отключена. Используется PostgreSQL + Elasticsearch")
    
    async def generate_response(self, user_question: str, user_id: str, chat_history: Optional[List[Dict[str, Any]]] = None,
                               preloaded_cars: Optional[List[Any]] = None, preloaded_used_cars: Optional[List[Any]] = None) -> Dict[str, Any]:
        """
        Генерирует ответ на вопрос пользователя используя RAG подход
        
        Args:
            user_question: Вопрос пользователя
            user_id: ID пользователя
            chat_history: История диалога (список словарей с ключами 'q' и 'a')
        """
        # Импортируем сервисы управления диалогом
        from services.dialog_state_service import DialogStateService
        from services.dialog_command_processor import DialogCommandProcessor
        
        # Удаляем URL из запроса (Google Drive, http/https ссылки)
        import re
        url_pattern = r'https?://[^\s]+'
        user_question = re.sub(url_pattern, '', user_question).strip()
        
        if not user_question or not user_question.strip():
            return {"response": "Пожалуйста, задайте вопрос.", "related_articles": [], "related_documents": [], "related_cars": [], "related_used_cars": []}
        
        dialog_state = DialogStateService(user_id)
        command_processor = DialogCommandProcessor(dialog_state)
        
        # Определяем тип команды
        command = command_processor.detect_command(user_question)
        
        # Обрабатываем команды
        if command["type"] == "start":
            dialog_state.clear_criteria()
            return await self._handle_start_command(user_id, user_question)
        
        if command["type"] == "reset":
            dialog_state.clear_criteria()
            return await self._handle_reset_command(user_id, user_question)
        
        if command["type"] == "show_results":
            return await self._handle_show_results_command(user_id, user_question, dialog_state)
        
        if command["type"] == "show_filters":
            return await self._handle_show_filters_command(user_id, user_question, dialog_state, command_processor)
        
        if command["type"] == "compare":
            return await self._handle_compare_command(user_id, command, dialog_state)
        
        if command["type"] == "similar":
            return await self._handle_similar_command(user_id, command, dialog_state)
        
        if command["type"] == "help":
            return await self._handle_help_command(user_id, user_question)
        
        if command["type"] == "contextual_question":
            return await self._handle_contextual_question(user_id, user_question, chat_history or [], dialog_state)
        
        # Обычный поиск - продолжаем стандартную обработку
        # 0. Предобработка и расширение вариантов запроса (для опечаток/синонимов/жаргона)
        # Нормализуем запрос (автоматическая транслитерация + словарь синонимов)
        normalized = self._normalize_query(user_question)
        
        # Извлекаем расширенные критерии из запроса
        extended_criteria = command_processor.extract_extended_criteria(user_question, chat_history)
        if extended_criteria:
            dialog_state.update_criteria(extended_criteria)
        
        # Обрабатываем относительные фильтры ("дешевле", "дороже") на основе истории
        normalized_with_history = self._process_relative_price_filters(user_question, normalized, chat_history or [])
        
        # Используем нормализованный запрос с учетом истории для дальнейшей обработки
        normalized = normalized_with_history
        
        # Спец-случай: точный VIN-поиск
        import re
        vin_match = re.search(r"\b([A-HJ-NPR-Z0-9]{11,17})\b", normalized, flags=re.IGNORECASE)
        vin_results: Dict[str, list] = {"cars": [], "used": []}
        if vin_match:
            vin_code = vin_match.group(1).upper()
            car = self.db_service.get_car_by_vin(vin_code)
            if car:
                vin_results["cars"].append(car)
            used = self.db_service.get_used_car_by_vin(vin_code)
            if used:
                vin_results["used"].append(used)
            if vin_results["cars"] or vin_results["used"]:
                # Сформируем краткий ответ без обращения к LLM
                resp_lines = []
                for c in vin_results["cars"]:
                    resp_lines.append(f"Новый: {c.mark or ''} {c.model or ''} — {c.city or ''}, {c.price or ''} ₽, VIN: {c.vin}")
                for c in vin_results["used"]:
                    resp_lines.append(f"С пробегом: {c.mark or ''} {c.model or ''} — {c.city or ''}, {c.price or ''} ₽, {c.mileage or 0} км, VIN: {c.vin}")
                response_text = "\n".join(resp_lines)
                chat_message = self.db_service.save_chat_message(
                    user_id=user_id, message=user_question, response=response_text, related_article_ids=[]
                )
                return {
                    "response": response_text,
                    "related_articles": [],
                    "related_documents": [],
                    "related_cars": vin_results["cars"],
                    "related_used_cars": vin_results["used"],
                    "model_info": _get_current_model_info(),
                    "message_id": chat_message.id,
                }
        variants = self._expand_query_variants(normalized)

        # 1. Гибридный поиск: семантика + текст + метаданные (теги/категории) + документы + автомобили
        collected: Dict[int, Article] = {}
        collected_docs: Dict[int, Any] = {}
        collected_cars: Dict[int, Car] = {}
        collected_used_cars: Dict[int, UsedCar] = {}
        
        # Разбор исключений вида "кроме BRAND"
        exclude_brands: set[str] = set()
        ex_match = re.findall(r"кроме\s+([A-Za-zА-Яа-я0-9\-]+)", normalized, flags=re.IGNORECASE)
        for ex in ex_match:
            exclude_brands.add(ex.strip().upper())
        
        # Убираем извлечение параметров - используем только семантический поиск

        # Расширяем варианты транслитерацией только марок
        expanded_variants = list(variants)
        for q in variants:
            # Добавляем вариант с транслитерированными марками
            transliterated_q = self._transliterate_brand_only(q)
            if transliterated_q and transliterated_q.lower() != q.lower():
                # Добавляем вариант с транслитерированными марками
                expanded_variants.append(transliterated_q)
        
        for q in expanded_variants:
            # Поиск по статьям (PostgreSQL)
            for art in self.db_service.search_articles_for_rag(q, limit=10):
                collected.setdefault(art.id, art)
            # Поиск по метаданным статей (PostgreSQL)
            for art in self._search_by_meta(q, limit=10):
                collected.setdefault(art.id, art)
            # Поиск по документам (PostgreSQL)
            for doc in self.doc_service.search_documents_for_rag(q, limit=10):
                collected_docs.setdefault(doc.id, doc)
            
            # Поиск по автомобилям через PostgreSQL
            for car in self.db_service.search_cars_for_rag(q, limit=50):
                collected_cars.setdefault(car.id, car)
            for used_car in self.db_service.search_used_cars_for_rag(q, limit=50):
                collected_used_cars.setdefault(used_car.id, used_car)
            
            # Основной поиск через Elasticsearch (более точный и быстрый)
            try:
                if getattr(self, 'es_service', None) and self.es_service.is_available():
                    es_result = self.es_service.search_cars(query=q, limit=100)
                    for hit in es_result.get("hits", []) or []:
                        src = hit.get('_source') or {}
                        car_type = src.get('type')
                        car_id = src.get('id')
                        if car_type == 'car' and car_id is not None:
                            car_obj = self.db_service.get_car(car_id)
                            if car_obj:
                                collected_cars.setdefault(car_obj.id, car_obj)
                        elif car_type == 'used_car' and car_id is not None:
                            used_obj = self.db_service.get_used_car(car_id)
                            if used_obj:
                                collected_used_cars.setdefault(used_obj.id, used_obj)
            except Exception as e:
                print(f"⚠️ Ошибка поиска в Elasticsearch: {e}")
                pass

            # Убираем жесткое ограничение - собираем все релевантные результаты
            if len(collected) >= 10 and len(collected_docs) >= 5 and len(collected_cars) + len(collected_used_cars) >= 20:
                break

        relevant_articles = list(collected.values())[:5]
        relevant_documents = list(collected_docs.values())[:3]
        
        # Применим исключения по брендам
        if exclude_brands:
            collected_cars = {k: v for k, v in collected_cars.items() if (v.mark or '').upper() not in exclude_brands}
            collected_used_cars = {k: v for k, v in collected_used_cars.items() if (v.mark or '').upper() not in exclude_brands}

        # Применяем строгую фильтрацию к результатам поиска
        cars_list = list(collected_cars.values())
        used_cars_list = list(collected_used_cars.values())
        
        # Извлекаем фильтры из запроса
        filters = self._extract_filters_from_query(user_question)
        
        # Проверяем, есть ли явные фильтры (цена, год, пробег, город, марка, модель и т.д.)
        has_explicit_filters = any([
            filters.get('min_price'), filters.get('max_price'),
            filters.get('min_year'), filters.get('max_year'),
            filters.get('min_mileage'), filters.get('max_mileage'),
            filters.get('city'), filters.get('body_type'), filters.get('fuel_type'),
            any(word in normalized.lower() for word in ['toyota', 'bmw', 'mercedes', 'audi', 
                                                         'hyundai', 'kia', 'lada', 'ваз', 'лада'])
        ])
        
        # Если есть строгие фильтры (цена, пробег, год), применяем их
        # Иначе используем все найденные результаты
        if filters:
            relevant_cars, relevant_used_cars = self._apply_strict_filters(
                cars_list, used_cars_list, user_question
            )
            # Если после строгой фильтрации ничего не осталось, возвращаем исходные результаты
            if not relevant_cars and not relevant_used_cars:
                relevant_cars = cars_list
                relevant_used_cars = used_cars_list
        else:
            # Нет строгих фильтров - используем все найденные результаты
            relevant_cars = cars_list
            relevant_used_cars = used_cars_list
        
        # Убираем жесткое ограничение - возвращаем все релевантные результаты
        # Ограничиваем только для производительности (максимум 50 каждого типа)
        relevant_cars = relevant_cars[:50]
        relevant_used_cars = relevant_used_cars[:50]
        
        # Если нет явных фильтров - собираем статистику для ИИ
        cars_statistics = None
        if not has_explicit_filters:
            try:
                cars_statistics = self.db_service.get_cars_statistics()
            except Exception as e:
                print(f"⚠️ Ошибка получения статистики: {e}")
                cars_statistics = None
        
        if not relevant_articles and not relevant_documents and not relevant_cars and not relevant_used_cars:
            # Нет релевантов — ответим через AI без контекста кратко
            try:
                ai_response, model_info = await _generate_with_ai_settings(self._create_prompt(user_question, "", cars_statistics=None))
            except Exception as e:
                ai_response = f"Извините, сейчас не удалось обработать запрос: {e}"
                model_info = _get_current_model_info()
            chat_message = self.db_service.save_chat_message(
                user_id=user_id,
                message=user_question,
                response=ai_response,
                related_article_ids=[]
            )
            return {
                "response": ai_response,
                "related_articles": [],
                "related_documents": [],
                "related_cars": [],
                "related_used_cars": [],
                "model_info": model_info,
                "message_id": chat_message.id
            }
        
        # 2. Формируем список автомобилей для контекста
        # ПРИОРИТЕТ: предзагруженные автомобили из sources_data > Elasticsearch > БД результаты
        context_cars = []
        context_used_cars = []
        
        # Сначала добавляем предзагруженные автомобили из sources_data (если есть)
        if preloaded_cars:
            context_cars.extend(preloaded_cars)
            print(f"✅ Добавлено {len(preloaded_cars)} новых автомобилей из sources_data в контекст")
        if preloaded_used_cars:
            context_used_cars.extend(preloaded_used_cars)
            print(f"✅ Добавлено {len(preloaded_used_cars)} подержанных автомобилей из sources_data в контекст")
        
        # Если предзагруженных автомобилей нет или их мало, пытаемся получить из Elasticsearch
        if len(context_cars) + len(context_used_cars) < 10:  # Увеличиваем лимит до 10 для лучшего контекста
            try:
                if getattr(self, 'es_service', None) and self.es_service.is_available():
                    # Получаем из Elasticsearch для более точного контекста
                    from services.dialog_command_processor import DialogCommandProcessor
                    from services.dialog_state_service import DialogStateService
                    dialog_state_temp = DialogStateService(user_id)
                    command_processor_temp = DialogCommandProcessor(dialog_state_temp)
                    extended_criteria = command_processor_temp.extract_extended_criteria(user_question, chat_history or [])
                    
                    f = self._extract_filters_from_query(normalized)
                    es_filters = {
                        'city': f.get('city'),
                        'body_type': extended_criteria.get('body_type') or f.get('body_type'),
                        'fuel_type': extended_criteria.get('fuel_type') or f.get('fuel_type'),
                        'gear_box_type': extended_criteria.get('gear_box_type'),
                        'driving_gear_type': extended_criteria.get('driving_gear_type'),
                        'color': extended_criteria.get('color'),
                        'interior_color': extended_criteria.get('interior_color'),
                        'options': extended_criteria.get('options'),
                        'min_price': f.get('min_price'),
                        'max_price': f.get('max_price'),
                        'min_year': extended_criteria.get('min_year') or f.get('min_year'),
                        'max_year': f.get('max_year'),
                        'min_mileage': f.get('min_mileage'),
                        'max_mileage': extended_criteria.get('max_mileage') or f.get('max_mileage'),
                    }
                    
                    es_resp = self.es_service.search_cars(
                        query=user_question,
                        **{k: v for k, v in es_filters.items() if v is not None},
                        limit=10  # Увеличиваем лимит
                    )
                    es_results = (es_resp or {}).get('hits', [])[:10]
                    
                    # Загружаем полные объекты из БД для результатов ES
                    existing_car_ids = {car.id for car in context_cars}
                    existing_used_car_ids = {car.id for car in context_used_cars}
                    
                    for hit in es_results:
                        src = hit.get('_source', {})
                        car_id = src.get('id')
                        car_type = src.get('type')
                        
                        if car_type == 'car' and car_id and car_id not in existing_car_ids:
                            car = self.db_service.get_car(car_id)
                            if car:
                                context_cars.append(car)
                                existing_car_ids.add(car_id)
                        elif car_type == 'used_car' and car_id and car_id not in existing_used_car_ids:
                            used_car = self.db_service.get_used_car(car_id)
                            if used_car:
                                context_used_cars.append(used_car)
                                existing_used_car_ids.add(car_id)
            except Exception as e:
                print(f"⚠️ Ошибка получения автомобилей из ES: {e}")
        
        # Если все еще недостаточно, дополняем из результатов БД поиска
        if len(context_cars) + len(context_used_cars) < 10:
            existing_car_ids = {car.id for car in context_cars}
            existing_used_car_ids = {car.id for car in context_used_cars}
            
            # Добавляем из relevant_cars и relevant_used_cars
            for c in relevant_cars:
                if c.id not in existing_car_ids and len(context_cars) < 10:
                    context_cars.append(c)
                    existing_car_ids.add(c.id)
            for c in relevant_used_cars:
                if c.id not in existing_used_car_ids and len(context_used_cars) < 10:
                    context_used_cars.append(c)
                    existing_used_car_ids.add(c.id)
        
        # 3. Формирование контекста (используем все найденные автомобили, до 10 каждого типа)
        # ВАЖНО: Если есть предзагруженные автомобили из sources_data, используем ВСЕ их (не ограничиваем)
        final_context_cars = context_cars[:10] if not preloaded_cars else context_cars
        final_context_used_cars = context_used_cars[:10] if not preloaded_used_cars else context_used_cars
        
        print(f"📊 Итого автомобилей в контексте: новых={len(final_context_cars)}, подержанных={len(final_context_used_cars)}")
        
        context = self._build_context(relevant_articles, relevant_documents, final_context_cars, final_context_used_cars)
        
        # 4. Создание промта для LLM (с учетом истории диалога и статистики)
        prompt = self._create_prompt(user_question, context, chat_history=chat_history or [], cars_statistics=cars_statistics)
        
        # 5. Генерация ответа с использованием настроек AI
        try:
            ai_response, model_info = await _generate_with_ai_settings(prompt)
        except Exception as e:
            ai_response = f"Произошла ошибка при обработке запроса: {str(e)}. Пожалуйста, обратитесь к службе поддержки."
            model_info = _get_current_model_info()
        
        # 6. Сохранение сообщения в БД
        related_article_ids = [article.id for article in relevant_articles]
        related_document_ids = [doc.id for doc in relevant_documents]
        # Автомобили сохраняем отдельно, но можем добавить в related_article_ids для совместимости
        all_related_ids = related_article_ids + related_document_ids
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id,
            message=user_question,
            response=ai_response,
            related_article_ids=all_related_ids
        )
        
        # Сохраняем показанные автомобили в состояние диалога
        try:
            from services.dialog_state_service import DialogStateService
            dialog_state = DialogStateService(user_id)
            
            # Форматируем автомобили для сохранения
            shown_cars = []
            for car in (relevant_cars + relevant_used_cars)[:10]:
                shown_cars.append({
                    "id": car.id,
                    "mark": car.mark,
                    "model": car.model,
                    "price": car.price,
                    "year": car.manufacture_year,
                    "mileage": getattr(car, 'mileage', None),
                })
            dialog_state.set_last_shown_cars(shown_cars)
            
            # Сохраняем результаты поиска
            dialog_state.save_search_results({
                "cars": [{"id": c.id, "mark": c.mark, "model": c.model, "price": c.price} for c in relevant_cars],
                "used_cars": [{"id": c.id, "mark": c.mark, "model": c.model, "price": c.price} for c in relevant_used_cars],
            })
        except Exception as e:
            print(f"⚠️ Ошибка сохранения состояния диалога: {e}")
        
        return {
            "response": ai_response,
            "related_articles": relevant_articles,
            "related_documents": relevant_documents,
            "related_cars": relevant_cars,
            "related_used_cars": relevant_used_cars,
            "model_info": model_info,
            "message_id": chat_message.id
        }

    def _transliterate_text(self, text: str) -> str:
        """Автоматическая транслитерация кириллицы в латиницу"""
        if not text:
            return text
        
        try:
            if TRANSLITERATE_AVAILABLE is True:
                # Используем transliterate (более точная транслитерация для русского)
                return translit(text, 'ru', reversed=True)
            elif TRANSLITERATE_AVAILABLE == "unidecode":
                # Fallback на unidecode (универсальная, но менее точная)
                return unidecode(text)
            else:
                return text
        except Exception:
            return text
    
    def _get_brand_mappings(self) -> Dict[str, str]:
        """Возвращает словарь марок (кириллица -> латиница)"""
        return {
            # Российские
            "лада": "lada",
            "ваз": "lada",
            "газ": "gaz",
            "москвич": "moskvich",
            "уаз": "uaz",
            "тагаз": "tagaz",
            "aurus": "aurus",
            
            # Китайские
            "джили": "geely",
            "гели": "geely",
            "чаери": "chery",
            "черри": "chery",
            "chery": "chery",
            "хавал": "haval",
            "haval": "haval",
            "great wall": "haval",
            "greatwall": "haval",
            "gwm": "haval",
            "донгфенг": "dongfeng",
            "донг фенг": "dongfeng",
            "dongfeng": "dongfeng",
            "омода": "omoda",
            "omoda": "omoda",
            "як": "jac",
            "джак": "jac",
            "jac": "jac",
            "джей эй си": "jac",
            "лифан": "lifan",
            "lifan": "lifan",
            "чанган": "changan",
            "changan": "changan",
            "exeed": "exeed",
            "gac": "gac",
            "brilliance": "brilliance",
            "byd": "byd",
            "haima": "haima",
            "kaiyi": "kaiyi",
            "luxgen": "luxgen",
            "tank": "tank",
            "zeekr": "zeekr",
            "zotye": "zotye",
            
            # Японские
            "мазда": "mazda",
            "мазд": "mazda",
            "mazda": "mazda",
            "тойота": "toyota",
            "тойот": "toyota",
            "toyota": "toyota",
            "хонда": "honda",
            "honda": "honda",
            "ниссан": "nissan",
            "nissan": "nissan",
            "митсубиси": "mitsubishi",
            "мицубиси": "mitsubishi",
            "mitsubishi": "mitsubishi",
            "субару": "subaru",
            "subaru": "subaru",
            "лексус": "lexus",
            "lexus": "lexus",
            "акура": "acura",
            "acura": "acura",
            "дайхацу": "daihatsu",
            "daihatsu": "daihatsu",
            "дацун": "datsun",
            "datsun": "datsun",
            "инфинити": "infiniti",
            "infiniti": "infiniti",
            "исузу": "isuzu",
            "isuzu": "isuzu",
            "сузуки": "suzuki",
            "suzuki": "suzuki",
            "scion": "scion",
            
            # Немецкие
            "бмв": "bmw",
            "бэмвэ": "bmw",
            "bmw": "bmw",
            "мерседес": "mercedes",
            "мерс": "mercedes",
            "mercedes": "mercedes",
            "ауди": "audi",
            "audi": "audi",
            "фольксваген": "volkswagen",
            "фольк": "volkswagen",
            "volkswagen": "volkswagen",
            "vw": "volkswagen",
            "опель": "opel",
            "opel": "opel",
            "порше": "porsche",
            "porsche": "porsche",
            
            # Корейские
            "хёндай": "hyundai",
            "хюндай": "hyundai",
            "хендай": "hyundai",
            "hyundai": "hyundai",
            "киа": "kia",
            "kia": "kia",
            "дэу": "daewoo",
            "даэу": "daewoo",
            "daewoo": "daewoo",
            "генезис": "genesis",
            "genesis": "genesis",
            "ссанг йонг": "ssangyong",
            "ssangyong": "ssangyong",
            
            # Американские
            "форд": "ford",
            "ford": "ford",
            "шевроле": "chevrolet",
            "шеви": "chevrolet",
            "chevrolet": "chevrolet",
            "chevy": "chevrolet",
            "бюик": "buick",
            "buick": "buick",
            "кадиллак": "cadillac",
            "cadillac": "cadillac",
            "линкольн": "lincoln",
            "lincoln": "lincoln",
            "понтиак": "pontiac",
            "pontiac": "pontiac",
            "тесла": "tesla",
            "tesla": "tesla",
            "chrysler": "chrysler",
            "dodge": "dodge",
            "gmc": "gmc",
            "hummer": "hummer",
            "jeep": "jeep",
            "mercury": "mercury",
            "oldsmobile": "oldsmobile",
            
            # Европейские
            "вольво": "volvo",
            "volvo": "volvo",
            "рено": "renault",
            "renault": "renault",
            "пежо": "peugeot",
            "peugeot": "peugeot",
            "ситроен": "citroen",
            "ситрон": "citroen",
            "citroen": "citroen",
            "сеат": "seat",
            "seat": "seat",
            "скада": "skoda",
            "шкода": "skoda",
            "skoda": "skoda",
            "фиат": "fiat",
            "fiat": "fiat",
            "альфа ромео": "alfa romeo",
            "альфа": "alfa romeo",
            "alfa romeo": "alfa romeo",
            "мазерати": "maserati",
            "maserati": "maserati",
            "ламборгини": "lamborghini",
            "lamborghini": "lamborghini",
            "феррари": "ferrari",
            "ferrari": "ferrari",
            "бентли": "bentley",
            "bentley": "bentley",
            "роллс-ройс": "rolls-royce",
            "роллс": "rolls-royce",
            "rolls-royce": "rolls-royce",
            "rolls royce": "rolls-royce",
            "aston martin": "aston martin",
            "bugatti": "bugatti",
            "ds": "ds",
            "jaguar": "jaguar",
            "lancia": "lancia",
            "land rover": "land rover",
            "maybach": "maybach",
            "mini": "mini",
            "ravon": "ravon",
            "rover": "rover",
            "saab": "saab",
            "smart": "smart",
            "zaz": "zaz",
        }
    
    def _transliterate_brand_only(self, text: str) -> str:
        """Транслитерирует только марки автомобилей в тексте, остальное не трогает"""
        if not text:
            return text
        
        brand_mappings = self._get_brand_mappings()
        words = text.split()
        result_words = []
        
        for word in words:
            word_lower = word.lower()
            word_original = word  # Сохраняем оригинальный регистр
            
            # Проверяем, является ли слово маркой (с учетом регистра)
            found_brand = None
            for cyrillic_brand, latin_brand in brand_mappings.items():
                if word_lower == cyrillic_brand or word_lower.startswith(cyrillic_brand):
                    found_brand = latin_brand
                    break
            
            if found_brand:
                # Если слово - марка на кириллице, транслитерируем
                if any('\u0400' <= char <= '\u04FF' for char in word):
                    # Используем автоматическую транслитерацию для марки
                    try:
                        if TRANSLITERATE_AVAILABLE is True:
                            transliterated = translit(word, 'ru', reversed=True)
                        elif TRANSLITERATE_AVAILABLE == "unidecode":
                            transliterated = unidecode(word)
                        else:
                            transliterated = found_brand
                        
                        # Если автоматическая транслитерация дала неправильный результат, используем словарь
                        # Проверяем, похожа ли транслитерация на правильную марку
                        if found_brand.lower() not in transliterated.lower() and transliterated.lower() != found_brand.lower():
                            # Используем правильную марку из словаря
                            result_words.append(found_brand if word.islower() else found_brand.capitalize())
                        else:
                            result_words.append(transliterated)
                    except Exception:
                        # Fallback на словарь
                        result_words.append(found_brand if word.islower() else found_brand.capitalize())
                else:
                    # Уже латиница - оставляем как есть
                    result_words.append(word_original)
            else:
                # Не марка - оставляем как есть
                result_words.append(word_original)
        
        return ' '.join(result_words)
    
    def _normalize_query(self, text: str) -> str:
        """Нормализует запрос: транслитерация только марок + синонимы для остального."""
        if not text:
            return ""
        t = (text or "").strip()
        
        # Транслитерируем только марки, остальное не трогаем
        t = self._transliterate_brand_only(t)
        
        # Словарь синонимов для специальных случаев (НЕ марки - только термины, типы кузова и т.д.)
        # Марки обрабатываются отдельно через _transliterate_brand_only
        replacements = {
            # Программное обеспечение
            "автокад": "AutoCAD",
            "ауто кад": "AutoCAD",
            "виндовс": "Windows",
            "эксель": "Excel",
            "оутлук": "Outlook",
            "аутлук": "Outlook",
            "мс офис": "MS Office",
            "мсо": "MSO",
            "гит": "GIT",
            "сбп": "СБП",
            "мт ": "МТ ",
            " диадок": " Диадок",
            
            # Автомобильные термины
            "автомат": "автоматическая коробка",
            "автоматическая": "автоматическая коробка",
            "акпп": "автоматическая коробка",
            "механика": "механическая коробка",
            "механическая": "механическая коробка",
            "мкпп": "механическая коробка",
            "робот": "роботизированная коробка",
            "вариатор": "вариаторная коробка",
            "cvt": "вариаторная коробка",
            
            # Типы кузова
            "внедорожник": "suv",
            "джип": "suv",
            "кроссовер": "suv",
            "пикап": "pickup",
            "грузовик": "pickup",
            "кабриолет": "кабриолет",
            "купе": "купе",
            "лифтбек": "лифтбек",
            "хетчбек": "хэтчбек",
            "хетч": "хэтчбек",
            
            # Типы топлива
            "дизель": "дизельный",
            "дизельный": "дизельный",
            "гибрид": "гибридный",
            "гибридный": "гибридный",
            "электро": "электрический",
            "электрический": "электрический",
            "газ": "газовый",
            "газовый": "газовый",
            "бензин": "бензиновый",
            "бензиновый": "бензиновый",
            
            # Привод
            "полный привод": "4wd",
            "4wd": "4wd",
            "4x4": "4wd",
            "передний привод": "fwd",
            "fwd": "fwd",
            "задний привод": "rwd",
            "rwd": "rwd",
            
            # Другие термины
            "новый": "новый автомобиль",
            "подержанный": "с пробегом",
            "б/у": "с пробегом",
            "бу": "с пробегом",
            "с пробегом": "с пробегом",
            "минимальный пробег": "с пробегом",
            "малый пробег": "с пробегом"
        }
        # Применяем замены из словаря (только для не-марок: термины, типы кузова и т.д.)
        low = t.lower()
        words = t.split()
        result_words = []
        
        for word in words:
            word_lower = word.lower()
            word_original = word
            replaced = False
            
            # Применяем замены из словаря (только для не-марок)
            for k, v in replacements.items():
                if k == word_lower or word_lower.startswith(k + ' ') or word_lower.endswith(' ' + k):
                    # Заменяем только если это не марка (марки уже обработаны)
                    if k not in self._get_brand_mappings():
                        result_words.append(v)
                        replaced = True
                        break
            
            if not replaced:
                result_words.append(word_original)
        
        t = ' '.join(result_words)
        
        # Нормализуем множественные пробелы
        while "  " in t:
            t = t.replace("  ", " ")
        return t.strip()
    
    def _extract_price_from_text(self, text: str) -> Optional[int]:
        """Извлекает цену из текста (для анализа предыдущих ответов)"""
        if not text:
            return None
        
        import re
        # Ищем цены в форматах: "2 500 000", "2.5 млн", "2500000"
        # Миллионы
        m = re.search(r"(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион)", text.lower())
        if m:
            try:
                val = float(m.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
                return int(val * 1_000_000)
            except Exception:
                pass
        
        # Тысячи
        m = re.search(r"(\d+[\s\u00A0]*[.,]??\d*)\s*(тыс|тысяч)", text.lower())
        if m:
            try:
                val = float(m.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
                return int(val * 1_000)
            except Exception:
                pass
        
        # Прямая цена (5-9 цифр)
        m = re.search(r"(\d{5,9})\s*₽", text)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        
        # Цена с пробелами: "1 500 000", "2 000 000"
        m = re.search(r"(\d{1,3}(?:\s+\d{3}){2,})", text)
        if m:
            try:
                # Удаляем пробелы и преобразуем
                price_str = m.group(1).replace(' ', '').replace('\u00a0', '')
                price = int(price_str)
                # Проверяем, что это разумная цена (от 100000 до 100000000)
                if 100000 <= price <= 100000000:
                    return price
            except Exception:
                pass
        
        # Цена без символа валюты (5-9 цифр подряд)
        m = re.search(r"\b(\d{5,9})\b", text)
        if m:
            try:
                price = int(m.group(1))
                # Проверяем, что это разумная цена (от 100000 до 100000000)
                if 100000 <= price <= 100000000:
                    return price
            except Exception:
                pass
        
        return None
    
    def _extract_prices_from_cars(self, cars: List[Any], used_cars: List[Any]) -> Optional[int]:
        """Извлекает среднюю/минимальную цену из списка автомобилей"""
        prices = []
        for car in cars:
            if hasattr(car, 'price') and car.price:
                try:
                    price_val = float(str(car.price).replace(' ', '').replace(',', '.'))
                    if price_val > 0:
                        prices.append(price_val)
                except Exception:
                    pass
        
        for car in used_cars:
            if hasattr(car, 'price') and car.price:
                try:
                    price_val = float(str(car.price).replace(' ', '').replace(',', '.'))
                    if price_val > 0:
                        prices.append(price_val)
                except Exception:
                    pass
        
        if prices:
            # Возвращаем минимальную цену (самый дешевый найденный автомобиль)
            return int(min(prices))
        
        return None
    
    def _process_relative_price_filters(self, original_query: str, normalized_query: str, chat_history: List[Dict[str, Any]]) -> str:
        """Обрабатывает относительные фильтры цены ('дешевле', 'дороже') на основе истории"""
        import re
        
        query_lower = original_query.lower()
        has_cheaper = bool(re.search(r"\bдешевле\b", query_lower))
        has_dearer = bool(re.search(r"\bдороже\b", query_lower))
        
        if not (has_cheaper or has_dearer):
            return normalized_query
        
        # Ищем цену в текущем запросе ("дешевле 2 млн")
        price_match = re.search(r"(дешевле|дороже)\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|тыс|тысяч)?", query_lower)
        if price_match:
            # Цена указана явно - ничего дополнительно не делаем
            return normalized_query
        
        # Ищем цену в истории диалога (последние 5 сообщений)
        reference_price = None
        
        # 1. Ищем в ответах AI (могут содержать найденные автомобили с ценами)
        for msg in reversed(chat_history):  # От новых к старым
            response_text = msg.get('a', '') or ''
            
            # Извлекаем цену из текста ответа
            price = self._extract_price_from_text(response_text)
            if price:
                reference_price = price
                break
        
        # 2. Если не нашли в ответах, ищем в запросах пользователя ("покажи машины до 2 млн")
        if reference_price is None:
            for msg in reversed(chat_history):
                query_text = msg.get('q', '') or ''
                
                # Ищем "до X млн" или "от X млн"
                price_match = re.search(r"(до|от)\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|тыс|тысяч)?", query_text.lower())
                if price_match:
                    try:
                        val = float(price_match.group(2).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
                        unit = price_match.group(3) or ''
                        
                        if 'млн' in unit or 'миллион' in unit:
                            reference_price = int(val * 1_000_000)
                        elif 'тыс' in unit or 'тысяч' in unit:
                            reference_price = int(val * 1_000)
                        else:
                            # Если единицы не указаны, считаем миллионами если число < 100, иначе рубли
                            if val < 100:
                                reference_price = int(val * 1_000_000)
                            else:
                                reference_price = int(val)
                        break
                    except Exception:
                        continue
        
        # Если нашли опорную цену, добавляем фильтр
        if reference_price is not None:
            if has_cheaper:
                # "дешевле чем X" -> "до X"
                # Уменьшаем немного для точности (на 10%)
                threshold = int(reference_price * 0.9)
                if threshold >= 1_000_000:
                    normalized_query = f"{normalized_query} до {threshold // 1_000_000} млн".strip()
                else:
                    normalized_query = f"{normalized_query} до {threshold // 1_000} тыс".strip()
            elif has_dearer:
                # "дороже чем X" -> "от X"
                # Увеличиваем немного для точности (на 10%)
                threshold = int(reference_price * 1.1)
                if threshold >= 1_000_000:
                    normalized_query = f"{normalized_query} от {threshold // 1_000_000} млн".strip()
                else:
                    normalized_query = f"{normalized_query} от {threshold // 1_000} тыс".strip()
        
        return normalized_query

    def _expand_query_variants(self, text: str) -> List[str]:
        """Создает набор вариантов запроса для устойчивого поиска (опечатки, аббревиатуры, синонимы)."""
        variants = []
        base = text.strip()
        if not base:
            return [""]
        variants.append(base)

        # Карты синонимов/аббревиатур
        synonym_groups = [
            # Автомобильные бренды с транслитерацией
            ["Mazda", "мазда", "мазд", "Mazda"],
            ["Toyota", "тойота", "тойот", "Toyota"],
            ["BMW", "бмв", "бэмвэ", "BMW"],
            ["Mercedes", "мерседес", "мерс", "Mercedes-Benz"],
            ["Audi", "ауди", "Audi"],
            ["Volkswagen", "фольксваген", "фольк", "VW"],
            ["Hyundai", "хёндай", "хюндай", "хендай"],
            ["Kia", "киа"],
            ["Nissan", "ниссан"],
            ["Ford", "форд"],
            ["Honda", "хонда"],
            ["Lexus", "лексус"],
            ["Chevrolet", "шевроле", "шеви", "Chevy"],
            ["Geely", "джили", "гели"],
            ["Chery", "чаери", "черри", "chery"],
            ["Haval", "хавал", "Great Wall"],
            ["Dongfeng", "донгфенг", "донг фенг"],
            ["Omoda", "омода"],
            ["JAC", "як", "джак", "Jac"],
            ["Lada", "лада", "ваз", "ВАЗ"],
            # Программное обеспечение
            ["AutoCAD", "Автокад", "Autodesk AutoCAD"],
            ["Excel", "Эксель", "MS Excel"],
            ["Outlook", "Аутлук", "MS Outlook"],
            ["Windows", "Виндовс", "MS Windows"],
            ["GIT", "Git", "Система контроля версий GIT"],
            ["МТ", "MT", "МойСклад?", "МТ кассы"],
            ["GLPI", "глпи"],
            ["ОФД", "офд"],
            ["Диадок", "Diadoc"],
        ]

        def add_replaced(orig: str, a: str, b: str):
            if a in orig:
                variants.append(orig.replace(a, b))

        # Сформировать варианты замен по группам
        for group in synonym_groups:
            for a in group:
                for b in group:
                    if a != b:
                        add_replaced(base, a, b)

        # Упростить некоторые фразы
        simplifications = [
            ("Не могу ", "Не удается "),
            ("Ошибка ", "Сбой "),
            ("не работает", "не функционирует"),
        ]
        for a, b in simplifications:
            add_replaced(base, a, b)

        # Добавить англо/рус варианты ключевых слов
        keyword_variants = {
            "dialog": ["dialog", "диалог", "диалоговое окно"],
            "save": ["save", "сохранение", "сохранить"],
            "sync": ["sync", "синхронизация", "синхронизируются"],
        }
        for lst in keyword_variants.values():
            for a in lst:
                for b in lst:
                    if a != b:
                        add_replaced(base, a, b)

        # Дедупликация, ограничение
        seen = set()
        deduped = []
        for v in variants:
            vv = v.strip()
            if vv and vv.lower() not in seen:
                deduped.append(vv)
                seen.add(vv.lower())
            if len(deduped) >= 8:
                break
        return deduped
    
    def _build_context(self, articles: List[Article], documents: List[Any] = None, 
                       cars: List[Car] = None, used_cars: List[UsedCar] = None) -> str:
        """Строит контекст из найденных статей и документов"""
        context_parts = []
        
        # Добавляем статьи
        for i, article in enumerate(articles, 1):
            context_part = f"""
Статья {i}:
Заголовок: {article.title}
Текст: {article.text[:1000]}{'...' if len(article.text) > 1000 else ''}
URL: {article.url or 'Не указан'}
"""
            context_parts.append(context_part)
        
        # Добавляем документы с поиском по чанкам
        if documents:
            for i, doc in enumerate(documents, len(articles) + 1):
                # Ищем релевантные чанки для документа
                relevant_chunks = self._search_document_chunks(doc.id, articles[0].text if articles else "")
                
                context_part = f"""
Документ {i}:
Заголовок: {doc.title or doc.original_filename}
Тема: {doc.topic or 'Не указана'}
Путь: {doc.path or 'Не указан'}
"""
                
                # Добавляем релевантные чанки
                if relevant_chunks:
                    context_part += "Релевантные фрагменты:\n"
                    for j, chunk in enumerate(relevant_chunks[:3], 1):  # Берем до 3 чанков
                        context_part += f"  Фрагмент {j}: {chunk.text[:500]}{'...' if len(chunk.text) > 500 else ''}\n"
                else:
                    # Если чанки не найдены, используем общее содержание
                    context_part += f"Содержание: {doc.extracted_text[:1000] if doc.extracted_text else 'Не извлечено'}{'...' if doc.extracted_text and len(doc.extracted_text) > 1000 else ''}\n"
                
                context_part += f"Краткое содержание: {doc.summary or 'Не создано'}\n"
                context_parts.append(context_part)
        
        # Добавляем новые автомобили со всеми полями
        if cars:
            for i, car in enumerate(cars, len(articles) + len(documents or []) + 1):
                # Формируем полную информацию об автомобиле со всеми полями
                car_fields = []
                car_fields.append(f"ID: {car.id}")
                if car.mark: car_fields.append(f"Марка: {car.mark}")
                if car.model: car_fields.append(f"Модель: {car.model}")
                if car.vin: car_fields.append(f"VIN: {car.vin}")
                if car.title: car_fields.append(f"Название: {car.title}")
                if car.doc_num: car_fields.append(f"Номер документа: {car.doc_num}")
                if car.price: car_fields.append(f"Цена: {car.price} руб.")
                if car.sale_price: car_fields.append(f"Цена продажи: {car.sale_price} руб.")
                if car.stock_qty: car_fields.append(f"Количество на складе: {car.stock_qty}")
                if car.manufacture_year: car_fields.append(f"Год выпуска: {car.manufacture_year}")
                if car.model_year: car_fields.append(f"Год модели: {car.model_year}")
                if car.fuel_type: car_fields.append(f"Тип топлива: {car.fuel_type}")
                if car.power: car_fields.append(f"Мощность: {car.power} л.с.")
                if car.body_type: car_fields.append(f"Тип кузова: {car.body_type}")
                if car.gear_box_type: car_fields.append(f"Коробка передач: {car.gear_box_type}")
                if car.driving_gear_type: car_fields.append(f"Привод: {car.driving_gear_type}")
                if car.engine_vol: car_fields.append(f"Объем двигателя: {car.engine_vol} л")
                if car.engine: car_fields.append(f"Двигатель: {car.engine}")
                if car.fuel_consumption: car_fields.append(f"Расход топлива: {car.fuel_consumption}")
                if car.max_torque: car_fields.append(f"Максимальный крутящий момент: {car.max_torque}")
                if car.acceleration: car_fields.append(f"Разгон: {car.acceleration}")
                if car.max_speed: car_fields.append(f"Максимальная скорость: {car.max_speed}")
                if car.eco_class: car_fields.append(f"Экологический класс: {car.eco_class}")
                if car.color: car_fields.append(f"Цвет: {car.color}")
                if car.interior_color: car_fields.append(f"Цвет салона: {car.interior_color}")
                if car.color_code: car_fields.append(f"Код цвета: {car.color_code}")
                if car.interior_code: car_fields.append(f"Код салона: {car.interior_code}")
                if car.pts_colour: car_fields.append(f"Цвет по ПТС: {car.pts_colour}")
                if car.door_qty: car_fields.append(f"Количество дверей: {car.door_qty}")
                if car.dimensions: car_fields.append(f"Габариты: {car.dimensions}")
                if car.weight: car_fields.append(f"Вес: {car.weight}")
                if car.cargo_volume: car_fields.append(f"Объем багажника: {car.cargo_volume}")
                if car.compl_level: car_fields.append(f"Уровень комплектации: {car.compl_level}")
                if car.code_compl: car_fields.append(f"Код комплектации: {car.code_compl}")
                if car.car_order_int_status: car_fields.append(f"Статус заказа: {car.car_order_int_status}")
                if car.city: car_fields.append(f"Город: {car.city}")
                if car.dealer_center: car_fields.append(f"Дилерский центр: {car.dealer_center}")
                if car.max_additional_discount: car_fields.append(f"Максимальная дополнительная скидка: {car.max_additional_discount}")
                if car.max_discount_trade_in: car_fields.append(f"Максимальная скидка Trade-in: {car.max_discount_trade_in}")
                if car.max_discount_credit: car_fields.append(f"Максимальная скидка по кредиту: {car.max_discount_credit}")
                if car.max_discount_casko: car_fields.append(f"Максимальная скидка КАСКО: {car.max_discount_casko}")
                if car.max_discount_extra_gear: car_fields.append(f"Максимальная скидка на доп. оборудование: {car.max_discount_extra_gear}")
                if car.max_discount_life_insurance: car_fields.append(f"Максимальная скидка на страхование жизни: {car.max_discount_life_insurance}")
                
                car_text = f"""
Автомобиль {i} (новый):
{chr(10).join(car_fields)}
"""
                context_parts.append(car_text)
        
        # Добавляем подержанные автомобили со всеми полями
        if used_cars:
            for i, car in enumerate(used_cars, len(articles) + len(documents or []) + len(cars or []) + 1):
                # Формируем полную информацию об автомобиле со всеми полями
                car_fields = []
                car_fields.append(f"ID: {car.id}")
                if car.mark: car_fields.append(f"Марка: {car.mark}")
                if car.model: car_fields.append(f"Модель: {car.model}")
                if car.vin: car_fields.append(f"VIN: {car.vin}")
                if car.title: car_fields.append(f"Название: {car.title}")
                if car.doc_num: car_fields.append(f"Номер документа: {car.doc_num}")
                if car.price: car_fields.append(f"Цена: {car.price} руб.")
                if car.manufacture_year: car_fields.append(f"Год выпуска: {car.manufacture_year}")
                if car.mileage: car_fields.append(f"Пробег: {car.mileage} км")
                if car.owners: car_fields.append(f"Количество владельцев: {car.owners}")
                if car.accident: car_fields.append(f"Аварии: {car.accident}")
                if car.certification_number: car_fields.append(f"Номер сертификата: {car.certification_number}")
                if car.fuel_type: car_fields.append(f"Тип топлива: {car.fuel_type}")
                if car.power: car_fields.append(f"Мощность: {car.power} л.с.")
                if car.body_type: car_fields.append(f"Тип кузова: {car.body_type}")
                if car.gear_box_type: car_fields.append(f"Коробка передач: {car.gear_box_type}")
                if car.driving_gear_type: car_fields.append(f"Привод: {car.driving_gear_type}")
                if car.engine_vol: car_fields.append(f"Объем двигателя: {car.engine_vol} л")
                if car.color: car_fields.append(f"Цвет: {car.color}")
                if car.doors: car_fields.append(f"Количество дверей: {car.doors}")
                if car.wheel_type: car_fields.append(f"Тип руля: {car.wheel_type}")
                if car.category: car_fields.append(f"Категория: {car.category}")
                if car.car_type: car_fields.append(f"Тип автомобиля: {car.car_type}")
                if car.region: car_fields.append(f"Регион: {car.region}")
                if car.city: car_fields.append(f"Город: {car.city}")
                if car.street: car_fields.append(f"Улица: {car.street}")
                if car.dealer_center: car_fields.append(f"Дилерский центр: {car.dealer_center}")
                if car.company_name: car_fields.append(f"Название компании: {car.company_name}")
                if car.manager_name: car_fields.append(f"Менеджер: {car.manager_name}")
                if car.contact_phone: car_fields.append(f"Телефон: {car.contact_phone}")
                if car.generation_id: car_fields.append(f"ID поколения: {car.generation_id}")
                if car.modification_id: car_fields.append(f"ID модификации: {car.modification_id}")
                if car.aaa_max_additional_discount: car_fields.append(f"Максимальная дополнительная скидка: {car.aaa_max_additional_discount}")
                if car.aaa_max_discount_trade_in: car_fields.append(f"Максимальная скидка Trade-in: {car.aaa_max_discount_trade_in}")
                if car.aaa_max_discount_credit: car_fields.append(f"Максимальная скидка по кредиту: {car.aaa_max_discount_credit}")
                if car.aaa_max_discount_casko: car_fields.append(f"Максимальная скидка КАСКО: {car.aaa_max_discount_casko}")
                if car.aaa_max_discount_extra_gear: car_fields.append(f"Максимальная скидка на доп. оборудование: {car.aaa_max_discount_extra_gear}")
                if car.aaa_max_discount_life_insurance: car_fields.append(f"Максимальная скидка на страхование жизни: {car.aaa_max_discount_life_insurance}")
                
                car_text = f"""
Автомобиль {i} (с пробегом):
{chr(10).join(car_fields)}
"""
                context_parts.append(car_text)
        
        return "\n".join(context_parts)
    
    def _search_document_chunks(self, document_id: int, query: str) -> List[Any]:
        """Ищет релевантные чанки в документе"""
        try:
            # Получаем чанки документа
            chunks = self.doc_service.get_document_chunks(document_id)
            if not chunks:
                return []
            
            # Простой поиск по тексту чанков (можно улучшить с помощью семантического поиска)
            relevant_chunks = []
            query_lower = query.lower()
            
            for chunk in chunks:
                if chunk.text and query_lower in chunk.text.lower():
                    relevant_chunks.append(chunk)
            
            # Если точного совпадения нет, берем первые несколько чанков
            if not relevant_chunks and chunks:
                relevant_chunks = chunks[:2]
            
            return relevant_chunks
        except Exception as e:
            print(f"Ошибка при поиске чанков документа {document_id}: {e}")
            return []
    
    def _create_prompt(self, question: str, context: str, chat_history: Optional[List[Dict[str, Any]]] = None, 
                      cars_statistics: Optional[Dict[str, Any]] = None) -> str:
        """Создает промт для LLM (автоэксперт и помощник по подбору авто)."""
        
        # Формируем историю диалога для контекста
        history_context = ""
        if chat_history and len(chat_history) > 0:
            history_context = "\n\nКонтекст предыдущего диалога (для понимания контекста запроса):\n"
            for i, msg in enumerate(reversed(chat_history[-5:]), 1):  # Последние 5 сообщений
                q = msg.get('q', '') or ''
                a = msg.get('a', '') or ''
                # Обрезаем длинные ответы
                if len(a) > 500:
                    a = a[:500] + "..."
                history_context += f"{i}. Пользователь: {q}\n"
                history_context += f"   Ассистент: {a}\n\n"
        
        # Добавляем статистику в промпт, если она есть
        statistics_section = ""
        if cars_statistics:
            statistics_section = f"""

ВАЖНАЯ ИНФОРМАЦИЯ О ДОСТУПНЫХ АВТОМОБИЛЯХ В БАЗЕ ДАННЫХ:
- Всего автомобилей в наличии: {cars_statistics['total_cars_count']}
  • Новые автомобили: {cars_statistics['new_cars_count']}
  • С пробегом: {cars_statistics['used_cars_count']}

- Доступные марки (всего {len(cars_statistics['unique_marks'])}): {', '.join(cars_statistics['unique_marks'][:20])}{' и другие' if len(cars_statistics['unique_marks']) > 20 else ''}

- Доступные модели (всего {len(cars_statistics['unique_models'])}): {', '.join(cars_statistics['unique_models'][:30])}{' и другие' if len(cars_statistics['unique_models']) > 30 else ''}

Используй эту статистику для полноценного ответа пользователю о доступном ассортименте. Можешь упоминать популярные марки и модели, давать общую картину о наличии автомобилей.

"""
        
        return f"""
Ты — автоэксперт и персональный помощник по подбору автомобиля. Отвечай на русском. 
Твой стиль — кратко, по делу, профессионально. Избегай воды. 

{statistics_section}

У тебя есть контекст (статьи/документы/карточки авто) ниже. Если в контексте есть автомобили, обязательно:
1) Дай экспертную рекомендацию (ТОП‑3 варианта) с причинами выбора;
2) Укажи ключевые характеристики (год, цена, пробег, город, кузов, коробка, привод, топливо), отметь соответствие запросу;
3) Добавь 2–3 альтернативы с короткими пояснениями;
4) Отметь риски/особенности (например, большой пробег, спорная ликвидность, дорогой налог, редкие запчасти);
5) Дай практические советы по покупке (что проверить на осмотре, какие документы/диагностика);
6) Предложи следующие шаги (сузить бюджет/год/пробег, выбрать город/кузов/коробку и т.п.);
7) Задай 2–4 уточняющих вопроса (приоритеты: бюджет, новый/с пробегом, кузов, привод, двигатель, год, пробег, город).

Если автомобилей в контексте нет, но есть статистика выше — используй её для информирования пользователя о доступном ассортименте и помоги уточнить критерии поиска.

Форматируй ответ структурированными пунктами. Числа (цены/пробег/год) пиши в человекочитаемом виде. Не выдумывай факты отсутствующие в контексте и статистике.

{history_context}

Контекст (найденная информация):
{context}

Запрос пользователя: {question}

Сформируй ответ автоэксперта:
"""

    # === Методы обработки команд диалога ===
    
    async def _handle_start_command(self, user_id: str, query: str) -> Dict[str, Any]:
        """Обрабатывает команду начала поиска"""
        response_text = """Конечно! Давайте подберем для вас идеальный автомобиль. 

Для начала ответьте на несколько вопросов:

💰 **Какой у вас бюджет?** (например, "до 2 млн" или "500-700 тыс")

🚗 **Какой тип кузова предпочитаете?** (внедорожник, седан, хэтчбек, универсал, купе, кабриолет, минивэн, пикап)

⛽ **Тип топлива?** (бензин, дизель, гибрид, электрический, газ)

⚙️ **Коробка передач?** (автомат, механика, вариатор, робот)

🔧 **Привод?** (полный, передний, задний)

Вы можете указать все критерии сразу или отвечать по одному."""
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id, message=query, response=response_text, related_article_ids=[]
        )
        
        return {
            "response": response_text,
            "related_articles": [],
            "related_documents": [],
            "related_cars": [],
            "related_used_cars": [],
            "model_info": _get_current_model_info(),
            "message_id": chat_message.id,
        }
    
    async def _handle_reset_command(self, user_id: str, query: str) -> Dict[str, Any]:
        """Обрабатывает команду сброса"""
        response_text = "Хорошо, начнем поиск с чистого листа.\n\n💰 Какой у вас бюджет?"
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id, message=query, response=response_text, related_article_ids=[]
        )
        
        return {
            "response": response_text,
            "related_articles": [],
            "related_documents": [],
            "related_cars": [],
            "related_used_cars": [],
            "model_info": _get_current_model_info(),
            "message_id": chat_message.id,
        }
    
    async def _handle_show_results_command(self, user_id: str, query: str, dialog_state) -> Dict[str, Any]:
        """Обрабатывает команду показа результатов"""
        # Получаем сохраненные результаты или выполняем поиск по текущим критериям
        saved_results = dialog_state.get_search_results()
        
        if saved_results:
            # Показываем сохраненные результаты
            cars = saved_results.get("cars", [])
            used_cars = saved_results.get("used_cars", [])
            
            response_text = f"Вот что я нашел по вашим критериям:\n\n"
            
            if cars or used_cars:
                # Форматируем результаты
                for i, car in enumerate((cars + used_cars)[:5], 1):
                    car_type = "новый" if car in cars else "с пробегом"
                    response_text += f"{i}. {car.get('mark', '')} {car.get('model', '')} ({car_type})\n"
                    response_text += f"   Цена: {car.get('price', '')} ₽, Год: {car.get('year', '')}\n"
                    if car_type == "с пробегом":
                        response_text += f"   Пробег: {car.get('mileage', '')} км\n"
                    response_text += "\n"
            else:
                response_text = "К сожалению, по вашим критериям ничего не найдено. Попробуйте изменить критерии."
        else:
            response_text = "Выполняю поиск по текущим критериям..."
            # Здесь будет логика поиска по критериям из dialog_state
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id, message=query, response=response_text, related_article_ids=[]
        )
        
        return {
            "response": response_text,
            "related_articles": [],
            "related_documents": [],
            "related_cars": [],
            "related_used_cars": [],
            "model_info": _get_current_model_info(),
            "message_id": chat_message.id,
        }
    
    async def _handle_show_filters_command(self, user_id: str, query: str, dialog_state, command_processor) -> Dict[str, Any]:
        """Обрабатывает команду показа фильтров"""
        criteria = dialog_state.get_criteria()
        
        if criteria:
            summary = command_processor.format_criteria_summary(criteria)
            response_text = f"Сейчас у вас заданы следующие критерии:\n\n{summary}\n\nЧто хотите изменить?"
        else:
            response_text = "Критерии пока не заданы. Начните с указания бюджета или других параметров."
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id, message=query, response=response_text, related_article_ids=[]
        )
        
        return {
            "response": response_text,
            "related_articles": [],
            "related_documents": [],
            "related_cars": [],
            "related_used_cars": [],
            "model_info": _get_current_model_info(),
            "message_id": chat_message.id,
        }
    
    async def _handle_compare_command(self, user_id: str, command: Dict[str, Any], dialog_state) -> Dict[str, Any]:
        """Обрабатывает команду сравнения двух моделей"""
        model1_query = command.get("model1", "").strip()
        model2_query = command.get("model2", "").strip()
        
        # Поиск автомобилей по запросам
        cars1 = []
        cars2 = []
        
        # Парсим марку и модель из первого запроса
        parts1 = model1_query.split()
        mark1 = parts1[0] if parts1 else ""
        model1 = " ".join(parts1[1:]) if len(parts1) > 1 else model1_query
        
        # Парсим марку и модель из второго запроса
        parts2 = model2_query.split()
        mark2 = parts2[0] if parts2 else ""
        model2 = " ".join(parts2[1:]) if len(parts2) > 1 else model2_query
        
        # Поиск через Elasticsearch
        if getattr(self, 'es_service', None) and self.es_service.is_available():
            try:
                # Ищем первую модель
                es_result1 = self.es_service.search_cars(query=model1_query, mark=mark1, model=model1, limit=5)
                for hit in es_result1.get("hits", []) or []:
                    src = hit.get('_source') or {}
                    car_id = src.get('id')
                    car_type = src.get('type')
                    if car_type == 'car' and car_id:
                        car = self.db_service.get_car(car_id)
                        if car:
                            cars1.append(car)
                    elif car_type == 'used_car' and car_id:
                        car = self.db_service.get_used_car(car_id)
                        if car:
                            cars1.append(car)
                
                # Ищем вторую модель
                es_result2 = self.es_service.search_cars(query=model2_query, mark=mark2, model=model2, limit=5)
                for hit in es_result2.get("hits", []) or []:
                    src = hit.get('_source') or {}
                    car_id = src.get('id')
                    car_type = src.get('type')
                    if car_type == 'car' and car_id:
                        car = self.db_service.get_car(car_id)
                        if car:
                            cars2.append(car)
                    elif car_type == 'used_car' and car_id:
                        car = self.db_service.get_used_car(car_id)
                        if car:
                            cars2.append(car)
            except Exception as e:
                print(f"⚠️ Ошибка поиска для сравнения: {e}")
        
        # Выбираем по одному представителю каждой модели
        car1 = cars1[0] if cars1 else None
        car2 = cars2[0] if cars2 else None
        
        if not car1 or not car2:
            response_text = f"Не удалось найти обе модели для сравнения.\n\n"
            if not car1:
                response_text += f"- {model1_query}: не найдено\n"
            if not car2:
                response_text += f"- {model2_query}: не найдено\n"
        else:
            # Формируем таблицу сравнения
            response_text = f"**Сравнение {car1.mark} {car1.model} и {car2.mark} {car2.model}:**\n\n"
            response_text += "| Параметр | " + f"{car1.mark} {car1.model}" + " | " + f"{car2.mark} {car2.model}" + " |\n"
            response_text += "|----------|" + "-" * (len(f"{car1.mark} {car1.model}") + 2) + "|" + "-" * (len(f"{car2.mark} {car2.model}") + 2) + "|\n"
            
            # Цена
            price1 = f"{car1.price} ₽" if car1.price else "Не указана"
            price2 = f"{car2.price} ₽" if car2.price else "Не указана"
            response_text += f"| 💰 Цена | {price1} | {price2} |\n"
            
            # Год
            year1 = car1.manufacture_year or "Не указан"
            year2 = car2.manufacture_year or "Не указан"
            response_text += f"| 📅 Год | {year1} | {year2} |\n"
            
            # Пробег (для подержанных)
            if hasattr(car1, 'mileage') and car1.mileage:
                mileage1 = f"{car1.mileage} км"
            else:
                mileage1 = "Новый"
            if hasattr(car2, 'mileage') and car2.mileage:
                mileage2 = f"{car2.mileage} км"
            else:
                mileage2 = "Новый"
            response_text += f"| 🛣️ Пробег | {mileage1} | {mileage2} |\n"
            
            # Двигатель
            engine1 = getattr(car1, 'engine_vol', None) or "Не указан"
            engine2 = getattr(car2, 'engine_vol', None) or "Не указан"
            if isinstance(engine1, (int, float)) and engine1 > 100:
                engine1 = f"{engine1/1000:.1f} л"
            if isinstance(engine2, (int, float)) and engine2 > 100:
                engine2 = f"{engine2/1000:.1f} л"
            response_text += f"| 🔧 Объем двигателя | {engine1} | {engine2} |\n"
            
            # Мощность
            power1 = f"{getattr(car1, 'power', None)} л.с." if getattr(car1, 'power', None) else "Не указана"
            power2 = f"{getattr(car2, 'power', None)} л.с." if getattr(car2, 'power', None) else "Не указана"
            response_text += f"| ⚡ Мощность | {power1} | {power2} |\n"
            
            # Топливо
            fuel1 = car1.fuel_type or "Не указано"
            fuel2 = car2.fuel_type or "Не указано"
            response_text += f"| ⛽ Топливо | {fuel1} | {fuel2} |\n"
            
            # КПП
            gearbox1 = getattr(car1, 'gear_box_type', None) or "Не указана"
            gearbox2 = getattr(car2, 'gear_box_type', None) or "Не указана"
            response_text += f"| ⚙️ КПП | {gearbox1} | {gearbox2} |\n"
            
            # Привод
            drive1 = getattr(car1, 'driving_gear_type', None) or "Не указан"
            drive2 = getattr(car2, 'driving_gear_type', None) or "Не указан"
            response_text += f"| 🚗 Привод | {drive1} | {drive2} |\n"
            
            # Кузов
            body1 = getattr(car1, 'body_type', None) or "Не указан"
            body2 = getattr(car2, 'body_type', None) or "Не указан"
            response_text += f"| 🚙 Кузов | {body1} | {body2} |\n"
            
            # Город
            city1 = car1.city or "Не указан"
            city2 = car2.city or "Не указан"
            response_text += f"| 📍 Город | {city1} | {city2} |\n"
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id, message=command["original_query"], response=response_text, related_article_ids=[]
        )
        
        related_cars = []
        related_used_cars = []
        if car1:
            if hasattr(car1, 'mileage'):
                related_used_cars.append(car1)
            else:
                related_cars.append(car1)
        if car2:
            if hasattr(car2, 'mileage'):
                related_used_cars.append(car2)
            else:
                related_cars.append(car2)
        
        return {
            "response": response_text,
            "related_articles": [],
            "related_documents": [],
            "related_cars": related_cars,
            "related_used_cars": related_used_cars,
            "model_info": _get_current_model_info(),
            "message_id": chat_message.id,
        }
    
    async def _handle_similar_command(self, user_id: str, command: Dict[str, Any], dialog_state) -> Dict[str, Any]:
        """Обрабатывает команду поиска похожих моделей"""
        model_query = command.get("model", "").strip()
        
        # Ищем эталонный автомобиль
        reference_car = None
        
        if getattr(self, 'es_service', None) and self.es_service.is_available():
            try:
                # Парсим марку и модель
                parts = model_query.split()
                mark = parts[0] if parts else ""
                model = " ".join(parts[1:]) if len(parts) > 1 else model_query
                
                # Ищем эталонный автомобиль
                es_result = self.es_service.search_cars(query=model_query, mark=mark, model=model, limit=1)
                for hit in es_result.get("hits", []) or []:
                    src = hit.get('_source') or {}
                    car_id = src.get('id')
                    car_type = src.get('type')
                    if car_type == 'car' and car_id:
                        reference_car = self.db_service.get_car(car_id)
                    elif car_type == 'used_car' and car_id:
                        reference_car = self.db_service.get_used_car(car_id)
                    if reference_car:
                        break
            except Exception as e:
                print(f"⚠️ Ошибка поиска эталона: {e}")
        
        if not reference_car:
            response_text = f"Не удалось найти модель '{model_query}' для поиска похожих."
        else:
            # Извлекаем характеристики эталонного автомобиля
            ref_price = float(str(reference_car.price).replace(' ', '').replace(',', '.')) if reference_car.price else None
            ref_body = getattr(reference_car, 'body_type', None)
            ref_fuel = reference_car.fuel_type
            ref_year = reference_car.manufacture_year
            
            # Ищем похожие (тот же кузов, топливо, похожая цена ±15%, похожий год ±2)
            similar_cars = []
            
            if getattr(self, 'es_service', None) and self.es_service.is_available():
                try:
                    # Задаем фильтры для похожих
                    filters = {}
                    if ref_body:
                        filters['body_type'] = ref_body
                    if ref_fuel:
                        filters['fuel_type'] = ref_fuel
                    if ref_price:
                        filters['min_price'] = int(ref_price * 0.85)
                        filters['max_price'] = int(ref_price * 1.15)
                    if ref_year:
                        filters['min_year'] = ref_year - 2
                        filters['max_year'] = ref_year + 2
                    
                    # Исключаем эталонный автомобиль
                    es_result = self.es_service.search_cars(
                        query="",
                        body_type=filters.get('body_type'),
                        fuel_type=filters.get('fuel_type'),
                        min_price=filters.get('min_price'),
                        max_price=filters.get('max_price'),
                        min_year=filters.get('min_year'),
                        max_year=filters.get('max_year'),
                        limit=10
                    )
                    
                    for hit in es_result.get("hits", []) or []:
                        src = hit.get('_source') or {}
                        car_id = src.get('id')
                        car_type = src.get('type')
                        
                        # Пропускаем эталонный
                        if car_id == reference_car.id:
                            continue
                        
                        if car_type == 'car' and car_id:
                            car = self.db_service.get_car(car_id)
                            if car:
                                similar_cars.append(car)
                        elif car_type == 'used_car' and car_id:
                            car = self.db_service.get_used_car(car_id)
                            if car:
                                similar_cars.append(car)
                except Exception as e:
                    print(f"⚠️ Ошибка поиска похожих: {e}")
            
            if not similar_cars:
                response_text = f"Похожие на {reference_car.mark} {reference_car.model} не найдены.\n\n"
                response_text += f"Характеристики эталона:\n"
                response_text += f"- Цена: {reference_car.price} ₽\n"
                response_text += f"- Кузов: {ref_body or 'Не указан'}\n"
                response_text += f"- Топливо: {ref_fuel or 'Не указано'}\n"
            else:
                response_text = f"Найдено {len(similar_cars)} похожих на {reference_car.mark} {reference_car.model}:\n\n"
                for i, car in enumerate(similar_cars[:5], 1):
                    car_type = "новый" if not hasattr(car, 'mileage') or not car.mileage else "с пробегом"
                    response_text += f"{i}. {car.mark} {car.model} ({car_type})\n"
                    response_text += f"   Цена: {car.price} ₽, Год: {car.manufacture_year}\n"
                    if car_type == "с пробегом" and hasattr(car, 'mileage') and car.mileage:
                        response_text += f"   Пробег: {car.mileage} км\n"
                    response_text += "\n"
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id, message=command["original_query"], response=response_text, related_article_ids=[]
        )
        
        # Разделяем на новые и подержанные
        related_cars = []
        related_used_cars = []
        for car in similar_cars[:5]:
            if hasattr(car, 'mileage') and car.mileage:
                related_used_cars.append(car)
            else:
                related_cars.append(car)
        if reference_car:
            if hasattr(reference_car, 'mileage') and reference_car.mileage:
                related_used_cars.insert(0, reference_car)
            else:
                related_cars.insert(0, reference_car)
        
        return {
            "response": response_text,
            "related_articles": [],
            "related_documents": [],
            "related_cars": related_cars,
            "related_used_cars": related_used_cars,
            "model_info": _get_current_model_info(),
            "message_id": chat_message.id,
        }
    
    async def _handle_help_command(self, user_id: str, query: str) -> Dict[str, Any]:
        """Обрабатывает команду помощи"""
        response_text = """Я помогаю подобрать автомобиль. Вот что я умею:

**Основные команды:**
• "Помоги подобрать машину" - начать поиск
• "Покажи результаты" - показать найденные варианты
• "Фильтры" - показать текущие критерии
• "Сброс" - начать поиск заново

**Можно указывать:**
• Бюджет: "до 2 млн", "от 500 тыс до 1.5 млн"
• Тип кузова: внедорожник, седан, хэтчбек и т.д.
• Топливо: бензин, дизель, гибрид
• Коробка: автомат, механика
• Привод: полный, передний, задний
• Год: "не старше 2018", "от 2015 до 2020"
• Пробег: "до 100 тыс км"
• Цвет и опции

**Уточнения:**
• "Дешевле" / "Дороже" - относительно предыдущего запроса
• "Покажи похожие на [модель]" - найти аналоги
• "Сравни [модель1] и [модель2]" - сравнить два варианта

Готов помочь вам найти идеальный автомобиль! 🚗"""
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id, message=query, response=response_text, related_article_ids=[]
        )
        
        return {
            "response": response_text,
            "related_articles": [],
            "related_documents": [],
            "related_cars": [],
            "related_used_cars": [],
            "model_info": _get_current_model_info(),
            "message_id": chat_message.id,
        }
    
    async def _handle_contextual_question(self, user_id: str, query: str, chat_history: List[Dict[str, Any]], dialog_state) -> Dict[str, Any]:
        """Обрабатывает контекстные вопросы (из них, этого варианта)"""
        # Получаем последние показанные автомобили
        last_cars = dialog_state.get_last_shown_cars()
        
        if not last_cars:
            response_text = "Сначала выполните поиск, чтобы я мог ответить на ваш вопрос."
            chat_message = self.db_service.save_chat_message(
                user_id=user_id, message=query, response=response_text, related_article_ids=[]
            )
            return {
                "response": response_text,
                "related_articles": [],
                "related_documents": [],
                "related_cars": [],
                "related_used_cars": [],
                "model_info": _get_current_model_info(),
                "message_id": chat_message.id,
            }
        
        # Анализируем вопрос
        query_lower = query.lower()
        
        # Определяем тип вопроса
        question_type = None
        if any(word in query_lower for word in ["расход", "потребление", "топливо"]):
            question_type = "fuel_consumption"
        elif any(word in query_lower for word in ["привод", "полный привод", "4wd", "4x4"]):
            question_type = "drive"
        elif any(word in query_lower for word in ["дешевле", "дороже", "цена", "стоимость"]):
            question_type = "price"
        elif any(word in query_lower for word in ["объем", "двигатель", "мощность"]):
            question_type = "engine"
        elif any(word in query_lower for word in ["кузов", "тип"]):
            question_type = "body"
        elif "почему" in query_lower or "рекомендовал" in query_lower:
            question_type = "recommendation"
        else:
            question_type = "general"
        
        # Загружаем полные данные об автомобилях
        cars_data = []
        for car_info in last_cars[:5]:  # Берем до 5 последних
            car_id = car_info.get("id")
            if not car_id:
                continue
            
            # Пытаемся найти автомобиль
            car = self.db_service.get_car(car_id)
            if not car:
                car = self.db_service.get_used_car(car_id)
            
            if car:
                cars_data.append(car)
        
        if not cars_data:
            response_text = "Не удалось загрузить данные об автомобилях."
        else:
            # Формируем ответ в зависимости от типа вопроса
            if question_type == "fuel_consumption":
                # Находим автомобиль с минимальным расходом
                min_consumption = None
                min_car = None
                for car in cars_data:
                    consumption = getattr(car, 'fuel_consumption', None)
                    if consumption:
                        try:
                            cons_val = float(str(consumption).replace(',', '.'))
                            if min_consumption is None or cons_val < min_consumption:
                                min_consumption = cons_val
                                min_car = car
                        except:
                            pass
                
                if min_car and min_consumption:
                    response_text = f"Из представленных самый экономичный по расходу топлива — {min_car.mark} {min_car.model}.\n"
                    response_text += f"Расход: {min_consumption} л/100км"
                else:
                    response_text = "К сожалению, данные о расходе топлива для представленных автомобилей отсутствуют."
            
            elif question_type == "drive":
                # Проверяем наличие полного привода
                full_drive_cars = []
                for car in cars_data:
                    drive = getattr(car, 'driving_gear_type', '').lower() or ''
                    if 'полный' in drive or '4wd' in drive or '4x4' in drive:
                        full_drive_cars.append(car)
                
                if full_drive_cars:
                    response_text = f"Полный привод есть у следующих моделей:\n\n"
                    for car in full_drive_cars:
                        response_text += f"- {car.mark} {car.model}\n"
                else:
                    response_text = "Из представленных моделей ни у одной нет полного привода."
            
            elif question_type == "price":
                # Находим самый дешевый и дорогой
                prices = []
                for car in cars_data:
                    if car.price:
                        try:
                            price_val = float(str(car.price).replace(' ', '').replace(',', '.'))
                            prices.append((price_val, car))
                        except:
                            pass
                
                if prices:
                    prices.sort()
                    cheapest = prices[0][1]
                    most_expensive = prices[-1][1]
                    response_text = f"Из представленных:\n\n"
                    response_text += f"💰 Самый дешевый: {cheapest.mark} {cheapest.model} — {cheapest.price} ₽\n"
                    response_text += f"💎 Самый дорогой: {most_expensive.mark} {most_expensive.model} — {most_expensive.price} ₽"
                else:
                    response_text = "Не удалось определить цены представленных автомобилей."
            
            elif question_type == "engine":
                # Информация о двигателе
                response_text = "Информация о двигателях представленных автомобилей:\n\n"
                for car in cars_data[:5]:
                    engine_vol = getattr(car, 'engine_vol', None)
                    power = getattr(car, 'power', None)
                    engine_info = []
                    if engine_vol:
                        if isinstance(engine_vol, (int, float)) and engine_vol > 100:
                            engine_info.append(f"{engine_vol/1000:.1f} л")
                        else:
                            engine_info.append(f"{engine_vol} л")
                    if power:
                        engine_info.append(f"{power} л.с.")
                    
                    response_text += f"- {car.mark} {car.model}: {', '.join(engine_info) if engine_info else 'Не указано'}\n"
            
            elif question_type == "recommendation":
                # Объяснение рекомендации
                if cars_data:
                    recommended = cars_data[0]  # Первый из списка
                    criteria = dialog_state.get_criteria()
                    
                    response_text = f"Я рекомендую {recommended.mark} {recommended.model}, потому что:\n\n"
                    
                    reasons = []
                    if "max_price" in criteria and recommended.price:
                        try:
                            max_p = criteria["max_price"]
                            price_val = float(str(recommended.price).replace(' ', '').replace(',', '.'))
                            if price_val <= max_p:
                                reasons.append(f"✅ Соответствует вашему бюджету (до {max_p//1_000_000} млн ₽)")
                        except:
                            pass
                    
                    if "body_type" in criteria:
                        body = getattr(recommended, 'body_type', '')
                        if body and criteria["body_type"].lower() in body.lower():
                            reasons.append(f"✅ Подходящий тип кузова: {body}")
                    
                    if "fuel_type" in criteria:
                        fuel = recommended.fuel_type or ''
                        if fuel and criteria["fuel_type"].lower() in fuel.lower():
                            reasons.append(f"✅ Требуемый тип топлива: {fuel}")
                    
                    if reasons:
                        response_text += "\n".join(reasons)
                    else:
                        response_text += "✅ Соответствует основным вашим критериям поиска"
            
            else:
                # Общий вопрос - формируем сводку по автомобилям
                response_text = "Вот информация о последних найденных автомобилях:\n\n"
                for i, car in enumerate(cars_data[:5], 1):
                    car_type = "новый" if not hasattr(car, 'mileage') or not car.mileage else "с пробегом"
                    response_text += f"{i}. {car.mark} {car.model} ({car_type})\n"
                    response_text += f"   Цена: {car.price} ₽, Год: {car.manufacture_year}\n"
                    if car_type == "с пробегом" and hasattr(car, 'mileage') and car.mileage:
                        response_text += f"   Пробег: {car.mileage} км\n"
                    response_text += "\n"
        
        # Используем LLM для более естественного ответа
        prompt = f"""Пользователь задал контекстный вопрос: "{query}"

Информация об автомобилях:
{response_text}

Дай естественный ответ на русском языке, основываясь на этой информации. Будь кратким и по делу."""
        
        try:
            ai_response, _ = await _generate_with_ai_settings(prompt)
            response_text = ai_response or response_text
        except:
            pass  # Используем сгенерированный ответ
        
        chat_message = self.db_service.save_chat_message(
            user_id=user_id, message=query, response=response_text, related_article_ids=[]
        )
        
        # Возвращаем автомобили для отображения
        related_cars = []
        related_used_cars = []
        for car in cars_data:
            if hasattr(car, 'mileage') and car.mileage:
                related_used_cars.append(car)
            else:
                related_cars.append(car)
        
        return {
            "response": response_text,
            "related_articles": [],
            "related_documents": [],
            "related_cars": related_cars,
            "related_used_cars": related_used_cars,
            "model_info": _get_current_model_info(),
            "message_id": chat_message.id,
        }
    
    def _search_by_meta(self, query: str, limit: int = 5) -> List[Article]:
        # Простая токенизация по пробелам и пунктуации
        import re
        tokens = re.findall(r"[\w\-]{2,32}", query, flags=re.UNICODE)
        try:
            return self.db_service.search_articles_by_meta(tokens, limit=limit)
        except Exception:
            return []
    
    def reindex_articles(self) -> Dict[str, Any]:
        """
        Переиндексирует все статьи в ChromaDB, используя встроенную модель ChromaDB
        """
        articles, total = self.db_service.get_articles(skip=0, limit=10000)
        
        # Удаляем старую коллекцию и создаем новую
        try:
            self.chroma_client.delete_collection("kb_articles")
        except Exception:
            pass
        
        # Создаем новую коллекцию без указания эмбеддингов - ChromaDB будет использовать свою модель
        self.collection = self.chroma_client.create_collection(name="kb_articles")
        
        if total == 0:
            return {"message": "Нет статей для индексации", "total_articles": 0, "status": "success"}
        
        # Обрабатываем статьи батчами по 10
        batch_size = 10
        processed = 0
        
        for i in range(0, len(articles), batch_size):
            batch_articles = articles[i:i + batch_size]
            ids = []
            documents = []
            metadatas = []
            
            for a in batch_articles:
                ids.append(str(a.id))
                documents.append((a.title or "") + "\n\n" + (a.text or ""))
                metadatas.append({"url": a.url or "", "language": a.language or "ru", "title": a.title})
            
            # Добавляем в коллекцию без эмбеддингов - ChromaDB сам их сгенерирует
            self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
            processed += len(batch_articles)
            print(f"Processed {processed}/{total} articles")
        
        return {"message": "Переиндексация завершена", "total_articles": total, "status": "success"}

    def _embed_mistral_batch(self, texts: List[str]) -> List[List[float]]:
        """Получает эмбеддинги у Mistral для списка текстов"""
        url = f"{settings.mistral_base_url}/v1/embeddings"
        headers = {
            "Authorization": f"Bearer {settings.mistral_api_key}",
            "Content-Type": "application/json",
        }
        vectors: List[List[float]] = []
        # Mistral API поддерживает батчи; отправим одним запросом, если возможно
        try:
            payload = {"model": settings.mistral_embed_model, "input": texts}
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json() or {}
            items = data.get("data") or []
            for item in items:
                emb = item.get("embedding", [])
                if len(emb) == 1024:  # Проверяем правильную размерность
                    vectors.append(emb)
                else:
                    vectors.append([0.0] * 1024)  # Fallback с правильной размерностью
        except Exception:
            # Фолбэк: попробуем по одному, чтобы вернуть хоть что-то
            for t in texts:
                try:
                    payload = {"model": settings.mistral_embed_model, "input": t}
                    r = requests.post(url, headers=headers, json=payload, timeout=60)
                    r.raise_for_status()
                    dd = r.json() or {}
                    emb = ((dd.get("data") or [{}])[0]).get("embedding", [])
                    if len(emb) == 1024:
                        vectors.append(emb)
                    else:
                        vectors.append([0.0] * 1024)
                except Exception:
                    vectors.append([0.0] * 1024)  # Fallback с правильной размерностью
        return vectors

    def _search_semantic(self, query: str, k: int = 5) -> List[Article]:
        # ChromaDB отключена - используем только PostgreSQL
        # Поиск через PostgreSQL вместо ChromaDB
        return self.db_service.search_articles_for_rag(query, limit=k)
    
    def _search_cars_semantic(self, query: str, k: int = 3) -> List[Car]:
        """Поиск новых автомобилей через PostgreSQL и Elasticsearch (ChromaDB отключена)"""
        results: List[Car] = []
        
        # Поиск через PostgreSQL
        for car in self.db_service.search_cars_for_rag(query, limit=k):
            results.append(car)
        
        # Дополнительный поиск через Elasticsearch
        if getattr(self, 'es_service', None) and self.es_service.is_available():
            try:
                es_result = self.es_service.search_cars(query=query, limit=k)
                for hit in es_result.get("hits", []) or []:
                    src = hit.get('_source') or {}
                    if src.get('type') == 'car':
                        car_id = src.get('id')
                        if car_id:
                            car = self.db_service.get_car(car_id)
                            if car and car not in results:
                                results.append(car)
            except Exception:
                pass
        
        return results[:k]
    
    def _search_used_cars_semantic(self, query: str, k: int = 3) -> List[UsedCar]:
        """Поиск подержанных автомобилей через PostgreSQL и Elasticsearch (ChromaDB отключена)"""
        results: List[UsedCar] = []
        
        # Поиск через PostgreSQL
        for used_car in self.db_service.search_used_cars_for_rag(query, limit=k):
            results.append(used_car)
        
        # Дополнительный поиск через Elasticsearch
        if getattr(self, 'es_service', None) and self.es_service.is_available():
            try:
                es_result = self.es_service.search_cars(query=query, limit=k, car_type="used_car")
                for hit in es_result.get("hits", []) or []:
                    src = hit.get('_source') or {}
                    if src.get('type') == 'used_car':
                        car_id = src.get('id')
                        if car_id:
                            used_car = self.db_service.get_used_car(car_id)
                            if used_car and used_car not in results:
                                results.append(used_car)
            except Exception:
                pass
        
        return results[:k]

    def _generate_with_ollama(self, prompt: str) -> str:
        # Сохранено для обратной совместимости; сейчас генерация идёт через Mistral
        import requests
        
        # Пробуем разные адреса Ollama
        ollama_urls = [
            f"{settings.ollama_host}:{settings.ollama_port}",
            "http://localhost:11434",
            "http://host.docker.internal:11434"
        ]
        
        payload = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False
        }
        
        for url in ollama_urls:
            try:
                resp = requests.post(f"{url}/api/generate", json=payload, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")
            except:
                continue
        
        raise Exception("Не удается подключиться к Ollama ни по одному из адресов")
    
    def _apply_strict_filters(self, cars: List[Car], used_cars: List[UsedCar], 
                             query: str) -> Tuple[List[Car], List[UsedCar]]:
        """Применяет строгую фильтрацию к результатам поиска"""
        filtered_cars = []
        filtered_used_cars = []
        
        # Извлекаем фильтры из запроса
        filters = self._extract_filters_from_query(query)
        
        # Фильтруем новые автомобили
        for car in cars:
            if self._matches_all_filters(car, filters, is_used=False):
                filtered_cars.append(car)
        
        # Фильтруем подержанные автомобили
        for car in used_cars:
            if self._matches_all_filters(car, filters, is_used=True):
                filtered_used_cars.append(car)
        
        return filtered_cars, filtered_used_cars
    
    def _extract_filters_from_query(self, query: str) -> Dict[str, Any]:
        """Извлекает фильтры из текста запроса"""
        filters = {}
        query_lower = query.lower()
        
        # === Фильтр по цене ===
        # Поддержка: млн, миллионов, тыс, тысяч, полные числа, диапазоны от/до/-
        price_patterns = [
            # Миллионы: от X млн / до X млн
            (r'от\s+(\d+(?:[.,]\d+)?)\s*(?:млн|миллионов?)', 'from_mln'),
            (r'до\s+(\d+(?:[.,]\d+)?)\s*(?:млн|миллионов?)', 'to_mln'),
            (r'(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s*(?:млн|миллионов?)', 'range_mln'),
            # Тысячи: от X тыс / до X тыс
            (r'от\s+(\d+(?:[.,]\d+)?)\s*(?:тыс|тысяч[а-я]*)', 'from_k'),
            (r'до\s+(\d+(?:[.,]\d+)?)\s*(?:тыс|тысяч[а-я]*)', 'to_k'),
            (r'(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s*(?:тыс|тысяч[а-я]*)', 'range_k'),
            # Полные числа: от X / до X (> 100k чтобы не путать с годом)
            (r'от\s+(\d{6,})', 'from_full'),
            (r'до\s+(\d{6,})', 'to_full'),
            (r'(\d{6,})\s*-\s*(\d{6,})', 'range_full'),
        ]
        
        for pattern, ptype in price_patterns:
            matches = re.findall(pattern, query_lower)
            if matches:
                if ptype == 'from_mln':
                    filters['min_price'] = float(matches[0].replace(',', '.')) * 1_000_000
                elif ptype == 'to_mln':
                    filters['max_price'] = float(matches[0].replace(',', '.')) * 1_000_000
                elif ptype == 'range_mln':
                    filters['min_price'] = float(matches[0][0].replace(',', '.')) * 1_000_000
                    filters['max_price'] = float(matches[0][1].replace(',', '.')) * 1_000_000
                elif ptype == 'from_k':
                    filters['min_price'] = float(matches[0].replace(',', '.')) * 1_000
                elif ptype == 'to_k':
                    filters['max_price'] = float(matches[0].replace(',', '.')) * 1_000
                elif ptype == 'range_k':
                    filters['min_price'] = float(matches[0][0].replace(',', '.')) * 1_000
                    filters['max_price'] = float(matches[0][1].replace(',', '.')) * 1_000
                elif ptype == 'from_full':
                    filters['min_price'] = int(matches[0])
                elif ptype == 'to_full':
                    filters['max_price'] = int(matches[0])
                elif ptype == 'range_full':
                    filters['min_price'] = int(matches[0][0])
                    filters['max_price'] = int(matches[0][1])
                break  # Берем первое найденное
        
        # === Фильтр по пробегу ===
        # Поддержка: от X км, до X км, X-Y км, тыс км
        mileage_patterns = [
            (r'от\s+(\d+(?:[.,]\d+)?)\s*(?:тыс[а-я]*\.?\s*км|тысяч[а-я]*\s*км)', 'from_k'),
            (r'до\s+(\d+(?:[.,]\d+)?)\s*(?:тыс[а-я]*\.?\s*км|тысяч[а-я]*\s*км)', 'to_k'),
            (r'пробег\s*от\s+(\d+(?:[.,]\d+)?)\s*(?:тыс[а-я]*\.?\s*км|тысяч[а-я]*\s*км)', 'from_k'),
            (r'пробег\s*до\s+(\d+(?:[.,]\d+)?)\s*(?:тыс[а-я]*\.?\s*км|тысяч[а-я]*\s*км)', 'to_k'),
            (r'от\s+(\d+)\s*км', 'from_km'),
            (r'до\s+(\d+)\s*км', 'to_km'),
            (r'пробег\s*от\s+(\d+)\s*км', 'from_km'),
            (r'пробег\s*до\s+(\d+)\s*км', 'to_km'),
            (r'(\d+)\s*-\s*(\d+)\s*км', 'range_km'),
        ]
        
        for pattern, mtype in mileage_patterns:
            matches = re.findall(pattern, query_lower)
            if matches:
                if mtype == 'from_k':
                    filters['min_mileage'] = int(float(matches[0].replace(',', '.')) * 1_000)
                elif mtype == 'to_k':
                    filters['max_mileage'] = int(float(matches[0].replace(',', '.')) * 1_000)
                elif mtype == 'from_km':
                    filters['min_mileage'] = int(matches[0])
                elif mtype == 'to_km':
                    filters['max_mileage'] = int(matches[0])
                elif mtype == 'range_km':
                    filters['min_mileage'] = int(matches[0][0])
                    filters['max_mileage'] = int(matches[0][1])
                break
        
        # === Фильтр по году (абсолютный и относительный) ===
        from datetime import datetime
        current_year = datetime.now().year
        
        # Относительные фильтры: старше/не старше/больше/меньше X лет
        age_patterns = [
            (r'(?:старше|более|больше)\s+(\d+)\s*(?:лет|года)', 'older'),
            (r'(?:не\s+старше|моложе|новее|меньше)\s+(\d+)\s*(?:лет|года)', 'newer'),
        ]
        for pattern, atype in age_patterns:
            matches = re.findall(pattern, query_lower)
            if matches:
                age = int(matches[0])
                if atype == 'older':
                    filters['max_year'] = current_year - age
                elif atype == 'newer':
                    filters['min_year'] = current_year - age
                break
        
        # Абсолютные годы: YYYY год, YYYY-YYYY год, YY года (10 года -> 2010)
        year_patterns = [
            (r'(\d{4})\s*-\s*(\d{4})\s*год[а-я]*', 'range'),
            (r'(\d{4})\s*год[а-я]*', 'single_full'),
            (r'(\d{2})\s*года', 'short'),  # "10 года" -> 2010
        ]
        
        for pattern, ytype in year_patterns:
            matches = re.findall(pattern, query_lower)
            if matches:
                if ytype == 'range':
                    filters['min_year'] = int(matches[0][0])
                    filters['max_year'] = int(matches[0][1])
                elif ytype == 'single_full':
                    filters['year'] = int(matches[0])
                elif ytype == 'short':
                    short_year = int(matches[0])
                    # Интерпретация: 10-25 -> 2010-2025, 90-99 -> 1990-1999
                    if short_year <= 25:
                        filters['year'] = 2000 + short_year
                    else:
                        filters['year'] = 1900 + short_year
                break
        
        # === Фильтр по типу топлива ===
        fuel_types = ['бензин', 'дизель', 'электрический', 'электро', 'гибрид', 'газ']
        for fuel in fuel_types:
            if fuel in query_lower:
                filters['fuel_type'] = fuel if fuel != 'электро' else 'электрический'
                break
        
        # === Фильтр по типу кузова ===
        body_types = ['внедорожник', 'седан', 'хэтчбек', 'хетчбек', 'универсал', 'пикап', 'кроссовер', 'купе', 'минивэн', 'фургон']
        for body in body_types:
            if body in query_lower:
                # Нормализация написания
                normalized = body if body not in ['хетчбек'] else 'хэтчбек'
                filters['body_type'] = normalized
                break
        
        # === Фильтр по городу ===
        known_cities = [
            'краснодар', 'москва', 'санкт-петербург', 'ростов-на-дону', 'воронеж', 
            'новосибирск', 'екатеринбург', 'казань', 'нижний новгород', 'самара', 
            'омск', 'челябинск', 'уфа', 'пермь', 'волгоград', 'красноярск', 
            'саратов', 'тюмень', 'тольятти', 'ижевск'
        ]
        for c in known_cities:
            if c in query_lower:
                filters['city'] = c
                break
        # Если город не найден по словарю — пробуем spaCy NER (GPE/LOC)
        if 'city' not in filters:
            city_spacy = self._extract_city_with_spacy(query)
            if city_spacy:
                filters['city'] = city_spacy.lower()
        
        # === Исключения брендов ===
        if 'кроме' in query_lower or 'исключая' in query_lower:
            exclude_pattern = r'(?:кроме|исключая)\s+([А-Яа-яA-Za-z]+)'
            exclude_match = re.search(exclude_pattern, query_lower)
            if exclude_match:
                filters['exclude_brand'] = exclude_match.group(1)
        
        return filters

    # --- Вспомогательные методы для извлечения города через spaCy ---
    _spacy_nlp = None

    def _get_spacy_nlp(self):
        if spacy is None:
            return None
        if self._spacy_nlp is not None:
            return self._spacy_nlp
        for model_name in ('ru_core_news_md', 'ru_core_news_sm', 'xx_ent_wiki_sm'):
            try:
                self._spacy_nlp = spacy.load(model_name)
                break
            except Exception:
                continue
        return self._spacy_nlp

    def _extract_city_with_spacy(self, text: str) -> Optional[str]:
        nlp = self._get_spacy_nlp()
        if nlp is None:
            return None
        try:
            doc = nlp(text)
            candidates: List[str] = []
            for ent in getattr(doc, 'ents', []) or []:
                if ent.label_.upper() in ('GPE', 'LOC'):
                    candidates.append(ent.text)
            if candidates:
                candidates.sort(key=lambda s: len(s), reverse=True)
                return candidates[0]
        except Exception:
            return None
        return None
    
    
    def _matches_all_filters(self, car: Any, filters: Dict[str, Any], is_used: bool = False) -> bool:
        """Проверяет, соответствует ли автомобиль всем фильтрам"""
        # Фильтр по цене
        if 'min_price' in filters or 'max_price' in filters:
            price = getattr(car, 'price', None)
            if price is None:
                return False
            
            try:
                price_float = float(price)
                if 'min_price' in filters and price_float < filters['min_price']:
                    return False
                if 'max_price' in filters and price_float > filters['max_price']:
                    return False
            except (ValueError, TypeError):
                return False
        
        # Фильтр по пробегу (только для подержанных)
        if is_used and 'max_mileage' in filters:
            mileage = getattr(car, 'mileage', None)
            if mileage is None or mileage > filters['max_mileage']:
                return False
        
        # Фильтр по году
        if 'min_year' in filters or 'max_year' in filters:
            year = getattr(car, 'manufacture_year', None)
            if year is None:
                return False
            
            if 'min_year' in filters and year < filters['min_year']:
                return False
            if 'max_year' in filters and year > filters['max_year']:
                return False
        
        # Фильтр по типу топлива
        if 'fuel_type' in filters:
            fuel = getattr(car, 'fuel_type', '')
            if not fuel or filters['fuel_type'].lower() not in fuel.lower():
                return False
        
        # Фильтр по типу кузова
        if 'body_type' in filters:
            body = getattr(car, 'body_type', '')
            if not body or filters['body_type'].lower() not in body.lower():
                return False
        
        # Фильтр по городу
        if 'city' in filters:
            city = getattr(car, 'city', '')
            if not city or filters['city'].lower() not in city.lower():
                return False
        
        # Исключения по бренду
        if 'exclude_brand' in filters:
            brand = getattr(car, 'mark', '')
            if brand and filters['exclude_brand'].lower() in brand.lower():
                return False
        
        return True
