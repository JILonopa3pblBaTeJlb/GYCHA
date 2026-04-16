# status.py — Главный графический движок (рендерер) интерфейса трансляции
import asyncio
import os
import shutil
import time
import sys
import select
import termios
import tty
from datetime import datetime, timedelta

# Оптимизация для Linux/Unix
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

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

# Состояние системы
STATE = {
    "res": ["Загрузка ресурсов..."],
    "finance": ["Загрузка курсов..."],
    "weather": ["Загрузка погоды..."],
    "rss": ["Загрузка новостей..."],
    "lineup": ["Загрузка расписания..."],
    "long_schedule": [],
    "uvb": ["Ожидание UVB..."],
    "diag": ["Ожидание DIAG..."],
    "movie_data": None
}

SHOW_CONSOLE = False

def load_vhs_params():
    try:
        vhs_hour = conf.AIR_CONTROL.vhs_hour
        vhs_days = conf.AIR_CONTROL.vhs_days
        if isinstance(vhs_days, int):
            vhs_days = [vhs_days]
        return vhs_hour, vhs_days
    except Exception:
        return 18, [4, 5, 6]

async def task_movie():
    movie_file = conf.PATHS.movie_info_file
    while True:
        try:
            v_h, v_d = load_vhs_params()
            now = datetime.now()
            if now.weekday() in v_d and os.path.exists(movie_file):
                offset = conf.CONTENT_MANAGER.vhs_preload_offset_min
                trigger_dt = now.replace(hour=v_h, minute=0, second=0, microsecond=0) - timedelta(minutes=offset)
                mtime_dt = datetime.fromtimestamp(os.path.getmtime(movie_file))
                header = "══════СЕГОДНЯ ПОКАЖЕМ═══════╗" if mtime_dt > trigger_dt else "══════РАНЕЕ ПОКАЗЫВАЛИ══════╗"
                
                def read_split():
                    with open(movie_file, "r", encoding="utf-8") as f:
                        lines = [l.rstrip() for l in f]
                    idx = -1
                    for i, l in enumerate(lines):
                        if i > 4 and not l.strip():
                            idx = i
                            break
                    return (lines[:idx+1], lines[idx+1:]) if idx != -1 else (lines, [])

                f_h, d_l = await asyncio.to_thread(read_split)
                STATE["movie_data"] = {"header_ui": header, "fixed_header": f_h, "description": d_l}
            else:
                STATE["movie_data"] = None
        except Exception:
            STATE["movie_data"] = None
        await asyncio.sleep(60)

def get_terminal_width():
    try:
        return max(shutil.get_terminal_size().columns, 132)
    except:
        return 132

def create_background(lines_count, width):
    return [' ' * width for _ in range(lines_count)]

def overlay_block(background, content_lines, start_row, start_col):
    if not content_lines: return background
    max_rows = len(background)
    for i, line in enumerate(content_lines):
        row_idx = start_row + i
        if row_idx >= max_rows: break
        bg_line = background[row_idx]
        text = str(line).rstrip()
        visible = text[:len(bg_line)-start_col] if start_col+len(text) > len(bg_line) else text
        background[row_idx] = bg_line[:start_col] + visible + bg_line[start_col+len(visible):]
    return background

async def task_runner(key, func, interval_key, session=None):
    while True:
        interval = getattr(conf.GUI_STATUS, f"interval_{key}_sec", 60)
        try:
            data = await func(session) if session else await asyncio.to_thread(func)
            if data and isinstance(data, list):
                STATE[key] = data
        except Exception as e:
            print(f"\rОшибка модуля {key}: {e}")
        await asyncio.sleep(interval)

async def task_lineup():
    while True:
        try:
            STATE["lineup"] = await asyncio.to_thread(lineup.get_lineup_lines)
            STATE["long_schedule"] = await asyncio.to_thread(lineup.get_long_schedule)
        except: pass
        now = datetime.now()
        next_h = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_h - now).total_seconds() + 1)

def check_input():
    """Проверка ввода с мгновенным откликом в консоль."""
    global SHOW_CONSOLE
    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        key = sys.stdin.read(1)
        if key.lower() == 'v':
            SHOW_CONSOLE = not SHOW_CONSOLE
            if not SHOW_CONSOLE:
                # Очистка консоли при выключении
                print('\033[2J\033[H' + "Мониторинг консоли: ВЫКЛЮЧЕН. Нажмите 'V' для включения.")
            return True
    return False

def sync_write_logfile(content):
    try:
        log_file = conf.GLOBAL.log_buffer_file
        tmp_file = log_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_file, log_file)
    except:
        pass

