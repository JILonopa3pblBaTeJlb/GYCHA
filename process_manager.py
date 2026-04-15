import asyncio
import datetime
from dataclasses import dataclass
from typing import Optional
from enum import Enum
from config_loader import conf
from ffmpeg_runner import get_ffmpeg2_cmd, get_ffmpeg3_cmd, build_overlay_concat
from vhs_runner import get_ffmpeg_vhs_cmd, get_ffmpeg_vhs_backup_cmd
from air_supply import ensure_process_stopped

class ProcessType(Enum):
    FFMPEG2 = "FFMPEG2"
    FFMPEG3 = "FFMPEG3"
    VHS = "VHS"
    VHS_BACKUP = "VHS_BACKUP"

@dataclass
class ProcessState:
    process: Optional[asyncio.subprocess.Process]
    type: ProcessType
    started_at: datetime.datetime
    expected_duration: Optional[float] = None

class ProcessManager:
    def __init__(self):
        self.current_process: Optional[ProcessState] = None
        self.monitor_task: Optional[asyncio.Task] = None
        self.vhs_deadline: Optional[datetime.datetime] = None
        
    async def switch_to(self, process_type: ProcessType, **kwargs) -> bool:
        conf.reload()
        print(f"🔄 Переключение на {process_type.value}...")
        
        self.vhs_deadline = None
        await self._stop_current()
        
        try:
            new_process = await self._create_process(process_type, **kwargs)
            self.current_process = ProcessState(
                process=new_process,
                type=process_type,
                started_at=datetime.datetime.now(),
                expected_duration=kwargs.get('expected_duration')
            )
            
            if process_type in [ProcessType.VHS, ProcessType.VHS_BACKUP]:
                if self.current_process.expected_duration:
                    buffer = conf.AIR_CONTROL.vhs_overtime_buffer_sec
                    self.vhs_deadline = self.current_process.started_at + datetime.timedelta(
                        seconds=self.current_process.expected_duration + buffer
                    )
            
            self.monitor_task = asyncio.create_task(self._monitor_current())
            return True
            
        except Exception as e:
            print(f"❌ Ошибка создания процесса {process_type.value}: {e}")
            return False
    
    async def _stop_current(self):
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try: await self.monitor_task
            except asyncio.CancelledError: pass
        
        if self.current_process and self.current_process.process:
            await ensure_process_stopped(
                self.current_process.process,
                self.current_process.type.value
            )
            
        self.current_process = None
        self.monitor_task = None
    
    async def _create_process(self, process_type: ProcessType, **kwargs):
        if process_type in [ProcessType.FFMPEG2, ProcessType.FFMPEG3]:
            await asyncio.to_thread(build_overlay_concat)
        
        if process_type == ProcessType.FFMPEG2: cmd = get_ffmpeg2_cmd()
        elif process_type == ProcessType.FFMPEG3: cmd = get_ffmpeg3_cmd()
        elif process_type == ProcessType.VHS: cmd = get_ffmpeg_vhs_cmd()
        elif process_type == ProcessType.VHS_BACKUP: cmd = get_ffmpeg_vhs_backup_cmd(kwargs.get('start_sec', 0))
        
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    
    async def _monitor_current(self):
        if not self.current_process: return
            
        process = self.current_process.process
        process_type = self.current_process.type
        last_output_time = datetime.datetime.now()
        start_time = datetime.datetime.now()
        
        # Буфер для хранения последних строк ошибок
        error_logs = []

        try:
            async def stream_reader():
                nonlocal last_output_time
                while True:
                    line = await process.stderr.readline()
                    if not line: break
                    last_output_time = datetime.datetime.now()
                    msg = line.decode('utf-8', errors='ignore').strip()
                    if msg:
                        error_logs.append(msg)
                        if len(error_logs) > 15: error_logs.pop(0)

            reader_task = asyncio.create_task(stream_reader())
            
            while process.returncode is None:
                await asyncio.sleep(1.0)
                now = datetime.datetime.now()
                elapsed_since_output = (now - last_output_time).total_seconds()
                uptime = (now - start_time).total_seconds()
                
                # Детекция зависания (только если процесс работает больше 20 сек)
                if uptime > 20 and elapsed_since_output > conf.AIR_CONTROL.hang_timeout_sec:
                    print(f"💥 Зависание {process_type.value}. Убиваем...")
                    process.kill()
                    break
            
            await process.wait()
            if process.returncode != 0 and process.returncode != -9:
                print(f"⚠️ {process_type.value} завершился с ошибкой {process.returncode}")
                print("Последние строки лога FFmpeg:")
                for log in error_logs:
                    print(f"  | {log}")
            
            if not reader_task.done(): reader_task.cancel()
            
        except asyncio.CancelledError: pass
        except Exception as e:
            print(f"❌ Ошибка монитора: {e}")
    
    def is_crashed(self) -> bool:
        if not self.current_process or not self.monitor_task: return False
        if not self.monitor_task.done(): return False
        return self.current_process.process.returncode not in [None, 0, -9]
    
    def is_vhs_active(self) -> bool:
        return (self.current_process and
                self.current_process.type in [ProcessType.VHS, ProcessType.VHS_BACKUP] and
                not self.monitor_task.done())
    
    def is_vhs_timeout_exceeded(self) -> bool:
        if not self.is_vhs_active() or not self.vhs_deadline: return False
        return datetime.datetime.now() >= self.vhs_deadline
    
    async def force_vhs_timeout(self) -> bool:
        return await self.switch_to(ProcessType.FFMPEG3)
    
    async def handle_crash(self) -> bool:
        if not self.current_process: return False
        print(f"🔧 Попытка восстановления...")
        await asyncio.sleep(2) # Пауза перед рестартом
        return await self.switch_to(ProcessType.FFMPEG3)
