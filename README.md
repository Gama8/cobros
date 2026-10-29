# cobranza_bot_v5_temp

Prueba controlada a medios de contacto propios. Conserva el cálculo dinámico del saldo y los mensajes de seguimiento al «saldo pendiente con Gustavo Marín». SMS deshabilitado.

| Hora de Colombia | Contactos por día |
|---|---|
| 09:00 | 1 llamada + 1 WhatsApp |
| 12:00 | 1 llamada |
| 15:00 | 1 llamada + 1 email |

Los dos extremos de `TEST_START_DATE` y `TEST_END_DATE` están incluidos, también fines de semana. El código funciona en Python 3.10 o posterior; la programación automática usa Windows Task Scheduler y PowerShell 5.1 o posterior.

## Instalar en otro equipo Windows

1. Instala Git y Python. Clona este repositorio en su ubicación definitiva y abre PowerShell dentro de esa carpeta. No copies la `.venv` del equipo anterior.
2. Ejecuta:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\instalar.ps1
```

El instalador crea una `.venv`, instala las dependencias y copia `.env.example` a `.env` si no existe. No programa tareas ni hace envíos. Si necesitas seleccionar Python:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\instalar.ps1 -BasePython 'C:\Ruta\Python\python.exe'
```

3. Configura el `.env` local. Puedes copiar de forma privada tu `.env` de prueba al nuevo equipo. Nunca lo subas a Git. Los campos necesarios son:

| Variables | Uso |
|---|---|
| `TEST_START_DATE`, `TEST_END_DATE` | Fechas literales `AAAA-MM-DD`; no admiten `today()` |
| `TEST_PHONE`, `TEST_WHATSAPP`, `TEST_EMAIL` | Tus propios destinos; WhatsApp vacío usa `TEST_PHONE` |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Credenciales Twilio |
| `TWILIO_PHONE_NUMBER` | Número Voice o Caller ID verificado |
| `WHATSAPP_SENDER`, `WHATSAPP_CONTENT_SID` | Sender registrado y plantilla aprobada |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD` | Emisor Gmail y contraseña de aplicación |
| `BALANCE_ANCHOR_DATE`, `BALANCE_ANCHOR_PRINCIPAL_COP` | Corte y capital de referencia |
| `MONTHLY_RATE`, `DAYS_IN_MONTH_BASIS`, `CAPITALIZATION_DAY` | Parámetros del cálculo; capitalización el día 15 |

Mantén `SMS_ENABLED=false`, `WHATSAPP_ENABLED=true` y `TWILIO_TRIAL_MODE=false`. Usa números E.164 (`+57...`) sin prefijo `whatsapp:` en el `.env`.

El ejemplo empieza con `DRY_RUN=true` y `TEST_OWN_CONTACTS_CONFIRMED=false`. Cambia las fechas de ejemplo por el período que quieras probar. Con `DRY_RUN=true` las pruebas sólo muestran mensajes. Para habilitar envíos reales a tus propios medios, configura `DRY_RUN=false` y `TEST_OWN_CONTACTS_CONFIRMED=true`.

## Revisar y programar

Desde la carpeta del repositorio:

```powershell
# Vista previa local, sin contactos ni reservas en SQLite:
& .\.venv\Scripts\python.exe -B .\test_0900.py --dry-run
& .\.venv\Scripts\python.exe -B .\test_1200.py --dry-run
& .\.venv\Scripts\python.exe -B .\test_1500.py --dry-run

