# 🚀 Инструкция по деплою TusaBot на Ubuntu сервер

## 📋 Содержание
1. [Подготовка сервера](#1-подготовка-сервера)
2. [Установка PostgreSQL](#2-установка-postgresql)
3. [Настройка проекта на сервере](#3-настройка-проекта-на-сервере)
4. [Настройка systemd](#4-настройка-systemd)
5. [Настройка GitHub](#5-настройка-github)
6. [Настройка GitHub Actions](#6-настройка-github-actions)
7. [Первый деплой](#7-первый-деплой)
8. [Проверка работы](#8-проверка-работы)

---

## 1. Подготовка сервера

### 1.1. Подключение к серверу
```bash
ssh root@5.129.243.22
```

### 1.2. Обновление системы
```bash
apt update && apt upgrade -y
```

### 1.3. Установка необходимых пакетов
```bash
apt install -y python3 python3-pip python3-venv git postgresql postgresql-contrib nginx ufw
```

### 1.4. Создание пользователя для бота
```bash
# Создаем пользователя tusabot
useradd -m -s /bin/bash tusabot

# Добавляем в sudo группу (опционально, для отладки)
usermod -aG sudo tusabot

# Устанавливаем пароль
passwd tusabot(пароль 123qwertq)
```

### 1.5. Настройка firewall
```bash
# Разрешаем SSH, HTTP, HTTPS
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp

# Включаем firewall
ufw --force enable
ufw status
```

---

## 2. Установка PostgreSQL

### 2.1. Создание базы данных и пользователя
```bash
# Переключаемся на пользователя postgres
sudo -u postgres psql

# В консоли PostgreSQL выполняем:
CREATE DATABASE largent WITH ENCODING 'UTF8';
CREATE USER tusabot_user WITH PASSWORD 'your_secure_password_here';
GRANT ALL PRIVILEGES ON DATABASE largent TO tusabot_user;
ALTER DATABASE largent OWNER TO tusabot_user;
\q
```

### 2.2. Настройка доступа к БД
```bash
# Редактируем pg_hba.conf
nano /etc/postgresql/*/main/pg_hba.conf

# Добавляем строку (после строк с postgres):
# local   all             tusabot_user                            md5

# Перезапускаем PostgreSQL
systemctl restart postgresql
```

### 2.3. Проверка подключения
```bash
psql -U tusabot_user -d largent -h 127.0.0.1
# Введите пароль
# Если подключение успешно - выходим: \q
```

---

## 3. Настройка проекта на сервере

### 3.1. Создание директории проекта
```bash
# Создаем директорию
mkdir -p /opt/tusabot
chown tusabot:tusabot /opt/tusabot

# Переключаемся на пользователя tusabot
su - tusabot
cd /opt/tusabot
```

### 3.2. Клонирование репозитория
```bash
# Замените YOUR_USERNAME на ваш GitHub username
git clone https://github.com/YOUR_USERNAME/TusaBot.git .

# Или если репозиторий приватный, используйте Personal Access Token:
# git clone https://YOUR_TOKEN@github.com/YOUR_USERNAME/TusaBot.git .
```

### 3.3. Создание виртуального окружения
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.4. Создание файла .env
```bash
nano .env
```

**Содержимое .env:**
```env
BOT_TOKEN=your_real_bot_token_here
ADMIN_USER_ID=your_telegram_id

DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=largent
DB_USER=tusabot_user
DB_PASSWORD=your_secure_password_here

CHANNEL_USERNAME=@largentmsk
CHANNEL_USERNAME_2=@idnrecords

VK_ENABLED=True
VK_GROUP_DOMAIN=largent.tusa
VK_TOKEN=your_vk_token_here

WEEKLY_DAY=4
WEEKLY_HOUR_LOCAL=10
WEEKLY_MINUTE=0
```

**Сохраните:** Ctrl+O, Enter, Ctrl+X

### 3.5. Применение миграций БД
```bash
# Делаем скрипт исполняемым
chmod +x migrations/migrate.sh

# Применяем миграции
bash migrations/migrate.sh
```

### 3.6. Создание директории для логов
```bash
# Выходим из пользователя tusabot
exit

# Создаем директорию для логов
mkdir -p /var/log/tusabot
chown tusabot:tusabot /var/log/tusabot
```

---

## 4. Настройка systemd

### 4.1. Копирование service файла
```bash
cp /opt/tusabot/tusabot.service /etc/systemd/system/
```

### 4.2. Перезагрузка systemd и запуск бота
```bash
# Перезагружаем конфигурацию systemd
systemctl daemon-reload

# Включаем автозапуск
systemctl enable tusabot

# Запускаем бота
systemctl start tusabot

# Проверяем статус
systemctl status tusabot 
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
# Проверяем статус
```

### 4.3. Полезные команды
```bash
# Просмотр логов
journalctl -u tusabot -f

# Или из файла
tail -f /var/log/tusabot/bot.log

# Перезапуск бота
systemctl restart tusabot

# Остановка бота
systemctl stop tusabot
```

---

## 5. Настройка GitHub

### 5.1. Создание репозитория
1. Перейдите на https://github.com
2. Нажмите "New repository"
3. Название: `TusaBot`
4. Выберите Private (если нужен приватный)
5. НЕ добавляйте README, .gitignore, license (они уже есть)
6. Создайте репозиторий

### 5.2. Инициализация Git локально
На вашем компьютере (Windows):
```powershell
cd C:\Users\Sasha\Desktop\TusaBot

# Инициализируем git (если еще не инициализирован)
git init

# Добавляем все файлы
git add .

# Делаем первый коммит
git commit -m "Initial commit"

# Добавляем удаленный репозиторий (замените YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/TusaBot.git

# Пушим код
git branch -M main
git push -u origin main
```

---

## 6. Настройка GitHub Actions

### 6.1. Генерация SSH ключа на сервере
```bash
# На сервере под root
ssh-keygen -t ed25519 -C "github-actions-tusabot" -f /root/.ssh/tusabot_deploy

# Добавляем публичный ключ в authorized_keys пользователя tusabot
cat /root/.ssh/tusabot_deploy.pub >> /home/tusabot/.ssh/authorized_keys
chmod 600 /home/tusabot/.ssh/authorized_keys
chown tusabot:tusabot /home/tusabot/.ssh/authorized_keys

# Выводим приватный ключ (скопируйте его полностью)
cat /root/.ssh/tusabot_deploy
```

### 6.2. Настройка GitHub Secrets
1. Перейдите в ваш репозиторий на GitHub
2. Settings → Secrets and variables → Actions
3. Нажмите "New repository secret"

Создайте 3 секрета:

**SECRET 1: SERVER_HOST**
- Name: `SERVER_HOST`
- Value: `5.129.243.22`

**SECRET 2: SERVER_USER**
- Name: `SERVER_USER`
- Value: `tusabot`

**SECRET 3: SSH_PRIVATE_KEY**
- Name: `SSH_PRIVATE_KEY`
- Value: *Вставьте содержимое файла `/root/.ssh/tusabot_deploy` (приватный ключ)*

### 6.3. Настройка Git на сервере для деплоя
```bash
# На сервере под пользователем tusabot
su - tusabot
cd /opt/tusabot

# Настраиваем Git
git config --global user.email "bot@tusabot.local"
git config --global user.name "TusaBot Deploy"

# Делаем скрипт деплоя исполняемым
chmod +x deploy.sh

# Добавляем tusabot в sudoers для systemctl
exit  # Выходим из tusabot

# Добавляем права для tusabot управлять своим сервисом
visudo

# Добавьте строку в конец файла:
# tusabot ALL=(ALL) NOPASSWD: /bin/systemctl start tusabot, /bin/systemctl stop tusabot, /bin/systemctl restart tusabot, /bin/systemctl status tusabot
```

---

## 7. Первый деплой

### 7.1. Тестовый коммит
На вашем компьютере:
```powershell
cd C:\Users\Sasha\Desktop\TusaBot

# Делаем небольшое изменение
echo "# TusaBot - автоматический деплой настроен!" >> README.md

# Коммитим и пушим
git add .
git commit -m "Test automatic deployment"
git push origin main
```

### 7.2. Проверка деплоя
1. Перейдите на GitHub в ваш репозиторий
2. Вкладка "Actions"
3. Вы увидите запущенный workflow "Deploy TusaBot to Server"
4. Дождитесь завершения (зеленая галочка ✅)

### 7.3. Проверка на сервере
```bash
ssh root@5.129.243.22
systemctl status tusabot
journalctl -u tusabot -n 50
```

---

## 8. Проверка работы

### 8.1. Проверка бота в Telegram
1. Откройте Telegram
2. Найдите вашего бота
3. Отправьте `/start`
4. Проверьте регистрацию
5. Проверьте админ-панель

### 8.2. Проверка БД
```bash
ssh root@5.129.243.22
sudo -u postgres psql -d largent

# Проверяем таблицы
\dt

# Проверяем пользователей
SELECT * FROM users;

# Выход
\q
```

### 8.3. Мониторинг логов
```bash
# Логи бота
tail -f /var/log/tusabot/bot.log

# Системные логи
journalctl -u tusabot -f

# Ошибки
tail -f /var/log/tusabot/error.log
```

---

## 🔄 Процесс обновления

После настройки, для обновления бота достаточно:

```powershell
# На вашем компьютере
cd C:\Users\Sasha\Desktop\TusaBot

# Внесите изменения в код
# ...

# Закоммитьте и запушьте
git add .
git commit -m "Описание изменений"
git push origin main
```

**Автоматически произойдет:**
1. ✅ GitHub Actions запустит workflow
2. ✅ Подключится к серверу по SSH
3. ✅ Остановит бота
4. ✅ Скачает новый код
5. ✅ Обновит зависимости
6. ✅ Применит миграции БД
7. ✅ Запустит бота

**Весь процесс занимает ~30-60 секунд!**

---

## 🆘 Troubleshooting

### Проблема: GitHub Actions не подключается по SSH
**Решение:**
```bash
# Проверьте SSH на сервере
ssh tusabot@5.129.243.22

# Проверьте права
ls -la /home/tusabot/.ssh/
```

### Проблема: Бот не запускается
**Решение:**
```bash
# Проверьте логи
journalctl -u tusabot -n 100

# Проверьте .env файл
cat /opt/tusabot/.env

# Попробуйте запустить вручную
su - tusabot
cd /opt/tusabot
source venv/bin/activate
python bot.py
```

### Проблема: Миграции не применяются
**Решение:**
```bash
# Проверьте подключение к БД
psql -U tusabot_user -d largent -h 127.0.0.1

# Примените миграции вручную
su - tusabot
cd /opt/tusabot
bash migrations/migrate.sh
```

### Проблема: Недостаточно прав для systemctl
**Решение:**
```bash
# Проверьте sudoers
sudo visudo

# Должна быть строка:
# tusabot ALL=(ALL) NOPASSWD: /bin/systemctl start tusabot, /bin/systemctl stop tusabot, /bin/systemctl restart tusabot, /bin/systemctl status tusabot
```

---

## 📝 Дополнительные файлы миграций

Для добавления новых миграций:

1. Создайте файл в `migrations/`:
```bash
# Локально
nano migrations/002_add_new_feature.sql
```

2. Напишите SQL:
```sql
-- migrations/002_add_new_feature.sql
ALTER TABLE users ADD COLUMN new_field TEXT;
```

3. Закоммитьте и запушьте:
```powershell
git add migrations/002_add_new_feature.sql
git commit -m "Add new field to users table"
git push origin main
```

4. Миграция применится автоматически при деплое!

---

## ✅ Готово!

Ваш бот теперь:
- ✅ Автоматически деплоится при каждом push
- ✅ Работает как systemd сервис
- ✅ Автоматически перезапускается при падении
- ✅ Логируется в `/var/log/tusabot/`
- ✅ Применяет миграции БД автоматически

**Удачного деплоя! 🚀**
