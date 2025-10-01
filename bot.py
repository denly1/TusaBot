import os
import logging
import asyncio
from datetime import datetime, timedelta, time, timezone
from pathlib import Path
import pytz
from typing import Set, Optional
import re
import httpx

# Simple validators
def is_valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return bool(re.match(r"^(https?://)[\w\-]+(\.[\w\-]+)+(:\d+)?(/[\w\-._~:/?#\[\]@!$&'()*+,;=%]*)?$", url))

def is_valid_caption(c: str) -> bool:
    # Telegram photo caption limit is 1024 chars for older APIs; use 1024 as a safe cap
    return c is not None and len(c) <= 1024

from dotenv import load_dotenv, dotenv_values, find_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    BotCommand,
)
from telegram.constants import ChatMemberStatus
from telegram.error import Forbidden
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PicklePersistence,
    ContextTypes,
    TypeHandler,
    filters,
)
from telegram.request import HTTPXRequest
from db import create_pool, init_schema, upsert_user, set_vk_id, get_user, get_user_by_username, get_all_user_ids, load_user_vk_data, get_user_stats, export_users_to_excel

# ----------------------
# Logging
# ----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("TusaBot")

# ----------------------
# Env config
# ----------------------
_DOTENV_PATH = find_dotenv(usecwd=True) or os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=_DOTENV_PATH, override=True)
_ENV_FALLBACK = dotenv_values(dotenv_path=_DOTENV_PATH)  # read .env directly as fallback


def _clean_env(v: str) -> str:
    v = (v or "").strip()
    # remove surrounding single or double quotes if present
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1].strip()
    return v


def _get_env(key: str, default: str = "") -> str:
    v = os.getenv(key)
    if v is None or v == "":
        v = _ENV_FALLBACK.get(key, default)
    return _clean_env(v)


BOT_TOKEN = _get_env("BOT_TOKEN", "")
ADMIN_USER_ID_STR = _get_env("ADMIN_USER_ID", "")
ADMIN_USER_ID = int(ADMIN_USER_ID_STR) if ADMIN_USER_ID_STR.isdigit() else 0
ADMIN_USER_ID_2_STR = _get_env("ADMIN_USER_ID_2", "")
ADMIN_USER_ID_2 = int(ADMIN_USER_ID_2_STR) if ADMIN_USER_ID_2_STR.isdigit() else 0
ADMIN_USER_ID_3_STR = _get_env("ADMIN_USER_ID_3", "")
ADMIN_USER_ID_3 = int(ADMIN_USER_ID_3_STR) if ADMIN_USER_ID_3_STR.isdigit() else 0
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@largentmsk")
CHANNEL_USERNAME_2 = os.getenv("CHANNEL_USERNAME_2", "@idnrecords")

def _normalize_channel(value: str):
    v = (value or "").strip()
    # numeric chat id like -1001234567890
    if v.startswith("-100") and v[4:].isdigit():
        return int(v)
    # strip t.me prefixes
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if v.lower().startswith(prefix):
            v = v[len(prefix):]
            break
    if not v.startswith("@"):
        v = f"@{v}"
    return v

CHANNEL_ID = _normalize_channel(CHANNEL_USERNAME)
CHANNEL_ID_2 = _normalize_channel(CHANNEL_USERNAME_2)
WEEKLY_DAY = int(_get_env("WEEKLY_DAY", "4"))  # 0=Mon..6=Sun
WEEKLY_HOUR_LOCAL = int(_get_env("WEEKLY_HOUR", "12"))
WEEKLY_MINUTE = int(_get_env("WEEKLY_MINUTE", "0"))
# VK integration
VK_TOKEN = _get_env("VK_TOKEN", "")
VK_ENABLED = bool(VK_TOKEN)
def _normalize_vk_group_domain(v: str) -> str:
    v = v.strip()
    for prefix in ("https://vk.com/", "http://vk.com/", "vk.com/"):
        if v.lower().startswith(prefix):
            v = v[len(prefix):]
            break
    return v.strip("/") or "largent.tusa"
VK_GROUP_DOMAIN = os.getenv("VK_GROUP_DOMAIN", "largent.tusa")
# Proxy settings
PROXY_URL = _get_env("PROXY_URL", "")
# Convert MSK (UTC+3) local hour to UTC for job queue
WEEKLY_HOUR_UTC = (WEEKLY_HOUR_LOCAL - 3) % 24

logger.info("Loaded .env from: %s", _DOTENV_PATH)

REENGAGE_TEXT = (
    "Мы очень скучаем без тебя 🥹\n"
    "Новая неделя, новые вечеринки 🥳\n"
    "Возвращайся скорее, будем делать тыц тыц тыц как в старые добрые 💃🕺🏻"
)

DATA_DIR = Path(__file__).parent / "data"
PERSISTENCE_FILE = DATA_DIR / "bot_data.pkl"

# ----------------------
# Helpers
# ----------------------

def ensure_data_dir() -> None:
    DATA_DIR.mkdir(exist_ok=True)


def week_key_for_date(dt: datetime) -> str:
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def previous_week_key(now: datetime) -> str:
    last_week_date = now - timedelta(days=7)
    return week_key_for_date(last_week_date)


async def is_user_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> tuple[bool, bool]:
    """Проверить подписку пользователя на оба Telegram канала
    
    Returns:
        tuple[bool, bool]: (подписан на первый канал, подписан на второй канал)
    """
    channel1_ok = False
    channel2_ok = False
    
    # Проверяем первый канал
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        channel1_ok = member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.warning("Failed to check TG subscription for user %s on %s: %s", user_id, CHANNEL_USERNAME, e)
    
    # Проверяем второй канал
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME_2, user_id)
        channel2_ok = member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.warning("Failed to check TG subscription for user %s on %s: %s", user_id, CHANNEL_USERNAME_2, e)
    
    return channel1_ok, channel2_ok


async def get_bot_channel_status(context: ContextTypes.DEFAULT_TYPE) -> str:
    try:
        bot_member = await context.bot.get_chat_member(CHANNEL_USERNAME, context.bot.id)
        if bot_member.status == "administrator":
            return f"Бот имеет права администратора в {CHANNEL_USERNAME} ✅"
        else:
            return f"⚠️ Бот не является администратором {CHANNEL_USERNAME}. Проверка подписки может работать некорректно."
    except Exception as e:
        logger.warning("Failed to get bot status in channel %s: %s", CHANNEL_USERNAME, e)
        return f"❌ Не удалось проверить статус бота в {CHANNEL_USERNAME}. Убедитесь, что бот добавлен в канал как администратор."


def get_known_users(context: ContextTypes.DEFAULT_TYPE) -> Set[int]:
    bd = context.bot_data
    if "known_users" not in bd:
        bd["known_users"] = set()
    return bd["known_users"]


def get_db_pool(context: ContextTypes.DEFAULT_TYPE):
    try:
        return context.application.bot_data.get("db_pool")
    except Exception:
        return None


