"""Обработчик команд диалога для ИИ-бота по подбору авто"""
import re
from typing import Dict, Any, Optional, List, Tuple
from services.dialog_state_service import DialogStateService


class DialogCommandProcessor:
    """Обрабатывает команды пользователя в контексте диалога"""
    
    # Стартовые команды
    START_COMMANDS = [
        r"помоги\s+подобрать\s+машину",
        r"нужен\s+автомобиль",
        r"хочу\s+купить\s+авто",
        r"ищу\s+машину",
        r"подбери\s+авто",
        r"начать\s+поиск",
    ]
    
    # Команды сброса
    RESET_COMMANDS = [
        r"сброс",
        r"начать\s+заново",
        r"ищем\s+другую\s+машину",
        r"новый\s+поиск",
        r"очистить",
        r"сбросить",
    ]
    
    # Команды управления поиском
    SHOW_RESULTS_COMMANDS = [
        r"покажи\s+результаты",
        r"что\s+ты\s+нашел",
        r"что\s+нашел",
        r"покажи\s+варианты",
        r"покажи\s+машины",
    ]
    
    FILTERS_COMMANDS = [
        r"фильтры",
        r"измени\s+критерии",
        r"изменить\s+критерии",
        r"какие\s+критерии",
        r"текущие\s+критерии",
    ]
    
    COMPARE_COMMANDS = [
        r"сравни\s+(.+?)\s+и\s+(.+?)$",
        r"сравнить\s+(.+?)\s+и\s+(.+?)$",
        r"сравни\s+(.+?)\s+с\s+(.+?)$",
    ]
    
    SIMILAR_COMMANDS = [
        r"покажи\s+похожие\s+на\s+(.+?)$",
        r"похожие\s+на\s+(.+?)$",
        r"аналоги\s+(.+?)$",
        r"похожие\s+на\s+([\w\s]+)",
    ]
    
    HELP_COMMANDS = [
        r"помощь",
        r"справка",
        r"что\s+ты\s+умеешь",
        r"какие\s+команды",
    ]
    
    def __init__(self, dialog_state: DialogStateService):
        self.dialog_state = dialog_state
    
    def detect_command(self, user_query: str) -> Optional[Dict[str, Any]]:
        """Определяет тип команды в запросе пользователя"""
        query_lower = user_query.lower().strip()
        
        # Старт
        for pattern in self.START_COMMANDS:
            if re.search(pattern, query_lower):
                return {"type": "start", "original_query": user_query}
        
        # Сброс
        for pattern in self.RESET_COMMANDS:
            if re.search(pattern, query_lower):
                return {"type": "reset", "original_query": user_query}
        
        # Показать результаты
        for pattern in self.SHOW_RESULTS_COMMANDS:
            if re.search(pattern, query_lower):
                return {"type": "show_results", "original_query": user_query}
        
        # Фильтры
        for pattern in self.FILTERS_COMMANDS:
            if re.search(pattern, query_lower):
                return {"type": "show_filters", "original_query": user_query}
        
        # Сравнение
        for pattern in self.COMPARE_COMMANDS:
            match = re.search(pattern, query_lower)
            if match:
                model1 = match.group(1).strip()
                model2 = match.group(2).strip()
                return {
                    "type": "compare",
                    "model1": model1,
                    "model2": model2,
                    "original_query": user_query
                }
        
        # Похожие
        for pattern in self.SIMILAR_COMMANDS:
            match = re.search(pattern, query_lower)
            if match:
                model = match.group(1).strip()
                return {
                    "type": "similar",
                    "model": model,
                    "original_query": user_query
                }
        
        # Помощь
        for pattern in self.HELP_COMMANDS:
            if re.search(pattern, query_lower):
                return {"type": "help", "original_query": user_query}
        
        # Проверяем контекстные вопросы ("из них", "этого варианта")
        if self._is_contextual_question(query_lower):
            return {"type": "contextual_question", "original_query": user_query}
        
        # Если не команда, значит это обычный запрос с критериями
        return {"type": "search", "original_query": user_query}
    
    def _is_contextual_question(self, query: str) -> bool:
        """Проверяет, является ли запрос контекстным вопросом"""
        contextual_patterns = [
            r"из\s+них",
            r"из\s+представленных",
            r"этого\s+варианта",
            r"этого\s+авто",
            r"этой\s+машины",
            r"у\s+него",
            r"у\s+неё",
            r"у\s+этого",
            r"какой\s+у\s+него",
            r"какая\s+у\s+него",
            r"есть\s+ли\s+у\s+него",
            r"есть\s+ли\s+у\s+этого",
            r"почему\s+ты\s+мне\s+его\s+рекомендовал",
            r"почему\s+рекомендовал",
        ]
        return any(re.search(pattern, query) for pattern in contextual_patterns)
    
    def extract_extended_criteria(self, query: str, chat_history: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Извлекает расширенные критерии из запроса и истории с указанием источника"""
        criteria = {}
        query_lower = query.lower()
        # Словарь для хранения источников критериев (откуда они извлечены)
        criteria_sources = {}
        
        # === Типы кузова с синонимами ===
        body_type_mapping = {
            "внедорожник": ["внедорожник", "джип", "suv", "паркетник", "кроссовер"],
            "седан": ["седан"],
            "хэтчбек": ["хэтчбек", "хетчбек", "хетч"],
            "универсал": ["универсал"],
            "купе": ["купе"],
            "кабриолет": ["кабриолет"],
            "лифтбек": ["лифтбек"],
            "минивэн": ["минивэн", "микроавтобус"],
            "пикап": ["пикап"],
        }
        
        for body_type, synonyms in body_type_mapping.items():
            if any(syn in query_lower for syn in synonyms):
                criteria["body_type"] = body_type
                break
        
        # === Тип топлива ===
        fuel_mapping = {
            "бензиновый": ["бензин", "бензиновый"],
            "дизельный": ["дизель", "дизельный"],
            "гибридный": ["гибрид", "гибридный"],
            "электрический": ["электрический", "электро", "электромобиль"],
            "газовый": ["газ", "газовый"],
        }
        
        for fuel_type, synonyms in fuel_mapping.items():
            if any(syn in query_lower for syn in synonyms):
                criteria["fuel_type"] = fuel_type
                break
        
        # === Коробка передач ===
        gearbox_mapping = {
            "автоматическая": ["автомат", "акпп", "автоматическая", "автоматическая коробка"],
            "механическая": ["механика", "мкпп", "механическая", "механическая коробка"],
            "вариатор": ["вариатор", "cvt"],
            "роботизированная": ["робот", "роботизированная"],
        }
        
        for gearbox_type, synonyms in gearbox_mapping.items():
            if any(syn in query_lower for syn in synonyms):
                criteria["gear_box_type"] = gearbox_type
                break
        
        # === Привод ===
        drive_mapping = {
            "полный": ["полный привод", "4wd", "4x4"],
            "передний": ["передний привод", "fwd"],
            "задний": ["задний привод", "rwd"],
        }
        
        for drive_type, synonyms in drive_mapping.items():
            if any(syn in query_lower for syn in synonyms):
                criteria["driving_gear_type"] = drive_type
                break
        
        # === Цвет кузова ===
        # Проверяем явное указание "цвет" или "цвет кузова"
        color_field_specified = False
        if "цвет кузова" in query_lower or ("цвет" in query_lower and "салон" not in query_lower):
            color_field_specified = True
        
        color_patterns = [
            (r"черн[ыаяой]+", "черный"),
            (r"бел[ыаяой]+", "белый"),
            (r"сер[ыаяой]+", "серый"),
            (r"син[ияей]+", "синий"),
            (r"красн[ыаяой]+", "красный"),
            (r"зелен[ыаяой]+", "зеленый"),
            (r"коричнев[ыаяой]+", "коричневый"),
            (r"желт[ыаяой]+", "желтый"),
            (r"оранжев[ыаяой]+", "оранжевый"),
            (r"фиолетов[ыаяой]+", "фиолетовый"),
        ]
        
        for pattern, color in color_patterns:
            if re.search(pattern, query_lower):
                if color_field_specified:
                    # Явно указан цвет кузова - ищем только в поле color
                    criteria["color"] = color
                    criteria_sources["color"] = "field"  # В конкретном поле
                elif "салон" in query_lower:
                    # Указан салон - ищем в interior_color
                    criteria["interior_color"] = color
                    criteria_sources["interior_color"] = "field"
                else:
                    # Не указано явно - применяем к обоим полям (будет искать в обоих)
                    criteria["color"] = color
                    criteria_sources["color"] = "both"  # Может быть и в color, и в interior_color
                break
        
        # === Цвет салона ===
        if "светл[ыаяой]+" in query_lower and "салон" in query_lower:
            criteria["interior_color"] = "светлый"
            criteria_sources["interior_color"] = "field"
        elif "темн[ыаяой]+" in query_lower and "салон" in query_lower:
            criteria["interior_color"] = "темный"
            criteria_sources["interior_color"] = "field"
        
        # === Дополнительные опции ===
        # Опции могут быть в поле options или в описании (description)
        options_keywords = {
            "панорамная крыша": ["панорамная крыша", "панорама"],
            "обогрев сидений": ["обогрев сидений", "обогрев"],
            "камера заднего вида": ["камера заднего вида", "камера", "задняя камера"],
            "apple carplay": ["apple carplay", "carplay"],
            "android auto": ["android auto"],
            "круиз-контроль": ["круиз-контроль", "круиз"],
            "навигация": ["навигация", "навигационная система"],
            "коврики": ["коврики", "резиновые коврики"],
            "подогрев руля": ["подогрев руля"],
            "климат-контроль": ["климат-контроль", "климат"],
            "автономный обогрев": ["автономный обогрев"],
            "парктроники": ["парктроники", "парковочные датчики"],
        }
        
        found_options = []
        for option, keywords in options_keywords.items():
            if any(kw in query_lower for kw in keywords):
                found_options.append(option)
        
        if found_options:
            criteria["options"] = ", ".join(found_options)
            # Опции могут быть в поле options или в description
            criteria_sources["options"] = "both"  # И в поле options, и в description
        
        # === Исключения ===
        if "не" in query_lower or "кроме" in query_lower:
            # Исключение по цвету
            for pattern, color in color_patterns:
                if re.search(rf"(?:не|кроме)\s+{pattern}", query_lower):
                    criteria["exclude_color"] = color
                    break
        
        # === Относительные значения ===
        if "не важно" in query_lower or "не важно" in query_lower:
            # Пользователь говорит, что критерий не важен
            # Определяем, о каком критерии идет речь
            if "пробег" in query_lower:
                criteria["mileage_not_important"] = True
            if "цвет" in query_lower:
                criteria["color_not_important"] = True
        
        if "минимальный пробег" in query_lower or "малый пробег" in query_lower:
            criteria["max_mileage"] = 50000  # До 50к км
        
        if "свежак" in query_lower or "свежий" in query_lower:
            # Последние 3-5 лет
            from datetime import datetime
            current_year = datetime.now().year
            criteria["min_year"] = current_year - 3
        
        # === Страна-производитель ===
        country_brands = {
            "японский": ["toyota", "honda", "nissan", "mazda", "subaru", "lexus", "infiniti", "acura"],
            "корейский": ["hyundai", "kia", "genesis"],
            "немецкий": ["bmw", "mercedes", "audi", "volkswagen", "opel", "porsche"],
            "французский": ["renault", "peugeot", "citroen"],
            "американский": ["ford", "chevrolet", "tesla", "buick", "cadillac"],
            "китайский": ["geely", "chery", "haval", "dongfeng", "omoda"],
        }
        
        for country, brands in country_brands.items():
            if country in query_lower:
                criteria["country"] = country
                # Добавляем популярные марки этой страны в запрос
                criteria["preferred_brands"] = brands[:3]  # Первые 3 марки
                break
        
        # Сохраняем источники в критериях для последующего использования
        if criteria_sources:
            criteria["_sources"] = criteria_sources
        
        return criteria
    
    def format_criteria_summary(self, criteria: Dict[str, Any]) -> str:
        """Форматирует сводку критериев для показа пользователю"""
        if not criteria:
            return "Критерии не заданы"
        
        parts = []
        
        if "min_price" in criteria or "max_price" in criteria:
            price_str = ""
            if "min_price" in criteria:
                min_p = criteria["min_price"]
                if min_p >= 1_000_000:
                    price_str += f"от {min_p // 1_000_000} млн"
                else:
                    price_str += f"от {min_p // 1_000} тыс"
            if "max_price" in criteria:
                max_p = criteria["max_price"]
                if max_p >= 1_000_000:
                    price_str += f" до {max_p // 1_000_000} млн" if price_str else f"до {max_p // 1_000_000} млн"
                else:
                    price_str += f" до {max_p // 1_000} тыс" if price_str else f"до {max_p // 1_000} тыс"
            parts.append(f"💰 Бюджет: {price_str} ₽")
        
        if "body_type" in criteria:
            parts.append(f"🚗 Кузов: {criteria['body_type']}")
        
        if "fuel_type" in criteria:
            parts.append(f"⛽ Топливо: {criteria['fuel_type']}")
        
        if "gear_box_type" in criteria:
            parts.append(f"⚙️ КПП: {criteria['gear_box_type']}")
        
        if "driving_gear_type" in criteria:
            parts.append(f"🔧 Привод: {criteria['driving_gear_type']}")
        
        if "min_year" in criteria or "max_year" in criteria:
            year_str = ""
            if "min_year" in criteria:
                year_str = f"от {criteria['min_year']}"
            if "max_year" in criteria:
                year_str += f" до {criteria['max_year']}" if year_str else f"до {criteria['max_year']}"
            parts.append(f"📅 Год: {year_str}")
        
        if "max_mileage" in criteria:
            parts.append(f"🛣️ Пробег: до {criteria['max_mileage']} км")
        
        if "color" in criteria:
            parts.append(f"🎨 Цвет: {criteria['color']}")
        
        if "options" in criteria:
            parts.append(f"🔧 Опции: {criteria['options']}")
        
        return "\n".join(parts) if parts else "Базовые критерии заданы"

