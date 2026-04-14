# watchdog.py — Мониторинг статуса стрима и обновление ссылок в Telegram
import os
import asyncio
import subprocess
from datetime import datetime
import requests
from telethon import TelegramClient
from telethon.tl.functions.messages import (
    UpdatePinnedMessageRequest,
    DeleteMessagesRequest,
    GetHistoryRequest
)
from telethon.tl.types import (
    MessageActionPinMessage
)

# Импорт глобальной конфигурации
from config_loader import conf

# ====== НАСТРОЙКИ ИЗ КОНФИГУРАЦИИ ======
API_ID = conf.TELEGRAM_BOTS.api_id
API_HASH = conf.TELEGRAM_BOTS.api_hash
SESSION = "watchdog_session" # Имя файла сессии для авторизации
CHANNEL = conf.RECORDER.target_channel
STREAM_URL = conf.WATCHDOG.twitch_url
CHECK_INTERVAL = conf.WATCHDOG.check_interval_sec
# Пути к файлам для сохранения состояния между перезапусками
LAST_TOKEN_FILE = conf.WATCHDOG.watchdog_token
LAST_URL_FILE = conf.WATCHDOG.watchdog_url
LAST_MSG_FILE = conf.WATCHDOG.watchdog_msg_ids
STREAMLINK_BIN = "streamlink"

# Инициализация клиента Telethon
client = TelegramClient(SESSION, API_ID, API_HASH)

def extract_token(m3u8_url: str) -> str:
    """
    Извлекает уникальный идентификатор трансляции (токен) из .m3u8 ссылки.
    Это позволяет понять, идет ли всё еще тот же стрим или начался новый.
    """
    if not m3u8_url:
        return ""
    # Обычно токен содержится в имени файла перед расширением .m3u8
    base = m3u8_url.split("/")[-1]
    return base.split(".m3u8")[0]

def is_stream_alive(url: str) -> bool:
    """
    Проверяет доступность прямой ссылки на поток с помощью HTTP HEAD запроса.
    """
    try:
        resp = requests.head(url, timeout=5)
        return resp.status_code == 200
    except:
        return False

async def get_stream_url() -> str:
    """
    Вызывает системную утилиту streamlink для получения прямой ссылки на поток (best quality).
    """
    try:
        # Запуск streamlink как подпроцесса
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                [STREAMLINK_BIN, "--stream-url", STREAM_URL, "best"],
                capture_output=True,
                text=True,
                timeout=20
            )
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        print(f"[{datetime.now()}] Ошибка получения ссылки через streamlink: {e}")
    return ""

# --- Функции работы с постоянным хранилищем состояния ---

def load_last_token() -> str:
    if os.path.exists(LAST_TOKEN_FILE):
        return open(LAST_TOKEN_FILE).read().strip()
    return ""

def save_last_token(token: str):
    with open(LAST_TOKEN_FILE, "w") as f:
        f.write(token)

def load_last_msg_ids() -> tuple[int|None, int|None]:
    """Загружает ID последнего поста и ID сервисного сообщения о закрепе."""
    if os.path.exists(LAST_MSG_FILE):
        try:
            content = open(LAST_MSG_FILE).read().strip()
            if not content: return None, None
            parts = content.split(",")
            p_id = int(parts[0]) if parts[0] != 'None' else None
            s_id = int(parts[1]) if parts[1] != 'None' else None
            return p_id, s_id
        except: pass
    return None, None

def save_last_msg_ids(post_id: int, pin_id: int | None):
    with open(LAST_MSG_FILE, "w") as f:
        f.write(f"{post_id},{pin_id}")

# --- Логика взаимодействия с Telegram ---

async def post_new_link(new_url: str, old_post_id: int | None, old_pin_msg_id: int | None) -> tuple[int, int | None]:
    """
    Публикует новую ссылку, закрепляет её и удаляет старые сообщения.
    Это позволяет избежать накопления нерабочих ссылок в канале.
    """
    # 1. Удаление старых сообщений (если они были)
    ids_to_delete = [i for i in [old_post_id, old_pin_msg_id] if i]
    if ids_to_delete:
        try:
            await client.delete_messages(CHANNEL, ids_to_delete, revoke=True)
        except: pass

    # 2. Постинг новой ссылки
    link_text = f"🔴 **Прямой эфир запущен!**\n\n[Смотреть трансляцию]({new_url})"
    msg = await client.send_message(CHANNEL, link_text, link_preview=False)

    # 3. Закрепление сообщения
    real_pin_service_id = None
    try:
        await client(UpdatePinnedMessageRequest(peer=CHANNEL, id=msg.id, silent=False))
        
        # Небольшая пауза, чтобы Telegram успел создать сервисное сообщение "pinned a message"
        await asyncio.sleep(1.5)
        
        # Находим и запоминаем ID этого сервисного сообщения, чтобы удалить его в следующий раз
        history = await client(GetHistoryRequest(
            peer=CHANNEL, limit=1, offset_id=0, offset_date=None,
            add_offset=0, max_id=0, min_id=0, hash=0
        ))
        if history.messages:
            last_msg = history.messages[0]
            if isinstance(getattr(last_msg, 'action', None), MessageActionPinMessage):
                real_pin_service_id = last_msg.id
    except: pass

    return msg.id, real_pin_service_id

async def watchdog_loop():
    """
    Главный цикл: каждые X секунд проверяет, жива ли текущая ссылка.
    Если стрим перезапустился (токен изменился), обновляет пост в Telegram.
    """
    async with client:
        print(f"[{datetime.now()}] 🛡 Watchdog запущен. Мониторинг: {STREAM_URL}")

        # Инициализация состояния из файлов
        last_token = load_last_token()
        last_post_id, last_pin_id = load_last_msg_ids()
        
        while True:
            try:
                # 1. Получаем актуальную ссылку от Twitch
                new_url = await get_stream_url()
                
                if not new_url:
                    # Стрим оффлайн — просто ждем
                    await asyncio.sleep(60)
                    continue

                new_token = extract_token(new_url)
                
                # 2. Если токен изменился — это новый стрим
                if new_token != last_token:
                    print(f"[{datetime.now()}] 🔄 Обнаружен новый эфир. Обновляю ссылку...")
                    
                    post_id, pin_id = await post_new_link(new_url, last_post_id, last_pin_id)
                    
                    # Сохраняем новое состояние
                    save_last_token(new_token)
                    save_last_msg_ids(post_id, pin_id)
                    
                    last_token, last_post_id, last_pin_id = new_token, post_id, pin_id
                else:
                    # Стрим тот же, просто спим до следующей проверки
                    await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"[{datetime.now()}] ❗ Ошибка в цикле Watchdog: {e}")
                await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(watchdog_loop())
    except KeyboardInterrupt:
        print("Остановка дежурного бота...")
