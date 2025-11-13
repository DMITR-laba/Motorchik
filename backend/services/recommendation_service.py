"""
Сервис генерации рекомендаций при отсутствии точных совпадений
"""
from typing import Dict, Any, List, Optional
import json
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType
from services.elasticsearch_service import ElasticsearchService


class RecommendationService:
    """Генерация рекомендаций и альтернативных вариантов"""
    
    def __init__(self):
        self.orchestrator = AIModelOrchestratorService()
        self.es_service = ElasticsearchService()
    
    async def generate_recommendations(
        self,
        initial_params: Dict[str, Any],
        user_query: str,
        available_cars: List[Dict[str, Any]],
        dialogue_context: str = ""
    ) -> Dict[str, Any]:
        """
        Генерирует рекомендации при отсутствии точных совпадений
        
        Args:
            initial_params: Исходные параметры поиска
            user_query: Запрос пользователя
            available_cars: Доступные автомобили (даже если не подходят под фильтры)
            dialogue_context: Контекст диалога
        
        Returns:
            Dict с анализом, рекомендациями и ближайшими совпадениями
        """
        if not available_cars:
            return {
                "analysis": "В базе данных нет доступных автомобилей",
                "recommendations": [],
                "closest_matches": [],
                "suggested_alternatives": []
            }
        
        # Анализируем причины отсутствия результатов
        analysis = await self._analyze_no_results(initial_params, user_query, available_cars)
        
        # Генерируем рекомендации через LLM
        recommendations = await self._generate_ai_recommendations(
            initial_params,
            user_query,
            analysis,
            dialogue_context
        )
        
        # Находим ближайшие совпадения
        closest_matches = self._find_closest_matches(initial_params, available_cars)
        
        # Предлагаем альтернативы
        suggested_alternatives = await self._suggest_alternatives(
            initial_params,
            user_query,
            available_cars
        )
        
        return {
            "analysis": analysis,
            "recommendations": recommendations,
            "closest_matches": closest_matches[:5],  # Топ-5 ближайших
            "suggested_alternatives": suggested_alternatives,
            "total_available": len(available_cars)
        }
    
    async def _analyze_no_results(
        self,
        params: Dict[str, Any],
        user_query: str,
        available_cars: List[Dict[str, Any]]
    ) -> str:
        """Анализирует причины отсутствия результатов"""
        
        # Простой анализ на основе параметров
        issues = []
        
        if params.get("max_price"):
            max_price = params.get("max_price")
            # Проверяем, есть ли автомобили дороже
            cars_above_price = [c for c in available_cars if self._get_car_price(c) > max_price]
            if cars_above_price:
                min_above = min([self._get_car_price(c) for c in cars_above_price])
                issues.append(f"Минимальная цена доступных автомобилей: {min_above:,} руб. (ваш бюджет: {max_price:,} руб.)")
        
        if params.get("min_year"):
            min_year = params.get("min_year")
            # Проверяем, есть ли автомобили старше
            cars_older = [c for c in available_cars if self._get_car_year(c) < min_year if self._get_car_year(c)]
            if cars_older:
                max_older = max([self._get_car_year(c) for c in cars_older if self._get_car_year(c)])
                issues.append(f"Самый новый доступный автомобиль: {max_older} год (ваш запрос: от {min_year} года)")
        
        if params.get("brand"):
            brand = params.get("brand")
            # Проверяем, есть ли эта марка
            cars_with_brand = [c for c in available_cars if c.get("mark", "").lower() == brand.lower()]
            if not cars_with_brand:
                available_brands = list(set([c.get("mark") for c in available_cars if c.get("mark")]))
                issues.append(f"Марка '{brand}' недоступна. Доступные марки: {', '.join(available_brands[:10])}")
        
        if issues:
            return " | ".join(issues)
        else:
            return "Не удалось определить причину отсутствия результатов"
    
    async def _generate_ai_recommendations(
        self,
        params: Dict[str, Any],
        user_query: str,
        analysis: str,
        dialogue_context: str
    ) -> List[Dict[str, Any]]:
        """Генерирует рекомендации через LLM"""
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.RECOMMENDATION
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            
            prompt = f"""Ты - эксперт-консультант по подбору автомобилей. Клиент не нашел подходящих вариантов.

ЗАПРОС КЛИЕНТА: {user_query}
ПАРАМЕТРЫ ПОИСКА: {json.dumps(params, ensure_ascii=False, indent=2)}
АНАЛИЗ ПРОБЛЕМЫ: {analysis}
"""
            
            if dialogue_context:
                prompt += f"\nКОНТЕКСТ ДИАЛОГА: {dialogue_context}\n"
            
            prompt += """
Сгенерируй 3-5 конкретных рекомендаций для клиента. Каждая рекомендация должна:
1. Быть конкретной и практичной
2. Предлагать реальную альтернативу
3. Объяснять преимущества предложения
4. Учитывать потребности клиента

Формат ответа JSON:
{
    "recommendations": [
        {
            "title": "Краткое название рекомендации",
            "description": "Подробное описание",
            "suggested_params": {
                "max_price": число или null,
                "min_year": число или null,
                "brand": "марка" или null,
                "category": "категория" или null
            },
            "reasoning": "Почему это подходит клиенту"
        }
    ]
}"""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты - эксперт-консультант по подбору автомобилей. Генерируешь полезные рекомендации."),
                ("human", prompt)
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            response = await chain.ainvoke({})
            
            # Парсим JSON
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                    return result.get("recommendations", [])
            except json.JSONDecodeError:
                pass
            
            # Fallback - простая генерация
            return self._generate_simple_recommendations(params, analysis)
            
        except Exception as e:
            print(f"⚠️ Ошибка генерации рекомендаций через ИИ: {e}")
            return self._generate_simple_recommendations(params, analysis)
    
    def _generate_simple_recommendations(
        self,
        params: Dict[str, Any],
        analysis: str
    ) -> List[Dict[str, Any]]:
        """Простая генерация рекомендаций без ИИ"""
        recommendations = []
        
        if params.get("max_price"):
            # Рекомендация увеличить бюджет
            new_price = int(params.get("max_price") * 1.2)
            recommendations.append({
                "title": "Увеличить бюджет на 20%",
                "description": f"Рассмотрите автомобили до {new_price:,} руб. Это расширит выбор доступных вариантов.",
                "suggested_params": {"max_price": new_price},
                "reasoning": "Текущий бюджет слишком ограничивает выбор"
            })
        
        if params.get("min_year"):
            # Рекомендация уменьшить год
            new_year = params.get("min_year") - 2
            if new_year >= 2015:
                recommendations.append({
                    "title": "Рассмотреть автомобили на 2 года старше",
                    "description": f"Автомобили от {new_year} года могут быть хорошей альтернативой.",
                    "suggested_params": {"min_year": new_year},
                    "reasoning": "Расширение диапазона годов увеличит выбор"
                })
        
        if params.get("brand"):
            recommendations.append({
                "title": "Рассмотреть другие марки",
                "description": "Похожие марки могут предложить аналогичные характеристики по более доступной цене.",
                "suggested_params": {"brand": None},
                "reasoning": "Расширение выбора марок увеличит количество вариантов"
            })
        
        return recommendations
    
    def _find_closest_matches(
        self,
        params: Dict[str, Any],
        available_cars: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Находит ближайшие совпадения по параметрам"""
        scored_cars = []
        
        for car in available_cars:
            score = 0.0
            max_score = 0.0
            
            # Сравниваем цену
            if params.get("max_price"):
                max_score += 1.0
                car_price = self._get_car_price(car)
                if car_price and car_price <= params.get("max_price"):
                    score += 1.0
                elif car_price:
                    # Штраф за превышение цены
                    penalty = min(1.0, (car_price - params.get("max_price")) / params.get("max_price"))
                    score += max(0, 1.0 - penalty)
            
            # Сравниваем год
            if params.get("min_year"):
                max_score += 1.0
                car_year = self._get_car_year(car)
                if car_year and car_year >= params.get("min_year"):
                    score += 1.0
                elif car_year:
                    # Штраф за старый год
                    penalty = min(1.0, (params.get("min_year") - car_year) / 5.0)
                    score += max(0, 1.0 - penalty)
            
            # Сравниваем марку
            if params.get("brand"):
                max_score += 0.5
                if car.get("mark", "").lower() == params.get("brand", "").lower():
                    score += 0.5
            
            # Сравниваем категорию
            if params.get("category") or params.get("body_type"):
                max_score += 0.5
                car_category = car.get("category") or car.get("body_type", "")
                param_category = params.get("category") or params.get("body_type", "")
                if car_category and param_category and car_category.lower() == param_category.lower():
                    score += 0.5
            
            # Нормализуем score
            if max_score > 0:
                normalized_score = score / max_score
                scored_cars.append({
                    "car": car,
                    "score": normalized_score,
                    "match_percentage": int(normalized_score * 100)
                })
        
        # Сортируем по score
        scored_cars.sort(key=lambda x: x["score"], reverse=True)
        
        return scored_cars
    
    async def _suggest_alternatives(
        self,
        params: Dict[str, Any],
        user_query: str,
        available_cars: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Предлагает альтернативные варианты (другие марки, категории)"""
        alternatives = []
        
        # Собираем статистику по доступным автомобилям
        brands = {}
        categories = {}
        price_ranges = []
        
        for car in available_cars:
            brand = car.get("mark")
            if brand:
                brands[brand] = brands.get(brand, 0) + 1
            
            category = car.get("category") or car.get("body_type")
            if category:
                categories[category] = categories.get(category, 0) + 1
            
            price = self._get_car_price(car)
            if price:
                price_ranges.append(price)
        
        # Предлагаем популярные марки
        if params.get("brand") and brands:
            sorted_brands = sorted(brands.items(), key=lambda x: x[1], reverse=True)
            top_brands = [b[0] for b in sorted_brands[:3] if b[0].lower() != params.get("brand", "").lower()]
            if top_brands:
                alternatives.append({
                    "type": "alternative_brand",
                    "title": f"Популярные марки: {', '.join(top_brands)}",
                    "suggested_params": {"brand": top_brands[0]},
                    "count": brands.get(top_brands[0], 0)
                })
        
        # Предлагаем популярные категории
        if (params.get("category") or params.get("body_type")) and categories:
            sorted_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)
            top_categories = [c[0] for c in sorted_categories[:3]]
            if top_categories:
                alternatives.append({
                    "type": "alternative_category",
                    "title": f"Популярные категории: {', '.join(top_categories)}",
                    "suggested_params": {"category": top_categories[0]},
                    "count": categories.get(top_categories[0], 0)
                })
        
        # Предлагаем ценовой диапазон
        if price_ranges and params.get("max_price"):
            avg_price = sum(price_ranges) / len(price_ranges)
            if avg_price > params.get("max_price") * 1.1:
                alternatives.append({
                    "type": "price_range",
                    "title": f"Средняя цена доступных автомобилей: {int(avg_price):,} руб.",
                    "suggested_params": {"max_price": int(avg_price * 1.1)},
                    "count": len(price_ranges)
                })
        
        return alternatives
    
    def _get_car_price(self, car: Dict[str, Any]) -> Optional[float]:
        """Извлекает цену автомобиля"""
        price = car.get("price") or car.get("sale_price")
        if price:
            if isinstance(price, (int, float)):
                return float(price)
            elif isinstance(price, str):
                # Убираем пробелы и преобразуем
                price_clean = price.replace(" ", "").replace(",", ".")
                try:
                    return float(price_clean)
                except:
                    return None
        return None
    
    def _get_car_year(self, car: Dict[str, Any]) -> Optional[int]:
        """Извлекает год автомобиля"""
        year = car.get("manufacture_year") or car.get("model_year")
        if year:
            if isinstance(year, int):
                return year
            elif isinstance(year, str):
                try:
                    return int(year)
                except:
                    return None
        return None




