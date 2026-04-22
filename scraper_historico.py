import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
import json
import argparse
from playwright.sync_api import sync_playwright

# Configuración de logs para seguimiento en GitHub Actions
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA = "datos"
ANO_INICIO = 2025
FECHA_INICIO = datetime(ANO_INICIO, 1, 1)
FECHA_FIN = datetime.now() - timedelta(days=1)
CIRCUITOS_NOMBRES = ["atp", "wta"]
PAUSA_ENTRE_DIAS = 2.0
PAUSA_ENTRE_REQUESTS = 0.5

def api_get(page, url: str) -> dict:
    """Realiza peticiones a la API de Sofascore."""
    try:
        time.sleep(PAUSA_ENTRE_REQUESTS)
        response = page.request.get(
            url,
            headers={"Accept": "application/json", "Referer": "https://www.sofascore.com/tennis"},
            timeout=30000,
        )
        if response.status == 200: 
            return response.json()
        elif response.status == 429:
            logging.warning("Rate limit (429) — esperando 30s...")
            time.sleep(30)
            return api_get(page, url)
        return {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}

def formatear_valor(val):
    """
    Convierte la respuesta de la API al formato '77/108 (71%)' 
    según el ejemplo de CSV proporcionado.
    """
    if isinstance(val, dict):
        v = val.get("value", 0)
        t = val.get("total", 0)
        if t and t > 0:
            perc = (v / t) * 100
            return f"{v}/{t} ({perc:.0f}%)"
        return f"{v}/{t} (0%)"
    return val

def get_eventos_del_dia(page, fecha: str) -> list[dict]:
    """Obtiene los eventos de un día específico. NO guarda archivos JSON."""
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    data = api_get(page, url)
    return data.get("events", [])

def detectar_circuito(evento: dict) -> str | None:
    categoria = evento.get("tournament", {}).get("category", {})
    if not isinstance(categoria, dict): return None
    cat_name = categoria.get("name", "").lower()
    cat_slug = categoria.get("slug", "").lower()
    for circuito in CIRCUITOS_NOMBRES:
        if circuito in cat_name or circuito in cat_slug: return circuito.upper()
    return None

def get_estado(evento: dict) -> str:
    status = evento.get("status", {})
    if isinstance(status, str): return status
    if isinstance(status, dict):
        type_field = status.get("type", {})
        if isinstance(type_field, dict): return type_field.get("name", "unknown")
        if isinstance(type_field, str): return type_field
        return status.get("name", "unknown")
    return "unknown"

def parsear_estadisticas(stats_data: dict) -> dict:
    """Procesa las estadísticas aplicando el formato de ratio y porcentaje."""
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
    if not os.path.exists(archivo): return set()
    try:
        df = pd.read_csv(archivo, usecols=["tourney_date"])
        return set(df["tourney_date"].dropna().unique())
    except Exception: return set()

def procesar_dia(page, fecha: str) -> list[dict]:
    """Filtra partidos ATP/WTA terminados y extrae sus datos."""
    eventos = get_eventos_del_dia(page, fecha)
    
    candidatos = []
    for evento in eventos:
        circuito = detectar_circuito(evento)
        estado = get_estado(evento)
        if circuito and estado == "finished":
            candidatos.append((evento, circuito))
    
    if not candidatos:
        logging.info(f"Día {fecha}: Sin partidos ATP/WTA terminados.")
        return []

    partidos = []
    for i, (evento, circuito_nombre) in enumerate(candidatos, 1):
        try:
            event_id = evento.get("id")
            home_team = evento.get("homeTeam", {})
            away_team = evento.get("awayTeam", {})
            home_score = evento.get("homeScore", {}).get("current", 0) or 0
            away_score = evento.get("awayScore", {}).get("current", 0) or 0
            home_wins = home_score > away_score

            winner, loser = (home_team.get("name"), away_team.get("name")) if home_wins else (away_team.get("name"), home_team.get("name"))
            
            partido = {
                "event_id": event_id,
                "circuito": circuito_nombre,
                "tourney_name": evento.get("tournament", {}).get("name", "Unknown"),
                "tourney_date": fecha,
                "round": evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface": evento.get("groundType") or evento.get("tournament", {}).get("groundType"),
                "winner_name": winner,
                "loser_name": loser,
                "winner_sets": home_score if home_wins else away_score,
                "loser_sets": away_score if home_wins else home_score,
                "scrape_date": datetime.now().strftime("%Y%m%d"),
            }

            stats_raw = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))
            partidos.append(partido)
        except Exception as e:
            logging.error(f"Error en evento {evento.get('id')}: {e}")
    return partidos

def append_to_csv(partidos: list[dict], archivo: str):
    """Guarda los datos en el CSV evitando duplicados por event_id."""
    if not partidos: return
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)
    
    if os.path.exists(archivo):
        df_viejo = pd.read_csv(archivo)
        df_final = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["event_id"], keep='last')
    else:
        df_final = df_nuevo
    
    df_final.to_csv(archivo, index=False)
    logging.info(f"🚀 CSV ACTUALIZADO: {archivo}. Total registros: {len(df_final)}")

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
    args = parser.parse_args()
    
    archivo = os.path.join(CARPETA_SALIDA, "tenis_historico.csv")
    
    if args.fecha:
        logging.info(f"*** MODO PRUEBA: Solo procesando {args.fecha} ***")
        pendientes = [args.fecha]
    else:
        todas = generar_fechas(FECHA_INICIO, FECHA_FIN)
        listas = fechas_ya_descargadas(archivo)
        pendientes = [f for f in todas if f not in listas]

    if not pendientes:
        logging.info("Nada pendiente para procesar.")
        exit(0)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()
        page.goto("https://www.sofascore.com/tennis", wait_until="domcontentloaded")
        time.sleep(5)

        for idx, fecha in enumerate(pendientes, 1):
            logging.info(f"[{idx}/{len(pendientes)}] Procesando {fecha}...")
            try:
                res = procesar_dia(page, fecha)
                append_to_csv(res, archivo)
            except Exception as e:
                logging.error(f"Error en {fecha}: {e}")
            time.sleep(PAUSA_ENTRE_DIAS)
        browser.close()




