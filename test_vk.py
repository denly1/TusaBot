#!/usr/bin/env python3
"""Тест VK функций бота"""

import asyncio
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Импортируем функции из бота
from bot import is_user_subscribed_vk, VK_ENABLED, VK_TOKEN, VK_GROUP_DOMAIN

async def test_vk_functions():
    print("🔍 Тестирование VK функций...")
    print(f"VK_ENABLED: {VK_ENABLED}")
    print(f"VK_TOKEN: {VK_TOKEN[:20]}..." if VK_TOKEN else "VK_TOKEN: None")
    print(f"VK_GROUP_DOMAIN: {VK_GROUP_DOMAIN}")
    print()
    
    if not VK_ENABLED:
        print("❌ VK не включен!")
        return
    
    # Тестируем разные форматы VK ID
    test_cases = [
        "825042510",  # ваш ID
        "id825042510",  # с префиксом id
        "1",  # Павел Дуров
        "durov",  # короткое имя
    ]
    
    for vk_id in test_cases:
        print(f"📱 Проверяем VK ID: {vk_id}")
        try:
            result = await is_user_subscribed_vk(vk_id)
            if result is None:
                print(f"   ❓ Не удалось проверить")
            elif result:
                print(f"   ✅ Подписан на группу")
            else:
                print(f"   ❌ Не подписан на группу")
        except Exception as e:
            print(f"   💥 Ошибка: {e}")
        print()

if __name__ == "__main__":
    asyncio.run(test_vk_functions())
