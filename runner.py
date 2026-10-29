import argparse
from datetime import date
import json
import logging
from logging.handlers import RotatingFileHandler
import time
import config
import db
import channels
import messages
from balance import calculate_balance, format_cop

LOGGER = logging.getLogger('cobranza_temp')
TERMINAL = {'calls': {'completed', 'busy', 'no-answer', 'failed', 'canceled'},
            'whatsapp': {'delivered', 'read', 'failed', 'undelivered', 'canceled'}}

def setup_logging():
    if LOGGER.handlers:
        return
    folder = config.ROOT / 'logs'
    folder.mkdir(exist_ok=True)
    handler = RotatingFileHandler(folder / 'test.log', maxBytes=1000000, backupCount=2, encoding='utf-8')
    # El instante ISO Colombia se incluye en cada evento, independientemente del host.
    handler.setFormatter(logging.Formatter('%(message)s'))
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(handler)
    LOGGER.addHandler(logging.StreamHandler())

def log(status, **detail):
    LOGGER.info(json.dumps({'at': db.timestamp(), 'status': status, **detail}, ensure_ascii=False, default=str))

def error_detail(exc):
    # No guardar contraseñas, cuerpos HTTP ni direcciones de contacto en errores.
    return {'error_type': type(exc).__name__, 'provider_code': getattr(exc, 'code', None)}

def preview(slot, day=None):
    config.validate()
    day = day or config.TEST_START_DATE
    b = calculate_balance(day, persist=False)
    print(f'Vista previa {slot}, {day.isoformat()} Colombia: {", ".join(config.PLAN[slot])}; SMS=0')
    print(f'Capital: {format_cop(b["principal"])}; interés: {format_cop(b["accrued_interest"])}; total: {format_cop(b["total_balance"])}')
    # vars() permite una fecha explícita exclusivamente para mostrar el mensaje de mañana.
    print(messages.call_text(day))
    if 'whatsapp' in config.PLAN[slot]:
        print('WhatsApp variables:', json.dumps(messages.whatsapp_content_variables(day), ensure_ascii=False))
    if 'email' in config.PLAN[slot]:
        print(messages.email_body(day))
    print('No se envía nada ni se reservan intentos.')

def observe(rows, seconds=None):
    seconds = config.OBSERVE_SECONDS if seconds is None else seconds
    deadline = time.monotonic() + seconds
    pending = {r['id']: r for r in rows if r['external_id'] and r['channel'] in TERMINAL
               and (seconds == 0 or r['status'] not in TERMINAL[r['channel']])}
    failed = False
    while pending:
        for attempt_id, row in list(pending.items()):
            try:
                status, detail = channels.fetch_status(row['channel'], row['external_id'])
                if status != row['status']:
                    db.update(attempt_id, status, detail=detail)
                    log(status, slot=row['slot'], channel=row['channel'], attempt_id=attempt_id, **detail)
                    row = dict(row, status=status)
                    pending[attempt_id] = row
                if status in TERMINAL[row['channel']]:
                    # Actualiza duración final incluso si el estado no cambió.
                    db.update(attempt_id, status, detail=detail)
                    if status in {'failed', 'undelivered'}:
                        failed = True
                    del pending[attempt_id]
            except Exception as exc:
                detail = error_detail(exc)
                # Conserva el último estado del proveedor y el SID para refresh posterior.
                db.update(attempt_id, row['status'], detail={'observation_error': detail})
                log('observation_error', attempt_id=attempt_id, **detail)
                failed = True
                del pending[attempt_id]
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(min(config.POLL_SECONDS, max(0, deadline - time.monotonic())))
    for row in pending.values():
        db.update(row['id'], row['status'], detail={'observation_pending': True})
        log('observation_pending', attempt_id=row['id'], channel=row['channel'])
    return failed

def execute(slot):
    setup_logging()
    try:
        config.validate(live=True)
        config.check_window(slot)
    except ValueError as exc:
        log('blocked', slot=slot, reason=str(exc))
        return 2
    db.init_db()
    day = config.now_colombia().date()
    rows = [r for r in db.attempts() if r['test_date'] == day.isoformat() and r['slot'] == slot]
    if set(config.PLAN[slot]).issubset({r['channel'] for r in rows}):
        log('already_attempted', slot=slot, test_date=day.isoformat())
        return 0
    calculate_balance(day, persist=True)
    errors = False
    for channel in config.PLAN[slot]:
        # Revisa la hora antes de cada contacto, incluso tras un fallo lento.
        try:
            config.check_window(slot)
        except ValueError as exc:
            log('blocked', slot=slot, channel=channel, reason=str(exc))
            errors = True
            continue
        attempt_id = db.claim(slot, channel)
        if attempt_id is None:
            log('duplicate_skipped', slot=slot, channel=channel)
            continue
        log('reserved', slot=slot, channel=channel, attempt_id=attempt_id)
        try:
            result = channels.DISPATCH[channel](slot)
            db.update(attempt_id, result['status'], result.get('external_id'))
            if result['status'] in {'failed', 'undelivered'}:
                errors = True
            log(result['status'], slot=slot, channel=channel, attempt_id=attempt_id,
                external_id=result.get('external_id'))
        except Exception as exc:
            detail = error_detail(exc)
            db.update(attempt_id, 'dispatch_error_or_unknown', detail=detail)
            log('dispatch_error_or_unknown', slot=slot, channel=channel, attempt_id=attempt_id, **detail)
            errors = True
        # No break: cada canal autorizado de la franja tiene su propio intento.
    observation_failed = observe([r for r in db.attempts() if r['slot'] == slot and r['test_date'] == day.isoformat()])
    return 1 if errors or observation_failed else 0

def slot_main(slot):
    parser = argparse.ArgumentParser(description='Prueba controlada dentro del período configurado, hora Colombia')
    parser.add_argument('--test-date', help='Fecha exacta de esta tarea de Windows')
    parser.add_argument('--dry-run', action='store_true', help='Previsualizar sin red ni SQLite')
    args = parser.parse_args()
    expected = None
    if args.test_date:
        try:
            expected = date.fromisoformat(args.test_date)
        except ValueError:
            print('Fecha de tarea inválida; usa AAAA-MM-DD.')
            return 2
        if not config.TEST_START_DATE <= expected <= config.TEST_END_DATE:
            print('La fecha de esta tarea está fuera del período configurado; vuelve a crear las tareas.')
            return 2
    if args.dry_run or config.DRY_RUN:
        preview(slot, expected)
        return 0
    if expected is not None and expected != config.now_colombia().date():
        print('Esta tarea corresponde a otro día; no se envía nada.')
        return 2
    return execute(slot)

