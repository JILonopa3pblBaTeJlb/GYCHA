# messenger.py — Модуль приема и модерации сообщений от слушателей
import re
import asyncio
import os
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from config_loader import conf

# Загрузка настроек бота из конфигурации
API_TOKEN = getattr(conf.TELEGRAM_BOTS, "messenger_bot_token")
# Параметры отображения и фильтрации
MAX_LINES = getattr(conf.MESSENGER, "max_lines", 3)
MAX_WIDTH = getattr(conf.MESSENGER, "max_width", 67)
BROADCAST_MAX = getattr(conf.MESSENGER, "broadcast_max", 92)
BLACKLIST_FILE = getattr(conf.PATHS, "blacklist_file", "blacklist.txt")
BROADCAST_FILE = getattr(conf.PATHS, "broadcast_file", "broadcast.txt")
BLACKLIST_CACHE_TTL = getattr(conf.MESSENGER, "blacklist_ttl_sec", 60)

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Внутреннее состояние модуля
_state = {
    "message_block": [],   # Список строк для блока "Дорогая редакция"
    "broadcast_line": ""   # Текущая строка для бегущей строки
}

# Переменные для кэширования черного списка
_blacklist_cache = []
_blacklist_regex = None
_last_blacklist_read = 0

# Регулярное выражение для очистки текста от опасных символов (для drawtext в FFmpeg)
ALLOWED_CHARS_RE = re.compile(r'[^a-zA-Zа-яА-ЯЁё0-9\s\n",.:!?-]')

def load_blacklisted_words() -> list[str]:
    """
    Загружает запрещенные слова из файла и компилирует их в один регулярный паттерн.
    Реализовано кэширование: файл перечитывается не чаще, чем раз в BLACKLIST_CACHE_TTL секунд,
    чтобы не нагружать диск при каждом входящем сообщении.
    """
    global _blacklist_cache, _last_blacklist_read, _blacklist_regex
    
    now = time.time()
    if now - _last_blacklist_read < BLACKLIST_CACHE_TTL and _blacklist_regex is not None:
        return _blacklist_cache
        
    try:
        if os.path.exists(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                words = [line.strip().lower() for line in f if line.strip()]
            
            _blacklist_cache = words
            if words:
                # Создаем паттерн типа (слово1|слово2|...) для быстрого поиска
                pattern_str = "|".join(re.escape(w) for w in words)
                _blacklist_regex = re.compile(pattern_str, re.IGNORECASE)
            else:
                _blacklist_regex = None
        else:
            _blacklist_cache = []
            _blacklist_regex = None
    except Exception:
        pass
        
    _last_blacklist_read = now
    return _blacklist_cache

def contains_blacklisted(text: str) -> bool:
    """
    Проверяет текст на наличие слов из черного списка с помощью регулярного выражения.
    """
    load_blacklisted_words()
    if not _blacklist_regex:
        return False
    return bool(_blacklist_regex.search(text))

def clean_text(text: str) -> str:
    """
    Удаляет символы, которые не входят в разрешенный набор. 
    Это предотвращает инъекции команд в FFmpeg и проблемы с отрисовкой шрифтов.
    """
    return ALLOWED_CHARS_RE.sub('', text)

def format_text_to_lines(text: str) -> list[str]:
    """
    Разбивает длинный текст на строки фиксированной ширины.
    Используется для красивой верстки сообщений в блоке интерфейса.
    """
    words = text.split()
    lines = []
    current_line = ""
    for w in words:
        # Проверяем, влезет ли слово в текущую строку
        if len(current_line) + len(w) + (1 if current_line else 0) <= MAX_WIDTH:
            current_line += (" " + w) if current_line else w
        else:
            lines.append(current_line)
            current_line = w
            if len(lines) == MAX_LINES: break
    if len(lines) < MAX_LINES and current_line:
        lines.append(current_line)
    return lines[:MAX_LINES]

async def update_broadcast_file(content: str):
    """
    Записывает текст в файл для FFmpeg. 
    Используется asyncio.to_thread, чтобы синхронная запись в файл не блокировала
    основной цикл бота при высокой нагрузке.
    """
    try:
        def sync_write():
            with open(BROADCAST_FILE, "w", encoding="utf-8") as f:
                f.write(content)
        await asyncio.to_thread(sync_write)
    except Exception:
        pass

@dp.message()
async def handler(message: Message):
    """
    Основной обработчик всех входящих сообщений.
    """
    if not message.text or message.text == "/start": return
    
    # Формируем никнейм автора
    user_nick = message.from_user.username or message.from_user.full_name or "Anonymous"
    user_nick = clean_text(user_nick)
    
    # Очищаем основной текст
    clean_body = clean_text(message.text)
    if not clean_body.strip(): return

    # Проверка на цензуру
    if contains_blacklisted(clean_body) or contains_blacklisted(user_nick):
        return

    # Логика обновления бегущей строки
    broadcast_content = f"@{user_nick}: {clean_body}".replace("\n", " ")
    if len(broadcast_content) > BROADCAST_MAX:
        broadcast_content = broadcast_content[:BROADCAST_MAX - 3] + "..."
    
    _state["broadcast_line"] = broadcast_content
    await update_broadcast_file(broadcast_content)

    # Если сообщение начинается с ключевой фразы, выводим его в большой блок интерфейса
    if message.text.startswith("Дорогая редакция"):
        full_content = f"@{user_nick}: {clean_body}"
        _state["message_block"] = format_text_to_lines(full_content)

def get_message_block() -> list[str]:
    """Возвращает текущий блок текста 'Дорогая редакция' для рендерера."""
    return _state["message_block"]

def get_broadcast_line() -> str:
    """Возвращает текущую бегущую строку для рендерера."""
    return _state["broadcast_line"]

async def start_bot():
    """
    Запускает Telegram бота в режиме long polling.
    Перед запуском очищает очередь старых сообщений, чтобы не спамить в эфир при включении.
    """
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception:
        pass

if __name__ == "__main__":
    asyncio.run(start_bot())
