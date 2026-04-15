import asyncio
import datetime
from dataclasses import dataclass
from typing import Optional
from enum import Enum

# Импорт единого конфига
from config_loader import conf

# Импортируем функции из существующих файлов
from ffmpeg_runner import get_ffmpeg2_cmd, get_ffmpeg3_cmd, build_overlay_concat
from vhs_runner import get_ffmpeg_vhs_cmd, get_ffmpeg_vhs_backup_cmd
from air_supply import ensure_process_stopped, run_script

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
        # Принудительно обновляем конфиг перед переключением
        conf.reload()
        print(f"🔄 Переключаюсь на {process_type.value}")
        
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
            
            # Установка дедлайна VHS с учетом буфера из конфига
            if process_type in [ProcessType.VHS, ProcessType.VHS_BACKUP]:
                if self.current_process.expected_duration:
                    buffer = conf.AIR_CONTROL.vhs_overtime_buffer_sec
                    self.vhs_deadline = self.current_process.started_at + datetime.timedelta(
                        seconds=self.current_process.expected_duration + buffer
                    )
                    print(f"⏰ VHS дедлайн установлен: {self.vhs_deadline.strftime('%H:%M:%S')} (буфер {buffer}с)")
            
            self.monitor_task = asyncio.create_task(self._monitor_current())
            return True
            
        except Exception as e:
            print(f"❌ Ошибка создания {process_type.value}: {e}")
            if process_type != ProcessType.FFMPEG3:
                return await self.switch_to(ProcessType.FFMPEG3)
            return False
    
    async def _stop_current(self):
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        if self.current_process and self.current_process.process:
            await ensure_process_stopped(
                self.current_process.process,
                self.current_process.type.value
            )
            
        self.current_process = None
        self.monitor_task = None
        self.vhs_deadline = None
        
        # Пауза для освобождения RTMP сокета из конфига
        delay = conf.AIR_CONTROL.socket_release_delay_sec
        await asyncio.sleep(delay)
    
    async def _create_process(self, process_type: ProcessType, **kwargs):
        if process_type in [ProcessType.FFMPEG2, ProcessType.FFMPEG3]:
            build_overlay_concat()
        
        if process_type == ProcessType.FFMPEG2:
            cmd = get_ffmpeg2_cmd()
        elif process_type == ProcessType.FFMPEG3:
            cmd = get_ffmpeg3_cmd()
        elif process_type == ProcessType.VHS:
            cmd = get_ffmpeg_vhs_cmd()
        elif process_type == ProcessType.VHS_BACKUP:
            start_sec = kwargs.get('start_sec', 0)
            cmd = get_ffmpeg_vhs_backup_cmd(start_sec)
        
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    
    async def _monitor_current(self):
        if not self.current_process:
            return
            
        process = self.current_process.process
        process_type = self.current_process.type
        last_output_time = datetime.datetime.now()
        start_time = datetime.datetime.now()
        
        try:
            # Воркер для чтения stderr. Используем read(порция), а не readline,
            # так как TLS handshake может не содержать символов новой строки.
            async def stream_reader():
                nonlocal last_output_time
                try:
                    while True:
                        chunk = await process.stderr.read(1024)
                        if not chunk:
                            break
                        last_output_time = datetime.datetime.now()
                except Exception:
                    pass

            reader_task = asyncio.create_task(stream_reader())
            
            while process.returncode is None:
                await asyncio.sleep(1.0)
                
                now = datetime.datetime.now()
                elapsed = (now - last_output_time).total_seconds()
                uptime = (now - start_time).total_seconds()
                
                # Логика детекции зависания
                hang_limit = conf.AIR_CONTROL.hang_timeout_sec
                
                # ГРАЦИЯ ДЛЯ RTMPS (Telegram):
                # Если процесс запущен менее 20 секунд назад, не убиваем его,
                # даже если он молчит (идет установка SSL соединения).
                if uptime > 20 and elapsed > hang_limit:
                    print(f"💥 Hang детекция {process_type.value}: молчание {elapsed:.1f}с (limit {hang_limit}с)")
                    try:
                        process.kill()
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except:
                        pass
                    break
            
            if not reader_task.done():
                reader_task.cancel()
            
            print(f"📢 {process_type.value} завершился (код: {process.returncode})")
            
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"❌ Ошибка мониторинга {process_type.value}: {e}")
    
    def is_crashed(self) -> bool:
        if not self.current_process or not self.monitor_task:
            return False
        
        if not self.monitor_task.done():
            return False
        
        process = self.current_process.process
        if process.returncode is None:
            return False
        
        if self.current_process.type in [ProcessType.VHS, ProcessType.VHS_BACKUP]:
            if self.is_vhs_timeout_exceeded():
                return False
        
        return process.returncode != 0
    
    def is_vhs_active(self) -> bool:
        return (self.current_process and
                self.current_process.type in [ProcessType.VHS, ProcessType.VHS_BACKUP] and
                self.monitor_task and
                not self.monitor_task.done())
    
    def is_vhs_timeout_exceeded(self) -> bool:
        if not self.is_vhs_active() or not self.vhs_deadline:
            return False
        
        now = datetime.datetime.now()
        if now >= self.vhs_deadline:
            print(f"🚨 VHS дедлайн: превышение на { (now - self.vhs_deadline).total_seconds():.1f}с")
            return True
        return False
    
    async def force_vhs_timeout(self) -> bool:
        if not self.is_vhs_active():
            return True
        print("🛑 Принудительный выход из VHS по таймауту")
        self.vhs_deadline = None
        return await self.switch_to(ProcessType.FFMPEG3)
    
    async def handle_crash(self) -> bool:
        if not self.current_process:
            return False
        crashed_type = self.current_process.type
        print(f"🔧 Аварийное восстановление: {crashed_type.value}")
        
        if crashed_type == ProcessType.VHS:
            return await self._handle_vhs_crash()
        return await self.switch_to(ProcessType.FFMPEG3)
    
    async def _handle_vhs_crash(self) -> bool:
        if not self.current_process.expected_duration:
            return await self.switch_to(ProcessType.FFMPEG3)
            
        elapsed = (datetime.datetime.now() - self.current_process.started_at).total_seconds()
        remaining = self.current_process.expected_duration - elapsed
        
        if remaining > 30:
            print(f"🔄 Рестарт VHS с {elapsed:.1f}с")
            return await self.switch_to(
                ProcessType.VHS_BACKUP,
                start_sec=int(elapsed),
                expected_duration=self.current_process.expected_duration
            )
        return await self.switch_to(ProcessType.FFMPEG3)
