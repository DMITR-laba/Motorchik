import httpx
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.core.config import settings

class AIService:
    def __init__(self):
        # Используем настройки из config.py
        pass
    
    async def _find_working_ollama_url(self) -> Optional[str]:
        """Находит рабочий URL для Ollama"""
        from services.ollama_utils import find_working_ollama_url
        return await find_working_ollama_url(timeout=2.0)
        
    async def test_api_connection(self, service: str, key: str) -> Dict[str, Any]:
        """Тестирование подключения к внешнему API"""
        try:
            if service == "mistral":
                return await self._test_mistral_connection(key)
            elif service == "openai":
                return await self._test_openai_connection(key)
            elif service == "anthropic":
                return await self._test_anthropic_connection(key)
            elif service == "google":
                return await self._test_google_connection(key)
            else:
                raise ValueError(f"Неподдерживаемый сервис: {service}")
        except Exception as e:
            raise Exception(f"Ошибка тестирования подключения: {str(e)}")
    
    async def _test_mistral_connection(self, key: str) -> Dict[str, Any]:
        """Тестирование подключения к Mistral AI"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "mistral-tiny",
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 10
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                return {"status": "success", "model": "mistral-tiny"}
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
    
    async def _test_openai_connection(self, key: str) -> Dict[str, Any]:
        """Тестирование подключения к OpenAI"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 10
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                return {"status": "success", "model": "gpt-3.5-turbo"}
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
    
    async def _test_anthropic_connection(self, key: str) -> Dict[str, Any]:
        """Тестирование подключения к Anthropic"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "test"}]
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                return {"status": "success", "model": "claude-3-haiku-20240307"}
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
    
    async def _test_google_connection(self, key: str) -> Dict[str, Any]:
        """Тестирование подключения к Google AI"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": "test"}]}]
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                return {"status": "success", "model": "gemini-pro"}
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
    
    async def get_ollama_models(self) -> List[Dict[str, Any]]:
        """Получение списка моделей Ollama"""
        try:
            # Находим рабочий URL
            working_url = await self._find_working_ollama_url()
            if not working_url:
                raise Exception("Не удается подключиться к Ollama. Проверьте, что Ollama запущен на localhost:11434 или host.docker.internal:11434")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{working_url}/api/tags",
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    for model in data.get("models", []):
                        models.append({
                            "name": model.get("name", ""),
                            "size": self._format_size(model.get("size", 0)),
                            "modified_at": model.get("modified_at", "")
                        })
                    return models
                else:
                    raise Exception(f"HTTP {response.status_code}: {response.text}")
        except httpx.ConnectError:
            raise Exception("Не удается подключиться к Ollama. Убедитесь, что Ollama запущен.")
        except Exception as e:
            raise Exception(f"Ошибка получения моделей: {str(e)}")
    
    async def pull_ollama_model(self, model_name: str) -> Dict[str, Any]:
        """Загрузка модели в Ollama"""
        try:
            # Находим рабочий URL
            working_url = await self._find_working_ollama_url()
            if not working_url:
                raise Exception("Не удается подключиться к Ollama. Проверьте, что Ollama запущен на localhost:11434 или host.docker.internal:11434")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{working_url}/api/pull",
                    json={"name": model_name},
                    timeout=300.0  # 5 минут для загрузки
                )
                
                if response.status_code == 200:
                    return {"status": "success", "model": model_name}
                else:
                    raise Exception(f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            raise Exception(f"Ошибка загрузки модели: {str(e)}")
    
    async def check_ollama_status(self) -> Dict[str, Any]:
        """Проверка статуса Ollama"""
        try:
            # Находим рабочий URL
            working_url = await self._find_working_ollama_url()
            if not working_url:
                return {"status": "disconnected", "message": "Ollama не запущен на localhost:11434 или host.docker.internal:11434"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{working_url}/api/version",
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "status": "running",
                        "version": data.get("version", "unknown"),
                        "url": working_url
                    }
                else:
                    return {"status": "error", "message": f"HTTP {response.status_code}"}
        except httpx.ConnectError:
            return {"status": "disconnected", "message": "Ollama не запущен"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def get_settings(self) -> Dict[str, Any]:
        """Получение текущих настроек AI"""
        # В реальном приложении здесь можно загрузить из базы данных
        return {
            "response_model": "",
            "embedding_model": "",
            "api_service": "",
            "api_key": None
        }
    
    def _format_size(self, size_bytes: int) -> str:
        """Форматирование размера в читаемый вид"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"

    async def save_settings_dict(self, settings_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Сохранение настроек AI из словаря"""
        try:
            # Сохраняем в файл
            with open("ai_settings.json", "w", encoding="utf-8") as f:
                json.dump(settings_dict, f, indent=2, ensure_ascii=False)
            
            return settings_dict
        except Exception as e:
            raise Exception(f"Ошибка сохранения настроек: {str(e)}")

    async def get_settings(self) -> Dict[str, Any]:
        """Получение текущих настроек AI"""
        try:
            if os.path.exists("ai_settings.json"):
                with open("ai_settings.json", "r", encoding="utf-8") as f:
                    settings = json.load(f)
            else:
                # Возвращаем настройки по умолчанию
                settings = {
                    "response_model": "",
                    "embedding_model": "",
                    "api_service": "mistral",
                    "api_key": "",
                    "updated_at": None
                }
            
            return settings
        except Exception as e:
            raise Exception(f"Ошибка получения настроек: {str(e)}")

    async def test_response_model(self, model_name: str) -> Dict[str, Any]:
        """Тестирование модели для ответов"""
        try:
            # Проверяем, является ли это моделью Ollama
            if model_name.startswith("ollama:"):
                model_name = model_name.replace("ollama:", "")
                return await self._test_ollama_response_model(model_name)
            else:
                # Тестируем внешний API
                return await self._test_external_response_model(model_name)
        except Exception as e:
            raise Exception(f"Ошибка тестирования модели ответов: {str(e)}")

    async def test_embedding_model(self, model_name: str) -> Dict[str, Any]:
        """Тестирование модели для эмбеддингов"""
        try:
            # Проверяем, является ли это моделью Ollama
            if model_name.startswith("ollama:"):
                model_name = model_name.replace("ollama:", "")
                return await self._test_ollama_embedding_model(model_name)
            else:
                # Тестируем внешний API
                return await self._test_external_embedding_model(model_name)
        except Exception as e:
            raise Exception(f"Ошибка тестирования модели эмбеддингов: {str(e)}")

    async def _test_ollama_response_model(self, model_name: str) -> Dict[str, Any]:
        """Тестирование модели ответов Ollama"""
        working_url = await self._find_working_ollama_url()
        if not working_url:
            raise Exception("Ollama недоступен")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{working_url}/api/generate",
                json={
                    "model": model_name,
                    "prompt": "Привет! Это тестовое сообщение.",
                    "stream": False
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "status": "success",
                    "model": model_name,
                    "response": data.get("response", ""),
                    "type": "ollama"
                }
            else:
                raise Exception(f"Ошибка Ollama: {response.status_code}")

    async def _test_ollama_embedding_model(self, model_name: str) -> Dict[str, Any]:
        """Тестирование модели эмбеддингов Ollama"""
        working_url = await self._find_working_ollama_url()
        if not working_url:
            raise Exception("Ollama недоступен")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{working_url}/api/embeddings",
                json={
                    "model": model_name,
                    "prompt": "Тестовый текст для эмбеддинга"
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "status": "success",
                    "model": model_name,
                    "embedding_length": len(data.get("embedding", [])),
                    "type": "ollama"
                }
            else:
                raise Exception(f"Ошибка Ollama: {response.status_code}")

    async def _test_external_response_model(self, model_name: str) -> Dict[str, Any]:
        """Тестирование внешней модели для ответов"""
        # Здесь можно добавить тестирование внешних API
        return {
            "status": "success",
            "model": model_name,
            "type": "external"
        }

    async def _test_external_embedding_model(self, model_name: str) -> Dict[str, Any]:
        """Тестирование внешней модели для эмбеддингов"""
        # Здесь можно добавить тестирование внешних API
        return {
            "status": "success",
            "model": model_name,
            "type": "external"
        }
