#!/usr/bin/env python3
"""Диагностика данных TusaBot"""

import asyncio
import os
import pickle
from pathlib import Path
from dotenv import load_dotenv
from db import create_pool, get_all_user_ids, get_user

# Загружаем переменные окружения
load_dotenv()

async def check_database():
    """Проверяем данные в PostgreSQL"""
    print("🔍 Проверяем базу данных PostgreSQL...")
    try:
        pool = await create_pool()
        user_ids = await get_all_user_ids(pool)
        print(f"📊 Пользователей в БД: {len(user_ids)}")
        
        if user_ids:
            print("👥 Пользователи в БД:")
            for user_id in user_ids[:5]:  # Показываем первых 5
                user_data = await get_user(pool, user_id)
                print(f"  - {user_id}: {user_data}")
        else:
            print("❌ База данных пустая")
            
        await pool.close()
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")

def check_persistence_file():
    """Проверяем файл persistence"""
    print("\n🔍 Проверяем файл persistence...")
    
    persistence_paths = [
        Path("data/bot_data.pkl"),
        Path("bot_data.pickle"),
        Path("bot_data.pkl")
    ]
    
    for path in persistence_paths:
        if path.exists():
            print(f"📁 Найден файл: {path}")
            try:
                with open(path, 'rb') as f:
                    data = pickle.load(f)
                    
                print(f"📊 Размер данных: {len(str(data))} символов")
                print(f"🔑 Ключи в данных: {list(data.keys())}")
                
                # Проверяем известных пользователей
                if 'known_users' in data:
                    known_users = data['known_users']
                    print(f"👥 Известных пользователей: {len(known_users)}")
                    if known_users:
                        print(f"  Список: {list(known_users)}")
                
                # Проверяем user_data
                if 'user_data' in data:
                    user_data = data['user_data']
                    print(f"📝 Данных пользователей: {len(user_data)}")
                    for user_id, udata in list(user_data.items())[:3]:
                        print(f"  - Пользователь {user_id}:")
                        for key, value in udata.items():
                            print(f"    {key}: {value}")
                        print()
                        
            except Exception as e:
                print(f"❌ Ошибка чтения файла {path}: {e}")
        else:
            print(f"❌ Файл не найден: {path}")

def check_env():
    """Проверяем настройки подключения"""
    print("\n🔍 Проверяем настройки подключения...")
    
    db_settings = {
        'DB_HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'DB_PORT': os.getenv('DB_PORT', '5432'),
        'DB_NAME': os.getenv('DB_NAME', 'largent'),
        'DB_USER': os.getenv('DB_USER', 'postgres'),
        'DB_PASSWORD': os.getenv('DB_PASSWORD', '1')
    }
    
    print("⚙️ Настройки БД:")
    for key, value in db_settings.items():
        if key == 'DB_PASSWORD':
            print(f"  {key}: {'*' * len(value)}")
        else:
            print(f"  {key}: {value}")

async def main():
    print("🔧 Диагностика данных TusaBot\n")
    
    check_env()
    check_persistence_file()
    await check_database()
    
    print("\n💡 Возможные причины пустой БД:")
    print("1. Данные хранятся только в файле persistence")
    print("2. Бот не подключается к БД (ошибки подключения)")
    print("3. Бот подключается к другой базе данных")
    print("4. Схема БД не соответствует коду")

if __name__ == "__main__":
    asyncio.run(main())
