"""Prueba manual real inmediata a contactos propios. No modifica el calendario."""
import argparse
import json
import re
import uuid
import config
import db
import channels
import messages
from balance import calculate_balance
from runner import setup_logging, log, observe, error_detail

def execute_now(selected, run_id=None, dry_run=False):
    today = config.now_colombia().date()
    if selected not in ('calls', 'whatsapp', 'email', 'all'):
        raise ValueError('Canal desconocido')
    plan = tuple(channels.DISPATCH) if selected == 'all' else (selected,)
    if dry_run or config.DRY_RUN:
        config.validate()
        print(f'Prueba manual simulada {today}: {", ".join(plan)}. No se envía nada.')
        if 'calls' in plan:
            print(messages.call_text(today))
        if 'whatsapp' in plan:
            print(json.dumps(messages.whatsapp_content_variables(today), ensure_ascii=False))
        if 'email' in plan:
            print(messages.email_body(today))
        return 0
    config.validate(live=True)
    run_id = run_id or uuid.uuid4().hex
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', run_id):
        raise ValueError('run-id: usa letras, números, guion o guion bajo (máximo 64)')
    slot = 'manual_' + run_id
    setup_logging()
    db.init_db()
    calculate_balance(today, persist=True)
    log('manual_start', run_id=run_id, channels=plan)
    errors = False
    for channel in plan:
        attempt_id = db.claim(slot, channel)
        if attempt_id is None:
            log('duplicate_skipped', slot=slot, channel=channel)
            continue
        try:
            result = channels.DISPATCH[channel](slot)
            db.update(attempt_id, result['status'], result.get('external_id'))
            log(result['status'], slot=slot, channel=channel, attempt_id=attempt_id,
                external_id=result.get('external_id'))
            errors = errors or result['status'] in {'failed', 'undelivered'}
        except Exception as exc:
            detail = error_detail(exc)
            db.update(attempt_id, 'dispatch_error_or_unknown', detail=detail)
            log('dispatch_error_or_unknown', slot=slot, channel=channel, attempt_id=attempt_id, **detail)
            errors = True
    observation_failed = observe([r for r in db.attempts() if r['slot'] == slot and r['test_date'] == today.isoformat()])
    return 1 if errors or observation_failed else 0

def main():
    parser = argparse.ArgumentParser(description='Prueba manual ahora, sin esperar el período ni la franja')
    parser.add_argument('--channel', choices=('calls','whatsapp','email','all'), default='calls')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--run-id', help='Reutiliza este ID para evitar repetir el mismo intento manual en el día')
    args = parser.parse_args()
    try:
        return execute_now(args.channel, args.run_id, args.dry_run)
    except ValueError as exc:
        print(f'Configuración: {exc}')
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
