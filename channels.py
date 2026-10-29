"""Sólo llamadas, WhatsApp y email a destinos TEST_*. Nunca SMS."""
import json
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from xml.sax.saxutils import escape
from twilio.rest import Client
from twilio.http.http_client import TwilioHttpClient
import config
import messages

def client():
    # Sin reintentos de POST: una respuesta perdida no debe duplicar un contacto.
    return Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN,
                  http_client=TwilioHttpClient(timeout=20, max_retries=0))

def guard(slot, channel):
    config.validate(live=True)
    if slot.startswith('manual_') and channel in DISPATCH:
        return
    config.check_window(slot)
    if channel not in config.PLAN[slot]:
        raise ValueError('Canal no autorizado para esta franja')

def make_call(slot):
    guard(slot, 'calls')
    text = escape(messages.call_text())
    c = client().calls.create(to=config.TEST_PHONE, from_=config.TWILIO_PHONE_NUMBER,
        timeout=config.CALL_RING_TIMEOUT,
        twiml=f'<Response><Say language="es-MX">{text}</Say></Response>')
    return {'status': c.status or 'queued', 'external_id': c.sid}

def send_whatsapp(slot):
    guard(slot, 'whatsapp')
    m = client().messages.create(from_=f'whatsapp:{config.WHATSAPP_SENDER}',
        to=f'whatsapp:{config.TEST_WHATSAPP}', content_sid=config.WHATSAPP_CONTENT_SID,
        content_variables=json.dumps(messages.whatsapp_content_variables(), ensure_ascii=False))
    return {'status': m.status or 'queued', 'external_id': m.sid}

def send_email(slot):
    guard(slot, 'email')
    msg = EmailMessage()
    msg['Subject'] = messages.email_subject()
    msg['From'] = config.GMAIL_USER
    msg['To'] = config.TEST_EMAIL
    msg['Message-ID'] = make_msgid()
    msg.set_content(messages.email_body())
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=20) as s:
        s.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        refused = s.send_message(msg)
        if refused:
            raise RuntimeError('SMTP rechazó el destinatario')
    return {'status': 'smtp_accepted', 'external_id': msg['Message-ID']}

def fetch_status(channel, external_id):
    if channel == 'calls':
        c = client().calls(external_id).fetch()
        return c.status, {'duration_seconds': c.duration, 'answered_by': c.answered_by,
                          'start_time': c.start_time, 'end_time': c.end_time}
    if channel == 'whatsapp':
        m = client().messages(external_id).fetch()
        return m.status, {'error_code': m.error_code}
    raise ValueError('Sólo se consulta Twilio para llamadas/WhatsApp')

DISPATCH = {'calls': make_call, 'whatsapp': send_whatsapp, 'email': send_email}

