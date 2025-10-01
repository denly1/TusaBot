#!/bin/bash
set -e

echo "🚀 Starting deployment..."

# Переходим в директорию проекта
cd /opt/tusabot

# Останавливаем бота
echo "⏸️  Stopping bot..."
sudo systemctl stop tusabot || true

# Сохраняем .env файл
echo "💾 Backing up .env..."
cp .env .env.backup || true

# Получаем последние изменения из GitHub
echo "📥 Pulling latest code from GitHub..."
git fetch origin main
git reset --hard origin/main

# Восстанавливаем .env
echo "🔧 Restoring .env..."
cp .env.backup .env || true

# Активируем виртуальное окружение
echo "🐍 Activating virtual environment..."
source venv/bin/activate

# Обновляем зависимости
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Применяем миграции БД
echo "🗄️  Running database migrations..."
if [ -f "migrations/migrate.sh" ]; then
    bash migrations/migrate.sh
else
    echo "⚠️  No migrations script found, skipping..."
fi

# Перезапускаем бота
echo "▶️  Starting bot..."
sudo systemctl start tusabot

# Проверяем статус
echo "✅ Checking bot status..."
sleep 2
sudo systemctl status tusabot --no-pager

echo "🎉 Deployment completed successfully!"
