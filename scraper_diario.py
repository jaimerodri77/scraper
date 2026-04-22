import pandas as pd
from datetime import datetime, timedelta
import logging
import os
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA = "datos"
# Crea el archivo dinámicamente según el año actual (ej: tenis_2026.csv)
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

def formatear_valor(val):
    """Convierte la respuesta de la API al formato '77/108 (71%)'."""
    if isinstance(val, dict):
        v = val.get("value", 0)
        t = val.get("total", 0)
        if t and t > 0:
            perc = (v / t) * 100
            return f"{v}/{t} ({perc:.0f}%)"
        return f"{v}/{t} (0%)"
    return val

def es_partido_sencillos(evento: dict) -> bool:
    """Filtra partidos de dobles."""
    tourney_name = evento.get("tournament", {}).get("name", "").lower()
    cat_name = evento.get("tournament", {}).get("category", {}).get("name", "").lower()
    if "doubles" in tourney_name or "dobles" in tourney_name: return False
    if "doubles" in cat_name or "dobles" in cat_name: return False
    home_name = evento.get("homeTeam", {}).get("name", "")
    away_name = evento.get("awayTeam", {}).get("name", "")
    if "/" in home_name or "&" in home_name or "/" in away_name or "&" in away_name: return False
    return True

def ultima_fecha_csv(archivo):
    fecha_base = datetime(datetime.now().year, 1, 1).date() - timedelta(days=1)
    if not os.path.exists(archivo):
        return fecha_base
    try:
        df = pd.read_csv(archivo)
        if 'tourney_date' not in df.columns:
            return fecha_base
        fechas = pd.to_datetime(df['tourney_date']).dt.date
        return max(fechas)
    except Exception:
        return fecha_base

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
                resultado[f"{periodo_nombre}_{nombre}_home"] = formatear_valor(item.get("home"))
                resultado[f"{periodo_nombre}_{nombre}_away"] = formatear_valor(item.get("away"))
    return resultado

def procesar_dia(page, fecha):
    eventos = get_eventos_del_dia(page, fecha)
    candidatos = []
    
    for evento in eventos:
        circuito_nombre = detectar_circuito(evento)
        estado = get_estado(evento)
        # FILTRO: ATP/WTA + Terminado + Sencillos
        if circuito_nombre and estado == "finished" and es_partido_sencillos(evento):
            candidatos.append((evento, circuito_nombre))

    partidos = []
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
                "scrape_date": datetime.now().strftime("%Y%m%d"),
            }

            stats_raw = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))

            partidos.append(partido)
        except Exception as e:
            logging.warning(f"Error procesando evento {evento.get('id')}: {e}")
            continue
            
    return partidos

def append_to_csv(partidos, archivo):
    if not partidos: return
    os.makedirs(os.path.dirname(archivo), exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)
    
    if os.path.exists(archivo) and os.path.getsize(archivo) > 0:
        try:
            df_viejo = pd.read_csv(archivo)
            df_final = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["event_id"], keep='last')
        except Exception:
            df_final = df_nuevo
    else:
        df_final = df_nuevo
    
    df_final.to_csv(archivo, index=False)
    logging.info(f"🚀 CSV ACTUALIZADO: {archivo}. Total registros: {len(df_final)}")

if __name__ == "__main__":
    logging.info(f"Actualizando partidos diarios en {ARCHIVO_PARTIDOS}")
    
    ultima = ultima_fecha_csv(ARCHIVO_PARTIDOS)
    fechas = generar_fechas_desde(ultima)
    
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

