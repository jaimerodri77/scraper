import pandas as pd
from datetime import datetime, timedelta
import logging
import os
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA = "datos"
ARCHIVO_PARTIDOS = os.path.join(CARPETA_SALIDA, f"tenis_{datetime.now().year}.csv")
CIRCUITOS_NOMBRES = ["atp", "wta"]

def api_get(page, url):
    try:
        response = page.request.get(url, headers={
            "Accept": "application/json",
            "Referer": "https://www.sofascore.com/tennis",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        return response.json() if response.status == 200 else {}
    except Exception as e:
        logging.warning(f"Error API {url}: {e}")
        return {}

def ultima_fecha_csv(archivo):
    if not os.path.exists(archivo):
        return datetime.now().date() - timedelta(days=365)  # Empezar 1 año atrás si no existe
    df = pd.read_csv(archivo)
    if 'tourney_date' not in df.columns:
        return datetime.now().date() - timedelta(days=365)
    fechas = pd.to_datetime(df['tourney_date']).dt.date
    return max(fechas)

def generar_fechas_desde(ultima_fecha):
    hoy = datetime.now().date()
    fechas = []
    actual = ultima_fecha + timedelta(days=1)
    while actual <= hoy:
        fechas.append(actual.strftime("%Y-%m-%d"))
        actual += timedelta(days=1)
    return fechas

def get_eventos_del_dia(page, fecha):
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    data = api_get(page, url)
    return data.get('events', [])

def detectar_circuito(evento: dict):
    categoria = evento.get("tournament", {}).get("category", {})
    if not isinstance(categoria, dict): return None
    cat_name = categoria.get("name", "").lower()
    cat_slug = categoria.get("slug", "").lower()
    for circuito in CIRCUITOS_NOMBRES:
        if circuito in cat_name or circuito in cat_slug:
            return circuito.upper()
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
    resultado = {}
    for periodo in stats_data.get("statistics", []):
        periodo_nombre = periodo.get("period", "ALL").upper()
        for grupo in periodo.get("groups", []):
            for item in grupo.get("statisticsItems", []):
                nombre = item.get("name", "").replace(" ", "_").lower()
                resultado[f"{periodo_nombre}_{nombre}_home"] = item.get("home")
                resultado[f"{periodo_nombre}_{nombre}_away"] = item.get("away")
    return resultado

def procesar_dia(page, fecha):
    eventos = get_eventos_del_dia(page, fecha)
    candidatos = []
    
    for evento in eventos:
        circuito_nombre = detectar_circuito(evento)
        estado = get_estado(evento)
        if circuito_nombre and estado == "finished":
            candidatos.append((evento, circuito_nombre))

    partidos = []
    total = len(candidatos)
    for i, (evento, circuito_nombre) in enumerate(candidatos, 1):
        try:
            event_id = evento.get("id")
            home = evento.get("homeTeam", {}).get("name", "Unknown")
            away = evento.get("awayTeam", {}).get("name", "Unknown")
            home_score = evento.get("homeScore", {}).get("current", 0) or 0
            away_score = evento.get("awayScore", {}).get("current", 0) or 0
            winner, loser = (home, away) if home_score > away_score else (away, home)

            surface = (evento.get("groundType") or evento.get("tournament", {}).get("groundType") or None)

            partido = {
                "event_id": event_id,
                "circuito": circuito_nombre,
                "tourney_name": evento.get("tournament", {}).get("name", "Unknown"),
                "tourney_date": fecha,
                "round": evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface": surface,
                "winner_name": winner,
                "loser_name": loser,
                "winner_sets": home_score if home_score > away_score else away_score,
                "loser_sets": away_score if home_score > away_score else home_score,
                "scrape_date": datetime.now().strftime("%Y%m%d"),
            }

            print(f"\r    [{i}/{total}] {winner} vs {loser}", end="", flush=True)

            stats_raw = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))

            partidos.append(partido)
        except Exception as e:
            logging.warning(f"Error procesando evento {evento.get('id')}: {e}")
            continue
            
    if candidatos:
        print()
        
    return partidos

def append_to_csv(partidos, archivo):
    if not partidos:
        return
    os.makedirs(os.path.dirname(archivo), exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)
    event_ids_nuevos = set(df_nuevo['event_id'])
    
    if os.path.exists(archivo):
        df_viejo = pd.read_csv(archivo)
        event_ids_viejos = set(df_viejo['event_id'].dropna().astype(int))
        df_nuevo = df_nuevo[~df_nuevo['event_id'].isin(event_ids_viejos)]
    
    if not df_nuevo.empty:
        df_final = pd.concat([pd.read_csv(archivo) if os.path.exists(archivo) else pd.DataFrame(), df_nuevo], ignore_index=True)
        df_final.to_csv(archivo, index=False)
        logging.info(f"Agregados {len(df_nuevo)} partidos nuevos a {archivo}")
    else:
        logging.info("No hay partidos nuevos")

if __name__ == "__main__":
    logging.info(f"Actualizando partidos desde última fecha hasta hoy en {ARCHIVO_PARTIDOS}")
    
    ultima = ultima_fecha_csv(ARCHIVO_PARTIDOS)
    fechas = generar_fechas_desde(ultima)
    logging.info(f"Fechas a procesar ({len(fechas)}): {ultima + timedelta(days=1)} a {datetime.now().date()}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        page.goto("https://www.sofascore.com/tennis")
        page.wait_for_timeout(2000)
        
        for fecha in fechas:
            logging.info(f"Procesando {fecha}...")
            partidos = procesar_dia(page, fecha)
            append_to_csv(partidos, ARCHIVO_PARTIDOS)
        
        browser.close()
    
    logging.info("✓ Scraper diario completado")
