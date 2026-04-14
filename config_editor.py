
"""
Config Editor Ultimate
TUI-редактор для .ini файлов с сохранением комментариев.
"""

import curses
import configparser
import asyncio
import os
import locale
import textwrap
from pathlib import Path

# Установка локали для корректного отображения кириллицы
try:
    locale.setlocale(locale.LC_ALL, '')
except Exception:
    pass

# Снижаем задержку ESC для мгновенного выхода из меню в SSH
os.environ.setdefault('ESCDELAY', '25')

class ConfigManager:
    def __init__(self, config_path="config.ini"):
        self.config_path = config_path
        self.config = configparser.ConfigParser(interpolation=None, strict=False)
        self.config.optionxform = str  # Сохраняем регистр ключей
        
        self.comments = {}  # Карта: {(section, key): [lines_of_comments]}
        self.section_comments = {} # Карта: {section: [lines_of_comments]}
        
        self.load_all_data()
        
        self.sections = self.config.sections()
        self.current_sect_idx = 0
        self.current_key_idx = 0
        self.focus = "sections"
        self.offset_sect = 0
        self.offset_keys = 0
        self.running = True
        self.status_msg = "Конфиг загружен. [S]-Сохранить [Enter]-Правка"
        
        self.sect_win = None
        self.keys_win = None
        self.desc_win = None
        self.last_h, self.last_w = 0, 0

    def load_all_data(self):
        """Парсинг конфига и ручной сбор комментариев."""
        if not os.path.exists(self.config_path):
            return

        self.comments = {}
        self.section_comments = {}
        curr_sect = None
        comment_buffer = []

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    
                    # Пустые строки
                    if not stripped:
                        comment_buffer = []
                        continue
                    
                    # Секции
                    if stripped.startswith('[') and ']' in stripped:
                        curr_sect = stripped[1:stripped.find(']')].strip()
                        if comment_buffer:
                            self.section_comments[curr_sect] = comment_buffer
                            comment_buffer = []
                        continue
                    
                    # Комментарии
                    if stripped.startswith((';', '#')):
                        comment_buffer.append(stripped)
                        continue
                    
                    # Ключи
                    if '=' in line and curr_sect:
                        key = line.split('=')[0].strip()
                        if comment_buffer:
                            self.comments[(curr_sect, key)] = comment_buffer
                            comment_buffer = []
                    else:
                        # Если это не ключ, не секция и не коммент — сбрасываем буфер
                        comment_buffer = []
                        
        except Exception as e:
            self.status_msg = f"Ошибка чтения комментариев: {e}"

        try:
            self.config.read(self.config_path, encoding="utf-8")
        except Exception as e:
            self.status_msg = f"Ошибка ConfigParser: {e}"

    def save_config(self):
        """Ручное сохранение для поддержки комментариев и форматирования."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                for sect in self.config.sections():
                    # Записываем комментарии секции
                    if sect in self.section_comments:
                        for c in self.section_comments[sect]:
                            f.write(f"{c}\n")
                    
                    f.write(f"[{sect}]\n")
                    
                    for key, val in self.config.items(sect):
                        # Записываем комментарии ключа
                        if (sect, key) in self.comments:
                            for c in self.comments[(sect, key)]:
                                f.write(f"{c}\n")
                        
                        # Обработка многострочных значений (добавляем табы)
                        if "\n" in str(val):
                            lines = str(val).split("\n")
                            first_line = lines[0]
                            rest = "\n\t".join(lines[1:])
                            f.write(f"{key} = {first_line}\n\t{rest}\n")
                        else:
                            f.write(f"{key} = {val}\n")
                    
                    f.write("\n") # Отступ между секциями
            self.status_msg = "Файл успешно сохранен с комментариями!"
        except Exception as e:
            self.status_msg = f"Ошибка записи: {e}"

    def init_windows(self, stdscr):
        h, w = stdscr.getmaxyx()
        if (h, w) == (self.last_h, self.last_w): return
        self.last_h, self.last_w = h, w
        stdscr.erase()
        
        lw = 32
        lh = h - 4
        self.sect_win = curses.newwin(lh, lw, 1, 1)
        
        kw = w - lw - 4
        kh = h - 12
        self.keys_win = curses.newwin(kh, kw, 1, lw + 2)
        self.desc_win = curses.newwin(7, kw, h - 10, lw + 2)
        
        for win in [self.sect_win, self.keys_win, self.desc_win, stdscr]:
            win.bkgd(' ', curses.color_pair(1))

    def sanitize_val(self, val):
        """Убирает переносы для компактного отображения в списке."""
        return " ".join(str(val).split())

    def draw_main(self, stdscr):
        h, w = stdscr.getmaxyx()
        self.init_windows(stdscr)
        c_norm, c_acc, c_cur = curses.color_pair(1), curses.color_pair(2), curses.color_pair(3)

        try:
            stdscr.attron(c_acc)
            stdscr.box()
            stdscr.addstr(0, 2, " CONFIG EDITOR PRO ", c_acc | curses.A_BOLD)
            stdscr.attroff(c_acc)
        except curses.error: pass

        # --- СЕКЦИИ ---
        self.sect_win.erase()
        self.sect_win.addstr(0, 1, " [ СЕКЦИИ ] ", c_acc | curses.A_BOLD)
        sh, sw = self.sect_win.getmaxyx()
        for i in range(sh - 2):
            idx = i + self.offset_sect
            if idx >= len(self.sections): break
            is_sel = (idx == self.current_sect_idx)
            attr = c_cur if (is_sel and self.focus == "sections") else \
                   (c_acc if (is_sel and self.focus == "keys") else c_norm)
            try:
                self.sect_win.addstr(i + 1, 0, f" {self.sections[idx][:sw-2]}".ljust(sw-1), attr)
            except curses.error: pass

        # --- КЛЮЧИ ---
        self.keys_win.erase()
        self.desc_win.erase()
        if self.sections:
            sect = self.sections[self.current_sect_idx]
            self.keys_win.addstr(0, 1, f" [ {sect} ] ", c_acc | curses.A_BOLD)
            items = list(self.config[sect].items())
            kh, kw = self.keys_win.getmaxyx()
            
            # Скроллинг ключей
            if self.current_key_idx >= self.offset_keys + kh - 2:
                self.offset_keys = self.current_key_idx - kh + 3
            if self.current_key_idx < self.offset_keys:
                self.offset_keys = self.current_key_idx

            for i in range(kh - 2):
                idx = i + self.offset_keys
                if idx >= len(items): break
                k, v = items[idx]
                is_sel = (idx == self.current_key_idx)
                attr = c_cur if (is_sel and self.focus == "keys") else c_norm
                v_clean = self.sanitize_val(v)
                line = f" {k:22} = {v_clean[:kw-26]}"
                try: self.keys_win.addstr(i + 1, 0, line.ljust(kw-1), attr)
                except curses.error: pass

            # --- ОПИСАНИЕ (КОММЕНТАРИИ) ---
            if items and self.current_key_idx < len(items):
                cur_k = items[self.current_key_idx][0]
                comm_list = self.comments.get((sect, cur_k), ["Нет описания."])
                comm_text = " ".join([c.lstrip(';# ') for c in comm_list])
                try:
                    self.desc_win.attron(c_acc); self.desc_win.box(); self.desc_win.addstr(0, 2, " КОММЕНТАРИЙ К КЛЮЧУ "); self.desc_win.attroff(c_acc)
                    wrapped = textwrap.wrap(comm_text, width=kw - 4)
                    for j, line in enumerate(wrapped[:5]): self.desc_win.addstr(j + 1, 2, line)
                except curses.error: pass

        try:
            stdscr.addstr(h - 2, 2, f" СТАТУС: {self.status_msg} "[:w-4], c_acc)
            stdscr.addstr(h - 1, 2, " [Tab]Смена [Enter]Правка [S]Сохранить [A]Добавить [D]Удалить [Q]Выход ", c_cur)
        except curses.error: pass
        
        stdscr.noutrefresh(); self.sect_win.noutrefresh(); self.keys_win.noutrefresh(); self.desc_win.noutrefresh(); curses.doupdate()

    def get_input(self, stdscr, prompt, existing=""):
        """Редактор одной строки."""
        h, w = stdscr.getmaxyx()
        in_win = curses.newwin(5, w-10, h//2-2, 5); in_win.keypad(True); in_win.bkgd(' ', curses.color_pair(1)); in_win.attron(curses.color_pair(2)); in_win.box(); curses.curs_set(1)
        buffer = list(str(existing)); pos = len(buffer)
        while True:
            in_win.erase(); in_win.box(); in_win.addstr(0, 2, f" {prompt} ")
            txt = "".join(buffer); field_w = w - 16; start_view = max(0, pos - field_w + 5)
            display_txt = txt[start_view : start_view + field_w]
            try: in_win.addstr(2, 2, display_txt); in_win.move(2, 2 + (pos - start_view))
            except curses.error: pass
            in_win.refresh()
            try: ch = in_win.get_wch()
            except: continue
            if ch == '\n' or ch == '\r': break
            elif ch == '\x1b': return None
            elif ch in ('\x7f', '\x08', curses.KEY_BACKSPACE):
                if pos > 0: buffer.pop(pos - 1); pos -= 1
            elif ch == curses.KEY_LEFT: pos = max(0, pos - 1)
            elif ch == curses.KEY_RIGHT: pos = min(len(buffer), pos + 1)
            elif isinstance(ch, str) and ord(ch) >= 32: buffer.insert(pos, ch); pos += 1
        curses.curs_set(0); stdscr.erase(); self.last_h = 0
        return "".join(buffer).strip()

    def get_multiline_input(self, stdscr, prompt, existing=""):
        """Полноэкранный редактор для сложных параметров (FFMPEG и т.д.)."""
        h, w = stdscr.getmaxyx()
        win = curses.newwin(h-4, w-4, 2, 2); win.keypad(True); win.bkgd(' ', curses.color_pair(1)); curses.curs_set(1)
        
        # Очищаем текст от табов configparser-а при чтении
        raw_lines = str(existing).split('\n')
        lines = [raw_lines[0]] + [l.strip() for l in raw_lines[1:]]
        
        cy, cx = 0, 0
        offset_y = 0

        while True:
            win.erase(); win.attron(curses.color_pair(2)); win.box(); win.addstr(0, 2, f" РЕДАКТОР: {prompt} "); win.addstr(h-5, 2, " [F10] Сохранить  [ESC] Отмена "); win.attroff(curses.color_pair(2))
            edit_h, edit_w = h - 7, w - 8
            for i in range(edit_h):
                idx = i + offset_y
                if idx < len(lines):
                    win.addstr(i + 1, 2, lines[idx][:edit_w])
            win.move(cy - offset_y + 1, cx + 2)
            win.refresh()

            try: ch = win.get_wch()
            except: continue

            if ch == '\x1b': return None
            elif ch == curses.KEY_F10: break
            elif ch == '\n' or ch == '\r':
                new_line = lines[cy][cx:]
                lines[cy] = lines[cy][:cx]
                lines.insert(cy + 1, new_line)
                cy += 1; cx = 0
            elif ch in ('\x7f', '\x08', curses.KEY_BACKSPACE):
                if cx > 0:
                    lines[cy] = lines[cy][:cx-1] + lines[cy][cx:]
                    cx -= 1
                elif cy > 0:
                    cx = len(lines[cy-1])
                    lines[cy-1] += lines[cy]
                    lines.pop(cy); cy -= 1
            elif ch == curses.KEY_UP and cy > 0: cy -= 1; cx = min(cx, len(lines[cy]))
            elif ch == curses.KEY_DOWN and cy < len(lines)-1: cy += 1; cx = min(cx, len(lines[cy]))
            elif ch == curses.KEY_LEFT:
                if cx > 0: cx -= 1
                elif cy > 0: cy -= 1; cx = len(lines[cy])
            elif ch == curses.KEY_RIGHT:
                if cx < len(lines[cy]): cx += 1
                elif cy < len(lines)-1: cy += 1; cx = 0
            elif isinstance(ch, str) and ord(ch) >= 32:
                lines[cy] = lines[cy][:cx] + ch + lines[cy][cx:]
                cx += 1
            
            if cy < offset_y: offset_y = cy
            if cy >= offset_y + edit_h: offset_y = cy - edit_h + 1

        curses.curs_set(0); stdscr.erase(); self.last_h = 0
        return "\n".join(lines)

    async def main_loop(self, stdscr):
        curses.start_color(); curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
        stdscr.keypad(True); stdscr.nodelay(True)
        
        while self.running:
            self.draw_main(stdscr)
            try: key = stdscr.get_wch()
            except: await asyncio.sleep(0.02); continue

            if key in ['q', 'Q', 'й', 'Й']: self.running = False
            elif key == '\t': self.focus = "keys" if self.focus == "sections" else "sections"
            elif key == curses.KEY_UP:
                if self.focus == "sections":
                    if self.sections: self.current_sect_idx = (self.current_sect_idx - 1) % len(self.sections); self.current_key_idx = 0
                else:
                    sect = self.sections[self.current_sect_idx]
                    items = list(self.config[sect].items())
                    if items: self.current_key_idx = (self.current_key_idx - 1) % len(items)
            elif key == curses.KEY_DOWN:
                if self.focus == "sections":
                    if self.sections: self.current_sect_idx = (self.current_sect_idx + 1) % len(self.sections); self.current_key_idx = 0
                else:
                    sect = self.sections[self.current_sect_idx]
                    items = list(self.config[sect].items())
                    if items: self.current_key_idx = (self.current_key_idx + 1) % len(items)
            elif key in ['s', 'S', 'ы', 'Ы']: self.save_config()
            elif key == '\n' or key == '\r':
                if self.focus == "sections": self.focus = "keys"
                else:
                    sect = self.sections[self.current_sect_idx]
                    keys = list(self.config[sect].keys())
                    if keys:
                        k = keys[self.current_key_idx]
                        val = self.config[sect][k]
                        if len(val) > 60 or "\n" in val or sect == "FFMPEG_TEMPLATES":
                            new_v = self.get_multiline_input(stdscr, k, val)
                        else:
                            new_v = self.get_input(stdscr, f"Правка: {k}", val)
                        if new_v is not None: self.config[sect][k] = new_v
            
            elif key in ['a', 'A', 'ф', 'Ф']:
                sect = self.sections[self.current_sect_idx]
                nk = self.get_input(stdscr, "Новый ключ:")
                if nk:
                    self.config[sect][nk] = "value"
                    self.current_key_idx = len(self.config[sect]) - 1

            elif key in ['d', 'D', 'в', 'В'] or key == curses.KEY_DC:
                if self.focus == "keys":
                    sect = self.sections[self.current_sect_idx]
                    keys = list(self.config[sect].keys())
                    if keys:
                        self.config.remove_option(sect, keys[self.current_key_idx])
                        self.current_key_idx = max(0, self.current_key_idx - 1)
            await asyncio.sleep(0.01)

def run_editor():
    manager = ConfigManager()
    curses.wrapper(lambda stdscr: asyncio.run(manager.main_loop(stdscr)))

if __name__ == "__main__":
    run_editor()
