import asyncio
import datetime
import os
import random
import signal
import shlex
from pathlib import Path
from config_loader import conf

LOG_FILE = conf.PATHS.system_log
PIP_DIR = conf.PATHS.pip_dir
PLAYLIST_FILE = conf.PATHS.playlist_file
CONCAT_OVERLAY_FILE = conf.PATHS.overlay_concat_file

def _get_abs_path(rel_path):
    """Превращает относительный путь из конфига в абсолютный."""
    return Path(conf.GLOBAL.base_dir).resolve() / rel_path

def _get_raw_template(template_attr):
    if isinstance(template_attr, list):
        return ",".join(map(str, template_attr))
    # Очищаем шаблон от переносов строк и лишних пробелов
    return " ".join(str(template_attr).split())

def get_ffmpeg2_cmd():
    """Формирует команду старта часа для RTMPS Telegram."""
    template = _get_raw_template(conf.FFMPEG_TEMPLATES.standard)
    
    # Резолвим пути к критичным файлам
    abs_cover = _get_abs_path(conf.PATHS.cover_image)
    abs_playlist = _get_abs_path(conf.PATHS.playlist_file)
    abs_overlay = _get_abs_path(conf.PATHS.overlay_concat_file)
    abs_font = _get_abs_path(conf.GLOBAL.font_main)
    abs_log = _get_abs_path(conf.GLOBAL.log_buffer_file)
    
    # Гарантируем наличие файла логов
    if not abs_log.exists():
        abs_log.touch()

    cmd_str = template.format(
        cover_image=abs_cover.as_posix(),
        font=abs_font.as_posix(),
        playlist=abs_playlist.as_posix(),
        overlay_concat=abs_overlay.as_posix(),
        log_file=abs_log.as_posix(),
        v_bitrate=conf.FFMPEG_SETTINGS.v_bitrate,
        v_maxrate=conf.FFMPEG_SETTINGS.v_maxrate,
        v_bufsize=conf.FFMPEG_SETTINGS.v_bufsize,
        a_bitrate=conf.FFMPEG_SETTINGS.a_bitrate,
        rtmp_url=conf.FFMPEG_SETTINGS.rtmp_url,
        fps=conf.FFMPEG_SETTINGS.fps or 25,
        gop=conf.FFMPEG_SETTINGS.gop or 50
    )
    
    return shlex.split(cmd_str)

def get_ffmpeg3_cmd():
    """Формирует команду подхвата эфира (seek) для RTMPS Telegram."""
    now = datetime.datetime.now()
    # Считаем смещение от начала часа (с запасом 5 секунд на старт)
    offset = max((now.minute * 60 + now.second) - 5, 0)
    
    template = _get_raw_template(conf.FFMPEG_TEMPLATES.standard)
    
    abs_cover = _get_abs_path(conf.PATHS.cover_image)
    abs_playlist = _get_abs_path(conf.PATHS.playlist_file)
    abs_overlay = _get_abs_path(conf.PATHS.overlay_concat_file)
    abs_font = _get_abs_path(conf.GLOBAL.font_main)
    abs_log = _get_abs_path(conf.GLOBAL.log_buffer_file)

    if not abs_log.exists():
        abs_log.touch()

    cmd_str = template.format(
        cover_image=abs_cover.as_posix(),
        font=abs_font.as_posix(),
        playlist=abs_playlist.as_posix(),
        overlay_concat=abs_overlay.as_posix(),
        log_file=abs_log.as_posix(),
        v_bitrate=conf.FFMPEG_SETTINGS.v_bitrate,
        v_maxrate=conf.FFMPEG_SETTINGS.v_maxrate,
        v_bufsize=conf.FFMPEG_SETTINGS.v_bufsize,
        a_bitrate=conf.FFMPEG_SETTINGS.a_bitrate,
        rtmp_url=conf.FFMPEG_SETTINGS.rtmp_url,
        fps=conf.FFMPEG_SETTINGS.fps or 25,
        gop=conf.FFMPEG_SETTINGS.gop or 50
    )
    
    # Вставляем перемотку ПЕРЕД плейлистом
    # Важно: ищем именно путь к плейлисту в уже сформированной строке
    marker = f"-i {abs_playlist.as_posix()}"
    if marker in cmd_str:
        cmd_str = cmd_str.replace(marker, f"-ss {offset} {marker}")

    return shlex.split(cmd_str)

def build_overlay_concat():
    base_dir = Path(conf.GLOBAL.base_dir).resolve()
    pip_path = base_dir / conf.PATHS.pip_dir
    overlay_file = base_dir / CONCAT_OVERLAY_FILE

    if not pip_path.exists():
        pip_path.mkdir(parents=True, exist_ok=True)
        
    mp4_files = [f for f in os.listdir(pip_path) if f.lower().endswith(".mp4")]
    if not mp4_files:
        with open(overlay_file, "w", encoding="utf-8") as f:
            f.write(f"file '{_get_abs_path(conf.PATHS.cover_image).as_posix()}'\n")
        return
            
    random.shuffle(mp4_files)
    with open(overlay_file, "w", encoding="utf-8") as f:
        for mp4 in mp4_files:
            abs_path = (pip_path / mp4).resolve()
            f.write(f"file '{abs_path.as_posix()}'\n")

async def run_ffmpeg(cmd, name=None):
    name = name or "FFmpeg"
    print(f"▶️ Запуск: {name}")
    # Вывод команды для отладки (можно закомментировать позже)
    # print(f"DEBUG CMD: {' '.join(cmd)}")
    return await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

async def stop_proc(proc, name):
    if proc is None or proc.returncode is not None:
        return
    print(f"⏹ Остановка {name}...")
    try:
        proc.send_signal(signal.SIGINT)
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            proc.terminate()
            await asyncio.sleep(1)
            if proc.returncode is None:
                proc.kill()
        except: pass
    print(f"✅ {name} остановлен.")

async def log_to_file(name, message):
    log_path = _get_abs_path(conf.PATHS.system_log)
    with open(log_path, "a", encoding="utf-8") as f:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{ts}][{name}] {message}\n")
