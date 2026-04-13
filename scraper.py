import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
import json
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

CARPETA_SALIDA = "datos"
ANO = datetime.now().year
FECHA_HOY = datetime.now().strftime("%Y-%m-%d")
FECHA_AYER = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

CIRCUITOS = {"ATP": 2, "WTA": 6}


def api_get(page, url: str) -> dict:
    """Hace una request a la API de Sofascore usando el contexto del navegador."""
    try:
        time.sleep(0.3)
        response = page.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.sofascore.com/tennis",
            },
            timeout=30000,
        )
        if response.status == 200:
            return response.json()
        else:
            logging.warning(f"HTTP {response.status} para {url}")
            return {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}


def get_eventos_del_dia(page, fecha: str) -> list[dict]:
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    data = api_get(page, url)
    eventos = data.get("events", [])
    logging.info(f"[{fecha}] Eventos encontrados: {len(eventos)}")
    return eventos


def parsear_estadisticas(stats_data: dict) -> dict:
    resultado = {}
    for periodo in stats_data.get("statistics", []):
        periodo_nombre = periodo.get("period", "ALL").upper()
        for grupo in periodo.get("groups", []):
            for item in grupo.get("statisticsItems", []):
                nombre = item.get("name", "").replace(" ", "_").lower()
                resultado[f"{periodo_nombre}_{nombre}_home"] = item.get("home")
                resultado[f"{periodo_nombre}_{nombre}_away"] = item.get("away")
    return resultado


def procesar_eventos(page, eventos: list[dict], fecha: str) -> list[dict]:
    candidatos = []
    estados_vistos = {}

    for evento in eventos:
        try:
            categoria_id = evento.get("tournament", {}).get("category", {}).get("id")
            circuito_nombre = next((n for n, cid in CIRCUITOS.items() if categoria_id == cid), None)
            estado = evento.get("status", {}).get("type", {}).get("name", "unknown")
            estados_vistos[estado] = estados_vistos.get(estado, 0) + 1
            if not circuito_nombre or estado != "finished":
                continue
            candidatos.append((evento, circuito_nombre))
        except Exception:
            continue

    logging.info(f"[{fecha}] Estados: {estados_vistos} | ATP/WTA terminados: {len(candidatos)}")

    partidos = []
    total = len(candidatos)
    for i, (evento, circuito_nombre) in enumerate(candidatos, 1):
        try:
            event_id = evento.get("id")
            home = evento.get("homeTeam", {}).get("name", "Unknown")
            away = evento.get("awayTeam", {}).get("name", "Unknown")
            home_score = evento.get("homeScore", {}).get("current", 0)
            away_score = evento.get("awayScore", {}).get("current", 0)
            winner, loser = (home, away) if home_score > away_score else (away, home)

            partido = {
                "event_id": event_id,
                "circuito": circuito_nombre,
                "tourney_name": evento.get("tournament", {}).get("name", "Unknown"),
                "tourney_date": fecha,
                "round": evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface": evento.get("groundType", None),
                "winner_name": winner,
                "loser_name": loser,
                "scrape_date": datetime.now().strftime("%Y%m%d"),
            }

            print(f"\r  [{i}/{total}] {winner} vs {loser}", end="", flush=True)

            stats_raw = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))

            partidos.append(partido)
        except Exception as e:
            logging.warning(f"Error evento {evento.get('id')}: {e}")
            continue

    if candidatos:
        print()
    logging.info(f"[{fecha}] Partidos procesados: {len(partidos)}")
    return partidos


def save_to_csv(partidos: list[dict], archivo: str):
    if not partidos:
        logging.warning("No hay partidos para guardar.")
        return
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)
    if os.path.exists(archivo):
        df_viejo = pd.read_csv(archivo)
        df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["event_id"])
    else:
        df = df_nuevo
    df.to_csv(archivo, index=False)
    logging.info(f"Total registros: {len(df)} → {archivo}")


if __name__ == "__main__":
    archivo = os.path.join(CARPETA_SALIDA, f"tenis_{ANO}.csv")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-ES",
        )
        # Visitar sofascore primero para establecer cookies/sesión
        page = context.new_page()
        logging.info("Iniciando sesión en Sofascore...")
        page.goto("https://www.sofascore.com/tennis", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        todos = []
        for fecha in [FECHA_AYER, FECHA_HOY]:
            eventos = get_eventos_del_dia(page, fecha)
            todos.extend(procesar_eventos(page, eventos, fecha))

        browser.close()

    save_to_csv(todos, archivo)
