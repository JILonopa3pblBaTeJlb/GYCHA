# process_manager.py — Управление процессами вещания и отказоустойчивостью
import asyncio
import datetime
from dataclasses import dataclass
from typing import Optional
from enum import Enum

# Импорт единого загрузчика конфигурации
from config_loader import conf

# Импорт функций для формирования команд и управления подпроцессами
from ffmpeg_runner import get_ffmpeg2_cmd, get_ffmpeg3_cmd, build_overlay_concat
from vhs_runner import get_ffmpeg_vhs_cmd, get_ffmpeg_vhs_backup_cmd
from air_supply import ensure_process_stopped

class ProcessType(Enum):
    """Типы процессов вещания."""
    FFMPEG2 = "RADIO_START"   # Стандартное радио (с начала плейлиста)
    FFMPEG3 = "RADIO_RESUME"  # Подхват радио (с вычисленным смещением)
    VHS = "MOVIE_START"       # Начало киносеанса
    VHS_BACKUP = "MOVIE_RESUME" # Возобновление киносеанса после сбоя

@dataclass
class ProcessState:
    """Хранилище состояния текущего запущенного процесса."""
    process: Optional[asyncio.subprocess.Process]
    type: ProcessType
    started_at: datetime.datetime
    expected_duration: Optional[float] = None

class ProcessManager:
    """
    Класс-менеджер, отвечающий за стабильность эфира.
    Следит за тем, чтобы в один момент времени работал только один поток вещания.
    """
    def __init__(self):
        self.current_process: Optional[ProcessState] = None
        self.monitor_task: Optional[asyncio.Task] = None
        self.vhs_deadline: Optional[datetime.datetime] = None
        
    async def switch_to(self, process_type: ProcessType, **kwargs) -> bool:
        """
        Основной метод переключения эфира.
        Останавливает текущий процесс, ждет освобождения ресурсов и запускает новый.
        """
        # Обновляем конфиг перед запуском нового процесса
        conf.reload()
        print(f"🔄 Переключение режима: {process_type.value}")
        
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
            
            # Если запускается фильм, рассчитываем время его принудительного завершения
            if process_type in [ProcessType.VHS, ProcessType.VHS_BACKUP]:
                if self.current_process.expected_duration:
                    buffer = conf.AIR_CONTROL.vhs_overtime_buffer_sec
                    self.vhs_deadline = self.current_process.started_at + datetime.timedelta(
                        seconds=self.current_process.expected_duration + buffer
                    )
            
            # Запускаем фоновый мониторинг здоровья процесса
            self.monitor_task = asyncio.create_task(self._monitor_current())
            return True
            
        except Exception as e:
            print(f"❌ Ошибка при старте {process_type.value}: {e}")
            # Если не удалось запустить что-то специфическое, пробуем вернуться к базовому радио
            if process_type != ProcessType.FFMPEG3:
                return await self.switch_to(ProcessType.FFMPEG3)
            return False
    
    async def _stop_current(self):
        """Останавливает текущий процесс и отменяет задачу мониторинга."""
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
    
    async def _create_process(self, process_type: ProcessType, **kwargs):
        """Фабрика создания процессов на основе команд из runner-модулей."""
        if process_type in [ProcessType.FFMPEG2, ProcessType.FFMPEG3]:
            # Для радио всегда пересобираем список оверлеев
            build_overlay_concat()
        
        if process_type == ProcessType.FFMPEG2:
            cmd = get_ffmpeg2_cmd()
        elif process_type == ProcessType.FFMPEG3:
            cmd = get_ffmpeg3_cmd()
        elif process_type == ProcessType.VHS:
            cmd = get_ffmpeg_vhs_cmd()
        elif process_type == ProcessType.VHS_BACKUP:
            # Режим возобновления фильма с определенной секунды
            start_sec = kwargs.get('start_sec', 0)
            cmd = get_ffmpeg_vhs_backup_cmd(start_sec)
        
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    
    async def _monitor_current(self):
        """
        Следит за выводом процесса. 
        Если FFmpeg перестал писать в stderr дольше, чем на hang_timeout_sec, 
        считаем процесс зависшим и убиваем его.
        """
        if not self.current_process:
            return
            
        process = self.current_process.process
        process_type = self.current_process.type
        
        try:
            last_output_time = datetime.datetime.now()
            
            async def read_stderr():
                nonlocal last_output_time
                while True:
                    line = await process.stderr.readline()
                    if not line: break
                    last_output_time = datetime.datetime.now()
            
            stderr_task = asyncio.create_task(read_stderr())
            
            while process.returncode is None:
                await asyncio.sleep(2.0)
                # Проверка на "замерзание" (полезно при проблемах с сетью или энкодером)
                elapsed = (datetime.datetime.now() - last_output_time).total_seconds()
                if elapsed > conf.AIR_CONTROL.hang_timeout_sec:
                    print(f"💥 Обнаружено зависание {process_type.value} (нет вывода {elapsed}с)")
                    process.kill()
                    break
            
            if not stderr_task.done():
                stderr_task.cancel()
                
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
    
    def is_crashed(self) -> bool:
        """Проверяет, завершился ли процесс с ошибкой (ненулевой код)."""
        if not self.current_process or not self.monitor_task:
            return False
        
        if not self.monitor_task.done():
            return False
        
        process = self.current_process.process
        # Если процесс завершился сам, проверяем код возврата
        if process.returncode is not None and process.returncode != 0:
            # Для VHS завершение может быть плановым по таймауту, это не краш
            if self.current_process.type in [ProcessType.VHS, ProcessType.VHS_BACKUP]:
                if self.is_vhs_timeout_exceeded():
                    return False
            return True
        return False
    
    def is_vhs_active(self) -> bool:
        """Проверяет, идет ли сейчас фильм."""
        return (self.current_process and
                self.current_process.type in [ProcessType.VHS, ProcessType.VHS_BACKUP] and
                self.monitor_task and
                not self.monitor_task.done())
    
    def is_vhs_timeout_exceeded(self) -> bool:
        """Проверяет, не пора ли выключать фильм (вышел ли срок его длительности)."""
        if not self.is_vhs_active() or not self.vhs_deadline:
            return False
        return datetime.datetime.now() >= self.vhs_deadline
    
    async def force_vhs_timeout(self) -> bool:
        """Принудительно возвращает эфир в режим радио."""
        print("🛑 Время фильма истекло, возвращаемся в радио-эфир.")
        return await self.switch_to(ProcessType.FFMPEG3)
    
    async def handle_crash(self) -> bool:
        """
        Логика восстановления после сбоя.
        Если упало радио — перезапускаем радио.
        Если упал фильм — пытаемся продолжить его с момента разрыва.
        """
        if not self.current_process:
            return False
            
        crashed_type = self.current_process.type
        if crashed_type == ProcessType.VHS or crashed_type == ProcessType.VHS_BACKUP:
            elapsed = (datetime.datetime.now() - self.current_process.started_at).total_seconds()
            # Если фильм только начался или еще далеко до конца — возобновляем
            if self.current_process.expected_duration and (self.current_process.expected_duration - elapsed) > 30:
                print(f"🔄 Рестарт фильма с {int(elapsed)} секунды...")
                return await self.switch_to(
                    ProcessType.VHS_BACKUP,
                    start_sec=int(elapsed),
                    expected_duration=self.current_process.expected_duration
                )
        
        # В любой непонятной ситуации — включаем радио
        return await self.switch_to(ProcessType.FFMPEG3)
