"""
app.py — Bot de WhatsApp para consulta de Colpensiones
=======================================================
Servidor Flask + webhook Twilio. Sin Playwright — usa requests.
"""

import os
import re
import logging
from datetime import datetime
from threading import Thread

import requests
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("colpensiones_bot")

app = Flask(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
CEDULA              = os.environ.get("CEDULA", "")
TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM         = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
RADICADO_ANIO       = "2026"
RADICADO_COMP       = "7487180"

# Estado más reciente conocido (respaldo si el portal no responde)
ULTIMO_ESTADO  = {
    "etapa": "ANÁLISIS",
    "estado": "Solicitud en análisis",
    "fecha": "12/05/2026",
    "radicado": f"{RADICADO_ANIO}_{RADICADO_COMP}",
    "fuente": "último registro conocido",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ─── Consulta por requests ────────────────────────────────────────────────────
def consultar_estado() -> dict:
    resultado = ULTIMO_ESTADO.copy()
    resultado["timestamp"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    try:
        session = requests.Session()
        session.headers.update(HEADERS)

        # GET para obtener la página y cookies/tokens
        url = "https://sede.colpensiones.gov.co/tramite/updInfo/39/"
        r_get = session.get(url, timeout=15)
        log.info(f"GET {url} → {r_get.status_code}")

        # Buscar en el HTML directamente con regex
        html = r_get.text
        texto = re.sub(r'<[^>]+>', ' ', html)  # quitar tags HTML

        # Buscar etapa y estado en el texto de respuesta
        etapas = [
            "ATENDIDA", "Atendida", "ANÁLISIS", "Análisis",
            "ENVÍO ANÁLISIS", "Envío Análisis", "VERIFICACIÓN",
            "Verificación", "RADICADO", "Radicado",
        ]
        for etapa in etapas:
            if etapa.lower() in texto.lower():
                resultado["etapa"] = etapa.upper()
                resultado["fuente"] = "portal en vivo"
                log.info(f"✅ Etapa encontrada: {etapa}")
                break

        estados = [
            "Solicitud en análisis", "Solicitud atendida",
            "En análisis", "Aprobada", "Negada", "Resuelta",
        ]
        for estado in estados:
            if estado.lower() in texto.lower():
                resultado["estado"] = estado
                resultado["fuente"] = "portal en vivo"
                log.info(f"✅ Estado encontrado: {estado}")
                break

        # Buscar fecha de actualización
        fechas = re.findall(r'\d{2}/\d{2}/\d{4}', texto)
        if fechas:
            resultado["fecha"] = fechas[0]
            log.info(f"✅ Fecha: {fechas[0]}")

    except Exception as e:
        log.warning(f"⚠️ Error en consulta live: {e} — usando último estado conocido")
        resultado["fuente"] = "último estado conocido (error de conexión)"

    return resultado


# ─── Generación del mensaje ───────────────────────────────────────────────────
def generar_mensaje(r: dict) -> str:
    ts = r.get("timestamp", datetime.now().strftime("%d/%m/%Y %H:%M"))
    fuente = f"\n_Fuente: {r['fuente']}_" if r.get("fuente") else ""
    return (
        f"📋 *Colpensiones — Estado de Trámite*\n"
        f"🗓️ {ts}\n\n"
        f"Tu solicitud de *Reconocimiento* está en:\n\n"
        f"  • Etapa: *{r['etapa']}*\n"
        f"  • Estado: *{r['estado']}*\n"
        f"  • Radicado: {r['radicado']}\n"
        f"  • Última actualización: {r['fecha']}"
        f"{fuente}\n\n"
        f"_Consulta: sede.colpensiones.gov.co_"
    )


# ─── Envío asíncrono ──────────────────────────────────────────────────────────
def consultar_y_enviar(destino: str):
    """Corre en segundo plano: consulta y envía el resultado por Twilio REST."""
    try:
        resultado = consultar_estado()
        mensaje   = generar_mensaje(resultado)
        client    = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(body=mensaje, from_=TWILIO_FROM, to=destino)
        log.info(f"✅ Resultado enviado a {destino} | SID: {msg.sid}")
    except Exception as e:
        log.error(f"❌ Error enviando resultado: {e}")


# ─── Webhook WhatsApp ─────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    entrante  = request.form.get("Body", "").strip().lower()
    remitente = request.form.get("From", "?")
    log.info(f"📩 Mensaje de {remitente}: '{entrante}'")

    resp = MessagingResponse()

    if entrante in ["ayuda", "help", "?"]:
        resp.message(
            "🤖 *Colpensiones Bot*\n\n"
            "Escríbeme cualquier cosa y te digo el estado de tu trámite.\n"
            "Ejemplo: *estado*, *consultar*, *hola*"
        )
        return Response(str(resp), mimetype="application/xml")

    # Responder de inmediato a Twilio (evita timeout de 15s)
    resp.message("🔍 Consultando tu trámite en Colpensiones...\n_Te respondo en unos segundos._")

    # Consulta en segundo plano → envía resultado cuando esté listo
    Thread(target=consultar_y_enviar, args=(remitente,), daemon=True).start()

    return Response(str(resp), mimetype="application/xml")


# ─── Health check ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return {"status": "ok", "bot": "Colpensiones Bot",
            "timestamp": datetime.now().isoformat()}


@app.route("/consultar", methods=["GET"])
def consultar_manual():
    r = consultar_estado()
    return {"estado": r, "mensaje": generar_mensaje(r)}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
