from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from models import get_db
from models.schemas import (
    Document, DocumentCreate, DocumentUpdate, DocumentListResponse, 
    DocumentUploadResponse, Category, Tag
)
from services.document_service import DocumentService
from services.database_service import DatabaseService
from app.api.auth import require_admin
import uuid
import os

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("/", response_model=DocumentListResponse)
async def get_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Получает список документов с пагинацией и поиском"""
    doc_service = DocumentService(db)
    documents, total = doc_service.get_documents(skip=skip, limit=limit, search=search)
    
    return DocumentListResponse(
        documents=documents,
        total=total,
        page=1,
        size=limit
    )


@router.get("/{document_id}", response_model=Document)
async def get_document(
    document_id: int, 
    db: Session = Depends(get_db), 
    _: object = Depends(require_admin)
):
    """Получает документ по ID"""
    doc_service = DocumentService(db)
    document = doc_service.get_document(document_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    return document


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    language: str = Form("ru"),
    path: str = Form(""),  # Путь к файлу
    category_ids: str = Form("[]"),  # JSON строка
    tag_names: str = Form("[]"),     # JSON строка
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Загружает и обрабатывает документ"""
    
    # Проверяем тип файла
    allowed_types = ['pdf', 'doc', 'docx', 'txt']
    file_extension = file.filename.split('.')[-1].lower() if '.' in file.filename else ''
    
    if file_extension not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Неподдерживаемый тип файла. Разрешены: {', '.join(allowed_types)}"
        )
    
    # Проверяем размер файла (максимум 50MB)
    file_content = await file.read()
    if len(file_content) > 50 * 1024 * 1024:  # 50MB
        raise HTTPException(status_code=400, detail="Файл слишком большой. Максимум 50MB")
    
    try:
        # Парсим JSON параметры
        import json
        try:
            category_ids_list = json.loads(category_ids) if category_ids != "[]" else []
            tag_names_list = json.loads(tag_names) if tag_names != "[]" else []
        except json.JSONDecodeError:
            category_ids_list = []
            tag_names_list = []
        
        # Создаем объект DocumentCreate
        document_data = DocumentCreate(
            original_filename=file.filename,
            file_type=file_extension,
            language=language,
            path=path if path else None,
            category_ids=category_ids_list,
            tag_names=tag_names_list
        )
        
        # Создаем документ
        doc_service = DocumentService(db)
        document = doc_service.create_document(document_data, file_content)
        
        # Запускаем обработку в фоне (можно сделать асинхронно)
        try:
            success = doc_service.process_document(document.id)
            if not success:
                return DocumentUploadResponse(
                    document_id=document.id,
                    message="Документ загружен, но обработка завершилась с ошибкой",
                    processing_status="failed"
                )
        except Exception as e:
            return DocumentUploadResponse(
                document_id=document.id,
                message=f"Документ загружен, но обработка завершилась с ошибкой: {str(e)}",
                processing_status="failed"
            )
        
        return DocumentUploadResponse(
            document_id=document.id,
            message="Документ успешно загружен и обработан",
            processing_status="completed"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при загрузке документа: {str(e)}")


@router.put("/{document_id}", response_model=Document)
async def update_document(
    document_id: int,
    document_data: DocumentUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Обновляет документ"""
    doc_service = DocumentService(db)
    document = doc_service.update_document(document_id, document_data)
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    return document


@router.delete("/{document_id}")
async def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Удаляет документ"""
    doc_service = DocumentService(db)
    success = doc_service.delete_document(document_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    return {"message": "Документ удален"}


@router.post("/{document_id}/process")
async def process_document(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Перезапускает обработку документа"""
    doc_service = DocumentService(db)
    document = doc_service.get_document(document_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    success = doc_service.process_document(document_id)
    
    if success:
        return {"message": "Обработка документа запущена"}
    else:
        raise HTTPException(status_code=500, detail="Ошибка при обработке документа")


@router.get("/{document_id}/download")
async def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Скачивает оригинальный файл документа"""
    doc_service = DocumentService(db)
    document = doc_service.get_document(document_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    if not document.file_content:
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    from fastapi.responses import Response
    
    return Response(
        content=document.file_content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename={document.original_filename}"
        }
    )


@router.get("/{document_id}/text")
async def get_document_text(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Получает извлеченный текст документа"""
    doc_service = DocumentService(db)
    document = doc_service.get_document(document_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    return {
        "document_id": document.id,
        "title": document.title,
        "extracted_text": document.extracted_text,
        "topic": document.topic,
        "summary": document.summary,
        "processing_status": document.processing_status,
        "path": document.path
    }


@router.post("/batch-process")
async def batch_process_documents(
    document_ids: List[int],
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Обрабатывает несколько документов"""
    doc_service = DocumentService(db)
    results = []
    
    for doc_id in document_ids:
        try:
            success = doc_service.process_document(doc_id)
            results.append({
                "document_id": doc_id,
                "success": success,
                "message": "Обработан успешно" if success else "Ошибка обработки"
            })
        except Exception as e:
            results.append({
                "document_id": doc_id,
                "success": False,
                "message": f"Ошибка: {str(e)}"
            })
    
    return {
        "message": f"Обработано {len(document_ids)} документов",
        "results": results
    }


@router.post("/{document_id}/generate-categories")
async def generate_categories(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Генерирует категории для документа с помощью ИИ"""
    doc_service = DocumentService(db)
    document = doc_service.get_document(document_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    if not document.extracted_text:
        raise HTTPException(status_code=400, detail="Документ не содержит извлеченный текст")
    
    try:
        # Генерируем категории
        categories = doc_service._generate_categories(document.extracted_text, document.title or "")
        
        if categories:
            # Очищаем старые категории и добавляем новые
            document.categories.clear()
            for category_name in categories:
                from models.database import Category
                category = db.query(Category).filter(Category.name == category_name).first()
                if not category:
                    category = Category(name=category_name)
                    db.add(category)
                    db.flush()
                document.categories.append(category)
            
            db.commit()
            return {
                "success": True,
                "message": f"Сгенерировано {len(categories)} категорий",
                "categories": categories
            }
        else:
            return {
                "success": False,
                "message": "Не удалось сгенерировать категории"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации категорий: {str(e)}")


@router.post("/{document_id}/generate-tags")
async def generate_tags(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Генерирует теги для документа с помощью ИИ"""
    doc_service = DocumentService(db)
    document = doc_service.get_document(document_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    if not document.extracted_text:
        raise HTTPException(status_code=400, detail="Документ не содержит извлеченный текст")
    
    try:
        # Генерируем теги
        tags = doc_service._generate_tags(document.extracted_text, document.title or "")
        
        if tags:
            # Очищаем старые теги и добавляем новые
            document.tags.clear()
            for tag_name in tags:
                from models.database import Tag
                tag = db.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    db.flush()
                document.tags.append(tag)
            
            db.commit()
            return {
                "success": True,
                "message": f"Сгенерировано {len(tags)} тегов",
                "tags": tags
            }
        else:
            return {
                "success": False,
                "message": "Не удалось сгенерировать теги"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации тегов: {str(e)}")


@router.post("/{document_id}/generate-meta")
async def generate_meta(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Генерирует все метаданные для документа (категории, теги, тему, резюме)"""
    doc_service = DocumentService(db)
    document = doc_service.get_document(document_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    if not document.extracted_text:
        raise HTTPException(status_code=400, detail="Документ не содержит извлеченный текст")
    
    try:
        # Генерируем все метаданные
        categories = doc_service._generate_categories(document.extracted_text, document.title or "")
        tags = doc_service._generate_tags(document.extracted_text, document.title or "")
        topic = doc_service._generate_topic(document.extracted_text)
        summary = doc_service._generate_summary(document.extracted_text)
        
        # Обновляем документ
        if topic:
            document.topic = topic
        if summary:
            document.summary = summary
        
        # Обновляем категории
        if categories:
            document.categories.clear()
            for category_name in categories:
                from models.database import Category
                category = db.query(Category).filter(Category.name == category_name).first()
                if not category:
                    category = Category(name=category_name)
                    db.add(category)
                    db.flush()
                document.categories.append(category)
        
        # Обновляем теги
        if tags:
            document.tags.clear()
            for tag_name in tags:
                from models.database import Tag
                tag = db.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    db.flush()
                document.tags.append(tag)
        
        db.commit()
        
        return {
            "success": True,
            "message": "Все метаданные успешно сгенерированы",
            "categories": categories,
            "tags": tags,
            "topic": topic,
            "summary": summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации метаданных: {str(e)}")
