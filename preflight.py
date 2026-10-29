"""Valida localmente y muestra mensajes; no hace conexiones ni envía contactos."""
import argparse
import config
from runner import preview

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-live', action='store_true', help='Exigir configuración lista para envíos reales')
    args = parser.parse_args()
    try:
        config.validate(live=args.check_live)
        days = (config.TEST_END_DATE - config.TEST_START_DATE).days + 1
        print(f'Período inclusivo: {config.TEST_START_DATE} a {config.TEST_END_DATE}; {days} días, '
              f'{3 * days} llamadas, {days} WhatsApp, {days} email, 0 SMS.')
        for slot in config.PLAN:
            preview(slot)
        print('Configuración local válida. Sender/template deben comprobarse en la consola Twilio.')
        return 0
    except ValueError as exc:
        print(f'Configuración incompleta: {exc}')
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
