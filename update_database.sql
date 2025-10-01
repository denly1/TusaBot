
фффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффффф
-- 1. Добавляем новую колонку age
ALTER TABLE users ADD COLUMN IF NOT EXISTS age INTEGER CHECK (age >= 16 AND age <= 100);

-- 2. Если у вас есть данные с birthdate, можно попробовать конвертировать их в возраст
-- (раскомментируйте следующие строки если нужно)
-- UPDATE users 
-- SET age = EXTRACT(YEAR FROM AGE(CURRENT_DATE, birthdate))
-- WHERE birthdate IS NOT NULL AND age IS NULL;

-- 3. Удаляем старую колонку birthdate (осторожно! данные будут потеряны)
ALTER TABLE users DROP COLUMN IF EXISTS birthdate;

-- 4. Добавляем недостающие колонки если их нет
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- 5. Создаем функцию для автоматического обновления updated_at (если её нет)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 6. Создаем триггер для автоматического обновления updated_at в таблице users
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at 
    BEFORE UPDATE ON users 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- 7. Проверяем структуру таблицы
SELECT column_name, data_type, is_nullable, column_default 
FROM information_schema.columns 
WHERE table_name = 'users' 
ORDER BY ordinal_position;
