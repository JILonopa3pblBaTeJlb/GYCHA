#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import curses
import os
import locale
import sys
from collections import OrderedDict

# Подключаем загрузчик конфигурации
from config_loader import conf

# Устанавливаем локаль для корректной работы с кириллицей в терминале
locale.setlocale(locale.LC_ALL, '')

# Глобальные константы интерфейса
DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
HOURS = ["{:02d}:00".format(h) for h in range(24)]

def read_day_file(path):
    """
    Загружает расписание из текстового файла.
    Зачем: Расписание дня — это просто 24 строки с названиями жанров.
    Как: Читает файл, если его нет — возвращает пустой список из 24 элементов.
    """
    if not os.path.exists(path):
        return [""] * 24
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f.readlines()]
    # Гарантируем, что в списке всегда 24 элемента (по количеству часов)
    return lines[:24] + [""] * (24 - len(lines))

def write_day_file(path, lines):
    """
    Сохраняет изменения в файл дня.
    Почему так: Перезаписывает файл целиком, гарантируя ровно 24 строки.
    """
    with open(path, "w", encoding="utf-8") as f:
        for line in lines[:24]:
            f.write((line or "") + "\n")

class RadioGridApp:
    """
    Основной класс визуального редактора сетки.
    """
    def __init__(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0) # Отключаем курсор для "чистого" интерфейса
        curses.use_default_colors()
        
        # Состояние приложения
        self.cx = 0          # Текущая колонка (0-6, Пн-Вс)
        self.cy = 0          # Текущая строка (0-23, часы)
        self.top_row = 0     # Смещение для вертикального скроллинга
        self.changed = False # Флаг наличия несохраненных правок
        self.show_vhs = False # Режим отображения блоков киносеанса
        
        # Названия файлов программ (program0.txt ... program6.txt)
        self.program_files = ["program{}.txt".format(i) for i in range(7)]
        self.default_file = conf.PATHS.program_default
        
        # Загружаем данные
        self.load_vhs_config()
        self.load_data()

    def load_data(self):
        """
        Заполняет рабочую сетку данными из файлов и формирует список жанров.
        Зачем: Чтобы пользователь мог выбирать программы из списка, а не вводить вручную.
        Как: Объединяет ключи из секции [PROGRAM_DISPLAY_NAMES] и всё, что уже вписано в файлы.
        """
        self.grid = []
        for i, p in enumerate(self.program_files):
            # Если файла конкретного дня нет, пробуем загрузить дефолтную программу
            target = p if os.path.exists(p) else self.default_file
            self.grid.append(read_day_file(target))
        
        # Формируем уникальный упорядоченный список программ
        seen = OrderedDict()
        
        # 1. Сначала добавляем жанры из конфигурации
        config_genres = conf.PROGRAM_DISPLAY_NAMES.get_dict().keys()
        for g in config_genres:
            if g != "vhs_movie": # Системный тег кино не добавляем
                seen[g] = True
        
        # 2. Добавляем всё, что уже есть в текущих файлах (если там вписано что-то кастомное)
        for day in self.grid:
            for entry in day:
                e = entry.strip()
                if e and e not in seen:
                    seen[e] = True
        
        self.programs = list(seen.keys())

    def load_vhs_config(self):
        """
        Получает настройки кинозала из центрального конфига.
        """
        self.vhs_hour = conf.AIR_CONTROL.vhs_hour
        self.vhs_days = conf.AIR_CONTROL.vhs_days
        # Конвертируем в список, если в конфиге указан только один день
        if isinstance(self.vhs_days, int):
            self.vhs_days = [self.vhs_days]

    def move_grid(self, dx, dy):
        """
        Обрабатывает перемещение по сетке.
        Зачем: Реализует циклическую навигацию и расчет скроллинга.
        """
        self.cx = (self.cx + dx) % 7
        self.cy = (self.cy + dy) % 24
        
        # Расчет "окна" видимости для скроллинга
        max_rows = curses.LINES - 6
        if self.cy < self.top_row:
            self.top_row = self.cy
        elif self.cy >= self.top_row + max_rows:
            self.top_row = self.cy - max_rows + 1

    def draw_box(self, y, x, h, w, title=None):
        """
        Рисует рамку с заголовком.
        Как: Использует ASCII символы для совместимости со всеми терминалами.
        """
        try:
            UL, UR, LL, LR, H, V = "╔", "╗", "╚", "╝", "═", "║"
            self.stdscr.addstr(y, x, UL + H * (w - 2) + UR)
            for i in range(1, h - 1):
                self.stdscr.addstr(y + i, x, V + " " * (w - 2) + V)
            self.stdscr.addstr(y + h - 1, x, LL + H * (w - 2) + LR)
            if title:
                t = f" {title} "
                if len(t) < w - 2:
                    self.stdscr.addstr(y, x + 2, t, curses.A_BOLD)
        except curses.error: pass

    def draw_grid_screen(self, H, W):
        """
        Отрисовывает основную таблицу редактирования.
        """
        # Рисуем внешнюю рамку
        self.draw_box(0, 0, H, W, title="РЕДАКТОР СЕТКИ ВЕЩАНИЯ " + ("(VHS ON)" if self.show_vhs else ""))
        
        col_w = max(10, (W - 10) // 7) # Ширина колонки дня
        start_x = 9 # Отступ под колонку времени
        
        # Рисуем заголовки дней недели
        for c in range(7):
            x = start_x + c * col_w
            attr = curses.A_BOLD | curses.A_UNDERLINE if c == self.cx else curses.A_BOLD
            self.stdscr.addnstr(1, x + 1, DAYS[c].center(col_w - 2), col_w - 2, attr)
        
        # Отрисовка строк часов
        visible_rows = H - 6
        for r in range(visible_rows):
            row_idx = self.top_row + r
            if row_idx >= 24: break
            y = 2 + r
            
            # Колонка времени (00:00)
            self.stdscr.addstr(y, 1, HOURS[row_idx], curses.A_DIM)
            
            for c in range(7):
                x = start_x + c * col_w
                val = self.grid[c][row_idx] or ""
                attr = curses.A_NORMAL
                
                # Подсветка текущей ячейки
                if c == self.cx and row_idx == self.cy:
                    attr |= curses.A_REVERSE
                
                # Визуализация блоков кино (VHS)
                if self.show_vhs and self.vhs_hour is not None and c in self.vhs_days:
                    if self.vhs_hour <= row_idx < self.vhs_hour + 2:
                        val = "🎥 [VHS_MOVIE]"
                        attr |= curses.A_BOLD
                
                # Обрезаем текст, чтобы не вылазил за пределы колонки
                display_text = " " + val[:col_w - 3]
                self.stdscr.addnstr(y, x + 1, display_text.ljust(col_w - 1), col_w - 1, attr)

        # Информационная панель внизу
        status = f" {DAYS[self.cx]} {HOURS[self.cy]} | {self.grid[self.cx][self.cy] or 'ПУСТО'} | Изменения: {'ДА' if self.changed else 'НЕТ'} "
        self.stdscr.addnstr(H - 2, 2, status[:W - 4], W - 4, curses.A_REVERSE)
        hint = " [Arrows]-Нав [Enter]-Выбор [d]-Удалить [s]-Сохр [v]-VHS [q]-Выход [h]-Помощь "
        self.stdscr.addnstr(H - 1, 2, hint[:W - 4], W - 4, curses.A_DIM)

    def draw(self):
        """Очищает экран и вызывает отрисовку текущего состояния."""
        self.stdscr.erase()
        H, W = curses.LINES, curses.COLS
        if H < 15 or W < 60:
            self.stdscr.addstr(0, 0, "Увеличьте окно терминала!")
        else:
            self.draw_grid_screen(H, W)
        self.stdscr.refresh()

    def prompt_string(self, prompt, initial=""):
        """
        Всплывающее окно для текстового ввода.
        Зачем: Используется для задания имени нового жанра.
        Как: Включает временное отображение курсора.
        """
        sh, sw = curses.LINES, curses.COLS
        win = curses.newwin(5, 60, (sh - 5) // 2, (sw - 60) // 2)
        win.keypad(True)
        win.border()
        curses.curs_set(1) # Показываем курсор
        s = list(initial)
        while True:
            win.erase()
            win.border()
            win.addstr(1, 2, prompt, curses.A_BOLD)
            win.addstr(2, 2, "".join(s))
            win.refresh()
            
            try:
                ch = win.get_wch() # Используем get_wch для поддержки Unicode
            except: continue

            if ch == '\n' or ch == '\r': break
            elif ch == '\x1b': # ESC
                s = None; break
            elif ch in ('\x7f', '\x08', curses.KEY_BACKSPACE):
                if s: s.pop()
            elif isinstance(ch, str):
                s.append(ch)
        
        curses.curs_set(0)
        return "".join(s).strip() if s is not None else None

    def show_program_overlay(self):
        """
        Окно выбора жанра из списка.
        Зачем: Чтобы не вписывать названия жанров руками.
        """
        sh, sw = curses.LINES, curses.COLS
        win_h = min(len(self.programs) + 4, sh - 4)
        win_w = 40
        win = curses.newwin(win_h, win_w, (sh - win_h) // 2, (sw - win_w) // 2)
        win.keypad(True)
        win.border()
        
        cursor = 0
        top = 0
        
        while True:
            win.erase()
            win.border()
            win.addstr(0, 2, " ВЫБЕРИТЕ ПРОГРАММУ ", curses.A_BOLD)
            
            visible_count = win_h - 2
            for i in range(visible_count):
                idx = top + i
                if idx >= len(self.programs): break
                attr = curses.A_REVERSE if idx == cursor else curses.A_NORMAL
                win.addnstr(1 + i, 2, f" {self.programs[idx]} ".ljust(win_w - 4), win_w - 4, attr)
            
            win.refresh()
            ch = win.getch()
            if ch == curses.KEY_UP:
                if cursor > 0: cursor -= 1
                if cursor < top: top -= 1
            elif ch == curses.KEY_DOWN:
                if cursor < len(self.programs) - 1: cursor += 1
                if cursor >= top + visible_count: top += 1
            elif ch in (10, 13): # Enter
                self.grid[self.cx][self.cy] = self.programs[cursor]
                self.changed = True
                break
            elif ch == 27: # Esc
                break
            elif ch == ord('n'): # Новая программа
                nm = self.prompt_string("Новое название:")
                if nm:
                    if nm not in self.programs: self.programs.append(nm)
                    cursor = self.programs.index(nm)
                    self.grid[self.cx][self.cy] = nm
                    self.changed = True
                    break
        del win

    def save_all(self):
        """Записывает все изменения по всем 7 дням в файлы."""
        for i, p in enumerate(self.program_files):
            write_day_file(p, self.grid[i])
        self.changed = False

    def show_help(self):
        """Окно справки по горячим клавишам."""
        sh, sw = curses.LINES, curses.COLS
        help_text = [
            "ГОРЯЧИЕ КЛАВИШИ:",
            " Стрелки / hjkl : Навигация",
            " Enter / e      : Выбрать программу из списка",
            " d              : Очистить ячейку (удалить программу)",
            " s              : Сохранить все изменения в .txt файлы",
            " v              : Показать/скрыть блоки кино (VHS)",
            " n              : Добавить новое имя программы (в окне выбора)",
            " q              : Выйти из редактора",
            " h              : Эта справка",
            "",
            "Нажмите любую клавишу для возврата..."
        ]
        win = curses.newwin(len(help_text) + 2, 50, (sh - len(help_text)) // 2, (sw - 50) // 2)
        win.border()
        for i, line in enumerate(help_text):
            win.addstr(i + 1, 2, line)
        win.refresh()
        win.getch()
        del win

    def run(self):
        """Главный цикл обработки ввода."""
        while True:
            self.draw()
            ch = self.stdscr.getch()
            
            if ch == curses.KEY_RIGHT or ch == ord('l'): self.move_grid(1, 0)
            elif ch == curses.KEY_LEFT or ch == ord('h'): self.move_grid(-1, 0)
            elif ch == curses.KEY_UP or ch == ord('k'): self.move_grid(0, -1)
            elif ch == curses.KEY_DOWN or ch == ord('j'): self.move_grid(0, 1)
            
            elif ch in (10, 13, ord('e')):
                self.show_program_overlay()
            elif ch == ord('d'):
                self.grid[self.cx][self.cy] = ""
                self.changed = True
            elif ch == ord('s'):
                self.save_all()
            elif ch == ord('v'):
                self.show_vhs = not self.show_vhs
            elif ch == ord('q'):
                if self.changed:
                    # Если есть изменения, запрашиваем подтверждение выхода
                    confirm = self.prompt_string("Изменения не сохранены! Выйти? (y/n)")
                    if confirm and confirm.lower() == 'y': break
                else: break
            elif ch == ord('h'):
                self.show_help()

def main(stdscr):
    app = RadioGridApp(stdscr)
    app.run()

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except Exception as e:
        # В случае фатальной ошибки curses, выводим её в консоль
        print(f"Ошибка приложения: {e}")
