-- Создание базы данных largent для TusaBot
-- Выполните этот код в pgAdmin или psql

-- 1. Создание базы данных (выполнить от имени postgres)
CREATE DATABASE largent
    WITH 
    OWNER = postgres
    ENCODING = 'UTF8'
    LC_COLLATE = 'Russian_Russia.1251'
    LC_CTYPE = 'Russian_Russia.1251'
    TABLESPACE = pg_default
    CONNECTION LIMIT = -1;

-- 2. Подключитесь к базе largent и выполните следующие команды:

-- Создание таблицы пользователей
CREATE TABLE IF NOT EXISTS users (
    tg_id BIGINT PRIMARY KEY,                    -- Telegram ID пользователя
    name TEXT,                                   -- Имя пользователя
    gender TEXT CHECK (gender IN ('male', 'female')), -- Пол
    age INTEGER CHECK (age >= 16 AND age <= 100), -- Возраст пользователя
    vk_id TEXT,                                  -- VK ID (может быть id123456 или screen_name)
    registered_at TIMESTAMPTZ DEFAULT now(),     -- Время регистрации
    created_at TIMESTAMPTZ DEFAULT now(),        -- Время создания записи
    updated_at TIMESTAMPTZ DEFAULT now()         -- Время последнего обновления
);

-- Создание индексов для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_users_vk_id ON users(vk_id);
CREATE INDEX IF NOT EXISTS idx_users_registered_at ON users(registered_at);

-- Создание таблицы для афиш (опционально, для будущего расширения)
CREATE TABLE IF NOT EXISTS posters (
    id SERIAL PRIMARY KEY,
    file_id TEXT NOT NULL,                       -- Telegram file_id фото
    caption TEXT,                                -- Описание афиши
    ticket_url TEXT,                             -- Ссылка на билеты
    created_at TIMESTAMPTZ DEFAULT now(),        -- Время создания
    is_active BOOLEAN DEFAULT true               -- Активна ли афиша
);

-- Создание таблицы для отметок пользователей на мероприятиях
CREATE TABLE IF NOT EXISTS attendances (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(tg_id) ON DELETE CASCADE,
    poster_id INTEGER REFERENCES posters(id) ON DELETE CASCADE,
    attended_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, poster_id)                   -- Один пользователь может отметиться только раз на мероприятие
);

-- Создание функции для автоматического обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Создание триггера для автоматического обновления updated_at в таблице users
CREATE TRIGGER update_users_updated_at 
    BEFORE UPDATE ON users 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Вставка тестовых данных (опционально)
-- INSERT INTO users (tg_id, name, gender, birthdate, vk_id) VALUES 
-- (123456789, 'Тестовый пользователь', 'male', '1995-06-15', 'durov');

-- Просмотр структуры таблиц
-- \d users
-- \d posters
-- \d attendances

-- Полезные запросы для администрирования:

-- Количество зарегистрированных пользователей
-- SELECT COUNT(*) as total_users FROM users;

-- Пользователи с привязанным VK
-- SELECT COUNT(*) as users_with_vk FROM users WHERE vk_id IS NOT NULL;

-- Последние регистрации
-- SELECT tg_id, name, registered_at FROM users ORDER BY registered_at DESC LIMIT 10;

-- Очистка тестовых данных (осторожно!)
-- DELETE FROM attendances;
-- DELETE FROM posters;
-- DELETE FROM users WHERE tg_id = 123456789;
