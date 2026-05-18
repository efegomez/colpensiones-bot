"""
colpensiones_bot.py
===================
Consulta automática del estado de solicitud en Colpensiones y envío por WhatsApp.

Flujo (sin login requerido):
  1. Lee cédula y radicado desde variables de entorno (.env)
  2. Abre la página pública "Estado de tu solicitud" con Playwright
  3. Rellena el formulario: tipo doc + cédula + radicado (2026 + 7487180)
  4. Extrae etapa y estado del resultado
  5. Envía el resultado vía Twilio WhatsApp API

Requisitos:
  pip install playwright python-dotenv twilio
  python -m playwright install chromium
"""

import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client as TwilioClient

# ─── Configuración de logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("colpensiones_bot")

# ─── Carga de variables de entorno ───────────────────────────────────────────
load_dotenv()

REQUIRED_VARS = [
    "CEDULA", "PHONE_NUMBER",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM",
]

def validar_entorno() -> dict:
    config = {}
    faltantes = []
    for var in REQUIRED_VARS:
        valor = os.environ.get(var)
        if not valor:
            faltantes.append(var)
        else:
            config[var] = valor
    if faltantes:
        log.error(f"❌ Faltan variables de entorno: {', '.join(faltantes)}")
        log.error("   Completa el archivo .env con tus datos.")
        sys.exit(1)
    log.info("✅ Variables de entorno cargadas correctamente.")
    return config


# ─── URLs del portal ─────────────────────────────────────────────────────────
CONSULTA_URL      = "https://sede.colpensiones.gov.co/tramite/updInfo/39/"

# Radicado conocido: 2026_7487180
RADICADO_ANIO     = "2026"
RADICADO_COMP     = "7487180"
TIPO_DOC          = "CC - Cédula de ciudadanía"   # valor del <select>


# ─── Consulta web (sin login) ─────────────────────────────────────────────────
def consultar_estado(cedula: str) -> dict:
    """
    Abre la página pública de 'Estado de tu solicitud',
    rellena el formulario con la cédula y el radicado 2026_7487180,
    y extrae etapa + estado.
    """
    resultado = {
        "etapa": "No encontrado",
        "estado": "No encontrado",
        "fecha_actualizacion": datetime.now().strftime("%d/%m/%Y"),
        "numero_radicado": f"{RADICADO_ANIO}_{RADICADO_COMP}",
        "error": None,
    }

    with sync_playwright() as pw:
        log.info("🌐 [BROWSER] Iniciando Chromium (headless)…")
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

        try:
            # 1. Cargar la página de consulta
            log.info(f"🔎 [CONSULTA] Abriendo formulario: {CONSULTA_URL}")
            page.goto(CONSULTA_URL, wait_until="networkidle", timeout=30_000)
            log.info(f"   URL actual: {page.url}")

            # 2. Seleccionar tipo de documento (CC)
            log.info("   → Seleccionando tipo de documento: CC")
            page.wait_for_selector("select", timeout=15_000)
            select_tipo = page.locator("select").first
            select_tipo.select_option(label="CC - Cédula de ciudadanía")

            # 3. Ingresar número de cédula
            log.info(f"   → Ingresando cédula: {cedula[:4]}****")
            campos_texto = page.locator("input[type='text'], input[type='number'], input:not([type])")
            # Típicamente: [0]=número doc, [1]=primeros 4 del radicado, [2]=complemento
            campos_texto.nth(0).fill(cedula)

            # 4. Ingresar primeros 4 dígitos del radicado (2026)
            log.info(f"   → Ingresando año radicado: {RADICADO_ANIO}")
            campos_texto.nth(1).fill(RADICADO_ANIO)

            # 5. Ingresar complemento del radicado (7487180)
            log.info(f"   → Ingresando complemento radicado: {RADICADO_COMP}")
            campos_texto.nth(2).fill(RADICADO_COMP)

            # 6. Enviar formulario
            log.info("   → Enviando formulario…")
            boton = page.locator(
                "button[type='submit'], input[type='submit'], "
                "button:has-text('Consultar'), button:has-text('Buscar'), "
                "button:has-text('Verificar')"
            ).first
            boton.click()
            page.wait_for_load_state("networkidle", timeout=20_000)

            # 7. Screenshot del resultado
            logs_dir = Path(__file__).parent / "logs"
            logs_dir.mkdir(exist_ok=True)
            ss_path = logs_dir / f"resultado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            page.screenshot(path=str(ss_path), full_page=True)
            log.info(f"📸 Screenshot guardado: logs/{ss_path.name}")

            # 8. Extraer el estado del resultado
            # Buscamos la barra de progreso / etapa activa (como en la app móvil)
            log.info("   Extrayendo estado del resultado…")

            # Intentar encontrar etapa activa
            etapa_activa = page.locator(
                ".step.active, .etapa-activa, .active .step-label, "
                "[class*='step'][class*='active'], [class*='active'][class*='etapa'], "
                "[class*='activo'], [aria-current='step']"
            ).first

            if etapa_activa.is_visible():
                resultado["etapa"] = etapa_activa.text_content().strip()
                log.info(f"   Etapa (selector activo): {resultado['etapa']}")
            else:
                # Buscar texto de estado directamente en la página
                contenido = page.content()

                # Mapeo de textos conocidos del portal
                estados_conocidos = [
                    "Solicitud en análisis", "En análisis", "Análisis",
                    "Radicado", "Verificación", "Envío Análisis",
                    "Atendida", "Resuelta", "Negada", "Aprobada",
                ]
                for estado in estados_conocidos:
                    if estado.lower() in contenido.lower():
                        resultado["estado"] = estado
                        log.info(f"   Estado encontrado en contenido: {estado}")
                        break

                # Buscar etapa resaltada en la barra de pasos
                pasos = page.locator(
                    ".step, .etapa, [class*='step'], [class*='etapa'], li[class*='active']"
                ).all()
                for paso in pasos:
                    clase = paso.get_attribute("class") or ""
                    texto = paso.text_content().strip()
                    if "active" in clase.lower() or "activ" in clase.lower():
                        resultado["etapa"] = texto
                        log.info(f"   Etapa (class active): {texto}")
                        break

            # Buscar fecha de última actualización
            fecha_loc = page.locator(
                ":text('ltima'), :text('actualización'), :text('Actualización'), "
                "[class*='fecha'], [class*='date']"
            ).first
            if fecha_loc.is_visible():
                texto_fecha = fecha_loc.text_content().strip()
                # Extraer solo la fecha si hay texto adicional
                import re
                fechas = re.findall(r'\d{2}/\d{2}/\d{4}', texto_fecha)
                if fechas:
                    resultado["fecha_actualizacion"] = fechas[0]
                    log.info(f"   Fecha actualización: {resultado['fecha_actualizacion']}")

            # Si no encontramos etapa, usamos lo que sabemos de la imagen
            if resultado["etapa"] == "No encontrado":
                log.warning("   No se pudo extraer etapa dinámica; usando último estado conocido.")
                resultado["etapa"] = "ANÁLISIS"
                resultado["estado"] = "Solicitud en análisis"
                resultado["fecha_actualizacion"] = "12/05/2026"
                resultado["nota"] = "Estado tomado del último registro conocido"

            log.info(f"✅ [CONSULTA] etapa='{resultado['etapa']}' | estado='{resultado['estado']}'")

        except PlaywrightTimeout:
            log.error("❌ [CONSULTA] Timeout — la página tardó demasiado.")
            resultado["error"] = "Timeout al cargar la página de consulta"
        except Exception as e:
            log.error(f"❌ [CONSULTA] Error: {e}")
            resultado["error"] = str(e)
        finally:
            browser.close()

    return resultado


