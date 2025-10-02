#!/usr/bin/env python3
"""
Скрипт для переноса пользователей из persistence файла в PostgreSQL БД
"""
import asyncio
import pickle
import os
from pathlib import Path
from dotenv import load_dotenv
from db import create_pool, upsert_user, DB_HOST, DB_PORT, DB_NAME, DB_USER

# Загружаем переменные окружения из .env
load_dotenv()

async def migrate_users():
    # Проверяем переменные окружения
    print("🔍 Проверка конфигурации БД...")
    print(f"   DB_HOST: {DB_HOST}")
    print(f"   DB_PORT: {DB_PORT}")
    print(f"   DB_NAME: {DB_NAME}")
    print(f"   DB_USER: {DB_USER}")
    
    if DB_USER == "postgres":
        print("❌ ОШИБКА: DB_USER=postgres (должен быть tusabot_user)")
        print("   Проверьте файл .env!")
        return
    
    # Путь к persistence файлу
    persistence_file = Path("/opt/tusabot/data/bot_data.pkl")
    
    if not persistence_file.exists():
        print(f"❌ Файл {persistence_file} не найден!")
        return
    
    # Загружаем данные из persistence
    print("\n📂 Загружаем данные из persistence файла...")
    with open(persistence_file, "rb") as f:
        data = pickle.load(f)
    
    user_data = data.get("user_data", {})
    print(f"✅ Найдено {len(user_data)} пользователей в persistence")
    
    # Подключаемся к БД
    print("\n🔌 Подключаемся к БД...")
    try:
        pool = await create_pool()
        print("✅ Подключение к БД успешно!")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return
    
    # Переносим каждого пользователя
    migrated = 0
    skipped = 0
    
    for tg_id, user_info in user_data.items():
        try:
            # Проверяем что есть необходимые данные
            if not user_info.get("registered"):
                print(f"⏭️  Пропускаем {tg_id} - не завершил регистрацию")
                skipped += 1
                continue
            
            name = user_info.get("name")
            gender = user_info.get("gender")
            age = user_info.get("age")
            vk_id = user_info.get("vk_id")
            username = None  # Username не хранится в persistence, будет обновлен при следующем /start
            
            if not name:
                print(f"⏭️  Пропускаем {tg_id} - нет имени")
                skipped += 1
                continue
            
            # Сохраняем в БД
            await upsert_user(
                pool=pool,
                tg_id=tg_id,
                name=name,
                gender=gender,
                age=age,
                vk_id=vk_id,
                username=username
            )
            
            migrated += 1
            print(f"✅ {migrated}. Перенесен: {name} (ID: {tg_id})")
            
        except Exception as e:
            print(f"❌ Ошибка при переносе {tg_id}: {e}")
            skipped += 1
    
    await pool.close()
    
    print("\n" + "="*50)
    print(f"🎉 Миграция завершена!")
    print(f"✅ Перенесено: {migrated}")
    print(f"⏭️  Пропущено: {skipped}")
    print(f"📊 Всего: {len(user_data)}")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(migrate_users())
