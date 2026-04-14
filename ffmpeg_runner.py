# ffmpeg_runner.py — Генератор команд и запуск FFmpeg
import asyncio
import datetime
import os
import random
import signal
import shlex
from pathlib import Path
from config_loader import conf

# Константы путей, подгружаемые из конфигурации
LOG_FILE = conf.PATHS.system_log
PIP_DIR = conf.PATHS.pip_dir
PLAYLIST_FILE = conf.PATHS.playlist_file
CONCAT_OVERLAY_FILE = conf.PATHS.overlay_concat_file

def _get_raw_template(template_attr):
    """
    Вспомогательная функция для обработки шаблонов команд.
    Если загрузчик конфига встретил запятые в фильтрах FFmpeg и ошибочно 
    превратил строку в список, эта функция склеивает её обратно в одну команду.
    """
    if isinstance(template_attr, list):
        return ",".join(map(str, template_attr))
    return str(template_attr)

# -----------------------------------------------------------------------------
# ФОРМИРОВАНИЕ КОМАНД
# -----------------------------------------------------------------------------

def get_ffmpeg2_cmd():
    """
    Генерирует команду для стандартного запуска радио-эфира.
    Использует шаблон 'standard' из конфига. Плейлист проигрывается с самого начала.
    """
    template = _get_raw_template(conf.FFMPEG_TEMPLATES.standard)
    
    # Подставляем переменные окружения и пути в шаблон
    cmd_str = template.format(
        cover_image=conf.PATHS.cover_image,
        font=conf.GLOBAL.font_main,
        playlist=PLAYLIST_FILE,
        overlay_concat=CONCAT_OVERLAY_FILE,
        log_file=conf.GLOBAL.log_buffer_file,
        v_bitrate=conf.FFMPEG_SETTINGS.v_bitrate,
        v_maxrate=conf.FFMPEG_SETTINGS.v_maxrate,
        v_bufsize=conf.FFMPEG_SETTINGS.v_bufsize,
        a_bitrate=conf.FFMPEG_SETTINGS.a_bitrate,
        rtmp_url=conf.FFMPEG_SETTINGS.rtmp_url
    )
    
    # shlex.split корректно разбивает строку на список аргументов, сохраняя кавычки
    return shlex.split(cmd_str)


def get_ffmpeg3_cmd():
    """
    Генерирует команду для 'подхвата' текущего часа.
    Вычисляет, сколько секунд прошло с начала часа, и добавляет параметр -ss.
    Это позволяет стриму возобновиться с нужного момента в плейлисте после сбоя.
    """
    now = datetime.datetime.now()
    # Считаем секунды от начала часа
    sec = now.second + now.minute * 60
    # Делаем небольшой запас (90 секунд) для буферизации
    offset = max(sec - 90, 0)
    
    template = _get_raw_template(conf.FFMPEG_TEMPLATES.standard)
    
    cmd_str = template.format(
        cover_image=conf.PATHS.cover_image,
        font=conf.GLOBAL.font_main,
        playlist=PLAYLIST_FILE,
        overlay_concat=CONCAT_OVERLAY_FILE,
        log_file=conf.GLOBAL.log_buffer_file,
        v_bitrate=conf.FFMPEG_SETTINGS.v_bitrate,
        v_maxrate=conf.FFMPEG_SETTINGS.v_maxrate,
        v_bufsize=conf.FFMPEG_SETTINGS.v_bufsize,
        a_bitrate=conf.FFMPEG_SETTINGS.a_bitrate,
        rtmp_url=conf.FFMPEG_SETTINGS.rtmp_url
    )
    
    # Внедряем параметр seek (-ss) перед входным файлом плейлиста
    marker = f"-i {PLAYLIST_FILE}"
    if marker in cmd_str:
        cmd_str = cmd_str.replace(marker, f"-ss {offset} {marker}")

    return shlex.split(cmd_str)


# -----------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ОПЕРАЦИИ
# -----------------------------------------------------------------------------

def build_overlay_concat():
    """
    Создает файл 'overlay_concat.txt' для FFmpeg concat demuxer.
    Сканирует папку 'pip' на наличие видео-фонов и перемешивает их.
    Эти видео будут бесконечно крутиться на заднем фоне радио-эфира.
    """
    pip_path = Path(conf.PATHS.pip_dir)
    if not pip_path.exists():
        pip_path.mkdir(parents=True, exist_ok=True)
        
    mp4_files = [f for f in os.listdir(conf.PATHS.pip_dir) if f.lower().endswith(".mp4")]
    
    if not mp4_files:
        # Если папка пуста, вещание с визуальными эффектами невозможно
        raise FileNotFoundError(f"❌ Ошибка: В директории {conf.PATHS.pip_dir} нет видео-файлов для фона.")
            
    random.shuffle(mp4_files)
    
    with open(CONCAT_OVERLAY_FILE, "w", encoding="utf-8") as f:
        for mp4 in mp4_files:
            abs_path = Path(conf.PATHS.pip_dir) / mp4
            path_str = abs_path.as_posix()
            # Повторяем каждый файл несколько раз, чтобы уменьшить частоту переоткрытия файлов демультиплексором
            for _ in range(3):
                f.write(f"file '{path_str}'\n")


async def run_ffmpeg(cmd, name=None):
    """
    Запускает процесс FFmpeg с переданными аргументами.
    Возвращает объект asyncio.subprocess.Process для дальнейшего мониторинга.
    """
    name = name or "FFmpeg"
    print(f"▶️ Запуск процесса: {name}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    return proc


async def stop_proc(proc, name):
    """
    Пытается мягко остановить процесс FFmpeg, отправляя SIGINT (аналог нажатия 'q').
    Если процесс не завершается за 10 секунд, принудительно убивает его.
    """
    if proc is None or proc.returncode is not None:
        return
        
    print(f"⏹ Остановка {name}...")
    try:
        proc.send_signal(signal.SIGINT)
    except ProcessLookupError:
        return
        
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
        print(f"✅ Процесс {name} завершен корректно.")
    except asyncio.TimeoutError:
        print(f"⚠️ {name} не отвечает. Принудительное завершение (kill)...")
        proc.kill()
        await proc.wait()


async def log_to_file(name, message):
    """
    Записывает ошибки и события работы FFmpeg в системный лог.
    """
    log_path = conf.PATHS.system_log
    with open(log_path, "a", encoding="utf-8") as log_fd:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_fd.write(f"[{timestamp}][{name}] {message}\n")
