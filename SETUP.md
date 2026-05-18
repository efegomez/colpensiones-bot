# Configuración del Bot de Colpensiones

## Requisitos previos
- Python 3.9 o superior
- Cuenta en Twilio con WhatsApp habilitado (sandbox o número aprobado)
- Credenciales de Colpensiones

---

## Paso 1 — Instalar dependencias

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Paso 2 — Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con tus valores reales:

| Variable               | Descripción                                          |
|------------------------|------------------------------------------------------|
| `USER`                 | Usuario del portal Colpensiones                      |
| `PASSWORD`             | Contraseña del portal                                |
| `CEDULA`               | Cédula (opcional, si el módulo la requiere)          |
| `PHONE_NUMBER`         | Tu número WhatsApp destino (+57XXXXXXXXXX)           |
| `TWILIO_ACCOUNT_SID`   | Account SID desde console.twilio.com                 |
| `TWILIO_AUTH_TOKEN`    | Auth Token desde console.twilio.com                  |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+14155238886` (sandbox) o tu número Twilio |

---

## Paso 3 — Configurar Twilio WhatsApp Sandbox (pruebas)

1. Ve a https://console.twilio.com → Messaging → Try it out → Send a WhatsApp message
2. Desde tu WhatsApp, envía el mensaje que te indique Twilio al número sandbox
3. Ya puedes recibir mensajes de prueba

---

## Paso 4 — Ejecutar manualmente

```bash
python colpensiones_bot.py
```

Los logs se guardan en la carpeta `logs/`.

---

## Paso 5 — Automatizar con cron (Linux/Mac)

Ejecuta `crontab -e` y agrega una línea como:

```
# Todos los días a las 8:00 AM
0 8 * * * /usr/bin/python3 /ruta/completa/colpensiones_bot.py >> /ruta/completa/logs/cron.log 2>&1
```

En Windows usa el Programador de tareas o el script `ejecutar.bat`.

---

## Logs y evidencia

Cada ejecución genera en la carpeta `logs/`:
- `ejecucion_YYYYMMDD_HHMMSS.json` — resultado detallado en JSON
- `screenshot_YYYYMMDD_HHMMSS.png` — captura de pantalla de la última página visitada
