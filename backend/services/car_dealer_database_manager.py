"""
Менеджер баз данных автосалона
Управляет всеми базами данных: автомобили, финансы, опции
"""
from typing import Dict, Any, List, Optional
from services.elasticsearch_service import ElasticsearchService
from services.database_service import DatabaseService
from services.finance_calculator_service import FinanceCalculatorService


class CarDealerDatabaseManagerService:
    """Управление всеми базами данных автосалона"""
    
    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
        self.es_service = ElasticsearchService()
        self.finance_calculator = FinanceCalculatorService()
    
    def search(
        self,
        domain: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Универсальный поиск по домену
        
        Args:
            domain: Домен поиска ("cars", "used_cars", "finance")
            parameters: Параметры поиска
        
        Returns:
            Результаты поиска
        """
        if domain in ["cars", "used_cars"]:
            # Поиск автомобилей через Elasticsearch
            return self.es_service.search_cars(**parameters)
        elif domain == "finance":
            # Поиск финансовых предложений
            return self._search_finance_offers(parameters)
        else:
            return {
                "success": False,
                "error": f"Неизвестный домен: {domain}"
            }
    
    def get_available_brands(self) -> List[str]:
        """Получает список доступных марок"""
        try:
            result = self.es_service.search_cars(limit=500)
            brands = set()
            
            for hit in result.get("hits", []):
                brand = hit.get("_source", {}).get("mark")
                if brand:
                    brands.add(brand)
            
            return sorted(list(brands))
        except Exception as e:
            print(f"⚠️ Ошибка получения марок: {e}")
            return []
    
    def get_available_categories(self) -> List[str]:
        """Получает список доступных категорий кузова"""
        try:
            result = self.es_service.search_cars(limit=500)
            categories = set()
            
            for hit in result.get("hits", []):
                category = hit.get("_source", {}).get("body_type") or hit.get("_source", {}).get("category")
                if category:
                    categories.add(category)
            
            return sorted(list(categories))
        except Exception as e:
            print(f"⚠️ Ошибка получения категорий: {e}")
            return []
    
    def calculate_finance_for_car(
        self,
        car_price: float,
        down_payment_percent: float = 20.0,
        loan_term: int = 60
    ) -> Dict[str, Any]:
        """
        Рассчитывает финансовые параметры для автомобиля
        
        Args:
            car_price: Цена автомобиля
            down_payment_percent: Процент первоначального взноса
            loan_term: Срок кредита в месяцах
        
        Returns:
            Результаты финансовых расчетов
        """
        return self.finance_calculator.calculate_with_credit_offers(
            car_price=car_price,
            down_payment_percent=down_payment_percent,
            loan_term=loan_term
        )
    
    def get_car_details(self, car_id: int, car_type: str = "car") -> Optional[Dict[str, Any]]:
        """
        Получает детальную информацию об автомобиле
        
        Args:
            car_id: ID автомобиля
            car_type: Тип автомобиля ("car" или "used_car")
        
        Returns:
            Детальная информация об автомобиле или None
        """
        try:
            if car_type == "used_car":
                car = self.db_service.get_used_car(car_id)
            else:
                car = self.db_service.get_car(car_id)
            
            if car:
                # Преобразуем в словарь
                car_dict = {
                    "id": car.id,
                    "mark": car.mark,
                    "model": car.model,
                    "price": car.price if hasattr(car, 'price') else getattr(car, 'sale_price', None),
                    "year": getattr(car, 'manufacture_year', None) or getattr(car, 'model_year', None),
                    "fuel_type": getattr(car, 'fuel_type', None),
                    "body_type": getattr(car, 'body_type', None) or getattr(car, 'category', None),
                    "power": getattr(car, 'power', None),
                    "engine_vol": getattr(car, 'engine_vol', None),
                    "city": getattr(car, 'city', None),
                    "type": car_type
                }
                
                # Добавляем пробег для подержанных
                if car_type == "used_car" and hasattr(car, 'mileage'):
                    car_dict["mileage"] = car.mileage
                
                return car_dict
            
            return None
            
        except Exception as e:
            print(f"⚠️ Ошибка получения деталей автомобиля: {e}")
            return None
    
    def _search_finance_offers(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Поиск финансовых предложений
        
        Args:
            parameters: Параметры поиска (car_price, down_payment_percent, loan_term)
        
        Returns:
            Результаты поиска финансовых предложений
        """
        car_price = parameters.get("car_price", 0)
        down_payment_percent = parameters.get("down_payment_percent", 20.0)
        loan_term = parameters.get("loan_term", 60)
        
        if car_price <= 0:
            return {
                "success": False,
                "error": "Не указана цена автомобиля"
            }
        
        # Используем стандартные предложения
        credit_offers = [
            {
                "bank": "Сбербанк",
                "rate": 8.5,
                "min_down_payment": 15,
                "max_period": 60,
                "special_conditions": "Первоначальный взнос от 15%"
            },
            {
                "bank": "ВТБ",
                "rate": 9.0,
                "min_down_payment": 20,
                "max_period": 84,
                "special_conditions": "Срок до 7 лет"
            },
            {
                "bank": "Альфа-Банк",
                "rate": 9.5,
                "min_down_payment": 10,
                "max_period": 60,
                "special_conditions": "Первоначальный взнос от 10%"
            }
        ]
        
        calculation = self.finance_calculator.calculate_with_credit_offers(
            car_price=car_price,
            down_payment_percent=down_payment_percent,
            loan_term=loan_term,
            credit_offers=credit_offers
        )
        
        return {
            "success": True,
            "offers": calculation.get("offers", []),
            "best_offer": calculation.get("best_offer")
        }
    
    def get_car_options(self, car_id: int) -> List[Dict[str, Any]]:
        """Получает опции автомобиля"""
        try:
            options = self.db_service.get_car_options(car_id)
            
            result = []
            for option in options:
                result.append({
                    "id": option.id,
                    "description": option.description,
                    "code": option.code,
                    "group": option.group.name if option.group else None
                })
            
            return result
            
        except Exception as e:
            print(f"⚠️ Ошибка получения опций: {e}")
            return []



