# weather.py — Модуль мониторинга погоды через Open-Meteo API
import aiohttp
import asyncio
from datetime import datetime
from config_loader import conf

# Внутренний кэш для хранения последних успешных прогнозов
_weather_cache = {}

# Маппинг кодов WMO (World Meteorological Organization) в текстовые описания
# Эти коды возвращаются API и описывают состояние неба и осадки
weather_text = {
    0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "иней, туман", 51: "легкая морось", 53: "умеренная морось", 55: "плотная морось",
    56: "ледяная морось", 57: "сильная ледяная морось", 61: "небольшой дождь", 63: "умеренный дождь",
    65: "сильный дождь", 66: "ледяной дождь", 67: "сильный ледяной дождь", 71: "небольшой снег",
    73: "умеренный снег", 75: "сильный снегопад", 77: "снежная зернь", 80: "небольшой ливень",
    81: "умеренный ливень", 82: "сильный ливень", 85: "небольшой снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}

def parse_cities_from_config():
    """
    Преобразует строки из секции [WEATHER_CITIES] конфигурационного файла в рабочий словарь.
    Формат в конфиге: Название = Отображаемое имя | Широта | Долгота
    Пример: haifa = Хайфа | 32.7940 | 34.9896
    """
    raw_cities = conf.WEATHER_CITIES.get_dict()
    parsed_cities = {}
    for key, value in raw_cities.items():
        try:
            if isinstance(value, str) and "|" in value:
                parts = [p.strip() for p in value.split("|")]
                if len(parts) == 3:
                    display_name, lat, lon = parts
                    parsed_cities[display_name] = (float(lat), float(lon))
        except Exception:
            # Ошибки парсинга отдельного города не должны прерывать загрузку остальных
            continue
    return parsed_cities


async def get_weather_lines(session: aiohttp.ClientSession) -> list[str]:
    """
    Основная функция модуля. 
    1. Формирует единый пакетный запрос к API для всех городов сразу.
    2. Извлекает прогноз на ближайший час.
    3. Формирует список строк для интерфейса вещания.
    """
    # Проверяем, не изменился ли список городов в конфиге
    conf.reload()
    
    cities = parse_cities_from_config()
    lines = []
    city_names = list(cities.keys())
    
    if not city_names:
        return ["Погода: города не настроены"]
    
    try:
        # Подготовка параметров для пакетного запроса (координаты через запятую)
        lats = ",".join(str(cities[name][0]) for name in city_names)
        lons = ",".join(str(cities[name][1]) for name in city_names)
        
        # Запрос прогноза (температура и коды погоды)
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lats}&longitude={lons}"
            "&hourly=temperature_2m,weathercode"
            "&timezone=UTC"
        )
        
        async with session.get(url, timeout=15) as resp:
            if resp.status != 200:
                resp.raise_for_status()

            data = await resp.json()
            
            # Если в запросе был один город, API вернет словарь, если несколько — список словарей
            if isinstance(data, dict):
                data = [data]
                
            # Работаем в UTC для синхронизации с данными API
            now_utc = datetime.utcnow()
            
            for i, city_data in enumerate(data):
                if i >= len(city_names): break
                
                city = city_names[i]
                hourly = city_data.get('hourly', {})
                times = hourly.get('time', [])
                temps = hourly.get('temperature_2m', [])
                codes = hourly.get('weathercode', [])
                
                forecast_str = "нет данных"
                
                # Ищем в почасовом прогнозе ближайшую временную метку
                for j, t_str in enumerate(times):
                    try:
                        t_obj = datetime.fromisoformat(t_str)
                        # Выбираем прогноз на текущий час
                        if t_obj >= now_utc.replace(minute=0, second=0, microsecond=0):
                            temp = temps[j]
                            desc = weather_text.get(codes[j], "неизвестно")
                            forecast_str = f"{temp:+.1f}'C, {desc}"
                            break
                    except (ValueError, IndexError):
                        continue
                
                # Обновляем кэш свежими данными
                _weather_cache[city] = forecast_str
                lines.append(f"{city}: {forecast_str}")
                
    except Exception:
        # В случае сбоя сети пытаемся отдать данные из кэша
        for city in city_names:
            if city in _weather_cache:
                lines.append(f"{city}: {_weather_cache[city]} (кэш)")
            else:
                lines.append(f"{city}: нет связи")

    return lines
