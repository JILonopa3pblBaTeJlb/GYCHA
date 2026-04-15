import datetime
import random
import json
from pathlib import Path

# Предполагается, что конфиг загружает пути из env или внешнего yaml/toml.
# Зачем: Чтобы не хардкодить абсолютные пути (C:/Users/...) в коде.
from config_loader import conf

# Динамическое определение корневой директории проекта.
# Почему так: resolve() превращает относительный путь в абсолютный,
# что исключает ошибки при запуске скрипта из разных папок.
BASE_DIR = Path(conf.GLOBAL.base_dir).resolve()
HISTORY_FILE = BASE_DIR / conf.GLOBAL.history_file


def load_history():
    """
    Загружает историю проигранных файлов из JSON.
    Зачем: Чтобы после перезапуска скрипта радио не начинало играть одни и те же треки.
    """
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(history):
    """
    Сохраняет обновленную историю в файл.
    Как работает: Использует indent=2 для читаемости и ensure_ascii=False для поддержки кириллицы в названиях песен.
    """
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def read_hour_structure():
    """
    Читает шаблон часа (например: джингл, трек, трек, реклама).
    Зачем: Позволяет менять сетку вещания, просто редактируя текстовый файл, без правок кода.
    """
    hour_file = BASE_DIR / "hour.txt"
    if not hour_file.exists():
        return []
    return [line.strip() for line in hour_file.open("r", encoding="utf-8") if line.strip()]


def read_program_schedule_for_day(target_date=None):
    """
    Определяет жанр/программу для каждого часа текущего дня.
    Как работает: Ищет файл programN.txt (где N - день недели). Если нет — берет дефолт.
    Зачем: Позволяет настраивать уникальную музыку для выходных или спец. эфиров.
    """
    if target_date is None:
        target_date = datetime.datetime.now()
    
    weekday = target_date.weekday()
    program_file = BASE_DIR / f"program{weekday}.txt"
    
    # Если файла на конкретный день нет, берем стандартное расписание из конфига
    if not program_file.exists():
        program_file = BASE_DIR / conf.PATHS.program_default
        
    return [line.strip() for line in program_file.open("r", encoding="utf-8") if line.strip()]


def get_random_file(folder: Path, history=None, key=None):
    """
    Выбирает случайный файл из папки, избегая повтора последнего сыгранного.
    Зачем: Для джинглов, чтобы один и тот же звук не играл дважды подряд.
    """
    files = list(folder.glob("*.m4a"))
    if not files:
        return None
    
    last_played = history.get(key, {}).get("last_played") if history and key else None
    # Фильтруем список, исключая последний трек
    candidates = [f for f in files if f.name != last_played] or files
    track = random.choice(candidates)
    
    if history is not None and key is not None:
        history.setdefault(key, {})["last_played"] = track.name
    return track


def get_track_with_history(folder, genre, history):
    """
    Сложный алгоритм выбора музыкального трека.
    Логика:
    1. Исключаем недавно проигранные треки ('recent').
    2. Исключаем треки, которые уже играли в текущем цикле ('played'), пока не проиграем всё.
    Зачем: Чтобы создать ощущение бесконечного и разнообразного потока без частых повторов.
    """
    all_tracks = [t for t in Path(folder).glob("*.m4a") if t.name != "intro.m4a"]
    if not all_tracks:
        return None
    
    all_names = [t.name for t in all_tracks]
    
    # Инициализация структуры данных в истории, если жанр новый
    if genre not in history or not isinstance(history[genre], dict):
        history[genre] = {"played": [], "recent": []}
    
    genre_hist = history[genre]
    played = genre_hist.get("played", [])
    recent = genre_hist.get("recent", [])
    
    # Если все песни из папки уже были проиграны, сбрасываем цикл
    if set(played) >= set(all_names):
        played = []
    
    # Выбираем кандидатов: те, что не в 'played' и не в 'recent' (последние 5 песен)
    candidates = [t for t in all_tracks if t.name not in played and t.name not in recent] or \
                 [t for t in all_tracks if t.name not in recent] or \
                 all_tracks
                 
    track = random.choice(candidates)
    name = track.name
    
    # Обновляем историю: добавляем в сыгранные и в список последних
    genre_hist["played"] = (played + [name])[-len(all_names):]
    genre_hist["recent"] = (recent + [name])[-5:] # Храним 5 последних треков для жесткого исключения
    
    return track

