#!/usr/bin/env python3
"""Тест кнопок бота"""

import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from bot import VK_ENABLED, show_main_menu

async def test_buttons():
    print("🔍 Тестирование кнопок...")
    print(f"VK_ENABLED: {VK_ENABLED}")
    
    # Создаем мок объекты для тестирования
    class MockUser:
        def __init__(self):
            self.id = 825042510
    
    class MockChat:
        def __init__(self):
            self.id = 825042510
    
    class MockUpdate:
        def __init__(self):
            self.effective_user = MockUser()
            self.effective_chat = MockChat()
    
    class MockContext:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {
                "all_posters": [
                    {
                        "file_id": "test",
                        "caption": "Тестовая афиша",
                        "ticket_url": "https://example.com"
                    }
                ]
            }
    
    update = MockUpdate()
    context = MockContext()
    
    print("Проверяем генерацию кнопок главного меню...")
    
    # Это покажет нам какие кнопки должны генерироваться
    try:
        # Не можем вызвать show_main_menu напрямую, но можем проверить логику
        if VK_ENABLED:
            print("✅ VK включен - кнопка 'Привязать VK профиль' должна быть")
        else:
            print("❌ VK выключен - кнопки VK не будет")
            
        print("Проверяем переменные VK:")
        from bot import VK_TOKEN, VK_GROUP_DOMAIN
        print(f"VK_TOKEN: {'✅ установлен' if VK_TOKEN else '❌ не установлен'}")
        print(f"VK_GROUP_DOMAIN: {VK_GROUP_DOMAIN}")
        
    except Exception as e:
        print(f"💥 Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(test_buttons())
