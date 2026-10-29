"""Configuración aislada: sólo lee el .env de esta carpeta, nunca el de v5."""
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
import math
import re
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
VALUES = dotenv_values(ROOT / '.env', interpolate=False)
COLOMBIA = timezone(timedelta(hours=-5), 'America/Bogota')
PLAN = {'0900': ('calls', 'whatsapp'), '1200': ('calls',), '1500': ('calls', 'email')}
SLOT_HOURS = {'0900': 9, '1200': 12, '1500': 15}
WINDOW_MINUTES = 10
SMS_ENABLED = False

def value(name, default=''):
    return (VALUES.get(name) or default).strip()

TEST_START_DATE = date.fromisoformat(value('TEST_START_DATE', value('TEST_DATE', '2026-10-09')))
TEST_END_DATE = date.fromisoformat(value('TEST_END_DATE', TEST_START_DATE.isoformat()))
# Alias de compatibilidad para vistas previas antiguas; no fija el día de ejecución.
TEST_DATE = TEST_START_DATE

def test_days():
    if TEST_END_DATE < TEST_START_DATE:
        raise ValueError('TEST_END_DATE debe ser igual o posterior a TEST_START_DATE')
    day = TEST_START_DATE
    while day <= TEST_END_DATE:
        yield day
        if day == TEST_END_DATE:
            break
        day += timedelta(days=1)

def flag(name, default='false'):
    text = value(name, default).lower()
    if text not in {'true', 'false'}:
        raise ValueError(f'{name}: usa true o false')
    return text == 'true'

def now_colombia():
    return datetime.now(COLOMBIA)

DRY_RUN = flag('DRY_RUN', 'true')
TWILIO_ACCOUNT_SID = value('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = value('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = value('TWILIO_PHONE_NUMBER')
WHATSAPP_SENDER = value('WHATSAPP_SENDER')
WHATSAPP_CONTENT_SID = value('WHATSAPP_CONTENT_SID')
TEST_PHONE = value('TEST_PHONE')
TEST_WHATSAPP = value('TEST_WHATSAPP') or TEST_PHONE
TEST_EMAIL = value('TEST_EMAIL')
GMAIL_USER = value('GMAIL_USER')
GMAIL_APP_PASSWORD = value('GMAIL_APP_PASSWORD')
WHATSAPP_ENABLED = flag('WHATSAPP_ENABLED', 'true')
TWILIO_TRIAL_MODE = flag('TWILIO_TRIAL_MODE', 'false')
OWN_CONTACTS_CONFIRMED = flag('TEST_OWN_CONTACTS_CONFIRMED')
BALANCE_ANCHOR_DATE = value('BALANCE_ANCHOR_DATE', '2026-09-15')
BALANCE_ANCHOR_PRINCIPAL_COP = float(value('BALANCE_ANCHOR_PRINCIPAL_COP', '268019128.13'))
MONTHLY_RATE = float(value('MONTHLY_RATE', '0.05'))
DAYS_IN_MONTH_BASIS = int(value('DAYS_IN_MONTH_BASIS', '30'))
CAPITALIZATION_DAY = int(value('CAPITALIZATION_DAY', '15'))
CALL_RING_TIMEOUT = 30
POLL_SECONDS = 5
OBSERVE_SECONDS = 180

def validate(live=False):
    if TEST_END_DATE < TEST_START_DATE:
        raise ValueError('TEST_END_DATE debe ser igual o posterior a TEST_START_DATE')
    anchor = date.fromisoformat(BALANCE_ANCHOR_DATE)
    if anchor.day != 15 or CAPITALIZATION_DAY != 15 or anchor > TEST_START_DATE:
        raise ValueError('El corte ancla debe ser un día 15 anterior a la prueba')
    if not all(math.isfinite(n) for n in (BALANCE_ANCHOR_PRINCIPAL_COP, MONTHLY_RATE)):
        raise ValueError('Saldo/tasa deben ser finitos')
    if BALANCE_ANCHOR_PRINCIPAL_COP <= 0 or MONTHLY_RATE < 0 or DAYS_IN_MONTH_BASIS <= 0:
        raise ValueError('Revisa capital, tasa y base de días')
    if flag('SMS_ENABLED', 'false'):
        raise ValueError('SMS permanece deshabilitado en esta copia')
    if not live:
        return
    if DRY_RUN:
        raise ValueError('Para los envíos reales configura DRY_RUN=false')
    if not OWN_CONTACTS_CONFIRMED:
        raise ValueError('Configura tus propios destinos y TEST_OWN_CONTACTS_CONFIRMED=true')
    if TWILIO_TRIAL_MODE or not WHATSAPP_ENABLED:
        raise ValueError('Requiere TWILIO_TRIAL_MODE=false y WHATSAPP_ENABLED=true')
    for name in ('TEST_PHONE', 'TEST_WHATSAPP', 'TWILIO_PHONE_NUMBER', 'WHATSAPP_SENDER'):
        if not re.fullmatch(r'\+[1-9]\d{7,14}', globals()[name]):
            raise ValueError(f'{name}: usa un número E.164 propio/sender, sin prefijo whatsapp:')
    for name, prefix in (('TWILIO_ACCOUNT_SID', 'AC'), ('WHATSAPP_CONTENT_SID', 'HX')):
        if not re.fullmatch(prefix + r'[0-9a-fA-F]{32}', globals()[name]):
            raise ValueError(f'{name}: SID inválido')
    if not TWILIO_AUTH_TOKEN or not GMAIL_APP_PASSWORD:
        raise ValueError('Faltan credenciales Twilio/Gmail en el .env temporal')
    for name in ('TEST_EMAIL', 'GMAIL_USER'):
        if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', globals()[name]):
            raise ValueError(f'{name}: correo inválido')

def check_window(slot, now=None):
    now = (now or now_colombia()).astimezone(COLOMBIA)
    if slot not in PLAN:
        raise ValueError('Franja desconocida')
    day = now.date()
    if not TEST_START_DATE <= day <= TEST_END_DATE:
        raise ValueError(f'Fuera del período {TEST_START_DATE} a {TEST_END_DATE} (Colombia); no se envía nada')
    start = datetime.combine(day, datetime.min.time(), COLOMBIA).replace(hour=SLOT_HOURS[slot])
    if not start <= now < start + timedelta(minutes=WINDOW_MINUTES):
        raise ValueError(f'Fuera de la franja {slot} del {day.isoformat()} (Colombia); no se envía nada')
    return day

