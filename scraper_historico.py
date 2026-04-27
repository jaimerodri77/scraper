"""
VARIABLES DE ENTORNO requeridas en GitHub Actions secrets:
  PROXY_URL   → https://tennis-proxy.TU-USUARIO.workers.dev
  PROXY_TOKEN → tu contraseña secreta (debe coincidir con el Worker)

Sin proxy: el scraper intenta conectar directo (útil para pruebas locales).
"""

import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
import argparse
import subprocess
import json
from curl_cffi import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA       = "datos"
FECHA_INICIO         = datetime(2026, 1, 1)
FECHA_FIN            = datetime(2026, 4, 27)
CIRCUITOS_NOMBRES    = ["atp", "wta"]
PAUSA_ENTRE_DIAS     = 1.5
PAUSA_ENTRE_REQUESTS = 0.6
INTERVALO_GUARDADO   = 10
MODO_DEBUG_JSON      = False

# Variables de entorno opcionales (ya no se usan, las dejamos para que no rompa si existen)
PROXY_URL   = os.environ.get("PROXY_URL", "").rstrip("/")
PROXY_TOKEN = os.environ.get("PROXY_TOKEN", "")


# =============================================================================
# GIT
# =============================================================================

def git_push_progress():
    try:
        logging.info("Guardando progreso en GitHub...")
        subprocess.run(["git", "config", "--global", "user.email", "scraperbot@github.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "TennisScraperBot"], check=True)
        subprocess.run(["git", "add", "datos/*.csv"], check=True)
        result = subprocess.run(["git", "diff", "--staged", "--quiet"], capture_output=True)
        if result.returncode == 0:
            logging.info("No hay cambios nuevos.")
            return
        subprocess.run(["git", "commit", "-m", f"Progreso 2025: {datetime.now().strftime('%Y-%m-%d %H:%M')}"], check=True)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
        subprocess.run(["git", "push"], check=True)
        logging.info("Progreso guardado.")
    except Exception as e:
        logging.error(f"Error en git push: {e}")


# =============================================================================
# HTTP — via proxy o directo
# =============================================================================

def _session():
    """Session de curl_cffi con headers base."""
    s = requests.Session(impersonate="chrome120")
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.sofascore.com/tennis",
        "Origin": "https://www.sofascore.com",
    })
    return s

SESSION = _session()


def api_get(path: str, intentos: int = 3) -> dict:
    """
    Hace GET a la API de SofaScore usando curl_cffi (Chrome TLS fingerprinting)
    para evitar bloqueos 403.
    """
    url = f"https://api.sofascore.com{path}"
    
    for intento in range(1, intentos + 1):
        try:
            time.sleep(PAUSA_ENTRE_REQUESTS)
            resp = SESSION.get(url, timeout=30)

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                espera = 60 * intento
                logging.warning(f"Rate limit 429 -> esperando {espera}s...")
                time.sleep(espera)
            elif resp.status_code == 403:
                logging.warning(f"403 en {path} (intento {intento}/{intentos}). SofaScore bloqueó la request.")
                time.sleep(15 * intento)
            else:
                logging.warning(f"HTTP {resp.status_code} en {path}")
                return {}

        except Exception as e:
            logging.warning(f"Excepcion en {path} (intento {intento}/{intentos}): {e}")
            time.sleep(5 * intento)

    logging.error(f"Fallo despues de {intentos} intentos: {path}")
    return {}


def verificar_conexion():
    """Verifica que curl_cffi bypass bypass funcione antes de empezar el scraping."""
    logging.info("Verificando conexion directa con curl_cffi (bypass antibot)...")

    data = api_get("/api/v1/sport/tennis/scheduled-events/2025-01-15")
    if data and data.get("events") is not None:
        logging.info(f"Conexion OK. Eventos de prueba: {len(data.get('events', []))}")
        return True
    else:
        logging.error("Conexion FALLIDA. SofaScore esta bloqueando incluso curl_cffi.")
        return False


# =============================================================================
# PARSEO
# =============================================================================

def formatear_valor(val):
    if isinstance(val, dict):
        v = val.get("value", 0)
        t = val.get("total", 0)
        if t and t > 0:
            return f"{v}/{t} ({(v/t)*100:.0f}%)"
        return f"{v}/{t} (0%)"
    return val


def get_eventos_del_dia(fecha: str) -> list[dict]:
    data = api_get(f"/api/v1/sport/tennis/scheduled-events/{fecha}")
    eventos = data.get("events", [])
    logging.info(f"  -> {len(eventos)} eventos totales para {fecha}")
    return eventos


def es_partido_sencillos(evento: dict) -> bool:
    tourney_name = evento.get("tournament", {}).get("name", "").lower()
    cat_name     = evento.get("tournament", {}).get("category", {}).get("name", "").lower()
    if "doubles" in tourney_name or "dobles" in tourney_name: return False
    if "doubles" in cat_name     or "dobles" in cat_name:     return False
    home_name = evento.get("homeTeam", {}).get("name", "")
    away_name = evento.get("awayTeam", {}).get("name", "")
    if "/" in home_name or "&" in home_name: return False
    if "/" in away_name or "&" in away_name: return False
    return True


def detectar_circuito(evento: dict) -> str | None:
    categoria = evento.get("tournament", {}).get("category", {})
    if not isinstance(categoria, dict): return None
    cat_name = categoria.get("name", "").lower()
    cat_slug = categoria.get("slug", "").lower()
    for circuito in CIRCUITOS_NOMBRES:
        if circuito in cat_name or circuito in cat_slug:
            return circuito.upper()
    return None


