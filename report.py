import argparse
from datetime import datetime, timedelta
import config
import db
from runner import observe, setup_logging

def missing_attempts(rows, now=None):
    now = (now or config.now_colombia()).astimezone(config.COLOMBIA)
    recorded = {(r['test_date'], r['slot'], r['channel']) for r in rows}
    missing = []
    for day in config.test_days():
        if day > now.date():
            break
        for slot, hour in config.SLOT_HOURS.items():
            end = datetime.combine(day, datetime.min.time(), config.COLOMBIA).replace(hour=hour) + timedelta(minutes=config.WINDOW_MINUTES)
            if now < end:
                continue
            for channel in config.PLAN[slot]:
                key = (day.isoformat(), slot, channel)
                if key not in recorded:
                    missing.append(key)
    return missing

def print_missing(rows):
    for day, slot, channel in missing_attempts(rows):
        print(f'{day} {slot} {channel:8} NO_INICIADO: termino la ventana sin un intento programado registrado.')

def main():
    parser = argparse.ArgumentParser(description='Reporte de prueba; refresh sólo consulta estados existentes')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    if not db.DB_PATH.exists():
        print('Todavía no hay intentos reales registrados.')
        print_missing([])
        return 0
    if args.refresh:
        if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
            parser.error('Faltan credenciales Twilio para consultar estados')
        setup_logging()
        observe(db.attempts(), seconds=0)
    rows = db.attempts()
    for row in rows:
        print(f"{row['test_date']} {row['slot']} {row['channel']:8} {row['status']:25} SID/ID={row['external_id']} detalle={row['detail']}")
    print_missing(rows)
    print('SQLite:', db.DB_PATH)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
