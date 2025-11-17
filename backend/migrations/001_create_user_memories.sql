-- Миграция: Создание таблицы user_memories для долговременной памяти пользователя
-- Дата: 2025-11-16

-- Убеждаемся, что расширение pgvector установлено
CREATE EXTENSION IF NOT EXISTS vector;

-- Создание таблицы user_memories
CREATE TABLE IF NOT EXISTS user_memories (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    memory_type VARCHAR(50) NOT NULL,  -- 'preference', 'rejection', 'interest', 'criteria'
    memory_text TEXT NOT NULL,          -- Человекочитаемое описание
    embedding vector(1024),            -- Векторное представление для семантического поиска
    memory_metadata TEXT,               -- JSON строка с метаданными
    confidence FLOAT DEFAULT 1.0,      -- Уверенность в извлеченной информации
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_user_memories_user_id ON user_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_user_memories_memory_type ON user_memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_user_memories_user_type ON user_memories(user_id, memory_type);

-- HNSW индекс для быстрого векторного поиска (pgvector)
CREATE INDEX IF NOT EXISTS idx_user_memories_semantic 
ON user_memories 
USING ivfflat (embedding vector_cosine_ops) 
WITH (lists = 100)
WHERE embedding IS NOT NULL;

-- Комментарии к таблице и полям
COMMENT ON TABLE user_memories IS 'Долговременная память пользователя: предпочтения, интересы, критерии поиска';
COMMENT ON COLUMN user_memories.memory_type IS 'Тип памяти: preference (предпочтения), rejection (отклонения), interest (интересы), criteria (критерии)';
COMMENT ON COLUMN user_memories.memory_text IS 'Человекочитаемое описание памяти для контекста';
COMMENT ON COLUMN user_memories.embedding IS 'Векторное представление (1024 измерения) для семантического поиска';
COMMENT ON COLUMN user_memories.memory_metadata IS 'JSON строка с структурированными данными (бренды, бюджет, критерии и т.д.)';
COMMENT ON COLUMN user_memories.confidence IS 'Уверенность в извлеченной информации (0.0 - 1.0)';

