from num2words import num2words
from balance import calculate_balance, format_cop


MONTHS_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def vars(as_of=None):
    b = calculate_balance(as_of)
    d = b["as_of"]

    return {
        "date": d.strftime("%d/%m/%Y"),
        "date_voice": (
            f"{d.day} de "
            f"{MONTHS_ES[d.month]} de "
            f"{d.year}"
        ),
        "principal": format_cop(b["principal"]),
        "interest": format_cop(b["accrued_interest"]),
        "total": format_cop(b["total_balance"]),
        "total_raw": b["total_balance"],
    }


def money_to_voice(value):
    pesos = round(value)
    return f"{num2words(pesos, lang='es')} pesos colombianos"


def sms_text():
    v = vars()

    return (
        "Buen día. "
        "Este es un mensaje de seguimiento al saldo pendiente con Gustavo Marín. "
        f"Con corte al {v['date']}: "
        f"capital vigente {v['principal']}; "
        f"interés causado {v['interest']}; "
        f"saldo total actualizado {v['total']}. "
        "Agradezco confirmar el estado del pago "
        "o una fecha concreta de cumplimiento. "
        "Gracias."
    )


def call_text(as_of=None):
    v = vars(as_of)

    return (
        "Buen día. "
        "Esta es una llamada de seguimiento al saldo pendiente con Gustavo Marín. "
        f"Con corte al {v['date_voice']}, "
        f"el saldo total actualizado es de "
        f"{money_to_voice(v['total_raw'])}. "
        "Agradezco confirmar el estado del pago  "
        "o una fecha concreta de cumplimiento. "
        "Gracias."
    )


def email_subject():
    return "Seguimiento de saldo pendiente"


def email_body(as_of=None):
    v = vars(as_of)

    return f"""Buen día,

Este es un mensaje de seguimiento al saldo pendiente con Gustavo Marín.

Con corte al {v['date']}:

Capital vigente: {v['principal']}
Interés causado: {v['interest']}
Saldo total actualizado: {v['total']}

Agradezco confirmar el estado del pago o una fecha concreta de cumplimiento.

Gracias.
"""


def whatsapp_content_variables(as_of=None):
    v = vars(as_of)

    return {
        "1": v["date"],
        "2": v["principal"],
        "3": v["interest"],
        "4": v["total"],
    }
