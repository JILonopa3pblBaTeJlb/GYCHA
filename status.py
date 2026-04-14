# status.py — Главный графический движок и рендерер интерфейса стрима
import asyncio
import os
import shutil
import time
import sys
import select
import termios
import tty
from datetime import datetime, timedelta

# Оптимизация событийного цикла для Linux-серверов
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# Импорт центрального конфига и всех модулей данных
from config_loader import conf
import aiohttp
import res
import finance
import weather
import rss
import lineup
import uvb
import messenger
import diag
import clock

def get_intervals():
    """
    Извлекает интервалы обновления для различных модулей из конфигурации.
    Это позволяет менять частоту опроса API без перезагрузки системы.
    """
    return {
        "res": conf.GUI_STATUS.interval_res_sec,
        "uvb": conf.GUI_STATUS.interval_uvb_sec,
        "finance": conf.GUI_STATUS.interval_finance_sec,
        "weather": conf.GUI_STATUS.interval_weather_sec,
        "rss": conf.GUI_STATUS.interval_rss_sec,
        "lineup": conf.GUI_STATUS.interval_lineup_sec,
        "diag": conf.GUI_STATUS.interval_diag_sec
    }

# Флаг управления локальным выводом в консоль (включается клавишей 'V')
SHOW_CONSOLE = False

# Глобальное хранилище данных, полученных от модулей
STATE = {
    "res": ["Загрузка ресурсов..."],
    "finance": ["Загрузка курсов..."],
    "weather": ["Загрузка погоды..."],
    "rss": ["Загрузка новостей..."],
    "lineup": ["Загрузка расписания..."],
    "long_schedule": [],
    "uvb": ["Ожидание UVB..."],
    "diag": ["Ожидание DIAG..."],
}

def load_vhs_params():
    """
    Загружает параметры киносеансов. 
    Определяет, в какие дни и часы активна панель видеосалона.
    """
    try:
        vhs_hour = conf.AIR_CONTROL.vhs_hour
        vhs_days = conf.AIR_CONTROL.vhs_days
        if isinstance(vhs_days, int):
            vhs_days = [vhs_days]
        return vhs_hour, vhs_days
    except Exception as e:
        return 20, [4, 5, 6] # Значения по умолчанию (Пт, Сб, Вс)

async def task_movie():
    """
    Следит за файлом описания фильма (movie.txt).
    Определяет, является ли фильм "сегодняшним" на основе времени изменения файла (mtime).
    Если файл обновлен недавно (после триггера загрузки), он помечается как актуальный.
    """
    movie_file = conf.PATHS.movie_info_file
    while True:
        try:
            vhs_hour, vhs_days = load_vhs_params()
            now = datetime.now()
            
            if now.weekday() not in vhs_days or not os.path.exists(movie_file):
                STATE["movie_data"] = None
            else:
                offset = conf.CONTENT_MANAGER.vhs_preload_offset_min
                trigger_dt = now.replace(hour=vhs_hour, minute=0, second=0, microsecond=0) - timedelta(minutes=offset)
                
                mtime_dt = datetime.fromtimestamp(os.path.getmtime(movie_file))

                # Выбор заголовка панели в зависимости от новизны контента
                header_ui = "══════СЕГОДНЯ ПОКАЖЕМ═══════╗" if mtime_dt > trigger_dt else "══════РАНЕЕ ПОКАЗЫВАЛИ══════╗"

                def read_and_split():
                    """Разделяет описание фильма на фиксированный заголовок и прокручиваемое описание."""
                    with open(movie_file, "r", encoding="utf-8") as f:
                        all_lines = [line.rstrip() for line in f]
                    
                    split_idx = -1
                    for i, line in enumerate(all_lines):
                        if i > 4 and line.strip() == "": # Ищем пустую строку после технических данных
                            split_idx = i
                            break
                    
                    return (all_lines[:split_idx + 1], all_lines[split_idx + 1:]) if split_idx != -1 else (all_lines, [])
                
                fixed_h, desc_l = await asyncio.to_thread(read_and_split)
                STATE["movie_data"] = {"header_ui": header_ui, "fixed_header": fixed_h, "description": desc_l}
        except Exception:
            STATE["movie_data"] = None
        await asyncio.sleep(60)

