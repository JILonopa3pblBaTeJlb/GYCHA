import asyncio
import os
import json
import random
from pathlib import Path
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.errors import FloodWaitError

# Импорт глобального конфига
from config_loader import conf

# =============================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И КЭШИРОВАНИЕ
# =============================================================================

_last_scan_time_cache = None
_cached_program = None
_cached_date = None

def log_step(msg):
    """Выводит логи с временной меткой для отслеживания этапов работы загрузчика."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

async def schedule_vhs_announcement(vhs_start_hour):
    """
    Планирует публикацию анонса фильма. 
    Рассчитывает время так, чтобы запустить 'movie_announcer.py' ровно за 11 минут до фильма.
    Использует asyncio.wait_for для предотвращения зависания внешней утилиты.
    """
    now = datetime.now()
    start_dt = now.replace(hour=vhs_start_hour, minute=0, second=0, microsecond=0)
    announcement_dt = start_dt - timedelta(minutes=11)
    
    delay = (announcement_dt - now).total_seconds()
    
    if delay > 0:
        log_step(f"⏳ Анонс запланирован на {announcement_dt.strftime('%H:%M:%S')} (через {delay/60:.1f} мин)")
        await asyncio.sleep(delay)
    else:
        log_step(f"⚠️ Время анонса ({announcement_dt.strftime('%H:%M:%S')}) уже прошло. Запуск немедленно.")

    try:
        log_step("📢 Запуск инструмента анонсирования (лимит 5 минут)...")
        # Импорт вынесен внутрь для избежания циклических зависимостей
        from movie_announcer import run_tool
        await asyncio.wait_for(run_tool(), timeout=300)
        log_step("✅ Анонс успешно опубликован.")
    except asyncio.TimeoutError:
        log_step("❌ КРИТИЧНО: movie_announcer.py превысил лимит времени и был прерван.")
    except Exception as e:
        log_step(f"❌ Ошибка при выполнении анонса: {e}")

def load_last_scan_time():
    """Читает время последнего сканирования каналов из файла лога."""
    global _last_scan_time_cache
    if _last_scan_time_cache is not None:
        return _last_scan_time_cache

    scan_log_path = conf.PATHS.last_scan_log
    if os.path.exists(scan_log_path):
        try:
            with open(scan_log_path, "r") as f:
                timestamp_str = f.read().strip()
                _last_scan_time_cache = datetime.fromisoformat(timestamp_str)
                return _last_scan_time_cache
        except Exception as e:
            log_step(f"Ошибка чтения лога сканирования: {e}")
            return None
    return None

def save_last_scan_time():
    """Сохраняет текущее время как метку последнего успешного сканирования."""
    global _last_scan_time_cache
    now = datetime.now()
    _last_scan_time_cache = now
    try:
        with open(conf.PATHS.last_scan_log, "w") as f:
            f.write(now.isoformat())
    except Exception as e:
        log_step(f"Ошибка записи лога сканирования: {e}")

def load_program_for_date(target_date=None):
    """
    Загружает список жанров из текстового файла программы на конкретный день.
    Если файл дня (например, program0.txt) отсутствует, берет дефолтный файл.
    """
    if target_date is None:
        target_date = datetime.now()
    
    weekday = target_date.weekday()
    weekday_file = f"program{weekday}.txt"

    if os.path.exists(weekday_file):
        program_file = weekday_file
        log_step(f"Используем расписание для дня {weekday}")
    else:
        program_file = conf.PATHS.program_default
        if not os.path.exists(program_file):
            raise FileNotFoundError(f"Критическая ошибка: файл {program_file} не найден.")
        log_step(f"Используем стандартное расписание: {program_file}")

    with open(program_file, "r", encoding="utf-8") as f:
        program = [line.strip() for line in f if line.strip()]

    return program

def get_current_program():
    """Возвращает текущую программу передач с использованием кэша для экономии ресурсов."""
    global _cached_program, _cached_date
    today = datetime.now().date()
    if _cached_program is None or _cached_date != today:
        _cached_program = load_program_for_date()
        _cached_date = today
    return _cached_program

def get_program_for_next_hour(current_hour):
    """
    Определяет жанр, который будет играть в следующем часе. 
    Учитывает переход через полночь и загружает программу следующего дня.
    """
    next_hour = (current_hour + 1) % 24
    if next_hour == 0:
        tomorrow = datetime.now() + timedelta(days=1)
        next_program = load_program_for_date(tomorrow)
        log_step(f"🌙 Полночь: загружена программа на завтра.")
        return next_program[next_hour]
    else:
        current_program = get_current_program()
        return current_program[next_hour]

def load_vhs_config():
    """Получает параметры киносеансов из глобального конфига."""
    vhs_hour = conf.AIR_CONTROL.vhs_hour
    vhs_days = conf.AIR_CONTROL.vhs_days
    if isinstance(vhs_days, int):
        vhs_days = [vhs_days]
    return vhs_hour, vhs_days

def load_downloaded():
    """Загружает базу данных скачанных постов (downloaded.json), чтобы не качать одно и то же."""
    download_file = Path(conf.GLOBAL.base_dir).resolve() / "downloaded.json"
    if download_file.exists():
        try:
            with open(download_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            log_step(f"Ошибка загрузки downloaded.json: {e}")
    return {}

def save_downloaded(data):
    """Сохраняет обновленную базу идентификаторов скачанных медиафайлов."""
    download_file = Path(conf.GLOBAL.base_dir).resolve() / "downloaded.json"
    try:
        with open(download_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log_step(f"Ошибка сохранения истории загрузок: {e}")

def should_scan_channels():
    """Проверяет, пришло ли время для полной инвентаризации каналов (по интервалу из конфига)."""
    last_scan = load_last_scan_time()
    if not last_scan:
        return True
    hours_since_scan = (datetime.now() - last_scan).total_seconds() / 3600
    return hours_since_scan >= conf.CONTENT_MANAGER.scan_interval_h

# =============================================================================
# ВЕРИФИКАЦИЯ И ЗАГРУЗКА
# =============================================================================

async def verify_media_integrity(filename, is_video=False):
    """
    Использует ffprobe для проверки файла.
    Проверяет: считывается ли длительность, не поврежден ли заголовок и
    соответствует ли длительность минимальным лимитам (защита от битых файлов).
    """
    try:
        process = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration,size',
            '-of', 'default=noprint_wrappers=1', filename,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode != 0:
            log_step(f"⚠️ FFPROBE ERROR: {filename} поврежден.")
            return False, 0
        
        output = stdout.decode().strip()
        duration, size = None, None
        for line in output.split('\n'):
            if line.startswith('duration='):
                duration = float(line.split('=')[1])
            elif line.startswith('size='):
                size = int(line.split('=')[1])
        
        if duration is None: return False, 0
        
        # Проверка минимально допустимой длины (чтобы не стримить тишину или обрубки)
        min_duration = 60 if is_video else 30
        if duration < min_duration:
            log_step(f"⚠️ Файл слишком короткий ({duration}s).")
            return False, 0
        
        return True, duration
    except Exception as e:
        log_step(f"⚠️ Ошибка верификации: {e}")
        return False, 0

async def download_with_retry(message, filename, post_id, is_video=False):
    """
    Скачивает медиафайл с системой повторов.
    Использует временные файлы (.part -> .new) для атомарной замены, чтобы 
    FFmpeg не попытался прочитать недокачанный файл.
    """
    max_retries = 10
    temp_file = filename + ".part"
    final_temp = filename + ".new"
    expected_size = message.document.size if hasattr(message, "document") and message.document else None
    
    timeout = conf.CONTENT_MANAGER.download_timeout_video_sec if is_video else conf.CONTENT_MANAGER.download_timeout_audio_sec
    
    for attempt in range(max_retries):
        try:
            log_step(f"📥 Загрузка {post_id} (попытка {attempt + 1})")
            download_task = message.download_media(file=temp_file)
            await asyncio.wait_for(download_task, timeout=timeout)
            
            if not os.path.exists(temp_file): continue
            
            actual_size = os.path.getsize(temp_file)
            if expected_size and actual_size < expected_size:
                os.remove(temp_file)
                continue

            # Проверка на "пустышки"
            if actual_size < (50 * 1024 * 1024 if is_video else 1024 * 1024):
                os.remove(temp_file)
                continue

            # Важнейший этап: проверка файла перед тем, как отдать его в эфир
            success, duration = await verify_media_integrity(temp_file, is_video=is_video)
            if not success:
                os.remove(temp_file)
                await asyncio.sleep(20)
                continue
            
            # Атомарная замена
            if os.path.exists(final_temp): os.remove(final_temp)
            os.rename(temp_file, final_temp)
            if os.path.exists(filename): os.remove(filename)
            os.rename(final_temp, filename)
            
            log_step(f"✅ Файл готов: {filename}")
            return True, duration

        except asyncio.TimeoutError:
            log_step(f"⏱️ Таймаут при загрузке {post_id}.")
            if os.path.exists(temp_file): os.remove(temp_file)
        except FloodWaitError as e:
            log_step(f"🚫 FloodWait: спим {e.seconds}с")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            log_step(f"❌ Ошибка загрузки: {e}")
            if os.path.exists(temp_file): os.remove(temp_file)
            await asyncio.sleep(15)

    return False, 0

# =============================================================================
# СКАНИРОВАНИЕ КАНАЛОВ
# =============================================================================

async def get_last_post_id(client, chat_id):
    """Получает ID последнего сообщения в канале с таймаутом."""
    try:
        # Устанавливаем таймаут 15 секунд на запрос к API
        messages = await asyncio.wait_for(client.get_messages(chat_id, limit=1), timeout=15)
        if messages:
            return messages[0].id
        return None
    except asyncio.TimeoutError:
        log_step(f"⚠️ Таймаут при получении ID сообщения для {chat_id}")
        return None
    except Exception as e:
        log_step(f"⚠️ Ошибка get_last_post_id для {chat_id}: {e}")
        return None


async def get_real_post_count(client, chat_id, last_id):
    """Запрашивает общее количество сообщений в канале с таймаутом."""
    try:
        # Используем limit=0 для получения метаданных (включая total)
        posts = await asyncio.wait_for(client.get_messages(chat_id, limit=0), timeout=15)
        return posts.total if hasattr(posts, 'total') and posts.total is not None else last_id
    except asyncio.TimeoutError:
        log_step(f"⚠️ Таймаут при получении счетчика постов для {chat_id}")
        return last_id or 0
    except Exception as e:
        log_step(f"⚠️ Ошибка get_real_post_count для {chat_id}: {e}")
        return last_id or 0
def save_scan_results(vhs_posts, music_posts, total_gb):
    """Записывает статистику библиотеки в текстовый файл для вывода в интерфейс (status.py)."""
    scan_line = f"Фильмов: {vhs_posts}, Музыки: {music_posts}ч, Библиотека: {total_gb:.2f} ГБ"
    with open("cloud_storage.txt", "w", encoding="utf-8") as f:
        f.write(scan_line)

async def scan_channels(client):
    """
    Проходит по всем каналам из CHANNELS_MAPPING.
    Считает количество постов и примерный объем данных для статистики.
    """
    total_size = 0
    vhs_posts = 0
    music_posts = 0
    log_step("🕵️ Сканирование библиотеки каналов...")
    
    mapping = conf.CHANNELS_MAPPING.get_dict()
    items = list(mapping.items())
    random.shuffle(items) # Рандомизация порядка, чтобы не триггерить антифлуд ТГ

    for name, chat_id in items:
        try:
            log_step(f"🔍 Анализ канала: {name} (ID: {chat_id})...")
            await asyncio.sleep(random.uniform(1, 3))
            
            # Оптимизация: получаем всё одним запросом
            # get_messages возвращает TotalList, у которого есть атрибут .total
            msgs = await asyncio.wait_for(client.get_messages(chat_id, limit=1), timeout=20)
            
            if msgs is None:
                log_step(f"❓ Канал {name} не вернул сообщений (возможно, пуст или нет доступа)")
                continue
                
            real_count = msgs.total if hasattr(msgs, 'total') and msgs.total is not None else 0
            if real_count == 0 and len(msgs) > 0:
                real_count = msgs[0].id
                
            log_step(f"📊 Канал {name}: обнаружено {real_count} постов.")

            # Оценка веса на основе лимитов из конфига
            limit_mb = conf.CONTENT_MANAGER.max_video_size_mb if name == "vhs" else conf.CONTENT_MANAGER.max_audio_size_mb
            total_size += real_count * limit_mb
            
            if name == "vhs":
                vhs_posts = real_count
            elif name != "reading":
                music_posts += real_count
            
        except asyncio.TimeoutError:
            log_step(f"❌ Канал {name} не ответил за отведенное время (Timeout)")
        except Exception as e:
            log_step(f"⚠️ Ошибка сканирования {name}: {e}")
    
    save_scan_results(vhs_posts, music_posts, total_size / 1024)
    save_last_scan_time()
    log_step("✅ Сканирование завершено.")

# =============================================================================
# ОСНОВНАЯ ЛОГИКА ТРИГГЕРОВ
# =============================================================================

def is_hour_covered_by_vhs(check_hour):
    """
    Проверяет, не занят ли указанный час воспроизведением фильма.
    Использует файл length.txt, куда записываются тайминги текущего фильма.
    """
    length_file = conf.PATHS.vhs_length_file
    if not os.path.exists(length_file): return False
    try:
        with open(length_file, "r", encoding="utf-8") as f:
            line = f.read().strip()
            if not "|" in line: return False
            start_str, duration_str = line.split("|")
            vhs_start = datetime.fromisoformat(start_str.strip())
            vhs_end = vhs_start + timedelta(seconds=float(duration_str.strip()))
            
            now = datetime.now()
            target_time = now.replace(hour=check_hour, minute=0, second=0, microsecond=0)
            if check_hour <= now.hour: target_time += timedelta(days=1)
            
            return vhs_start <= target_time < vhs_end
    except:
        return False

async def process_program(client, downloaded, vhs_hour, vhs_days):
    """
    Центральный диспетчер задач.
    Проверяет время и запускает либо сканирование, либо предзагрузку фильма,
    либо загрузку трека на следующий час.
    """
    now = datetime.now()
    hour, minute, second = now.hour, now.minute, now.second
    weekday = now.weekday()

    if should_scan_channels():
        await scan_channels(client)

    # Логика VHS (предзагрузка за X минут до начала)
    offset = conf.CONTENT_MANAGER.vhs_preload_offset_min
    v_trigger = (datetime.now().replace(hour=vhs_hour, minute=0, second=0, microsecond=0) - timedelta(minutes=offset))
    
    if (weekday == v_trigger.weekday() and hour == v_trigger.hour and
        minute == v_trigger.minute and second == 0 and weekday in vhs_days):
        log_step("🎬 Запуск предзагрузки фильма...")
        await handle_channel(client, "vhs", "movie.mp4", downloaded, ordered=False, is_video=True, vhs_start_hour=vhs_hour)
        return

    # Логика ежечасной загрузки музыки (в момент свитча плейлиста)
    if minute == conf.AIR_CONTROL.switch_min and second == conf.AIR_CONTROL.switch_sec:
        next_hour_val = (hour + 1) % 24
        if is_hour_covered_by_vhs(next_hour_val):
            log_step("⏸ Пропуск загрузки музыки: идет киносеанс.")
            return

        next_prog = get_program_for_next_hour(hour)
        os.makedirs(next_prog, exist_ok=True)
        out_file = os.path.join(next_prog, f"{next_prog}.m4a")
        await handle_channel(client, next_prog, out_file, downloaded, ordered=(next_prog == "reading"), is_video=False)

async def handle_channel(client, program_name, out_file, downloaded, ordered=False, is_video=False, vhs_start_hour=None):
    """
    Выбирает пост из канала и скачивает его.
    ordered=True: берет следующий пост по порядку (для аудиокниг).
    ordered=False: берет случайный пост, которого нет в истории загрузок.
    """
    mapping = conf.CHANNELS_MAPPING.get_dict()
    chat_id = mapping.get(program_name)
    if not chat_id: return

    last_id = await get_last_post_id(client, chat_id)
    if not last_id: return

    used_ids = downloaded.get(program_name, [])
    if not isinstance(used_ids, list): used_ids = []

    if ordered:
        next_id = max(used_ids, default=2) + 1
        available_ids = list(range(next_id, last_id + 1))
    else:
        available_ids = [i for i in range(3, last_id + 1) if i not in used_ids]

    if not available_ids:
        # Сброс круга, если всё кончилось
        downloaded[program_name] = []
        save_downloaded(downloaded)
        available_ids = list(range(3, last_id + 1))

    selected_id, message = None, None
    for _ in range(15): # Попытки найти пост с медиа
        if not available_ids: break
        candidate_id = available_ids[0] if ordered else random.choice(available_ids)
        try:
            message = await client.get_messages(chat_id, ids=candidate_id)
            if message and message.media:
                selected_id = candidate_id
                break
            available_ids.remove(candidate_id)
        except:
            if candidate_id in available_ids: available_ids.remove(candidate_id)
    
    if selected_id and message:
        success, duration = await download_with_retry(message, out_file, selected_id, is_video=is_video)
        if success:
            used_ids.append(selected_id)
            downloaded[program_name] = used_ids
            save_downloaded(downloaded)

            if program_name == "vhs" and vhs_start_hour is not None:
                # Запись метаданных фильма для контроля времени
                start_dt = datetime.now().replace(hour=vhs_start_hour, minute=0, second=0, microsecond=0)
                with open("length.txt", "w", encoding="utf-8") as lf:
                    lf.write(f"{start_dt.isoformat()} | {duration}")
                
                # Генерация визуальной карточки фильма и запуск задачи анонса
                from vhs_card import generate_card
                if generate_card(selected_id):
                    asyncio.create_task(schedule_vhs_announcement(vhs_start_hour))

def seconds_until_next_trigger(vhs_hour, vhs_days):
    """
    Рассчитывает время сна до следующего события.
    Это позволяет скрипту не крутить цикл впустую, экономя ресурсы CPU.
    """
    now = datetime.now()
    # Следующий час (минута переключения)
    base_trigger = now.replace(minute=conf.AIR_CONTROL.switch_min, second=conf.AIR_CONTROL.switch_sec, microsecond=0)
    if now >= base_trigger: base_trigger += timedelta(hours=1)

    # Следующий VHS
    vhs_trigger = None
    offset = conf.CONTENT_MANAGER.vhs_preload_offset_min
    for days_ahead in range(7):
        check_date = now + timedelta(days=days_ahead)
        if check_date.weekday() in vhs_days:
            candidate = check_date.replace(hour=vhs_hour, minute=0, second=0, microsecond=0) - timedelta(minutes=offset)
            if candidate > now:
                vhs_trigger = candidate
                break

    triggers = [base_trigger]
    if vhs_trigger: triggers.append(vhs_trigger)
    return max(1, int((min(triggers) - now).total_seconds()))

async def main():
    """Точка входа. Инициализирует Telethon и запускает бесконечный цикл."""
    client = TelegramClient("bot_session", conf.TELEGRAM_BOTS.api_id, conf.TELEGRAM_BOTS.api_hash)
    vhs_hour, vhs_days = load_vhs_config()
    downloaded = load_downloaded()

    async with client:
        await client.start(bot_token=conf.TELEGRAM_BOTS.content_bot_token)
        log_step("🚀 Контент-менеджер запущен и готов к работе.")
        await scan_channels(client)

        while True:
            try:
                await process_program(client, downloaded, vhs_hour, vhs_days)
            except Exception as e:
                log_step(f"Критическая ошибка цикла: {e}")

            sleep_sec = seconds_until_next_trigger(vhs_hour, vhs_days)
            await asyncio.sleep(sleep_sec)

if __name__ == "__main__":
    asyncio.run(main())
