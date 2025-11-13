"""
Сервис для обработки и форматирования результатов поиска
"""
from typing import Dict, Any, List, Optional
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType


class CarResultProcessorService:
    """Обработка и форматирование результатов поиска автомобилей"""
    
    def __init__(self):
        self.orchestrator = AIModelOrchestratorService()
    
    async def process_search_results(
        self,
        search_results: Dict[str, Any],
        user_query: str
    ) -> Dict[str, Any]:
        """
        Обрабатывает результаты поиска и создает сводку
        
        Args:
            search_results: Результаты поиска от IntelligentSearchService
            user_query: Исходный запрос пользователя
        
        Returns:
            Dict с обработанными результатами:
            - success: успешность поиска
            - results_summary: сводка результатов
                - summary: текстовое описание
                - top_recommendations: топ рекомендации
                - suggested_refinements: предложения по уточнению
                - next_questions: следующие вопросы
                - finance_options: информация о финансировании
            - raw_results: исходные результаты
            - total_found: общее количество найденных
        """
        try:
            hits = search_results.get("results", [])
            total = search_results.get("total", 0)
            relaxation_applied = search_results.get("relaxation_applied", False)
            recommendations = search_results.get("recommendations")
            
            # Генерируем сводку через LLM
            summary = await self._generate_summary(
                user_query=user_query,
                total=total,
                hits=hits[:5],  # Топ-5 для анализа
                relaxation_applied=relaxation_applied,
                recommendations=recommendations
            )
            
            # Выделяем лучшие варианты
            top_recommendations = self._select_top_recommendations(hits[:10])
            
            # Генерируем предложения по уточнению
            suggested_refinements = self._generate_refinements(
                user_query=user_query,
                total=total,
                hits=hits
            )
            
            # Генерируем следующие вопросы
            next_questions = await self._generate_next_questions(
                user_query=user_query,
                total=total,
                hits=hits
            )
            
            # Информация о финансировании
            finance_options = None
            if hits and total > 0:
                finance_options = self._extract_finance_info(hits[:3])
            
            return {
                "success": total > 0,
                "results_summary": {
                    "summary": summary,
                    "top_recommendations": top_recommendations,
                    "suggested_refinements": suggested_refinements,
                    "next_questions": next_questions,
                    "finance_options": finance_options
                },
                "raw_results": hits,
                "total_found": total,
                "relaxation_applied": relaxation_applied
            }
            
        except Exception as e:
            print(f"⚠️ Ошибка обработки результатов: {e}")
            return {
                "success": False,
                "results_summary": {
                    "summary": "Произошла ошибка при обработке результатов",
                    "top_recommendations": [],
                    "suggested_refinements": [],
                    "next_questions": [],
                    "finance_options": None
                },
                "raw_results": [],
                "total_found": 0,
                "error": str(e)
            }
    
    async def _generate_summary(
        self,
        user_query: str,
        total: int,
        hits: List[Dict],
        relaxation_applied: bool,
        recommendations: Optional[Dict]
    ) -> str:
        """Генерирует текстовую сводку результатов"""
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.RESULT_PROCESSING
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            
            # Формируем информацию о найденных автомобилях
            cars_info = []
            for i, hit in enumerate(hits[:5], 1):
                source = hit.get("_source", {})
                mark = source.get("mark", "Неизвестно")
                model = source.get("model", "")
                price = source.get("price") or source.get("sale_price", "Не указана")
                year = source.get("manufacture_year") or source.get("model_year", "")
                cars_info.append(f"{i}. {mark} {model} {year} года - {price} руб.")
            
            prompt = f"""Создай краткую сводку результатов поиска автомобилей для клиента.

ЗАПРОС КЛИЕНТА: {user_query}
НАЙДЕНО АВТОМОБИЛЕЙ: {total}
ОСЛАБЛЕНИЕ ФИЛЬТРОВ: {"Да" if relaxation_applied else "Нет"}

НАЙДЕННЫЕ АВТОМОБИЛИ:
{chr(10).join(cars_info) if cars_info else "Не найдено"}

Создай краткую сводку (2-3 предложения), которая:
1. Информирует о количестве найденных вариантов
2. Упоминает, если применялось ослабление фильтров
3. Дает общее представление о найденных автомобилях

Сводка:"""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты создаешь сводки результатов поиска для клиентов автосалона."),
                ("human", prompt)
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            summary = await chain.ainvoke({})
            
            return summary.strip()
            
        except Exception as e:
            print(f"⚠️ Ошибка генерации сводки: {e}")
            if total > 0:
                return f"Найдено {total} автомобилей, соответствующих вашему запросу."
            else:
                return "По вашим критериям не найдено автомобилей."
    
    def _select_top_recommendations(self, hits: List[Dict]) -> List[Dict[str, Any]]:
        """Выделяет лучшие варианты из результатов"""
        top = []
        
        for hit in hits[:5]:  # Топ-5
            source = hit.get("_source", {})
            top.append({
                "id": source.get("id"),
                "mark": source.get("mark"),
                "model": source.get("model"),
                "price": source.get("price") or source.get("sale_price"),
                "year": source.get("manufacture_year") or source.get("model_year"),
                "body_type": source.get("body_type") or source.get("category"),
                "fuel_type": source.get("fuel_type"),
                "score": hit.get("_score", 0)
            })
        
        return top
    
    def _generate_refinements(
        self,
        user_query: str,
        total: int,
        hits: List[Dict]
    ) -> List[str]:
        """Генерирует предложения по уточнению поиска"""
        refinements = []
        
        if total == 0:
            refinements.append("Попробуйте расширить критерии поиска (увеличить бюджет, изменить марку)")
            refinements.append("Рассмотрите другие категории автомобилей")
        elif total > 20:
            refinements.append("Уточните критерии поиска для более точных результатов")
            refinements.append("Добавьте фильтры по году, типу топлива или другим параметрам")
        else:
            refinements.append("Результаты соответствуют вашим критериям")
        
        return refinements
    
    async def _generate_next_questions(
        self,
        user_query: str,
        total: int,
        hits: List[Dict]
    ) -> List[str]:
        """Генерирует следующие вопросы для уточнения"""
        try:
            if total == 0:
                return [
                    "Какой бюджет вы рассматриваете?",
                    "Какая марка вас интересует?",
                    "Новые или подержанные автомобили?"
                ]
            elif total > 10:
                return [
                    "Хотите уточнить критерии поиска?",
                    "Какие характеристики наиболее важны для вас?"
                ]
            else:
                return [
                    "Хотите узнать подробнее о каком-то автомобиле?",
                    "Интересует ли вас финансирование?"
                ]
        except Exception:
            return []
    
    def _extract_finance_info(self, hits: List[Dict]) -> Dict[str, Any]:
        """Извлекает информацию о финансировании из результатов"""
        if not hits:
            return None
        
        # Берем первый автомобиль для примера
        first_car = hits[0]
        source = first_car.get("_source", {})
        price = source.get("price") or source.get("sale_price")
        
        if price:
            try:
                if isinstance(price, str):
                    price_clean = price.replace(" ", "").replace(",", ".").replace("₽", "")
                    price_value = float(price_clean)
                else:
                    price_value = float(price)
                
                return {
                    "car_price": price_value,
                    "suggested_down_payment": price_value * 0.2,  # 20%
                    "suggested_loan_term": 60,  # 5 лет
                    "message": "Доступны программы кредитования и лизинга"
                }
            except Exception:
                pass
        
        return None



