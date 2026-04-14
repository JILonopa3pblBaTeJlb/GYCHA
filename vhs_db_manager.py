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

# Установка локали для корректного отображения Unicode (кириллицы) в терминале
locale.setlocale(locale.LC_ALL, '')

# --- КОНФИГУРАЦИЯ И МОК-ДАННЫЕ ---
# Замените эти значения на ваши реальные ключи перед использованием
TMDB_API_KEY = "YOUR_TMDB_API_KEY_HERE"
OMDB_API_KEY = "YOUR_OMDB_API_KEY_HERE"

DB_FILE = "vhs_metadata.json"
CSV_EXPORT_FILE = "vhs_export.csv"
TRANSLATE_PROMPT_FILE = "translate_prompt.txt"

# Настройка задержки Esc для мгновенной реакции (по умолчанию в curses Esc тормозит на 1 сек)
os.environ.setdefault('ESCDELAY', '25')

class VHSManager:
    """
    Класс для управления базой данных VHS-кассет. 
    Реализует TUI (Terminal User Interface), интеграцию с API кинобаз и GPT перевод.
    """
    def __init__(self):
        self.movies = self.load_db()
        self.current_idx = 0  # Текущий выбранный фильм в списке
        self.offset = 0       # Смещение для прокрутки списка
        self.running = True
        self.status_msg = f"Загружено: {len(self.movies)} фильмов. [S]-Поиск [Enter]-Правка"

    def load_db(self):
        """Загружает данные из JSON файла. Если файл поврежден или отсутствует, возвращает пустой список."""
        if Path(DB_FILE).exists():
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def save_db(self):
        """
        Сохраняет базу в JSON. Перед сохранением сортирует записи по ID поста в обратном порядке,
        чтобы новые/последние добавленные записи были сверху.
        """
        try:
            # Сортировка по числовому значению post_id
            self.movies.sort(key=lambda x: int(x.get('post_id', 0)), reverse=True)
        except (ValueError, KeyError):
            pass
            
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(self.movies, f, indent=2, ensure_ascii=False)

    def get_next_id(self):
        """Генерирует следующий порядковый ID для новой записи, основываясь на максимальном существующем."""
        if not self.movies:
            return 1
        try:
            ids = [int(m.get('post_id', 0)) for m in self.movies]
            return max(ids) + 1
        except ValueError:
            return len(self.movies) + 1

    def export_to_csv(self):
        """Экспортирует основные поля базы в CSV формат для работы в табличных редакторах."""
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
        """
        Выполняет перевод текста с помощью библиотеки g4f (провайдер Opera Aria).
        Во время работы рисует всплывающее окно лога, чтобы пользователь видел прогресс.
        """
        if not text:
            return text
            
        h, w = stdscr.getmaxyx()
        # Центрированное окно для отображения процесса "размышления" нейросети
        log_h, log_w = 10, 60
        log_win = curses.newwin(log_h, log_w, (h - log_h) // 2, (w - log_w) // 2)
        log_win.attron(curses.color_pair(2))
        log_win.box()
        log_win.attroff(curses.color_pair(2))
        log_win.addstr(0, 2, " GPT TRANSLATION LOG ", curses.color_pair(2) | curses.A_BOLD)
        
        lines = []

        def add_log(msg):
            """Вспомогательная функция для добавления строки в окно лога."""
            lines.append(f"[*] {msg}")
            if len(lines) > log_h - 4:
                lines.pop(0)
            for i, line in enumerate(lines):
                try:
                    log_win.addstr(i + 1, 2, line[:log_w-4])
                except curses.error: pass
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
            
            add_log("Запрос к Opera Aria...")
            messages = [{"role": "user", "content": f"{system_prompt}\n\n{text}"}]
            
            # Асинхронный вызов нейросети
            response = await g4f.ChatCompletion.create_async(
                model="aria",
                provider=g4f.Provider.OperaAria,
                messages=messages,
            )
            
            if response:
                add_log("Готово!")
                await asyncio.sleep(0.5)
                return response.strip()
            else:
                add_log("Ошибка: пустой ответ")
                await asyncio.sleep(1)
                return text

        except Exception as e:
            add_log(f"Крит. ошибка: {str(e)[:40]}")
            log_win.refresh()
            await asyncio.sleep(1.5)
            return text

    async def fetch_tmdb_search(self, session, query):
        """Поиск фильмов через API TMDB. Возвращает список результатов."""
        url = "https://api.themoviedb.org/3/search/movie"
        params = {"api_key": TMDB_API_KEY, "query": query, "language": "ru-RU"}
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("results", [])
        except Exception: return []
        return []

    async def fetch_full_details(self, session, tmdb_id):
        """
        Запрашивает детальную информацию о фильме из TMDB (включая актеров)
        и дополняет её данными из OMDB (для рейтингов IMDb и Rotten Tomatoes).
        """
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
            
            # Поиск режиссера в списке съемочной группы
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
        except Exception: return None

    def draw_main(self, stdscr):
        """Отрисовывает главный интерфейс: список слева и детализацию справа."""
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
        
        try:
            stdscr.attron(color_accent)
            stdscr.box()
            stdscr.addstr(0, 2, " VHS DATABASE MANAGER ", color_accent | curses.A_BOLD)
            stdscr.attroff(color_accent)
        except curses.error: pass

        # Отрисовка списка (Левая колонка)
        list_w = w // 2 - 2
        list_h = h - 4
        if list_w > 5 and list_h > 2:
            list_win = curses.newwin(list_h, list_w, 1, 1)
            list_win.erase()
            for i in range(list_h - 2):
                idx = i + self.offset
                if idx >= len(self.movies): break
                
                attr = color_cursor if idx == self.current_idx else color_normal
                m = self.movies[idx]
                p_id = str(m.get('post_id', '?')).rjust(4)
                title = (m.get('title_ru') or m.get('title', 'Unknown'))[:list_w - 12]
                line = f" {p_id} │ {title} ({m.get('year','?')})"
                try: list_win.addstr(i + 1, 0, line.ljust(list_w), attr)
                except curses.error: pass
            list_win.noutrefresh()

        # Отрисовка карточки фильма (Правая колонка)
        info_w = w // 2 - 2
        info_h = h - 4
        if info_w > 5 and info_h > 2:
            info_win = curses.newwin(info_h, info_w, 1, w // 2 + 1)
            info_win.erase()
            if self.movies and self.current_idx < len(self.movies):
                m = self.movies[self.current_idx]
                try:
                    info_win.addstr(1, 1, f"{m.get('title_ru')}", color_accent | curses.A_BOLD)
                    info_win.addstr(2, 1, f"Original: {m.get('title_en')}", curses.A_DIM)
                    info_win.addstr(3, 1, f"Director: {m.get('director', 'Unknown')}", color_accent)
                    info_win.addstr(4, 1, f"Year: {m.get('year')}   Runtime: {m.get('runtime')}")
                    
                    r = m.get('ratings', {})
                    info_win.addstr(6, 1, f"IMDb: {r.get('imdb','N/A')}  RT: {r.get('rt','N/A')}")
                    
                    wrapper = textwrap.TextWrapper(width=info_w - 4)
                    ov = m.get("overview", "")
                    for i, row in enumerate(wrapper.wrap(ov)[:info_h - 13]):
                        info_win.addstr(8 + i, 1, row)
                except curses.error: pass
            info_win.noutrefresh()

        try:
            stdscr.addstr(h - 2, 2, f" STATUS: {self.status_msg} "[:w-4], color_accent)
        except curses.error: pass
        curses.doupdate()

    async def edit_form(self, stdscr, session, movie_data=None):
        """
        Форма редактирования/создания записи. 
        Позволяет вручную менять поля или подтягивать данные из API по F3.
        """
        h, w = stdscr.getmaxyx()
        f_win = curses.newwin(h-2, w-4, 1, 2)
        f_win.keypad(True)
        
        is_new = movie_data is None
        m = movie_data.copy() if movie_data else {
            "post_id": self.get_next_id(), "title_ru": "", "title_en": "",
            "director": "", "year": 0, "overview": "", "ratings": {"imdb": "N/A", "rt": "N/A"}
        }

        fields = [
            ("Post ID", "post_id"), ("Название RU", "title_ru"), ("Название EN", "title_en"),
            ("Режиссер", "director"), ("Год", "year"), ("Описание", "overview")
        ]
        
        cur_f = 0
        while True:
            f_win.erase()
            f_win.box()
            f_win.addstr(0, 2, " РЕДАКТИРОВАНИЕ КАРТОЧКИ ", curses.color_pair(2))
            f_win.addstr(h-4, 2, " [F3]-TMDB [F4]-Перевод Aria [F10]-Сохранить [Esc]-Отмена ", curses.color_pair(3))

            for i, (label, key) in enumerate(fields):
                attr = curses.color_pair(3) if i == cur_f else curses.A_NORMAL
                val = str(m.get(key, ""))
                try: f_win.addstr(i*2 + 2, 2, f"{label.ljust(12)}: {val[:w-30]}", attr)
                except curses.error: pass

            f_win.refresh()
            k = f_win.getch()

            if k == 27: return None # ESC
            elif k == curses.KEY_F10: return m
            elif k == curses.KEY_UP: cur_f = (cur_f - 1) % len(fields)
            elif k == curses.KEY_DOWN: cur_f = (cur_f + 1) % len(fields)
            elif k == curses.KEY_F3:
                # Поиск через API
                q = self.get_input(stdscr, "Поиск в API: ", m['title_ru'])
                if q:
                    res = await self.fetch_tmdb_search(session, q)
                    if res:
                        sel = await self.select_api_result(stdscr, res)
                        if sel:
                            full = await self.fetch_full_details(session, sel['id'])
                            if full:
                                saved_id = m['post_id']
                                m.update(full)
                                m['post_id'] = saved_id
            elif k == curses.KEY_F4:
                # Перевод текущего поля через GPT
                label, kn = fields[cur_f]
                m[kn] = await self.translate_field(stdscr, m[kn])
            elif k == 10: # Enter - ввод значения в поле
                label, kn = fields[cur_f]
                new_v = self.get_input(stdscr, f"{label}: ", str(m[kn]))
                if kn in ['post_id', 'year']:
                    m[kn] = int(new_v) if new_v.isdigit() else 0
                else:
                    m[kn] = new_v

    async def select_api_result(self, stdscr, results):
        """Всплывающее окно для выбора конкретного фильма из результатов поиска API."""
        h, w = stdscr.getmaxyx()
        win_h = min(len(results) + 4, h - 4)
        sel_win = curses.newwin(win_h, w - 10, (h - win_h)//2, 5)
        sel_win.keypad(True)
        sel_win.box()
        cur = 0
        while True:
            sel_win.addstr(1, 2, "Выберите фильм (Enter-OK, Esc-Отмена):", curses.A_BOLD)
            for i, r in enumerate(results[:win_h-4]):
                attr = curses.A_REVERSE if i == cur else curses.A_NORMAL
                line = f"{r.get('title')} ({r.get('release_date','?')[:4]})"
                try: sel_win.addstr(i+2, 2, line.ljust(w-14), attr)
                except curses.error: pass
            sel_win.refresh()
            k = sel_win.getch()
            if k == curses.KEY_UP: cur = (cur - 1) % len(results)
            elif k == curses.KEY_DOWN: cur = (cur + 1) % len(results)
            elif k == 10: return results[cur]
            elif k == 27: return None

    def get_input(self, stdscr, prompt, existing=""):
        """
        Кастомная функция ввода текста. 
        Использует get_wch() для поддержки русского языка (Unicode).
        """
        h, w = stdscr.getmaxyx()
        in_win = curses.newwin(3, w-10, h//2-1, 5)
        in_win.keypad(True)
        curses.curs_set(1)
        buffer = list(str(existing))
        
        while True:
            in_win.erase()
            in_win.box()
            txt = "".join(buffer)
            display_txt = txt[-(w-25):] # Скроллинг текста внутри поля ввода
            try: in_win.addstr(1, 1, f"{prompt}{display_txt}")
            except curses.error: pass
            in_win.refresh()
            
            try:
                ch = in_win.get_wch()
            except Exception: continue

            if ch == '\n' or ch == '\r' or ch == curses.KEY_ENTER: break
            elif ch == '\x1b': # Esc
                buffer = list(str(existing))
                break
            elif ch == '\x7f' or ch == '\x08' or ch == curses.KEY_BACKSPACE:
                if buffer: buffer.pop()
            elif isinstance(ch, str) and ord(ch) >= 32:
                buffer.append(ch)
                    
        curses.curs_set(0)
        return "".join(buffer).strip()

    async def main_loop(self, stdscr):
        """Главный цикл приложения: обработка нажатий клавиш и обновление экрана."""
        curses.start_color()
        curses.use_default_colors()
        # Инициализация цветовых пар
        curses.init_pair(1, curses.COLOR_WHITE, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE) # Инверсия для курсора
        
        stdscr.keypad(True)
        stdscr.nodelay(True) # Делаем getch неблокирующим для работы asyncio
        curses.curs_set(0)
        
        async with aiohttp.ClientSession() as session:
            while self.running:
                self.draw_main(stdscr)
                h, w = stdscr.getmaxyx()
                
                try:
                    key = stdscr.get_wch()
                except Exception:
                    await asyncio.sleep(0.02)
                    continue

                # Навигация и горячие клавиши
                if key in ['q', 'Q', 'й', 'Й']:
                    self.running = False
                elif key == curses.KEY_UP:
                    if self.movies:
                        self.current_idx = (self.current_idx - 1) % len(self.movies)
                        if self.current_idx < self.offset: self.offset = self.current_idx
                elif key == curses.KEY_DOWN:
                    if self.movies:
                        self.current_idx = (self.current_idx + 1) % len(self.movies)
                        if self.current_idx >= self.offset + h - 6: self.offset += 1
                elif key in ['a', 'A', 'ф', 'Ф']: # Добавить новый
                    res = await self.edit_form(stdscr, session, None)
                    if res:
                        self.movies.append(res)
                        self.save_db()
                elif key == '\n' or key == '\r': # Редактировать
                    if self.movies:
                        res = await self.edit_form(stdscr, session, self.movies[self.current_idx])
                        if res:
                            self.movies[self.current_idx] = res
                            self.save_db()
                elif key == curses.KEY_DC: # Удалить (Delete)
                    if self.movies:
                        self.movies.pop(self.current_idx)
                        self.save_db()
                
                await asyncio.sleep(0.01)

def run_manager():
    """Точка входа в приложение. Инициализирует curses wrapper."""
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
