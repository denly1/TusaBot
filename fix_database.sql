-- Исправление базы данных TusaBot
-- Приводим схему в соответствие с кодом

-- 1. Сначала проверим текущую структуру
SELECT column_name, data_type, is_nullable, column_default 
FROM information_schema.columns 
WHERE table_name = 'users' 
ORDER BY ordinal_position;

-- 2. Добавляем колонку age если её нет
ALTER TABLE users ADD COLUMN IF NOT EXISTS age INTEGER CHECK (age >= 14 AND age <= 100);

-- 3. Удаляем старую колонку birthdate
ALTER TABLE users DROP COLUMN IF EXISTS birthdate;

-- 4. Проверяем что все колонки на месте
SELECT column_name, data_type, is_nullable, column_default 
FROM information_schema.columns 
WHERE table_name = 'users' 
ORDER BY ordinal_position;

-- 5. Очищаем таблицу от старых данных (так как схема изменилась)
TRUNCATE TABLE users;

-- 6. Проверяем что таблица пустая
SELECT COUNT(*) FROM users;