async def load_user_data_from_db(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Загружает данные пользователя из БД в context.user_data"""
    pool = get_db_pool(context)
    if not pool:
        logger.warning("No DB pool available for user %s", user_id)
        return
    
    try:
        user_in_db = await get_user(pool, user_id)
        logger.info("DB query result for user %s: %s", user_id, user_in_db)
        
        if user_in_db:
            # Загружаем все доступные данные
            context.user_data["name"] = user_in_db.get("name")
            context.user_data["gender"] = user_in_db.get("gender")
            context.user_data["age"] = user_in_db.get("age")
            
            # Загружаем VK ID если есть
            if user_in_db.get("vk_id"):
                context.user_data["vk_id"] = user_in_db.get("vk_id")
            
            # Проверяем полноту регистрации - нужны минимум имя, пол и возраст
            has_required_data = (
                user_in_db.get("name") and 
                user_in_db.get("gender") and 
                user_in_db.get("age") is not None
            )
            
            if has_required_data:
                context.user_data["registered"] = True
                logger.info("User %s fully registered - loaded from DB: name=%s, gender=%s, age=%s", 
                           user_id, user_in_db.get("name"), user_in_db.get("gender"), user_in_db.get("age"))
            else:
                context.user_data["registered"] = False
                logger.info("User %s in DB but incomplete: name=%s, gender=%s, age=%s", 
                           user_id, user_in_db.get("name"), user_in_db.get("gender"), user_in_db.get("age"))
        else:
            # Пользователя нет в БД - сбрасываем регистрацию
            context.user_data["registered"] = False
            context.user_data.pop("name", None)
            context.user_data.pop("gender", None)
            context.user_data.pop("age", None)
            context.user_data.pop("vk_id", None)
            logger.info("User %s not found in DB - reset registration", user_id)
    except Exception as e:
        logger.warning("Failed to load user data from DB for user %s: %s", user_id, e)




def get_admins(context: ContextTypes.DEFAULT_TYPE) -> Set[int]:
    bd = context.bot_data
    if "admins" not in bd:
        bd["admins"] = set()
    
    # Всегда добавляем админов из .env (на случай если добавили новых)
    if ADMIN_USER_ID:
        bd["admins"].add(ADMIN_USER_ID)
    if ADMIN_USER_ID_2:
        bd["admins"].add(ADMIN_USER_ID_2)
    if ADMIN_USER_ID_3:
        bd["admins"].add(ADMIN_USER_ID_3)
    
    return bd["admins"]


# ----------------------
# VK helpers
# ----------------------

VK_PROFILE_RE = re.compile(r"(?:https?://)?(?:www\.)?vk\.com/(id\d+|[A-Za-z0-9_\.]+)", re.IGNORECASE)


def extract_vk_id(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    m = VK_PROFILE_RE.search(text)
    if m:
        return m.group(1)
    # if numeric id
    if text.isdigit():
        return f"id{text}"
    return None


async def vk_is_member(vk_user: str) -> Optional[bool]:
    if not VK_TOKEN:
        return None  # cannot verify
    # groups.isMember accepts group_id (domain) and user_id
    params = {
        "group_id": VK_GROUP_DOMAIN,
        "user_id": vk_user,
        "access_token": VK_TOKEN,
        "v": "5.131",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://api.vk.com/method/groups.isMember", params=params)
            data = r.json()
            if "error" in data:
                logger.warning("VK API error: %s", data["error"])
                return None
            resp = data.get("response")
            if isinstance(resp, dict):
                return bool(resp.get("member", 0))
            return bool(resp)
    except Exception as e:
        logger.warning("VK check failed: %s", e)
        return None


async def is_user_subscribed_vk(vk_user_id: str) -> Optional[bool]:
    """Автопроверка подписки пользователя на VK группу.

    Возвращает:
      - True/False — если проверка удалась
      - None — если проверить не удалось (ошибка VK API/сеть)
    """
    if not VK_ENABLED or not VK_TOKEN:
        return None

    try:
        import aiohttp

        # 1) Получаем numeric group_id по домену
        async with aiohttp.ClientSession() as session:
            group_url = (
                "https://api.vk.com/method/groups.getById"
                f"?group_id={VK_GROUP_DOMAIN}&access_token={VK_TOKEN}&v=5.131"
            )
            async with session.get(group_url) as resp:
                group_data = await resp.json()
                if 'error' in group_data:
                    logger.warning("VK API error getting group info: %s", group_data['error'])
                    return None
                group_id = group_data['response'][0]['id']

            # 2) Нормализуем user_id: поддерживаем 'id123', '123', 'durov'
            raw = (vk_user_id or '').strip()
            if raw.lower().startswith('id') and raw[2:].isdigit():
                user_id_numeric = raw[2:]
            elif raw.isdigit():
                user_id_numeric = raw
            else:
                # resolve screen name -> object_id
                resolve_url = (
                    "https://api.vk.com/method/utils.resolveScreenName"
                    f"?screen_name={raw}&access_token={VK_TOKEN}&v=5.131"
                )
                async with session.get(resolve_url) as r2:
                    rj = await r2.json()
                    if 'error' in rj or not rj.get('response'):
                        logger.warning("VK resolveScreenName failed for %s: %s", raw, rj.get('error'))
                        return None
                    resp = rj['response']
                    if resp.get('type') != 'user':
                        logger.warning("Resolved name is not a user: %s", resp)
                        return None
                    user_id_numeric = str(resp.get('object_id'))

            # 3) Проверяем членство
            check_url = (
                "https://api.vk.com/method/groups.isMember"
                f"?group_id={group_id}&user_id={user_id_numeric}&access_token={VK_TOKEN}&v=5.131"
            )
            async with session.get(check_url) as resp:
                data = await resp.json()
                if 'error' in data:
                    logger.warning("VK API error checking membership: %s", data['error'])
                    return None
                # ответ может быть числом 1/0 или словарем {member: 1}
                resp_val = data.get('response')
                if isinstance(resp_val, dict):
                    return bool(resp_val.get('member', 0))
                return bool(resp_val)

    except Exception as e:
        logger.warning("Failed to check VK subscription for %s: %s", vk_user_id, e)
        return None


async def broadcast_to_vk(poster_data: dict) -> bool:
    """Отправить афишу в VK группу largent.tusa"""
    if not VK_ENABLED or not VK_TOKEN:
        logger.info("VK broadcast disabled - no token")
        return False
    
    try:
        import aiohttp
        
        # Получаем данные афиши
        caption = poster_data.get('caption', '')
        ticket_url = poster_data.get('ticket_url', '')
        
        # Формируем текст поста
        post_text = caption
        if ticket_url:
            post_text += f"\n\n🎫 Билеты: {ticket_url}"
        
        async with aiohttp.ClientSession() as session:
            # Получаем ID группы
            group_url = f"https://api.vk.com/method/groups.getById?group_id={VK_GROUP_DOMAIN}&access_token={VK_TOKEN}&v=5.131"
            async with session.get(group_url) as resp:
                group_data = await resp.json()
                if 'error' in group_data:
                    logger.error("VK API error getting group info: %s", group_data['error'])
                    return False
                
                group_id = group_data['response'][0]['id']
            
            # Отправляем пост на стену группы
            post_url = f"https://api.vk.com/method/wall.post"
            post_data = {
                'owner_id': f'-{group_id}',
                'message': post_text,
                'from_group': 1,
                'access_token': VK_TOKEN,
                'v': '5.131'
            }
            
            async with session.post(post_url, data=post_data) as resp:
                result = await resp.json()
                if 'error' in result:
                    logger.error("VK API error posting: %s", result['error'])
                    return False
                
                logger.info("Successfully posted to VK group: post_id=%s", result['response']['post_id'])
                return True
                
    except Exception as e:
        logger.error("Failed to broadcast to VK: %s", e)
        return False


# ----------------------
# Handlers
# ----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    
    get_known_users(context).add(user.id)
    
    # Создаем минимальную запись в БД если её нет
    pool = get_db_pool(context)
    if pool:
        try:
            await upsert_user(pool, tg_id=user.id, username=user.username)
        except Exception as e:
            logger.warning("DB upsert on /start failed: %s", e)
    
    # Загружаем данные пользователя из БД
    await load_user_data_from_db(context, user.id)
    
    # Проверяем, завершена ли регистрация пользователя более надежно
    user_data = context.user_data
    is_registered = (
        user_data.get("registered") == True and 
        user_data.get("name") and 
        user_data.get("gender") and 
        user_data.get("age") is not None
    )
    
    # Проверяем незавершенную регистрацию
    has_partial_data = user_data.get("name") or user_data.get("gender") or user_data.get("age") is not None
    
    logger.info("Start command for user %s: registered=%s, name=%s, gender=%s, age=%s", 
               user.id, user_data.get("registered"), user_data.get("name"), 
               user_data.get("gender"), user_data.get("age"))
    
    if is_registered:
        # Пользователь уже зарегистрирован - показываем сообщение и кнопку меню
        # Сбрасываем флаг регистрации если он остался
        user_data.pop("registration_step", None)
        user_data.pop("awaiting_vk", None)
        user_data.pop("awaiting_username_check", None)
        
        kb = [[InlineKeyboardButton("🎉 Перейти в меню", callback_data="back_to_menu")]]
        await update.effective_chat.send_message(
            "🎉 Вы уже зарегистрированы у нас на вечеринках!\n\n"
            f"👤 Ваши данные:\n"
            f"• Имя: {user_data.get('name', 'Не указано')}\n"
            f"• Пол: {'Мужской' if user_data.get('gender') == 'male' else 'Женский' if user_data.get('gender') == 'female' else 'Не указан'}\n"
            f"• Возраст: {user_data.get('age', 'Не указан')} лет\n"
            f"• VK профиль: {'Привязан' if user_data.get('vk_id') else 'Не привязан'}\n\n"
            "Добро пожаловать обратно! 🥳",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    
    # Если есть частичные данные, продолжаем с того места где остановились
    if has_partial_data and not is_registered:
        # Определяем на каком этапе остановились
        if not user_data.get("name"):
            user_data["registration_step"] = "name"
            await update.effective_chat.send_message(
                "👋 Продолжим регистрацию!\n\n"
                "Как вас зовут? (Введите ваше имя)"
            )
        elif not user_data.get("gender"):
            user_data["registration_step"] = "gender"
            kb = [
                [InlineKeyboardButton("👨 Мужской", callback_data="gender_male")],
                [InlineKeyboardButton("👩 Женский", callback_data="gender_female")]
            ]
            await update.effective_chat.send_message(
                f"Отлично, {user_data.get('name')}! 😊\n\n"
                "Укажите ваш пол:",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        elif user_data.get("age") is None:
            user_data["registration_step"] = "age"
            await update.effective_chat.send_message(
                "Последний шаг! 🎯\n\n"
                "Укажите ваш возраст (числом):\n"
                "Например: 25"
            )
        return
    
    # Начинаем регистрацию с начала
    user_data["registration_step"] = "name"
    logger.info("Starting registration for user %s", user.id)
    await update.effective_chat.send_message(
        "🎉 Добро пожаловать на наши вечеринки!\n\n"
        "Для начала давайте знакомиться.\n"
        "Как вас зовут? (Введите ваше имя)"
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню с кнопками и статусами подписки"""
    user = update.effective_user
    if not user:
        return

    # Добавляем пользователя в известные
    get_known_users(context).add(user.id)
    
    # Загружаем данные пользователя из БД
    await load_user_data_from_db(context, user.id)

    # Проверяем регистрацию более надежно
    user_data = context.user_data
    is_registered = (
        user_data.get("registered") == True and 
        user_data.get("name") and 
        user_data.get("gender") and 
        user_data.get("age") is not None
    )
    
    logger.info("Menu command for user %s: registered=%s, name=%s, gender=%s, age=%s", 
               user.id, user_data.get("registered"), user_data.get("name"), 
               user_data.get("gender"), user_data.get("age"))
    
    if not is_registered:
        logger.info("User %s not registered - showing registration message", user.id)
        await update.effective_chat.send_message(
            "❗ Для использования меню необходимо пройти регистрацию.\n\n"
            "Нажмите /start для начала регистрации."
        )
        return

    # Показываем главное меню
    await show_main_menu(update, context)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать главное меню с текущей афишей и навигацией"""
    user = update.effective_user
    if not user:
        return
    
    # Загружаем данные пользователя из БД (в том числе VK ID)
    await load_user_data_from_db(context, user.id)
    
    # Получаем все афиши
    all_posters = context.bot_data.get("all_posters", [])
    current_poster = context.bot_data.get("poster")
    
    # Если есть текущая афиша, но её нет в списке всех афиш, добавляем
    if current_poster and current_poster not in all_posters:
        all_posters.append(current_poster)
        context.bot_data["all_posters"] = all_posters
    
    if not all_posters:
        # Нет афиш - показываем заглушку
        kb = []
        if user.id in get_admins(context):
            kb.append([InlineKeyboardButton("🛠 Админ-панель", callback_data="open_admin")])
        
        await update.effective_chat.send_message(
            "🎭 Пока нет доступных афиш\n\n"
            "Следите за обновлениями!",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None
        )
        return
    
    # Получаем текущий индекс афиши (по умолчанию - последняя)
    if "current_poster_index" not in context.user_data and all_posters:
        context.user_data["current_poster_index"] = len(all_posters) - 1
    current_poster_index = context.user_data.get("current_poster_index", 0)
    if current_poster_index >= len(all_posters):
        current_poster_index = len(all_posters) - 1
        context.user_data["current_poster_index"] = current_poster_index
    elif current_poster_index < 0:
        current_poster_index = 0
        context.user_data["current_poster_index"] = current_poster_index
    
    # Показываем текущую афишу
    poster = all_posters[current_poster_index]
    
    # Создаем кнопки навигации и действий
    nav_buttons = []
    
    # Навигация по афишам (если больше одной)
    if len(all_posters) > 1:
        nav_row = []
        if current_poster_index > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Предыдущая", callback_data="poster_prev"))
        if current_poster_index < len(all_posters) - 1:
            nav_row.append(InlineKeyboardButton("➡️ Следующая", callback_data="poster_next"))
        if nav_row:
            nav_buttons.append(nav_row)
    
    # Основные кнопки действий в правильном порядке
    action_buttons = []
    
    # 1. Кнопка билетов (если есть ссылка)
    if poster.get("ticket_url"):
        action_buttons.append([InlineKeyboardButton("🎫 Купить билет", url=poster["ticket_url"])])
    
    # 2. Кнопка привязки/перепривязки VK для всех пользователей
    if VK_ENABLED:
        vk_id = context.user_data.get("vk_id")
        if not vk_id:
            action_buttons.append([InlineKeyboardButton("🔗 Привязать VK профиль", callback_data="link_vk")])
        else:
            action_buttons.append([InlineKeyboardButton("🔄 Перепривязать VK", callback_data="link_vk")])
    
    # Админские кнопки
    if user and user.id in get_admins(context):
        admin_row = []
        admin_row.append(InlineKeyboardButton("🛠 Админ-панель", callback_data="open_admin"))
        if len(all_posters) > 0:
            admin_row.append(InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_poster:{current_poster_index}"))
        action_buttons.append(admin_row)
    
    # Собираем все кнопки
    all_buttons = nav_buttons + action_buttons
    
    # Отправляем или редактируем афишу
    try:
        caption = poster.get("caption", "")
        if len(all_posters) > 1:
            caption += f"\n\n📍 Афиша {current_poster_index + 1} из {len(all_posters)}"
        
        # Убираем админскую клавиатуру если была
        keyboard_remove_msg = await update.effective_chat.send_message(
            "📋 Главное меню", 
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Отправляем афишу
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=poster["file_id"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(all_buttons)
        )
        
        # Удаляем сообщение "Главное меню" чтобы не дублировать
        try:
            await keyboard_remove_msg.delete()
        except:
            pass  # Игнорируем ошибки удаления
            
    except Exception as e:
        logger.exception("Failed to send poster: %s", e)
        await update.effective_chat.send_message(
            "Ошибка при загрузке афиши. Попробуйте позже.",
            reply_markup=None
        )


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        await update.effective_chat.send_message(f"Ваш ID: {user.id}")


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
        user = query.from_user
        data = query.data
        
        logger.info("Button pressed by user %s: %s", user.id, data)

        # Загружаем данные пользователя из БД
        await load_user_data_from_db(context, user.id)

        if data == "check_all":
            tg1_ok, tg2_ok = await is_user_subscribed(context, user.id)
            vk_id = context.user_data.get("vk_id")
            vk_status = None
            if VK_ENABLED and vk_id:
                vk_status = await is_user_subscribed_vk(vk_id)

            # Формируем сообщение с простым форматом
            lines = ["🔍 **Статус подписок:**\n"]
            
            # Первый Telegram канал
            tg1_icon = "✅" if tg1_ok else "❌"
            tg1_url = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
            lines.append(f"{tg1_icon} [Largent MSK]({tg1_url})")
            
            # Второй Telegram канал
            tg2_icon = "✅" if tg2_ok else "❌"
            tg2_url = f"https://t.me/{CHANNEL_USERNAME_2.lstrip('@')}"
            lines.append(f"{tg2_icon} [IDN Records]({tg2_url})")
            
            # VK со ссылкой и статусом
            if VK_ENABLED:
                if not vk_id:
                    lines.append(f"⚠️ [VK группа](https://vk.com/{VK_GROUP_DOMAIN}) - профиль не привязан")
                elif vk_status is None:
                    lines.append(f"❓ [VK группа](https://vk.com/{VK_GROUP_DOMAIN}) - не удалось проверить")
                elif vk_status is True:
                    lines.append(f"✅ [VK группа](https://vk.com/{VK_GROUP_DOMAIN})")
                elif vk_status is False:
                    lines.append(f"❌ [VK группа](https://vk.com/{VK_GROUP_DOMAIN}) - не подписан")
            
            # Итоговый статус - нужны все подписки
            all_tg_ok = tg1_ok and tg2_ok
            if all_tg_ok and (not VK_ENABLED or not vk_id or vk_status):
                lines.append("\n🎉 **Все проверки пройдены!**")
            else:
                lines.append("\n⚠️ **Требуется подписка для участия**")
            
            text = "\n".join(lines)
            
            # Кнопки действий
            btns = []
            
            # Кнопки подписки на каналы (если не подписан)
            if not tg1_ok:
                btns.append([InlineKeyboardButton("📢 Подписаться на Largent MSK", url=tg1_url)])
            if not tg2_ok:
                btns.append([InlineKeyboardButton("🎵 Подписаться на IDN Records", url=tg2_url)])
            
            # VK привязка - всегда показываем
            if VK_ENABLED:
                if not vk_id:
                    btns.append([InlineKeyboardButton("🔗 Привязать VK профиль", callback_data="link_vk")])
                else:
                    btns.append([InlineKeyboardButton("🔄 Перепривязать VK", callback_data="link_vk")])
            
            btns.append([InlineKeyboardButton("🔄 Перепроверить", callback_data="check_all")])
            btns.append([InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")])
            
            # Удаляем старое сообщение и отправляем новое
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=text, 
                reply_markup=InlineKeyboardMarkup(btns), 
                parse_mode="Markdown"
            )

        elif data == "link_vk":
            # Запрашиваем VK ID для привязки
            logger.info("User %s clicked link_vk button", user.id)
            try:
                context.user_data["awaiting_vk"] = True
                kb = [[InlineKeyboardButton("❌ Отмена", callback_data="back_to_menu")]]
                
                # Проверяем есть ли уже привязанный VK
                current_vk = context.user_data.get("vk_id")
                if current_vk:
                    text = (
                        "🔄 Перепривязка VK аккаунта\n\n"
                        f"Текущий VK ID: {current_vk}\n\n"
                        "Отправьте новый ID вашего VK аккаунта:\n\n"
                        "Поддерживаемые форматы:\n"
                        "• Цифры: 123456789\n"
                        "• ID: id123456789\n"
                        "• Никнейм: durov, ivan_petrov\n\n"
                        "Как найти ID аккаунта:\n"
                        "1. Откройте свой профиль VK\n"
                        "2. Скопируйте из адресной строки:\n"
                        "   • vk.com/durov → отправьте: durov\n"
                        "   • vk.com/id123456789 → отправьте: 123456789\n\n"
                        "⚠️ Убедитесь, что подписки в профиле открыты для просмотра"
                    )
                else:
                    text = (
                        "🔗 Привязка VK аккаунта\n\n"
                        "Отправьте ID вашего VK аккаунта для проверки подписки:\n\n"
                        "Поддерживаемые форматы:\n"
                        "• Цифры: 123456789\n"
                        "• ID: id123456789\n"
                        "• Никнейм: durov, ivan_petrov\n\n"
                        "Как найти ID аккаунта:\n"
                        "1. Откройте свой профиль VK\n"
                        "2. Скопируйте из адресной строки:\n"
                        "   • vk.com/durov → отправьте: durov\n"
                        "   • vk.com/id123456789 → отправьте: 123456789\n\n"
                        "⚠️ Убедитесь, что подписки в профиле открыты для просмотра"
                    )
                
                # Удаляем старое сообщение (афишу) и отправляем новое
                try:
                    await query.message.delete()
                except Exception:
                    pass
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
                logger.info("Successfully showed VK link form to user %s", user.id)
            except Exception as e:
                logger.error("Failed to show VK link form to user %s: %s", user.id, e)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Произошла ошибка при открытии формы привязки VK.\n\n"
                         "Попробуйте еще раз или обратитесь к администратору.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]])
                )
        
        elif data == "show_current_poster":
            # Показать актуальную афишу (последнюю)
            all_posters = context.bot_data.get("all_posters", [])
            if all_posters:
                context.user_data["current_poster_index"] = len(all_posters) - 1
            # UX: удаляем старое сообщение и отправляем новое фото афиши
            try:
                await query.message.delete()
            except Exception:
                pass
            await show_main_menu(update, context)
        
        elif data == "poster":
            # Показать актуальную афишу (последнюю) - для совместимости
            all_posters = context.bot_data.get("all_posters", [])
            if all_posters:
                context.user_data["current_poster_index"] = len(all_posters) - 1
            try:
                await query.message.delete()
            except Exception:
                pass
            await show_main_menu(update, context)
        
        elif data == "open_admin":
            # Открыть админ-панель через callback
            await admin_panel(update, context)
        
        elif data == "back_to_menu":
            # Загружаем данные пользователя из БД перед показом меню
            await load_user_data_from_db(context, user.id)
            
            # Сбрасываем индекс афиши на последнюю (самую новую)
            all_posters = context.bot_data.get("all_posters", [])
            if all_posters:
                context.user_data["current_poster_index"] = len(all_posters) - 1
            try:
                await query.message.delete()
            except Exception:
                pass
            await show_main_menu(update, context)
        
        elif data == "poster_prev":
            # Переход к предыдущей афише
            all_posters = context.bot_data.get("all_posters", [])
            current_index = context.user_data.get("current_poster_index", len(all_posters) - 1 if all_posters else 0)
            if current_index > 0:
                context.user_data["current_poster_index"] = current_index - 1
            try:
                await query.message.delete()
            except Exception:
                pass
            await show_main_menu(update, context)
        
        elif data.startswith("delete_poster:"):
            try:
                poster_index = int(data.split(":", 1)[1])
                all_posters = context.bot_data.get("all_posters", [])
                
                if 0 <= poster_index < len(all_posters):
                    deleted_poster = all_posters.pop(poster_index)
                    context.bot_data["all_posters"] = all_posters
                    
                    # Если удаленная афиша была текущей, обновляем текущую
                    current_poster = context.bot_data.get("poster")
                    if current_poster == deleted_poster:
                        if all_posters:
                            context.bot_data["poster"] = all_posters[-1]
                        else:
                            context.bot_data.pop("poster", None)
                    
                    caption = deleted_poster.get("caption", "Без описания")
                    if len(caption) > 50:
                        caption = caption[:50] + "..."
                    
                    await query.edit_message_text(
                        f"✅ Афиша удалена: {caption}\n\nОсталось афиш: {len(all_posters)}"
                    )
                else:
                    await query.edit_message_text("❌ Неверный номер афиши")
            except (ValueError, IndexError):
                await query.edit_message_text("❌ Ошибка при удалении афиши")
        
        elif data == "cancel_delete":
            await query.edit_message_text("❌ Удаление отменено")
        
        elif data == "poster_next":
            # Переход к следующей афише
            all_posters = context.bot_data.get("all_posters", [])
            current_index = context.user_data.get("current_poster_index", len(all_posters) - 1 if all_posters else 0)
            if current_index < len(all_posters) - 1:
                context.user_data["current_poster_index"] = current_index + 1
            try:
                await query.message.delete()
            except Exception:
                pass
            await show_main_menu(update, context)
        
        elif data.startswith("gender_"):
            # Обработка выбора пола
            gender = data.split("_", 1)[1]
            context.user_data["gender"] = gender
            context.user_data["registration_step"] = "age"
            
            # Сохраняем пол в БД
            pool = get_db_pool(context)
            if pool:
                try:
                    await upsert_user(pool, tg_id=user.id, gender=gender, username=user.username)
                    logger.info("Gender saved to DB for user %s: %s", user.id, gender)
                except Exception as e:
                    logger.warning("Failed to save gender to DB: %s", e)
            
            gender_text = {
                "male": "мужской",
                "female": "женский"
            }.get(gender, "")
            
            await query.edit_message_text(
                f"Пол: {gender_text} ✅\n\n"
                "Теперь укажите ваш возраст (только число)\n"
                "Например: 18"
            )
        
        elif data == "past_event":
            # Уведомление о прошедшем мероприятии
            await query.answer("Это мероприятие уже прошло 📅")
        
        elif data.startswith("admin:"):
            sub = data.split(":", 1)[1]
            if user.id not in get_admins(context):
                await query.edit_message_text("Недостаточно прав.")
                return
            
            if sub == "create_poster":
                # init draft
                ud = context.user_data
                ud["poster_draft"] = {"step": "photo", "file_id": None, "caption": None, "ticket_url": None}
                await query.edit_message_text(
                    "Шаг 1/4: пришлите фото афиши",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Назад в панель", callback_data="admin:back_to_panel")],
                        [InlineKeyboardButton("❌ Отмена", callback_data="admin:cancel_poster")],
                    ]),
                )
            
            elif sub == "broadcast_now":
                await do_weekly_broadcast(context)
                await query.edit_message_text("Афиша отправлена всем ✅")
            
            elif sub == "set_ticket":
                context.user_data["awaiting_ticket"] = True
                await query.edit_message_text("Пришлите ссылку для кнопки «Купить билет»")
            
            elif sub == "delete_poster":
                # Удаляем текущую афишу
                current_poster = context.bot_data.pop("poster", None)
                if current_poster:
                    # Удаляем из списка всех афиш
                    all_posters = context.bot_data.get("all_posters", [])
                    if current_poster in all_posters:
                        all_posters.remove(current_poster)
                        context.bot_data["all_posters"] = all_posters
                    
                    # Если есть другие афиши, делаем последнюю текущей
                    if all_posters:
                        context.bot_data["poster"] = all_posters[-1]
                        await query.edit_message_text(f"Афиша удалена ✅\n\nОсталось афиш: {len(all_posters)}")
                    else:
                        await query.edit_message_text("Афиша удалена ✅\n\nАфиш больше нет.")
                else:
                    await query.edit_message_text("Нет афиши для удаления ❌")
            
            elif sub == "broadcast_text":
                context.user_data["awaiting_broadcast_text"] = True
                await query.edit_message_text("Пришлите текст рассылки одним сообщением")
            
            elif sub == "stats":
                count = len(get_known_users(context))
                await query.edit_message_text(f"Пользователей: {count}")
            
            elif sub == "back_to_panel":
                context.user_data.pop("poster_draft", None)
                await admin_panel(update, context)
            
            elif sub == "confirm_poster":
                draft = context.user_data.get("poster_draft") or {}
                # Validate poster before saving
                if not draft.get("file_id"):
                    await query.edit_message_text("❌ Не загружено фото афиши. Начните заново.")
                    return
                caption_ok = is_valid_caption(draft.get("caption") or "")
                link_ok = (not draft.get("ticket_url")) or is_valid_url(draft.get("ticket_url"))
                if not caption_ok:
                    await query.edit_message_text("❌ Слишком длинная подпись. Максимум 1024 символа.")
                    return
                if not link_ok:
                    await query.edit_message_text("❌ Некорректная ссылка на билеты. Укажите URL формата https://...")
                    return
                
                poster = {"file_id": draft["file_id"], "caption": draft.get("caption") or "", "ticket_url": draft.get("ticket_url")}
                context.bot_data["poster"] = poster
                
                # Добавляем афишу в список всех афиш
                all_posters = context.bot_data.get("all_posters", [])
                all_posters.append(poster)
                context.bot_data["all_posters"] = all_posters
                
                context.user_data.pop("poster_draft", None)
                # Опубликовать в чат админу одним сообщением (фото+текст+кнопка)
                rm = None
                if poster.get("ticket_url"):
                    rm = InlineKeyboardMarkup([[InlineKeyboardButton("Купить билет", url=poster["ticket_url"])]])
                await context.bot.send_photo(
                    chat_id=query.message.chat_id, 
                    photo=poster["file_id"], 
                    caption=poster.get("caption", ""), 
                    reply_markup=rm
                )
                await query.edit_message_text(f"Афиша сохранена и опубликована ✅\n\nВсего афиш: {len(all_posters)}")
            
            elif sub == "cancel_poster":
                context.user_data.pop("poster_draft", None)
                await query.edit_message_text("Создание афиши отменено ❌")
            
            elif sub == "users_count":
                # Показать количество пользователей
                pool = get_db_pool(context)
                if pool:
                    try:
                        stats = await get_user_stats(pool)
                        text = f"👥 **Статистика пользователей**\n\n"
                        text += f"• Всего пользователей: {stats.get('total_users', 0)}\n"
                        text += f"• С привязанным VK: {stats.get('users_with_vk', 0)}\n"
                        text += f"• Мужчин: {stats.get('male_users', 0)}\n"
                        text += f"• Женщин: {stats.get('female_users', 0)}\n"
                        text += f"• Зарегистрировано сегодня: {stats.get('today_registrations', 0)}"
                    except Exception as e:
                        text = f"❌ Ошибка получения статистики: {e}"
                else:
                    text = f"👥 Пользователей в кеше: {len(get_known_users(context))}"
                
                kb = [[InlineKeyboardButton("🔙 Назад в панель", callback_data="admin:refresh")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            
            elif sub == "list_posters":
                # Показать список всех афиш
                all_posters = context.bot_data.get("all_posters", [])
                if not all_posters:
                    text = "📋 Список афиш пуст"
                else:
                    text = f"📋 **Список всех афиш ({len(all_posters)}):**\n\n"
                    current_poster = context.bot_data.get("poster")
                    
                    for i, poster in enumerate(all_posters):
                        caption = poster.get("caption", "Без описания")
                        if len(caption) > 40:
                            caption = caption[:40] + "..."
                        
                        status = "🟢 ТЕКУЩАЯ" if poster == current_poster else "⚪"
                        ticket_status = "🎫" if poster.get("ticket_url") else "❌"
                        
                        text += f"{i+1}. {status} {caption}\n   Билеты: {ticket_status}\n\n"
                
                kb = [[InlineKeyboardButton("🔙 Назад в панель", callback_data="admin:refresh")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            
            elif sub == "check_by_username":
                # Проверка подписки по username/ID в режиме непрерывной проверки
                context.user_data["awaiting_username_check"] = True
                context.user_data["continuous_check_mode"] = True
                kb = [[InlineKeyboardButton("🔙 Завершить проверку", callback_data="admin:stop_check")]]
                await query.edit_message_text(
                    "🔍 **Режим массовой проверки активирован**\n\n"
                    "Отправьте username (с @) или Telegram ID пользователя:\n\n"
                    "**Примеры:**\n"
                    "• Username: `@durov`\n"
                    "• ID: `123456789`\n\n"
                    "💡 После проверки сразу можно вводить следующий username\n"
                    "Нажмите '🔙 Завершить проверку' для выхода",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
            
            elif sub == "stop_check":
                # Завершение режима непрерывной проверки
                context.user_data["awaiting_username_check"] = False
                context.user_data["continuous_check_mode"] = False
                await query.edit_message_text(
                    "✅ Режим проверки завершен\n\n"
                    "Возвращение в админ-панель...",
                    parse_mode="Markdown"
                )
                await asyncio.sleep(1)
                await admin_panel(update, context)
            
            elif sub == "refresh":
                # Обновить админ-панель
                await admin_panel(update, context)
    
    except Exception as e:
        logger.exception("handle_buttons failed: %s", e)
        try:
            await query.answer("Произошла ошибка, попробуйте еще раз", show_alert=False)
        except Exception:
            pass


async def send_poster_to_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    all_posters = context.bot_data.get("all_posters", [])
    if not all_posters:
        await context.bot.send_message(chat_id, "Афиш пока нет ;(")
        return
    
    # Берем последнюю (самую новую) афишу для рассылки
    poster = all_posters[-1]
    file_id = poster.get("file_id")
    caption = poster.get("caption", "")
    ticket_url = poster.get("ticket_url")
    
    try:
        reply_markup = None
        if ticket_url:
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎫 Купить билет", url=ticket_url)]])
        await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, reply_markup=reply_markup)
    except Forbidden:
        logger.info("Cannot send message to chat_id %s (blocked or privacy)", chat_id)
    except Exception as e:
        logger.exception("Failed to send poster to %s: %s", chat_id, e)


# ----------------------
# Admin commands
# ----------------------

async def admin_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return bool(user and (user.id in get_admins(context)))


async def save_poster(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_only(update, context):
        return
    msg = update.message
    if not msg:
        return
    # If command is a reply to a photo, use that; otherwise, try this message
    photo_msg = msg.reply_to_message if (msg.reply_to_message and msg.reply_to_message.photo) else msg
    if not photo_msg.photo:
        await msg.reply_text("Пожалуйста, ответь этой командой на сообщение с фото афиши и подписью.")
        return
    largest = photo_msg.photo[-1]
    file_id = largest.file_id
    caption = photo_msg.caption or ""
    poster = context.bot_data.get("poster", {})
    ticket_url = poster.get("ticket_url")
    context.bot_data["poster"] = {"file_id": file_id, "caption": caption, "ticket_url": ticket_url}
    await msg.reply_text("Афиша сохранена ✅ (фото и подпись). Для ссылки используйте /set_ticket <url>")


async def set_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_only(update, context):
        return
    msg = update.message
    if not msg:
        return
    if not context.args:
        await msg.reply_text("Укажи ссылку: /set_ticket https://...")
        return
    url = context.args[0].strip()
    poster = context.bot_data.get("poster") or {}
    poster["ticket_url"] = url
    context.bot_data["poster"] = poster
    await msg.reply_text("Ссылка на покупку билета сохранена ✅")


async def delete_poster(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_only(update, context):
        return
    context.bot_data.pop("poster", None)
    await update.message.reply_text("Афиша удалена. Загрузите новую с /save_poster")


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отобразить улучшенную админ-панель с inline кнопками."""
    user = update.effective_user
    admins = get_admins(context)
    if not admins and user:
        admins.add(user.id)
    if not user or user.id not in admins:
        await update.effective_chat.send_message("Эта команда доступна только администратору.")
        return
    
    # Получаем статистику из БД
    pool = get_db_pool(context)
    stats = {}
    if pool:
        try:
            stats = await get_user_stats(pool)
        except Exception as e:
            logger.warning("Failed to get stats: %s", e)
    
    # Показать информацию об афишах и пользователях
    all_posters = context.bot_data.get("all_posters", [])
    current_poster = context.bot_data.get("poster")
    
    status_text = "🛠 **Админ-панель TusaBot**\n\n"
    
    # Статистика афиш
    status_text += "📊 **Афиши:**\n"
    status_text += f"• Всего афиш: {len(all_posters)}\n"
    if current_poster:
        status_text += "• Текущая афиша: ✅ есть\n"
        if current_poster.get("ticket_url"):
            status_text += "• Ссылка на билеты: ✅ есть\n"
        else:
            status_text += "• Ссылка на билеты: ❌ нет\n"
    else:
        status_text += "• Текущая афиша: ❌ нет\n"
    
    # Статистика пользователей из БД
    status_text += "\n👥 **Пользователи:**\n"
    if stats:
        status_text += f"• Всего: {stats.get('total_users', 0)}\n"
        status_text += f"• С VK: {stats.get('users_with_vk', 0)}\n"
        status_text += f"• Мужчин: {stats.get('male_users', 0)}\n"
        status_text += f"• Женщин: {stats.get('female_users', 0)}\n"
        status_text += f"• Сегодня: {stats.get('today_registrations', 0)}\n"
    else:
        status_text += f"• Всего: {len(get_known_users(context))}\n"
    
    # Inline кнопки для удобства
    admin_buttons = [
        # Управление афишами
        [
            InlineKeyboardButton("🧩 Создать афишу", callback_data="admin:create_poster"),
            InlineKeyboardButton("📋 Список афиш", callback_data="admin:list_posters")
        ],
        [
            InlineKeyboardButton("📤 Разослать афишу", callback_data="admin:broadcast_now"),
            InlineKeyboardButton("🗑 Удалить афишу", callback_data="admin:delete_poster")
        ],
        # Настройки и рассылки
        [
            InlineKeyboardButton("🔗 Задать ссылку", callback_data="admin:set_ticket"),
            InlineKeyboardButton("📝 Текстовая рассылка", callback_data="admin:broadcast_text")
        ],
        # Пользователи
        [
            InlineKeyboardButton("🔍 Проверка по нику", callback_data="admin:check_by_username"),
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:refresh")
        ],
        [
            InlineKeyboardButton("👥 Пользователи", callback_data="admin:users_count")
        ],
        # Выход
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]
    ]
    
    await update.effective_chat.send_message(
        status_text, 
        reply_markup=InlineKeyboardMarkup(admin_buttons),
        parse_mode="Markdown"
    )


