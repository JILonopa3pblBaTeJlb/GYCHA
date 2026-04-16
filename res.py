# res.py
import os
import psutil
from datetime import datetime
from config_loader import conf

# Конфигурация из единого конфига
CLOUD_STORAGE_FILE = conf.PATHS.cloud_storage_file if hasattr(conf.PATHS, 'cloud_storage_file') else "cloud_storage.txt"

# ---------- ШКАЛА CPU ----------
def cpu_bar(percent: float) -> str:
    mask = "║" * 16 + "!" * 4
    p = 0.0 if percent is None else float(percent)
    p = 0.0 if p < 0 else (100.0 if p > 100 else p)
    filled = int(round(p / 5.0))  # 0..20
    return mask[:filled].ljust(20, ".") + "]"

def two_cpu_bars(cpu1: float, cpu2: float) -> tuple[str, str]:
    return cpu_bar(cpu1), cpu_bar(cpu2)

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def get_last_reboot_time():
    try:
        boot_ts = psutil.boot_time()
        boot_dt = datetime.fromtimestamp(boot_ts)
        return boot_dt.strftime("%m/%d %H:%M:%S")
    except Exception:
        return "неизвестно"

def get_cpu_usage():
    try:
        # interval=None важен для неблокирующего вызова!
        usage = psutil.cpu_percent(interval=None, percpu=True)
        cpu1 = usage[0] if len(usage) > 0 else 0
        cpu2 = usage[1] if len(usage) > 1 else 0
        return cpu1, cpu2
    except Exception:
        return 0, 0

def get_ram_usage():
    try:
        mem = psutil.virtual_memory()
        used_mb = mem.used // (1024 * 1024)
        total_mb = mem.total // (1024 * 1024)
        return used_mb, total_mb
    except Exception:
        return 0, 0

def get_disk_usage():
    try:
        disk = psutil.disk_usage('/')
        used_gb = disk.used / (1024**3)
        total_gb = disk.total / (1024**3)
        return used_gb, total_gb
    except Exception:
        return 0, 0

def get_cloud_lines(filename=CLOUD_STORAGE_FILE):
    line1, line2 = "cloud_storage пусто", ""
    try:
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        parts = line.split(",", 1)
                        line1 = parts[0].strip()
                        line2 = parts[1].strip() if len(parts) > 1 else ""
                        break
    except Exception:
        pass
    return line1, line2

# ---------- ГЛАВНАЯ ФУНКЦИЯ ВОЗВРАТА ДАННЫХ ----------
def get_status_lines() -> list[str]:
    """Возвращает список строк для вывода на экран"""
    reboot_time = get_last_reboot_time()
    cpu1, cpu2 = get_cpu_usage()
    bar1, bar2 = two_cpu_bars(cpu1, cpu2)
    ram_used, ram_total = get_ram_usage()
    disk_used, disk_total = get_disk_usage()
    cloud_line1, cloud_line2 = get_cloud_lines()

    lines =[
        f"{cloud_line1}",
        f"{cloud_line2}",
        f"LAST_REBOOT: {reboot_time}",
        f"CPU1 {cpu1:.1f} {bar1}",
        f"CPU2 {cpu2:.1f} {bar2}",
        f"RAM: {ram_used}Mb / {ram_total}Mb",
        f"HDD: {disk_used:.2f}Gb / {disk_total:.2f}Gb",
    ]
    return lines

if __name__ == "__main__":
    # Для теста
    print("\n".join(get_status_lines()))
