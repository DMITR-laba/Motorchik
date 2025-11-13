"""
Сервис для интеграции внешних знаний в ответы системы
"""
from typing import List, Dict, Any, Optional


class KnowledgeIntegratorService:
    """Интеграция доменных знаний в вопросы и ответы"""
    
    def __init__(self):
        # Доменные знания по категориям
        self.domain_knowledge = {
            "автомобили": {
                "keywords": ["автомобиль", "машина", "авто", "транспорт"],
                "suggestions": [
                    "Учитывайте расход топлива при выборе",
                    "Проверьте наличие сервисных центров в вашем городе",
                    "Рассмотрите программы гарантийного обслуживания"
                ]
            },
            "финансирование": {
                "keywords": ["кредит", "лизинг", "рассрочка", "финансирование", "платеж"],
                "suggestions": [
                    "Сравните предложения разных банков",
                    "Учитывайте страховку при расчете",
                    "Рассмотрите программы с минимальным первоначальным взносом"
                ]
            },
            "технические характеристики": {
                "keywords": ["мощность", "объем", "расход", "характеристики", "параметры"],
                "suggestions": [
                    "Мощность влияет на расход топлива",
                    "Объем двигателя определяет динамику",
                    "Учитывайте экологический класс"
                ]
            },
            "тест-драйв": {
                "keywords": ["тест-драйв", "пробная поездка", "прокат"],
                "suggestions": [
                    "Тест-драйв поможет оценить комфорт",
                    "Проверьте работу всех систем",
                    "Обратите внимание на шумоизоляцию"
                ]
            }
        }
    
    def enrich_with_knowledge(
        self,
        questions: List[str],
        topic: str,
        relation_type: str
    ) -> List[str]:
        """
        Обогащает вопросы доменными знаниями
        
        Args:
            questions: Список вопросов
            topic: Тема диалога
            relation_type: Тип связи с предыдущим диалогом
        
        Returns:
            Обогащенные вопросы
        """
        enriched_questions = questions.copy()
        
        # Определяем домен по теме
        domain = self._identify_domain(topic)
        
        if domain and domain in self.domain_knowledge:
            knowledge = self.domain_knowledge[domain]
            suggestions = knowledge.get("suggestions", [])
            
            # Добавляем предложения, если это новая тема или уточнение
            if relation_type in ["new_topic", "clarification"] and suggestions:
                # Добавляем одно предложение к вопросам
                if len(enriched_questions) < 3:
                    enriched_questions.append(suggestions[0])
        
        return enriched_questions
    
    def _identify_domain(self, topic: str) -> Optional[str]:
        """Определяет домен по теме"""
        topic_lower = topic.lower()
        
        for domain, knowledge in self.domain_knowledge.items():
            keywords = knowledge.get("keywords", [])
            if any(keyword in topic_lower for keyword in keywords):
                return domain
        
        return None
    
    def get_domain_suggestions(self, topic: str) -> List[str]:
        """Получает предложения для домена"""
        domain = self._identify_domain(topic)
        
        if domain and domain in self.domain_knowledge:
            return self.domain_knowledge[domain].get("suggestions", [])
        
        return []
    
    def enrich_response_with_knowledge(
        self,
        response: str,
        topic: str,
        search_results: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Обогащает ответ доменными знаниями
        
        Args:
            response: Базовый ответ
            topic: Тема диалога
            search_results: Результаты поиска (опционально)
        
        Returns:
            Обогащенный ответ
        """
        domain = self._identify_domain(topic)
        
        if domain and domain in self.domain_knowledge:
            suggestions = self.domain_knowledge[domain].get("suggestions", [])
            
            if suggestions and search_results:
                # Добавляем одно предложение, если есть результаты
                enriched = f"{response}\n\n💡 {suggestions[0]}"
                return enriched
        
        return response



