import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
import json
import argparse
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

CARPETA_SALIDA = "datos"
ANO_INICIO = 2025
FECHA_INICIO = datetime(ANO_INICIO, 1, 1)
FECHA_FIN = datetime.now() - timedelta(days=1)  # hasta ayer inclusive

# Coincidencia parcial en minúsculas — robusto ante cambios de ID en la API
CIRCUITOS_NOMBRES = ["atp", "wta"]

# Pausa entre días para evitar rate limiting
PAUSA_ENTRE_DIAS = 2.0      # segundos
PAUSA_ENTRE_REQUESTS = 0.5  # segundos


def api_get(page, url: str) -> dict:
    try:
        time.sleep(PAUSA_ENTRE_REQUESTS)
        logging.info(f"API CALL: {url}")
        response = page.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.sofascore.com/tennis",
            },
            timeout=30000,
        )
        logging.info(f"API {url}: status={response.status}")
        if response.status == 200:
            data = response.json()
            logging.info(f"API OK: {len(str(data))} chars")
            return data
        elif response.status == 429:
            logging.warning("Rate limit (429) — esperando 30s...")
            time.sleep(30)
            return api_get(page, url)  # reintento
        else:
            logging.warning(f"HTTP {response.status} para {url}")
            return {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}


def get_eventos_del_dia(page, fecha: str) -> list[dict]:
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    data = api_get(page, url)
    logging.info(f"=== DEBUG {fecha} === Eventos encontrados: {len(data.get('events', []))}")
    # Save raw para debug
    debug_file = os.path.join(CARPETA_SALIDA, f"debug_{fecha}.json")
    with open(debug_file, 'w') as f:
        json.dump(data, f, indent=2)
    logging.info(f"Raw data guardado en {debug_file}")
    return data.get("events", [])


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
    status = evento.get("status", {})
    if isinstance(status, str):
        return status
    if isinstance(status, dict):
        type_field = status.get("type", {})
        if isinstance(type_field, dict):
            return type_field.get("name", "unknown")
        if isinstance(type_field, str):
            return type_field
        return status.get("name", "unknown")
    return "unknown"


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


def fechas_ya_descargadas(archivo: str) -> set:
    """Retorna el conjunto de fechas (YYYY-MM-DD) que ya están en el CSV."""
    if not os.path.exists(archivo):
        return set()
    try:
        df = pd.read_csv(archivo, usecols=["tourney_date"])
        return set(df["tourney_date"].dropna().unique())
    except Exception:
        return set()


def procesar_dia(page, fecha: str) -> list[dict]:
    eventos = get_eventos_del_dia(page, fecha)
    logging.info(f"Total eventos: {len(eventos)}")
    candidatos = []

    for evento in eventos:
        circuito_nombre = detectar_circuito(evento)
        estado = get_estado(evento)
        logging.debug(f"Evento: circuito={circuito_nombre}, estado={estado}")
        if circuito_nombre and estado == "finished":
            candidatos.append((evento, circuito_nombre))
    
    logging.info(f"Candidatos ATP/WTA finished: {len(candidatos)}")

    partidos = []
    total = len(candidatos)
    for i, (evento, circuito_nombre) in enumerate(candidatos, 1):
        try:
            event_id = evento.get("id")
            home_team = evento.get("homeTeam", {})
            away_team = evento.get("awayTeam", {})
            home = home_team.get("name", "Unknown")
            away = away_team.get("name", "Unknown")
            home_id = home_team.get("id")
            away_id = away_team.get("id")
            home_score = evento.get("homeScore", {}).get("current", 0) or 0
            away_score = evento.get("awayScore", {}).get("current", 0) or 0
            home_wins = home_score > away_score

            winner,    loser    = (home,    away)    if home_wins else (away,    home)
            winner_id, loser_id = (home_id, away_id) if home_wins else (away_id, home_id)

            surface = (
                evento.get("groundType")
                or evento.get("tournament", {}).get("groundType")
                or None
            )

            partido = {
                "event_id":    event_id,
                "circuito":    circuito_nombre,
                "tourney_name": evento.get("tournament", {}).get("name", "Unknown"),
                "tourney_date": fecha,
                "round":       evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface":     surface,
                "winner_id":   winner_id,
                "winner_name": winner,
                "loser_id":    loser_id,
                "loser_name":  loser,
                "winner_sets": home_score if home_wins else away_score,
                "loser_sets":  away_score if home_wins else home_score,
                "scrape_date": datetime.now().strftime("%Y%m%d"),
            }

            print(f"\r    [{i}/{total}] {winner} vs {loser}", end="", flush=True)

            stats_raw = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))

            partidos.append(partido)
        except Exception as e:
            logging.warning(f"Error evento {evento.get('id')}: {e}")
            continue

    if candidatos:
        print()

    return partidos


def append_to_csv(partidos: list[dict], archivo: str):
    """Agrega nuevos partidos al CSV evitando duplicados por event_id."""
    if not partidos:
        return
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)
    if os.path.exists(archivo):
        df_viejo = pd.read_csv(archivo)
        df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["event_id"])
    else:
        df = df_nuevo
    df.to_csv(archivo, index=False)


def generar_fechas(inicio: datetime, fin: datetime) -> list[str]:
    fechas = []
    actual = inicio
    while actual <= fin:
        fechas.append(actual.strftime("%Y-%m-%d"))
        actual += timedelta(days=1)
    return fechas


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper histórico tenis Sofascore")
    parser.add_argument("--fecha", type=str, help="Fecha específica YYYY-MM-DD para DEBUG (solo 1 día)")
    args = parser.parse_args()
    
    archivo = os.path.join(CARPETA_SALIDA, "tenis_historico.csv")
    debug_fecha = args.fecha

    if debug_fecha:
        logging.info(f"*** MODO DEBUG: Solo procesando {debug_fecha} ***")
        pendientes = [debug_fecha]
    else:
        todas_las_fechas = generar_fechas(FECHA_INICIO, FECHA_FIN)
        fechas_listas = fechas_ya_descargadas(archivo)
        pendientes = [f for f in todas_las_fechas if f not in fechas_listas]
        total_dias = len(todas_las_fechas)
        dias_pendientes = len(pendientes)
        logging.info(f"Rango: {todas_las_fechas[0]} → {todas_las_fechas[-1]} ({total_dias} días)")
        logging.info(f"Ya descargados: {total_dias - dias_pendientes} | Pendientes: {dias_pendientes}")

    if not pendientes:
        logging.info("Nada pendiente.")
        exit(0)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # DEBUG: visible para inspeccionar
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-ES",
        )
        page = context.new_page()
        logging.info("Iniciando sesión en Sofascore...")
        page.goto("https://www.sofascore.com/tennis", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        for idx, fecha in enumerate(pendientes, 1):
            logging.info(f"[{idx}/{dias_pendientes}] Procesando {fecha}...")
            try:
                partidos = procesar_dia(page, fecha)
                append_to_csv(partidos, archivo)
                logging.info(f"  → {len(partidos)} partidos guardados")
            except Exception as e:
                logging.error(f"  Error en {fecha}: {e} — continuando con el siguiente día")

            # Guardar progreso cada 30 días y hacer pausa más larga
            if idx % 30 == 0:
                logging.info(f"Checkpoint: {idx}/{dias_pendientes} días completados. Pausa de 10s...")
                time.sleep(10)
            else:
                time.sleep(PAUSA_ENTRE_DIAS)

        browser.close()

    # Resumen final
    if os.path.exists(archivo):
        df_final = pd.read_csv(archivo)
        logging.info(f"✓ Descarga completa: {len(df_final)} partidos totales en {archivo}")
