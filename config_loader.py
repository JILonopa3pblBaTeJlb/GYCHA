# config_loader.py — Загрузчик и парсер конфигурации
import configparser
import os
from pathlib import Path

class ConfigSection:
    """
    Контейнер для секции конфигурации.
    Преобразует пары ключ-значение из словаря в атрибуты объекта.
    Автоматически определяет и приводит типы данных.
    """
    def __init__(self, items):
        for key, value in items:
            # Динамически создаем атрибут класса для каждого ключа в секции
            setattr(self, key, self._cast(value))
            
    def _cast(self, val: str):
        """
        Приводит строковое значение из .ini файла к соответствующему типу Python.
        Поддерживает: bool, int, float, list и строки.
        """
        val = val.strip()
        # Обработка логических значений
        if val.lower() in ("true", "yes", "on"): return True
        if val.lower() in ("false", "no", "off"): return False
        
        try:
            # Пробуем преобразовать в число (float или int)
            if "." in val: return float(val)
            return int(val)
        except ValueError:
            # Если в строке есть запятые, преобразуем её в список элементов
            if "," in val:
                return [self._cast(i) for i in val.split(",")]
            # В остальных случаях оставляем как строку
            return val

    def get_dict(self):
        """
        Возвращает содержимое секции в виде обычного словаря.
        Полезно, когда нужно итерироваться по параметрам (например, маппинг жанров).
        """
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}


class UniversalConfig:
    """
    Главный класс конфигурации с поддержкой "горячей" перезагрузки.
    Следит за временем изменения файла на диске.
    """
    def __init__(self, path="config.ini"):
        self._path = Path(path)
        self._mtime = 0
        self.reload()

    def reload(self):
        """
        Проверяет, обновлялся ли файл config.ini с момента последней загрузки.
        Если файл изменен, перечитывает его и обновляет атрибуты объекта.
        """
        try:
            if not self._path.exists():
                return False
                
            current_mtime = os.path.getmtime(self._path)
            # Загружаем только если файл реально изменился
            if current_mtime > self._mtime:
                cfg = configparser.ConfigParser()
                cfg.read(self._path, encoding="utf-8")
                
                for section in cfg.sections():
                    # Каждую секцию превращаем в объект ConfigSection
                    setattr(self, section, ConfigSection(cfg.items(section)))
                
                self._mtime = current_mtime
                return True
        except Exception as e:
            # Используем базовый принт, так как логгер может еще не быть инициализирован
            print(f"[ConfigLoader] Ошибка при чтении файла конфигурации: {e}")
        return False

# Создаем единственный экземпляр конфигурации (Singleton),
# который будет импортироваться во все остальные модули проекта.
conf = UniversalConfig()