def sys_log(text):
    """Служебная функция для внутреннего логирования (отключена для экономии ресурсов)."""
    pass

def get_terminal_width():
    """Определяет ширину терминала для корректной верстки фона."""
    try:
        return max(shutil.get_terminal_size().columns, 132)
    except:
        return 132

def create_background(lines_count, width):
    """Создает пустой холст (список строк из пробелов) для рендеринга."""
    return [' ' * width for _ in range(lines_count)]

def overlay_block(background, content_lines, start_row, start_col):
    """
    Накладывает блок текстовых строк на фоновый холст по указанным координатам.
    Реализует логику "слоев", сохраняя размеры холста.
    """
    if not content_lines: return background
    max_rows = len(background)
    for i, line in enumerate(content_lines):
        row_idx = start_row + i
        if row_idx >= max_rows: break
        
        bg_line = background[row_idx]
        text = str(line).rstrip()
        
        # Обрезаем текст, если он выходит за границы холста справа
        visible_part = text[:len(bg_line) - start_col] if start_col + len(text) > len(bg_line) else text

        left = bg_line[:start_col]
        right = bg_line[start_col + len(visible_part):]
        background[row_idx] = left + visible_part + right
    return background

async def task_runner(key, func, interval_key, session=None):
    """
    Универсальный обертчик для периодического запуска функций из других модулей.
    Обновляет глобальный словарь STATE данными от модулей.
    """
    while True:
        # Динамическое получение интервала (позволяет менять настройки на лету)
        interval = getattr(conf.GUI_STATUS, f"interval_{key}_sec", 60)
        try:
            data = await func(session) if session else await asyncio.to_thread(func)
            if data and isinstance(data, list):
                STATE[key] = data
        except Exception as e:
            print(f"Ошибка в задаче {key}: {e}")
        await asyncio.sleep(interval)

async def task_lineup():
    """Обновляет расписание эфира. Запускается раз в час в начале каждого часа."""
    while True:
        try:
            STATE["lineup"] = await asyncio.to_thread(lineup.get_lineup_lines)
            STATE["long_schedule"] = await asyncio.to_thread(lineup.get_long_schedule)
        except: pass
        
        now = datetime.now()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_hour - now).total_seconds() + 1)

def check_input():
    """Проверяет нажатие клавиши 'V' для переключения режима отображения в консоли."""
    global SHOW_CONSOLE
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        key = sys.stdin.read(1)
        if key.lower() == 'v':
            SHOW_CONSOLE = not SHOW_CONSOLE

def sync_write_logfile(content):
    """
    Атомарно записывает итоговую ASCII-картину в файл лога.
    FFmpeg считывает этот файл для отображения интерфейса на стриме.
    """
    try:
        log_file = conf.GLOBAL.log_buffer_file
        tmp_logfile = log_file + ".tmp"
        with open(tmp_logfile, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_logfile, log_file)
    except: pass

