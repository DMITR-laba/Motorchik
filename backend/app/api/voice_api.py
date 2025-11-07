from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from models import get_db
from models.schemas import VoiceSettingsResponse, VoiceSettingsRequest, VoiceTranscribeResponse
import json
import os
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# Путь к файлу настроек (можно хранить в БД или файле)
VOICE_SETTINGS_FILE = Path("voice_settings.json")

def _load_voice_settings() -> dict:
    """Загрузка настроек голосового ввода"""
    default_settings = {
        "enabled": False,
        "model": "base",
        "autoDetectLanguage": True,
        "language": "ru",
        "silenceThreshold": 500,
        "minSpeechDuration": 1.0
    }
    
    if VOICE_SETTINGS_FILE.exists():
        try:
            with open(VOICE_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                return {**default_settings, **settings}
        except Exception as e:
            logger.error(f"Ошибка загрузки настроек: {e}")
    
    return default_settings

def _save_voice_settings(settings: dict):
    """Сохранение настроек голосового ввода"""
    try:
        with open(VOICE_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сохранения настроек")

@router.get("/settings", response_model=VoiceSettingsResponse)
async def get_voice_settings():
    """Получение настроек голосового ввода"""
    settings = _load_voice_settings()
    return VoiceSettingsResponse(**settings)

@router.post("/settings", response_model=VoiceSettingsResponse)
async def update_voice_settings(request: VoiceSettingsRequest):
    """Обновление настроек голосового ввода"""
    settings_dict = request.dict(exclude_none=True)
    _save_voice_settings(settings_dict)
    return VoiceSettingsResponse(**settings_dict)

@router.post("/transcribe", response_model=VoiceTranscribeResponse)
async def transcribe_audio(
    audio: UploadFile = File(...),
    model: Optional[str] = Form("base"),
    language: Optional[str] = Form(None)
):
    """
    Транскрибация аудио с помощью Whisper
    
    Args:
        audio: Аудио файл (webm, wav, mp3 и т.д.)
        model: Модель Whisper (tiny, base, small, medium, large)
        language: Язык (ru, en и т.д.) или None для автоопределения
    """
    try:
        # Импортируем whisper только при использовании
        try:
            import whisper
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="Whisper не установлен. Установите: pip install openai-whisper"
            )
        
        # Сохраняем временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{audio.filename.split('.')[-1] if audio.filename else 'webm'}") as tmp_file:
            content = await audio.read()
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            # Загружаем модель Whisper
            logger.info(f"Загрузка модели Whisper: {model}")
            whisper_model = whisper.load_model(model)
            
            # Транскрибируем аудио
            logger.info(f"Транскрибация аудио (язык: {language or 'авто'})")
            result = whisper_model.transcribe(
                tmp_file_path,
                language=language if language else None,
                task="transcribe"
            )
            
            # Получаем результат
            text = result.get("text", "").strip()
            detected_language = result.get("language", language or "unknown")
            
            logger.info(f"Распознано: {text[:50]}... (язык: {detected_language})")
            
            return VoiceTranscribeResponse(
                text=text,
                language=detected_language,
                confidence=result.get("no_speech_prob", 0)  # Используем вероятность отсутствия речи как индикатор
            )
            
        finally:
            # Удаляем временный файл
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)
                
    except Exception as e:
        logger.error(f"Ошибка транскрибации: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка распознавания речи: {str(e)}")



