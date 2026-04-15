
import shlex
import os
from pathlib import Path
from config_loader import conf

def _get_raw_template(template_attr):
    if isinstance(template_attr, list):
        return ",".join(map(str, template_attr))
    return str(template_attr)

def ffmpeg_vhs_cmd(input_file, pip_file=None, start_sec=0):
    template = _get_raw_template(conf.FFMPEG_TEMPLATES.vhs)
    ss_pos = f"-ss {start_sec}" if start_sec > 0 else ""
    
    if not pip_file:
        pip_file = conf.PATHS.pip_video

    gop = conf.FFMPEG_SETTINGS.gop or 50

    cmd_str = template.format(
        ss_pos=ss_pos,
        input=input_file,
        pip=pip_file,
        font=conf.GLOBAL.font_main,
        broadcast_file=conf.PATHS.broadcast_file,
        rtmp_url=conf.FFMPEG_SETTINGS.rtmp_url,
        gop=gop
    )
    
    cmd_str = " ".join(cmd_str.split())
    return shlex.split(cmd_str)

def get_ffmpeg_vhs_cmd():
    return ffmpeg_vhs_cmd("movie.mp4", start_sec=0)

def get_ffmpeg_vhs_backup_cmd(start_sec):
    return ffmpeg_vhs_cmd("movie.mp4", start_sec=start_sec)
