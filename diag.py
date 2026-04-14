# diag.py — Диагностика системы и мониторинг сетевого здоровья
import asyncio
import re
from config_loader import conf

# Фиксированная ширина строки для верстки блока в интерфейсе
LINE_WIDTH = 45

# Внутреннее состояние диагностики (хранит последние замеры)
_diag_state = {
    "vmstat_boot": "0",  # Среднее значение с момента загрузки ОС
    "vmstat_30s": "0",   # Значение за последние 30 секунд
    "mtr_lines": []      # Список строк с результатами трассировки
}

def sanitize_for_ffmpeg(text: str) -> str:
    """
    Экранирует спецсимволы и очищает строку перед передачей в фильтр drawtext FFmpeg.
    Удаляет символы, которые могут вызвать ошибку парсинга командной строки.
    """
    # Экранируем обратные слэши и проценты
    text = text.replace('\\', '\\\\')
    text = text.replace('%', '%%')
    # Оставляем только безопасный набор символов (буквы, цифры, знаки препинания)
    clean = re.sub(r'[^a-zA-Zа-яА-ЯЁё0-9\s\.,:!\-\[\]\(\)\|║═╗╚╝_\\\/]', '', text)
    return clean

async def run_vmstat():
    """
    Фоновая задача для сбора метрик CPU через системную утилиту vmstat.
    Запускается циклично с интервалом из конфигурации.
    """
    interval = conf.DIAGNOSTICS.vmstat_interval_sec
    while True:
        try:
            # Выполняем 2 замера с интервалом 30 секунд
            # Первый замер — среднее с загрузки, второй — актуальное состояние
            proc = await asyncio.create_subprocess_shell(
                "vmstat 30 2",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if stdout:
                lines = stdout.decode('utf-8', errors='ignore').strip().split('\n')
                if len(lines) >= 3:
                    # Извлекаем колонку 'st' (Steal time) или 'id' (Idle) в зависимости от ОС
                    # В данном случае ориентируемся на последние значения в строке (статистика CPU)
                    parts_boot = lines[-2].split()
                    parts_30s = lines[-1].split()
                    
                    # Записываем состояние процессора
                    _diag_state["vmstat_boot"] = parts_boot[-1] if len(parts_boot) >= 15 else "0"
                    _diag_state["vmstat_30s"] = parts_30s[-1] if len(parts_30s) >= 15 else "0"
        except Exception:
            # Ошибки игнорируются, чтобы не останавливать основной цикл GUI
            pass
        await asyncio.sleep(interval)

async def run_mtr():
    """
    Фоновая задача для мониторинга сети через mtr (My Traceroute).
    Проверяет потери пакетов (Loss) и задержки (Ping) до целевого хоста.
    """
    interval = conf.DIAGNOSTICS.mtr_interval_sec
    target = conf.DIAGNOSTICS.mtr_target_host
    while True:
        try:
            # Запускаем mtr в режиме отчета (-rw) с 50 пакетами (-c 50)
            proc = await asyncio.create_subprocess_shell(
                f"mtr -rwzbc 50 {target}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if stdout:
                lines = stdout.decode('utf-8', errors='ignore').strip().split('\n')
                
                mtr_parsed = []
                for line in lines:
                    if not line.strip(): continue
                    parts = line.split()
                    if not parts or not parts[0].replace('.', '').isdigit():
                        continue
                        
                    # Парсим номер хопа, процент потерь и средний пинг
                    if len(parts) >= 8:
                        hop_raw = parts[0].replace('.', '')
                        avg_ping = parts[-4]
                        try:
                            loss_val = float(parts[-7].replace('%', ''))
                        except:
                            loss_val = 0.0
                        
                        mtr_line = f"H:{hop_raw:>2} L:{loss_val:04.1f} P:{avg_ping:>5}ms"
                        mtr_parsed.append(mtr_line)
                
                if mtr_parsed:
                    _diag_state["mtr_lines"] = mtr_parsed
        except Exception:
            pass
        await asyncio.sleep(interval)

def get_diag_lines() -> list[str]:
    """
    Формирует визуальный блок «NODE HEALTH» для вывода в FFmpeg.
    Собирает данные из vmstat и mtr в красивый ASCII-контейнер.
    """
    lines = []
    HEADER_STR = "═════════NODE HEALTH══════════╗"
    FOOTER_STR = "═════════════════════════════════╝"
    CONTENT_WIDTH = 30 # Ширина внутренней части рамки

    # Верхняя граница
    lines.append(HEADER_STR.rjust(LINE_WIDTH))
    
    # Логотип/Заголовок VMSTAT (ASCII-арт)
    vm_ascii = [
        r"_  _ _  _ ____ ___ ____ ___ ",
        r"|  | |\/| [__   |  |__|  |  ",
        r" \/  |  | ___]  |  |  |  |  "
    ]
    for row in vm_ascii:
        san_row = sanitize_for_ffmpeg(row)
        # Учитываем экранирование слэшей при расчете отступов
        extra = row.count('\\')
        lines.append((san_row.center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH + extra))
        
    # Данные о загрузке процессора
    v_stat = f"[st: avg {_diag_state['vmstat_boot']} | 30s: {_diag_state['vmstat_30s']}]"
    lines.append((sanitize_for_ffmpeg(v_stat).center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH))
    
    # Разделитель
    empty_row = (" " * CONTENT_WIDTH + "║").rjust(LINE_WIDTH)
    lines.append(empty_row)
    
    # Логотип/Заголовок MTR (ASCII-арт)
    mtr_ascii = [
        r"  _  _ ___ ____ ",
        r" |\/|  |  |__/ ",
        r" |  |  |  |  \ "
    ]
    for row in mtr_ascii:
        san_row = sanitize_for_ffmpeg(row)
        extra = row.count('\\')
        lines.append((san_row.center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH + extra))
    
    # Результаты трассировки (последние 7 прыжков)
    mtr_data = _diag_state["mtr_lines"]
    if not mtr_data:
        msg = "INITIALIZING...".center(CONTENT_WIDTH) + "║"
        lines.append(msg.rjust(LINE_WIDTH))
    else:
        for m in mtr_data[:7]:
            m_san = sanitize_for_ffmpeg(m)
            row_content = f"     {m_san}     ║"
            lines.append(row_content.rjust(LINE_WIDTH))
        
    # Заполняем пустое пространство до фиксированной высоты блока
    while len(lines) < 17:
        lines.append(empty_row)
        
    # Нижняя граница
    lines.append(FOOTER_STR.rjust(LINE_WIDTH))
    return lines
