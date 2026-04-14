import asyncio
import logging
import os
import re
import aiohttp
import g4f
from telegram import Bot
from typing import Tuple
from PIL import Image

# Импорт глобального загрузчика конфигурации
from config_loader import conf

# Настройка логирования для отслеживания работы в фоновом режиме
logging.basicConfig(
    format="[%(asctime)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Регулярное выражение для извлечения прямой ссылки на картинку из ответа нейросети
RE_IMAGE_URL = re.compile(r"https?://[^\s)]+\.(?:webp|jpg|jpeg|png|gif)(?:[^\s)]*)", re.IGNORECASE)

def parse_movie_data(path: str) -> Tuple[str, str, str]:
    """
    Парсит файл movie.txt для подготовки данных анонса.
    Зачем: Telegram имеет лимиты на длину подписи и переносы строк. 
    Мы "распрямляем" описание, чтобы оно выглядело аккуратно.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Файл {path} не найден!")

    with open(path, "r", encoding="utf-8") as f:
        raw_content = f.read().strip()

    # Делим текст на логические абзацы
    parts = [p.strip() for p in raw_content.split('\n\n') if p.strip()]
    if not parts:
        raise ValueError("Файл данных фильма пуст!")

    # Название фильма — это всегда первая строка первого блока
    title = raw_content.splitlines()[0].strip()

    # Описание — это последний блок в файле
    description_raw = parts[-1]
    # Удаляем лишние переносы строк внутри описания (делаем "плоским")
    description_flat = " ".join(description_raw.split())

    # Собираем финальный текст: Метаданные (режиссер, год) + Чистое описание
    if len(parts) > 1:
        metadata_part = "\n\n".join(parts[:-1])
        final_full_content = f"{metadata_part}\n\n{description_flat}"
    else:
        final_full_content = description_flat

    return title, description_flat, final_full_content

async def get_image_from_aria(system_prompt: str, title: str, description: str) -> str:
    """
    Запрашивает генерацию или поиск постера через нейросеть (OperaAria).
    Почему так: Это позволяет автоматически создавать визуальный контент для каждого анонса.
    """
    user_request = f"{system_prompt}\n\ntitle: {title}, description: {description}"
    messages = [{"role": "user", "content": user_request}]
    
    while True:
        try:
            logger.info("Запрос к AI (Aria) для получения постера...")
            response = await g4f.ChatCompletion.create_async(
                model="aria",
                provider=g4f.Provider.OperaAria,
                messages=messages,
            )
            
            if not response: continue
                
            match = RE_IMAGE_URL.search(response)
            if match:
                img_url = match.group(0).rstrip(')')
                logger.info(f"✅ Ссылка на постер найдена: {img_url}")
                return img_url
            
            logger.warning("AI не выдал ссылку. Пробую еще раз...")
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Ошибка нейросети: {e}")
            await asyncio.sleep(5)

async def download_and_sanitize_image(url: str) -> str:
    """
    Скачивает изображение и пересохраняет его в стандартный JPEG.
    Зачем: Чтобы избежать проблем с форматами (например, .webp), которые Telegram может не принять как фото.
    """
    raw_path = "temp_raw_img"
    clean_path = "poster.jpg"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=30) as resp:
            if resp.status == 200:
                content = await resp.read()
                with open(raw_path, "wb") as f:
                    f.write(content)
                
                try:
                    with Image.open(raw_path) as img:
                        # Конвертация в RGB и сохранение в качественный JPEG
                        rgb_img = img.convert("RGB")
                        rgb_img.save(clean_path, "JPEG", quality=95)
                    os.remove(raw_path)
                    return clean_path
                except Exception as e:
                    logger.error(f"Ошибка Pillow: {e}")
                    os.rename(raw_path, clean_path)
                    return clean_path
            raise Exception(f"Ошибка загрузки: {resp.status}")

async def run_tool():
    """Основной процесс анонсирования."""
    try:
        # Загружаем настройки
        tg_token = conf.TELEGRAM_BOTS.content_bot_token
        channel_id = conf.RECORDER.target_channel
        movie_file = conf.PATHS.movie_info_file
        prompt_file = conf.PATHS.poster_prompt_file

        # 1. Читаем промпт для AI
        with open(prompt_file, "r", encoding="utf-8") as f:
            system_prompt = f.read().strip()

        # 2. Получаем данные о фильме
        title, flat_desc, full_content = parse_movie_data(movie_file)

        # 3. Получаем визуал через AI
        image_url = await get_image_from_aria(system_prompt, title, flat_desc)

        # 4. Готовим файл к отправке
        file_path = await download_and_sanitize_image(image_url)

        # 5. Публикация в Telegram
        bot = Bot(token=tg_token)
        async with bot:
            with open(file_path, "rb") as photo:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=photo,
                    caption=full_content[:1024] # Лимит ТГ на текст под фото
                )
        
        if os.path.exists(file_path): os.remove(file_path)
        logger.info(f"🚀 Анонс фильма '{title}' успешно опубликован!")

    except Exception as e:
        logger.critical(f"Критическая ошибка анонсера: {e}")

if __name__ == "__main__":
    asyncio.run(run_tool())
