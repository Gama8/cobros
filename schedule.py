"""Calendario para PowerShell: salida JSON sin contactos ni credenciales."""
import json
import config

def schedule():
    config.validate()
    days = list(config.test_days())
    return {'start_date': config.TEST_START_DATE.isoformat(),
            'end_date': config.TEST_END_DATE.isoformat(), 'days': len(days),
            'launch_retry': {'interval_seconds': 60, 'duration_seconds': config.WINDOW_MINUTES * 60 - 30},
            'awake': {'name': f'CobranzaV5Temp_Awake_{config.TEST_START_DATE:%Y%m%d}_{config.TEST_END_DATE:%Y%m%d}',
                      'until': f'{config.TEST_END_DATE.isoformat()}T15:15:00-05:00'},
            'totals': {'calls': 3 * len(days), 'whatsapp': len(days), 'email': len(days), 'sms': 0},
            'tasks': [
                {'test_date': day.isoformat(), 'slot': slot,
                 'name': f'CobranzaV5Temp_{day:%Y%m%d}_{slot}',
                 'at': f'{day.isoformat()}T{config.SLOT_HOURS[slot]:02d}:00:00-05:00',
                 'script': f'test_{slot}.py'}
                for day in days for slot in config.PLAN]}

if __name__ == '__main__':
    print(json.dumps(schedule()))
