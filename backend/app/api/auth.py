from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import jwt, JWTError
import bcrypt
import hashlib

from models import get_db
from models.schemas import Token, User as UserSchema, UserCreate
from models.database import User
from services.database_service import DatabaseService
from app.core.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Временное решение для работы с SHA256
    if len(hashed_password) == 64:  # SHA256 hash
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password
    
    # Обрезаем пароль до 72 байт для bcrypt
    password_bytes = plain_password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
    except:
        return False


def get_password_hash(password: str) -> str:
    # Обрезаем пароль до 72 байт для bcrypt
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=60))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm="HS256")
    return encoded_jwt


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    db_service = DatabaseService(db)
    user = db_service.get_user_by_email(email)
    if user is None:
        raise credentials_exception
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


@router.post("/token", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        db_service = DatabaseService(db)
        user = db_service.get_user_by_email(form_data.username)
        
        if not user:
            logger.warning(f"Пользователь не найден: {form_data.username}")
            raise HTTPException(status_code=401, detail="Incorrect username or password")
        
        if not verify_password(form_data.password, user.hashed_password):
            logger.warning(f"Неверный пароль для пользователя: {form_data.username}")
            raise HTTPException(status_code=401, detail="Incorrect username or password")
        
        access_token = create_access_token({"sub": user.email, "role": user.role})
        logger.info(f"Успешный вход пользователя: {user.email}")
        return {"access_token": access_token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при входе: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/register", response_model=UserSchema)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    db_service = DatabaseService(db)
    if db_service.get_user_by_email(user_data.email):
        raise HTTPException(status_code=400, detail="User already exists")
    user = db_service.create_user(user_data, hashed_password=get_password_hash(user_data.password))
    return user


@router.post("/bootstrap-admin")
def bootstrap_admin(db: Session = Depends(get_db)):
    db_service = DatabaseService(db)
    if db_service.get_user_by_email("admin@example.com"):
        return {"message": "Admin already exists"}
    user_data = UserCreate(email="admin@example.com", full_name="Admin", password="admin", role="admin")
    user = db_service.create_user(user_data, hashed_password=get_password_hash(user_data.password), role="admin")
    return {"message": "Admin created", "email": user.email, "password": "admin"}


@router.get("/me", response_model=UserSchema)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Получить информацию о текущем пользователе"""
    return current_user


@router.get("/users", response_model=list[UserSchema])
def get_all_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Получить список всех пользователей (только для админов)"""
    db_service = DatabaseService(db)
    return db_service.get_all_users()


@router.post("/users", response_model=UserSchema)
def create_user(user_data: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Создать нового пользователя (только для админов)"""
    db_service = DatabaseService(db)
    if db_service.get_user_by_email(user_data.email):
        raise HTTPException(status_code=400, detail="User already exists")
    user = db_service.create_user(user_data, hashed_password=get_password_hash(user_data.password))
    return user


@router.put("/users/{user_id}", response_model=UserSchema)
def update_user(user_id: int, user_data: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Обновить пользователя (только для админов)"""
    db_service = DatabaseService(db)
    user = db_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Обновляем данные пользователя
    user.email = user_data.email
    user.full_name = user_data.full_name
    user.role = user_data.role
    if user_data.password:
        user.hashed_password = get_password_hash(user_data.password)
    
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Удалить пользователя (только для админов)"""
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    db_service = DatabaseService(db)
    user = db_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully"}





