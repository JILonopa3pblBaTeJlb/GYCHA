# vhs_runner.py — Формирование команд FFmpeg для киносеансов
import shlex
import os
from pathlib import Path
from config_loader import conf

def _get_raw_template(template_attr):
    """
    Вспомогательная функция для корректного чтения шаблонов из конфига.
    Поскольку фильтры FFmpeg часто содержат запятые, ConfigParser может 
    ошибочно интерпретировать строку как список. Функция склеивает такие 
    фрагменты обратно в единую команду.
    """
    if isinstance(template_attr, list):
        return ",".join(map(str, template_attr))
    return str(template_attr)

def ffmpeg_vhs_cmd(input_file, pip_file=None, start_sec=0):
    """
    Основной конструктор команды для запуска видео.
    
    Как это работает:
    1. Берет шаблон 'vhs' из секции [FFMPEG_TEMPLATES].
    2. Если указан start_sec, добавляет параметр -ss перед входом, чтобы 
       перемотать фильм на нужный момент.
    3. Подставляет пути к шрифтам, файлам бегущей строки и RTMP-урл.
    4. Очищает команду от лишних пробелов для корректного запуска в shell.
    
    Параметры:
        input_file: Путь к основному файлу фильма (movie.mp4).
        pip_file: Видео для режима "картинка в картинке" (если не указано, берется из конфига).
        start_sec: Позиция в секундах, с которой нужно начать или продолжить показ.
    """
    # Загружаем шаблон команды из конфигурации
    template = _get_raw_template(conf.FFMPEG_TEMPLATES.vhs)
    
    # Формируем строку перемотки (seek)
    ss_pos = f"-ss {start_sec}" if start_sec > 0 else ""
    
    # Определяем файл для PIP-оверлея (второстепенное видео в углу экрана)
    if not pip_file:
        pip_file = conf.PATHS.pip_video

    # Подставляем все необходимые данные в шаблон
    # Ключи в шаблоне: {ss_pos}, {input}, {pip}, {font}, {broadcast_file}, {rtmp_url}
    cmd_str = template.format(
        ss_pos=ss_pos,
        input=input_file,
        pip=pip_file,
        font=conf.GLOBAL.font_main,
        broadcast_file=conf.PATHS.broadcast_file,
        rtmp_url=conf.FFMPEG_SETTINGS.rtmp_url
    )
    
    # Удаляем возможные двойные пробелы, возникшие при пустом ss_pos
    cmd_str = " ".join(cmd_str.split())
    
    # Разбиваем строку на список аргументов, безопасный для subprocess
    return shlex.split(cmd_str)

def get_ffmpeg_vhs_cmd():
    """
    Генерирует стандартную команду для начала нового киносеанса.
    Фильм всегда называется 'movie.mp4' и запускается с 0-й секунды.
    """
    input_file = "movie.mp4"
    return ffmpeg_vhs_cmd(input_file, start_sec=0)

def get_ffmpeg_vhs_backup_cmd(start_sec):
    """
    Генерирует команду для аварийного возобновления киносеанса.
    Используется ProcessManager-ом, если основной процесс VHS упал, 
    чтобы зрители могли продолжить просмотр почти с того же места.
    
    Параметры:
        start_sec: Время в секундах, на котором произошел обрыв.
    """
    input_file = "movie.mp4"
    return ffmpeg_vhs_cmd(input_file, start_sec=start_sec)
