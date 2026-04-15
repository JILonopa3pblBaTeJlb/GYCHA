import curses
import json
import asyncio
import aiohttp
import os
import textwrap
import locale
import g4f
import csv
from pathlib import Path

locale.setlocale(locale.LC_ALL, '')

# API Ключи (Заменены на мокапы для GitHub)
TMDB_API_KEY = "YOUR_TMDB_API_KEY_HERE"
OMDB_API_KEY = "YOUR_OMDB_API_KEY_HERE"
DB_FILE = "vhs_metadata.json"
CSV_EXPORT_FILE = "vhs_export.csv"
TRANSLATE_PROMPT_FILE = "translate_prompt.txt"

# Настройка задержки Esc для мгновенной реакции
os.environ.setdefault('ESCDELAY', '25')

class VHSManager:
    def __init__(self):
        self.movies = self.load_db()
        self.current_idx = 0
        self.offset = 0
        self.running = True
        self.status_msg = f"Загружено: {len(self.movies)} фильмов. [S]-Поиск [Enter]-Правка"

    def load_db(self):
        if Path(DB_FILE).exists():
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            except: return []
        return []

    def save_db(self):
        # Сортировка по ID поста (убывание)
        try:
            self.movies.sort(key=lambda x: int(x.get('post_id', 0)), reverse=True)
        except: pass
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(self.movies, f, indent=2, ensure_ascii=False)

    def get_next_id(self):
        """Находит следующий свободный ID"""
        if not self.movies:
            return 1
        try:
            ids = [int(m.get('post_id', 0)) for m in self.movies]
            return max(ids) + 1
        except:
            return len(self.movies) + 1

    def export_to_csv(self):
        """Экспорт базы в CSV формат"""
        if not self.movies:
            self.status_msg = "Ошибка: база пуста для экспорта"
            return
        try:
            keys = ["post_id", "title_ru", "title_en", "year", "director", "runtime", "imdb_id", "tagline", "overview"]
            with open(CSV_EXPORT_FILE, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(self.movies)
            self.status_msg = f"Экспортировано в {CSV_EXPORT_FILE}"
        except Exception as e:
            self.status_msg = f"Ошибка экспорта: {str(e)[:30]}"

    async def translate_field(self, stdscr, text):
        """Перевод текста через g4f (Opera Aria) с выводом лога процесса"""
        if not text:
            return text
            
        h, w = stdscr.getmaxyx()
        # Создаем окно для лога (высота 10, ширина 60, центрировано)
        log_h, log_w = 10, 60
        log_win = curses.newwin(log_h, log_w, (h - log_h) // 2, (w - log_w) // 2)
        log_win.attron(curses.color_pair(2))
        log_win.box()
        log_win.attroff(curses.color_pair(2))
        log_win.addstr(0, 2, " GPT TRANSLATION LOG ", curses.color_pair(2) | curses.A_BOLD)
        
        lines = []

        def add_log(msg):
            lines.append(f"[*] {msg}")
            if len(lines) > log_h - 4:
                lines.pop(0)
            for i, line in enumerate(lines):
                try:
                    log_win.addstr(i + 1, 2, line[:log_w-4])
                except: pass
            log_win.refresh()

        add_log("Проверка файла промпта...")
        if not os.path.exists(TRANSLATE_PROMPT_FILE):
            add_log(f"Ошибка: {TRANSLATE_PROMPT_FILE} не найден")
            log_win.refresh()
            await asyncio.sleep(1)
            return text

        try:
            with open(TRANSLATE_PROMPT_FILE, "r", encoding="utf-8") as f:
                system_prompt = f.read().strip()
            
            add_log("Подготовка запроса к Opera Aria...")
            messages = [{"role": "user", "content": f"{system_prompt}\n\n{text}"}]
            
            add_log("Установка соединения с провайдером...")
            await asyncio.sleep(0.2)
            
            response = await g4f.ChatCompletion.create_async(
                model="aria",
                provider=g4f.Provider.OperaAria,
                messages=messages,
            )
            
            if response:
                add_log("Ответ успешно получен.")
                add_log("Обработка результата...")
                await asyncio.sleep(0.5)
                return response.strip()
            else:
                add_log("Провайдер вернул пустой ответ.")
                await asyncio.sleep(1)
                return text

        except Exception as e:
            add_log(f"Критическая ошибка: {str(e)[:40]}")
            log_win.refresh()
            await asyncio.sleep(1.5)
            return text
        finally:
            add_log("Закрытие сессии перевода...")
            await asyncio.sleep(0.3)

    async def fetch_tmdb_search(self, session, query):
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"api_key": TMDB_API_KEY, "query": query, "language": "ru-RU"}
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("results", [])
        except: return []
        return []

    async def fetch_full_details(self, session, tmdb_id):
        det_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
        params = {"api_key": TMDB_API_KEY, "language": "ru-RU", "append_to_response": "credits"}
        try:
            async with session.get(det_url, params=params) as resp:
                m_ru = await resp.json()
            imdb_id = m_ru.get("imdb_id")
            omdb_data = {}
            if imdb_id:
                o_params = {"i": imdb_id, "apikey": OMDB_API_KEY}
                async with session.get("http://www.omdbapi.com/", params=o_params) as resp:
                    if resp.status == 200:
                        omdb_data = await resp.json()
            
            director = "Неизвестен"
            crew = m_ru.get("credits", {}).get("crew", [])
            directors = [m["name"] for m in crew if m.get("job") == "Director"]
            if directors:
                director = ", ".join(directors)
            elif omdb_data.get("Director") and omdb_data.get("Director") != "N/A":
                director = omdb_data["Director"]

            return {
                "post_id": 0,
                "imdb_id": imdb_id,
                "title_ru": m_ru.get("title"),
                "title_en": m_ru.get("original_title"),
                "year": int(m_ru.get("release_date", "0000")[:4]) if m_ru.get("release_date") else 0,
                "director": director,
                "runtime": omdb_data.get("Runtime", f"{m_ru.get('runtime')} min"),
                "tagline": m_ru.get("tagline", ""),
                "overview": m_ru.get("overview") or "Нет описания",
                "genres": [g["name"] for g in m_ru.get("genres", [])],
                "cast": [c["name"] for i, c in enumerate(m_ru.get("credits", {}).get("cast", [])) if i < 8],
                "ratings": {
                    "imdb": omdb_data.get("imdbRating", "N/A"),
                    "rt": next((r["Value"] for r in omdb_data.get("Ratings", []) if r["Source"] == "Rotten Tomatoes"), "N/A")
                }
            }
        except: return None

    def draw_main(self, stdscr):
        """
        Отрисовывает основной интерфейс.
        Оптимизировано: рисуем напрямую в stdscr без создания промежуточных окон в цикле.
        """
        h, w = stdscr.getmaxyx()
        
        if h < 10 or w < 40:
            stdscr.erase()
            stdscr.addstr(0, 0, "Экран слишком мал!")
            stdscr.refresh()
            return

        color_normal = curses.color_pair(1)
        color_accent = curses.color_pair(2)
        color_cursor = curses.color_pair(3)

        stdscr.erase()
        stdscr.bkgd(' ', color_normal)
        
        # Рисуем рамку и заголовок
        try:
            stdscr.attron(color_accent)
            stdscr.border()
            stdscr.addstr(0, 2, " VHS DATABASE MANAGER ", color_accent | curses.A_BOLD)
            stdscr.attroff(color_accent)
        except curses.error: pass

        # Левая часть: Список фильмов
        list_w = w // 2 - 2
        list_h = h - 4
        if list_w > 5 and list_h > 2:
            for i in range(list_h):
                idx = i + self.offset
                if idx >= len(self.movies): break
                
                attr = color_cursor if idx == self.current_idx else color_normal
                m = self.movies[idx]
                p_id = str(m.get('post_id', '?')).rjust(4)
                title = (m.get('title_ru') or m.get('title', 'Unknown'))[:list_w - 12]
                line = f" {p_id} │ {title} ({m.get('year','?')})"
                
                try:
                    stdscr.addstr(i + 2, 2, line.ljust(list_w), attr)
                except curses.error: pass

        # Правая часть: Детальная информация
        info_w = w // 2 - 2
        info_x = w // 2 + 1
        if info_w > 5:
            if self.movies and self.current_idx < len(self.movies):
                m = self.movies[self.current_idx]
                try:
                    stdscr.addstr(2, info_x, f"{m.get('title_ru')}"[:info_w], color_accent | curses.A_BOLD)
                    stdscr.addstr(3, info_x, f"Original: {m.get('title_en')}"[:info_w], curses.A_DIM)
                    stdscr.addstr(4, info_x, f"Director: {m.get('director', 'Unknown')}"[:info_w], color_accent)
                    stdscr.addstr(5, info_x, f"Year: {m.get('year')}   Runtime: {m.get('runtime')}"[:info_w])
                    
                    r = m.get('ratings', {})
                    stdscr.addstr(7, info_x, f"IMDb: ", color_normal)
                    stdscr.addstr(7, info_x + 6, f"{r.get('imdb','N/A')}", color_accent | curses.A_BOLD)
                    stdscr.addstr(7, info_x + 14, f"RT: {r.get('rt','N/A')}")
                    
                    ov = m.get("overview", "")
                    wrapper = textwrap.TextWrapper(width=info_w - 2)
                    wrapped_ov = wrapper.wrap(ov)
                    for i, row in enumerate(wrapped_ov[:h - 15]):
                        stdscr.addstr(9 + i, info_x, row)
                    
                    cast = ", ".join(m.get("cast", []))
                    if h > 15:
                        stdscr.addstr(h - 4, info_x, "Cast:", color_accent)
                        stdscr.addstr(h - 3, info_x, f"{cast[:info_w-2]}", curses.A_DIM)
                except curses.error: pass

        # Нижние строки (Статус и Меню)
        try:
            status_text = f" STATUS: {self.status_msg} "
            stdscr.addstr(h - 2, 2, status_text[:w-4], color_accent)
            menu_str = " [S]Поиск [A]Добавить [E]CSV [Enter]Правка [Del]Удалить [Q]Выход "
            stdscr.addstr(h - 1, 2, menu_str[:w-4], color_cursor)
        except curses.error: pass
        
        stdscr.refresh()

    async def edit_form(self, stdscr, session, movie_data=None):
        h, w = stdscr.getmaxyx()
        f_win = curses.newwin(h-2, w-4, 1, 2)
        f_win.keypad(True)
        
        is_new = movie_data is None
        if movie_data:
            m = movie_data.copy()
            m['cast_str'] = ", ".join(m.get('cast', []))
            m['imdb_rat'] = m.get('ratings', {}).get('imdb', 'N/A')
            m['rt_rat'] = m.get('ratings', {}).get('rt', 'N/A')
        else:
            m = {
                "post_id": self.get_next_id(), "title_ru": "", "title_en": "", "director": "",
                "year": 0, "runtime": "", "imdb_id": "", "overview": "",
                "cast_str": "", "imdb_rat": "N/A", "rt_rat": "N/A"
            }

        fields = [
            ("Post ID", "post_id"), ("Название RU", "title_ru"), ("Название EN", "title_en"),
            ("Режиссер", "director"), ("Год", "year"), ("Runtime", "runtime"),
            ("IMDB ID", "imdb_id"), ("В ролях", "cast_str"), ("Рейтинг IMDb", "imdb_rat"),
            ("Рейтинг RT", "rt_rat"), ("Описание", "overview")
        ]
        
        cur_f = 0
        ov_scroll = 0
        
        while True:
            f_win.erase()
            f_win.box()
            f_win.addstr(0, 2, " РЕДАКТИРОВАНИЕ КАРТОЧКИ ", curses.color_pair(2))
            f_win.addstr(h-4, 2, " [F3]-TMDB [F4]-Перевод Aria [F10]-Сохранить [Esc]-Отмена ", curses.color_pair(3))

            y = 1
            for i, (label, key) in enumerate(fields):
                attr = curses.color_pair(3) if i == cur_f else curses.A_NORMAL
                val = str(m.get(key, ""))
                
                if key == "overview":
                    f_win.addstr(y, 2, f"{label}:", attr)
                    ov_y_start = y + 1
                    ov_max_h = (h - 2) - ov_y_start - 4
                    wrapper = textwrap.TextWrapper(width=w-10)
                    wrapped_lines = wrapper.wrap(val)
                    
                    for j, line in enumerate(wrapped_lines[ov_scroll : ov_scroll + ov_max_h]):
                        try: f_win.addstr(ov_y_start + j, 4, line, attr)
                        except: break
                    
                    if len(wrapped_lines) > ov_max_h:
                        f_win.addstr(ov_y_start + ov_max_h, 4, f"... (Стр {ov_scroll//ov_max_h + 1}) ...", curses.A_DIM)
                else:
                    try:
                        f_win.addstr(y, 2, f"{label.ljust(12)}: {val[:w-30]}", attr)
                    except: pass
                    y += 1 if h < 35 else 2

            f_win.refresh()
            k = f_win.getch()

            if k == 27: return None
            elif k == curses.KEY_F10:
                new_imdb = str(m.get('imdb_id', '')).strip()
                if new_imdb:
                    duplicate = None
                    for existing_movie in self.movies:
                        if not is_new and str(existing_movie.get('post_id')) == str(m.get('post_id')):
                            continue
                        if existing_movie.get('imdb_id') == new_imdb:
                            duplicate = existing_movie
                            break
                    
                    if duplicate:
                        warn_win = curses.newwin(7, 60, h//2-3, w//2-30)
                        warn_win.box()
                        warn_win.attron(curses.color_pair(2))
                        warn_win.addstr(1, 2, "ВНИМАНИЕ: IMDB ID уже есть в базе!", curses.A_BOLD)
                        warn_win.attroff(curses.color_pair(2))
                        warn_win.addstr(2, 2, f"Фильм: {duplicate.get('title_ru')[:50]}")
                        warn_win.addstr(4, 2, "[Y] - Все равно продолжить", curses.A_BOLD)
                        warn_win.refresh()
                        
                        curses.echo()
                        k_warn = warn_win.getch()
                        curses.noecho()
                        
                        if k_warn not in [ord('y'), ord('Y'), ord('н'), ord('Н')]:
                            continue

                m['cast'] = [x.strip() for x in m['cast_str'].split(',') if x.strip()]
                m['ratings'] = {"imdb": m['imdb_rat'], "rt": m['rt_rat']}
                return m
            elif k == curses.KEY_UP:
                if cur_f == 10 and ov_scroll > 0:
                    ov_scroll -= 1
                else:
                    cur_f = (cur_f - 1) % len(fields)
                    ov_scroll = 0
            elif k == curses.KEY_DOWN:
                if cur_f == 10:
                    ov_y_start = 1 + (10 * (1 if h < 35 else 2)) + 1
                    ov_max_h = (h - 2) - ov_y_start - 4
                    if ov_scroll + ov_max_h < len(textwrap.TextWrapper(width=w-10).wrap(m['overview'])):
                        ov_scroll += 1
                    else:
                        cur_f = (cur_f + 1) % len(fields)
                else:
                    cur_f = (cur_f + 1) % len(fields)
                    ov_scroll = 0
            elif k == curses.KEY_F3:
                q = self.get_input(stdscr, "Поиск в API: ", m['title_ru'])
                if q:
                    res = await self.fetch_tmdb_search(session, q)
                    if res:
                        sel = await self.select_api_result(stdscr, res)
                        if sel:
                            full = await self.fetch_full_details(session, sel['id'])
                            if full:
                                saved_pid = m['post_id']
                                m.update(full)
                                m['post_id'] = saved_pid
                                m['cast_str'] = ", ".join(full.get('cast', []))
                                m['imdb_rat'] = full['ratings']['imdb']
                                m['rt_rat'] = full['ratings']['rt']
            elif k == curses.KEY_F4:
                label, kn = fields[cur_f]
                translated = await self.translate_field(stdscr, m[kn])
                m[kn] = translated
            elif k == 10:
                label, kn = fields[cur_f]
                new_v = self.get_input(stdscr, f"{label}: ", str(m[kn]))
                if kn in ['post_id', 'year']:
                    m[kn] = int(new_v) if new_v.isdigit() else 0
                else:
                    m[kn] = new_v
                    
    async def select_search_result(self, stdscr, results_indices):
        h, w = stdscr.getmaxyx()
        win_h = min(len(results_indices) + 4, h - 4)
        sel_win = curses.newwin(win_h, w - 10, (h - win_h)//2, 5)
        sel_win.keypad(True)
        sel_win.attron(curses.color_pair(2))
        sel_win.box()
        sel_win.attroff(curses.color_pair(2))
        cur = 0
        while True:
            sel_win.addstr(1, 2, f"Найдено совпадений: {len(results_indices)} (Enter-Выбор, Esc-Отмена):", curses.A_BOLD)
            for i, idx in enumerate(results_indices[:win_h-4]):
                attr = curses.A_REVERSE if i == cur else curses.A_NORMAL
                m = self.movies[idx]
                line = f"{str(m.get('post_id')).rjust(4)} | {m.get('title_ru')} ({m.get('year')})"
                try: sel_win.addstr(i+2, 2, line.ljust(w-14), attr)
                except: pass
            sel_win.refresh()
            k = sel_win.getch()
            if k == curses.KEY_UP: cur = (cur - 1) % len(results_indices)
            elif k == curses.KEY_DOWN: cur = (cur + 1) % len(results_indices)
            elif k == 10: return results_indices[cur]
            elif k == 27: return None

    async def select_api_result(self, stdscr, results):
        h, w = stdscr.getmaxyx()
        win_h = min(len(results) + 4, h - 4)
        sel_win = curses.newwin(win_h, w - 10, (h - win_h)//2, 5)
        sel_win.keypad(True)
        sel_win.attron(curses.color_pair(2))
        sel_win.box()
        sel_win.attroff(curses.color_pair(2))
        cur = 0
        while True:
            sel_win.addstr(1, 2, "Выберите фильм (Enter-OK, Esc-Отмена):", curses.A_BOLD)
            for i, r in enumerate(results[:win_h-4]):
                attr = curses.A_REVERSE if i == cur else curses.A_NORMAL
                line = f"{r.get('title')} ({r.get('release_date','?')[:4]})"
                try: sel_win.addstr(i+2, 2, line.ljust(w-14), attr)
                except: pass
            sel_win.refresh()
            k = sel_win.getch()
            if k == curses.KEY_UP: cur = (cur - 1) % len(results)
            elif k == curses.KEY_DOWN: cur = (cur + 1) % len(results)
            elif k == 10: return results[cur]
            elif k == 27: return None

    def get_input(self, stdscr, prompt, existing=""):
        h, w = stdscr.getmaxyx()
        in_win = curses.newwin(3, w-10, h//2-1, 5)
        in_win.keypad(True)
        in_win.attron(curses.color_pair(3))
        in_win.erase()
        in_win.box()
        curses.curs_set(1)
        buffer = list(str(existing))
        
        while True:
            in_win.erase()
            in_win.box()
            txt = "".join(buffer)
            display_txt = txt[-(w-25):]
            try:
                in_win.addstr(1, 1, f"{prompt}{display_txt}")
            except: pass
            
            in_win.refresh()
            
            try:
                ch = in_win.get_wch()
            except:
                continue

            if ch == '\n' or ch == '\r' or ch == curses.KEY_ENTER:
                break
            elif ch == '\x1b':
                buffer = list(str(existing))
                break
            elif ch == '\x7f' or ch == '\x08' or ch == curses.KEY_BACKSPACE:
                if buffer:
                    buffer.pop()
            elif isinstance(ch, str):
                if ord(ch) >= 32:
                    buffer.append(ch)
            elif ch == curses.KEY_DC:
                if buffer:
                    buffer.pop()
                    
        curses.curs_set(0)
        return "".join(buffer).strip()

    async def main_loop(self, stdscr):
        """Главный цикл управления."""
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
        
        stdscr.keypad(True)
        # Отключаем nodelay, чтобы get_wch() блокировал цикл до нажатия клавиши
        # Это мгновенно решает проблему мигания и потребления CPU.
        stdscr.nodelay(False)
        curses.curs_set(0)
        
        async with aiohttp.ClientSession() as session:
            need_redraw = True
            while self.running:
                if need_redraw:
                    self.draw_main(stdscr)
                    need_redraw = False
                
                try:
                    # В режиме nodelay(False) это блокирующий вызов
                    key = stdscr.get_wch()
                except KeyboardInterrupt:
                    break
                except:
                    continue

                if key in ['q', 'Q', 'й', 'Й']:
                    self.running = False
                elif key == curses.KEY_UP:
                    if self.movies:
                        self.current_idx = (self.current_idx - 1) % len(self.movies)
                        if self.current_idx == len(self.movies) - 1:
                            self.offset = max(0, len(self.movies) - (curses.LINES - 6))
                        elif self.current_idx < self.offset:
                            self.offset = self.current_idx
                    need_redraw = True
                elif key == curses.KEY_DOWN:
                    if self.movies:
                        self.current_idx = (self.current_idx + 1) % len(self.movies)
                        if self.current_idx == 0:
                            self.offset = 0
                        elif self.current_idx >= self.offset + curses.LINES - 6:
                            self.offset += 1
                    need_redraw = True
                elif key in ['s', 'S', 'ы', 'Ы']:
                    q = self.get_input(stdscr, "Поиск по всем полям: ")
                    if q:
                        q = q.lower()
                        results_indices = []
                        for i, m in enumerate(self.movies):
                            content = " ".join(str(v) for v in m.values()).lower()
                            if q in content:
                                results_indices.append(i)
                        
                        if results_indices:
                            if len(results_indices) > 1:
                                selected_idx = await self.select_search_result(stdscr, results_indices)
                                if selected_idx is not None:
                                    self.current_idx = selected_idx
                                    self.offset = max(0, selected_idx - (curses.LINES // 4))
                            else:
                                self.current_idx = results_indices[0]
                                self.offset = max(0, self.current_idx - (curses.LINES // 4))
                        else:
                            self.status_msg = f"Ничего не найдено для: {q[:15]}"
                    need_redraw = True
                elif key in ['e', 'E', 'у', 'У']:
                    self.export_to_csv()
                    need_redraw = True
                elif key == '\n' or key == '\r':
                    if self.movies:
                        res = await self.edit_form(stdscr, session, self.movies[self.current_idx])
                        if res:
                            self.movies[self.current_idx] = res
                            self.save_db()
                    need_redraw = True
                elif key in ['a', 'A', 'ф', 'Ф']:
                    res = await self.edit_form(stdscr, session, None)
                    if res:
                        self.movies.append(res)
                        self.save_db()
                        for i, m in enumerate(self.movies):
                            if m.get('post_id') == res.get('post_id'):
                                self.current_idx = i
                                break
                    need_redraw = True
                elif key == curses.KEY_DC:
                    if self.movies:
                        self.movies.pop(self.current_idx)
                        if self.movies:
                            self.current_idx = self.current_idx % len(self.movies)
                        else:
                            self.current_idx = 0
                        self.save_db()
                    need_redraw = True


def run_manager():
    manager = VHSManager()
    
    def start(stdscr):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(manager.main_loop(stdscr))
        finally:
            loop.close()

    try:
        curses.wrapper(start)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    run_manager()
