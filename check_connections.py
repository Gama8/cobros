"""Comprueba servicios sin iniciar llamadas, enviar mensajes ni enviar emails."""
import json
import smtplib
import unicodedata
from twilio.base.exceptions import TwilioException
import config
from channels import client

def query(stage, action):
    print(f'twilio/{stage}: comprobando...')
    try:
        result = action()
    except Exception as exc:
        exc.check_stage = stage
        raise
    print(f'twilio/{stage}: OK')
    return result

def error_info(exc):
    detail = {'ok': False, 'error_type': type(exc).__name__,
              'provider_code': getattr(exc, 'code', getattr(exc, 'smtp_code', None)),
              'stage': getattr(exc, 'check_stage', 'validation')}
    reason = str(exc) if isinstance(exc, ValueError) else None
    if isinstance(exc, TwilioException):
        reason = getattr(exc, 'msg', None) or (exc.args[0] if exc.args and isinstance(exc.args[0], str) else 'Error de Twilio')
        for arg in exc.args:
            if hasattr(arg, 'status_code'):
                detail['http_status'] = arg.status_code
                try:
                    payload = json.loads(arg.text)
                    if isinstance(payload, dict):
                        detail['provider_code'] = payload.get('code', detail['provider_code'])
                        reason = payload.get('message') or reason
                except (ValueError, TypeError, AttributeError):
                    pass
    if reason:
        reason = str(reason)
        for secret in (config.TWILIO_AUTH_TOKEN, config.GMAIL_APP_PASSWORD, config.TWILIO_ACCOUNT_SID,
                       config.TEST_PHONE, config.TEST_WHATSAPP, config.TEST_EMAIL, config.GMAIL_USER):
            if secret:
                reason = reason.replace(secret, '[oculto]')
        detail['reason'] = reason[:1000]
    return detail

def check_twilio():
    provider = client()
    account = query('account', lambda: provider.api.accounts(config.TWILIO_ACCOUNT_SID).fetch())
    if account.status != 'active' or str(account.type).lower() != 'full':
        raise ValueError('La cuenta Twilio debe estar activa y fuera de trial')
    numbers = query('voice_numbers', lambda: provider.incoming_phone_numbers.list(phone_number=config.TWILIO_PHONE_NUMBER, limit=20))
    voice_number = any((n.capabilities or {}).get('voice') for n in numbers)
    if not voice_number:
        verified = query('verified_caller_id', lambda: provider.outgoing_caller_ids.list(phone_number=config.TWILIO_PHONE_NUMBER, limit=20))
        if not verified:
            raise ValueError('El Caller ID no figura como número Voice ni número verificado en Twilio')
    senders = query('whatsapp_sender', lambda: provider.messaging.v2.channels_senders.list(channel='whatsapp', limit=1000))
    sender = next((s for s in senders if s.sender_id == f'whatsapp:{config.WHATSAPP_SENDER}'), None)
    if sender is None or str(sender.status).upper() != 'ONLINE':
        raise ValueError('El sender WhatsApp configurado no figura ONLINE en la cuenta Twilio')
    content = provider.content.v1.contents(config.WHATSAPP_CONTENT_SID)
    template = query('template', content.fetch)
    approval = query('template_approval', lambda: content.approval_fetch().fetch())
    if str((approval.whatsapp or {}).get('status', '')).lower() != 'approved':
        raise ValueError('La plantilla WhatsApp no figura aprobada')
    if set(template.variables or {}) != {'1', '2', '3', '4'}:
        raise ValueError('La plantilla debe usar las variables 1, 2, 3 y 4 del saldo')
    body = ' '.join(str(t.get('body', '')) for t in (template.types or {}).values() if isinstance(t, dict))
    body = unicodedata.normalize('NFC', body).lower()
    if 'saldo pendiente con gustavo marín' not in body:
        raise ValueError('La plantilla no contiene la referencia al saldo pendiente con Gustavo Marín')
    return {'account': 'active', 'voice_sender': 'available', 'whatsapp_sender': 'ONLINE', 'template': 'approved'}

def check_gmail():
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=20) as smtp:
        smtp.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
    return {'smtp_login': 'ok'}

def main():
    config.validate(live=True)
    results = {'checked_at': config.now_colombia().isoformat(),
               'start_date': config.TEST_START_DATE.isoformat(), 'end_date': config.TEST_END_DATE.isoformat(), 'checks': {}}
    failed = False
    for name, check in (('twilio', check_twilio), ('gmail', check_gmail)):
        try:
            results['checks'][name] = {'ok': True, **check()}
            print(f'{name}: OK (comprobación sin envíos)')
        except Exception as exc:
            detail = error_info(exc)
            results['checks'][name] = detail
            print(f'{name}: FALLÓ en {detail["stage"]}. {detail.get("reason", "Revisa credenciales/conexión")} Código: {detail["provider_code"]}; tipo: {detail["error_type"]}')
            failed = True
    folder = config.ROOT / 'logs'
    folder.mkdir(exist_ok=True)
    (folder / 'connection_checks.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    return 1 if failed else 0

if __name__ == '__main__':
    raise SystemExit(main())
