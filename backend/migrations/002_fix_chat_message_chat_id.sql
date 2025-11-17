-- Миграция: Исправление модели ChatMessage - убираем nullable с chat_id
-- Дата: 2025-11-16

-- Шаг 1: Создаем чаты для сообщений без chat_id (если такие есть)
INSERT INTO chats (user_id, title, created_at)
SELECT DISTINCT 
    cm.user_id, 
    'Миграция ' || cm.user_id || ' ' || TO_CHAR(NOW(), 'YYYY-MM-DD HH24:MI:SS'),
    NOW()
FROM chat_messages cm
WHERE cm.chat_id IS NULL
ON CONFLICT DO NOTHING;

-- Шаг 2: Обновляем chat_id для сообщений без чата
-- Связываем с последним чатом пользователя или создаем новый
UPDATE chat_messages cm
SET chat_id = (
    SELECT id 
    FROM chats c 
    WHERE c.user_id = cm.user_id 
    ORDER BY c.created_at DESC 
    LIMIT 1
)
WHERE cm.chat_id IS NULL;

-- Шаг 3: Если все еще есть сообщения без chat_id, создаем для них чаты
DO $$
DECLARE
    msg_record RECORD;
    new_chat_id INTEGER;
BEGIN
    FOR msg_record IN 
        SELECT DISTINCT user_id 
        FROM chat_messages 
        WHERE chat_id IS NULL
    LOOP
        -- Создаем новый чат
        INSERT INTO chats (user_id, title, created_at)
        VALUES (msg_record.user_id, 'Миграция ' || msg_record.user_id, NOW())
        RETURNING id INTO new_chat_id;
        
        -- Обновляем все сообщения этого пользователя
        UPDATE chat_messages
        SET chat_id = new_chat_id
        WHERE user_id = msg_record.user_id AND chat_id IS NULL;
    END LOOP;
END $$;

-- Шаг 4: Убираем nullable с chat_id
ALTER TABLE chat_messages 
ALTER COLUMN chat_id SET NOT NULL;

-- Комментарий
COMMENT ON COLUMN chat_messages.chat_id IS 'ID чата (обязательное поле, исправлено в миграции 002)';

