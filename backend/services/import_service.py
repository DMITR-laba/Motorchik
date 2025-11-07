"""
Сервис для импорта автомобилей из JSON/XML файлов
"""
import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.orm import Session
from models.database import (
    ImportCar, ImportUsedCar, ImportCarPicture, ImportUsedCarPicture,
    ImportCarOption, ImportCarOptionsGroup, Car, UsedCar, CarPicture,
    UsedCarPicture, CarOption, CarOptionsGroup
)
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def similarity(a: str, b: str) -> float:
    """Вычисляет похожесть двух строк"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class ImportService:
    """Сервис для импорта автомобилей"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def parse_json_file(self, file_content: bytes) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Парсит JSON файл и возвращает список записей
        Возвращает: (root_key, records)
        """
        try:
            data = json.loads(file_content.decode('utf-8'))
            
            # Если это список
            if isinstance(data, list):
                return ("", data)
            
            # Если это словарь, ищем первый список
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list):
                        return (key, value)
                    elif isinstance(value, dict):
                        # Рекурсивно ищем список
                        for sub_key, sub_value in value.items():
                            if isinstance(sub_value, list):
                                return (f"{key}.{sub_key}", sub_value)
            
            # Если не нашли список, возвращаем весь словарь как одну запись
            return ("", [data])
            
        except Exception as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            raise
    
    def parse_xml_file(self, file_content: bytes) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Парсит XML файл и возвращает список записей
        Возвращает: (root_key, records)
        """
        try:
            # Пробуем использовать ElementTree.parse() с временным файлом для более надежного парсинга
            import tempfile
            import os
            
            # Создаем временный файл для парсинга
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.xml') as tmp_file:
                tmp_file.write(file_content)
                tmp_file_path = tmp_file.name
            
            try:
                # Пробуем парсить через parse() - это более надежно для больших файлов
                tree = ET.parse(tmp_file_path)
                root = tree.getroot()
                logger.info("XML успешно распарсен через ElementTree.parse()")
            except ET.ParseError as parse_err:
                # Если parse() не сработал, пробуем fromstring() с очищенным содержимым
                logger.warning(f"ElementTree.parse() не сработал: {parse_err}")
                try:
                    # Очищаем содержимое и пробуем fromstring()
                    content_str = None
                    encoding = 'utf-8'
                    
                    # Декодируем файл
                    try:
                        first_bytes = file_content[:500]
                        if b'encoding=' in first_bytes:
                            import re
                            first_str = first_bytes.decode('utf-8', errors='ignore')
                            match = re.search(r'encoding=["\']([^"\']+)["\']', first_str, re.IGNORECASE)
                            if match:
                                encoding = match.group(1).lower()
                                if encoding == 'windows-1251':
                                    encoding = 'cp1251'
                    except Exception:
                        pass  # Используем кодировку по умолчанию
                    
                    try:
                        if encoding == 'cp1251':
                            content_str = file_content.decode('cp1251')
                        elif encoding == 'windows-1251':
                            content_str = file_content.decode('windows-1251')
                        else:
                            content_str = file_content.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            content_str = file_content.decode('windows-1251')
                        except UnicodeDecodeError:
                            content_str = file_content.decode('cp1251')
                    
                    # Очищаем и исправляем
                    import re
                    content_str = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', content_str)
                    content_str = re.sub(r'&(?![a-zA-Z]+[0-9]*;|#x?[0-9a-fA-F]+;)', '&amp;', content_str)
                    
                    def fix_attr_chars(match):
                        attr_value = match.group(1)
                        attr_value = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', attr_value)
                        return f'="{attr_value}"'
                    content_str = re.sub(r'="([^"]*)"', fix_attr_chars, content_str)
                    
                    root = ET.fromstring(content_str.encode('utf-8'))
                    logger.info("XML успешно распарсен через ElementTree.fromstring() после очистки")
                except Exception as e2:
                    logger.error(f"Не удалось распарсить XML даже после очистки: {e2}")
                    raise
            finally:
                # Удаляем временный файл
                try:
                    os.unlink(tmp_file_path)
                except:
                    pass
            
            # Продолжаем с парсингом структуры
            records = []
            root_key = root.tag
            
            # Специальная обработка для формата Ads (подержанные автомобили)
            if root.tag == 'Ads':
                # Ищем все элементы Ad
                for ad in root.findall('.//Ad'):
                    records.append(self._xml_element_to_dict(ad))
                root_key = 'Ad'
            # Специальная обработка для формата DealerCenter (новые автомобили)
            elif root.tag == 'DealerCenter':
                # Ищем все элементы CarOrder рекурсивно (используем findall для поиска всех вложенных)
                # findall('.//CarOrder') найдет все CarOrder элементы на любом уровне вложенности
                car_orders = root.findall('.//CarOrder')
                if car_orders:
                    logger.info(f"Найдено {len(car_orders)} элементов CarOrder в DealerCenter")
                    for car_order in car_orders:
                        records.append(self._xml_element_to_dict(car_order))
                    root_key = 'CarOrder'
                else:
                    # Если не нашли CarOrder через findall, пробуем прямые дочерние элементы
                    logger.warning("CarOrder элементы не найдены через findall, пробуем прямые дочерние")
                    for child in root:
                        if child.tag == 'CarOrder':
                            records.append(self._xml_element_to_dict(child))
                        elif child.tag in ['Car', 'Vehicle', 'Auto']:
                            records.append(self._xml_element_to_dict(child))
                        elif child.tag not in ['picture_path', 'pictures_real']:  # Пропускаем служебные элементы
                            # Берем все остальные дочерние элементы
                            records.append(self._xml_element_to_dict(child))
                    
                    if not records:
                        logger.warning("Не найдено CarOrder элементов, создаем запись из корня")
                        # Если совсем ничего не нашли, создаем запись из корня
                        records.append(self._xml_element_to_dict(root))
                    
                    root_key = root.tag
            else:
                # Общая обработка для других форматов
                children = list(root)
                if children:
                    # Если все дочерние элементы имеют одинаковый тег
                    if len(set(child.tag for child in children)) == 1:
                        root_key = children[0].tag
                        for child in children:
                            records.append(self._xml_element_to_dict(child))
                    else:
                        # Разные теги - создаем одну запись из всех
                        records.append(self._xml_element_to_dict(root))
                else:
                    # Нет дочерних элементов - создаем запись из корня
                    records.append(self._xml_element_to_dict(root))
            
            return (root_key, records)
            
        except Exception as e:
            logger.error(f"Ошибка парсинга XML: {e}")
            raise
    
    def _xml_element_to_dict(self, element: ET.Element) -> Dict[str, Any]:
        """Конвертирует XML элемент в словарь"""
        result = {}
        
        # Добавляем атрибуты
        for key, value in element.attrib.items():
            result[key] = value
        
        # Добавляем дочерние элементы
        for child in element:
            if len(child) == 0:  # Нет дочерних элементов
                # Обработка специальных элементов
                if child.tag == 'Image' and 'url' in child.attrib:
                    # Для изображений
                    if 'Images' not in result:
                        result['Images'] = []
                    result['Images'].append({'url': child.attrib['url']})
                elif child.tag == 'Images':
                    # Контейнер для изображений
                    if 'Images' not in result:
                        result['Images'] = []
                    # Ищем все Image элементы внутри Images
                    for img in child.findall('Image'):
                        if 'url' in img.attrib:
                            result['Images'].append({'url': img.attrib['url']})
                    # Также проверяем, есть ли Image как дочерний элемент напрямую
                    for img_child in child:
                        if img_child.tag == 'Image' and 'url' in img_child.attrib:
                            result['Images'].append({'url': img_child.attrib['url']})
                else:
                    # Обычные элементы - берем текст содержимого
                    text_value = child.text.strip() if child.text and child.text.strip() else ""
                    # Если текст пустой, но есть атрибуты, берем атрибут 'value' или первый атрибут
                    if not text_value and child.attrib:
                        # Пробуем взять значение из атрибута value, если есть
                        text_value = child.attrib.get('value') or child.attrib.get('Value') or ""
                        # Если все еще пусто, берем первый атрибут (кроме Title, Code)
                        if not text_value:
                            for key, val in child.attrib.items():
                                if key.lower() not in ['title', 'code', 'name']:
                                    text_value = val
                                    break
                    
                    # Если несколько элементов с одним тегом - создаем список
                    if child.tag in result:
                        if not isinstance(result[child.tag], list):
                            result[child.tag] = [result[child.tag]]
                        result[child.tag].append(text_value)
                    else:
                        result[child.tag] = text_value
            else:
                # Есть дочерние элементы - рекурсивно обрабатываем
                child_dict = self._xml_element_to_dict(child)
                if child.tag in result:
                    if not isinstance(result[child.tag], list):
                        result[child.tag] = [result[child.tag]]
                    result[child.tag].append(child_dict)
                else:
                    result[child.tag] = child_dict
        
        # Добавляем текст элемента, если он есть и нет дочерних элементов
        if element.text and element.text.strip():
            text_value = element.text.strip()
            if not result:
                return text_value
            result["_text"] = text_value
        
        return result
    
    def analyze_file(self, file_content: bytes, file_type: str) -> Dict[str, Any]:
        """
        Анализирует файл и возвращает информацию о структуре
        """
        if file_type.lower() == "json":
            root_key, records = self.parse_json_file(file_content)
        elif file_type.lower() == "xml":
            root_key, records = self.parse_xml_file(file_content)
        else:
            raise ValueError(f"Неподдерживаемый тип файла: {file_type}")
        
        if not records:
            raise ValueError("Файл не содержит записей")
        
        # Получаем все уникальные поля из всех записей
        all_fields = set()
        for record in records:
            self._extract_fields(record, all_fields, "")
        
        # Получаем примеры записей (первые 5)
        sample_records = records[:5]
        
        # Автоматическое сопоставление полей
        auto_mapping = self._auto_map_fields(list(all_fields))
        
        # Предложения для каждого поля
        suggestions = {}
        for field in all_fields:
            suggestions[field] = self._suggest_mappings(field)
        
        return {
            "file_type": file_type,
            "total_records": len(records),
            "sample_records": sample_records,
            "available_fields": sorted(list(all_fields)),
            "auto_mapping": auto_mapping,
            "suggestions": suggestions
        }
    
    def _extract_fields(self, obj: Any, fields: set, prefix: str = ""):
        """Рекурсивно извлекает все поля из объекта"""
        if isinstance(obj, dict):
            for key, value in obj.items():
                field_name = f"{prefix}.{key}" if prefix else key
                fields.add(field_name)
                if isinstance(value, (dict, list)):
                    self._extract_fields(value, fields, field_name)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    self._extract_fields(item, fields, prefix)
    
    def _auto_map_fields(self, source_fields: List[str]) -> Dict[str, Optional[str]]:
        """Автоматически сопоставляет поля из файла с полями таблицы"""
        # Поля, которые НЕ нужно импортировать в car_data (но могут использоваться для других целей)
        excluded_fields = {
            'picture_path', 'picture_path.path',
            'pictures_real', 'pictures_real.pic',
            'Images', 'Images.Image', 'Images.Images', 'Images.Images.url', 'Images.Image.url',
            'Kilometrage'  # Это поле маппится на mileage, но само не импортируется
        }
        
        # Специальные сопоставления для XML форматов
        xml_field_mapping = {
            # Для новых автомобилей (CarOrder)
            "Mark": "mark",
            "Model": "model",
            "Price": "price",
            "City": "city",
            "ManufactureYear": "manufacture_year",
            "FuelType": "fuel_type",
            "Power": "power",
            "BodyType": "body_type",
            "GearBoxType": "gear_box_type",
            "DrivingGearType": "driving_gear_type",
            "EngineVol": "engine_vol",
            "Color": "color",
            "VIN": "vin",
            "CodeCompl": "code_compl",
            "StockQty": "stock_qty",
            "DocNum": "doc_num",
            "Title": "title",
            "InteriorColor": "interior_color",
            "Engine": "engine",
            "DoorQty": "door_qty",
            "PTSColour": "pts_colour",
            "ModelYear": "model_year",
            "FuelConsumption": "fuel_consumption",
            "MaxTorque": "max_torque",
            "Acceleration": "acceleration",
            "MaxSpeed": "max_speed",
            "EcoClass": "eco_class",
            "Dimensions": "dimensions",
            "Weight": "weight",
            "CargoVolume": "cargo_volume",
            "ComplLevel": "compl_level",
            "interior-code": "interior_code",
            "color-code": "color_code",
            "CarOrderIntStatus": "car_order_int_status",
            "SalePrice": "sale_price",
            "MaxAdditionalDiscount": "max_additional_discount",
            "MaxDiscountTradeIn": "max_discount_trade_in",
            "MaxDiscountCredit": "max_discount_credit",
            "MaxDiscountCasko": "max_discount_casko",
            "MaxDiscountExtraGear": "max_discount_extra_gear",
            "MaxDiscountLifeInsurance": "max_discount_life_insurance",
            # Для подержанных автомобилей (Ads/Ad)
            "Make": "mark",
            "Year": "manufacture_year",
            "Kilometrage": "mileage",
            "Transmission": "gear_box_type",
            "DriveType": "driving_gear_type",
            "EngineSize": "engine_vol",
            "DateBegin": "date_begin",
            "DateEnd": "date_end",
            "AdStatus": "ad_status",
            "AllowEmail": "allow_email",
            "CompanyName": "company_name",
            "ManagerName": "manager_name",
            "ContactPhone": "contact_phone",
            "Category": "category",
            "Region": "region",
            "CarType": "car_type",
            "CertificationNumber": "certification_number",
            "AllowAvtokodReportLink": "allow_avtokod_report_link",
            "Doors": "doors",
            "WheelType": "wheel_type",
            "Owners": "owners",
            "Street": "street",
            "Sticker": "sticker",
            "GenerationId": "generation_id",
            "ModificationId": "modification_id",
            "AAA_MaxAdditionalDiscount": "aaa_max_additional_discount",
            "AAA_MaxDiscountTradeIn": "aaa_max_discount_trade_in",
            "AAA_MaxDiscountCredit": "aaa_max_discount_credit",
            "AAA_MaxDiscountCasko": "aaa_max_discount_casko",
            "AAA_MaxDiscountExtraGear": "aaa_max_discount_extra_gear",
            "AAA_MaxDiscountLifeInsurance": "aaa_max_discount_life_insurance",
            "DealerCenter": "dealer_center",
        }
        
        # Поля для новых автомобилей
        car_fields = [
            "title", "doc_num", "stock_qty", "mark", "model", "code_compl", "vin",
            "color", "price", "city", "manufacture_year", "fuel_type", "power",
            "body_type", "gear_box_type", "driving_gear_type", "engine_vol",
            "dealer_center", "interior_color", "engine", "door_qty", "pts_colour",
            "model_year", "fuel_consumption", "max_torque", "acceleration",
            "max_speed", "eco_class", "dimensions", "weight", "cargo_volume",
            "compl_level", "interior_code", "color_code", "car_order_int_status",
            "sale_price", "max_additional_discount", "max_discount_trade_in",
            "max_discount_credit", "max_discount_casko", "max_discount_extra_gear",
            "max_discount_life_insurance"
        ]
        
        # Поля для подержанных автомобилей
        used_car_fields = [
            "title", "doc_num", "mark", "model", "vin", "color", "price", "city",
            "manufacture_year", "mileage", "body_type", "gear_box_type",
            "driving_gear_type", "engine_vol", "power", "fuel_type", "dealer_center",
            "date_begin", "date_end", "ad_status", "allow_email", "company_name",
            "manager_name", "contact_phone", "category", "region", "car_type",
            "accident", "certification_number", "allow_avtokod_report_link",
            "doors", "wheel_type", "owners", "street", "sticker", "generation_id",
            "modification_id", "aaa_max_additional_discount", "aaa_max_discount_trade_in",
            "aaa_max_discount_credit", "aaa_max_discount_casko",
            "aaa_max_discount_extra_gear", "aaa_max_discount_life_insurance"
        ]
        
        # Объединяем все поля
        all_target_fields = set(car_fields + used_car_fields)
        
        mapping = {}
        for source_field in source_fields:
            # Пропускаем исключенные поля (они не должны маппиться на car_data)
            if source_field in excluded_fields:
                mapping[source_field] = None
                continue
            
            # Сначала проверяем точное соответствие в XML маппинге
            field_name = source_field.split(".")[-1]  # Берем последнюю часть пути
            
            # Проверяем точное совпадение (с учетом регистра)
            if field_name in xml_field_mapping:
                mapping[source_field] = xml_field_mapping[field_name]
                continue
            
            # Проверяем нечувствительное к регистру совпадение
            field_name_lower = field_name.lower()
            exact_match = None
            for xml_key, db_field in xml_field_mapping.items():
                if xml_key.lower() == field_name_lower:
                    exact_match = db_field
                    break
            
            if exact_match:
                mapping[source_field] = exact_match
                continue
            
            # Если точного совпадения нет, используем алгоритм похожести
            normalized_source = field_name.lower().replace("_", "").replace("-", "")
            
            best_match = None
            best_score = 0.5  # Минимальный порог похожести
            
            for target_field in all_target_fields:
                normalized_target = target_field.lower().replace("_", "")
                score = similarity(normalized_source, normalized_target)
                
                if score > best_score:
                    best_score = score
                    best_match = target_field
            
            mapping[source_field] = best_match if best_match else None
        
        return mapping
    
    def _suggest_mappings(self, source_field: str) -> List[str]:
        """Предлагает возможные сопоставления для поля"""
        # Похожая логика, но возвращает топ-5 вариантов
        all_fields = [
            "title", "doc_num", "stock_qty", "mark", "model", "code_compl", "vin",
            "color", "price", "city", "manufacture_year", "fuel_type", "power",
            "body_type", "gear_box_type", "driving_gear_type", "engine_vol",
            "mileage", "dealer_center"
        ]
        
        normalized_source = source_field.split(".")[-1].lower().replace("_", "").replace("-", "")
        
        scores = []
        for field in all_fields:
            normalized_target = field.lower().replace("_", "")
            score = similarity(normalized_source, normalized_target)
            scores.append((field, score))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return [field for field, score in scores[:5] if score > 0.3]
    
    def _get_nested_value(self, obj: Dict, field_path: str) -> Any:
        """Получает значение из вложенного словаря по пути"""
        if not obj or not field_path:
            return None
        
        parts = field_path.split(".")
        value = obj
        
        for part in parts:
            if value is None:
                return None
            
            if isinstance(value, dict):
                # Пробуем найти ключ с учетом регистра и без
                if part in value:
                    value = value[part]
                else:
                    # Пробуем найти без учета регистра
                    part_lower = part.lower()
                    for key, val in value.items():
                        if key.lower() == part_lower:
                            value = val
                            break
                    else:
                        return None
            elif isinstance(value, list):
                # Если список, берем первый элемент
                if value and isinstance(value[0], dict):
                    value = value[0].get(part)
                else:
                    return None
            else:
                return None
        
        return value
    
    def save_import(self, file_content: bytes, file_type: str, 
                   field_mapping: Dict[str, Optional[str]], 
                   car_type: str = "new") -> Dict[str, Any]:
        """
        Сохраняет импортированные данные в таблицы импорта
        """
        # Парсим файл
        if file_type.lower() == "json":
            root_key, records = self.parse_json_file(file_content)
        elif file_type.lower() == "xml":
            root_key, records = self.parse_xml_file(file_content)
        else:
            raise ValueError(f"Неподдерживаемый тип файла: {file_type}")
        
        imported_cars = 0
        imported_used_cars = 0
        imported_pictures = 0
        imported_options = 0
        errors = []
        
        for idx, record in enumerate(records):
            try:
                # Создаем словарь для сохранения
                car_data = {}
                
                # Для XML формата DealerCenter, извлекаем Name как dealer_center
                if isinstance(record, dict) and 'Name' in record:
                    car_data['dealer_center'] = record['Name']
                
                # Извлекаем фотографии и опции ДО применения сопоставления полей
                images_urls = []
                options_list = []
                
                # Извлекаем фотографии из Images
                images_data = self._get_nested_value(record, 'Images')
                if images_data:
                    if isinstance(images_data, list):
                        for img_item in images_data:
                            if isinstance(img_item, dict):
                                url = img_item.get('url') or img_item.get('link') or img_item.get('src')
                                if url:
                                    images_urls.append(url)
                            elif isinstance(img_item, str):
                                images_urls.append(img_item)
                    elif isinstance(images_data, dict):
                        # Если Images это словарь, ищем Image внутри
                        if 'Image' in images_data:
                            img_list = images_data['Image'] if isinstance(images_data['Image'], list) else [images_data['Image']]
                            for img in img_list:
                                if isinstance(img, dict):
                                    url = img.get('url') or img.get('link') or img.get('src')
                                    if url:
                                        images_urls.append(url)
                
                # Извлекаем опции из ComplLevel, Options, Equipment и т.д.
                for opt_field in ['ComplLevel', 'Options', 'Equipment', 'Features', 'Option']:
                    opt_value = self._get_nested_value(record, opt_field)
                    if opt_value:
                        if isinstance(opt_value, str) and opt_value.strip():
                            # Если это строка, разбиваем по разделителям
                            options_list.extend([opt.strip() for opt in opt_value.split(',') if opt.strip()])
                        elif isinstance(opt_value, list):
                            for opt in opt_value:
                                if isinstance(opt, str):
                                    options_list.append(opt.strip())
                                elif isinstance(opt, dict):
                                    desc = opt.get('description') or opt.get('name') or opt.get('text')
                                    if desc:
                                        options_list.append(str(desc).strip())
                
                # Применяем сопоставление полей (исключая поля для фотографий и опций)
                excluded_from_mapping = {'Images', 'Images.Image', 'Images.Images', 'Images.Images.url', 
                                        'Images.Image.url', 'picture_path', 'pictures_real', 'ComplLevel', 
                                        'Options', 'Equipment', 'Features', 'Kilometrage'}
                
                for source_field, target_field in field_mapping.items():
                    # Пропускаем исключенные поля и поля без маппинга
                    if source_field in excluded_from_mapping or target_field is None:
                        continue
                    
                    # Для новых автомобилей не добавляем поле mileage
                    if car_type == "new" and target_field == "mileage":
                        continue
                    
                    value = self._get_nested_value(record, source_field)
                    
                    # Если значение не найдено по полному пути, пробуем найти только по имени поля
                    if value is None and '.' in source_field:
                        field_name = source_field.split('.')[-1]
                        value = self._get_nested_value(record, field_name)
                    
                    # Если все еще не найдено, пробуем найти по имени поля без учета регистра
                    if value is None or value == "":
                        field_name = source_field.split('.')[-1]
                        # Ищем в record по имени поля без учета регистра
                        if isinstance(record, dict):
                            for key, val in record.items():
                                if key.lower() == field_name.lower():
                                    value = val
                                    break
                    
                    if value is not None and value != "":
                        # Преобразуем списки в строки
                        if isinstance(value, list):
                            if value:  # Проверяем, что список не пустой
                                value = ", ".join(str(v) for v in value if v)
                            else:
                                continue  # Пропускаем пустые списки
                        
                        # Преобразуем числовые значения
                        if target_field in ['manufacture_year', 'engine_vol', 'mileage', 'owners', 'stock_qty']:
                            try:
                                # Убираем пробелы и запятые, заменяем запятую на точку
                                if isinstance(value, str):
                                    value_clean = value.replace(' ', '').replace(',', '.')
                                    if '.' in value_clean:
                                        value = int(float(value_clean))
                                    else:
                                        value = int(value_clean)
                            except (ValueError, TypeError):
                                pass  # Оставляем как есть, если не удалось преобразовать
                        
                        car_data[target_field] = str(value) if not isinstance(value, (int, float)) else value
                
                # Обрабатываем Kilometrage -> mileage (специальная обработка только для подержанных)
                # Для новых автомобилей mileage не используется
                if car_type == "used":
                    kilometrage_value = self._get_nested_value(record, 'Kilometrage')
                    if kilometrage_value is not None and 'mileage' not in car_data:
                        try:
                            if isinstance(kilometrage_value, str):
                                kilometrage_clean = kilometrage_value.replace(' ', '').replace(',', '.')
                                car_data['mileage'] = int(float(kilometrage_clean)) if '.' in kilometrage_clean else int(kilometrage_clean)
                            else:
                                car_data['mileage'] = int(kilometrage_value)
                        except (ValueError, TypeError):
                            pass
                
                # Определяем, новый или подержанный автомобиль
                if car_type == "new":
                    # Удаляем поле mileage из car_data, так как оно не существует в ImportCar
                    car_data.pop('mileage', None)
                    # Создаем ImportCar
                    import_car = ImportCar(
                        **car_data,
                        import_status="imported",
                        import_source=f"file_{idx}"
                    )
                    self.db.add(import_car)
                    self.db.flush()
                    imported_cars += 1
                    
                    # Обрабатываем фотографии из извлеченных URLs
                    if images_urls:
                        for pic_idx, url in enumerate(images_urls):
                            if url and url.strip():
                                import_pic = ImportCarPicture(
                                    car_id=import_car.id,
                                    url=url.strip(),
                                    seqno=pic_idx,
                                    type=None
                                )
                                self.db.add(import_pic)
                                imported_pictures += 1
                    
                    # Обрабатываем опции из извлеченного списка
                    if options_list:
                        for opt_desc in options_list:
                            if opt_desc and opt_desc.strip():
                                import_option = ImportCarOption(
                                    car_id=import_car.id,
                                    code=None,
                                    description=opt_desc.strip()
                                )
                                self.db.add(import_option)
                                imported_options += 1
                
                elif car_type == "used":
                    # Создаем ImportUsedCar
                    import_used_car = ImportUsedCar(
                        **car_data,
                        import_status="imported",
                        import_source=f"file_{idx}"
                    )
                    self.db.add(import_used_car)
                    self.db.flush()
                    imported_used_cars += 1
                    
                    # Обрабатываем фотографии из извлеченных URLs
                    if images_urls:
                        for pic_idx, url in enumerate(images_urls):
                            if url and url.strip():
                                import_pic = ImportUsedCarPicture(
                                    used_car_id=import_used_car.id,
                                    url=url.strip(),
                                    seqno=pic_idx,
                                    type=None
                                )
                                self.db.add(import_pic)
                                imported_pictures += 1
                    
                    # Обрабатываем опции из извлеченного списка
                    # Примечание: ImportCarOption использует ForeignKey на import_cars.id
                    # Для подержанных автомобилей опции можно сохранить, но нужно будет
                    # создать отдельную таблицу или использовать существующую структуру
                    # Пока сохраняем опции только для новых автомобилей
                    # TODO: Добавить поддержку опций для подержанных автомобилей
                    if options_list:
                        logger.warning(f"Опции для подержанных автомобилей не поддерживаются в текущей структуре БД. Найдено опций: {len(options_list)}")
                
            except Exception as e:
                error_msg = f"Ошибка при импорте записи {idx + 1}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        self.db.commit()
        
        return {
            "success": True,
            "imported_cars": imported_cars,
            "imported_used_cars": imported_used_cars,
            "imported_pictures": imported_pictures,
            "imported_options": imported_options,
            "errors": errors
        }
