"""
Сервис для анализа эмоциональной окраски запросов
"""
from typing import Dict, Any, List
from services.ai_model_orchestrator_service import AIModelOrchestratorService, TaskType


class EmotionAnalyzerService:
    """Анализ эмоций и адаптация тона общения"""
    
    def __init__(self):
        self.orchestrator = AIModelOrchestratorService()
    
    async def analyze_emotion(self, query: str) -> Dict[str, Any]:
        """
        Анализирует эмоциональную окраску запроса
        
        Returns:
            Dict с ключами:
            - sentiment: "positive", "negative", "neutral"
            - urgency: "low", "medium", "high"
            - emotion: "happy", "frustrated", "curious", "anxious", "neutral"
            - confidence: float (0.0-1.0)
        """
        try:
            llm = await self.orchestrator.get_llm_for_task_async(
                task_type=TaskType.EMOTION_ANALYSIS
            )
            
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            import json
            
            prompt = f"""Проанализируй эмоциональную окраску следующего запроса пользователя автосалона.

ЗАПРОС: {query}

Определи:
1. Тональность (sentiment): "positive", "negative", "neutral"
2. Уровень срочности (urgency): "low", "medium", "high"
3. Эмоциональное состояние (emotion): "happy", "frustrated", "curious", "anxious", "neutral"
4. Уверенность в оценке (confidence): число от 0.0 до 1.0

Ответ в формате JSON:
{{
    "sentiment": "positive|negative|neutral",
    "urgency": "low|medium|high",
    "emotion": "happy|frustrated|curious|anxious|neutral",
    "confidence": 0.85
}}

ВАЖНО: Используй двойные фигурные скобки {{}} для JSON структуры в ответе."""
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", "Ты анализируешь эмоции пользователя. Возвращаешь JSON с анализом."),
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
                    return {
                        "sentiment": result.get("sentiment", "neutral"),
                        "urgency": result.get("urgency", "medium"),
                        "emotion": result.get("emotion", "neutral"),
                        "confidence": float(result.get("confidence", 0.5))
                    }
            except Exception as e:
                print(f"⚠️ Ошибка парсинга ответа анализатора эмоций: {e}")
            
            # Fallback - простая эвристика
            return self._simple_emotion_analysis(query)
            
        except Exception as e:
            print(f"⚠️ Ошибка анализа эмоций: {e}")
            return self._simple_emotion_analysis(query)
    
    def _simple_emotion_analysis(self, query: str) -> Dict[str, Any]:
        """Простой анализ эмоций без LLM"""
        query_lower = query.lower()
        
        # Определяем тональность
        positive_words = ["хорошо", "отлично", "нравится", "интересно", "спасибо", "благодарю"]
        negative_words = ["плохо", "не нравится", "не подходит", "разочарован", "проблема", "ошибка"]
        
        sentiment = "neutral"
        if any(word in query_lower for word in positive_words):
            sentiment = "positive"
        elif any(word in query_lower for word in negative_words):
            sentiment = "negative"
        
        # Определяем срочность
        urgency_words_high = ["срочно", "быстро", "немедленно", "как можно скорее", "сегодня"]
        urgency_words_medium = ["скоро", "в ближайшее время", "в течение недели"]
        
        urgency = "low"
        if any(word in query_lower for word in urgency_words_high):
            urgency = "high"
        elif any(word in query_lower for word in urgency_words_medium):
            urgency = "medium"
        
        # Определяем эмоцию
        emotion = "neutral"
        if sentiment == "positive":
            emotion = "happy"
        elif sentiment == "negative":
            emotion = "frustrated"
        elif any(word in query_lower for word in ["интересно", "хочу узнать", "расскажи"]):
            emotion = "curious"
        elif any(word in query_lower for word in ["беспокоюсь", "волнуюсь", "не уверен"]):
            emotion = "anxious"
        
        return {
            "sentiment": sentiment,
            "urgency": urgency,
            "emotion": emotion,
            "confidence": 0.6
        }
    
    def adjust_tone_for_questions(
        self,
        questions: List[str],
        emotion_data: Dict,
        question_style: str = "neutral"
    ) -> List[str]:
        """
        Адаптирует тон вопросов под эмоциональный контекст
        
        Args:
            questions: Список вопросов
            emotion_data: Данные об эмоциях
            question_style: "neutral", "friendly", "professional", "empathetic"
        
        Returns:
            Список адаптированных вопросов
        """
        sentiment = emotion_data.get("sentiment", "neutral")
        urgency = emotion_data.get("urgency", "medium")
        emotion = emotion_data.get("emotion", "neutral")
        
        adjusted_questions = []
        
        for question in questions:
            adjusted = question
            
            # Адаптация под тональность
            if sentiment == "negative" or emotion == "frustrated":
                # Добавляем эмпатичные фразы
                if not any(word in adjusted.lower() for word in ["понимаю", "давайте", "помогу"]):
                    adjusted = f"Понимаю вашу ситуацию. {adjusted}"
            
            # Адаптация под срочность
            if urgency == "high":
                # Добавляем маркер срочности
                if "срочно" not in adjusted.lower():
                    adjusted = f"Срочно: {adjusted}"
            
            # Адаптация под стиль
            if question_style == "friendly":
                # Делаем более дружелюбным
                if not adjusted.startswith(("Привет", "Здравствуйте", "Добрый")):
                    adjusted = f"Давайте уточним: {adjusted}"
            elif question_style == "professional":
                # Делаем более профессиональным
                if not any(word in adjusted.lower() for word in ["пожалуйста", "уточните"]):
                    adjusted = f"Пожалуйста, уточните: {adjusted}"
            elif question_style == "empathetic":
                # Делаем более эмпатичным
                if sentiment == "negative":
                    adjusted = f"Я понимаю, что это важно для вас. {adjusted}"
            
            adjusted_questions.append(adjusted)
        
        return adjusted_questions


