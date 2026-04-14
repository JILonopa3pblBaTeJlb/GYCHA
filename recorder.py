# recorder.py — Автоматическая запись и архивация эфирных часов
import os
import subprocess
import asyncio
import re
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeAudio

# Импорт конфигурации
from config_loader import conf

# Настройки из конфигурационного файла
API_ID = conf.TELEGRAM_BOTS.api_id
API_HASH = conf.TELEGRAM_BOTS.api_hash
SESSION = "recorder_session" # Имя файла сессии Telethon
CHANNEL = conf.RECORDER.target_channel

PLAYLIST_FILE = conf.PATHS.playlist_file
FFMPEG_BIN = "ffmpeg"

# Инициализация клиента Telethon
client = TelegramClient(SESSION, API_ID, API_HASH)

def get_caption_from_playlist():
    """
    Анализирует текущий playlist.txt, чтобы определить жанр или название программы.
    Используется для автоматического создания хэштегов к аудиозаписи (например, #phonk).
    Специальная логика предусмотрена для авторских шоу (поиск ключевого слова roboshow).
    """
    hashtag = ""
    try:
        if not os.path.exists(PLAYLIST_FILE):
            return ""

        with open(PLAYLIST_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        
        if not lines:
            return ""

        # Берем последнюю строку плейлиста, извлекаем путь к файлу
        # Формат строки: file 'folder/track.m4a'
        last_line = lines[-1]
        match = re.search(r"'(.*?)'", last_line)
        full_path = match.group(1) if match else last_line.split()[-1]

        # Извлекаем имя папки или файла для определения жанра
        filename = os.path.basename(full_path)
        name_clean = os.path.splitext(filename)[0]

        # Логика маппинга хэштегов
        if name_clean.startswith("roboshow"):
            hashtag = "#авторскаяпрограмма"
        else:
            hashtag = f"#{name_clean}"
            
    except Exception as e:
        print(f"Ошибка при формировании хэштега: {e}")
    
    return hashtag

def merge_playlist():
    """
    Использует FFmpeg concat demuxer для склейки всех файлов из плейлиста в один.
    Используется флаг '-c copy', что означает отсутствие перекодирования — 
    процесс происходит мгновенно и без потери качества.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = f"archive_{timestamp}.m4a"

    # Команда для бесшовной склейки
    cmd = [
        FFMPEG_BIN,
        "-f", "concat",
        "-safe", "0",
        "-i", PLAYLIST_FILE,
        "-c", "copy",
        out_file
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out_file
    except subprocess.CalledProcessError:
        return None

async def run_once():
    """
    Основной рабочий цикл рекордера:
    1. Склеивает файлы часа в один аудиофайл.
    2. Определяет описание (хэштеги).
    3. Загружает файл в Telegram канал с заполнением метаданных (Title/Artist).
    4. Удаляет временный файл с диска.
    """
    async with client:
        # 1. Сборка файла
        file_path = await asyncio.to_thread(merge_playlist)
        if not file_path:
            return
        
        # 2. Подготовка метаданных
        caption_text = get_caption_from_playlist()

        try:
            # 3. Отправка в Telegram
            print(f"📤 Загрузка архива {file_path} в канал...")
            await client.send_file(
                entity=CHANNEL,
                file=file_path,
                caption=caption_text,
                voice=False, # Отправляем как музыкальный файл, а не голосовое сообщение
                attributes=[DocumentAttributeAudio(
                    duration=0, # Telegram сам определит длительность
                    title=conf.RECORDER.audio_title,
                    performer=conf.RECORDER.audio_performer
                )]
            )
            # 4. Очистка
            os.remove(file_path)
            print("✅ Архив успешно отправлен и удален локально.")
        except Exception as e:
            print(f"❌ Ошибка при отправке в Telegram: {e}")

if __name__ == "__main__":
    # Скрипт обычно запускается планировщиком (cron) в конце каждого часа
    asyncio.run(run_once())
