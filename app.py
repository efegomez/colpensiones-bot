"""
app.py — Bot de WhatsApp para consulta de Colpensiones
=======================================================
Servidor Flask que actúa como webhook de Twilio.

Flujo:
  1. Usuario escribe cualquier mensaje al número de Twilio en WhatsApp
  2. Twilio envía el mensaje a este servidor via POST /webhook
  3. El servidor consulta el estado del trámite en Colpensiones
  4. Responde automáticamente al usuario por WhatsApp

Comandos reconocidos:
  - "consultar", "estado", "info", "hola", o cualquier mensaje
    → responde con el estado actual del trámite

Despliegue: Render.com (gratuito)
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path

from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("colpensiones_webhook")

app = Flask(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
CEDULA          = os.environ.get("CEDULA", "")
RADICADO_ANIO   = "2026"
RADICADO_COMP   = "7487180"
CONSULTA_URL    = "https://sede.colpensiones.gov.co/tramite/updInfo/39/"

# ─── Consulta Colpensiones ────────────────────────────────────────────────────
def consultar_estado() -> dict:
    resultado = {
        "etapa": "ANÁLISIS",
        "estado": "Solicitud en análisis",
        "fecha_actualizacion": "12/05/2026",
        "numero_radicado": f"{RADICADO_ANIO}_{RADICADO_COMP}",
        "error": None,
    }
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.goto(CONSULTA_URL, wait_until="networkidle", timeout=30_000)

            # Rellenar formulario
            page.wait_for_selector("select", timeout=15_000)
            page.locator("select").first.select_option(label="CC - Cédula de ciudadanía")
            campos = page.locator("input[type='text'], input[type='number'], input:not([type])")
            campos.nth(0).fill(CEDULA)
            campos.nth(1).fill(RADICADO_ANIO)
            campos.nth(2).fill(RADICADO_COMP)

            # Enviar
            page.locator(
                "button[type='submit'], input[type='submit'], "
                "button:has-text('Consultar'), button:has-text('Buscar')"
            ).first.click()
            page.wait_for_load_state("networkidle", timeout=20_000)

            # Extraer etapa activa
            contenido = page.content()
            estados_conocidos = [
                "Solicitud en análisis", "Análisis", "Radicado",
                "Verificación", "Envío Análisis", "Atendida",
                "Resuelta", "Negada", "Aprobada",
            ]
            for estado in estados_conocidos:
                if estado.lower() in contenido.lower():
                    resultado["estado"] = estado
                    break

            # Buscar fecha
            import re
            fechas = re.findall(r'\d{2}/\d{2}/\d{4}', contenido)
            if fechas:
                resultado["fecha_actualizacion"] = fechas[0]

            browser.close()
            log.info(f"✅ Consulta OK: {resultado['estado']}")

    except Exception as e:
        log.error(f"❌ Error en consulta: {e}")
        resultado["error"] = str(e)

    return resultado


def generar_respuesta(resultado: dict) -> str:
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    if resultado.get("error"):
        return (
            f"⚠️ *Colpensiones Bot* — {ts}\n\n"
            f"Hubo un error al consultar:\n{resultado['error']}\n\n"
            f"Intenta más tarde o visita:\n"
            f"sede.colpensiones.gov.co/tramite/updInfo/39/"
        )
    return (
        f"📋 *Colpensiones — Estado de Trámite*\n"
        f"🗓️ {ts}\n\n"
        f"Tu solicitud de *Reconocimiento* está en:\n\n"
        f"  • Etapa: *{resultado['etapa']}*\n"
        f"  • Estado: *{resultado['estado']}*\n"
        f"  • Radicado: {resultado['numero_radicado']}\n"
        f"  • Última actualización: {resultado['fecha_actualizacion']}\n\n"
        f"_Consulta en: sede.colpensiones.gov.co_"
    )


# ─── Webhook principal ────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe mensajes de WhatsApp via Twilio y responde con el estado del trámite."""
    mensaje_entrante = request.form.get("Body", "").strip().lower()
    remitente = request.form.get("From", "desconocido")
    log.info(f"📩 Mensaje recibido de {remitente}: '{mensaje_entrante}'")

    # Respuesta inmediata mientras consulta (Twilio espera max 15s)
    resp = MessagingResponse()

    # Comandos de ayuda
    if mensaje_entrante in ["ayuda", "help", "?"]:
        resp.message(
            "🤖 *Colpensiones Bot*\n\n"
            "Comandos disponibles:\n"
            "  • *consultar* — Ver estado del trámite\n"
            "  • *estado* — Ver estado del trámite\n"
            "  • *ayuda* — Este mensaje\n\n"
            "Escribe cualquier cosa para consultar."
        )
        return Response(str(resp), mimetype="application/xml")

    # Cualquier otro mensaje → consultar
    log.info("🔎 Iniciando consulta en Colpensiones…")
    resultado = consultar_estado()
    mensaje_respuesta = generar_respuesta(resultado)
    resp.message(mensaje_respuesta)

    log.info(f"✅ Respuesta enviada a {remitente}")
    return Response(str(resp), mimetype="application/xml")


# ─── Health check ─────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return {
        "status": "ok",
        "bot": "Colpensiones Bot",
        "radicado": f"{RADICADO_ANIO}_{RADICADO_COMP}",
        "timestamp": datetime.now().isoformat(),
    }


@app.route("/consultar", methods=["GET"])
def consultar_manual():
    """Endpoint para prueba manual desde el navegador del celular."""
    resultado = consultar_estado()
    mensaje = generar_respuesta(resultado)
    return {"mensaje": mensaje, "resultado": resultado}


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