# Registrar y verificar las franjas futuras del .env:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\programar_periodo.ps1
```

`programar_periodo.ps1` valida la configuración, comprueba Twilio/Gmail sin enviar contactos, registra tres tareas por día futuro y comprueba el auxiliar de energía. Sólo muestra `LISTO` al terminar las verificaciones. Si Windows deniega acceso al Programador, ejecútalo desde PowerShell como administrador con la misma cuenta que dejará la sesión iniciada.

Las rutas se calculan desde la carpeta clonada. Cada tarea usa el Python de su `.venv`, una fecha exacta y horas de Colombia, convertidas a la zona de Windows. Si cambias las fechas del `.env`, vuelve a ejecutar `programar_periodo.ps1`. Si mueves la carpeta, recrea `.venv` y vuelve a programar.

Deja el PC encendido, con corriente, Internet y tu sesión iniciada; puedes bloquearla y cerrar PowerShell. El auxiliar intenta evitar la suspensión automática hasta las 15:15 del último día; no permite ejecutar contactos con el equipo apagado ni garantiza ejecución tras una suspensión manual. Se reactiva al iniciar sesión dentro del período.

### Trasladar la automatización desde el equipo anterior

Programa los envíos en **un solo equipo a la vez**. Antes de activar el nuevo, elimina o deshabilita las tareas temporales del equipo anterior. Cada instalación tiene su propia SQLite: el control de duplicados no se comparte entre computadoras. Un clon nuevo tampoco contiene los intentos ya hechos el mismo día; empieza después de la última franja de ese día o en una fecha futura.

Este repositorio no incluye `.env`, credenciales, números de destino, bases de datos ni logs. Conserva el cálculo y los parámetros financieros de ejemplo del proyecto. Copiar código no traslada las tareas de Windows ni el historial; tampoco modifica la v5 de producción.

## Sender y plantilla de WhatsApp

En Twilio Console verifica el sender de WhatsApp `ONLINE` y la plantilla aprobada de la misma cuenta. El texto debe incluir «saldo pendiente con Gustavo Marín» y las variables `1=fecha`, `2=capital`, `3=interés`, `4=saldo total`. No uses el sandbox como sustituto del sender configurado.

```powershell
# Sólo comprueba autenticación y configuración del proveedor; no envía contactos:
& .\.venv\Scripts\python.exe -B .\check_connections.py
```

## Consultar resultados

```powershell
& .\.venv\Scripts\python.exe -B .\report.py
# Consulta y actualiza estados de SID existentes; no vuelve a enviar:
& .\.venv\Scripts\python.exe -B .\report.py --refresh
Get-Content -LiteralPath .\logs\test.log -Tail 40
```

SQLite está en `data/test_results.sqlite3`. Registra fecha, franja, canal, SID, estados y saldo calculado. Reserva cada contacto antes del envío; repetir el arranque no reenvía un contacto reservado, incluso si quedó fallido o incierto. No borres `data` para reintentar. Windows repite el arranque cada minuto durante 9 minutos y 30 segundos; Python limita cada franja a diez minutos y bloquea fechas incorrectas. No recupera franjas vencidas automáticamente.

- `ringing`: Twilio reportó timbrado; no garantiza que el celular haya sonado físicamente.
- `no-answer`: no se registró una conexión contestada o se rechazó la llamada.
- `completed`: hubo conexión y terminó; puede ser persona o buzón. No está activada la detección de contestador y `answered_by` puede estar vacío.
- WhatsApp `delivered` confirma entrega; `sent` sólo envío. `read` depende de los recibos del destinatario.
- Email `smtp_accepted` confirma aceptación por el servidor, no lectura ni llegada a la bandeja de entrada.
- `dispatch_error_or_unknown` o `reserved` tras una interrupción necesitan revisión en el proveedor antes de asumir que no hubo contacto.

## Pruebas manuales y eliminación de tareas

```powershell
# Son pruebas adicionales, independientes de los envíos programados:
& .\.venv\Scripts\python.exe -B .\test_now.py --channel calls --run-id prueba1
& .\.venv\Scripts\python.exe -B .\test_now.py --channel whatsapp --run-id prueba1
# Mismo ID/canal/día evita repetir esa prueba manual. No deduplica contra franjas programadas.

# Ver qué tareas temporales se eliminarían y luego eliminarlas:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\remove_tasks.ps1 -WhatIf
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\remove_tasks.ps1
# También admite -StartDate AAAA-MM-DD -EndDate AAAA-MM-DD para otro período.
```

Eliminar tareas conserva la base de datos y los logs. El repositorio no activa envíos por clonarlo o instalar dependencias. Los scripts de programación y energía están limitados a la copia de prueba.

## Verificaciones sin contactos reales

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Las pruebas simulan proveedores, reloj y bases temporales. No registran tareas reales ni usan las credenciales para hacer envíos. El saldo se capitaliza cada día 15; entre cortes se calcula el interés diario con los parámetros del `.env`.