async def make_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавить администратора: /make_admin <user_id> или в ответ на сообщ. пользователя."""
    user = update.effective_user
    if not user or user.id not in get_admins(context):
        await update.effective_chat.send_message("Эта команда доступна только администратору.")
        return
    target_id = None
    if context.args and context.args[0].isdigit():
        target_id = int(context.args[0])
    elif update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
    if not target_id:
        await update.effective_chat.send_message("Укажи ID: /make_admin <user_id> или ответь на его сообщение.")
        return
    admins = get_admins(context)
    admins.add(target_id)
    await update.effective_chat.send_message(f"Пользователь {target_id} добавлен в администраторы ✅")


async def broadcast_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_only(update, context):
        return
    await do_weekly_broadcast(context)
    await update.message.reply_text("Разослал текущую афишу всем известным пользователям ✅")


async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_only(update, context):
        return
    if not context.args:
        await update.message.reply_text("Формат: /broadcast_text ваш текст")
        return
    text = update.message.text.partition(' ')[2]
    for uid in list(get_known_users(context)):
        try:
            await context.bot.send_message(uid, text)
        except Forbidden:
            logger.info("Cannot message user %s (blocked)", uid)
        except Exception as e:
            logger.warning("Broadcast text failed to %s: %s", uid, e)


# ----------------------
# Weekly jobs
# ----------------------

async def finalize_previous_week_and_reengage(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(timezone.utc)
    prev_key = previous_week_key(now)

    for uid in list(get_known_users(context)):
        ud = context.application.user_data.setdefault(uid, {})
        attended_weeks: Set[str] = ud.get("attended_weeks", set())
        missed_in_row = int(ud.get("missed_in_row", 0))
        if prev_key in attended_weeks:
            ud["missed_in_row"] = 0
        else:
            missed_in_row += 1
            ud["missed_in_row"] = missed_in_row
            if missed_in_row > 2:
                try:
                    await context.bot.send_message(uid, REENGAGE_TEXT)
                except Forbidden:
                    logger.info("Cannot message user %s (blocked)", uid)
                except Exception as e:
                    logger.warning("Re-engage send failed to %s: %s", uid, e)
        context.application.user_data[uid] = ud


async def do_weekly_broadcast(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Еженедельная рассылка афиши всем пользователям в Telegram и VK"""
    known_users = get_known_users(context)
    if not known_users:
        logger.info("No users to broadcast to")
        return
    
    # Получаем последнюю афишу для рассылки
    all_posters = context.bot_data.get("all_posters", [])
    if not all_posters:
        logger.info("No posters to broadcast")
        return
    
    latest_poster = all_posters[-1]
    
    # Рассылка в Telegram
    success_count = 0
    for user_id in known_users:
        try:
            await send_poster_to_chat(context, user_id)
            success_count += 1
        except Exception as e:
            logger.warning("Failed to send poster to user %s: %s", user_id, e)
    
    # Рассылка в VK
    vk_success = False
    if VK_ENABLED and VK_TOKEN:
        try:
            vk_success = await broadcast_to_vk(latest_poster)
        except Exception as e:
            logger.warning("Failed to broadcast to VK: %s", e)
    
    logger.info("Weekly broadcast completed: %d/%d users (Telegram), VK: %s", 
                success_count, len(known_users), "✅" if vk_success else "❌")
    
    # Отправляем админу отчет
    admin_id = ADMIN_USER_ID
    if admin_id:
        try:
            report = f"📊 Рассылка завершена:\n"
            report += f"Telegram: {success_count}/{len(known_users)} пользователей\n"
            report += f"VK: {'✅ Опубликовано' if vk_success else '❌ Ошибка'}"
            await context.bot.send_message(admin_id, report)
        except Exception as e:
            logger.warning("Failed to send broadcast report to admin: %s", e)