def get_ad_with_history(history):
    """
    Ротация рекламных роликов.
    Аналогична музыкальной, но использует отдельный ключ в истории.
    """
    folder = BASE_DIR / "ad"
    key = "ad_rotation"
    all_ads = list(folder.glob("*.m4a"))
    if not all_ads:
        return None
    
    # Логика исключения повторов (аналогична get_track_with_history)
    if key not in history or not isinstance(history[key], dict):
        history[key] = {"played": [], "recent": []}
        
    key_hist = history[key]
    played = key_hist.get("played", [])
    recent = key_hist.get("recent", [])

    # ИСПРАВЛЕНО: Сравниваем set с set, чтобы определить окончание цикла ротации
    if set(played) >= set(t.name for t in all_ads):
        played = []
        
    candidates = [t for t in all_ads if t.name not in played and t.name not in recent] or all_ads
    ad = random.choice(candidates)
    
    key_hist["played"] = (played + [ad.name])[-len(all_ads):]
    key_hist["recent"] = (recent + [ad.name])[-3:]
    
    return ad


def build_hour_block(hour, genre, structure, history):
    """
    Собирает список путей к файлам на основе структуры часа.
    Зачем: Это 'движок', который превращает абстрактный '[track]' в путь к файлу.
    Как работает: Проходит циклом по hour.txt и вызывает нужные функции выбора.
    """
    result = []
    for item in structure:
        path = None
        
        if item == "time_signals":
            path = BASE_DIR / f"timesignals/{hour:02d}oclock.m4a"
        elif item == "day_jingles":
            path = get_random_file(BASE_DIR / "day_jingles", history, "day_jingles")
        elif item == "night_jingles":
            path = get_random_file(BASE_DIR / "night_jingles", history, "night_jingles")
        elif item == "news":
            path = BASE_DIR / "news/news.m4a"
        elif item == "ad":
            path = get_ad_with_history(history)
        elif item == "jingles":
            path = get_random_file(BASE_DIR / "jingles", history, "jingles")
        elif item == "intro":
            path = BASE_DIR / genre / "intro.m4a"
        elif item == "[track]":
            track = get_track_with_history(BASE_DIR / genre, genre, history)
            path = track if track else None
            
        if path and path.exists():
            # Форматируем путь для ffmpeg concat demuxer
            # Почему as_posix(): Чтобы на Windows пути были через '/', а не '\'
            rel_path = path.relative_to(BASE_DIR)
            result.append(f"file '{rel_path.as_posix()}'")
            
    return result


def generate_playlist_next_hour_only():
    """
    Основная функция запуска. Генерирует плейлист на следующий час.
    Особенности:
    - Учитывает смену суток (переход в 00:00).
    - Меняет дневные джинглы на ночные автоматически.
    - Сохраняет результат в файл для ffmpeg.
    """
    hour_structure = read_hour_structure()
    now = datetime.datetime.now()
    next_hour = (now.hour + 1) % 24

    # Обработка перехода через полночь для выбора правильной программы дня
    target_date = now + datetime.timedelta(days=1) if next_hour == 0 else now
    
    program_genres = read_program_schedule_for_day(target_date)
    genre = program_genres[next_hour]

    history = load_history()
    
    # Автоматическая замена типа джинглов в зависимости от времени суток
    # Зачем: Чтобы не переписывать hour.txt вручную под ночь.
    structure = [
        "night_jingles" if x == "day_jingles" and (next_hour < 6 or next_hour >= 18) else x
        for x in hour_structure
    ]
    
    playlist_lines = build_hour_block(next_hour, genre, structure, history)

    # Запись в файл плейлиста
    playlist_path = BASE_DIR / conf.PATHS.playlist_file
    with open(playlist_path, "w", encoding="utf-8") as f:
        f.write("\n".join(playlist_lines))
        
    save_history(history)
    print(f"--- Playlist generated for {next_hour:02d}:00 (Genre: {genre}) ---")


if __name__ == "__main__":
    generate_playlist_next_hour_only()
