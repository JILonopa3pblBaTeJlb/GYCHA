# air_supply.py — Утилиты для управления эфирным временем и процессами
import asyncio
import datetime
import sys
from ffmpeg_runner import stop_proc
from config_loader import conf

def next_occurrence(minute, second):
    """
    Вычисляет объект datetime для следующего наступления указанной минуты и секунды.
    Используется для определения момента переключения часа (например, каждый час в 59:45).
    """
    now = datetime.datetime.now()
    target = now.replace(minute=minute, second=second, microsecond=0)
    # Если целевое время в этом часу уже прошло, прибавляем час
    if target <= now:
        target += datetime.timedelta(hours=1)
    return target

def next_vhs_occurrence(vhs_hour, vhs_min, vhs_days):
    """
    Вычисляет время следующего киносеанса.
    Проверяет текущий и последующие дни недели на соответствие списку разрешенных дней (vhs_days).
    """
    # Если в конфиге пусто или значение не задано
    if vhs_days is None or vhs_days == "":
        return None
        
    # Приводим к списку целых чисел, если из конфига пришла строка или одиночное число
    if isinstance(vhs_days, (int, float)):
        vhs_days = [int(vhs_days)]
    elif isinstance(vhs_days, str):
        try:
            vhs_days = [int(x.strip()) for x in vhs_days.split(',') if x.strip()]
        except ValueError:
            return None

    now = datetime.datetime.now()
    today_weekday = now.weekday()
    
    # Перебираем дни, начиная с сегодняшнего
    for days_ahead in range(8):
        target_day = (today_weekday + days_ahead) % 7
        if target_day in vhs_days:
            target = now.replace(hour=vhs_hour, minute=vhs_min, second=0, microsecond=0) + \
                     datetime.timedelta(days=days_ahead)
            if target > now:
                return target
    return None

async def sleep_until(dt):
    """
    Асинхронно засыпает до наступления указанной временной метки.
    Проверяет время каждые 0.5 сек, чтобы избежать погрешностей длинного сна.
    """
    while True:
        now = datetime.datetime.now()
        delta = (dt - now).total_seconds()
        if delta <= 0:
            return
        await asyncio.sleep(min(delta, 0.5))

async def run_script(script_path):
    """
    Запускает внешний Python-скрипт как подпроцесс.
    Используется для генерации плейлиста, чтобы основной цикл не блокировался.
    """
    proc = await asyncio.create_subprocess_exec(sys.executable, script_path)
    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Скрипт {script_path} завершился с ошибкой {proc.returncode}")

async def get_video_duration(file_path):
    """
    Использует ffprobe для получения длительности видеофайла в секундах.
    Это критически важно для VHS-режима, чтобы знать, когда возвращаться в радио-эфир.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
            '-of', 'csv=p=0', file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            print(f"❌ ffprobe error: {stderr.decode()}")
            return None
            
        duration_str = stdout.decode().strip()
        if not duration_str:
            return None
            
        return float(duration_str)
        
    except Exception as e:
        print(f"❌ Ошибка при получении длительности видео: {e}")
        return None

async def ensure_process_stopped(proc, name):
    """
    Гарантированно останавливает процесс FFmpeg.
    Сначала посылает сигнал мягкой остановки (через ffmpeg_runner), 
    затем terminate/kill, если процесс завис.
    В конце ждет освобождения порта (socket_release_delay), чтобы следующий процесс мог забиндить RTMP.
    """
    if proc is None:
        return
    
    print(f"📴 Остановка процесса {name}...")
    
    # Если процесс еще живой
    if proc.returncode is None:
        await stop_proc(proc, name)
        try:
            # Даем шанс закрыться по terminate
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            print(f"⚠️ {name} не сдается, применяем kill...")
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                print(f"⚠️ {name} полностью завис.")
        except ProcessLookupError:
            pass
    
    # Пауза для очистки сетевого сокета
    delay = conf.AIR_CONTROL.socket_release_delay_sec
    await asyncio.sleep(delay)
    print(f"✅ Процесс {name} остановлен, порт свободен.")
