import json
import textwrap
from pathlib import Path
from config_loader import conf

# Определяем ширину строки в соответствии с дизайном GUI (status.py)
LINE_WIDTH = 34

def get_last_vhs_id():
    """
    Находит ID последнего скачанного фильма в истории загрузок.
    Зачем: Чтобы знать, для какого фильма генерировать описание.
    """
    history_path = Path(conf.PATHS.downloaded_history)
    if not history_path.exists():
        return None
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            vhs_list = data.get("vhs", [])
            return vhs_list[-1] if vhs_list else None
    except Exception as e:
        print(f"Ошибка чтения истории: {e}")
        return None

def load_movie_data(post_id):
    """
    Ищет подробные метаданные фильма в JSON-базе.
    """
    db_path = Path(conf.PATHS.vhs_metadata)
    if not db_path.exists():
        return None
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            db = json.load(f)
            for movie in db:
                if int(movie.get("post_id", 0)) == int(post_id):
                    return movie
    except Exception: pass
    return None

def generate_card(post_id=None):
    """
    Генерирует текстовый файл movie.txt.
    Зачем: Этот файл считывается GUI вещания и анонсером. 
    Как: Форматирует данные (рейтинг, год, актеры) в красивые колонки.
    """
    target_id = post_id or get_last_vhs_id()
    if not target_id:
        return False

    movie = load_movie_data(target_id)
    output_path = Path(conf.PATHS.movie_info_file)

    if not movie:
        output_path.write_text("Сведения о фильме отсутствуют", encoding="utf-8")
        return False

    lines = []
    
    # Формирование "шапки" карточки
    title_ru = movie.get("title_ru", "").upper()
    if title_ru:
        lines.extend(textwrap.wrap(title_ru, width=LINE_WIDTH))
    
    title_en = movie.get("title_en", "")
    if title_en and title_en.upper() != title_ru:
        lines.extend(textwrap.wrap(title_en, width=LINE_WIDTH))
    
    lines.append("-" * LINE_WIDTH)

    # Техническая информация (Год, Длительность, Режиссер)
    year = movie.get("year")
    runtime = movie.get("runtime")
    if (year and year != 0) or (runtime and runtime != "N/A"):
        lines.append(f"{year if year else ''}г. {runtime if runtime != 'N/A' else ''}".strip())

    director = movie.get("director")
    if director and director not in ["N/A", "Неизвестен"]:
        lines.extend(textwrap.wrap(f"Реж: {director}", width=LINE_WIDTH))

    # Блок рейтингов (IMDb и Rotten Tomatoes)
    ratings = movie.get("ratings", {})
    imdb, rt = ratings.get("imdb"), ratings.get("rt")
    rat_line = " ".join([f"IMDb:{imdb}" if imdb != "N/A" else "", f"RT:{rt}" if rt != "N/A" else ""])
    if rat_line.strip():
        lines.append(rat_line.strip())

    lines.append("-" * LINE_WIDTH)

    # Список актеров (ограничиваем 3 строками, чтобы не перегружать экран)
    cast = movie.get("cast", [])
    if cast:
        cast_str = "В ролях: " + ", ".join(cast)
        lines.extend(textwrap.wrap(cast_str, width=LINE_WIDTH)[:3])

    lines.append("") # Разделитель перед описанием

    # Обработка основного описания (Overview)
    overview = movie.get("overview")
    if overview and overview != "Нет описания":
        paragraphs = overview.split('\n\n')
        for p in paragraphs:
            if not p.strip(): continue
            # Убираем лишние пробелы и красиво нарезаем текст по ширине LINE_WIDTH
            clean_p = " ".join(p.split())
            ov_lines = textwrap.wrap(clean_p, width=LINE_WIDTH, break_long_words=False)
            lines.extend(ov_lines)
            lines.append("") # Пустая строка между абзацами

    # Финальная запись
    try:
        if lines and lines[-1] == "": lines.pop()
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return True
    except Exception as e:
        print(f"Ошибка сохранения карточки: {e}")
        return False

if __name__ == "__main__":
    import sys
    # Возможность вызвать скрипт вручную для конкретного ID поста
    manual_id = sys.argv[1] if len(sys.argv) > 1 else None
    generate_card(manual_id)
