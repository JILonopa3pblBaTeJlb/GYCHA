# uvb.py — Генератор криптограмм в стиле радиостанции УВБ-76
import random
import unicodedata
import os
from config_loader import conf

# Константы для верстки
N_MESSAGES = 16    # Количество сообщений в блоке
LINE_WIDTH = 45    # Ширина строки для выравнивания в интерфейсе

# Глобальные переменные для хранения словаря в памяти
_nouns = []
_first_allowed = []
_data_loaded = False

# Резервный набор слов на случай отсутствия внешнего словаря
FALLBACK_NOUNS = ["ОБЪЕКТ", "РАЙОН", "ЦЕНТР", "СИГНАЛ", "ПРИЕМ", "СВЯЗЬ", "КОД", "БАЗА"]

def normalize_word(word: str) -> str:
    """
    Приводит слово к стандартному виду: верхний регистр, отсутствие лишних пробелов
    и нормализация символов Юникода (NFC).
    """
    return unicodedata.normalize('NFC', word.strip()).upper()

def ends_bad_for_first(word: str) -> bool:
    """
    Проверяет, подходит ли слово для использования в качестве первой части сложного слова.
    Исключает слова с окончаниями, которые плохо звучат при слиянии (например, на 'Ь', 'Й', 'Я').
    """
    BAD_FIRST_ENDINGS = ("ИЕ", "ИЙ", "ЫЙ", "ЬЕ", "ЬЁ", "УЙ", "Ь", "Я", "Ё", "Е", "Э", "ЕО", "ОЙ", "ЕЙ", "АЙ", "Ы")
    w = normalize_word(word)
    if w.endswith("ИЯ"): return True
    for e in BAD_FIRST_ENDINGS:
        if w.endswith(e): return True
    return False

def load_data():
    """
    Загружает словарь существительных из файла, указанного в конфигурации.
    Формирует два списка: все слова и слова, пригодные для начала сложной конструкции.
    """
    global _nouns, _first_allowed, _data_loaded
    
    loaded_nouns = []
    path_to_nouns = conf.PATHS.nouns_file
    
    if os.path.exists(path_to_nouns):
        try:
            with open(path_to_nouns, "r", encoding="utf-8") as f:
                loaded_nouns = [normalize_word(line) for line in f if line.strip()]
        except Exception as e:
            print(f"[uvb] Ошибка загрузки словаря: {e}")
    
    if not loaded_nouns:
        loaded_nouns = FALLBACK_NOUNS

    _nouns = loaded_nouns
    # Фильтруем слова для первой части пароля по лингвистическим правилам
    _first_allowed = [w for w in _nouns if not ends_bad_for_first(w)]
    
    if not _first_allowed:
        _first_allowed = _nouns
        
    _data_loaded = True

def random_cyrillic_letters(n=4):
    """Генерирует случайный буквенный позывной заданной длины."""
    letters = [chr(code) for code in range(ord('А'), ord('Я') + 1)]
    return ''.join(random.choices(letters, k=n))

def random_number(digits=4):
    """Генерирует случайную цифровую группу."""
    start = 10 ** (digits - 1)
    end = 10 ** digits - 1
    return str(random.randint(start, end))

def join_words_with_rules(word1, word2):
    """
    Соединяет два слова по правилам русского языка, используя соединительную гласную 'О'.
    Пример: ОБЪЕКТ + СИГНАЛ -> ОБЪЕКТОСИГНАЛ.
    """
    last_char = word1[-1]
    if last_char == 'О':
        word1 = word1[:-1]
        connector = 'О'
    elif last_char == 'А':
        word1 = word1[:-1] + 'О'
        connector = ''
    elif last_char == 'Я':
        connector = ''
    elif last_char == 'Ь':
        connector = 'Я'
    else:
        connector = 'О'
    return f"{word1}{connector}{word2}"

def generate_codeword():
    """
    Создает уникальное кодовое слово-пароль, комбинируя два случайных существительных.
    Проводит до 50 попыток, чтобы найти удачную комбинацию, подходящую по длине.
    """
    for _ in range(50):
        word1 = random.choice(_first_allowed)
        word2 = random.choice(_nouns)
        # Избегаем повторов и слов на одну и ту же букву для лучшей читаемости
        if word1 == word2 or word1[0] == word2[0]:
            continue
        combined = join_words_with_rules(word1, word2)
        if len(combined) <= 22: # Лимит длины для корректной верстки
            return combined
    return f"{word1}-{word2}"

def generate_message_raw():
    """
    Собирает полную строку сообщения.
    Формат: ПОЗЫВНОЙ-ГРУППА-ПАРОЛЬ-ЦИФРЫ║
    """
    callsign = random_cyrillic_letters(4)
    group = random_number(4)
    codeword = generate_codeword()
    number2 = random_number(4)
    return f"{callsign}-{group}-{codeword}-{number2}║"

def mirror_sort_correct(messages):
    """
    Сортирует сообщения так, чтобы самые короткие были по краям, а длинные — в центре.
    Это создает характерный визуальный "ромбовидный" силуэт в текстовом блоке.
    """
    n = len(messages)
    mid = n // 2
    top = messages[:mid]
    bottom = messages[mid:]
    return top[::-1] + bottom

def shuffle_middle_5(messages):
    """Слегка перемешивает центральные строки для придания списку более хаотичного вида."""
    n = len(messages)
    mid = n // 2
    start = max(mid - 2, 0)
    end = min(mid + 3, n)
    middle_slice = messages[start:end]
    random.shuffle(middle_slice)
    return messages[:start] + middle_slice + messages[end:]

def get_uvb_lines() -> list[str]:
    """
    Главная функция модуля. Генерирует пачку сообщений, 
    применяет к ним визуальные фильтры и возвращает список строк с рамками.
    """
    if not _data_loaded:
        load_data()

    lines = []
    lines.append("════════УВБ-76════════════════╗".rjust(LINE_WIDTH))

    # Генерируем сообщения
    messages = [generate_message_raw() for _ in range(N_MESSAGES)]
    # Сортируем по длине для "зеркального" эффекта
    messages_sorted = sorted(messages, key=len)
    messages_mirrored = mirror_sort_correct(messages_sorted)
    # Добавляем немного хаоса в центр
    messages_final = shuffle_middle_5(messages_mirrored)

    # Добавляем отступы для выравнивания в правой панели
    lines.extend([msg.rjust(LINE_WIDTH) for msg in messages_final])
    lines.append("════════════UVB76════════════════╝".rjust(LINE_WIDTH))
    
    return lines
