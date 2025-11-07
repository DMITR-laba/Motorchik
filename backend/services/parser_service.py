"""
Сервис для парсинга автомобилей с сайта aaa-motors.ru
"""
import re
import json
import time
import httpx
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.database import ParsedCar, ParsedCarPicture
import logging

logger = logging.getLogger(__name__)


class AAAMotorsParser:
    """Парсер для сайта aaa-motors.ru"""
    
    def __init__(self, db_session: Session, base_url: str = "https://aaa-motors.ru"):
        self.db = db_session
        self.base_url = base_url
        self.session = None
        self.stats = {
            "total_parsed": 0,
            "total_errors": 0,
            "current_page": 0
        }
        self.is_running = False
        
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
    
    def _extract_number(self, text: str) -> Optional[int]:
        """Извлекает число из текста"""
        if not text:
            return None
        # Убираем все символы кроме цифр
        numbers = re.findall(r'\d+', str(text).replace(' ', ''))
        if numbers:
            return int(numbers[0])
        return None
    
    def _extract_price(self, text: str) -> Optional[str]:
        """Извлекает цену из текста"""
        if not text:
            return None
        # Убираем пробелы, оставляем цифры и разделители
        price_clean = re.sub(r'[^\d\s,.]', '', str(text))
        return price_clean.strip() if price_clean.strip() else None
    
    def _parse_car_page(self, url: str) -> Optional[Dict[str, Any]]:
        """Парсит страницу автомобиля"""
        try:
            session = self._create_session()
            response = session.get(url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
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
                "pictures": []
            }
            
            # Парсинг заголовка (марка и модель)
            title_elem = soup.find('h1') or soup.find('title')
            if title_elem:
                title_text = title_elem.get_text(strip=True)
                # Пытаемся извлечь марку и модель из заголовка
                # Формат может быть: "BMW X5 2024" или "BMW X5 в Москве"
                title_parts = title_text.split()
                if len(title_parts) >= 2:
                    car_data["mark"] = title_parts[0]
                    car_data["model"] = " ".join(title_parts[1:3]) if len(title_parts) >= 3 else title_parts[1]
            
            # Парсинг цены
            price_selectors = [
                soup.find(class_=re.compile(r'price', re.I)),
                soup.find(id=re.compile(r'price', re.I)),
                soup.find(string=re.compile(r'цена', re.I)),
                soup.find('span', string=re.compile(r'\d+.*₽', re.I)),
            ]
            for price_elem in price_selectors:
                if price_elem:
                    price_text = price_elem.get_text() if hasattr(price_elem, 'get_text') else str(price_elem)
                    car_data["price"] = self._extract_price(price_text)
                    if car_data["price"]:
                        break
            
            # Парсинг характеристик из таблицы или списка
            # Ищем таблицы с характеристиками
            specs_tables = soup.find_all(['table', 'dl', 'div'], class_=re.compile(r'spec|characteristic|param', re.I))
            for table in specs_tables:
                rows = table.find_all(['tr', 'dt']) if table.name != 'div' else table.find_all('div')
                for row in rows:
                    cells = row.find_all(['td', 'dd', 'span'])
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True).lower()
                        value = cells[1].get_text(strip=True)
                        
                        # Маппинг ключей на поля БД
                        if 'марка' in key or 'brand' in key:
                            car_data["mark"] = value
                        elif 'модель' in key or 'model' in key:
                            car_data["model"] = value
                        elif 'город' in key or 'city' in key or 'локация' in key:
                            car_data["city"] = value
                        elif 'год' in key or 'year' in key:
                            car_data["manufacture_year"] = self._extract_number(value)
                        elif 'кузов' in key or 'body' in key:
                            car_data["body_type"] = value
                        elif 'топливо' in key or 'fuel' in key:
                            car_data["fuel_type"] = value
                        elif 'коробка' in key or 'transmission' in key or 'gearbox' in key:
                            car_data["gear_box_type"] = value
                        elif 'привод' in key or 'drive' in key:
                            car_data["driving_gear_type"] = value
                        elif 'объем' in key or 'engine' in key or 'двигатель' in key:
                            vol = self._extract_number(value)
                            if vol:
                                car_data["engine_vol"] = vol
                        elif 'мощность' in key or 'power' in key:
                            car_data["power"] = value
                        elif 'цвет' in key or 'color' in key:
                            car_data["color"] = value
                        elif 'пробег' in key or 'mileage' in key:
                            car_data["mileage"] = self._extract_number(value)
                        else:
                            # Сохраняем в characteristics
                            car_data["characteristics"][key] = value
            
            # Парсинг фотографий
            img_selectors = [
                soup.find_all('img', class_=re.compile(r'car|photo|image|gallery', re.I)),
                soup.find_all('img', src=re.compile(r'car|auto|photo', re.I)),
            ]
            
            all_images = set()
            for selector_list in img_selectors:
                for img in selector_list:
                    src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                    if src:
                        # Преобразуем относительные URL в абсолютные
                        if src.startswith('//'):
                            src = 'https:' + src
                        elif src.startswith('/'):
                            src = urljoin(self.base_url, src)
                        elif not src.startswith('http'):
                            src = urljoin(self.base_url, src)
                        all_images.add(src)
            
            # Сортируем и добавляем фото
            sorted_images = sorted(list(all_images))
            for idx, img_url in enumerate(sorted_images[:20]):  # Ограничиваем до 20 фото
                car_data["pictures"].append({
                    "image_url": img_url,
                    "seqno": idx
                })
            
            return car_data
            
        except Exception as e:
            logger.error(f"Ошибка парсинга страницы {url}: {e}")
            self.stats["total_errors"] += 1
            return None
    
    def _find_car_links(self, page_url: str) -> List[str]:
        """Находит все ссылки на автомобили на странице каталога"""
        try:
            session = self._create_session()
            response = session.get(page_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            car_links = []
            
            # Ищем ссылки на автомобили (специфично для aaa-motors.ru)
            # Формат: /sale/used/mark/model/id или /sale/new/mark/model/id
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
            
            # Убираем дубликаты, сохраняя порядок
            seen = set()
            unique_links = []
            for link in car_links:
                if link not in seen:
                    seen.add(link)
                    unique_links.append(link)
            
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
                        
                        # Парсим пагинацию
                        soup = BeautifulSoup(response.content, 'html.parser')
                        
                        # Ищем ссылки на страницы
                        pagination = soup.find_all('a', href=re.compile(r'page|p=\d+', re.I))
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
                        break
                except Exception as e:
                    logger.debug(f"Не удалось загрузить {catalog_url}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Ошибка поиска страниц каталога: {e}")
        
        return catalog_pages
    
    def _save_car(self, car_data: Dict[str, Any]) -> bool:
        """Сохраняет автомобиль в базу данных"""
        try:
            # Проверяем, существует ли уже автомобиль с таким URL
            existing = self.db.query(ParsedCar).filter(
                ParsedCar.source_url == car_data["source_url"]
            ).first()
            
            if existing:
                # Обновляем существующий
                for key, value in car_data.items():
                    if key != "pictures" and key != "characteristics" and hasattr(existing, key):
                        setattr(existing, key, value)
                
                # Обновляем характеристики
                if car_data.get("characteristics"):
                    existing.characteristics = json.dumps(car_data["characteristics"], ensure_ascii=False)
                
                # Обновляем фотографии (удаляем старые, добавляем новые)
                self.db.query(ParsedCarPicture).filter(
                    ParsedCarPicture.parsed_car_id == existing.id
                ).delete()
                
                parsed_car = existing
            else:
                # Создаем новый
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
                    characteristics=json.dumps(car_data.get("characteristics", {}), ensure_ascii=False) if car_data.get("characteristics") else None,
                    is_active=True
                )
                self.db.add(parsed_car)
                self.db.flush()  # Получаем ID
            
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
            # Сначала считаем сколько данных будет удалено
            cars_count = self.db.query(ParsedCar).count()
            pictures_count = self.db.query(ParsedCarPicture).count()
            
            logger.info(f"🗑️ Найдено данных для удаления: {cars_count} автомобилей, {pictures_count} фотографий")
            
            if cars_count == 0 and pictures_count == 0:
                logger.info("✅ Данных для удаления нет, база уже пуста")
                return 0
            
            # Удаляем все фотографии (должны удаляться первыми из-за внешних ключей)
            deleted_pictures = self.db.query(ParsedCarPicture).delete(synchronize_session=False)
            logger.info(f"🗑️ Удалено фотографий: {deleted_pictures}")
            
            # Удаляем все автомобили (ВСЕ, включая неактивные)
            deleted_cars = self.db.query(ParsedCar).delete(synchronize_session=False)
            logger.info(f"🗑️ Удалено автомобилей: {deleted_cars}")
            
            # КРИТИЧЕСКИ ВАЖНО: Коммитим изменения для очистки
            self.db.commit()
            logger.info(f"✅ Коммит очистки выполнен")
            
            # Проверяем что данные действительно удалены
            remaining_cars = self.db.query(ParsedCar).count()
            remaining_pictures = self.db.query(ParsedCarPicture).count()
            
            if remaining_cars > 0 or remaining_pictures > 0:
                logger.warning(f"⚠️ После очистки осталось: {remaining_cars} автомобилей, {remaining_pictures} фотографий")
                
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
                    else:
                        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: После принудительного удаления осталось: {remaining_cars} автомобилей, {remaining_pictures} фотографий")
                except Exception as e:
                    logger.error(f"❌ Ошибка принудительного удаления: {e}", exc_info=True)
            
            logger.info(f"✅ Очищено данных: {deleted_cars} автомобилей, {deleted_pictures} фотографий")
            return deleted_cars
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Ошибка при очистке данных: {e}", exc_info=True)
            raise
    
    def parse(self, max_pages: Optional[int] = None, max_cars: Optional[int] = None, delay: float = 1.0, clear_before: bool = True) -> Dict[str, Any]:
        """
        Запускает парсинг автомобилей
        
        Args:
            max_pages: Максимальное количество страниц каталога для парсинга
            max_cars: Максимальное количество автомобилей для парсинга
            delay: Задержка между запросами (секунды)
            clear_before: Очистить все данные перед парсингом (по умолчанию True)
        """
        self.is_running = True
        self.stats = {
            "total_parsed": 0,
            "total_errors": 0,
            "current_page": 0
        }
        
        try:
            # Очищаем все данные перед парсингом
            if clear_before:
                logger.info("🗑️ Очистка существующих данных перед парсингом...")
                deleted_count = self.clear_all_data()
                logger.info(f"✅ Удалено {deleted_count} автомобилей перед началом парсинга")
            
            # Находим страницы каталога
            catalog_pages = self._find_catalog_pages()
            if not catalog_pages:
                logger.warning("Не найдено страниц каталога")
                return {
                    "status": "error",
                    "message": "Не найдено страниц каталога",
                    **self.stats
                }
            
            # Ограничиваем количество страниц
            if max_pages:
                catalog_pages = catalog_pages[:max_pages]
            
            all_car_links = []
            
            # Собираем все ссылки на автомобили
            for page_url in catalog_pages:
                if not self.is_running:
                    break
                    
                self.stats["current_page"] += 1
                logger.info(f"Парсинг страницы {self.stats['current_page']}: {page_url}")
                
                car_links = self._find_car_links(page_url)
                all_car_links.extend(car_links)
                
                # Задержка между запросами
                if delay > 0:
                    time.sleep(delay)
            
            # Убираем дубликаты
            unique_car_links = list(set(all_car_links))
            logger.info(f"Найдено {len(unique_car_links)} уникальных автомобилей")
            
            # Ограничиваем количество автомобилей
            if max_cars:
                unique_car_links = unique_car_links[:max_cars]
            
            # Парсим каждый автомобиль
            for idx, car_url in enumerate(unique_car_links):
                if not self.is_running:
                    break
                
                if max_cars and self.stats["total_parsed"] >= max_cars:
                    break
                
                logger.info(f"Парсинг автомобиля {idx + 1}/{len(unique_car_links)}: {car_url}")
                
                car_data = self._parse_car_page(car_url)
                if car_data:
                    self._save_car(car_data)
                
                # Задержка между запросами
                if delay > 0 and idx < len(unique_car_links) - 1:
                    time.sleep(delay)
            
            return {
                "status": "completed",
                "message": f"Парсинг завершен. Обработано {self.stats['total_parsed']} автомобилей",
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

