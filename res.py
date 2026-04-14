# res.py — Модуль мониторинга системных ресурсов и статистики хранилища
import os
import psutil
from datetime import datetime
from config_loader import conf

# Динамическое получение пути к файлу статистики из конфига с фолбеком
CLOUD_STORAGE_FILE = conf.PATHS.cloud_storage_file if hasattr(conf.PATHS, 'cloud_storage_file') else "cloud_storage.txt"

def cpu_bar(percent: float) -> str:
    """
    Создает визуальную ASCII-шкалу нагрузки на процессор.
    Использует символы '║' для заполнения и '!' для индикации критической зоны (последние 20%).
    Пример: [║║║║║║║║..........]
    """
    mask = "║" * 16 + "!" * 4
    # Защита от некорректных значений процента
    p = max(0.0, min(100.0, float(percent or 0)))
    
    # Расчет количества сегментов (всего 20 делений по 5% каждое)
    filled = int(round(p / 5.0))
    return mask[:filled].ljust(20, ".") + "]"

def two_cpu_bars(cpu1: float, cpu2: float) -> tuple[str, str]:
    """Генерирует две визуальные шкалы для многоядерных систем."""
    return cpu_bar(cpu1), cpu_bar(cpu2)

def get_last_reboot_time():
    """Возвращает дату и время последней загрузки операционной системы."""
    try:
        boot_ts = psutil.boot_time()
        boot_dt = datetime.fromtimestamp(boot_ts)
        return boot_dt.strftime("%m/%d %H:%M:%S")
    except Exception:
        return "N/A"

def get_cpu_usage():
    """
    Снимает показатели нагрузки CPU по каждому ядру.
    interval=None обеспечивает неблокирующее получение мгновенных данных.
    """
    try:
        usage = psutil.cpu_percent(interval=None, percpu=True)
        # Поддержка систем с разным количеством ядер
        cpu1 = usage[0] if len(usage) > 0 else 0
        cpu2 = usage[1] if len(usage) > 1 else cpu1
        return cpu1, cpu2
    except Exception:
        return 0, 0

def get_ram_usage():
    """Возвращает текущее использование оперативной памяти в мегабайтах."""
    try:
        mem = psutil.virtual_memory()
        used_mb = mem.used // (1024 * 1024)
        total_mb = mem.total // (1024 * 1024)
        return used_mb, total_mb
    except Exception:
        return 0, 0

def get_disk_usage():
    """Возвращает занятое и общее пространство на системном диске в гигабайтах."""
    try:
        disk = psutil.disk_usage('/')
        used_gb = disk.used / (1024**3)
        total_gb = disk.total / (1024**3)
        return used_gb, total_gb
    except Exception:
        return 0, 0

def get_cloud_lines(filename=CLOUD_STORAGE_FILE):
    """
    Читает актуальную статистику по количеству медиафайлов из файла.
    Этот файл формируется модулем content.py после сканирования каналов.
    """
    line1, line2 = "Библиотека: обновление...", ""
    try:
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                line = f.read().strip()
                if line:
                    # Разделяем строку на две части для красивой верстки в интерфейсе
                    parts = line.split(",", 1)
                    line1 = parts[0].strip()
                    line2 = parts[1].strip() if len(parts) > 1 else ""
    except Exception:
        pass
    return line1, line2

def get_status_lines() -> list[str]:
    """
    Основная функция-агрегатор. Собирает все системные метрики 
    и возвращает список отформатированных строк для вывода на экран вещания.
    """
    reboot_time = get_last_reboot_time()
    cpu1, cpu2 = get_cpu_usage()
    bar1, bar2 = two_cpu_bars(cpu1, cpu2)
    ram_used, ram_total = get_ram_usage()
    disk_used, disk_total = get_disk_usage()
    cloud_line1, cloud_line2 = get_cloud_lines()

    return [
        f"{cloud_line1}",
        f"{cloud_line2}",
        f"LAST_REBOOT: {reboot_time}",
        f"CPU1 {cpu1:04.1f}% {bar1}",
        f"CPU2 {cpu2:04.1f}% {bar2}",
        f"RAM: {ram_used}Mb / {ram_total}Mb",
        f"HDD: {disk_used:.2f}Gb / {disk_total:.2f}Gb",
    ]
