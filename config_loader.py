import configparser
import os
from pathlib import Path

class ConfigSection:
    """
    Контейнер для секции конфигурации с безопасным доступом к атрибутам.
    """
    def __init__(self, items):
        self._raw_items = {}
        for key, value in items:
            casted_val = self._cast(value)
            self._raw_items[key] = casted_val
            setattr(self, key, casted_val)
            
    def _cast(self, val: str):
        val = val.strip()
        if val.lower() in ("true", "yes", "on"): return True
        if val.lower() in ("false", "no", "off"): return False
        
        try:
            if "." in val: return float(val)
            return int(val)
        except ValueError:
            if "," in val:
                return [self._cast(i) for i in val.split(",")]
            return val

    def __getattr__(self, item):
        """Возвращает None вместо ошибки, если ключ не найден."""
        return self._raw_items.get(item, None)

    def get_dict(self):
        return self._raw_items


class UniversalConfig:
    def __init__(self, path="config.ini"):
        self._path = Path(path).resolve()
        self._mtime = 0
        self._sections = {}
        self.reload()

    def reload(self):
        try:
            if not self._path.exists():
                print(f"[ConfigLoader] Файл не найден: {self._path}")
                return False
                
            current_mtime = os.path.getmtime(self._path)
            if current_mtime > self._mtime:
                cfg = configparser.ConfigParser(interpolation=None)
                cfg.read(self._path, encoding="utf-8")
                
                for section in cfg.sections():
                    new_section_obj = ConfigSection(cfg.items(section))
                    setattr(self, section, new_section_obj)
                    self._sections[section] = new_section_obj
                
                self._mtime = current_mtime
                return True
        except Exception as e:
            print(f"[ConfigLoader] Ошибка: {e}")
        return False

    def __getattr__(self, section_name):
        """Если секция не найдена, возвращает пустой объект, чтобы не падать на секция.ключ."""
        if section_name in self._sections:
            return self._sections[section_name]
        return ConfigSection([])

conf = UniversalConfig()
