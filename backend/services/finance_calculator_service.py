"""
Сервис для расчета финансовых параметров (кредиты, лизинг)
"""
from typing import Dict, Any, List, Optional
import math


class FinanceCalculatorService:
    """Расчет параметров кредита и лизинга"""
    
    def calculate_loan(
        self,
        car_price: float,
        down_payment: float,
        interest_rate: float,
        loan_term: int  # в месяцах
    ) -> Dict[str, Any]:
        """
        Рассчитывает параметры кредита
        
        Args:
            car_price: Цена автомобиля
            down_payment: Первоначальный взнос
            interest_rate: Процентная ставка (годовая, например 9.5)
            loan_term: Срок кредита в месяцах
        
        Returns:
            Dict с параметрами кредита:
            - loan_amount: Сумма кредита
            - monthly_payment: Ежемесячный платеж
            - total_payment: Общая сумма выплат
            - total_interest: Общая сумма процентов
            - payment_schedule: График платежей (опционально)
        """
        loan_amount = car_price - down_payment
        
        if loan_amount <= 0:
            return {
                "loan_amount": 0,
                "monthly_payment": 0,
                "total_payment": car_price,
                "total_interest": 0,
                "error": "Первоначальный взнос больше или равен цене автомобиля"
            }
        
        # Месячная процентная ставка
        monthly_rate = interest_rate / 100 / 12
        
        # Расчет аннуитетного платежа
        if monthly_rate > 0:
            monthly_payment = loan_amount * (
                monthly_rate * (1 + monthly_rate) ** loan_term
            ) / (
                (1 + monthly_rate) ** loan_term - 1
            )
        else:
            # Без процентов
            monthly_payment = loan_amount / loan_term
        
        total_payment = monthly_payment * loan_term
        total_interest = total_payment - loan_amount
        
        return {
            "loan_amount": round(loan_amount, 2),
            "monthly_payment": round(monthly_payment, 2),
            "total_payment": round(total_payment, 2),
            "total_interest": round(total_interest, 2),
            "interest_rate": interest_rate,
            "loan_term_months": loan_term,
            "loan_term_years": round(loan_term / 12, 1),
            "down_payment": down_payment,
            "down_payment_percent": round((down_payment / car_price) * 100, 1) if car_price > 0 else 0
        }
    
    def calculate_lease(
        self,
        car_price: float,
        residual_value: float,  # Остаточная стоимость
        lease_term: int,  # в месяцах
        interest_rate: float = 0.0  # Процентная ставка (опционально)
    ) -> Dict[str, Any]:
        """
        Рассчитывает параметры лизинга
        
        Args:
            car_price: Цена автомобиля
            residual_value: Остаточная стоимость (выкупная стоимость)
            lease_term: Срок лизинга в месяцах
            interest_rate: Процентная ставка (годовая, опционально)
        
        Returns:
            Dict с параметрами лизинга:
            - lease_amount: Сумма лизинга (цена - остаточная стоимость)
            - monthly_payment: Ежемесячный платеж
            - total_payment: Общая сумма выплат
            - residual_value: Остаточная стоимость
        """
        lease_amount = car_price - residual_value
        
        if lease_amount <= 0:
            return {
                "lease_amount": 0,
                "monthly_payment": 0,
                "total_payment": residual_value,
                "residual_value": residual_value,
                "error": "Остаточная стоимость больше или равна цене автомобиля"
            }
        
        # Месячная процентная ставка
        monthly_rate = interest_rate / 100 / 12 if interest_rate > 0 else 0
        
        # Расчет ежемесячного платежа
        if monthly_rate > 0:
            monthly_payment = lease_amount * (
                monthly_rate * (1 + monthly_rate) ** lease_term
            ) / (
                (1 + monthly_rate) ** lease_term - 1
            )
        else:
            # Без процентов (просто делим сумму на срок)
            monthly_payment = lease_amount / lease_term
        
        total_payment = monthly_payment * lease_term
        
        return {
            "lease_amount": round(lease_amount, 2),
            "monthly_payment": round(monthly_payment, 2),
            "total_payment": round(total_payment, 2),
            "residual_value": residual_value,
            "residual_percent": round((residual_value / car_price) * 100, 1) if car_price > 0 else 0,
            "lease_term_months": lease_term,
            "lease_term_years": round(lease_term / 12, 1),
            "interest_rate": interest_rate
        }
    
    def calculate_with_credit_offers(
        self,
        car_price: float,
        down_payment_percent: float = 20.0,
        loan_term: int = 60,
        credit_offers: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Рассчитывает кредит с учетом предложений банков
        
        Args:
            car_price: Цена автомобиля
            down_payment_percent: Процент первоначального взноса
            loan_term: Срок кредита в месяцах
            credit_offers: Список кредитных предложений банков
        
        Returns:
            Dict с расчетами для каждого предложения
        """
        down_payment = car_price * (down_payment_percent / 100)
        
        if not credit_offers:
            # Используем стандартные предложения
            credit_offers = [
                {
                    "bank": "Сбербанк",
                    "rate": 8.5,
                    "min_down_payment": 15,
                    "max_period": 60
                },
                {
                    "bank": "ВТБ",
                    "rate": 9.0,
                    "min_down_payment": 20,
                    "max_period": 84
                },
                {
                    "bank": "Альфа-Банк",
                    "rate": 9.5,
                    "min_down_payment": 10,
                    "max_period": 60
                }
            ]
        
        results = []
        
        for offer in credit_offers:
            # Проверяем, подходит ли предложение
            min_down = offer.get("min_down_payment", 0)
            max_period = offer.get("max_period", 60)
            
            if down_payment_percent >= min_down and loan_term <= max_period:
                rate = offer.get("rate", 9.0)
                calculation = self.calculate_loan(
                    car_price=car_price,
                    down_payment=down_payment,
                    interest_rate=rate,
                    loan_term=loan_term
                )
                
                calculation["bank"] = offer.get("bank", "Неизвестный банк")
                calculation["offer_details"] = offer
                results.append(calculation)
        
        # Сортируем по ежемесячному платежу (от меньшего к большему)
        results.sort(key=lambda x: x.get("monthly_payment", float('inf')))
        
        return {
            "car_price": car_price,
            "down_payment": down_payment,
            "down_payment_percent": down_payment_percent,
            "loan_term": loan_term,
            "offers": results,
            "best_offer": results[0] if results else None
        }
    
    def compare_financing_options(
        self,
        car_price: float,
        down_payment: float,
        loan_term: int = 60
    ) -> Dict[str, Any]:
        """
        Сравнивает варианты финансирования (кредит vs лизинг)
        
        Returns:
            Dict с сравнением вариантов
        """
        # Расчет кредита
        loan_calculation = self.calculate_loan(
            car_price=car_price,
            down_payment=down_payment,
            interest_rate=9.0,  # Средняя ставка
            loan_term=loan_term
        )
        
        # Расчет лизинга (остаточная стоимость 30% от цены)
        residual_value = car_price * 0.3
        lease_calculation = self.calculate_lease(
            car_price=car_price,
            residual_value=residual_value,
            lease_term=loan_term,
            interest_rate=8.0  # Обычно лизинг дешевле
        )
        
        return {
            "car_price": car_price,
            "down_payment": down_payment,
            "loan_term": loan_term,
            "loan": loan_calculation,
            "lease": lease_calculation,
            "comparison": {
                "monthly_payment_difference": round(
                    loan_calculation["monthly_payment"] - lease_calculation["monthly_payment"],
                    2
                ),
                "total_payment_difference": round(
                    loan_calculation["total_payment"] - lease_calculation["total_payment"],
                    2
                ),
                "cheaper_option": "lease" if lease_calculation["monthly_payment"] < loan_calculation["monthly_payment"] else "loan"
            }
        }



