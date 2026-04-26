import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
import argparse
import subprocess
import json
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA = "datos"
FECHA_INICIO = datetime(2025, 1, 1)
FECHA_FIN = datetime(2025, 12, 31)
CIRCUITOS_NOMBRES = ["atp", "wta"]
PAUSA_ENTRE_DIAS = 2.0
PAUSA_ENTRE_REQUESTS = 0.8   # Aumentado ligeramente para evitar rate limiting
INTERVALO_GUARDADO = 10

# ─────────────────────────────────────────────────────────────
# DIAGNÓSTICO: Muestra la estructura JSON cruda del primer evento
# Ponlo en True si los partidos siguen sin aparecer después del fix
# ─────────────────────────────────────────────────────────────
MODO_DEBUG_JSON = False


def git_push_progress():
    """Sube los cambios actuales al repositorio de GitHub para evitar pérdida de datos."""
    try:
        logging.info("💾 Guardando progreso en GitHub...")
        subprocess.run(["git", "config", "--global", "user.email", "scraperbot@github.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "TennisScraperBot"], check=True)
        subprocess.run(["git", "add", "datos/*.csv"], check=True)

        result = subprocess.run(["git", "diff", "--staged", "--quiet"], capture_output=True)
        if result.returncode == 0:
            logging.info("No hay cambios nuevos para guardar.")
            return

        subprocess.run(["git", "commit", "-m", f"Progreso Histórico 2025: {datetime.now().strftime('%Y-%m-%d %H:%M')}"], check=True)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
        subprocess.run(["git", "push"], check=True)
        logging.info("✅ Progreso guardado exitosamente en la nube.")
    except Exception as e:
        logging.error(f"❌ Error al guardar progreso en Git: {e}")


def iniciar_sesion(page):
    """
    Navega a SofaScore y espera hasta que la sesión esté completamente cargada.
    SofaScore usa Cloudflare y cookies de sesión — necesitamos esperar a que
    el JS cargue completamente antes de hacer API calls.
    """
    logging.info("🌐 Iniciando sesión en SofaScore...")
    try:
        page.goto("https://www.sofascore.com/tennis", wait_until="networkidle", timeout=60000)
    except Exception:
        # networkidle puede fallar si hay requests en curso — no es crítico
        logging.warning("networkidle timeout, continuando de todas formas...")

    # Esperar a que existan elementos clave del DOM (confirmación de carga real)
    try:
        page.wait_for_selector("body", timeout=10000)
    except Exception:
        pass

    time.sleep(8)  # Tiempo extra para que Cloudflare/cookies se establezcan

    # Test rápido: verificar que la sesión funciona haciendo una petición de prueba
    test_url = "https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/2025-01-15"
    test_resp = page.request.get(
        test_url,
        headers=_headers(),
        timeout=30000,
    )
    if test_resp.status == 200:
        logging.info("✅ Sesión establecida correctamente.")
    elif test_resp.status == 403:
        logging.error("❌ Sesión NO establecida — SofaScore devuelve 403. Intentando navegar de nuevo...")
        time.sleep(15)
        page.reload(wait_until="networkidle", timeout=60000)
        time.sleep(10)
    else:
        logging.warning(f"⚠️ Test de sesión devolvió {test_resp.status} — continuando igual.")


def _headers() -> dict:
    """Headers que imitan un navegador real navegando dentro de sofascore.com"""
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.sofascore.com/tennis",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def api_get(page, url: str, intentos: int = 3) -> dict:
    for intento in range(1, intentos + 1):
        try:
            time.sleep(PAUSA_ENTRE_REQUESTS)
            response = page.request.get(url, headers=_headers(), timeout=30000)

            if response.status == 200:
                return response.json()

            elif response.status == 429:
                espera = 60 * intento  # Espera progresiva: 60s, 120s, 180s
                logging.warning(f"Rate limit (429) — esperando {espera}s... (intento {intento}/{intentos})")
                time.sleep(espera)

            elif response.status == 403:
                logging.warning(f"403 en {url} (intento {intento}/{intentos}) — recargando sesión...")
                time.sleep(20 * intento)
                try:
                    page.reload(wait_until="networkidle", timeout=60000)
                    time.sleep(10)
                except Exception:
                    pass

            else:
                logging.warning(f"HTTP {response.status} en {url}")
                return {}

        except Exception as e:
            logging.warning(f"Excepción en {url} (intento {intento}/{intentos}): {e}")
            time.sleep(5 * intento)

    logging.error(f"❌ Falló después de {intentos} intentos: {url}")
    return {}


def formatear_valor(val):
    if isinstance(val, dict):
        v = val.get("value", 0)
        t = val.get("total", 0)
        if t and t > 0:
            perc = (v / t) * 100
            return f"{v}/{t} ({perc:.0f}%)"
        return f"{v}/{t} (0%)"
    return val


def get_eventos_del_dia(page, fecha: str) -> list[dict]:
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    data = api_get(page, url)
    eventos = data.get("events", [])
    logging.info(f"  → {len(eventos)} eventos totales encontrados para {fecha}")
    return eventos


def es_partido_sencillos(evento: dict) -> bool:
    tourney_name = evento.get("tournament", {}).get("name", "").lower()
    cat_name = evento.get("tournament", {}).get("category", {}).get("name", "").lower()
    if "doubles" in tourney_name or "dobles" in tourney_name:
        return False
    if "doubles" in cat_name or "dobles" in cat_name:
        return False
    home_name = evento.get("homeTeam", {}).get("name", "")
    away_name = evento.get("awayTeam", {}).get("name", "")
    if "/" in home_name or "&" in home_name or "/" in away_name or "&" in away_name:
        return False
    return True


def detectar_circuito(evento: dict) -> str | None:
    categoria = evento.get("tournament", {}).get("category", {})
    if not isinstance(categoria, dict):
        return None
    cat_name = categoria.get("name", "").lower()
    cat_slug = categoria.get("slug", "").lower()
    for circuito in CIRCUITOS_NOMBRES:
        if circuito in cat_name or circuito in cat_slug:
            return circuito.upper()
    return None


def get_estado(evento: dict) -> str:
    """
    FIX PRINCIPAL: SofaScore cambió la estructura del campo 'status'.
    Esta versión cubre todas las variantes conocidas del JSON.

    Estructuras posibles observadas:
      1. status: "finished"                          (string directo)
      2. status: { "type": "finished" }              (dict con string)
      3. status: { "type": { "name": "finished" } }  (dict anidado - versión antigua)
      4. status: { "name": "finished" }              (dict con name)
      5. status: { "code": 100, "description": "Ended" }  (código numérico)
    """
    status = evento.get("status", {})

    # Caso 1: string directo
    if isinstance(status, str):
        return status.lower()

    if not isinstance(status, dict):
        return "unknown"

    # Caso 2 y 3: campo "type"
    type_field = status.get("type")
    if type_field is not None:
        if isinstance(type_field, str):
            return type_field.lower()
        if isinstance(type_field, dict):
            name = type_field.get("name", "")
            return name.lower() if name else "unknown"

    # Caso 4: campo "name" directo en status
    name_field = status.get("name", "")
    if name_field:
        return name_field.lower()

    # Caso 5: código numérico de SofaScore (100 = finished/ended)
    # https://www.sofascore.com/news/api-codes (documentación no oficial)
    code = status.get("code")
    if code is not None:
        CODIGOS_FINISHED = {100}           # Ended / Finished
        CODIGOS_CANCELADOS = {60, 70, 80}  # Cancelled, Postponed, Abandoned
        if code in CODIGOS_FINISHED:
            return "finished"
        if code in CODIGOS_CANCELADOS:
            return "cancelled"
        return f"code_{code}"

    return "unknown"


def parsear_estadisticas(stats_data: dict) -> dict:
    resultado = {}
    for periodo in stats_data.get("statistics", []):
        periodo_nombre = periodo.get("period", "ALL").upper()
        for grupo in periodo.get("groups", []):
            for item in grupo.get("statisticsItems", []):
                nombre = item.get("name", "").replace(" ", "_").lower()
                resultado[f"{periodo_nombre}_{nombre}_home"] = formatear_valor(item.get("home"))
                resultado[f"{periodo_nombre}_{nombre}_away"] = formatear_valor(item.get("away"))
    return resultado


def fechas_ya_descargadas(archivo: str) -> set:
    if not os.path.exists(archivo) or os.path.getsize(archivo) == 0:
        return set()
    try:
        df = pd.read_csv(archivo, usecols=["tourney_date"])
        return set(df["tourney_date"].dropna().unique())
    except Exception:
        return set()


def procesar_dia(page, fecha: str) -> list[dict]:
    eventos = get_eventos_del_dia(page, fecha)
    if not eventos:
        return []

    # DIAGNÓSTICO: muestra la estructura del primer evento si está activado
    if MODO_DEBUG_JSON and eventos:
        logging.info("🔍 DEBUG — Estructura del primer evento:")
        logging.info(json.dumps(eventos[0], indent=2, ensure_ascii=False)[:2000])

    candidatos = []
    estados_vistos = {}  # Para diagnóstico

    for evento in eventos:
        estado = get_estado(evento)
        circuito = detectar_circuito(evento)
        es_singles = es_partido_sencillos(evento)

        # Conteo de estados para diagnóstico
        estados_vistos[estado] = estados_vistos.get(estado, 0) + 1

        if circuito and estado == "finished" and es_singles:
            candidatos.append((evento, circuito))

    # Log de diagnóstico: distribución de estados del día
    if estados_vistos:
        logging.info(f"  → Estados detectados: {dict(sorted(estados_vistos.items()))}")
    logging.info(f"  → Partidos ATP/WTA finalizados (singles): {len(candidatos)}")

    if not candidatos:
        return []

    partidos = []
    scrape_date_str = datetime.now().strftime("%Y%m%d")

    for i, (evento, circuito_nombre) in enumerate(candidatos, 1):
        try:
            event_id = evento.get("id")
            tournament_data = evento.get("tournament", {})
            home_team = evento.get("homeTeam", {})
            away_team = evento.get("awayTeam", {})
            home_id, home_name = home_team.get("id"), home_team.get("name")
            away_id, away_name = away_team.get("id"), away_team.get("name")
            home_score = evento.get("homeScore", {}).get("current", 0) or 0
            away_score = evento.get("awayScore", {}).get("current", 0) or 0
            home_wins = home_score > away_score
            winner_name, loser_name = (home_name, away_name) if home_wins else (away_name, home_name)
            winner_id, loser_id = (home_id, away_id) if home_wins else (away_id, home_id)

            partido = {
                "event_id": event_id,
                "circuito": circuito_nombre,
                "tourney_id": tournament_data.get("id"),
                "tourney_name": tournament_data.get("name", "Unknown"),
                "tourney_date": fecha,
                "round": evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface": evento.get("groundType") or tournament_data.get("groundType"),
                "winner_id": winner_id,
                "winner_name": winner_name,
                "loser_id": loser_id,
                "loser_name": loser_name,
                "winner_sets": home_score if home_wins else away_score,
                "loser_sets": away_score if home_wins else home_score,
                "scrape_date": scrape_date_str,
            }

            stats_raw = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))

            partidos.append(partido)
            logging.info(f"  ✓ [{i}/{len(candidatos)}] {winner_name} def. {loser_name} ({circuito_nombre})")

        except Exception as e:
            logging.error(f"Error en evento {evento.get('id')}: {e}")

    return partidos