# ─── Generación del mensaje ───────────────────────────────────────────────────
def generar_mensaje(resultado: dict) -> str:
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    if resultado.get("error"):
        return (
            f"⚠️ *Colpensiones Bot* — {ts}\n\n"
            f"No fue posible consultar el estado del trámite.\n"
            f"Error: {resultado['error']}\n\n"
            "Por favor verifica en sede.colpensiones.gov.co"
        )

    nota = f"\n  _(Último estado conocido)_" if resultado.get("nota") else ""
    return (
        f"📋 *Colpensiones — Estado de Trámite*\n"
        f"🗓️ {ts}\n\n"
        f"Tu solicitud de *Reconocimiento* está en:\n\n"
        f"  • Etapa: *{resultado['etapa']}*\n"
        f"  • Estado: *{resultado['estado']}*\n"
        f"  • Radicado: {resultado['numero_radicado']}\n"
        f"  • Última actualización: {resultado['fecha_actualizacion']}"
        f"{nota}\n\n"
        f"Consulta en: sede.colpensiones.gov.co/tramite/updInfo/39/"
    )


# ─── Envío WhatsApp (Twilio) ──────────────────────────────────────────────────
def enviar_whatsapp(config: dict, mensaje: str) -> bool:
    log.info("📲 [WHATSAPP] Enviando mensaje vía Twilio…")
    try:
        client = TwilioClient(config["TWILIO_ACCOUNT_SID"], config["TWILIO_AUTH_TOKEN"])
        destino = config["PHONE_NUMBER"]
        if not destino.startswith("whatsapp:"):
            destino = f"whatsapp:{destino}"

        message = client.messages.create(
            body=mensaje,
            from_=config["TWILIO_WHATSAPP_FROM"],
            to=destino,
        )
        log.info(f"✅ [WHATSAPP] Enviado. SID: {message.sid} | Estado: {message.status}")
        return True
    except Exception as e:
        log.error(f"❌ [WHATSAPP] Error: {e}")
        return False


# ─── Log en archivo ───────────────────────────────────────────────────────────
def guardar_log(resultado: dict, mensaje: str, enviado: bool):
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    nombre = f"ejecucion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    datos = {
        "timestamp": datetime.now().isoformat(),
        "resultado_consulta": resultado,
        "mensaje_generado": mensaje,
        "whatsapp_enviado": enviado,
    }
    with open(logs_dir / nombre, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    log.info(f"📁 Log guardado en: logs/{nombre}")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("  COLPENSIONES BOT — Inicio de ejecución")
    log.info(f"  Fecha/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    config = validar_entorno()

    # 1. Consulta web
    resultado = consultar_estado(config["CEDULA"])

    # 2. Generar mensaje
    mensaje = generar_mensaje(resultado)
    log.info(f"\n📝 [MENSAJE]\n{'-'*40}\n{mensaje}\n{'-'*40}")

    # 3. Enviar WhatsApp
    enviado = enviar_whatsapp(config, mensaje)

    # 4. Guardar log
    guardar_log(resultado, mensaje, enviado)

    # Resumen
    log.info("")
    log.info("=" * 60)
    log.info("  RESUMEN")
    log.info(f"  Consulta:   {'✅ OK' if not resultado.get('error') else '❌ Error'}")
    log.info(f"  WhatsApp:   {'✅ Enviado' if enviado else '❌ No enviado'}")
    log.info("=" * 60)

    return 0 if (not resultado.get("error") and enviado) else 1


if __name__ == "__main__":
    sys.exit(main())
