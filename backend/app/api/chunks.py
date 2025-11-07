from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from models import get_db
from models.schemas import DocumentChunk, DocumentChunkListResponse
from services.document_service import DocumentService
from app.api.auth import require_admin

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


@router.get("/document/{document_id}", response_model=DocumentChunkListResponse)
async def get_document_chunks(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Получает чанки документа"""
    doc_service = DocumentService(db)
    chunks = doc_service.get_document_chunks(document_id)
    
    return {
        "chunks": chunks,
        "total": len(chunks)
    }


@router.post("/document/{document_id}/create")
async def create_document_chunks(
    document_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Создает чанки для документа"""
    doc_service = DocumentService(db)
    chunks = doc_service.create_document_chunks(document_id)
    
    return {
        "message": f"Создано {len(chunks)} чанков",
        "chunks_count": len(chunks)
    }


@router.get("/search")
async def search_chunks(
    query: str,
    limit: int = 10,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin)
):
    """Поиск по чанкам документов"""
    doc_service = DocumentService(db)
    chunks = doc_service.search_document_chunks(query, limit)
    
    return {
        "chunks": chunks,
        "total": len(chunks),
        "query": query
    }







