# Настройка PostgreSQL через pgAdmin для TusaBot

## 1. Подключение к серверу в pgAdmin

1. Откройте pgAdmin
2. Щелкните правой кнопкой на "Servers" → "Register" → "Server"
3. Заполните данные:

**Вкладка General:**
- Name: `TusaBot Local`

**Вкладка Connection:**
- Host name/address: `127.0.0.1`
- Port: `5432`
- Maintenance database: `postgres`
- Username: `postgres`
- Password: `1`

4. Нажмите "Save"

## 2. Создание базы данных

### Способ 1: Через интерфейс pgAdmin
1. Подключитесь к серверу
2. Щелкните правой кнопкой на "Databases" → "Create" → "Database"
3. Заполните:
   - Database: `largent`
   - Owner: `postgres`
4. Нажмите "Save"

### Способ 2: Через SQL (рекомендуется)
1. Подключитесь к базе `postgres`
2. Откройте Query Tool (Tools → Query Tool)
3. Выполните SQL из файла `database_setup.sql`

## 3. Создание таблиц

1. Подключитесь к созданной базе `largent`
2. Откройте Query Tool
3. Выполните SQL код создания таблиц из `database_setup.sql`

## 4. Проверка подключения

Выполните тестовый запрос:
```sql
SELECT current_database(), current_user, version();
```

## 5. Настройка прав доступа (если нужно)

```sql
-- Предоставить все права пользователю postgres на базу largent
GRANT ALL PRIVILEGES ON DATABASE largent TO postgres;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;
```

## 6. Полезные запросы для мониторинга

```sql
-- Просмотр всех пользователей бота
SELECT tg_id, name, gender, birthdate, vk_id, registered_at 
FROM users 
ORDER BY registered_at DESC;

-- Статистика по пользователям
SELECT 
    COUNT(*) as total_users,
    COUNT(vk_id) as users_with_vk,
    COUNT(CASE WHEN gender = 'male' THEN 1 END) as male_users,
    COUNT(CASE WHEN gender = 'female' THEN 1 END) as female_users
FROM users;

-- Активность по дням
SELECT 
    DATE(registered_at) as registration_date,
    COUNT(*) as new_users
FROM users 
GROUP BY DATE(registered_at)
ORDER BY registration_date DESC;
```

## Структура базы данных

### Таблица `users`
- `tg_id` (BIGINT, PRIMARY KEY) - Telegram ID
- `name` (TEXT) - Имя пользователя
- `gender` (TEXT) - Пол (male/female/other)
- `birthdate` (DATE) - Дата рождения
- `vk_id` (TEXT) - VK ID или screen name
- `registered_at` (TIMESTAMPTZ) - Время регистрации
- `created_at` (TIMESTAMPTZ) - Время создания записи
- `updated_at` (TIMESTAMPTZ) - Время последнего обновления

### Таблица `posters` (для будущего расширения)
- `id` (SERIAL, PRIMARY KEY) - Уникальный ID афиши
- `file_id` (TEXT) - Telegram file_id фото
- `caption` (TEXT) - Описание афиши
- `ticket_url` (TEXT) - Ссылка на билеты
- `created_at` (TIMESTAMPTZ) - Время создания
- `is_active` (BOOLEAN) - Активна ли афиша

### Таблица `attendances` (для отметок на мероприятиях)
- `id` (SERIAL, PRIMARY KEY) - Уникальный ID отметки
- `user_id` (BIGINT) - Ссылка на пользователя
- `poster_id` (INTEGER) - Ссылка на афишу
- `attended_at` (TIMESTAMPTZ) - Время отметки

## Резервное копирование

### Создание бэкапа
```bash
pg_dump -h 127.0.0.1 -p 5432 -U postgres -d largent > backup_largent.sql
```

### Восстановление из бэкапа
```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d largent < backup_largent.sql
```