async def renderer():
    """
    ГЛАВНЫЙ ЦИКЛ ОТРИСОВКИ.
    Исправлено: теперь мессенджер добавляется без символа \n, 
    чтобы не нарушать вертикальное позиционирование ASCII-часов.
    """
    global SHOW_CONSOLE
    CLEAR = '\033[2J\033[H'
    w_scroll, r_scroll = 0, 0
    mode, timer, ticks = "DIAG", 0, 0
    last_min, cached_clock = -1, []
    
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    
    print("Рендерер запущен. Нажмите 'V' для просмотра кадров.")
    
    try:
        tty.setcbreak(fd)
        while True:
            conf.reload()
            check_input()
            
            ref_rate = conf.GUI_STATUS.refresh_rate_sec
            
            if ticks % 10 == 0:
                if STATE["weather"]: w_scroll = (w_scroll + 1) % len(STATE["weather"])
                if STATE["rss"]: r_scroll = (r_scroll + 1) % len(STATE["rss"])

            # Логика переключения правой панели
            v_h, v_d = load_vhs_params()
            if mode == "DIAG" and timer >= 10: mode = "UVB_1"; timer = 0
            elif mode == "UVB_1" and timer >= 10:
                mode = "MOVIE" if (datetime.now().weekday() in v_d and STATE["movie_data"]) else "UVB_2"
                timer = 0
            elif mode == "MOVIE":
                m = STATE["movie_data"]
                if not m: mode = "UVB_2"; timer = 0
                else:
                    l_desc = max(1, 16 - len(m["fixed_header"]))
                    pages = (len(m["description"]) + l_desc - 1) // l_desc
                    if timer >= max(1, pages) * 10: mode = "UVB_2"; timer = 0
            elif mode == "UVB_2" and timer >= 10: mode = "SCHEDULE"; timer = 0
            elif mode == "SCHEDULE":
                if not STATE["long_schedule"] or (timer // 10) >= len(STATE["long_schedule"]):
                    mode = "UVB_3"; timer = 0
            elif mode == "UVB_3" and timer >= 10: mode = "DIAG"; timer = 0

            # Сборка кадра
            width = get_terminal_width()
            left = [""] * 5
            for k in ["res", "finance"]:
                if STATE.get(k): left.extend(STATE[k])
            
            if STATE["weather"]:
                for i in range(conf.GUI_STATUS.weather_window_size):
                    left.append(STATE["weather"][(w_scroll + i) % len(STATE["weather"])])
            
            left.append("") # Разделитель перед расписанием
            if STATE["lineup"]: left.extend(STATE["lineup"])
            
            # ИСПРАВЛЕННЫЙ БЛОК: Messenger и RSS
            # Добавляем строго по одной строке в элемент списка
            left.append("") # Пустая строка-разделитель (вместо \n)
            
            # Проверяем мессенджер. Если модуля нет или он пуст, ставим заглушку
            messenger_line = messenger.get_broadcast_line() if hasattr(messenger, 'get_broadcast_line') else None
            left.append(messenger_line or "—")
            
            if STATE["rss"]:
                left.append(STATE["rss"][r_scroll % len(STATE["rss"])])

            # Правая панель (без изменений)
            right = []
            if "UVB" in mode: right = list(STATE["uvb"])
            elif mode == "DIAG": right = list(STATE["diag"])
            elif mode == "SCHEDULE":
                blocks = STATE["long_schedule"]
                if blocks:
                    b_idx = min(timer // 10, len(blocks) - 1)
                    v_l = blocks[b_idx]
                    right = ["═══════ПРОГРАММА ПЕРЕДАЧ══════╗".rjust(45), (" " * 30 + "║").rjust(45),
                             (v_l[0].strip().center(30) + "║").rjust(45), (" " * 30 + "║").rjust(45)]
                    for sl in v_l[1:]: right.append((f"  {sl.strip()[:27]}".ljust(30) + "║").rjust(45))
                    while len(right) < 17: right.append((" " * 30 + "║").rjust(45))
                    right.append("═════════════════════════════════╝".rjust(45))
            elif mode == "MOVIE":
                m = STATE["movie_data"]
                if m:
                    l_desc = max(1, 16 - len(m["fixed_header"]))
                    pages = max(1, (len(m["description"]) + l_desc - 1) // l_desc)
                    pg = (timer // 10) % pages
                    desc = m["description"][pg*l_desc : (pg+1)*l_desc]
                    right.append(m["header_ui"].rjust(45))
                    for rt in m["fixed_header"] + desc:
                        st = rt.replace('\\', '\\\\').replace('%', '%%')
                        ex = st.count('\\') // 2
                        right.append((st.ljust(34 + ex) + "║").rjust(45 + ex))
                    while len(right) < 17: right.append((" " * 34 + "║").rjust(45))
                    right.append("══════════════════════════════╝".rjust(45))

            # Создание фона и оверлей
            # Важно: оверлей накладывается поверх background, поэтому
            # если left слишком длинный, часы его просто перекроют (что нам и нужно)
            canvas = create_background(max(len(left), 35), width)
            canvas = overlay_block(canvas, right, 5, 81)
            canvas = overlay_block(canvas, left, 0, 0)
            
            # Накладываем часы на фиксированные строки 29, 30, 31
            now_c = datetime.now() + timedelta(seconds=conf.GUI_STATUS.clock_offset_sec)
            if now_c.minute != last_min:
                cached_clock = clock.get_clock_lines(now_c)
                last_min = now_c.minute
            canvas = overlay_block(canvas, cached_clock, 29, 35)
            
            frame = "\n".join(canvas)
            await asyncio.to_thread(sync_write_logfile, frame)

            if SHOW_CONSOLE:
                print(CLEAR + frame, flush=True)
            else:
                sys.stdout.write(f"\r[РЕНДЕРЕР РАБОТАЕТ] Тик: {ticks} | Панель: {mode} | Файл: {conf.GLOBAL.log_buffer_file}   ")
                sys.stdout.flush()

            timer += ref_rate
            ticks += 1
            await asyncio.sleep(ref_rate)
    except Exception as e:
        print(f"\rКритическая ошибка рендерера: {e}")
        time.sleep(2)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

async def main():
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
        print("\nОстановка...")