async def renderer():
    """
    ГЛАВНЫЙ ЦИКЛ ОТРИСОВКИ. 
    Работает с частотой refresh_rate_sec (обычно 1 раз в секунду).
    Формирует итоговый кадр, переключает панели и управляет прокруткой.
    """
    global SHOW_CONSOLE
    CLEAR = '\033[2J\033[H' # Код очистки экрана терминала
    weather_scroll_idx = 0
    rss_scroll_idx = 0
    
    # Режим правой панели (циклическая смена: Диагностика -> UVB -> Фильм -> Расписание)
    RIGHT_PANEL_MODE = "DIAG"
    mode_timer = 0
    tick_counter = 0
    
    last_clock_min = -1
    cached_clock_lines = []
    
    # Настройка терминала для неблокирующего чтения клавиатуры
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    
    try:
        tty.setcbreak(fd)
        while True:
            conf.reload()
            check_input()
            
            refresh_rate = conf.GUI_STATUS.refresh_rate_sec
            weather_window = conf.GUI_STATUS.weather_window_size
            
            # Логика прокрутки погоды и новостей
            if tick_counter % 10 == 0:
                w_lines = STATE.get("weather", [])
                if w_lines: weather_scroll_idx = (weather_scroll_idx + 1) % len(w_lines)
                rss_lines = STATE.get("rss", [])
                if rss_lines: rss_scroll_idx = (rss_scroll_idx + 1) % len(rss_lines)

            # --- УПРАВЛЕНИЕ СОСТОЯНИЕМ ПРАВОЙ ПАНЕЛИ ---
            vhs_hour, vhs_days = load_vhs_params()
            
            # Переключение между DIAG, UVB, MOVIE и SCHEDULE по таймеру
            if RIGHT_PANEL_MODE == "DIAG" and mode_timer >= 10:
                RIGHT_PANEL_MODE = "UVB_1"
                mode_timer = 0
            elif RIGHT_PANEL_MODE == "UVB_1" and mode_timer >= 10:
                is_vhs = datetime.now().weekday() in vhs_days and STATE.get("movie_data")
                RIGHT_PANEL_MODE = "MOVIE" if is_vhs else "UVB_2"
                mode_timer = 0
            elif RIGHT_PANEL_MODE == "MOVIE":
                m_data = STATE.get("movie_data")
                if not m_data:
                    RIGHT_PANEL_MODE = "UVB_2"; mode_timer = 0
                else:
                    # Рассчитываем время на чтение всех страниц описания фильма
                    lines_for_desc = max(1, 16 - len(m_data["fixed_header"]))
                    total_pages = max(1, (len(m_data["description"]) + lines_for_desc - 1) // lines_for_desc)
                    if mode_timer >= total_pages * 10:
                        RIGHT_PANEL_MODE = "UVB_2"; mode_timer = 0
            elif RIGHT_PANEL_MODE == "UVB_2" and mode_timer >= 10:
                RIGHT_PANEL_MODE = "SCHEDULE"; mode_timer = 0
            elif RIGHT_PANEL_MODE == "SCHEDULE":
                blocks = STATE.get("long_schedule", [])
                if not blocks or (mode_timer // 10) >= len(blocks):
                    RIGHT_PANEL_MODE = "UVB_3"; mode_timer = 0
            elif RIGHT_PANEL_MODE == "UVB_3" and mode_timer >= 10:
                RIGHT_PANEL_MODE = "DIAG"; mode_timer = 0

            # --- СБОРКА КАДРА ---
            term_width = get_terminal_width()
            
            # Левая колонка (Ресурсы, Финансы, Погода, Плейлист, Бегущая строка)
            left_col = [""] * 5
            for key in ["res", "finance"]:
                if STATE.get(key): left_col.extend(STATE[key])

            # Виджет погоды с вертикальной прокруткой
            w_lines = STATE.get("weather", [])
            if w_lines:
                for i in range(weather_window):
                    left_col.append(w_lines[(weather_scroll_idx + i) % len(w_lines)])
            
            left_col.append("")
            if STATE.get("lineup"): left_col.extend(STATE["lineup"])
            
            left_col.append("")
            left_col.append(messenger.get_broadcast_line() or "—")

            # Новостная лента
            rss_lines = STATE.get("rss", [])
            if rss_lines: left_col.append(rss_lines[rss_scroll_idx % len(rss_lines)])

            # Формирование правой колонки на основе активного режима
            right_col = []
            if "UVB" in RIGHT_PANEL_MODE:
                right_col = list(STATE.get("uvb", []))
            elif RIGHT_PANEL_MODE == "DIAG":
                right_col = list(STATE.get("diag", []))
            elif RIGHT_PANEL_MODE == "SCHEDULE":
                # Отрисовка блоков расписания
                blocks = STATE.get("long_schedule", [])
                if blocks:
                    block_idx = min(mode_timer // 10, len(blocks) - 1)
                    v_lines = blocks[block_idx]
                    right_col.append("═══════ПРОГРАММА ПЕРЕДАЧ══════╗".rjust(45))
                    right_col.append((" " * 30 + "║").rjust(45))
                    right_col.append((v_lines[0].strip().center(30) + "║").rjust(45))
                    right_col.append((" " * 30 + "║").rjust(45))
                    for sl in v_lines[1:]:
                        right_col.append((f"  {sl.strip()[:27]}".ljust(30) + "║").rjust(45))
                    while len(right_col) < 17: right_col.append((" " * 30 + "║").rjust(45))
                    right_col.append("═════════════════════════════════╝".rjust(45))
            elif RIGHT_PANEL_MODE == "MOVIE":
                # Отрисовка карточки фильма с постраничной прокруткой описания
                m_data = STATE.get("movie_data")
                if m_data:
                    lines_for_desc = max(1, 16 - len(m_data["fixed_header"]))
                    total_pages = max(1, (len(m_data["description"]) + lines_for_desc - 1) // lines_for_desc)
                    curr_pg = (mode_timer // 10) % total_pages
                    desc_pg = m_data["description"][curr_pg * lines_for_desc : (curr_pg + 1) * lines_for_desc]
                    
                    right_col.append(m_data["header_ui"].rjust(45))
                    for row in m_data["fixed_header"] + desc_pg:
                        safe = row.replace('\\', '\\\\').replace('%', '%%')
                        extra = safe.count('\\') // 2
                        right_col.append((safe.ljust(34 + extra) + "║").rjust(45 + extra))
                    while len(right_col) < 17: right_col.append((" " * 34 + "║").rjust(45))
                    right_col.append("══════════════════════════════╝".rjust(45))

            # Компоновка всех элементов на финальный холст
            total_lines = max(len(left_col), 32)
            canvas = create_background(total_lines, term_width)
            canvas = overlay_block(canvas, right_col, start_row=5, start_col=81)
            canvas = overlay_block(canvas, left_col, start_row=0, start_col=0)
            
            # Добавление ASCII-часов с учетом оффсета (задержки трансляции)
            now_off = datetime.now() + timedelta(seconds=conf.GUI_STATUS.clock_offset_sec)
            if now_off.minute != last_clock_min:
                cached_clock_lines = clock.get_clock_lines(now_off)
                last_clock_min = now_off.minute
            canvas = overlay_block(canvas, cached_clock_lines, start_row=29, start_col=35)
            
            # Финализация: запись в буфер и опциональный вывод в консоль
            final_frame = "\n".join(canvas)
            await asyncio.to_thread(sync_write_logfile, final_frame)

            if SHOW_CONSOLE:
                print(CLEAR + final_frame, flush=True)

            mode_timer += refresh_rate
            tick_counter += 1
            await asyncio.sleep(refresh_rate)

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

async def main():
    """Точка входа. Инициализирует асинхронную сессию и запускает все модули."""
    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(task_runner("res", res.get_status_lines, "res")),
            asyncio.create_task(task_runner("uvb", uvb.get_uvb_lines, "uvb")),
            asyncio.create_task(task_runner("finance", finance.get_finance_lines, "finance", session)),
            asyncio.create_task(task_runner("weather", weather.get_weather_lines, "weather", session)),
            asyncio.create_task(task_runner("rss", rss.get_rss_lines, "rss", session)),
            asyncio.create_task(task_runner("diag", diag.get_diag_lines, "diag")),
            asyncio.create_task(task_lineup()),
            asyncio.create_task(task_movie()),
            asyncio.create_task(diag.run_vmstat()),
            asyncio.create_task(diag.run_mtr()),
            asyncio.create_task(renderer()),
            asyncio.create_task(messenger.start_bot())
        ]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановка рендерера...")