def append_to_csv(partidos: list[dict], archivo: str):
    if not partidos:
        return
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)
    if os.path.exists(archivo) and os.path.getsize(archivo) > 0:
        try:
            df_viejo = pd.read_csv(archivo)
            df_final = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["event_id"], keep="last")
        except Exception:
            df_final = df_nuevo
    else:
        df_final = df_nuevo
    df_final.to_csv(archivo, index=False)
    logging.info(f"  💾 CSV actualizado: {len(df_final)} partidos totales.")


def generar_fechas(inicio, fin):
    fechas = []
    actual = inicio
    while actual <= fin:
        fechas.append(actual.strftime("%Y-%m-%d"))
        actual += timedelta(days=1)
    return fechas


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", type=str, help="Fecha YYYY-MM-DD para prueba")
    parser.add_argument("--debug", action="store_true", help="Activa MODO_DEBUG_JSON para ver estructura cruda")
    args = parser.parse_args()

    if args.debug:
        MODO_DEBUG_JSON = True
        logging.info("🔍 MODO DEBUG activado — se mostrará el JSON crudo del primer evento.")

    archivo = os.path.join(CARPETA_SALIDA, "tenis_historico.csv")

    if args.fecha:
        logging.info(f"*** MODO PRUEBA: Solo procesando {args.fecha} ***")
        pendientes = [args.fecha]
    else:
        todas = generar_fechas(FECHA_INICIO, FECHA_FIN)
        listas = fechas_ya_descargadas(archivo)
        pendientes = [f for f in todas if f not in listas]

    if not pendientes:
        logging.info("Todo el año ya procesado.")
        exit(0)

    logging.info(f"📅 Fechas pendientes: {len(pendientes)} ({pendientes[0]} → {pendientes[-1]})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-ES",
        )
        page = context.new_page()

        # Establecer sesión con verificación
        iniciar_sesion(page)

        for idx, fecha in enumerate(pendientes, 1):
            logging.info(f"\n[{idx}/{len(pendientes)}] ── Procesando {fecha} ──")
            try:
                res = procesar_dia(page, fecha)
                append_to_csv(res, archivo)
            except Exception as e:
                logging.error(f"Error crítico en {fecha}: {e}")

            if idx % INTERVALO_GUARDADO == 0:
                git_push_progress()

            time.sleep(PAUSA_ENTRE_DIAS)

        browser.close()

    git_push_progress()











