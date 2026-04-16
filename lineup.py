# lineup.py — Генератор расписания программ для интерфейса
import time
import os
from datetime import datetime, timedelta
from config_loader import conf

# Загружаем человекочитаемые названия жанров из секции [PROGRAM_DISPLAY_NAMES]
program_names = conf.PROGRAM_DISPLAY_NAMES.get_dict()

# Кэш для хранения содержимого файлов расписания
_cache = {}

def get_vhs_config():
    """
    Возвращает настройки киносеанса напрямую из конфига с нормализацией типов.
    Гарантирует, что v_days всегда будет списком, а v_h — числом.
    """
    v_h = conf.AIR_CONTROL.vhs_hour
    v_d = conf.AIR_CONTROL.vhs_days

    # Нормализация часа
    if v_h is None or v_h == "":
        v_h = 20
    else:
        try:
            v_h = int(v_h)
        except (ValueError, TypeError):
            v_h = 20

    # Нормализация дней (vhs_days)
    if v_d is None or v_d == "":
        v_d = []
    elif isinstance(v_d, int):
        v_d = [v_d]
    elif not isinstance(v_d, list):
        # Если пришла строка или что-то иное, во избежание ошибок делаем пустой список
        v_d = []
        
    return v_h, v_d

def fetch_schedule(weekday):
    """
    Ищет файл расписания для конкретного дня (например, program0.txt).
    Если файла дня нет, возвращает путь к дефолтной программе.
    """
    fname = f"program{weekday}.txt"
    default_target = conf.PATHS.program_default
    target = fname if os.path.exists(fname) else default_target
    
    if not os.path.exists(target):
        return []

    # Проверка времени последнего изменения файла
    m_time = os.path.getmtime(target)
    if target in _cache and _cache[target]['mtime'] == m_time:
        return _cache[target]['data']

    try:
        with open(target, "r", encoding="utf-8") as f:
            content = [l.strip() for l in f if l.strip()]
        # Обновляем кэш
        _cache[target] = {'mtime': m_time, 'data': content}
        return content
    except Exception as e:
        return []

def get_lineup_lines() -> list[str]:
    """
    Формирует список строк «Сейчас», «Далее» и расписание на ближайшие часы.
    """
    now_dt = datetime.now()
    h_now = now_dt.hour
    curr_wday = now_dt.weekday()
    
    v_h, v_days = get_vhs_config()

    # Загружаем программы на сегодня и на завтра
    sched_today = fetch_schedule(curr_wday)
    sched_tomorrow = fetch_schedule((curr_wday + 1) % 7)

    def get_prog_display_name(h, offset_days=0):
        target_wday = (curr_wday + offset_days) % 7
        
        # Проверка на киносеанс (v_days теперь гарантированно список)
        if v_days and target_wday in v_days:
            if h == v_h or h == (v_h + 1) % 24:
                return program_names.get("vhs_movie", "КИНОСЕАНС")
                
        source = sched_tomorrow if offset_days > 0 else sched_today
        if not source: return "Перерыв"
        
        idx = h % 24
        p_code = source[idx] if idx < len(source) else source[-1]
        return program_names.get(p_code, p_code)

    output = []
    
    c_name = get_prog_display_name(h_now)
    n_h = (h_now + 1) % 24
    n_name = get_prog_display_name(n_h, 1 if n_h == 0 else 0)
    
    output.append(f"Сейчас: {c_name}")
    output.append(f"Далее: {n_name}")

    for offset in range(2, 6):
        t_dt = now_dt + timedelta(hours=offset)
        t_h = t_dt.hour
        p_name = get_prog_display_name(t_h, 1 if t_dt.date() > now_dt.date() else 0)
        output.append(f"{t_h:02d}:00: {p_name}")

    return output

def get_long_schedule() -> list[list[str]]:
    """
    Генерирует массив блоков расписания на 3 дня вперед.
    """
    now = datetime.now()
    start_date = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    v_h, v_days = get_vhs_config()
    blocks = []
    
    days_rus = ["Пнд", "Втр", "Срд", "Чтв", "Птн", "Суб", "Вск"]
    months_rus = ["", "Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
    
    for block_idx in range(6):
        block_lines = []
        block_start_time = start_date + timedelta(hours=12 * block_idx)
        
        d = block_start_time.day
        m = block_start_time.month
        wday = block_start_time.weekday()
        time_tag = "(ночь)" if block_start_time.hour == 0 else "(день)"
        
        date_str = f"      [{d:02d}] {months_rus[m]} {days_rus[wday]} {time_tag}"
        block_lines.append(date_str)
        
        for offset in range(12):
            target_time = block_start_time + timedelta(hours=offset)
            w_t = target_time.weekday()
            h = target_time.hour
            
            # Логика определения жанра с учетом VHS
            if v_days and w_t in v_days and (h == v_h or h == (v_h + 1) % 24):
                p_name = program_names.get("vhs_movie", "КИНОСЕАНС")
            else:
                sched = fetch_schedule(w_t)
                p_code = sched[h % 24] if sched and (h % 24) < len(sched) else "---"
                p_name = program_names.get(p_code, p_code)
            
            block_lines.append(f"             ├{h:02d}:00 {p_name}")
            
        blocks.append(block_lines)
        
    return blocks
