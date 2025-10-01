-- Проверяем текущие данные в БД

-- 1. Смотрим что есть в таблице users
SELECT * FROM users;

-- 2. Смотрим структуру таблицы
SELECT column_name, data_type, is_nullable, column_default 
FROM information_schema.columns 
WHERE table_name = 'users' 
ORDER BY ordinal_position;

-- 3. Если нужно очистить таблицы (осторожно!)
-- TRUNCATE TABLE attendances CASCADE;
-- TRUNCATE TABLE users CASCADE;
