-- Добавление колонки username для хранения Telegram username
-- Выполните в базе данных largent

-- 1. Добавляем колонку username
ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;

-- 2. Создаем индекс для быстрого поиска по username
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- 3. Проверяем структуру таблицы
SELECT column_name, data_type, is_nullable, column_default 
FROM information_schema.columns 
WHERE table_name = 'users' 
ORDER BY ordinal_position;

-- 4. Проверяем текущие данные
SELECT tg_id, name, username, vk_id FROM users LIMIT 10;