async def weekly_job(context: CallbackContext) -> None:
    await do_weekly_broadcast(context)


def schedule_weekly(app: Application) -> None:
    job_queue = app.job_queue
    send_time_utc = time(hour=WEEKLY_HOUR_UTC, minute=WEEKLY_MINUTE, tzinfo=pytz.utc)
    job_queue.run_daily(weekly_job, time=send_time_utc, days=(WEEKLY_DAY,))
    logger.info(
        "Scheduled weekly broadcast: day=%s at %02d:%02d UTC (local %02d:%02d MSK)",
        WEEKLY_DAY,
        WEEKLY_HOUR_UTC,
        WEEKLY_MINUTE,
        WEEKLY_HOUR_LOCAL,
        WEEKLY_MINUTE,
    )


async def _notify_admin_start(_: CallbackContext) -> None:
    if ADMIN_USER_ID:
        try:
            await _.bot.send_message(ADMIN_USER_ID, "Бот запущен ✅")
        except Exception:
            pass


# ----------------------
# Registration Handler
# ----------------------

async def handle_registration_step(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user, user_data: dict, reg_step: str) -> None:
    """Обработка шагов регистрации"""
    pool = get_db_pool(context)
    
    if reg_step == "name":
        name = text.strip()
        user_data["name"] = name
        user_data["registration_step"] = "gender"
        
        # Создаем минимальную запись в БД с именем
        if pool:
            try:
                await upsert_user(pool, tg_id=user.id, name=name, username=user.username)
                logger.info("Name saved to DB for user %s: %s", user.id, name)
            except Exception as e:
                logger.warning("Failed to save name to DB: %s", e)
        
        kb = [
            [InlineKeyboardButton("👨 Мужской", callback_data="gender_male")],
            [InlineKeyboardButton("👩 Женский", callback_data="gender_female")]
        ]
        await update.message.reply_text(
            f"Приятно познакомиться, {name}! 😊\n\n"
            "Укажите ваш пол:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    
    elif reg_step == "age":
        # Проверяем формат возраста
        try:
            age = int(text.strip())
            if age < 14 or age > 100:
                await update.message.reply_text(
                    "❌ Неверный возраст!\n\n"
                    "Пожалуйста, введите возраст от 14 до 100 лет\n"
                    "Например: 25"
                )
                return
                
            user_data["age"] = age
            user_data["registered"] = True
            user_data.pop("registration_step", None)
            
            # Завершаем регистрацию - берем имя из памяти, а если нет - из БД
            name = user_data.get("name")
            if not name and pool:
                try:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow("SELECT name FROM users WHERE tg_id = $1", user.id)
                        if row and row['name']:
                            name = row['name']
                            user_data["name"] = name
                except Exception as e:
                    logger.warning("Failed to load name from DB: %s", e)
            
            if not name:
                name = "Не указано"
            
            gender_text = {
                "male": "мужской",
                "female": "женский"
            }.get(user_data.get("gender", ""), "не указан")
            
            # Обновляем все данные в БД
            if pool:
                try:
                    await upsert_user(
                        pool,
                        tg_id=user.id,
                        name=name,
                        gender=user_data.get("gender"),
                        age=age,
                        vk_id=user_data.get("vk_id"),
                        username=user.username,
                    )
                    logger.info("Registration completed for user %s: %s", user.id, name)
                except Exception as e:
                    logger.warning("DB upsert after registration failed: %s", e)
            
            kb = [[InlineKeyboardButton("🎉 Перейти в меню", callback_data="back_to_menu")]]
            await update.message.reply_text(
                f"🎉 Отлично! Вы прошли регистрацию!\n\n"
                f"📝 Ваши данные:\n"
                f"• Имя: {name}\n"
                f"• Пол: {gender_text}\n"
                f"• Возраст: {age} лет\n\n"
                f"Теперь вы можете посещать наши вечеринки! 🥳",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            return
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат возраста!\n\n"
                "Пожалуйста, введите возраст числом\n"
                "Например: 18"
            )
            return


# ----------------------
# Bootstrap
# ----------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Registration flow
    if update.message and update.message.text:
        text = update.message.text
        user = update.effective_user
        user_data = context.user_data
        
        # ПРИОРИТЕТ 1: Обработка регистрации (должна быть ПЕРВОЙ!)
        reg_step = user_data.get("registration_step")
        if reg_step:
            # Пользователь в процессе регистрации - обрабатываем только это
            await handle_registration_step(update, context, text, user, user_data, reg_step)
            return
        
        # ПРИОРИТЕТ 2: Проверка подписки по username/ID (для админов)
        if user_data.get("awaiting_username_check"):
            # НЕ сбрасываем флаг здесь! Он будет сброшен после обработки, если НЕ в режиме continuous
            
            input_text = text.strip()
            target_user_id = None
            username_display = input_text
            
            try:
                # Проверяем, это ID или username
                if input_text.isdigit():
                    # Это ID
                    target_user_id = int(input_text)
                    username_display = f"ID {input_text}"
                else:
                    # Это username - ищем в БД
                    username = input_text.lstrip('@')
                    username_display = f"@{username}"
                    
                    # Ищем пользователя в БД по username
                    pool = get_db_pool(context)
                    if pool:
                        try:
                            user_in_db = await get_user_by_username(pool, username)
                            if user_in_db:
                                target_user_id = user_in_db.get("tg_id")
                                logger.info(f"Found user by username @{username}: ID={target_user_id}")
                            else:
                                # Если не нашли в БД, пробуем через get_chat (для публичных профилей)
                                try:
                                    target_chat = await context.bot.get_chat(f"@{username}")
                                    target_user_id = target_chat.id
                                    logger.info(f"Found user by get_chat @{username}: ID={target_user_id}")
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"Error searching user by username in DB: {e}")
                    
                    if not target_user_id:
                        # Проверяем режим
                        if context.user_data.get("continuous_check_mode"):
                            kb = [[InlineKeyboardButton("🔙 Завершить проверку", callback_data="admin:stop_check")]]
                            await update.message.reply_text(
                                f"❌ Пользователь @{username} не найден\n\n"
                                f"Возможные причины:\n"
                                f"• Username указан неверно\n"
                                f"• Пользователь не взаимодействовал с ботом\n"
                                f"• Профиль скрыт или удален\n\n"
                                f"💡 Попробуйте ввести другой username или используйте Telegram ID",
                                reply_markup=InlineKeyboardMarkup(kb)
                            )
                            # НЕ сбрасываем флаги
                        else:
                            context.user_data["awaiting_username_check"] = False
                            await update.message.reply_text(
                                f"❌ Пользователь @{username} не найден\n\n"
                                f"Возможные причины:\n"
                                f"• Username указан неверно\n"
                                f"• Пользователь не взаимодействовал с ботом\n"
                                f"• Профиль скрыт или удален\n\n"
                                f"💡 **Рекомендация:** Используйте Telegram ID\n"
                                f"Попросите пользователя написать @userinfobot",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в панель", callback_data="admin:refresh")]])
                            )
                        return
                
                if not target_user_id:
                    await update.message.reply_text(
                        "❌ Не удалось определить ID пользователя",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в панель", callback_data="admin:refresh")]])
                    )
                    return
                
                # Проверяем подписки на оба TG канала
                tg1_ok, tg2_ok = await is_user_subscribed(context, target_user_id)
                
                # Проверяем VK (если есть привязка)
                pool = get_db_pool(context)
                vk_id = None
                vk_status = None
                if pool:
                    try:
                        user_in_db = await get_user(pool, target_user_id)
                        vk_id = user_in_db.get("vk_id") if user_in_db else None
                        if vk_id and VK_ENABLED:
                            vk_status = await is_user_subscribed_vk(vk_id)
                    except Exception:
                        pass
                
                # Формируем отчет (экранируем специальные символы Markdown)
                def escape_markdown(text):
                    """Экранирует специальные символы для Markdown"""
                    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
                    for char in special_chars:
                        text = text.replace(char, '\\' + char)
                    return text
                
                username_safe = escape_markdown(str(username_display))
                
                report = f"🔍 **Проверка подписок для {username_safe}**\n\n"
                report += f"👤 Telegram ID: `{target_user_id}`\n\n"
                report += "📺 **Telegram каналы:**\n"
                report += f"{'✅' if tg1_ok else '❌'} {CHANNEL_USERNAME} \\(Largent MSK\\)\n"
                report += f"{'✅' if tg2_ok else '❌'} {CHANNEL_USERNAME_2} \\(IDN Records\\)\n\n"
                
                if VK_ENABLED:
                    report += "🎵 **VK группа:**\n"
                    if not vk_id:
                        report += "⚠️ VK профиль не привязан\n"
                    elif vk_status is None:
                        report += f"❓ VK ID: {vk_id} \\- не удалось проверить\n"
                    elif vk_status:
                        report += f"✅ VK ID: {vk_id}\n"
                    else:
                        report += f"❌ VK ID: {vk_id} \\- не подписан\n"
                
                all_ok = tg1_ok and tg2_ok and (not VK_ENABLED or vk_status)
                report += f"\n{'🎉 **Все подписки активны\\!**' if all_ok else '⚠️ **Не все подписки активны**'}"
                
                # Кнопки в зависимости от режима
                if context.user_data.get("continuous_check_mode"):
                    # Режим непрерывной проверки - оставляем флаг активным
                    kb = [[InlineKeyboardButton("🔙 Завершить проверку", callback_data="admin:stop_check")]]
                    await update.message.reply_text(
                        report + "\n\n💡 Введите следующий username или нажмите 'Завершить проверку'",
                        reply_markup=InlineKeyboardMarkup(kb),
                        parse_mode="MarkdownV2"
                    )
                    # НЕ сбрасываем флаг awaiting_username_check!
                else:
                    # Обычный режим - одна проверка
                    context.user_data["awaiting_username_check"] = False
                    await update.message.reply_text(
                        report,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в панель", callback_data="admin:refresh")]]),
                        parse_mode="MarkdownV2"
                    )
                return
                
            except Exception as e:
                logger.error("Error checking subscriptions by username: %s", e)
                
                # Проверяем режим
                if context.user_data.get("continuous_check_mode"):
                    kb = [[InlineKeyboardButton("🔙 Завершить проверку", callback_data="admin:stop_check")]]
                    await update.message.reply_text(
                        f"❌ Ошибка при проверке подписок:\n{str(e)}\n\n"
                        f"💡 Попробуйте ввести другой username",
                        reply_markup=InlineKeyboardMarkup(kb)
                    )
                    # НЕ сбрасываем флаги
                else:
                    context.user_data["awaiting_username_check"] = False
                    await update.message.reply_text(
                        f"❌ Ошибка при проверке подписок:\n{str(e)}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в панель", callback_data="admin:refresh")]])
                    )
                return
        
        # Админские команды теперь только через inline кнопки в админ-панели
        # Оставляем только обработку ввода данных
        # Handle admin text inputs
        if context.user_data.get("awaiting_ticket"):
            context.user_data["awaiting_ticket"] = False
            url = update.message.text.strip()
            poster = context.bot_data.get("poster") or {}
            poster["ticket_url"] = url
            context.bot_data["poster"] = poster
            await update.message.reply_text("Ссылка сохранена ✅")
            return
            
        if context.user_data.get("awaiting_broadcast_text"):
            context.user_data["awaiting_broadcast_text"] = False
            text = update.message.text
            for uid in list(get_known_users(context)):
                try:
                    await context.bot.send_message(uid, text)
                except Forbidden:
                    logger.info("Cannot message user %s (blocked)", uid)
                except Exception as e:
                    logger.warning("Broadcast text failed to %s: %s", uid, e)
            await update.message.reply_text("Текстовая рассылка отправлена ✅")
            return
        
        # Poster draft: expecting caption or link
        draft = context.user_data.get("poster_draft")
        if draft:
            step = draft.get("step")
            if step == "caption":
                draft["caption"] = update.message.text
                draft["step"] = "link"
                context.user_data["poster_draft"] = draft
                await update.message.reply_text(
                    "Шаг 3/4: пришлите ссылку для кнопки «Купить билет»",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("❌ Отмена", callback_data="admin:cancel_poster")],
                        [InlineKeyboardButton("◀️ Назад в панель", callback_data="admin:back_to_panel")],
                    ]),
                )
                return
            if step == "link":
                url = update.message.text.strip()
                draft["ticket_url"] = url
                draft["step"] = "preview"
                context.user_data["poster_draft"] = draft
                # Предпросмотр: отправим фото с подписью и кнопкой
                rm = None
                if url:
                    rm = InlineKeyboardMarkup([[InlineKeyboardButton("Купить билет", url=url)]])
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=draft["file_id"],
                    caption=draft.get("caption") or "",
                    reply_markup=rm,
                )
                await update.message.reply_text(
                    "Шаг 4/4: подтвердить публикацию?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Подтвердить", callback_data="admin:confirm_poster")],
                        [InlineKeyboardButton("❌ Отмена", callback_data="admin:cancel_poster")],
                        [InlineKeyboardButton("◀️ Назад в панель", callback_data="admin:back_to_panel")],
                    ]),
                )
                return
        if VK_ENABLED and context.user_data.get("awaiting_vk"):
            context.user_data["awaiting_vk"] = False
            vk_input = update.message.text.strip()
            
            # Проверяем формат: цифры, id123456, или никнейм
            if not vk_input:
                kb = [[InlineKeyboardButton("🔗 Попробовать еще раз", callback_data="link_vk")]]
                await update.message.reply_text(
                    "❌ **Пустое поле**\n\n"
                    "Введите ваш VK ID или никнейм",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
                return
            
            # Проверяем что это валидный формат VK ID/никнейма
            is_valid = (
                vk_input.isdigit() or  # только цифры: 123456789
                (vk_input.lower().startswith('id') and vk_input[2:].isdigit()) or  # id123456789
                (len(vk_input) >= 3 and vk_input.replace('_', '').replace('.', '').isalnum())  # никнейм: durov, ivan_petrov
            )
            
            if not is_valid:
                kb = [[InlineKeyboardButton("🔗 Попробовать еще раз", callback_data="link_vk")]]
                await update.message.reply_text(
                    "❌ **Неверный формат VK ID/никнейма**\n\n"
                    "Поддерживаемые форматы:\n"
                    "• **Цифры:** 123456789\n"
                    "• **ID:** id123456789\n"
                    "• **Никнейм:** durov, ivan_petrov\n\n"
                    "📍 Найти можно в адресной строке профиля VK",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
                return
            
            # Проверяем была ли это перепривязка
            was_relink = bool(context.user_data.get("vk_id"))
            
            vk_id = vk_input
            context.user_data["vk_id"] = vk_id
            
            # Persist VK link to database
            pool = get_db_pool(context)
            if pool:
                try:
                    await set_vk_id(pool, user.id, vk_id)
                    # Обновляем кеш
                    vk_cache = context.bot_data.get("user_vk_cache", {})
                    vk_cache[user.id] = vk_id
                    context.bot_data["user_vk_cache"] = vk_cache
                    logger.info("VK ID %s linked to user %s", vk_id, user.id)
                except Exception as e:
                    logger.warning("DB set_vk_id failed: %s", e)
            
            # Проверяем подписку сразу после привязки
            status = await is_user_subscribed_vk(vk_id)
            
            kb = [[InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")]]
            
            if status is None:
                action_text = "перепривязан" if was_relink else "привязан"
                await update.message.reply_text(
                    f"✅ **VK профиль успешно {action_text}!**",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
            elif status:
                action_text = "перепривязан" if was_relink else "привязан"
                await update.message.reply_text(
                    f"✅ **VK профиль успешно {action_text}!**",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
            else:
                action_text = "перепривязан" if was_relink else "привязан"
                await update.message.reply_text(
                    f"✅ **VK профиль успешно {action_text}!**",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="Markdown"
                )
            return


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Poster draft: expecting photo at step 'photo'
    draft = context.user_data.get("poster_draft")
    if draft and draft.get("step") == "photo" and update.message.photo:
        largest = update.message.photo[-1]
        draft["file_id"] = largest.file_id
        draft["step"] = "caption"
        context.user_data["poster_draft"] = draft
        await update.message.reply_text(
            "Шаг 2/4: пришлите текст (подпись) для афиши",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="admin:cancel_poster")],
                [InlineKeyboardButton("◀️ Назад в панель", callback_data="admin:back_to_panel")],
            ]),
        )
        return
    # если фото вне мастера — ничего не делаем


def build_app() -> Application:
    """Build and configure the Application"""
    ensure_data_dir()
    persistence = PicklePersistence(filepath=str(PERSISTENCE_FILE))
    
    # Create request with timeout and proxy support
    request = None
    if PROXY_URL:
        from httpx import AsyncClient
        from telegram.request import HTTPXRequest
        client = AsyncClient(proxies=PROXY_URL, timeout=30.0)
        request = HTTPXRequest(http_client=client)
    
    app = ApplicationBuilder().token(BOT_TOKEN).persistence(persistence).request(request).build()

    # DB lifecycle
    async def _on_startup(app: Application):
        try:
            pool = await create_pool()
            await init_schema(pool)
            app.bot_data["db_pool"] = pool
            
            # Загружаем существующих пользователей из БД
            user_ids = await get_all_user_ids(pool)
            app.bot_data["known_users"] = set(user_ids)
            
            # Загружаем VK данные для кеширования
            vk_data = await load_user_vk_data(pool)
            app.bot_data["user_vk_cache"] = vk_data
            
            # Настраиваем команды бота (только для обычных пользователей)
            commands = [
                BotCommand("start", "Начать работу с ботом"),
                BotCommand("menu", "Главное меню")
            ]
            await app.bot.set_my_commands(commands)
            
            logger.info("DB pool initialized, schema ready, loaded %d users, commands set", len(user_ids))
        except Exception as e:
            logger.error("Failed to init DB: %s", e)

    async def _on_shutdown(app: Application):
        pool = app.bot_data.get("db_pool")
        if pool:
            try:
                await pool.close()
                logger.info("DB pool closed")
            except Exception as e:
                logger.warning("Error closing DB pool: %s", e)

    async def _notify_admin_start(context: ContextTypes.DEFAULT_TYPE):
        # Уведомление админу убрано по запросу
        pass

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Register lifecycle handlers - удалено неправильный handler
    app.post_init = _on_startup
    app.post_shutdown = _on_shutdown

    schedule_weekly(app)
    # Notify admin shortly after start
    app.job_queue.run_once(_notify_admin_start, when=1)
    return app


def main() -> None:
    app = build_app()
    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
