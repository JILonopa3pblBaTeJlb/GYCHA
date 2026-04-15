
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

def _get_raw_template(template_attr):
    if isinstance(template_attr, list):
        return ",".join(map(str, template_attr))
    return str(template_attr)

def get_ffmpeg2_cmd():
    """Формирует команду старта часа для RTMPS Telegram."""
    template = _get_raw_template(conf.FFMPEG_TEMPLATES.standard)
    
    # Фолбеки на случай, если в config.ini забыли прописать параметры
    fps = conf.FFMPEG_SETTINGS.fps or 25
    gop = conf.FFMPEG_SETTINGS.gop or 50
    
    cmd_str = template.format(
        cover_image=conf.PATHS.cover_image,
        font=conf.GLOBAL.font_main,
        playlist=PLAYLIST_FILE,
        overlay_concat=CONCAT_OVERLAY_FILE,
        log_file=conf.GLOBAL.log_buffer_file,
        v_bitrate=conf.FFMPEG_SETTINGS.v_bitrate or "400k",
        v_maxrate=conf.FFMPEG_SETTINGS.v_maxrate or "600k",
        v_bufsize=conf.FFMPEG_SETTINGS.v_bufsize or "1200k",
        a_bitrate=conf.FFMPEG_SETTINGS.a_bitrate or "128k",
        rtmp_url=conf.FFMPEG_SETTINGS.rtmp_url,
        fps=fps,
        gop=gop
    )
    
    return shlex.split(cmd_str)

def get_ffmpeg3_cmd():
    """Формирует команду подхвата эфира (seek) для RTMPS Telegram."""
    now = datetime.datetime.now()
    sec = now.second + now.minute * 60
    offset = max(sec - 90, 0)
    
    template = _get_raw_template(conf.FFMPEG_TEMPLATES.standard)
    
    fps = conf.FFMPEG_SETTINGS.fps or 25
    gop = conf.FFMPEG_SETTINGS.gop or 50
    
    cmd_str = template.format(
        cover_image=conf.PATHS.cover_image,
        font=conf.GLOBAL.font_main,
        playlist=PLAYLIST_FILE,
        overlay_concat=CONCAT_OVERLAY_FILE,
        log_file=conf.GLOBAL.log_buffer_file,
        v_bitrate=conf.FFMPEG_SETTINGS.v_bitrate or "400k",
        v_maxrate=conf.FFMPEG_SETTINGS.v_maxrate or "600k",
        v_bufsize=conf.FFMPEG_SETTINGS.v_bufsize or "1200k",
        a_bitrate=conf.FFMPEG_SETTINGS.a_bitrate or "128k",
        rtmp_url=conf.FFMPEG_SETTINGS.rtmp_url,
        fps=fps,
        gop=gop
    )
    
    # Вставляем перемотку перед входом плейлиста
    marker = f"-i {PLAYLIST_FILE}"
    if marker in cmd_str:
        cmd_str = cmd_str.replace(marker, f"-ss {offset} {marker}")

    return shlex.split(cmd_str)

def build_overlay_concat():
    pip_path = Path(conf.PATHS.pip_dir)
    if not pip_path.exists():
        pip_path.mkdir(parents=True, exist_ok=True)
        
    mp4_files = [f for f in os.listdir(conf.PATHS.pip_dir) if f.lower().endswith(".mp4")]
    if not mp4_files:
        # Резервный файл, если папка пуста
        with open(CONCAT_OVERLAY_FILE, "w", encoding="utf-8") as f:
            f.write(f"file '{conf.PATHS.cover_image}'\n")
        return
            
    random.shuffle(mp4_files)
    with open(CONCAT_OVERLAY_FILE, "w", encoding="utf-8") as f:
        for mp4 in mp4_files:
            abs_path = Path(conf.PATHS.pip_dir) / mp4
            f.write(f"file '{abs_path.as_posix()}'\n")

async def run_ffmpeg(cmd, name=None):
    name = name or "FFmpeg"
    print(f"▶️ Запуск: {name}")
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
            proc.kill()
        except: pass
    print(f"✅ {name} остановлен.")

async def log_to_file(name, message):
    log_path = conf.PATHS.system_log
    with open(log_path, "a", encoding="utf-8") as f:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{ts}][{name}] {message}\n")
