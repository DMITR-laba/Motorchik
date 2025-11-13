"""
Сервис для визуализации структуры диалога
"""
from typing import Dict, Any, List
from services.dialogue_history_service import DialogueHistoryService


class DialogueVisualizerService:
    """Визуализация и анализ структуры диалога"""
    
    def create_dialogue_map(
        self,
        history: DialogueHistoryService
    ) -> Dict[str, Any]:
        """
        Создает карту диалога с связями между темами
        
        Returns:
            Dict с картой диалога:
            - nodes: узлы (темы)
            - edges: связи между темами
            - timeline: таймлайн диалога
            - statistics: статистика
        """
        try:
            messages = history.get_all_messages()
            topics = history.get_already_covered_topics()
            
            # Создаем узлы (темы)
            nodes = []
            topic_counts = {}
            
            for msg in messages:
                topic = msg.get("topic")
                if topic:
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1
            
            for topic, count in topic_counts.items():
                nodes.append({
                    "id": topic,
                    "label": topic,
                    "count": count,
                    "size": count * 10  # Размер узла пропорционален количеству упоминаний
                })
            
            # Создаем связи между темами
            edges = []
            prev_topic = None
            
            for msg in messages:
                current_topic = msg.get("topic")
                if current_topic and prev_topic and current_topic != prev_topic:
                    # Ищем существующую связь
                    existing_edge = next(
                        (e for e in edges if e["source"] == prev_topic and e["target"] == current_topic),
                        None
                    )
                    
                    if existing_edge:
                        existing_edge["weight"] += 1
                    else:
                        edges.append({
                            "source": prev_topic,
                            "target": current_topic,
                            "weight": 1
                        })
                
                if current_topic:
                    prev_topic = current_topic
            
            # Создаем таймлайн
            timeline = []
            for i, msg in enumerate(messages):
                timeline.append({
                    "index": i,
                    "timestamp": msg.get("timestamp", 0),
                    "role": msg.get("role", "unknown"),
                    "topic": msg.get("topic", "unknown"),
                    "content_preview": str(msg.get("content", ""))[:50]
                })
            
            # Статистика
            statistics = {
                "total_messages": len(messages),
                "total_topics": len(topic_counts),
                "most_discussed_topic": max(topic_counts.items(), key=lambda x: x[1])[0] if topic_counts else None,
                "avg_messages_per_topic": len(messages) / len(topic_counts) if topic_counts else 0,
                "topic_transitions": len(edges)
            }
            
            return {
                "nodes": nodes,
                "edges": edges,
                "timeline": timeline,
                "statistics": statistics
            }
            
        except Exception as e:
            print(f"⚠️ Ошибка создания карты диалога: {e}")
            return {
                "nodes": [],
                "edges": [],
                "timeline": [],
                "statistics": {},
                "error": str(e)
            }
    
    def analyze_topic_transitions(
        self,
        history: DialogueHistoryService
    ) -> List[Dict[str, Any]]:
        """Анализирует переходы между темами"""
        try:
            messages = history.get_all_messages()
            transitions = []
            
            prev_topic = None
            for msg in messages:
                current_topic = msg.get("topic")
                
                if current_topic and prev_topic and current_topic != prev_topic:
                    transitions.append({
                        "from": prev_topic,
                        "to": current_topic,
                        "timestamp": msg.get("timestamp", 0)
                    })
                
                if current_topic:
                    prev_topic = current_topic
            
            return transitions
            
        except Exception as e:
            print(f"⚠️ Ошибка анализа переходов: {e}")
            return []
    
    def get_key_moments(
        self,
        history: DialogueHistoryService
    ) -> List[Dict[str, Any]]:
        """Определяет ключевые моменты диалога"""
        try:
            messages = history.get_all_messages()
            key_moments = []
            
            # Ищем моменты смены темы
            prev_topic = None
            for i, msg in enumerate(messages):
                current_topic = msg.get("topic")
                
                if current_topic and current_topic != prev_topic:
                    key_moments.append({
                        "index": i,
                        "type": "topic_change",
                        "topic": current_topic,
                        "timestamp": msg.get("timestamp", 0),
                        "content_preview": str(msg.get("content", ""))[:100]
                    })
                
                # Ищем моменты с эмоциями
                emotion = msg.get("emotion")
                if emotion and emotion.get("urgency") == "high":
                    key_moments.append({
                        "index": i,
                        "type": "high_urgency",
                        "topic": current_topic,
                        "timestamp": msg.get("timestamp", 0),
                        "content_preview": str(msg.get("content", ""))[:100]
                    })
                
                if current_topic:
                    prev_topic = current_topic
            
            return key_moments
            
        except Exception as e:
            print(f"⚠️ Ошибка определения ключевых моментов: {e}")
            return []
    
    def print_conversation_analysis(self, assistant: Any):
        """Выводит анализ диалога в консоль (для отладки)"""
        try:
            # Получаем историю из ассистента
            if hasattr(assistant, 'history'):
                history = assistant.history
                
                dialogue_map = self.create_dialogue_map(history)
                transitions = self.analyze_topic_transitions(history)
                key_moments = self.get_key_moments(history)
                
                print("\n" + "="*60)
                print("АНАЛИЗ ДИАЛОГА")
                print("="*60)
                
                stats = dialogue_map.get("statistics", {})
                print(f"\n📊 Статистика:")
                print(f"  Всего сообщений: {stats.get('total_messages', 0)}")
                print(f"  Тем обсуждено: {stats.get('total_topics', 0)}")
                print(f"  Самая обсуждаемая тема: {stats.get('most_discussed_topic', 'Нет')}")
                print(f"  Переходов между темами: {stats.get('topic_transitions', 0)}")
                
                if transitions:
                    print(f"\n🔄 Переходы между темами:")
                    for trans in transitions[:5]:
                        print(f"  {trans['from']} → {trans['to']}")
                
                if key_moments:
                    print(f"\n⭐ Ключевые моменты:")
                    for moment in key_moments[:5]:
                        print(f"  [{moment['type']}] {moment.get('topic', 'Неизвестно')}: {moment['content_preview']}")
                
                print("="*60 + "\n")
                
        except Exception as e:
            print(f"⚠️ Ошибка вывода анализа: {e}")



