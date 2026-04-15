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
    Очищает строку от символов, которые могут сломать логику drawtext,
    но НЕ экранирует их (экранирование делает status.py).
    """
    # Убираем всё, кроме разрешенного набора
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
    Формирует визуальный блок «NODE HEALTH».
    """
    lines = []
    HEADER_STR = "═════════NODE HEALTH══════════╗"
    FOOTER_STR = "═════════════════════════════════╝"
    CONTENT_WIDTH = 30 

    lines.append(HEADER_STR.rjust(LINE_WIDTH))
    
    vm_ascii = [
        r"_  _ _  _ ____ ___ ____ ___ ",
        r"|  | |\/| [__   |  |__|  |  ",
        r" \/  |  | ___]  |  |  |  |  "
    ]
    for row in vm_ascii:
        # Просто центрируем сырую строку
        lines.append((row.center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH))
        
    v_stat = f"[st: avg {_diag_state['vmstat_boot']} | 30s: {_diag_state['vmstat_30s']}]"
    lines.append((v_stat.center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH))
    
    empty_row = (" " * CONTENT_WIDTH + "║").rjust(LINE_WIDTH)
    lines.append(empty_row)
    
    mtr_ascii = [
        r"  _  _ ___ ____ ",
        r" |\/|  |  |__/ ",
        r" |  |  |  |  \ "
    ]
    for row in mtr_ascii:
        lines.append((row.center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH))
    
    mtr_data = _diag_state["mtr_lines"]
    if not mtr_data:
        lines.append("INITIALIZING...".center(CONTENT_WIDTH).rjust(LINE_WIDTH) + "║")
    else:
        for m in mtr_data[:7]:
            # Берем очищенную строку MTR
            m_san = sanitize_for_ffmpeg(m)
            lines.append((m_san.center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH))
        
    while len(lines) < 17:
        lines.append(empty_row)
        
    lines.append(FOOTER_STR.rjust(LINE_WIDTH))
    return lines
