import urllib.request
import json
from datetime import datetime


API_URL = 'https://api.open-meteo.com/v1/forecast'

WMO_CODES = {
    0:  'Clear sky',
    1:  'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Icy fog',
    51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle',
    56: 'Light freezing drizzle', 57: 'Heavy freezing drizzle',
    61: 'Light rain', 63: 'Rain', 65: 'Heavy rain',
    66: 'Light freezing rain', 67: 'Heavy freezing rain',
    71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains',
    80: 'Light showers', 81: 'Showers', 82: 'Heavy showers',
    85: 'Snow showers', 86: 'Heavy snow showers',
    95: 'Thunderstorm', 96: 'Thunderstorm w/ hail', 99: 'Thunderstorm w/ heavy hail',
}

def fetch_weather(config):
    weather_cfg = config.get('weather', {})
    lat  = weather_cfg.get('latitude')
    lon  = weather_cfg.get('longitude')
    unit = weather_cfg.get('units', 'fahrenheit')

    if not lat or not lon:
        print('    Skipping weather: no latitude/longitude in config')
        return None

    temp_unit = 'fahrenheit' if unit == 'fahrenheit' else 'celsius'
    unit_symbol = 'F' if unit == 'fahrenheit' else 'C'

    params = (
        '?latitude=' + str(lat) +
        '&longitude=' + str(lon) +
        '&temperature_unit=' + temp_unit +
        '&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m' +
        '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max' +
        '&forecast_days=6' +
        '&wind_speed_unit=mph' +
        '&timezone=auto'
    )

    url = API_URL + params
    print('    Fetching Open-Meteo...')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'DailyBriefing/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print('    Warning: Could not fetch weather: ' + str(e))
        return None

    current = data.get('current', {})
    daily   = data.get('daily', {})

    today = {
        'condition':    WMO_CODES.get(current.get('weather_code', 0), 'Unknown'),
        'temp':         _fmt(current.get('temperature_2m'), unit_symbol),
        'feels_like':   _fmt(current.get('apparent_temperature'), unit_symbol),
        'humidity':     str(int(current.get('relative_humidity_2m', 0))) + '%',
        'wind':         _fmt_wind(current.get('wind_speed_10m')),
        'high':         _fmt(daily.get('temperature_2m_max', [None])[0], unit_symbol),
        'low':          _fmt(daily.get('temperature_2m_min', [None])[0], unit_symbol),
        'precip_chance': str(daily.get('precipitation_probability_max', [0])[0]) + '%',
    }

    forecast = []
    dates    = daily.get('time', [])
    codes    = daily.get('weather_code', [])
    highs    = daily.get('temperature_2m_max', [])
    lows     = daily.get('temperature_2m_min', [])
    precips  = daily.get('precipitation_probability_max', [])

    for i in range(1, min(6, len(dates))):
        dt = datetime.strptime(dates[i], '%Y-%m-%d')
        forecast.append({
            'day':          dt.strftime('%A'),
            'date':         dt.strftime('%b %-d'),
            'condition':    WMO_CODES.get(codes[i] if i < len(codes) else 0, 'Unknown'),
            'high':         _fmt(highs[i] if i < len(highs) else None, unit_symbol),
            'low':          _fmt(lows[i]  if i < len(lows)  else None, unit_symbol),
            'precip_chance': str(precips[i] if i < len(precips) else 0) + '%',
        })

    print('    Got weather + ' + str(len(forecast)) + '-day forecast')
    return {'today': today, 'forecast': forecast, 'unit': unit_symbol}


def _fmt(val, symbol):
    if val is None:
        return '—'
    return str(round(val)) + '°' + symbol

def _fmt_wind(val):
    if val is None:
        return '—'
    return str(round(val)) + ' mph'
