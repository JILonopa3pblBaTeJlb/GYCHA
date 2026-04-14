# rss.py — Модуль сбора и обработки новостей из RSS-лент
import re
import feedparser
import aiohttp
import asyncio
from datetime import datetime
from collections import deque
from config_loader import conf

# Лимит для хранения уникальных заголовков во избежание утечек памяти
MAX_SEEN_TITLES = 500

# Глобальные переменные состояния модуля
_rss_history = []          # Список строк вида "ЧЧ:ММ: Заголовок" для вывода
_seen_titles_set = set()   # Множество для быстрой проверки уникальности (O(1))
_seen_titles_queue = deque() # Очередь для ротации старых заголовков из множества

def clean_text_paragraphs(text):
    """
    Очищает заголовок новости от специфического мусора.
    1. Удаляет хвосты Google News (источник новости после тире).
    2. Оставляет только безопасные символы, чтобы FFmpeg drawtext не выдавал ошибку.
    """
    # Удаляем упоминание источника в конце (обычно "- Источник")
    last_dash_space = text.rfind("- ")
    if last_dash_space != -1:
        text = text[:last_dash_space].rstrip()
    
    # Регулярное выражение оставляет буквы, цифры и базовую пунктуацию
    return re.sub(r'[^a-zA-Zа-яА-ЯЁё0-9\s\n",.:!?-]', '', text, flags=re.UNICODE)

async def fetch_titles(session: aiohttp.ClientSession):
    """
    Асинхронно скачивает и парсит все ленты, указанные в конфигурации.
    Использование aiohttp позволяет не блокировать отрисовку GUI во время ожидания ответа сервера.
    """
    titles = []
    
    # Получаем список URL из конфига. Поддерживаем как одиночную строку, так и список.
    raw_feeds = conf.RSS.feeds
    feeds_list = raw_feeds if isinstance(raw_feeds, list) else [raw_feeds]
    
    for url in feeds_list:
        url = url.strip()
        try:
            # Запрос контента ленты с таймаутом
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    # Парсим RSS структуру
                    feed = feedparser.parse(content)
                    
                    # Берем только свежие 10 записей из каждой ленты
                    for entry in feed.entries[:10]:
                        clean_title = clean_text_paragraphs(entry.title)
                        titles.append(clean_title)
                else:
                    # Ошибки HTTP не должны прерывать цикл обработки других лент
                    print(f"[rss] Ошибка HTTP {resp.status} для {url}")
        except Exception as e:
            print(f"[rss] Ошибка чтения ленты {url}: {e}")
    return titles

async def get_rss_lines(session: aiohttp.ClientSession) -> list[str]:
    """
    Основная точка входа для рендерера.
    Обновляет список новостей, фильтрует дубликаты и возвращает историю заголовков.
    """
    global _rss_history, _seen_titles_set, _seen_titles_queue
    
    try:
        # Принудительно проверяем обновление конфигурации
        conf.reload()
        
        # Получаем список «грязных» заголовков из сети
        titles = await fetch_titles(session)
        timestamp = datetime.now().strftime('%H:%M')
        
        new_entries_found = False
        for title in titles:
            # Проверяем: видели ли мы эту новость раньше и подходит ли она по длине
            if title not in _seen_titles_set and len(title) <= 149:
                # Добавляем в структуру контроля дубликатов
                _seen_titles_set.add(title)
                _seen_titles_queue.append(title)
                
                # Если накопилось слишком много ID, удаляем старые
                if len(_seen_titles_queue) > MAX_SEEN_TITLES:
                    oldest = _seen_titles_queue.popleft()
                    _seen_titles_set.discard(oldest)
                    
                # Формируем итоговую строку
                line = f"{timestamp}: {title}"
                _rss_history.append(line)
                new_entries_found = True
        
        # Ограничиваем общую длину истории новостей (настройка из конфига)
        if new_entries_found:
            max_lines = conf.RSS.max_history_lines
            if len(_rss_history) > max_lines:
                _rss_history = _rss_history[-max_lines:]
                
    except Exception as e:
        print(f"[rss] Критическая ошибка модуля: {e}")
    
    # Возвращаем копию списка истории для отрисовки
    return list(_rss_history)
