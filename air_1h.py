import asyncio
import datetime
from process_manager import ProcessManager, ProcessType
from air_supply import next_occurrence, next_vhs_occurrence, run_script, get_video_duration
from config_loader import conf

# Настройки таймингов переключения, подтянутые из конфига
SWITCH_MIN = conf.AIR_CONTROL.switch_min
SWITCH_SEC = conf.AIR_CONTROL.switch_sec
# Подготовка плейлиста начинается за 1 секунду до свитча (или по логике PREPARE_SEC)
PREPARE_SEC = (SWITCH_SEC - 1) % 60
ONE_HOUR_PL_SCRIPT = "1h_pl.py"
VHS_MIN = 0

async def main():
    """
    Основной цикл управления эфиром.
    Отвечает за переключение между часовыми блоками и запуск VHS по расписанию.
    """
    print("🚀 Эфирный менеджер запущен...")
    
    pm = ProcessManager()
    
    # При старте запускаем процесс FFMPEG3, который подхватывает текущий плейлист
    # с расчетом времени (чтобы не начинать час сначала при перезагрузке скрипта)
    await pm.switch_to(ProcessType.FFMPEG3)
    
    while True:
        # Перегружаем конфиг, чтобы подхватить изменения без перезагрузки скрипта
        conf.reload()
        
        # 1. Проверка на краш: если процесс упал, пытаемся восстановиться
        if pm.is_crashed():
            print("💥 Обнаружена остановка процесса. Перезапуск...")
            success = await pm.handle_crash()
            if not success:
                print("❌ Критическая ошибка восстановления. Выход.")
                break
            continue
        
        # 2. Проверка таймаута VHS: если фильм идет дольше положенного, выключаем его
        if pm.is_vhs_timeout_exceeded():
            print("🚨 Таймаут фильма превышен. Принудительный возврат в радио-эфир.")
            await pm.force_vhs_timeout()
            continue
        
        # 3. Расчет времени до следующих событий
        # Время подготовки следующего часа
        next_prepare = next_occurrence(conf.AIR_CONTROL.switch_min, PREPARE_SEC)
        # Время начала ближайшего VHS-сеанса
        next_vhs = next_vhs_occurrence(conf.AIR_CONTROL.vhs_hour, VHS_MIN, conf.AIR_CONTROL.vhs_days)
        
        next_events = [e for e in [next_prepare, next_vhs] if e is not None]
        if not next_events:
            await asyncio.sleep(1.0)
            continue
        
        # Берем самое ближайшее событие
        next_event = min(next_events)
        
        # 4. Ожидание события
        while datetime.datetime.now() < next_event:
            await asyncio.sleep(0.5)
            # В процессе ожидания продолжаем проверять состояние процессов
            if pm.is_crashed() or pm.is_vhs_timeout_exceeded():
                break
        
        if pm.is_crashed() or pm.is_vhs_timeout_exceeded():
            continue
        
        # 5. Обработка наступившего события
        if next_event == next_vhs:
            await handle_vhs_event(pm)
        elif next_event == next_prepare:
            await handle_hourly_switch(pm, next_prepare)

async def handle_vhs_event(pm: ProcessManager):
    """
    Логика запуска VHS-фильма.
    Проверяет наличие файла, его длительность и запускает специальный процесс FFmpeg.
    """
    if pm.is_vhs_active():
        return
    
    print(f"📼 Время киносеанса: {conf.AIR_CONTROL.vhs_hour}:00")
    
    # Путь к файлу фильма (в продакшене подставляется реальное имя)
    vhs_file = "movie.mp4"
    expected_duration = await get_video_duration(vhs_file)
    
    if expected_duration is None or expected_duration < 60:
        print("⚠️ Фильм не найден или поврежден. Отмена сеанса.")
        return
    
    # Рассчитываем дедлайн завершения (длительность + буфер из конфига)
    buffer = conf.AIR_CONTROL.vhs_overtime_buffer_sec
    print(f"📼 Запуск фильма. Длительность: {expected_duration/60:.1f} мин. Буфер: {buffer}с")
    
    await pm.switch_to(ProcessType.VHS, expected_duration=expected_duration)

async def handle_hourly_switch(pm: ProcessManager, prepare_time):
    """
    Логика смены часа.
    Генерирует новый плейлист и в нужную секунду переключает поток.
    """
    if pm.is_vhs_active():
        # Если идет фильм, мы не прерываем его часовым плейлистом
        return
    
    try:
        print(f"🕒 Подготовка плейлиста на {prepare_time.strftime('%H:%M')}")
        # Запускаем внешний скрипт 1h_pl.py
        await run_script(ONE_HOUR_PL_SCRIPT)
    except Exception as e:
        print(f"❌ Ошибка генерации плейлиста: {e}")
    
    # Ждем точного момента переключения (например, 59:45)
    next_switch = next_occurrence(conf.AIR_CONTROL.switch_min, conf.AIR_CONTROL.switch_sec)
    while datetime.datetime.now() < next_switch:
        await asyncio.sleep(0.5)
        if pm.is_crashed() or pm.is_vhs_timeout_exceeded():
            return
    
    if pm.is_vhs_active():
        return
    
    # Переключаемся на стандартный режим (FFMPEG2 — запуск плейлиста с начала)
    await pm.switch_to(ProcessType.FFMPEG2)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Завершение работы менеджера эфира...")