def get_estado(evento: dict) -> str:
    """Cubre todas las variantes del campo status de SofaScore."""
    status = evento.get("status", {})
    if isinstance(status, str):
        return status.lower()
    if not isinstance(status, dict):
        return "unknown"
    type_field = status.get("type")
    if type_field is not None:
        if isinstance(type_field, str):
            return type_field.lower()
        if isinstance(type_field, dict):
            name = type_field.get("name", "")
            return name.lower() if name else "unknown"
    name_field = status.get("name", "")
    if name_field:
        return name_field.lower()
    code = status.get("code")
    if code is not None:
        if code in {100}: return "finished"
        if code in {60, 70, 80}: return "cancelled"
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


# =============================================================================
# PROCESADO POR DÍA
# =============================================================================

def procesar_dia(fecha: str) -> list[dict]:
    eventos = get_eventos_del_dia(fecha)
    if not eventos:
        return []

    if MODO_DEBUG_JSON:
        logging.info("DEBUG - Primer evento:")
        logging.info(json.dumps(eventos[0], indent=2, ensure_ascii=False)[:2000])

    candidatos    = []
    estados_vistos = {}

    for evento in eventos:
        estado   = get_estado(evento)
        circuito = detectar_circuito(evento)
        estados_vistos[estado] = estados_vistos.get(estado, 0) + 1
        if circuito and estado == "finished" and es_partido_sencillos(evento):
            candidatos.append((evento, circuito))

    logging.info(f"  -> Estados: {dict(sorted(estados_vistos.items()))}")
    logging.info(f"  -> Candidatos ATP/WTA singles: {len(candidatos)}")

    if not candidatos:
        return []

    partidos = []
    scrape_date_str = datetime.now().strftime("%Y%m%d")

    for i, (evento, circuito_nombre) in enumerate(candidatos, 1):
        try:
            event_id        = evento.get("id")
            tournament_data = evento.get("tournament", {})
            home_team       = evento.get("homeTeam", {})
            away_team       = evento.get("awayTeam", {})
            home_id, home_name = home_team.get("id"), home_team.get("name")
            away_id, away_name = away_team.get("id"), away_team.get("name")
            home_score = evento.get("homeScore", {}).get("current", 0) or 0
            away_score = evento.get("awayScore", {}).get("current", 0) or 0
            home_wins  = home_score > away_score
            winner_name, loser_name = (home_name, away_name) if home_wins else (away_name, home_name)
            winner_id,   loser_id   = (home_id, away_id)     if home_wins else (away_id, home_id)

            partido = {
                "event_id":     event_id,
                "circuito":     circuito_nombre,
                "tourney_id":   tournament_data.get("id"),
                "tourney_name": tournament_data.get("name", "Unknown"),
                "tourney_date": fecha,
                "round":        evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface":      evento.get("groundType") or tournament_data.get("groundType"),
                "winner_id":    winner_id,
                "winner_name":  winner_name,
                "loser_id":     loser_id,
                "loser_name":   loser_name,
                "winner_sets":  home_score if home_wins else away_score,
                "loser_sets":   away_score if home_wins else home_score,
                "scrape_date":  scrape_date_str,
            }
            stats_raw = api_get(f"/api/v1/event/{event_id}/statistics")
            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))
            partidos.append(partido)
            logging.info(f"  [{i}/{len(candidatos)}] {winner_name} def. {loser_name} ({circuito_nombre})")
        except Exception as e:
            logging.error(f"Error en evento {evento.get('id')}: {e}")

    return partidos


# =============================================================================
# CSV
# =============================================================================

def append_to_csv(partidos: list[dict], archivo: str):
    if not partidos: return
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
    logging.info(f"  CSV: {len(df_final)} partidos totales.")


def generar_fechas(inicio, fin):
    fechas, actual = [], inicio
    while actual <= fin:
        fechas.append(actual.strftime("%Y-%m-%d"))
        actual += timedelta(days=1)
    return fechas


def fechas_ya_descargadas(archivo: str) -> set:
    if not os.path.exists(archivo) or os.path.getsize(archivo) == 0:
        return set()
    try:
        df = pd.read_csv(archivo, usecols=["tourney_date"])
        return set(df["tourney_date"].dropna().unique())
    except Exception:
        return set()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", type=str, help="Fecha YYYY-MM-DD para prueba")
    parser.add_argument("--debug", action="store_true", help="Activa MODO_DEBUG_JSON")
    args = parser.parse_args()

    if args.debug:
        MODO_DEBUG_JSON = True

    archivo = os.path.join(CARPETA_SALIDA, "tenis_historico.csv")

    if args.fecha:
        logging.info(f"*** MODO PRUEBA: Solo procesando {args.fecha} ***")
        pendientes = [args.fecha]
    else:
        todas      = generar_fechas(FECHA_INICIO, FECHA_FIN)
        listas     = fechas_ya_descargadas(archivo)
        pendientes = [f for f in todas if f not in listas]

    if not pendientes:
        logging.info("Todo el año ya procesado.")
        exit(0)

    logging.info(f"Fechas pendientes: {len(pendientes)} ({pendientes[0]} -> {pendientes[-1]})")

    # Verificar conexion antes de empezar
    if not verificar_conexion():
        exit(1)

    for idx, fecha in enumerate(pendientes, 1):
        logging.info(f"\n[{idx}/{len(pendientes)}] -- {fecha} --")
        try:
            res = procesar_dia(fecha)
            append_to_csv(res, archivo)
        except Exception as e:
            logging.error(f"Error critico en {fecha}: {e}")

        if idx % INTERVALO_GUARDADO == 0:
            git_push_progress()

        time.sleep(PAUSA_ENTRE_DIAS)

    git_push_progress()











