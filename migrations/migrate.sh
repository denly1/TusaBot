#!/bin/bash
set -e

echo "🗄️  Applying database migrations..."

# Загружаем переменные окружения
if [ -f "/opt/tusabot/.env" ]; then
    export $(cat /opt/tusabot/.env | grep -v '^#' | xargs)
fi

# Параметры подключения к БД
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-largent}"
DB_USER="${DB_USER:-tusabot_user}"

# Директория с миграциями
MIGRATIONS_DIR="/opt/tusabot/migrations"

# Применяем каждую миграцию
for migration in $(ls -1 $MIGRATIONS_DIR/*.sql | sort); do
    echo "  📝 Applying: $(basename $migration)"
    PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f $migration
done

echo "✅ All migrations applied successfully!"
