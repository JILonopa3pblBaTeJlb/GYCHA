import datetime
import random
import json
from pathlib import Path
from config_loader import conf

# Динамическое определение путей на основе конфигурационного файла
# BASE_DIR — корень проекта, HISTORY_FILE — база данных прослушанных треков
BASE_DIR = Path(conf.GLOBAL.base_dir).resolve()
HISTORY_FILE = BASE_DIR / conf.GLOBAL.history_file

def load_history():
    """
    Загружает историю воспроизведения из JSON-файла.
    Используется для предотвращения повторов треков и рекламы.
    """
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history):
    """
    Сохраняет обновленную историю воспроизведения в JSON-файл.
    """
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def read_hour_structure():
    """
    Читает шаблон структуры часа из файла hour.txt.
    Шаблон определяет порядок элементов (например: джингл, трек, реклама).
    """
    path = BASE_DIR / "hour.txt"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def read_program_schedule_for_day(target_date=None):
    """
    Определяет расписание жанров для конкретного дня.
    Ищет файлы типа program0.txt (понедельник) ... program6.txt (воскресенье).
    Если файл дня не найден, берет дефолтную программу из конфига.
    """
    if target_date is None:
        target_date = datetime.datetime.now()
    
    weekday = target_date.weekday()
    program_file = BASE_DIR / f"program{weekday}.txt"
    
    if not program_file.exists():
        program_file = BASE_DIR / conf.PATHS.program_default
        
    with open(program_file, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def get_random_file(folder: Path, history=None, key=None):
    """
    Выбирает случайный файл из папки (например, джингл), 
    стараясь не повторять тот, который играл последним.
    """
    files = list(folder.glob("*.m4a"))
    if not files:
        return None
    
    last_played = history.get(key, {}).get("last_played") if history and key else None
    candidates = [f for f in files if f.name != last_played] or files
    track = random.choice(candidates)
    
    if history is not None and key is not None:
        history.setdefault(key, {})["last_played"] = track.name
    return track

def get_track_with_history(folder, genre, history):
    """
    Умный выбор музыкального трека. 
    Следит за списком уже сыгранных файлов (played) и списком недавних (recent),
    чтобы обеспечить максимальную ротацию без частых повторов.
    """
    all_tracks = [t for t in Path(folder).glob("*.m4a") if t.name != "intro.m4a"]
    if not all_tracks:
        return None
    
    all_names = [t.name for t in all_tracks]
    
    # Инициализация структуры истории для жанра
    genre_hist = history.get(genre, {})
    if not isinstance(genre_hist, dict):
        genre_hist = {}
        history[genre] = genre_hist

    played = genre_hist.get("played", [])
    recent = genre_hist.get("recent", [])
    
    # Если все треки из папки уже сыграны, сбрасываем круг
    if set(played) >= set(all_names):
        played = []
    
    # Приоритет выбора: треки, которых нет ни в played, ни в recent
    candidates = [t for t in all_tracks if t.name not in played and t.name not in recent] or \
                 [t for t in all_tracks if t.name not in recent] or \
                 all_tracks
                 
    track = random.choice(candidates)
    
    # Обновление истории: добавляем в сыгранные и ограничиваем глубину памяти
    genre_hist["played"] = (played + [track.name])[-len(all_names):]
    genre_hist["recent"] = (recent + [track.name])[-5:] # Помнить 5 последних
    
    return track

def get_ad_with_history(history):
    """
    Выбирает рекламный ролик из папки 'ad', используя ту же логику ротации, 
    что и для музыкальных треков.
    """
    folder = BASE_DIR / "ad"
    key = "ad_rotation"
    all_ads = list(folder.glob("*.m4a"))
    if not all_ads:
        return None
    
    all_names = [t.name for t in all_ads]
    key_hist = history.setdefault(key, {"played": [], "recent": []})

    if set(key_hist["played"]) >= set(all_names):
        key_hist["played"] = []
        
    candidates = [t for t in all_ads if t.name not in key_hist["played"] and t.name not in key_hist["recent"]] or \
                 all_ads
                 
    ad = random.choice(candidates)
    key_hist["played"].append(ad.name)
    key_hist["recent"] = (key_hist["recent"] + [ad.name])[-5:]
    
    return ad

def build_hour_block(hour, genre, structure, history):
    """
    Основной конструктор блока. 
    Проходит по структуре часа и заменяет теги ([track], jingles, ad) 
    на реальные пути к файлам в формате, понятном для FFmpeg concat demuxer.
    """
    result = []
    for item in structure:
        path = None
        if item == "time_signals":
            # Сигналы точного времени (например, 05oclock.m4a)
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
            track_path = get_track_with_history(BASE_DIR / genre, genre, history)
            if track_path:
                path = track_path
        
        if path and path.exists():
            # Формируем строку для ffmpeg concat: file 'путь/к/файлу.m4a'
            rel_path = path.relative_to(BASE_DIR)
            result.append(f"file '{rel_path.as_posix()}'")
            
    return result

def generate_playlist_next_hour_only():
    """
    Главная функция запуска. 
    Определяет параметры следующего часа и записывает готовый playlist.txt.
    """
    hour_structure = read_hour_structure()
    now = datetime.datetime.now()
    next_hour_dt = now + datetime.timedelta(hours=1)
    next_hour = next_hour_dt.hour

    # Определяем жанр по расписанию
    program_genres = read_program_schedule_for_day(next_hour_dt)
    genre = program_genres[next_hour]

    history = load_history()
    
    # Корректировка структуры: замена дневных джинглов на ночные по времени
    structure = [
        "night_jingles" if x == "day_jingles" and (next_hour < 6 or next_hour >= 18) else x
        for x in hour_structure
    ]
    
    playlist_lines = build_hour_block(next_hour, genre, structure, history)

    # Сохранение плейлиста для FFmpeg
    playlist_path = BASE_DIR / conf.PATHS.playlist_file
    with open(playlist_path, "w", encoding="utf-8") as f:
        f.write("\n".join(playlist_lines))
    
    save_history(history)
    print(f"--- Playlist generated for {next_hour:02d}:00 (Genre: {genre}) ---")

if __name__ == "__main__":
    generate_playlist_next_hour_only()
