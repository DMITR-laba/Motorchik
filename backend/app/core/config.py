from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    postgres_db: str = "vectordb"
    postgres_user: str = "postgres"
    postgres_password: str = "password"
    postgres_host: str = "postgres"  # Изменено для Docker
    postgres_port: int = 5432
    
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "your-secret-key-here"
    debug: bool = True
    
    # OpenAI
    openai_api_key: str = "your-openai-api-key-here"
    openai_model: str = "gpt-4-turbo"
    
    # ChromaDB
    chroma_host: str = "localhost"  # не используется в embedded
    chroma_port: int = 8001          # не используется в embedded
    chroma_persist_dir: str = "./chroma"
    
    # Keycloak
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "your-realm"
    keycloak_client_id: str = "your-client-id"
    keycloak_client_secret: str = "your-client-secret"

    # Ollama (фолбэк/локальная генерация)
    # Примечание: ollama_host должен быть БЕЗ http:// (протокол добавляется автоматически)
    ollama_host: str = "host.docker.internal"
    ollama_port: int = 11434
    ollama_model: str = "llama3:8b"

    # Mistral (облачная генерация и эмбеддинги)
    mistral_api_key: str = "i9cUCrVRnlRD7jxu3aM5NTg2wJCQ8TCn"
    mistral_model: str = "mistral-large-latest"
    mistral_base_url: str = "https://api.mistral.ai"
    mistral_embed_model: str = "mistral-embed"

    # Прямой URL БД (для локального запуска без Postgres можно указать sqlite)
    database_url_env: Optional[str] = None

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    
    @property
    def database_url(self) -> str:
        if self.database_url_env:
            return self.database_url_env
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"
    
    class Config:
        env_file = ".env"


settings = Settings()
