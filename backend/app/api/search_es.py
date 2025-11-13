from fastapi import APIRouter, Query
from typing import Optional, Tuple, Dict, Any, List
import re
try:
    import spacy  # optional city NER
except Exception:
    spacy = None
from services.elasticsearch_service import ElasticsearchService


router = APIRouter(prefix="/api/search/es", tags=["search-es"])

es_service = ElasticsearchService()


def _extract_filters_from_text(text: str) -> Dict[str, Any]:
    """Улучшенный извлекатель фильтров из натурального текста.
    Извлекает: цена (до/от), объем двигателя, мощность, город, тип кузова, год, пробег.
    """
    if not text:
        return {}
    
    # Удаляем URL из текста (Google Drive, http/https ссылки)
    import re
    url_pattern = r'https?://[^\s]+'
    text = re.sub(url_pattern, '', text).strip()
    
    t = text.lower()
    filters: Dict[str, Any] = {}
    
    # Суперлативы: "самая дорогая", "самый дорогой", "максимальная цена"
    if re.search(r"сам[аяой]+ дорог[аяой]+|максимальн[аяой]+ цен[ае]|сам[аяой]+ дорог[аяой]+ модель", t):
        filters['sort_by'] = 'price_desc'
        filters['superlative'] = 'most_expensive'
    
    # Суперлативы: "самая дешевая", "самый дешевый", "минимальная цена"
    if re.search(r"сам[аяой]+ дешев[аяой]+|минимальн[аяой]+ цен[ае]|сам[аяой]+ дешев[аяой]+ модель", t):
        filters['sort_by'] = 'price_asc'
        filters['superlative'] = 'cheapest'
    
    # Фильтры по скидкам
    if re.search(r"скидк|акци|специальн[аяое]+ предложен|распродаж", t):
        filters['has_discount'] = True
    
    # Фильтры по объему багажника
    if "багажник" in t:
        if re.search(r"больш[ойе]+|просторн[ыйе]+", t):
            filters['large_cargo'] = True
        elif re.search(r"мал[ыйе]+|небольш[ойе]+", t):
            filters['small_cargo'] = True
    
    # Фильтры по турбонаддуву
    if re.search(r"турбо|наддув|turb[oа]", t):
        filters['has_turbo'] = True
    
    # Фильтры по клиренсу
    clearance_match = re.search(r"клиренс[ае]?\s*(?:больше|больш[ей]+|от)\s*(\d+)\s*(?:см|см\.?)", t)
    if clearance_match:
        try:
            clearance_cm = int(clearance_match.group(1))
            filters['min_clearance_cm'] = clearance_cm
        except Exception:
            pass
    
    # Фильтры по спортивному стилю
    if re.search(r"спортивн[ыйое]+|спорт", t):
        filters['sport_style'] = True

    # Относительные фильтры: "дешевле X", "дороже X"
    # Дешевле
    cheaper_match = re.search(r"дешевле\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|миллионов|тыс|тысяч|миллиона|миллион[ая]|миллион[а]|млн\.)?", t)
    if cheaper_match:
        try:
            val = float(cheaper_match.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
            unit = (cheaper_match.group(2) or '').lower()
            
            if 'млн' in unit or 'миллион' in unit:
                filters['max_price'] = int(val * 1_000_000)
            elif 'тыс' in unit or 'тысяч' in unit:
                filters['max_price'] = int(val * 1_000)
            else:
                # Если единицы не указаны, определяем по контексту
                # "дешевле миллиона" без числа - особый случай
                if re.search(r"дешевле\s*(?:миллиона|млн)", t):
                    filters['max_price'] = 1_000_000
                # Если число < 100, считаем миллионами
                elif val < 100:
                    filters['max_price'] = int(val * 1_000_000)
                else:
                    filters['max_price'] = int(val)
        except Exception:
            pass
    
    # Специальный случай: "дешевле миллиона" (без числа)
    if 'max_price' not in filters and re.search(r"дешевле\s*(?:миллиона|млн|миллион)", t):
        filters['max_price'] = 1_000_000
    
    # Дороже
    dearer_match = re.search(r"дороже\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|миллионов|тыс|тысяч)?", t)
    if dearer_match:
        try:
            val = float(dearer_match.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
            unit = dearer_match.group(2) or ''
            
            if 'млн' in unit or 'миллион' in unit:
                filters['min_price'] = int(val * 1_000_000)
            elif 'тыс' in unit or 'тысяч' in unit:
                filters['min_price'] = int(val * 1_000)
            else:
                # Если единицы не указаны, считаем миллионами если число < 100
                if val < 100:
                    filters['min_price'] = int(val * 1_000_000)
                else:
                    filters['min_price'] = int(val)
        except Exception:
            pass
    
    # Цена: "до 3 млн", "от 2 млн", "до 3000000", "от 1.5 млн", "2-4 млн"
    # До (только если не обработан "дешевле")
    if 'max_price' not in filters:
        # Поддержка дробных чисел: "до 1.5 млн"
        m = re.search(r"до\s*(\d+[\s\u00A0]*[.,]?\d*)\s*(млн|мл|миллион|миллионов)", t)
        if m:
            try:
                val = m.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.')
                max_mln = float(val)
                filters['max_price'] = int(max_mln * 1_000_000)
            except Exception:
                pass
        else:
            # До в рублях (5-8 цифр)
            m2 = re.search(r"до\s*(\d{5,8})", t)
            if m2:
                try:
                    filters['max_price'] = int(m2.group(1))
                except Exception:
                    pass
    
    # Диапазон цен: "от 1 до 3 млн", "от 1.5 млн до 2.5 млн" (проверяем ПЕРВЫМ, чтобы перезаписать отдельные "от" и "до")
    m_range = re.search(r"от\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|миллионов|тыс|тысяч)?\s*до\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|миллионов|тыс|тысяч)", t)
    if m_range:
        try:
            min_val = float(m_range.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
            max_val = float(m_range.group(3).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
            # Определяем единицы измерения
            min_unit = m_range.group(2) or m_range.group(4) or ''
            max_unit = m_range.group(4) or m_range.group(2) or ''
            
            # Конвертируем в рубли
            if 'млн' in min_unit or 'миллион' in min_unit:
                min_val *= 1_000_000
            elif 'тыс' in min_unit or 'тысяч' in min_unit:
                min_val *= 1_000
            
            if 'млн' in max_unit or 'миллион' in max_unit:
                max_val *= 1_000_000
            elif 'тыс' in max_unit or 'тысяч' in max_unit:
                max_val *= 1_000
            
            filters['min_price'] = int(min_val)
            filters['max_price'] = int(max_val)
        except Exception:
            pass
    
    # Диапазон цен через дефис: "2-4 млн", "1.5-2.5 млн"
    m5 = re.search(r"(\d+[\s\u00A0]*[.,]??\d*)\s*-\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|миллионов|тыс|тысяч)", t)
    if m5:
        try:
            min_val = float(m5.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
            max_val = float(m5.group(2).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
            unit = m5.group(3) or ''
            
            if 'млн' in unit or 'миллион' in unit:
                min_val *= 1_000_000
                max_val *= 1_000_000
            elif 'тыс' in unit or 'тысяч' in unit:
                min_val *= 1_000
                max_val *= 1_000
            
            filters['min_price'] = int(min_val)
            filters['max_price'] = int(max_val)
        except Exception:
            pass
    
    # От (только если не обработан диапазон)
    if 'min_price' not in filters:
        m3 = re.search(r"от\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|миллионов|тыс|тысяч)", t)
        if m3:
            try:
                val = m3.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.')
                min_val = float(val)
                unit = m3.group(2) or ''
                
                if 'млн' in unit or 'миллион' in unit:
                    min_val *= 1_000_000
                elif 'тыс' in unit or 'тысяч' in unit:
                    min_val *= 1_000
                
                filters['min_price'] = int(min_val)
            except Exception:
                pass
        else:
            m4 = re.search(r"от\s*(\d{5,8})", t)
            if m4:
                try:
                    filters['min_price'] = int(m4.group(1))
                except Exception:
                    pass
    
    # До (только если не обработан диапазон)
    if 'max_price' not in filters:
        m2 = re.search(r"до\s*(\d+[\s\u00A0]*[.,]??\d*)\s*(млн|мл|миллион|миллионов|тыс|тысяч)", t)
        if m2:
            try:
                val = m2.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.')
                max_val = float(val)
                unit = m2.group(2) or ''
                
                if 'млн' in unit or 'миллион' in unit:
                    max_val *= 1_000_000
                elif 'тыс' in unit or 'тысяч' in unit:
                    max_val *= 1_000
                
                filters['max_price'] = int(max_val)
            except Exception:
                pass
        else:
            # До в рублях (5-8 цифр)
            m2_rub = re.search(r"до\s*(\d{5,8})", t)
            if m2_rub:
                try:
                    filters['max_price'] = int(m2_rub.group(1))
                except Exception:
                    pass

    # Объем двигателя: "объем 2.0", "двигатель 1.6", "1.6 л", "до 2.0", "от 2.5"
    # До
    m6 = re.search(r"объем\s*(до|меньше|менее)\s*(\d+[.,]?\d*)", t)
    if m6:
        try:
            val = float(m6.group(2).replace(',', '.'))
            filters['max_engine_vol'] = val
        except Exception:
            pass
    
    # От
    m7 = re.search(r"объем\s*(от|больше|более)\s*(\d+[.,]?\d*)", t)
    if m7:
        try:
            val = float(m7.group(2).replace(',', '.'))
            filters['min_engine_vol'] = val
        except Exception:
            pass
    
    # Точный объем: "объем 2.0", "двигатель 1.6", "2.0 л"
    m8 = re.search(r"(объем|двигатель)\s*(\d+[.,]?\d*)\s*(л|литр)", t)
    if m8 and 'min_engine_vol' not in filters and 'max_engine_vol' not in filters:
        try:
            val = float(m8.group(2).replace(',', '.'))
            filters['min_engine_vol'] = val * 0.9  # небольшой диапазон для точности
            filters['max_engine_vol'] = val * 1.1
        except Exception:
            pass
    
    # Мощность: "мощность 150", "150 л.с.", "мощность до 200", "мощность от 200", "мощнее 200", "больше 200 лс"
    # Мощнее/больше (приоритет перед "от")
    m_power_more = re.search(r"(мощнее|больше|выше)\s*(\d+)\s*(?:л\.?\s*с\.?|лс)?", t)
    if m_power_more:
        try:
            filters['min_power'] = float(m_power_more.group(2))
        except Exception:
            pass
    
    # До
    if 'max_power' not in filters:
        m9 = re.search(r"мощность\s*(до|меньше|менее)\s*(\d+)", t)
        if m9:
            try:
                filters['max_power'] = float(m9.group(2))
            except Exception:
                pass
    
    # От (только если не обработан "мощнее")
    if 'min_power' not in filters:
        m10 = re.search(r"мощность\s*(от|больше|более)\s*(\d+)", t)
        if m10:
            try:
                filters['min_power'] = float(m10.group(2))
            except Exception:
                pass
    
    # Точная мощность: "мощность 150", "150 л.с.", "есть что-то мощнее 200 лс"
    if 'min_power' not in filters and 'max_power' not in filters:
        m11 = re.search(r"(\d+)\s*л\.?\s*с\.?|(\d+)\s*лс", t)
        if m11:
            try:
                power_val = float(m11.group(1) or m11.group(2))
                filters['min_power'] = power_val * 0.9
                filters['max_power'] = power_val * 1.1
            except Exception:
                pass
    
    # "Сколько лошадей у модели X" - вопрос о мощности (контекстный)
    if re.search(r"сколько\s+лошад|лошад[ейи]+", t):
        filters['power_question'] = True

    # Год выпуска: "2024", "2020 года", "старше 2015", "не старше 10 лет"
    from datetime import datetime
    current_year = datetime.now().year
    
    # Точный год
    m12 = re.search(r"(\d{4})\s*(года|год|г\.?)", t)
    if m12:
        try:
            year = int(m12.group(1))
            if 2000 <= year <= current_year:
                filters['min_year'] = year
                filters['max_year'] = year
        except Exception:
            pass
    
    # "старше X лет", "не старше X лет"
    m13 = re.search(r"(старше|больше)\s*(\d+)\s*лет", t)
    if m13:
        try:
            years_ago = int(m13.group(2))
            filters['max_year'] = current_year - years_ago
        except Exception:
            pass
    
    m14 = re.search(r"(не\s*старше|не\s*больше|младше|моложе)\s*(\d+)\s*лет", t)
    if m14:
        try:
            years_ago = int(m14.group(2))
            filters['min_year'] = current_year - years_ago
        except Exception:
            pass

    # Город (минимальный словарь + spaCy при наличии)
    cities = ['краснодар', 'москва', 'санкт-петербург', 'ростов-на-дону', 'новосибирск', 
              'екатеринбург', 'казань', 'воронеж', 'самара', 'нижний новгород', 'челябинск',
              'омск', 'красноярск', 'саратов', 'пермь', 'воронеж', 'тюмень', 'новокузнецк']
    for c in cities:
        if c in t:
            filters['city'] = c
            break
    if 'city' not in filters and spacy is not None and text:
        try:
            nlp = spacy.load('ru_core_news_md')
            doc = nlp(text)
            cand: List[str] = [ent.text for ent in getattr(doc, 'ents', []) or [] if ent.label_.upper() in ('GPE','LOC')]
            if cand:
                cand.sort(key=len, reverse=True)
                filters['city'] = cand[0].lower()
        except Exception:
            pass

    # Тип кузова
    if 'внедорож' in t or 'suv' in t:
        filters['body_type'] = 'внедорожник'
    elif 'кроссовер' in t:
        filters['body_type'] = 'кроссовер'
    elif 'седан' in t:
        filters['body_type'] = 'седан'
    elif 'хэтчбек' in t or 'хетчбек' in t:
        filters['body_type'] = 'хэтчбек'
    elif 'универсал' in t:
        filters['body_type'] = 'универсал'
    elif 'купе' in t:
        filters['body_type'] = 'купе'

    # Тип коробки передач
    if re.search(r'\b(автомат|автоматическ|акпп|automatic)\b', t):
        filters['gear_box_type'] = 'автомат'
    elif re.search(r'\b(механик|мкпп|manual)\b', t):
        filters['gear_box_type'] = 'механика'
    
    # Тип топлива
    if re.search(r'\b(бензин|petrol|gasoline)\b', t):
        filters['fuel_type'] = 'бензин'
    elif re.search(r'\b(дизель|diesel)\b', t):
        filters['fuel_type'] = 'дизель'
    elif re.search(r'\b(гибрид|hybrid)\b', t):
        filters['fuel_type'] = 'гибрид'
    elif re.search(r'\b(электрическ|electric|электро)\b', t):
        filters['fuel_type'] = 'электрический'
    
    # Тип привода
    if re.search(r'\b(полный|4wd|awd|full)\b', t):
        filters['driving_gear_type'] = 'полный'
    elif re.search(r'\b(передний|fwd|front)\b', t):
        filters['driving_gear_type'] = 'передний'
    elif re.search(r'\b(задний|rwd|rear)\b', t):
        filters['driving_gear_type'] = 'задний'
    
    # Марка и модель (базовое извлечение)
    # Более сложное извлечение марки/модели лучше делать через LLM
    common_marks = ['toyota', 'bmw', 'mercedes', 'audi', 'volkswagen', 'ford', 'hyundai', 
                    'kia', 'nissan', 'honda', 'mazda', 'skoda', 'renault', 'chery', 
                    'omoda', 'dongfeng', 'hongqi', 'aito', 'москвич', 'changan', 'jac', 
                    'belgee', 'jaecoo', 'tank', 'lrv', 'rvr', 'hnd', 'mbs', 'jgr']
    for mark in common_marks:
        if mark.lower() in t:
            filters['mark'] = mark.capitalize()
            break

    # Общие запросы без фильтров: "покажи машины", "какие модели доступны", "что есть"
    general_query_patterns = [
        r"покажи\s+машин|какие\s+модел|что\s+есть|что\s+доступн|подбери\s+мне\s+машин|хочу\s+купить\s+авто"
    ]
    is_general_query = any(re.search(pattern, t) for pattern in general_query_patterns)
    # Если нет фильтров и это общий запрос - показываем все доступные
    if is_general_query and not filters:
        filters['show_all'] = True

    return filters


@router.get("/cars")
async def search_cars(
    q: Optional[str] = Query(None, description="Текстовый запрос"),
    query: Optional[str] = Query(None, description="Алиас текстового запроса ('q') для совместимости"),
    mark: Optional[str] = None,
    model: Optional[str] = None,
    city: Optional[str] = None,
    fuel_type: Optional[str] = None,
    body_type: Optional[str] = None,
    gear_box_type: Optional[str] = None,
    driving_gear_type: Optional[str] = None,
    color: Optional[str] = None,
    interior_color: Optional[str] = None,
    options: Optional[str] = Query(None, description="Опции/комплектация (текст)"),
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    min_mileage: Optional[int] = None,
    max_mileage: Optional[int] = None,
    car_type: Optional[str] = Query(None, description='"car" или "used_car"'),
    vin: Optional[str] = None,
    engine: Optional[str] = None,
    cargo_volume: Optional[str] = None,
    door_qty: Optional[str] = None,
    doors: Optional[str] = None,
    fuel_consumption: Optional[str] = None,
    max_torque: Optional[str] = None,
    acceleration: Optional[str] = None,
    max_speed: Optional[str] = None,
    wheel_type: Optional[str] = None,
    category: Optional[str] = None,
    owners: Optional[int] = None,
    accident: Optional[str] = None,
    min_power: Optional[float] = None,
    max_power: Optional[float] = None,
    min_engine_vol: Optional[float] = None,
    max_engine_vol: Optional[float] = None,
    limit: int = 20,
    offset: int = 0,
    use_intelligent_search: Optional[bool] = Query(False, description="Использовать интеллектуальный поиск с ослаблением фильтров"),
):
    if not es_service.is_available():
        return {"total": 0, "hits": [], "error": "Elasticsearch недоступен"}

    # Поддержка обоих вариантов параметра: q и query
    text = q if (q is not None and q != "") else (query or "")

    # Если передан только текст без явных фильтров — извлечём все возможные фильтры
    extracted = {}
    search_query = text  # Текст для поиска по умолчанию
    if text:
        extracted = _extract_filters_from_text(text)
        
        # Извлекаем сортировку через ИИ (если доступно)
        try:
            from app.api.ai import _extract_sorting_with_ai
            sort_orders = await _extract_sorting_with_ai(
                user_query=text,
                extracted_filters=extracted
            )
            if sort_orders:
                extracted["sort_orders"] = sort_orders
        except Exception as e:
            print(f"⚠️ Ошибка извлечения сортировки через ИИ: {e}")
        
        # Также используем расширенный парсер критериев для лучшего извлечения
        from services.dialog_command_processor import DialogCommandProcessor
        from services.dialog_state_service import DialogStateService
        dialog_state_temp = DialogStateService("temp_user")
        command_processor_temp = DialogCommandProcessor(dialog_state_temp)
        extended_criteria = command_processor_temp.extract_extended_criteria(text, [])
        
        # Применяем извлеченные фильтры только если они не были указаны явно
        # Расширенные критерии имеют приоритет для специфичных полей
        city = city or extracted.get('city')
        body_type = body_type or extended_criteria.get('body_type') or extracted.get('body_type')
        fuel_type = fuel_type or extended_criteria.get('fuel_type') or extracted.get('fuel_type')
        gear_box_type = gear_box_type or extended_criteria.get('gear_box_type')
        driving_gear_type = driving_gear_type or extended_criteria.get('driving_gear_type')
        color = color or extended_criteria.get('color')
        interior_color = interior_color or extended_criteria.get('interior_color')
        options = options or extended_criteria.get('options')
        min_price = min_price if min_price is not None else extracted.get('min_price')
        max_price = max_price if max_price is not None else extracted.get('max_price')
        min_year = min_year if min_year is not None else (extended_criteria.get('min_year') or extracted.get('min_year'))
        max_year = max_year if max_year is not None else extracted.get('max_year')
        min_power = min_power if min_power is not None else extracted.get('min_power')
        max_power = max_power if max_power is not None else extracted.get('max_power')
        min_engine_vol = min_engine_vol if min_engine_vol is not None else extracted.get('min_engine_vol')
        max_engine_vol = max_engine_vol if max_engine_vol is not None else extracted.get('max_engine_vol')
        
        # Новые фильтры
        has_discount = extracted.get('has_discount', False)
        large_cargo = extracted.get('large_cargo', False)
        small_cargo = extracted.get('small_cargo', False)
        has_turbo = extracted.get('has_turbo', False)
        min_clearance_cm = extracted.get('min_clearance_cm')
        sport_style = extracted.get('sport_style', False)
        sort_by = extracted.get('sort_by')  # 'price_desc' или 'price_asc'
        superlative = extracted.get('superlative')  # 'most_expensive' или 'cheapest'
        show_all = extracted.get('show_all', False)
        
        # Если из запроса извлечены только фильтры (нет марки/модели/города для текстового поиска),
        # очищаем текстовый запрос, чтобы не мешал фильтрам
        has_text_content = any([
            extracted.get('city'),  # город извлечен
            any(word in text.lower() for word in ['toyota', 'bmw', 'mercedes', 'audi', 'volkswagen', 
                                                   'hyundai', 'kia', 'lada', 'ваз', 'лада'])  # марка в тексте
        ])
        
        # Если запрос содержит только фильтрующие слова без контента для поиска, очищаем query
        filter_only_words = ['от', 'до', 'млн', 'миллион', 'тысяч', 'тыс', 'мощность', 'объем', 
                            'двигатель', 'л.с.', 'лс', 'год', 'старше', 'младше', 'больше', 'меньше',
                            'скидк', 'акци', 'самый', 'самая', 'дорог', 'дешев']
        words_in_query = text.lower().split()
        is_filter_only = (
            any(word in filter_only_words for word in words_in_query) and 
            not has_text_content and
            not any(len(w) > 3 and w.isalpha() and w not in filter_only_words for w in words_in_query)
        )
        
        if is_filter_only or show_all:
            search_query = ""  # Очищаем текстовый запрос, оставляем только фильтры
    else:
        # Если нет текста, новые фильтры не применяются
        has_discount = None
        large_cargo = None
        small_cargo = None
        has_turbo = None
        min_clearance_cm = None
        sport_style = None
        sort_by = None
        superlative = None
        show_all = False

    # Если запрос "покажи все" без фильтров - показываем первые N популярных
    if show_all and not any([
        min_price, max_price, min_year, max_year, min_mileage, max_mileage,
        min_power, max_power, min_engine_vol, max_engine_vol,
        mark, model, city, fuel_type, body_type, gear_box_type, driving_gear_type,
        color, interior_color, options
    ]):
        # Убираем текстовый запрос и показываем все доступные автомобили
        search_query = ""

    # Если включен интеллектуальный поиск, используем IntelligentSearchService
    if use_intelligent_search:
        try:
            from services.intelligent_search_service import IntelligentSearchService
            
            print("🔍 Используется интеллектуальный поиск в search_es")
            
            # Формируем начальные параметры поиска
            initial_params = {
                "mark": mark,
                "model": model,
                "city": city,
                "fuel_type": fuel_type,
                "body_type": body_type,
                "gear_box_type": gear_box_type,
                "driving_gear_type": driving_gear_type,
                "color": color,
                "interior_color": interior_color,
                "options": options,
                "min_price": min_price,
                "max_price": max_price,
                "min_year": min_year,
                "max_year": max_year,
                "min_mileage": min_mileage,
                "max_mileage": max_mileage,
                "car_type": car_type,
                "min_power": min_power,
                "max_power": max_power,
                "min_engine_vol": min_engine_vol,
                "max_engine_vol": max_engine_vol,
            }
            # Убираем None значения
            initial_params = {k: v for k, v in initial_params.items() if v is not None}
            
            # Выполняем интеллектуальный поиск с поддержкой SQL агента
            from models import get_db
            from sqlalchemy.orm import Session
            # Получаем сессию БД для SQL агента
            db_gen = get_db()
            db = next(db_gen)
            try:
                intelligent_search = IntelligentSearchService(db_session=db)
                # Используем SQL агент если есть структурированные параметры
                use_sql_agent = len(initial_params) > 0
                search_result = await intelligent_search.search_with_intelligence(
                    initial_params=initial_params,
                    user_query=text or search_query,
                    dialogue_context="",
                    use_sql_agent=use_sql_agent
                )
            finally:
                db.close()
            
            # Если поиск успешен, возвращаем результаты в формате Elasticsearch
            if search_result.get("success") and search_result.get("results"):
                hits = search_result.get("results", [])
                total = search_result.get("total", len(hits))
                
                # Формируем результат в формате Elasticsearch
                result = {
                    "total": total,
                    "hits": hits[:limit],
                    "intelligent_search": {
                        "enabled": True,
                        "relaxation_applied": search_result.get("relaxation_applied", False),
                        "relaxation_steps": search_result.get("relaxation_steps", 0),
                        "relaxed_params": search_result.get("relaxed_params"),
                        "original_params": search_result.get("original_params"),
                        "recommendations": search_result.get("recommendations")
                    }
                }
            else:
                # Если результатов нет, возвращаем пустой результат с рекомендациями
                result = {
                    "total": 0,
                    "hits": [],
                    "intelligent_search": {
                        "enabled": True,
                        "relaxation_applied": search_result.get("relaxation_applied", False),
                        "relaxation_steps": search_result.get("relaxation_steps", 0),
                        "recommendations": search_result.get("recommendations")
                    }
                }
        except Exception as e:
            print(f"⚠️ Ошибка интеллектуального поиска: {e}, используем обычный поиск")
            # Fallback на обычный поиск
            result = es_service.search_cars(
                query=search_query,
                mark=mark,
                model=model,
                city=city,
                fuel_type=fuel_type,
                body_type=body_type,
                gear_box_type=gear_box_type,
                driving_gear_type=driving_gear_type,
                color=color,
                interior_color=interior_color,
                options=options,
                min_price=min_price,
                max_price=max_price,
                min_year=min_year,
                max_year=max_year,
                min_mileage=min_mileage,
                max_mileage=max_mileage,
                car_type=car_type,
                vin=vin,
                engine=engine,
                cargo_volume=cargo_volume,
                door_qty=door_qty,
                doors=doors,
                fuel_consumption=fuel_consumption,
                max_torque=max_torque,
                acceleration=acceleration,
                max_speed=max_speed,
                wheel_type=wheel_type,
                category=category,
                owners=owners,
                accident=accident,
                min_power=min_power,
                max_power=max_power,
                min_engine_vol=min_engine_vol,
                max_engine_vol=max_engine_vol,
                limit=limit,
                offset=offset,
                has_discount=has_discount,
                large_cargo=large_cargo,
                small_cargo=small_cargo,
                has_turbo=has_turbo,
                min_clearance_cm=min_clearance_cm,
                sport_style=sport_style,
                sort_by=sort_by,
                superlative=superlative,
                show_all=show_all,
                sort_orders=extracted.get("sort_orders") if extracted else None
            )
    else:
        # Обычный поиск
        result = es_service.search_cars(
            query=search_query,
            mark=mark,
            model=model,
            city=city,
            fuel_type=fuel_type,
            body_type=body_type,
            gear_box_type=gear_box_type,
            driving_gear_type=driving_gear_type,
            color=color,
            interior_color=interior_color,
            options=options,
            min_price=min_price,
            max_price=max_price,
            min_year=min_year,
            max_year=max_year,
            min_mileage=min_mileage,
            max_mileage=max_mileage,
            car_type=car_type,
            vin=vin,
            engine=engine,
            cargo_volume=cargo_volume,
            door_qty=door_qty,
            doors=doors,
            fuel_consumption=fuel_consumption,
            max_torque=max_torque,
            acceleration=acceleration,
            max_speed=max_speed,
            wheel_type=wheel_type,
            category=category,
            owners=owners,
            accident=accident,
            min_power=min_power,
            max_power=max_power,
            min_engine_vol=min_engine_vol,
            max_engine_vol=max_engine_vol,
            limit=limit,
            offset=offset,
            has_discount=has_discount,
            large_cargo=large_cargo,
            small_cargo=small_cargo,
            has_turbo=has_turbo,
            min_clearance_cm=min_clearance_cm,
            sport_style=sport_style,
            sort_by=sort_by,
            superlative=superlative,
            show_all=show_all,
            sort_orders=extracted.get("sort_orders") if extracted else None
        )
    # Расставляем пометки альтернативного результата по городу (если город извлечён)
    detected_city = None
    if text and not city:
        extracted2 = _extract_filters_from_text(text)
        detected_city = extracted2.get('city')
    else:
        detected_city = (city or '').lower() if city else None

    try:
        hits = result.get('hits', []) if isinstance(result, dict) else []
        for h in hits:
            s = h.get('_source', {})
            c = (s.get('city') or '').strip().lower()
            alt = False
            if detected_city and c and c != detected_city:
                alt = True
            # пишем флаг в _source
            s['alternative'] = alt
            h['_source'] = s
        if isinstance(result, dict):
            result['detected_city'] = detected_city
    except Exception:
        pass

    return result


