# finance.py — Модуль мониторинга финансовых рынков
import aiohttp
import asyncio
import os
from config_loader import conf

async def get_all_rates(session: aiohttp.ClientSession):
    """
    Асинхронно запрашивает курсы всех валют относительно BTC через CoinGecko API.
    Использование одного запроса для всех валют экономит лимиты API и ускоряет работу.
    """
    url = "https://api.coingecko.com/api/v3/exchange_rates"
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("rates", {})
            else:
                # В продакшене ошибки API логируются для диагностики
                return None
    except Exception as e:
        # Ошибки сети (таймауты, отсутствие связи) не должны ронять основной GUI
        return None

def sync_read_btc_max():
    """
    Синхронное чтение файла с зафиксированным максимумом цены Биткоина.
    Файл имеет формат "BTC/USD: цена <-max".
    """
    path = conf.PATHS.btc_data_file
    if not os.path.exists(path):
        return 0.0
    try:
        with open(path, "r", encoding="utf-8") as f:
            line = f.readline().strip()
            # Очищаем строку от меток, чтобы получить только числовое значение
            clean_line = line.split("<-")[0]
            if ":" in clean_line:
                val_str = clean_line.split(":")[1].strip()
                return float(val_str)
    except Exception:
        pass
    return 0.0

def sync_write_btc_max(line_text):
    """
    Записывает новое значение исторического максимума в файл.
    """
    try:
        with open(conf.PATHS.btc_data_file, "w", encoding="utf-8") as f:
            f.write(line_text + "\n")
    except Exception:
        pass

async def get_finance_lines(session: aiohttp.ClientSession) -> list[str]:
    """
    Главная функция модуля. Собирает данные, сравнивает с максимумом 
    и формирует список строк для вывода на экран вещания.
    
    Логика кросс-курса: API отдает курсы в BTC. Чтобы получить RUB/USD, 
    мы делим курс RUB (в BTC) на курс USD (в BTC).
    """
    # Принудительно обновляем конфиг, чтобы подхватить изменения в списке валют
    conf.reload()
    
    rates = await get_all_rates(session)
    lines = []

    if not rates:
        return ["Финансы: ошибка API"]

    # Извлекаем базу (например, USD) из настроек
    crypto_key = conf.FINANCE.base_crypto.lower()
    # Значение BTC в базовой валюте (база / BTC_rate)
    # На самом деле API отдает 'value' как кол-во единиц валюты за 1 BTC
    btc_fiat_price = rates.get(crypto_key, {}).get('value')

    # 1. Обработка курса Биткоина и проверка рекорда
    if btc_fiat_price is not None:
        # Используем run_in_executor (через to_thread), чтобы блокирующее чтение файла
        # не тормозило асинхронный цикл отрисовки GUI
        btc_max = await asyncio.to_thread(sync_read_btc_max)
        
        if btc_fiat_price > btc_max:
            line_str = f"BTC/{crypto_key.upper()}: {btc_fiat_price:.2f} <-max"
            await asyncio.to_thread(sync_write_btc_max, line_str)
        else:
            line_str = f"BTC/{crypto_key.upper()}: {btc_fiat_price:.2f}"
        lines.append(line_str)
    else:
        lines.append(f"BTC/{crypto_key.upper()}: ошибка")

    # 2. Динамическая обработка списка фиатных валют из config.ini
    target_fiats = conf.FINANCE.target_fiats
    if isinstance(target_fiats, str):
        target_fiats = [target_fiats]

    for fiat in target_fiats:
        fiat_code = fiat.strip().lower()
        if fiat_code == crypto_key: continue # Пропускаем дубликат базовой валюты
        
        fiat_btc_rate = rates.get(fiat_code, {}).get('value')
        
        if btc_fiat_price and fiat_btc_rate:
            # Вычисляем кросс-курс относительно базовой валюты
            # Пример: (RUB за 1 BTC) / (USD за 1 BTC) = RUB за 1 USD
            cross_rate = fiat_btc_rate / btc_fiat_price
            lines.append(f"{fiat_code.upper()}/{crypto_key.upper()}: {cross_rate:.2f}")
        else:
            lines.append(f"{fiat_code.upper()}/{crypto_key.upper()}: ошибка")

    return lines
