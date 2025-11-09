"""
ИИ-агент для интеллектуального парсинга автомобилей с использованием NLP, ML и Ollama
"""
import re
import json
import time
import httpx
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.database import ParsedCar, ParsedCarPicture
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# NLP импорты
try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    spacy = None
    SPACY_AVAILABLE = False

try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False


class AIParser:
    """ИИ-агент для интеллектуального парсинга с NLP, ML и Ollama компонентами"""
    
    def __init__(self, db_session: Session, base_url: str = "https://aaa-motors.ru", 
                 ollama_model: Optional[str] = None, use_ollama: bool = True):
        self.db = db_session
        self.base_url = base_url
        self.session = None
        self.stats = {
            "total_parsed": 0,
            "total_errors": 0,
            "current_page": 0,
            "nlp_extractions": 0,
            "structure_changes_detected": 0,
            "ollama_extractions": 0
        }
        self.is_running = False
        
        # Настройки Ollama
        self.use_ollama = use_ollama
        self.ollama_model = ollama_model or getattr(settings, 'ollama_model', 'llama3:8b')
        self.ollama_working_url = None
        
        # Инициализация NLP компонентов
        self.nlp_model = self._load_nlp_model()
        # Анализ тональности загружается лениво (только при использовании)
        self.sentiment_analyzer = None
        self._sentiment_analyzer_loading = False
        
        # Проверка доступности Ollama
        if self.use_ollama:
            self._check_ollama_availability()
        
        # Кэш для структуры страниц (для обнаружения изменений)
        self.page_structure_cache = {}
        
    def _load_nlp_model(self):
        """Загружает NLP модель для извлечения сущностей"""
        if not SPACY_AVAILABLE:
            logger.warning("spaCy не установлен. NLP функции будут ограничены.")
            return None
        
        model_names = ['ru_core_news_md', 'ru_core_news_sm', 'xx_ent_wiki_sm']
        for model_name in model_names:
            try:
                nlp = spacy.load(model_name)
                logger.info(f"✅ Загружена NLP модель: {model_name}")
                return nlp
            except OSError:
                continue
        
        logger.warning("Не удалось загрузить NLP модель. Используется базовое извлечение.")
        return None
    
    def _load_sentiment_analyzer(self):
        """
        Ленивая загрузка модели для анализа тональности (опционально)
        Анализ тональности не критичен для парсинга - парсер работает и без него
        Загружается только при первом использовании
        """
        # Если уже загружен - возвращаем
        if self.sentiment_analyzer is not None:
            return self.sentiment_analyzer
        
        # Если идет загрузка - возвращаем None (чтобы не блокировать)
        if self._sentiment_analyzer_loading:
            return None
        
        if not TRANSFORMERS_AVAILABLE:
            return None
        
        # Устанавливаем флаг загрузки
        self._sentiment_analyzer_loading = True
        
        try:
            # Устанавливаем переменные окружения для увеличения таймаута
            import os
            os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '60'  # 1 минута (быстрее)
            os.environ['HF_HUB_CACHE'] = os.path.expanduser('~/.cache/huggingface')
            
            from transformers import pipeline
            import threading
            
            # Загружаем в отдельном потоке с таймаутом, чтобы не блокировать
            def load_analyzer():
                try:
                    logger.debug("Загрузка модели анализа тональности (в фоне)...")
                    # Используем правильный способ загрузки DistilBERT
                    from transformers import AutoTokenizer, AutoModelForSequenceClassification
                    import torch
                    
                    model_name = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
                    
                    # Загружаем токенизатор и модель напрямую (без pipeline для избежания конфликтов)
                    tokenizer = AutoTokenizer.from_pretrained(model_name)
                    model = AutoModelForSequenceClassification.from_pretrained(model_name)
                    
                    # Создаем pipeline после загрузки модели
                    analyzer = pipeline(
                        "text-classification",
                        model=model,
                        tokenizer=tokenizer,
                        device=-1  # -1 для CPU
                    )
                    
                    self.sentiment_analyzer = analyzer
                    logger.debug("✅ Загружен анализатор тональности DistilBERT (в фоне)")
                except Exception as e:
                    logger.debug(f"Не удалось загрузить анализатор тональности: {e}")
                    # Пробуем упрощенный способ через pipeline напрямую
                    try:
                        from transformers import pipeline
                        analyzer = pipeline(
                            "text-classification",
                            model="distilbert/distilbert-base-uncased-finetuned-sst-2-english",
                            device=-1
                        )
                        self.sentiment_analyzer = analyzer
                        logger.debug("✅ Загружен анализатор тональности через pipeline")
                    except Exception as e2:
                        logger.debug(f"Не удалось загрузить через pipeline: {e2}")
                        # Не критично - парсер работает без него
                        self.sentiment_analyzer = None
                finally:
                    self._sentiment_analyzer_loading = False
            
            # Запускаем загрузку в фоне
            thread = threading.Thread(target=load_analyzer, daemon=True)
            thread.start()
            
            # Не ждем завершения - возвращаем None пока идет загрузка
            return None
            
        except Exception as e:
            logger.debug(f"Ошибка инициализации анализатора тональности: {e}")
            self._sentiment_analyzer_loading = False
            return None
    
    def _check_ollama_availability(self):
        """Проверяет доступность Ollama и находит рабочий URL"""
        import asyncio
        from services.ollama_utils import find_working_ollama_url
        
        # Используем async функцию для поиска рабочего URL
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        working_url = loop.run_until_complete(find_working_ollama_url(timeout=2.0))
        if working_url:
            self.ollama_working_url = working_url
            logger.info(f"✅ Ollama доступен: {working_url}, модель: {self.ollama_model}")
            return True
        else:
            logger.warning("⚠️ Ollama недоступен. Функции с LLM будут отключены.")
            self.use_ollama = False
            return False
    
    async def _call_ollama(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        Вызывает Ollama для обработки текста
        
        Args:
            prompt: Пользовательский запрос
            system_prompt: Системный промпт (опционально)
        """
        if not self.use_ollama or not self.ollama_working_url:
            return None
        
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": self.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # Низкая температура для более точных ответов
                }
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_working_url}/api/chat",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                result = data.get("message", {}).get("content", "").strip()
                
                if result:
                    self.stats["ollama_extractions"] += 1
                    return result
                
        except Exception as e:
            logger.warning(f"Ошибка вызова Ollama: {e}")
            # Пробуем старый API /api/generate
            try:
                payload = {
                    "model": self.ollama_model,
                    "prompt": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt,
                    "stream": False
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{self.ollama_working_url}/api/generate",
                        json=payload
                    )
                    response.raise_for_status()
                    data = response.json()
                    result = data.get("response", "").strip()
                    
                    if result:
                        self.stats["ollama_extractions"] += 1
                        return result
            except Exception as e2:
                logger.debug(f"Ошибка вызова Ollama (старый API): {e2}")
        
        return None
    
    def _call_ollama_sync(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """Синхронная версия вызова Ollama"""
        if not self.use_ollama or not self.ollama_working_url:
            return None
        
        try:
            # Пробуем новый API /api/chat
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": self.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                }
            }
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.ollama_working_url}/api/chat",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                result = data.get("message", {}).get("content", "").strip()
                
                if result:
                    self.stats["ollama_extractions"] += 1
                    return result
                
        except Exception as e:
            logger.debug(f"Ошибка вызова Ollama (новый API): {e}")
            # Fallback на старый API
            try:
                payload = {
                    "model": self.ollama_model,
                    "prompt": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt,
                    "stream": False
                }
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(
                        f"{self.ollama_working_url}/api/generate",
                        json=payload
                    )
                    response.raise_for_status()
                    data = response.json()
                    result = data.get("response", "").strip()
                    
                    if result:
                        self.stats["ollama_extractions"] += 1
                        return result
            except Exception as e2:
                logger.debug(f"Ошибка вызова Ollama: {e2}")
        
        return None
    
    def _create_session(self):
        """Создает HTTP сессию с правильными заголовками"""
        if self.session is None:
            self.session = httpx.Client(
                timeout=30.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1"
                },
                follow_redirects=True
            )
        return self.session
    
    def _extract_entities_nlp(self, text: str) -> Dict[str, List[str]]:
        """
        Извлекает сущности из текста с помощью NLP
        Возвращает: даты, организации, локации, продукты, деньги
        """
        entities = {
            "dates": [],
            "organizations": [],
            "locations": [],
            "products": [],
            "money": [],
            "other": []
        }
        
        if not self.nlp_model or not text:
            return entities
        
        try:
            doc = self.nlp_model(text)
            
            for ent in doc.ents:
                label = ent.label_.upper()
                text_clean = ent.text.strip()
                
                if label in ('DATE', 'TIME'):
                    entities["dates"].append(text_clean)
                elif label in ('ORG', 'ORGANIZATION'):
                    entities["organizations"].append(text_clean)
                elif label in ('GPE', 'LOC'):
                    entities["locations"].append(text_clean)
                elif label == 'PRODUCT':
                    entities["products"].append(text_clean)
                elif label == 'MONEY':
                    entities["money"].append(text_clean)
                else:
                    entities["other"].append(f"{label}:{text_clean}")
            
            # Дополнительно извлекаем цены через регулярные выражения
            price_patterns = [
                r'\d+[\s,.]?\d*[\s,.]?\d*\s*₽',
                r'\d+[\s,.]?\d*[\s,.]?\d*\s*рубл',
                r'\d+[\s,.]?\d*[\s,.]?\d*\s*руб',
            ]
            for pattern in price_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                entities["money"].extend(matches)
            
            # Убираем дубликаты
            for key in entities:
                entities[key] = list(set(entities[key]))
            
            self.stats["nlp_extractions"] += 1
            
        except Exception as e:
            logger.warning(f"Ошибка извлечения сущностей: {e}")
        
        return entities
    
    def _analyze_sentiment(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Анализирует тональность текста (опционально)
        Использует простой эвристический анализ если ML модель недоступна
        """
        if not text:
            return None
        
        # Пытаемся загрузить анализатор лениво (если еще не загружен)
        if self.sentiment_analyzer is None and not self._sentiment_analyzer_loading:
            self._load_sentiment_analyzer()
        
        # Если ML модель доступна - используем её
        if self.sentiment_analyzer:
            try:
                # Ограничиваем длину текста для анализа
                text_short = text[:512]  # Максимум 512 символов
                result = self.sentiment_analyzer(text_short)
                
                # Форматируем результат
                if isinstance(result, list) and len(result) > 0:
                    return {
                        "label": result[0].get("label", "N/A"),
                        "score": result[0].get("score", 0.0),
                        "method": "ml"
                    }
            except Exception as e:
                logger.debug(f"Ошибка ML анализа тональности: {e}")
        
        # Простой эвристический анализ (если ML модель недоступна)
        try:
            text_lower = text.lower()
            positive_words = ['отличный', 'хороший', 'новый', 'качественный', 'надежный', 'премиум', 'комфорт']
            negative_words = ['проблема', 'неисправность', 'требует', 'ремонт', 'поврежден', 'авария']
            
            positive_count = sum(1 for word in positive_words if word in text_lower)
            negative_count = sum(1 for word in negative_words if word in text_lower)
            
            if positive_count > negative_count:
                return {"label": "POSITIVE", "score": 0.6, "method": "heuristic"}
            elif negative_count > positive_count:
                return {"label": "NEGATIVE", "score": 0.6, "method": "heuristic"}
            else:
                return {"label": "NEUTRAL", "score": 0.5, "method": "heuristic"}
        except Exception as e:
            logger.debug(f"Ошибка эвристического анализа тональности: {e}")
        
        return None
    
    def _detect_structure_changes(self, url: str, soup: BeautifulSoup) -> bool:
        """
        Обнаруживает изменения в структуре страницы
        Использует хеширование ключевых элементов для сравнения
        """
        try:
            # Извлекаем ключевые элементы структуры
            key_selectors = [
                soup.find('h1'),
                soup.find('title'),
                soup.find(class_=re.compile(r'price|cost', re.I)),
                soup.find(id=re.compile(r'price|cost', re.I)),
            ]
            
            structure_hash = hash(tuple(
                elem.get_text(strip=True) if elem else None
                for elem in key_selectors
            ))
            
            # Проверяем, изменилась ли структура
            if url in self.page_structure_cache:
                if self.page_structure_cache[url] != structure_hash:
                    self.stats["structure_changes_detected"] += 1
                    logger.warning(f"⚠️ Обнаружено изменение структуры страницы: {url}")
                    self.page_structure_cache[url] = structure_hash
                    return True
            else:
                self.page_structure_cache[url] = structure_hash
            
            return False
        except Exception as e:
            logger.warning(f"Ошибка обнаружения изменений структуры: {e}")
            return False
    
    def _classify_text_element(self, text: str, element_type: str = None) -> str:
        """
        Классифицирует элемент текста (заголовок, описание, цена, характеристика и т.д.)
        """
        if not text:
            return "unknown"
        
        text_lower = text.lower().strip()
        
        # Классификация по ключевым словам (приоритет точным совпадениям)
        if any(word in text_lower for word in ['₽', 'руб', 'рубль', 'цена', 'стоимость', 'cost', 'price']):
            return "price"
        elif any(word in text_lower for word in ['год', 'year']) and any(word in text_lower for word in ['выпуск', 'производств']):
            return "year"
        elif 'год выпуска' in text_lower or 'год производства' in text_lower:
            return "year"
        elif any(word in text_lower for word in ['тип кузова', 'кузов', 'body']):
            return "body_type"
        elif 'тип двигателя' in text_lower or any(word in text_lower for word in ['топливо', 'fuel', 'бензин', 'дизель', 'газ', 'гибрид']):
            return "fuel_type"
        elif text_lower == 'кпп' or any(word in text_lower for word in ['коробка передач', 'transmission', 'gearbox', 'коробка']):
            return "gear_box"
        elif 'привод' in text_lower or any(word in text_lower for word in ['drive', 'полный', 'передний', 'задний']):
            return "drive_type"
        elif 'объем двигателя' in text_lower or ('объем' in text_lower and 'двигатель' in text_lower):
            return "engine"
        elif 'мощность двигателя' in text_lower or ('мощность' in text_lower and 'двигатель' in text_lower):
            return "engine"
        elif 'пробег' in text_lower or any(word in text_lower for word in ['mileage', 'км']):
            return "mileage"
        elif 'цвет' in text_lower or any(word in text_lower for word in ['color', 'окрас']):
            return "color"
        elif any(word in text_lower for word in ['город', 'city', 'локация']):
            return "location"
        elif element_type == 'h1' or element_type == 'title':
            return "title"
        else:
            return "description"
    
    def _extract_number(self, text: str) -> Optional[int]:
        """Извлекает число из текста с улучшенной обработкой"""
        if not text:
            return None
        
        # Убираем все символы кроме цифр
        numbers = re.findall(r'\d+', str(text).replace(' ', '').replace(',', '').replace('.', ''))
        if numbers:
            return int(numbers[0])
        return None
    
    def _extract_price(self, text: str) -> Optional[str]:
        """Улучшенное извлечение цены с использованием NLP"""
        if not text:
            return None
        
        # Сначала пробуем извлечь через NLP
        entities = self._extract_entities_nlp(text)
        if entities.get("money"):
            # Берем первую найденную цену
            price_text = entities["money"][0]
            # Очищаем от символов валюты
            price_clean = re.sub(r'[^\d\s,.]', '', price_text)
            return price_clean.strip()
        
        # Fallback на регулярные выражения
        price_patterns = [
            r'(\d+[\s,.]?\d*[\s,.]?\d*)\s*₽',
            r'(\d+[\s,.]?\d*[\s,.]?\d*)\s*рубл',
            r'(\d+[\s,.]?\d*[\s,.]?\d*)\s*руб',
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
    
    def _intelligent_extract_car_data(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """
        Интеллектуальное извлечение данных об автомобиле со СТРАНИЦЫ АВТОМОБИЛЯ
        ВАЖНО: Этот метод предназначен для парсинга отдельной страницы автомобиля,
        а не карточки в каталоге. Селекторы оптимизированы для полной страницы.
        """
        # Определяем тип автомобиля по URL (new/used)
        car_type = "new" if "/sale/new/" in url else "used" if "/sale/used/" in url else "unknown"
        
        car_data = {
            "source_url": url,
            "mark": None,
            "model": None,
            "city": None,
            "price": None,
            "manufacture_year": None,
            "body_type": None,
            "fuel_type": None,
            "gear_box_type": None,
            "driving_gear_type": None,
            "engine_vol": None,
            "power": None,
            "color": None,
            "mileage": None,  # Для новых автомобилей будет None
            "characteristics": {},
            "pictures": [],
            "sentiment": None,
            "nlp_entities": {},
            "ollama_extracted": {},
            "car_type": car_type  # Сохраняем тип автомобиля
        }
        
        logger.info(f"   🚗 Тип автомобиля: {'Новый' if car_type == 'new' else 'Подержанный' if car_type == 'used' else 'Неизвестно'}")
        
        logger.debug(f"🔍 Начало интеллектуального извлечения данных для: {url}")
        
        # Получаем весь текст страницы для анализа
        page_text = soup.get_text(separator=' ', strip=True)
        logger.debug(f"   Размер текста страницы: {len(page_text)} символов")
        
        # Используем Ollama для извлечения структурированных данных
        if self.use_ollama and self.ollama_working_url:
            ollama_data = self._extract_with_ollama(page_text, soup)
            if ollama_data:
                car_data["ollama_extracted"] = ollama_data
                # Объединяем данные из Ollama с основными
                for key, value in ollama_data.items():
                    if key in car_data and not car_data[key] and value:
                        car_data[key] = value
        
        # Извлекаем сущности через NLP
        entities = self._extract_entities_nlp(page_text)
        car_data["nlp_entities"] = entities
        
        # Анализ тональности (для описаний)
        description_elements = soup.find_all(['p', 'div'], class_=re.compile(r'description|about|info', re.I))
        if description_elements:
            description_text = ' '.join([elem.get_text(strip=True) for elem in description_elements[:3]])
            car_data["sentiment"] = self._analyze_sentiment(description_text)
        
        # Специфичное извлечение для aaa-motors.ru (СТРАНИЦА АВТОМОБИЛЯ)
        # Ищем заголовок в различных местах (приоритет странице автомобиля, не карточке)
        title_selectors = [
            # Приоритетные селекторы для СТРАНИЦЫ АВТОМОБИЛЯ (не карточки каталога)
            soup.find('h1'),  # Обычно h1 содержит марку и модель на странице авто
            soup.find('h1', class_=re.compile(r'car-title|car-name|title', re.I)),
            soup.find('div', class_=re.compile(r'car-title|car-name|car-header', re.I)),
            soup.find('div', class_=re.compile(r'product-title|product-name', re.I)),
            # Мета-теги (обычно содержат полное название)
            soup.find('meta', property='og:title'),
            soup.find('meta', attrs={'name': 'title'}),
            soup.find('title'),
            # Fallback на карточку (только если ничего не найдено)
            soup.find('div', class_=re.compile(r'item__title|js-item-title', re.I)),
        ]
        
        logger.debug(f"🔍 Поиск заголовка автомобиля...")
        
        title_text = None
        for idx, title_elem in enumerate(title_selectors):
            if title_elem:
                if title_elem.name == 'meta':
                    title_text = title_elem.get('content', '')
                else:
                    title_text = title_elem.get_text(strip=True)
                if title_text and len(title_text) > 3:
                    # Очищаем от лишних символов
                    title_text = re.sub(r'\s+', ' ', title_text).strip()
                    logger.debug(f"   ✅ Заголовок найден через селектор #{idx}: {title_text[:100]}")
                    break
        
        if not title_text:
            logger.warning(f"   ⚠️ Заголовок не найден ни одним селектором")
        
        # Если не нашли, пробуем поиск по тексту страницы
        if not title_text:
            # Ищем паттерны типа "Daewoo Matiz" или "BMW X5" в тексте
            title_pattern = re.search(r'([A-ZА-Я][a-zа-я]+(?:\s+[A-ZА-Я][a-zа-я]+)+)', page_text[:500])
            if title_pattern:
                title_text = title_pattern.group(1)
        
        if title_text:
            # Очищаем заголовок от лишних слов
            title_text = re.sub(r'\s+(в наличии|купить|продажа|автомобиль|продам|купить|цена)', '', title_text, flags=re.I).strip()
            
            # Убираем дубликаты (для случаев типа "Москвич МОСКВИЧ 3" или "Daewoo Daewoo Matiz")
            words = title_text.split()
            unique_words = []
            seen_lower = set()
            for word in words:
                word_clean = word.strip()
                if word_clean and len(word_clean) > 1:
                    word_lower = word_clean.lower()
                    # Игнорируем дубликаты (только если слово не является числом)
                    if word_lower not in seen_lower or word_clean.isdigit():
                        unique_words.append(word_clean)
                        if not word_clean.isdigit():
                            seen_lower.add(word_lower)
            
            title_text_clean = " ".join(unique_words)
            
            # Используем NLP для извлечения марки и модели
            title_entities = self._extract_entities_nlp(title_text_clean)
            
            # Пытаемся найти марку и модель в заголовке
            # Формат обычно: "Daewoo Matiz" или "BMW X5" или "Москвич МОСКВИЧ 3"
            title_parts = [p for p in title_text_clean.split() if len(p) > 1]  # Убираем одиночные символы
            
            if len(title_parts) >= 2:
                # Первое слово обычно марка
                car_data["mark"] = title_parts[0]
                # Остальные слова - модель (но не более 3 слов)
                car_data["model"] = " ".join(title_parts[1:min(4, len(title_parts))])
                logger.debug(f"   ✅ Марка и модель извлечены: {car_data['mark']} {car_data['model']}")
            elif len(title_parts) == 1:
                # Если только одно слово - это может быть марка или модель
                car_data["mark"] = title_parts[0]
                logger.debug(f"   ⚠️ Только марка извлечена: {car_data['mark']}")
                
                # Пробуем извлечь модель из URL
                url_parts = url.rstrip('/').split('/')
                if len(url_parts) >= 5:
                    potential_model = url_parts[-2].replace('-', ' ').title()
                    if potential_model and potential_model.lower() != car_data["mark"].lower():
                        car_data["model"] = potential_model
                        logger.debug(f"   ✅ Модель извлечена из URL: {car_data['model']}")
            
            # Дополнительно используем NLP сущности (PRODUCT)
            if entities.get("products"):
                for product in entities["products"]:
                    product_clean = re.sub(r'[^\w\s]', '', product).strip()
                    parts = [p for p in product_clean.split() if len(p) > 1]
                    if len(parts) >= 2:
                        if not car_data["mark"]:
                            car_data["mark"] = parts[0]
                            logger.debug(f"   ✅ Марка из NLP: {car_data['mark']}")
                        if not car_data["model"]:
                            car_data["model"] = " ".join(parts[1:min(4, len(parts))])
                            logger.debug(f"   ✅ Модель из NLP: {car_data['model']}")
        else:
            logger.warning(f"   ⚠️ Заголовок не найден, марка и модель не извлечены")
            
            # Fallback: извлекаем из URL
            url_parts = url.rstrip('/').split('/')
            if len(url_parts) >= 5:
                if not car_data.get("mark"):
                    car_data["mark"] = url_parts[-3].replace('-', ' ').title()
                    logger.info(f"   ✅ Марка извлечена из URL: {car_data['mark']}")
                if not car_data.get("model"):
                    car_data["model"] = url_parts[-2].replace('-', ' ').title()
                    logger.info(f"   ✅ Модель извлечена из URL: {car_data['model']}")
        
        # Интеллектуальное извлечение цены (более агрессивный поиск)
        price_candidates = []
        
        # Метод 1: Специфичный поиск для aaa-motors.ru (страница автомобиля)
        # ПРИОРИТЕТ 1: card-info__price-main (основной селектор для страницы автомобиля)
        logger.debug("🔍 Поиск цены через card-info__price-main...")
        card_info_price = soup.find('div', class_='card-info__price-main')
        if not card_info_price:
            # Пробуем с regex
            card_info_price = soup.find('div', class_=re.compile(r'card-info__price-main', re.I))
        if card_info_price:
            price_text = card_info_price.get_text(strip=True)
            if price_text:
                logger.info(f"   ✅ Цена найдена через card-info__price-main: {price_text}")
                print(f"   ✅ Цена найдена: {price_text}")
                price_candidates.append(price_text)
            else:
                logger.debug(f"   ⚠️ card-info__price-main найден, но текст пустой")
        else:
            logger.debug(f"   ⚠️ card-info__price-main не найден")
        
        # ПРИОРИТЕТ 2: card-info__price (блок с ценой)
        logger.debug("🔍 Поиск цены через card-info__price...")
        card_info_price_block = soup.find('div', class_='card-info__price')
        if not card_info_price_block:
            card_info_price_block = soup.find('div', class_=re.compile(r'card-info__price', re.I))
        if card_info_price_block:
            price_elem = card_info_price_block.find('div', class_='card-info__price-main')
            if not price_elem:
                price_elem = card_info_price_block.find('div', class_=re.compile(r'card-info__price-main|price-main', re.I))
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                if price_text and price_text not in price_candidates:
                    logger.info(f"   ✅ Цена найдена через card-info__price: {price_text}")
                    print(f"   ✅ Цена найдена: {price_text}")
                    price_candidates.append(price_text)
            else:
                # Пробуем найти любой текст внутри card-info__price
                price_text = card_info_price_block.get_text(strip=True)
                # Ищем цену в тексте
                price_match = re.search(r'(\d{1,3}(?:\s+\d{3})+)\s*[рр]\.?', price_text)
                if price_match:
                    price_found = price_match.group(1).replace(' ', '') + ' р.'
                    if price_found not in price_candidates:
                        logger.info(f"   ✅ Цена извлечена из card-info__price: {price_found}")
                        print(f"   ✅ Цена найдена: {price_found}")
                        price_candidates.append(price_found)
        
        # ПРИОРИТЕТ 3: card__aside-block или card__main - основные блоки с ценой
        price_blocks = [
            soup.find('div', class_=re.compile(r'card__aside-block|card__main|card__header', re.I)),
            soup.find('div', class_=re.compile(r'card__price|card-price', re.I)),
        ]
        
        for block in price_blocks:
            if block:
                # Ищем цену внутри блока
                price_elem = block.find('div', class_=re.compile(r'price|cost', re.I))
                if not price_elem:
                    price_elem = block.find('span', class_=re.compile(r'price|cost', re.I))
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    if price_text and price_text not in price_candidates:
                        price_candidates.append(price_text)
        
        # ПРИОРИТЕТ 4: Все элементы с классами price
        price_selectors = [
            soup.find_all('div', class_=re.compile(r'card__price|card-price|item__price-main|price-main|item__price', re.I)),
            soup.find_all('span', class_=re.compile(r'card__price|price|cost|стоимость', re.I)),
            soup.find_all('div', class_=re.compile(r'price|cost|стоимость', re.I)),
            soup.find_all(class_=re.compile(r'price|cost|стоимость', re.I)),
            soup.find_all(id=re.compile(r'price|cost', re.I)),
        ]
        
        for selector_list in price_selectors:
            for elem in selector_list:
                price_text = elem.get_text(strip=True)
                if price_text and price_text not in price_candidates:
                    price_candidates.append(price_text)
        
        # Метод 2: Поиск через NLP (деньги)
        if entities.get("money"):
            price_candidates.extend(entities["money"])
        
        # Метод 3: Поиск по тексту страницы (более агрессивный)
        # Ищем паттерны: "217 000 р.", "217000 руб", "217000₽", "217 000 ₽"
        price_patterns = [
            re.search(r'(\d{1,3}(?:\s+\d{3})+)\s*[рр]\.?', page_text),
            re.search(r'(\d{1,3}(?:\s+\d{3})+)\s*руб', page_text, re.I),
            re.search(r'(\d{1,3}(?:\s+\d{3})+)\s*₽', page_text),
            re.search(r'₽\s*(\d{1,3}(?:\s+\d{3})+)', page_text),
            re.search(r'(\d{1,3}(?:\s+\d{3})+)\s*₽', page_text),
            # Также ищем числа от 100000 до 10000000 (разумные цены)
            re.search(r'(\d{6,7})\s*(?:руб|р\.?|₽)', page_text, re.I),
        ]
        
        for pattern in price_patterns:
            if pattern:
                price_text = pattern.group(1).replace(' ', '') + ' р.'
                if price_text not in price_candidates:
                    price_candidates.append(price_text)
        
        # Метод 3.5: Поиск в структурированных данных (data-атрибуты, мета-теги)
        meta_price = soup.find('meta', property=re.compile(r'price|cost', re.I))
        if meta_price:
            price_content = meta_price.get('content', '')
            if price_content:
                price_candidates.append(price_content)
        
        # Метод 4: Используем функцию извлечения цены
        price_text = self._extract_price(page_text)
        if price_text:
            price_candidates.append(price_text)
        
        # Выбираем лучшую цену (самую большую числовую)
        best_price = None
        best_price_value = 0
        logger.debug(f"   🔍 Обработка {len(price_candidates)} кандидатов на цену...")
        
        for candidate in price_candidates:
            logger.debug(f"      Кандидат: {candidate}")
            # Сначала пробуем извлечь через _extract_price
            extracted_price = self._extract_price(candidate)
            if not extracted_price:
                # Если не получилось, пробуем извлечь число напрямую
                # Формат может быть "455 000 р." или "455000 р."
                price_num_str = re.sub(r'[^\d]', '', candidate)
                if price_num_str and len(price_num_str) >= 5:  # Минимум 5 цифр для цены
                    extracted_price = price_num_str
                    logger.debug(f"      Извлечено число напрямую: {extracted_price}")
            
            if extracted_price:
                # Извлекаем числовое значение для сравнения
                price_num = self._extract_number(extracted_price)
                if price_num and price_num > best_price_value:
                    best_price_value = price_num
                    # Форматируем цену в читаемый вид (например "455 000 р.")
                    if price_num >= 1000:
                        best_price = f"{price_num:,}".replace(',', ' ') + ' р.'
                    else:
                        best_price = str(price_num) + ' р.'
                    logger.info(f"   ✅ Новая лучшая цена: {best_price} (значение: {best_price_value})")
        
        if best_price:
            car_data["price"] = best_price
            logger.info(f"   ✅ Цена установлена: {best_price}")
            print(f"   ✅ Цена установлена: {best_price}")
        else:
            logger.warning(f"   ⚠️ Цена не установлена из {len(price_candidates)} кандидатов")
            if price_candidates:
                logger.warning(f"      Кандидаты: {price_candidates}")
        
        # Интеллектуальное извлечение города
        # Специфичный поиск для aaa-motors.ru
        city_selectors = [
            soup.find('div', class_=re.compile(r'item-row__info-address|address|city', re.I)),
            soup.find('span', class_=re.compile(r'address|city|location', re.I)),
        ]
        
        for city_elem in city_selectors:
            if city_elem:
                city_text = city_elem.get_text(strip=True)
                # Извлекаем город из адреса (например: "АСП ААА Моторс Ростов Текучева 352Б" -> "Ростов")
                if city_text:
                    # Пытаемся найти название города
                    city_parts = city_text.split()
                    for part in city_parts:
                        if len(part) > 3 and not part[0].isdigit():
                            # Проверяем, не является ли это названием города
                            if any(word in part.lower() for word in ['москв', 'ростов', 'спб', 'питер', 'казан', 'нижн', 'новосиб', 'екатерин']):
                                car_data["city"] = part
                                break
                    if not car_data["city"] and city_text:
                        # Убираем лишние символы и запятые
                        city_clean = re.sub(r'[,;]\s*$', '', city_text).strip()
                        car_data["city"] = city_clean
        
        # Если не нашли через селекторы, используем NLP
        if not car_data["city"] and entities.get("locations"):
            # Берем первую локацию как город и очищаем
            city_from_entities = entities["locations"][0]
            if city_from_entities:
                car_data["city"] = re.sub(r'[,;]\s*$', '', city_from_entities).strip()
        
        # Очистка города от лишних символов
        if car_data["city"]:
            car_data["city"] = re.sub(r'[,;]\s*$', '', car_data["city"]).strip()
        
        # Интеллектуальное извлечение года
        # Специфичный поиск для aaa-motors.ru
        year_selectors = [
            # Ищем по тексту "Год выпуска: 2009"
            soup.find_all(string=re.compile(r'Год\s+выпуска|Год\s+производства', re.I)),
        ]
        
        for year_elem in year_selectors:
            if year_elem:
                # Ищем родительский элемент с годом
                parent = year_elem.parent if hasattr(year_elem, 'parent') else None
                if parent:
                    parent_text = parent.get_text(strip=True)
                    year = self._extract_number(parent_text)
                    if year and 1900 <= year <= 2100 and not car_data["manufacture_year"]:
                        car_data["manufacture_year"] = year
                        break
        
        # Fallback на NLP извлечение
        if not car_data["manufacture_year"] and entities.get("dates"):
            for date_text in entities["dates"]:
                year = self._extract_number(date_text)
                if year and 1900 <= year <= 2100:  # Разумный диапазон
                    car_data["manufacture_year"] = year
                    break
        
        # Адаптивный парсинг характеристик
        # Специфичный поиск для aaa-motors.ru
        # ПРИОРИТЕТ 1: card__tech (страница автомобиля) - структура <div><span>Название</span><span>Значение</span></div>
        # Поддерживаем как для новых, так и для подержанных автомобилей
        card_tech = soup.find('div', class_=re.compile(r'card__tech|js-card-tech', re.I))
        if card_tech:
            logger.debug("🔍 Найдена структура card__tech, парсинг характеристик...")
            # Ищем все дочерние div элементы
            tech_items = card_tech.find_all('div', recursive=False)
            logger.debug(f"   Найдено элементов характеристик: {len(tech_items)}")
            
            for tech_item in tech_items:
                # Ищем два span элемента: первый - название, второй - значение
                spans = tech_item.find_all('span', recursive=False)
                if len(spans) >= 2:
                    key = spans[0].get_text(strip=True)
                    value = spans[1].get_text(strip=True)
                    key_lower = key.lower()
                    
                    logger.debug(f"   📋 Извлечено: {key} = {value}")
                    
                    # Обрабатываем критичные характеристики
                    self._parse_characteristic(key, value, car_data)
                    
                    # Сохраняем дополнительные характеристики в JSON
                    if not car_data.get("characteristics"):
                        car_data["characteristics"] = {}
                    
                    # Сохраняем все характеристики, включая нестандартные
                    # Исключаем стандартные поля, которые уже обработаны
                    standard_fields = ['год выпуска', 'год', 'объем двигателя', 'объем', 
                                      'тип двигателя', 'мощность двигателя', 'мощность',
                                      'пробег', 'привод', 'кпп', 'цвет', 'руль', 'тип кузова',
                                      'кузов', 'макс скорость', 'вес']
                    
                    if key_lower not in standard_fields:
                        # Это дополнительные характеристики (макс скорость, вес и т.д.)
                        car_data["characteristics"][key] = value
                    elif key_lower in ['макс скорость', 'вес']:
                        # Сохраняем макс скорость и вес в characteristics
                        car_data["characteristics"][key] = value
        
        # ПРИОРИТЕТ 2: Парсинг комплектации (card__com-wrap)
        card_com = soup.find('div', class_=re.compile(r'card__com-wrap|js-card-com', re.I))
        if card_com:
            logger.debug("🔍 Найдена структура комплектации (card__com-wrap), парсинг опций...")
            
            # Ищем все элементы списка опций
            com_items = card_com.find_all('div', class_=re.compile(r'card__com-item|com-item', re.I))
            all_options = []
            
            for com_item in com_items:
                # Ищем ul списки внутри
                ul_lists = com_item.find_all('ul')
                for ul in ul_lists:
                    # Ищем все li элементы
                    li_items = ul.find_all('li')
                    for li in li_items:
                        option_text = li.get_text(strip=True)
                        if option_text and len(option_text) > 3:  # Минимальная длина опции
                            all_options.append(option_text)
            
            if all_options:
                # Сохраняем комплектацию в characteristics
                if not car_data.get("characteristics"):
                    car_data["characteristics"] = {}
                
                car_data["characteristics"]["equipment"] = all_options
                car_data["characteristics"]["equipment_count"] = len(all_options)
                logger.info(f"   ✅ Извлечено опций комплектации: {len(all_options)}")
                logger.debug(f"   📋 Первые 5 опций: {all_options[:5]}")
        
        # ПРИОРИТЕТ 3: Другие контейнеры с характеристиками
        spec_containers = [
            # Для страницы автомобиля - ищем по структуре данных
            soup.find_all('div', class_=re.compile(r'spec|characteristic|param|feature|car-info', re.I)),
            # Для карточки каталога
            soup.find_all('div', class_=re.compile(r'item__tech|tech', re.I)),
            # Стандартные контейнеры
            soup.find_all('table'),
            soup.find_all('dl'),
            soup.find_all('ul', class_=re.compile(r'spec|list|feature', re.I)),
        ]
        
        for container_list in spec_containers:
            for container in container_list:
                # Извлекаем пары ключ-значение
                if container.name == 'table':
                    rows = container.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            key = cells[0].get_text(strip=True).lower()
                            value = cells[1].get_text(strip=True)
                            self._parse_characteristic(key, value, car_data)
                
                elif container.name == 'dl':
                    dts = container.find_all('dt')
                    dds = container.find_all('dd')
                    for dt, dd in zip(dts, dds):
                        key = dt.get_text(strip=True).lower()
                        value = dd.get_text(strip=True)
                        self._parse_characteristic(key, value, car_data)
                
                # Дополнительно ищем характеристики в структуре "Название: Значение"
                # Это для страницы автомобиля, где данные могут быть в разных форматах
                if container.name in ['div', 'section', 'article']:
                    # Ищем все элементы с текстом вида "Название: Значение"
                    text_elements = container.find_all(string=re.compile(r'[А-Яа-я]+\s*:', re.I))
                    for text_elem in text_elements:
                        if text_elem.parent:
                            full_text = text_elem.parent.get_text(strip=True)
                            if ':' in full_text:
                                parts = full_text.split(':', 1)
                                if len(parts) == 2:
                                    key = parts[0].strip().lower()
                                    value = parts[1].strip()
                                    self._parse_characteristic(key, value, car_data)
                
                elif container.name in ['div', 'ul']:
                    # Специфичная обработка для aaa-motors.ru
                    # В item__tech данные разделены <div> элементами
                    # Формат HTML: <div>2009 г.<span>\</span></div>
                    items = container.find_all(['li', 'div'], recursive=False)
                    if not items:
                        # Если прямых дочерних элементов нет, ищем все элементы
                        items = container.find_all(['li', 'div', 'span'])
                    
                    for item in items:
                        # Получаем текст, игнорируя дочерние элементы с разделителями
                        text = ''
                        for child in item.children:
                            if hasattr(child, 'string') and child.string:
                                text += child.string
                            elif hasattr(child, 'get_text'):
                                child_text = child.get_text(strip=True)
                                # Пропускаем разделители типа "\"
                                if child_text and child_text not in ['\\', '|', '/']:
                                    text += ' ' + child_text
                        
                        if not text:
                            text = item.get_text(strip=True)
                        
                        # Для aaa-motors.ru формат: "2009 г.\" или "145 000 км\" или "Бензин\"
                        # Убираем обратный слеш и разделители
                        text = re.sub(r'[\\|/]', '', text).strip()
                        
                        if not text or len(text) < 2:
                            continue
                        
                        # Пытаемся найти паттерн "ключ: значение"
                        if ':' in text:
                            parts = text.split(':', 1)
                            if len(parts) == 2:
                                key = parts[0].strip().lower()
                                value = parts[1].strip()
                                self._parse_characteristic(key, value, car_data)
                        else:
                            # Пытаемся определить тип данных по содержимому
                            # Формат: "2009 г." -> год
                            if re.search(r'\d{4}\s*г\.?', text):
                                year = self._extract_number(text)
                                if year and 1900 <= year <= 2100 and not car_data["manufacture_year"]:
                                    car_data["manufacture_year"] = year
                            # Формат: "145 000 км" -> пробег
                            elif 'км' in text.lower():
                                mileage = self._extract_number(text)
                                if mileage and not car_data["mileage"]:
                                    car_data["mileage"] = mileage
                            # Формат: "0.8 л" -> объем
                            elif re.search(r'\d+\.?\d*\s*л\b', text, re.I):
                                vol_text = re.search(r'(\d+\.?\d*)', text)
                                if vol_text:
                                    try:
                                        vol = float(vol_text.group(1))
                                        if not car_data["engine_vol"]:
                                            car_data["engine_vol"] = int(vol)
                                    except:
                                        pass
                            # Формат: "52 л.с." -> мощность
                            elif 'л.с.' in text.lower() or 'лс' in text.lower():
                                power_text = text.replace('л.с.', '').replace('лс', '').strip()
                                if not car_data["power"]:
                                    car_data["power"] = power_text
                            # Бензин, Дизель -> топливо
                            elif any(word in text.lower() for word in ['бензин', 'дизель', 'электро', 'гибрид']):
                                if not car_data["fuel_type"]:
                                    car_data["fuel_type"] = text
                            # Механика, Автомат -> коробка
                            elif any(word in text.lower() for word in ['механик', 'автомат', 'вариатор', 'робот']):
                                if not car_data["gear_box_type"]:
                                    car_data["gear_box_type"] = text
                            # Привод: Передний, Задний, Полный
                            elif any(word in text.lower() for word in ['передний', 'задний', 'полный', '4wd', 'awd']):
                                if not car_data["driving_gear_type"]:
                                    car_data["driving_gear_type"] = text
                            # Тип кузова: Хетчбэк, Седан, и т.д.
                            elif any(word in text.lower() for word in ['хетчбэк', 'седан', 'универсал', 'купе', 'внедорожник', 'suv', 'кроссовер']):
                                if not car_data["body_type"]:
                                    car_data["body_type"] = text
                            # Цвет (если указан явно)
                            elif any(word in text.lower() for word in ['синий', 'красный', 'черный', 'белый', 'серый', 'зеленый']):
                                if not car_data["color"]:
                                    car_data["color"] = text
        
        # Интеллектуальное извлечение фотографий
        # Специфичный поиск для aaa-motors.ru (использует data-src и lozad)
        img_selectors = [
            # Основной селектор для aaa-motors.ru (lozad lazy loading)
            soup.find_all('img', class_=re.compile(r'lozad|item-row__img', re.I)),
            soup.find_all('img', {'data-src': True}),
            soup.find_all('img', class_=re.compile(r'car|photo|image|gallery|auto', re.I)),
            soup.find_all('img', src=re.compile(r'car|auto|photo|image|media\.cm\.expert', re.I)),
            soup.find_all('img', alt=re.compile(r'car|auto|машин|автомобил', re.I)),
        ]
        
        all_images = set()
        for selector_list in img_selectors:
            for img in selector_list:
                # Приоритет: data-src (для lazy loading), затем src
                src = img.get('data-src') or img.get('src') or img.get('data-lazy-src') or img.get('data-original')
                if src:
                    # Убираем параметры загрузки, если есть
                    if '?' in src:
                        src = src.split('?')[0]
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = urljoin(self.base_url, src)
                    elif not src.startswith('http'):
                        src = urljoin(self.base_url, src)
                    # Фильтруем placeholder изображения
                    if 'placeholder' not in src.lower() and 'no-image' not in src.lower():
                        all_images.add(src)
        
        sorted_images = sorted(list(all_images))
        for idx, img_url in enumerate(sorted_images[:20]):
            car_data["pictures"].append({
                "image_url": img_url,
                "seqno": idx
            })
        
        return car_data
    
    def _extract_with_ollama(self, page_text: str, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        Извлекает структурированные данные об автомобиле с помощью Ollama LLM
        """
        if not self.use_ollama or not self.ollama_working_url:
            return None
        
        # Формируем промпт для Ollama
        system_prompt = """Ты — эксперт по извлечению данных об автомобилях из текста. 
Извлекай только факты, которые есть в тексте. Отвечай ТОЛЬКО в формате JSON без дополнительных комментариев.
Если данных нет, используй null."""
        
        user_prompt = f"""Извлеки из следующего текста информацию об автомобиле в формате JSON:
{{
  "mark": "марка автомобиля или null",
  "model": "модель автомобиля или null",
  "city": "город расположения или null",
  "price": "цена в рублях (только цифры) или null",
  "manufacture_year": "год выпуска (только число) или null",
  "body_type": "тип кузова или null",
  "fuel_type": "тип топлива или null",
  "gear_box_type": "тип коробки передач или null",
  "driving_gear_type": "тип привода или null",
  "engine_vol": "объем двигателя в литрах (только число) или null",
  "power": "мощность в л.с. или null",
  "color": "цвет автомобиля или null",
  "mileage": "пробег в км (только число) или null"
}}

Текст страницы:
{page_text[:3000]}"""
        
        try:
            result = self._call_ollama_sync(user_prompt, system_prompt)
            if result:
                # Пытаемся извлечь JSON из ответа (поддержка вложенных объектов)
                # Ищем JSON объект, начиная с первой {
                start_idx = result.find('{')
                if start_idx != -1:
                    # Ищем парную закрывающую скобку
                    bracket_count = 0
                    end_idx = start_idx
                    for i in range(start_idx, len(result)):
                        if result[i] == '{':
                            bracket_count += 1
                        elif result[i] == '}':
                            bracket_count -= 1
                            if bracket_count == 0:
                                end_idx = i + 1
                                break
                    
                    if bracket_count == 0:
                        json_str = result[start_idx:end_idx]
                        try:
                            extracted_data = json.loads(json_str)
                            logger.debug(f"✅ Ollama извлек данные: {len(extracted_data)} полей")
                            return extracted_data
                        except json.JSONDecodeError as e:
                            logger.warning(f"Ошибка парсинга JSON от Ollama: {e}")
                            logger.debug(f"Ответ Ollama: {result[:200]}")
                    else:
                        logger.debug(f"Неполный JSON в ответе Ollama: {result[:200]}")
                else:
                    logger.debug(f"JSON не найден в ответе Ollama: {result[:200]}")
        except Exception as e:
            logger.warning(f"Ошибка извлечения данных через Ollama: {e}")
        
        return None
    
    def _parse_characteristic(self, key: str, value: str, car_data: Dict[str, Any]):
        """Парсит характеристику на основе ключа и классификации"""
        classification = self._classify_text_element(key)
        
        if classification == "price" and not car_data["price"]:
            car_data["price"] = self._extract_price(value)
        elif classification == "year" and not car_data["manufacture_year"]:
            year = self._extract_number(value)
            if year and 1900 <= year <= 2100:
                car_data["manufacture_year"] = year
        elif classification == "body_type" and not car_data["body_type"]:
            car_data["body_type"] = value
        elif classification == "fuel_type" and not car_data["fuel_type"]:
            car_data["fuel_type"] = value
        elif classification == "gear_box" and not car_data["gear_box_type"]:
            car_data["gear_box_type"] = value
        elif classification == "drive_type" and not car_data["driving_gear_type"]:
            car_data["driving_gear_type"] = value
        elif classification == "engine_volume":
            # Это объем двигателя
            if 'объем' in key.lower() or 'объем двигателя' in key.lower() or ('л' in value.lower() and 'л.с.' not in value.lower() and 'лс' not in value.lower()):
                # Извлекаем объем в литрах (например: "0.8 л" -> 800, "1.0 л" -> 1000, "1.6 л" -> 1600)
                vol_text = value.lower().replace('л', '').replace('л.', '').replace('литр', '').replace('литров', '').strip()
                
                # Убираем пробелы и запятые
                vol_text = vol_text.replace(' ', '').replace(',', '.')
                
                try:
                    # Пробуем извлечь число с точкой или без
                    if '.' in vol_text:
                        vol_float = float(vol_text)
                        # Если число меньше 10, это литры - умножаем на 1000
                        # Если число больше 10, это уже миллилитры
                        if vol_float < 10:
                            vol = int(vol_float * 1000)  # 0.8 л = 800 мл, 1.0 л = 1000 мл, 1.6 л = 1600 мл
                        else:
                            vol = int(vol_float)  # Уже в миллилитрах
                    else:
                        # Целое число
                        vol = int(vol_text)
                        # Если число меньше 10, это литры - умножаем на 1000
                        if vol < 10:
                            vol = vol * 1000  # 1 л = 1000 мл
                        # Если число больше 10000, возможно это уже в миллилитрах без запятой
                        # Но обычно объемы до 10 литров, так что умножаем на 1000 если меньше 10
                except (ValueError, AttributeError):
                    # Если не получилось распарсить, пробуем через _extract_number
                    vol = self._extract_number(value)
                    # Если число меньше 10, умножаем на 1000
                    if vol and vol < 10:
                        vol = vol * 1000
                
                if vol and not car_data["engine_vol"]:
                    car_data["engine_vol"] = vol
                    # Форматируем для логирования
                    if vol >= 1000:
                        vol_litres = vol / 1000.0
                        logger.debug(f"   ✅ Объем двигателя: {vol} мл ({vol_litres:.1f} л)")
                    else:
                        logger.debug(f"   ✅ Объем двигателя: {vol} мл")
        elif classification == "engine_power":
            # Это мощность двигателя
            if 'мощность' in key.lower() or 'мощность двигателя' in key.lower() or 'л.с.' in value.lower() or 'лс' in value.lower():
                if not car_data["power"]:
                    car_data["power"] = value
                    logger.debug(f"   ✅ Мощность: {value}")
        elif classification == "mileage" and not car_data["mileage"]:
            car_data["mileage"] = self._extract_number(value)
        elif classification == "color" and not car_data["color"]:
            car_data["color"] = value
        elif classification == "location" and not car_data["city"]:
            car_data["city"] = value
        else:
            # Сохраняем в дополнительные характеристики
            car_data["characteristics"][key] = value
    
    def _extract_from_catalog_card(self, card_element, url: str) -> Dict[str, Any]:
        """
        Извлекает данные об автомобиле из карточки каталога
        Используется когда парсится страница каталога, а не отдельная страница
        """
        car_data = {
            "source_url": url,
            "mark": None,
            "model": None,
            "city": None,
            "price": None,
            "manufacture_year": None,
            "body_type": None,
            "fuel_type": None,
            "gear_box_type": None,
            "driving_gear_type": None,
            "engine_vol": None,
            "power": None,
            "color": None,
            "mileage": None,
            "characteristics": {},
            "pictures": [],
        }
        
        # Извлекаем заголовок (марка и модель)
        title_elem = card_element.find('div', class_=re.compile(r'item__title|js-item-title', re.I))
        if not title_elem:
            title_elem = card_element.find('h2') or card_element.find('h3')
        
        if title_elem:
            title_text = title_elem.get_text(strip=True)
            if title_text:
                title_parts = [p for p in title_text.split() if len(p) > 1]
                if len(title_parts) >= 2:
                    car_data["mark"] = title_parts[0]
                    car_data["model"] = " ".join(title_parts[1:min(4, len(title_parts))])
        
        # Извлекаем цену
        price_elem = card_element.find('div', class_=re.compile(r'item__price-main|price-main', re.I))
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            extracted_price = self._extract_price(price_text)
            if extracted_price:
                car_data["price"] = extracted_price
        
        # Извлекаем характеристики из item__tech
        tech_elem = card_element.find('div', class_=re.compile(r'item__tech|tech', re.I))
        if tech_elem:
            tech_items = tech_elem.find_all('div', recursive=False)
            for item in tech_items:
                text = ''
                for child in item.children:
                    if hasattr(child, 'string') and child.string:
                        text += child.string
                    elif hasattr(child, 'get_text'):
                        child_text = child.get_text(strip=True)
                        if child_text and child_text not in ['\\', '|', '/']:
                            text += ' ' + child_text
                
                if not text:
                    text = item.get_text(strip=True)
                
                text = re.sub(r'[\\|/]', '', text).strip()
                
                if not text or len(text) < 2:
                    continue
                
                # Год: "2009 г."
                if re.search(r'\d{4}\s*г\.?', text):
                    year = self._extract_number(text)
                    if year and 1900 <= year <= 2100:
                        car_data["manufacture_year"] = year
                # Пробег: "145 000 км"
                elif 'км' in text.lower():
                    mileage = self._extract_number(text)
                    if mileage:
                        car_data["mileage"] = mileage
                # Объем: "0.8 л"
                elif re.search(r'\d+\.?\d*\s*л\b', text, re.I):
                    vol_match = re.search(r'(\d+\.?\d*)', text)
                    if vol_match:
                        try:
                            vol = float(vol_match.group(1))
                            car_data["engine_vol"] = int(vol * 1000) if vol < 10 else int(vol)
                        except:
                            pass
                # Мощность: "52 л.с."
                elif 'л.с.' in text.lower() or 'лс' in text.lower():
                    power_text = re.sub(r'л\.?с\.?', '', text, flags=re.I).strip()
                    car_data["power"] = power_text
                # Топливо: "Бензин", "Дизель"
                elif any(word in text.lower() for word in ['бензин', 'дизель', 'электро', 'гибрид']):
                    car_data["fuel_type"] = text
                # КПП: "Механика", "Автомат"
                elif any(word in text.lower() for word in ['механик', 'автомат', 'вариатор', 'робот']):
                    car_data["gear_box_type"] = text
        
        # Извлекаем город
        address_elem = card_element.find('div', class_=re.compile(r'item-row__info-address|address', re.I))
        if address_elem:
            address_text = address_elem.get_text(strip=True)
            # Ищем название города в адресе
            city_parts = address_text.split()
            for part in city_parts:
                if len(part) > 3 and not part[0].isdigit():
                    if any(word in part.lower() for word in ['москв', 'ростов', 'спб', 'питер', 'казан', 'нижн', 'новосиб', 'екатерин']):
                        car_data["city"] = re.sub(r'[,;]\s*$', '', part).strip()
                        break
            if not car_data["city"] and address_text:
                car_data["city"] = re.sub(r'[,;]\s*$', '', address_text).strip()
        
        # Извлекаем фотографии
        img_elem = card_element.find('img', class_=re.compile(r'lozad|item-row__img', re.I))
        if img_elem:
            img_url = img_elem.get('data-src') or img_elem.get('src')
            if img_url:
                if not img_url.startswith('http'):
                    img_url = urljoin(url, img_url)
                car_data["pictures"].append(img_url)
        
        return car_data
    
    def _log_extracted_data(self, car_data: Dict[str, Any], index: int):
        """
        Выводит найденные данные для проверки
        """
        # Логируем в файл
        logger.info(f"📋 АВТОМОБИЛЬ #{index}: {car_data.get('mark')} {car_data.get('model')} - "
                   f"Цена: {car_data.get('price')}, Город: {car_data.get('city')}, Год: {car_data.get('manufacture_year')}")
        
        # Выводим в консоль
        print("\n" + "="*80)
        print(f"📋 АВТОМОБИЛЬ #{index}")
        print("="*80)
        print(f"🔗 URL: {car_data.get('source_url', 'N/A')}")
        # Тип автомобиля
        car_type = car_data.get('car_type', 'unknown')
        car_type_display = 'Новый' if car_type == 'new' else 'Подержанный' if car_type == 'used' else 'Неизвестно'
        print(f"🚗 Тип: {car_type_display}")
        print(f"🚗 Марка: {car_data.get('mark') or 'НЕ НАЙДЕНО'}")
        print(f"🚙 Модель: {car_data.get('model') or 'НЕ НАЙДЕНО'}")
        print(f"📍 Город: {car_data.get('city') or 'НЕ НАЙДЕНО'}")
        print(f"💰 Цена: {car_data.get('price') or 'НЕ НАЙДЕНО'}")
        print(f"📅 Год: {car_data.get('manufacture_year') or 'НЕ НАЙДЕНО'}")
        print(f"📏 Пробег: {car_data.get('mileage') or 'НЕ НАЙДЕНО'}")
        print(f"🚗 Тип кузова: {car_data.get('body_type') or 'НЕ НАЙДЕНО'}")
        print(f"⛽ Топливо: {car_data.get('fuel_type') or 'НЕ НАЙДЕНО'}")
        print(f"⚙️ КПП: {car_data.get('gear_box_type') or 'НЕ НАЙДЕНО'}")
        print(f"🔧 Привод: {car_data.get('driving_gear_type') or 'НЕ НАЙДЕНО'}")
        # Форматируем объем двигателя для вывода
        engine_vol = car_data.get('engine_vol')
        if engine_vol:
            if engine_vol >= 1000:
                vol_litres = engine_vol / 1000.0
                # Если целое число, выводим без десятичной части
                if vol_litres == int(vol_litres):
                    vol_display = f"{int(vol_litres)} л ({engine_vol} мл)"
                else:
                    vol_display = f"{vol_litres:.1f} л ({engine_vol} мл)"
            else:
                vol_display = f"{engine_vol} мл"
            print(f"🔋 Объем двигателя: {vol_display}")
        else:
            print(f"🔋 Объем двигателя: НЕ НАЙДЕНО")
        print(f"⚡ Мощность: {car_data.get('power') or 'НЕ НАЙДЕНО'}")
        print(f"🎨 Цвет: {car_data.get('color') or 'НЕ НАЙДЕНО'}")
        
        # Дополнительные характеристики
        if car_data.get('characteristics'):
            # Показываем комплектацию отдельно, если есть
            equipment = car_data['characteristics'].get('equipment', [])
            if equipment:
                equipment_count = car_data['characteristics'].get('equipment_count', len(equipment))
                print(f"🔧 Комплектация: {equipment_count} опций")
                # Показываем первые 5 опций
                for i, option in enumerate(equipment[:5], 1):
                    print(f"   {i}. {option[:70]}...")
                if equipment_count > 5:
                    print(f"   ... и еще {equipment_count - 5} опций")
            
            # Показываем другие характеристики (исключая equipment)
            other_chars = {k: v for k, v in car_data['characteristics'].items() 
                          if k not in ['equipment', 'equipment_count', 'car_type']}
            if other_chars:
                print(f"📝 Доп. характеристики: {len(other_chars)} шт.")
                for key, value in list(other_chars.items())[:5]:  # Показываем первые 5
                    if isinstance(value, list):
                        print(f"   - {key}: {len(value)} элементов")
                    else:
                        print(f"   - {key}: {value}")
        
        # Фотографии
        pictures = car_data.get('pictures', [])
        pictures_count = len(pictures)
        print(f"📸 Фотографий: {pictures_count}")
        if pictures_count > 0:
            first_pic = pictures[0]
            if isinstance(first_pic, dict):
                pic_url = first_pic.get('image_url', 'N/A')
            else:
                pic_url = str(first_pic)
            print(f"   Первая: {pic_url[:80]}...")
        
        # NLP извлечения
        if car_data.get('nlp_entities'):
            nlp_entities = car_data['nlp_entities']
            print(f"🤖 NLP извлечения:")
            if nlp_entities.get('dates'):
                print(f"   - Даты: {nlp_entities['dates']}")
            if nlp_entities.get('locations'):
                print(f"   - Локации: {nlp_entities['locations']}")
            if nlp_entities.get('products'):
                print(f"   - Продукты: {nlp_entities['products']}")
        
        # Ollama извлечения
        if car_data.get('ollama_extracted'):
            print(f"🧠 Ollama извлечения: Да")
        
        print("="*80 + "\n")
    
    def _parse_car_page(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Парсит страницу автомобиля с использованием ИИ
        ВАЖНО: Это метод для парсинга ОТДЕЛЬНОЙ страницы автомобиля, а не карточки каталога
        """
        try:
            logger.debug(f"🔍 Начинаю парсинг страницы автомобиля: {url}")
            
            session = self._create_session()
            response = session.get(url, timeout=10.0)
            
            # Обрабатываем 404 ошибки отдельно - это не критично
            if response.status_code == 404:
                logger.warning(f"Страница не найдена (404): {url}")
                self.stats["total_errors"] += 1
                return None
            
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Проверяем, что это действительно страница автомобиля, а не каталог
            # Страница автомобиля обычно содержит h1 с названием и специфичные элементы
            page_title = soup.find('title')
            page_title_text = page_title.get_text(strip=True) if page_title else ""
            
            # Проверяем, что это не страница каталога
            if 'каталог' in page_title_text.lower() or 'catalog' in page_title_text.lower():
                logger.warning(f"⚠️ Обнаружена страница каталога вместо страницы автомобиля: {url}")
                return None
            
            logger.debug(f"✅ Страница загружена. Title: {page_title_text[:100]}")
            
            # Обнаружение изменений структуры
            self._detect_structure_changes(url, soup)
            
            # Интеллектуальное извлечение данных со страницы автомобиля
            logger.info(f"🔍 Извлечение данных со страницы автомобиля: {url}")
            car_data = self._intelligent_extract_car_data(soup, url)
            
            # Логируем результат извлечения (всегда)
            logger.info(f"📊 Результат извлечения: марка={car_data.get('mark') or 'НЕ НАЙДЕНО'}, "
                       f"модель={car_data.get('model') or 'НЕ НАЙДЕНО'}, "
                       f"цена={car_data.get('price') or 'НЕ НАЙДЕНО'}, "
                       f"год={car_data.get('manufacture_year') or 'НЕ НАЙДЕНО'}, "
                       f"город={car_data.get('city') or 'НЕ НАЙДЕНО'}")
            
            # КРИТИЧЕСКИ ВАЖНО: НЕ использовать fallback на карточку каталога для страниц автомобилей
            # Если данные не найдены на странице автомобиля, это проблема, которую нужно исправить
            if not car_data.get("mark") or not car_data.get("model"):
                logger.warning(f"⚠️ Не удалось извлечь основные данные со страницы автомобиля {url}")
                logger.warning(f"   Марка: {car_data.get('mark')}, Модель: {car_data.get('model')}")
                logger.warning(f"   Это может означать, что структура страницы изменилась или селекторы неверны")
                
                # Попытка извлечь из URL (последний резерв)
                url_parts = url.rstrip('/').split('/')
                if len(url_parts) >= 5:
                    # Формат: /sale/used/mark/model/id
                    potential_mark = url_parts[-3]
                    potential_model = url_parts[-2]
                    if not car_data.get("mark"):
                        car_data["mark"] = potential_mark.replace('-', ' ').title()
                        logger.info(f"   ✅ Марка извлечена из URL: {car_data['mark']}")
                        print(f"   ✅ Марка извлечена из URL: {car_data['mark']}")
                    if not car_data.get("model"):
                        car_data["model"] = potential_model.replace('-', ' ').title()
                        logger.info(f"   ✅ Модель извлечена из URL: {car_data['model']}")
                        print(f"   ✅ Модель извлечена из URL: {car_data['model']}")
            
            # ВСЕГДА возвращаем car_data, даже если данные неполные
            # Это позволяет сохранить то, что удалось извлечь
            logger.info(f"✅ Данные извлечены (даже если неполные): марка={car_data.get('mark')}, модель={car_data.get('model')}")
            return car_data
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Страница не найдена (404): {url}")
            else:
                logger.error(f"HTTP ошибка парсинга страницы {url}: {e}")
            self.stats["total_errors"] += 1
            return None
        except httpx.TimeoutException:
            logger.warning(f"Таймаут при загрузке страницы: {url}")
            self.stats["total_errors"] += 1
            return None
        except Exception as e:
            logger.error(f"Ошибка парсинга страницы {url}: {e}")
            self.stats["total_errors"] += 1
            return None
    
    def _find_car_links(self, page_url: str) -> List[str]:
        """Находит все ссылки на автомобили на странице каталога"""
        try:
            session = self._create_session()
            response = session.get(page_url, timeout=10.0)
            
            # Обрабатываем 404 ошибки
            if response.status_code == 404:
                logger.warning(f"Страница каталога не найдена (404): {page_url}")
                return []
            
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            car_links = []
            
            # Специфичный поиск для aaa-motors.ru
            # Ищем ссылки с классом js-item или по структуре /sale/used/
            link_selectors = [
                # Основной селектор для aaa-motors.ru (класс js-item)
                soup.find_all('a', class_=re.compile(r'js-item|item-row', re.I)),
                # Альтернативные селекторы по href
                soup.find_all('a', href=re.compile(r'/sale/(used|new)/', re.I)),
                soup.find_all('a', href=re.compile(r'/car/|/auto/|/vehicle/|/offer/', re.I)),
                soup.find_all('a', class_=re.compile(r'car|auto|vehicle|offer|card', re.I)),
            ]
            
            for selector_list in link_selectors:
                for link in selector_list:
                    href = link.get('href')
                    if not href:
                        continue
                    
                    # Нормализуем URL
                    if href.startswith('//'):
                        href = 'https:' + href
                    elif href.startswith('/'):
                        href = urljoin(self.base_url, href)
                    elif not href.startswith('http'):
                        href = urljoin(self.base_url, href)
                    
                    # Проверяем, что это ссылка на автомобиль
                    # Формат aaa-motors.ru: /sale/used/daewoo/matiz/cd64d5
                    if any(pattern in href.lower() for pattern in [
                        '/sale/used/', '/sale/new/', '/car/', '/auto/', '/vehicle/', '/offer/'
                    ]):
                        # Убираем параметры запроса и якоря
                        if '?' in href:
                            href = href.split('?')[0]
                        if '#' in href:
                            href = href.split('#')[0]
                        
                        # Проверяем, что ссылка содержит марку и модель (минимум 2 сегмента после /sale/used/)
                        parts = href.rstrip('/').split('/')
                        if len(parts) >= 5:  # https://, domain, sale, used, mark, model, id
                            car_links.append(href)
            
            # Убираем дубликаты
            seen = set()
            unique_links = []
            for link in car_links:
                if link not in seen:
                    seen.add(link)
                    unique_links.append(link)
            
            logger.info(f"Найдено {len(unique_links)} ссылок на автомобили на странице {page_url}")
            return unique_links
            
        except Exception as e:
            logger.error(f"Ошибка поиска ссылок на странице {page_url}: {e}")
            return []
    
    def _find_catalog_pages(self) -> List[str]:
        """Находит все страницы каталога"""
        catalog_pages = []
        
        try:
            # Специфичные URL для aaa-motors.ru
            catalog_urls = [
                f"{self.base_url}/catalog",  # Основной каталог
                f"{self.base_url}/sale/used",  # Подержанные автомобили
                f"{self.base_url}/sale/new",  # Новые автомобили
                f"{self.base_url}/cars",
                f"{self.base_url}/auto",
                f"{self.base_url}/offers",
                f"{self.base_url}/",
            ]
            
            session = self._create_session()
            for catalog_url in catalog_urls:
                try:
                    response = session.get(catalog_url)
                    if response.status_code == 200:
                        catalog_pages.append(catalog_url)
                        logger.info(f"✅ Найден каталог: {catalog_url}")
                        
                        soup = BeautifulSoup(response.content, 'html.parser')
                        
                        # Ищем пагинацию
                        pagination = soup.find_all('a', href=re.compile(r'page|p=\d+|/catalog\?page', re.I))
                        for page_link in pagination:
                            href = page_link.get('href')
                            if href:
                                if href.startswith('//'):
                                    href = 'https:' + href
                                elif href.startswith('/'):
                                    href = urljoin(self.base_url, href)
                                elif not href.startswith('http'):
                                    href = urljoin(self.base_url, href)
                                if href not in catalog_pages:
                                    catalog_pages.append(href)
                        
                        # Если нашли основной каталог, останавливаемся
                        if '/catalog' in catalog_url:
                            break
                except Exception as e:
                    logger.debug(f"Не удалось загрузить {catalog_url}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Ошибка поиска страниц каталога: {e}")
        
        if not catalog_pages:
            # Fallback на основной каталог
            catalog_pages = [f"{self.base_url}/catalog"]
            logger.warning("Используется fallback URL каталога")
        
        return catalog_pages
    
    def _save_car(self, car_data: Dict[str, Any]) -> bool:
        """Сохраняет автомобиль в базу данных"""
        try:
            # Логируем что пытаемся сохранить
            logger.debug(f"💾 Сохранение автомобиля: {car_data.get('mark')} {car_data.get('model')} - "
                       f"URL: {car_data.get('source_url')}")
            
            existing = self.db.query(ParsedCar).filter(
                ParsedCar.source_url == car_data["source_url"]
            ).first()
            
            if existing:
                logger.debug(f"   🔄 Найдена существующая запись (ID: {existing.id}), обновление...")
                logger.info(f"   📊 Текущие данные в БД: mark={existing.mark}, model={existing.model}, price={existing.price}")
                logger.info(f"   📊 Новые данные: mark={car_data.get('mark')}, model={car_data.get('model')}, price={car_data.get('price')}")
                
                # Обновляем существующий
                # КРИТИЧЕСКИ ВАЖНО: Для новых данных ВСЕГДА обновляем, особенно если существующее значение пустое
                # Это позволяет перепарсить данные если они были неполными
                for key, value in car_data.items():
                    if key not in ["pictures", "characteristics", "sentiment", "nlp_entities", "ollama_extracted", "source_url", "car_type"] and hasattr(existing, key):
                        existing_value = getattr(existing, key, None)
                        should_update = False
                        
                        # Проверяем что новое значение валидное
                        if value is not None and value != '':
                            # Для числовых полей проверяем, что значение не 0 (если это не пробег или год)
                            if isinstance(value, (int, float)):
                                if key in ['mileage', 'manufacture_year'] or value > 0:
                                    should_update = True
                            else:
                                should_update = True
                        
                        # ВСЕГДА обновляем если новое значение валидное (приоритет новым данным)
                        if should_update:
                            # Для критичных полей (mark, model, price, year) ВСЕГДА обновляем, если существующее пустое
                            if key in ['mark', 'model', 'price', 'manufacture_year']:
                                # Если существующее значение пустое ИЛИ отличается от нового - обновляем
                                if (existing_value is None or existing_value == '' or existing_value == 0) or (existing_value != value):
                                    logger.info(f"      ✏️ Обновление критичного поля {key}: '{existing_value}' -> '{value}'")
                                    setattr(existing, key, value)
                            # Для остальных полей обновляем только если существующее пустое
                            elif existing_value is None or existing_value == '' or existing_value == 0:
                                logger.debug(f"      ✏️ Обновление поля {key}: '{existing_value}' -> '{value}'")
                                setattr(existing, key, value)
                
                # Сохраняем характеристики (включая тип автомобиля и комплектацию)
                if car_data.get("characteristics"):
                    # Добавляем тип автомобиля в characteristics, если он есть
                    if car_data.get("car_type"):
                        car_data["characteristics"]["car_type"] = car_data["car_type"]
                    existing.characteristics = json.dumps(car_data["characteristics"], ensure_ascii=False)
                elif car_data.get("car_type"):
                    # Если characteristics пустые, но есть тип автомобиля
                    existing.characteristics = json.dumps({"car_type": car_data["car_type"]}, ensure_ascii=False)
                
                self.db.query(ParsedCarPicture).filter(
                    ParsedCarPicture.parsed_car_id == existing.id
                ).delete()
                
                parsed_car = existing
                logger.debug(f"   ✅ Запись обновлена (ID: {parsed_car.id})")
            else:
                # Создаем новый
                logger.debug(f"   ➕ Создание новой записи...")
                parsed_car = ParsedCar(
                    source_url=car_data["source_url"],
                    mark=car_data.get("mark"),
                    model=car_data.get("model"),
                    city=car_data.get("city"),
                    price=car_data.get("price"),
                    manufacture_year=car_data.get("manufacture_year"),
                    body_type=car_data.get("body_type"),
                    fuel_type=car_data.get("fuel_type"),
                    gear_box_type=car_data.get("gear_box_type"),
                    driving_gear_type=car_data.get("driving_gear_type"),
                    engine_vol=car_data.get("engine_vol"),
                    power=car_data.get("power"),
                    color=car_data.get("color"),
                    mileage=car_data.get("mileage"),
                    characteristics=None,  # Будет установлено после добавления car_type
                    is_active=True
                )
                
                # Добавляем тип автомобиля в characteristics и сохраняем все характеристики
                char_dict = car_data.get("characteristics", {})
                if car_data.get("car_type"):
                    char_dict["car_type"] = car_data["car_type"]
                
                if char_dict:
                    parsed_car.characteristics = json.dumps(char_dict, ensure_ascii=False)
                
                # ВАЖНО: Проверяем что критичные поля установлены перед сохранением
                if not parsed_car.mark and car_data.get("mark"):
                    parsed_car.mark = car_data["mark"]
                    logger.warning(f"   🔄 Принудительная установка mark: {car_data['mark']}")
                if not parsed_car.model and car_data.get("model"):
                    parsed_car.model = car_data["model"]
                    logger.warning(f"   🔄 Принудительная установка model: {car_data['model']}")
                if not parsed_car.price and car_data.get("price"):
                    parsed_car.price = car_data["price"]
                    logger.warning(f"   🔄 Принудительная установка price: {car_data['price']}")
                if not parsed_car.manufacture_year and car_data.get("manufacture_year"):
                    parsed_car.manufacture_year = car_data["manufacture_year"]
                    logger.warning(f"   🔄 Принудительная установка year: {car_data['manufacture_year']}")
                if not parsed_car.body_type and car_data.get("body_type"):
                    parsed_car.body_type = car_data["body_type"]
                if not parsed_car.fuel_type and car_data.get("fuel_type"):
                    parsed_car.fuel_type = car_data["fuel_type"]
                if not parsed_car.gear_box_type and car_data.get("gear_box_type"):
                    parsed_car.gear_box_type = car_data["gear_box_type"]
                if not parsed_car.city and car_data.get("city"):
                    parsed_car.city = car_data["city"]
                
                self.db.add(parsed_car)
                self.db.flush()
                
                # Проверяем что данные действительно установлены
                logger.info(f"   ✅ После создания записи ID={parsed_car.id}: mark={parsed_car.mark}, model={parsed_car.model}, price={parsed_car.price}, year={parsed_car.manufacture_year}")
            
            # Сохраняем фотографии
            for pic_data in car_data.get("pictures", []):
                picture = ParsedCarPicture(
                    parsed_car_id=parsed_car.id,
                    image_url=pic_data["image_url"],
                    seqno=pic_data.get("seqno", 0)
                )
                self.db.add(picture)
            
            self.db.commit()
            self.stats["total_parsed"] += 1
            
            # Обновляем объект из БД для проверки
            self.db.refresh(parsed_car)
            
            logger.info(f"   ✅ Автомобиль сохранен в БД (ID: {parsed_car.id})")
            
            # Проверяем что данные действительно сохранились
            logger.debug(f"   📊 Проверка сохраненных данных: "
                       f"марка={parsed_car.mark}, модель={parsed_car.model}, "
                       f"цена={parsed_car.price}, год={parsed_car.manufacture_year}")
            
            # ВАЖНО: Проверяем что критичные поля заполнены и принудительно сохраняем если нужно
            critical_fields = ['mark', 'model', 'price', 'manufacture_year']
            missing_fields = []
            for field in critical_fields:
                current_value = getattr(parsed_car, field, None)
                data_value = car_data.get(field)
                # Если в БД пусто, а в car_data есть значение - принудительно устанавливаем
                if not current_value and data_value:
                    setattr(parsed_car, field, data_value)
                    missing_fields.append(field)
                    logger.warning(f"   🔄 Принудительная установка поля {field}: {data_value}")
                # Если значение есть в car_data, но отличается - обновляем
                elif current_value != data_value and data_value:
                    setattr(parsed_car, field, data_value)
                    missing_fields.append(field)
                    logger.warning(f"   🔄 Обновление поля {field}: '{current_value}' -> '{data_value}'")
            
            if missing_fields:
                self.db.commit()
                self.db.refresh(parsed_car)
                logger.info(f"   ✅ Принудительно сохранены/обновлены поля: {missing_fields}")
            
            return True
            
        except IntegrityError as e:
            self.db.rollback()
            logger.warning(f"Дубликат автомобиля {car_data.get('source_url')}: {e}")
            return False
        except Exception as e:
            self.db.rollback()
            logger.error(f"Ошибка сохранения автомобиля: {e}")
            self.stats["total_errors"] += 1
            return False
    
    def clear_all_data(self) -> int:
        """
        Удаляет ВСЕ данные из таблиц парсинга (включая неактивные)
        Возвращает количество удаленных записей
        """
        try:
            # Сначала считаем сколько данных будет удалено (ВСЕ, включая неактивные)
            cars_count = self.db.query(ParsedCar).count()
            pictures_count = self.db.query(ParsedCarPicture).count()
            
            logger.info(f"🗑️ Найдено данных для удаления: {cars_count} автомобилей, {pictures_count} фотографий")
            print(f"\n{'='*80}")
            print(f"🗑️ НАЧАЛО ОЧИСТКИ ДАННЫХ")
            print(f"{'='*80}")
            print(f"Найдено автомобилей: {cars_count}")
            print(f"Найдено фотографий: {pictures_count}")
            
            if cars_count == 0 and pictures_count == 0:
                logger.info("✅ Данных для удаления нет, база уже пуста")
                print(f"✅ Данных для удаления нет")
                print(f"{'='*80}\n")
                return 0
            
            # Удаляем все фотографии (должны удаляться первыми из-за внешних ключей)
            # Используем synchronize_session=False для правильной работы с внешними ключами
            deleted_pictures = self.db.query(ParsedCarPicture).delete(synchronize_session=False)
            logger.info(f"🗑️ Удалено фотографий: {deleted_pictures}")
            print(f"🗑️ Удалено фотографий: {deleted_pictures}")
            
            # Удаляем все автомобили (ВСЕ, включая неактивные)
            deleted_cars = self.db.query(ParsedCar).delete(synchronize_session=False)
            logger.info(f"🗑️ Удалено автомобилей: {deleted_cars}")
            print(f"🗑️ Удалено автомобилей: {deleted_cars}")
            
            # КРИТИЧЕСКИ ВАЖНО: Коммитим изменения для очистки
            self.db.commit()
            logger.info(f"✅ Коммит очистки выполнен")
            
            # Проверяем что данные действительно удалены
            remaining_cars = self.db.query(ParsedCar).count()
            remaining_pictures = self.db.query(ParsedCarPicture).count()
            
            if remaining_cars > 0 or remaining_pictures > 0:
                logger.warning(f"⚠️ После очистки осталось: {remaining_cars} автомобилей, {remaining_pictures} фотографий")
                print(f"⚠️ ВНИМАНИЕ: После очистки осталось: {remaining_cars} автомобилей, {remaining_pictures} фотографий")
                
                # Пробуем принудительно удалить еще раз
                try:
                    logger.info(f"🔄 Попытка принудительного удаления оставшихся записей...")
                    self.db.query(ParsedCarPicture).delete(synchronize_session=False)
                    self.db.query(ParsedCar).delete(synchronize_session=False)
                    self.db.commit()
                    
                    # Проверяем еще раз
                    remaining_cars = self.db.query(ParsedCar).count()
                    remaining_pictures = self.db.query(ParsedCarPicture).count()
                    if remaining_cars == 0 and remaining_pictures == 0:
                        logger.info(f"✅ Принудительное удаление успешно выполнено")
                        print(f"✅ Принудительное удаление успешно выполнено")
                    else:
                        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: После принудительного удаления осталось: {remaining_cars} автомобилей, {remaining_pictures} фотографий")
                        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: После принудительного удаления осталось: {remaining_cars} автомобилей, {remaining_pictures} фотографий")
                except Exception as e:
                    logger.error(f"❌ Ошибка принудительного удаления: {e}", exc_info=True)
            else:
                logger.info(f"✅ Все данные успешно удалены")
                print(f"✅ Все данные успешно удалены")
            
            logger.info(f"✅ Очистка завершена: {deleted_cars} автомобилей, {deleted_pictures} фотографий")
            print(f"{'='*80}")
            print(f"✅ ОЧИСТКА ДАННЫХ ЗАВЕРШЕНА")
            print(f"{'='*80}\n")
            return deleted_cars
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Ошибка при очистке данных: {e}", exc_info=True)
            print(f"\n❌ ОШИБКА ПРИ ОЧИСТКЕ ДАННЫХ: {e}\n")
            raise
    
    def parse(self, max_pages: Optional[int] = None, max_cars: Optional[int] = None, delay: float = 1.0, clear_before: bool = True) -> Dict[str, Any]:
        """
        Запускает интеллектуальный парсинг автомобилей
        
        Args:
            max_pages: Максимальное количество страниц каталога
            max_cars: Максимальное количество автомобилей
            delay: Задержка между запросами (секунды)
            clear_before: Очистить все данные перед парсингом (по умолчанию True)
        """
        self.is_running = True
        self.stats = {
            "total_parsed": 0,
            "total_errors": 0,
            "current_page": 0,
            "nlp_extractions": 0,
            "structure_changes_detected": 0,
            "ollama_extractions": 0  # Добавляем поле для Ollama
        }
        
        try:
            # КРИТИЧЕСКИ ВАЖНО: Очищаем все данные перед парсингом
            # По умолчанию clear_before=True, если явно не указано False
            should_clear = clear_before if clear_before is not None else True
            
            logger.info(f"🗑️ Параметр clear_before: {clear_before} (результат: should_clear={should_clear})")
            
            if should_clear:
                print("\n" + "="*80)
                print("🗑️ НАЧАЛО ОЧИСТКИ ДАННЫХ ПЕРЕД ПАРСИНГОМ")
                print("="*80)
                logger.info("🗑️ Очистка существующих данных перед парсингом...")
                logger.info(f"   Параметр clear_before={clear_before}, should_clear={should_clear} - очистка включена")
                
                # Принудительно очищаем данные
                deleted_count = self.clear_all_data()
                
                logger.info(f"✅ Удалено {deleted_count} автомобилей перед началом парсинга")
                print(f"✅ Подготовка завершена. Удалено {deleted_count} автомобилей. Начинаем парсинг...\n")
                
                # Дополнительная проверка что данные удалены
                remaining_after_clear = self.db.query(ParsedCar).count()
                if remaining_after_clear > 0:
                    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: После очистки осталось {remaining_after_clear} автомобилей!")
                    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: После очистки осталось {remaining_after_clear} автомобилей!")
                    # Пробуем принудительно удалить оставшиеся
                    try:
                        self.db.query(ParsedCar).delete(synchronize_session=False)
                        self.db.query(ParsedCarPicture).delete(synchronize_session=False)
                        self.db.commit()
                        logger.info(f"✅ Принудительно удалены оставшиеся записи")
                    except Exception as e:
                        logger.error(f"❌ Ошибка принудительного удаления: {e}")
                else:
                    logger.info(f"✅ Проверка: база данных пуста, готов к парсингу")
            else:
                logger.warning("⚠️ Очистка данных отключена (clear_before=False). Данные будут добавлены к существующим.")
                print(f"⚠️ ВНИМАНИЕ: Очистка данных отключена. Новые данные будут добавлены к существующим.\n")
            
            catalog_pages = self._find_catalog_pages()
            if not catalog_pages:
                logger.warning("Не найдено страниц каталога")
                return {
                    "status": "error",
                    "message": "Не найдено страниц каталога",
                    **self.stats
                }
            
            if max_pages:
                catalog_pages = catalog_pages[:max_pages]
            
            all_car_links = []
            
            for page_url in catalog_pages:
                if not self.is_running:
                    break
                    
                self.stats["current_page"] += 1
                logger.info(f"Парсинг страницы {self.stats['current_page']}: {page_url}")
                
                car_links = self._find_car_links(page_url)
                all_car_links.extend(car_links)
                
                if delay > 0:
                    time.sleep(delay)
            
            unique_car_links = list(set(all_car_links))
            logger.info(f"Найдено {len(unique_car_links)} уникальных автомобилей")
            
            if max_cars:
                unique_car_links = unique_car_links[:max_cars]
            
            for idx, car_url in enumerate(unique_car_links):
                if not self.is_running:
                    break
                
                if max_cars and self.stats["total_parsed"] >= max_cars:
                    break
                
                logger.info(f"Парсинг автомобиля {idx + 1}/{len(unique_car_links)}: {car_url}")
                
                car_data = self._parse_car_page(car_url)
                
                # ВСЕГДА выводим данные для проверки, даже если они неполные
                if car_data:
                    # Проверяем что хотя бы базовые данные извлечены
                    has_basic_data = any([
                        car_data.get('mark'),
                        car_data.get('model'),
                        car_data.get('price'),
                        car_data.get('manufacture_year')
                    ])
                    
                    if not has_basic_data:
                        logger.warning(f"⚠️ [{idx + 1}/{len(unique_car_links)}] Данные извлечены, но все поля пустые: {car_url}")
                        # Пытаемся извлечь хотя бы марку и модель из URL
                        url_parts = car_url.rstrip('/').split('/')
                        if len(url_parts) >= 5:
                            if not car_data.get('mark'):
                                car_data['mark'] = url_parts[-3].replace('-', ' ').title()
                            if not car_data.get('model'):
                                car_data['model'] = url_parts[-2].replace('-', ' ').title()
                            logger.info(f"   ✅ Извлечены марка и модель из URL: {car_data.get('mark')} {car_data.get('model')}")
                    
                    # Выводим найденные данные для проверки (ВСЕГДА)
                    logger.info(f"📋 [{idx + 1}/{len(unique_car_links)}] Данные извлечены со страницы: {car_url}")
                    self._log_extracted_data(car_data, idx + 1)
                    
                    # ВСЕГДА пытаемся сохранить, даже если данных немного
                    logger.info(f"📦 ПЕРЕДАЧА ДАННЫХ В _save_car:")
                    logger.info(f"   mark={car_data.get('mark')}, model={car_data.get('model')}, price={car_data.get('price')}")
                    logger.info(f"   year={car_data.get('manufacture_year')}, city={car_data.get('city')}")
                    logger.info(f"   body_type={car_data.get('body_type')}, fuel_type={car_data.get('fuel_type')}, gear_box={car_data.get('gear_box_type')}")
                    
                    saved = self._save_car(car_data)
                    if saved:
                        # Проверяем что данные действительно сохранились
                        saved_car = self.db.query(ParsedCar).filter(
                            ParsedCar.source_url == car_data['source_url']
                        ).first()
                        
                        if saved_car:
                            logger.info(f"   ✅ Данные сохранены: mark={saved_car.mark}, model={saved_car.model}, price={saved_car.price}")
                            
                            # КРИТИЧНО: Если данные не сохранились, принудительно обновляем
                            needs_update = False
                            if not saved_car.mark and car_data.get("mark"):
                                saved_car.mark = car_data["mark"]
                                needs_update = True
                                logger.warning(f"   🔄 ПРИНУДИТЕЛЬНОЕ обновление mark: {car_data['mark']}")
                            if not saved_car.model and car_data.get("model"):
                                saved_car.model = car_data["model"]
                                needs_update = True
                                logger.warning(f"   🔄 ПРИНУДИТЕЛЬНОЕ обновление model: {car_data['model']}")
                            if not saved_car.price and car_data.get("price"):
                                saved_car.price = car_data["price"]
                                needs_update = True
                                logger.warning(f"   🔄 ПРИНУДИТЕЛЬНОЕ обновление price: {car_data['price']}")
                            if not saved_car.manufacture_year and car_data.get("manufacture_year"):
                                saved_car.manufacture_year = car_data["manufacture_year"]
                                needs_update = True
                                logger.warning(f"   🔄 ПРИНУДИТЕЛЬНОЕ обновление year: {car_data['manufacture_year']}")
                            if not saved_car.body_type and car_data.get("body_type"):
                                saved_car.body_type = car_data["body_type"]
                                needs_update = True
                            if not saved_car.fuel_type and car_data.get("fuel_type"):
                                saved_car.fuel_type = car_data["fuel_type"]
                                needs_update = True
                            if not saved_car.gear_box_type and car_data.get("gear_box_type"):
                                saved_car.gear_box_type = car_data["gear_box_type"]
                                needs_update = True
                            
                            if needs_update:
                                self.db.commit()
                                self.db.refresh(saved_car)
                                logger.info(f"   ✅ Принудительное обновление выполнено: mark={saved_car.mark}, model={saved_car.model}, price={saved_car.price}")
                        else:
                            logger.warning(f"   ⚠️ Запись не найдена после сохранения")
                    else:
                        logger.warning(f"   ⚠️ Не удалось сохранить данные для {car_url}")
                else:
                    logger.warning(f"⚠️ [{idx + 1}/{len(unique_car_links)}] Не удалось извлечь данные: {car_url}")
                    print(f"⚠️ [{idx + 1}/{len(unique_car_links)}] Не удалось извлечь данные: {car_url}")
                    print(f"   Это может означать, что страница не загрузилась или структура изменилась\n")
                    self.stats["total_errors"] += 1
                
                if delay > 0 and idx < len(unique_car_links) - 1:
                    time.sleep(delay)
            
            message = f"Парсинг завершен. Обработано {self.stats['total_parsed']} автомобилей. "
            message += f"NLP извлечений: {self.stats['nlp_extractions']}. "
            if self.use_ollama:
                message += f"Ollama извлечений: {self.stats['ollama_extractions']}. "
            message += f"Изменений структуры: {self.stats['structure_changes_detected']}"
            
            return {
                "status": "completed",
                "message": message,
                **self.stats
            }
            
        except Exception as e:
            logger.error(f"Критическая ошибка парсинга: {e}")
            return {
                "status": "error",
                "message": f"Ошибка парсинга: {str(e)}",
                **self.stats
            }
        finally:
            self.is_running = False
            if self.session:
                self.session.close()
                self.session = None
    
    def stop(self):
        """Останавливает парсинг"""
        self.is_running = False
    
    def get_status(self) -> Dict[str, Any]:
        """Возвращает статус парсинга"""
        return {
            "status": "running" if self.is_running else "stopped",
            **self.stats
        }

