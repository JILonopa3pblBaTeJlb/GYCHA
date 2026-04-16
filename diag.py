import asyncio
import re
from config_loader import conf

LINE_WIDTH = 45

# Внутреннее состояние диагностики
_diag_state = {
    "vmstat_boot": "0",
    "vmstat_30s": "0",
    "mtr_lines": []
}

def sanitize_for_ffmpeg(text: str) -> str:
    """Очистка текста и подготовка для FFmpeg"""
    text = text.replace('\\', '\\\\')
    text = text.replace('%', '%%')
    clean = re.sub(r'[^a-zA-Zа-яА-ЯЁё0-9\s\.,:!\-\[\]\(\)\|║═╗╚╝_\\\/]', '', text)
    return clean

async def run_vmstat():
    """Фоновый сборщик данных vmstat с интервалом из конфига"""
    interval = conf.DIAGNOSTICS.vmstat_interval_sec
    while True:
        try:
            # Делаем замер (vmstat [интервал] [кол-во])
            proc = await asyncio.create_subprocess_shell(
                "vmstat 30 2",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if stdout:
                lines = stdout.decode('utf-8', errors='ignore').strip().split('\n')
                if len(lines) >= 3:
                    parts_boot = lines[-2].split()
                    parts_30s = lines[-1].split()
                    
                    st_boot = parts_boot[-1] if len(parts_boot) >= 15 else "0"
                    st_30s = parts_30s[-1] if len(parts_30s) >= 15 else "0"
                    
                    _diag_state["vmstat_boot"] = st_boot
                    _diag_state["vmstat_30s"] = st_30s
        except Exception:
            pass
        await asyncio.sleep(interval)

async def run_mtr():
    """Фоновый сборщик mtr с параметрами из конфига"""
    interval = conf.DIAGNOSTICS.mtr_interval_sec
    target = conf.DIAGNOSTICS.mtr_target_host
    while True:
        try:
            # Используем хост из конфига
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
                    if not parts: continue
                    
                    hop_raw = parts[0].replace('.', '')
                    if not hop_raw.isdigit():
                        continue
                        
                    if len(parts) >= 8:
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
    """Формирует визуальный блок диагностики"""
    lines = []
    HEADER_STR = "═════════NODE HEALTH══════════╗"
    FOOTER_STR = "═════════════════════════════════╝"
    CONTENT_WIDTH = 30
    LINE_WIDTH = 45

    lines.append(HEADER_STR.rjust(LINE_WIDTH))
    
    vm_ascii = [
        r"_  _ _  _ ____ ___ ____ ___ ",
        r"|  | |\/| [__   |  |__|  |  ",
        r" \/  |  | ___]  |  |  |  |  "
    ]
    for row in vm_ascii:
        san_row = sanitize_for_ffmpeg(row)
        extra = row.count('\\')
        lines.append((san_row.center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH + extra))
        
    v_stat = f"[st: avg {_diag_state['vmstat_boot']} | 30s: {_diag_state['vmstat_30s']}]"
    lines.append((sanitize_for_ffmpeg(v_stat).center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH))
    
    empty_row = (" " * CONTENT_WIDTH + "║").rjust(LINE_WIDTH)
    lines.append(empty_row)
    
    mtr_ascii = [
        r"  _  _ ___ ____ ",
        r" |\/|  |  |__/ ",
        r" |  |  |  |  \ "
    ]
    for row in mtr_ascii:
        san_row = sanitize_for_ffmpeg(row)
        extra = row.count('\\')
        lines.append((san_row.center(CONTENT_WIDTH) + "║").rjust(LINE_WIDTH + extra))
    
    mtr_data = _diag_state["mtr_lines"]
    if not mtr_data:
        msg = "INITIALIZING...".center(CONTENT_WIDTH) + "║"
        lines.append(msg.rjust(LINE_WIDTH))
    else:
        for m in mtr_data[:7]:
            m_san = sanitize_for_ffmpeg(m)
            row_content = f"     {m_san}     ║"
            lines.append(row_content.rjust(LINE_WIDTH))
        
    while len(lines) < 17:
        lines.append(empty_row)
        
    lines.append(FOOTER_STR.rjust(LINE_WIDTH))
    return lines
