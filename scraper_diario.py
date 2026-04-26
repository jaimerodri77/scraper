import pandas as pd
from datetime import datetime, timedelta
import logging
import os
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA = "datos"
ARCHIVO_PARTIDOS = os.path.join(CARPETA_SALIDA, "tenis_historico.csv")

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
    if isinstance(val, dict):
        v = val.get("value", 0)
        t = val.get("total", 0)
        if t and t > 0:
            perc = (v / t) * 100
            return f"{v}/{t} ({perc:.0f}%)"
        return f"{v}/{t} (0%)"
    return val

def es_partido_sencillos(evento: dict) -> bool:
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
    if not os.path.exists(archivo) or os.path.getsize(archivo) == 0:
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
    if not stats_data: return resultado
    mapeo_stats = {
        "Aces": "ALL_aces", "Double faults": "ALL_double_faults", "Service points won": "ALL_total",
        "1st serve": "ALL_first_serve", "1st serve points won": "ALL_first_serve_points",
        "2nd serve points won": "ALL_second_serve_points", "Service games played": "ALL_service_games_played",
        "Break points saved": "ALL_break_points_saved"
    }
    for periodo in stats_data.get("statistics", []):
        periodo_nombre = periodo.get("period", "ALL").upper()
        if periodo_nombre != "ALL": continue
        for grupo in periodo.get("groups", []):
            for item in grupo.get("statisticsItems", []):
                nombre_original = item.get("name", "")
                nombre_normalizado = mapeo_stats.get(nombre_original)
                if nombre_normalizado:
                    resultado[f"{periodo_nombre}_{nombre_normalizado}_home"] = formatear_valor(item.get("home"))
                    resultado[f"{periodo_nombre}_{nombre_normalizado}_away"] = formatear_valor(item.get("away"))
    return resultado

def procesar_dia(page, fecha):
    eventos = get_eventos_del_dia(page, fecha)
    
    # DIAGNÓSTICO: Logueamos cuántos eventos totales devolvió la API
    total_api = len(eventos)
    logging.info(f"API devolvió {total_api} eventos totales para {fecha}")

    candidatos = []
    for evento in eventos:
        estado = get_estado(evento)
        # Solo procesamos si está terminado y es individual
        if estado in ["finished", "ended"] and es_partido_sencillos(evento):
            candidatos.append(evento)

    partidos = []
    for evento in candidatos:
        try:
            event_id = evento.get("id")
            tournament_data = evento.get("tournament", {})
            home_team = evento.get("homeTeam", {})
            away_team = evento.get("awayTeam", {})
            home_id, home_name = home_team.get("id"), home_team.get("name")
            away_id, away_name = away_team.get("id"), away_team.get("name")
            home_score = evento.get("homeScore", {}).get("current", 0) or 0
            away_score = evento.get("awayScore", {}).get("current", 0) or 0
            winner_code = evento.get("winnerCode", 0)
            
            if winner_code == 1:
                winner_name, loser_name = home_name, away_name
                winner_id, loser_id = home_id, away_id
                winner_sets, loser_sets = home_score, away_score
            elif winner_code == 2:
                winner_name, loser_name = away_name, home_name
                winner_id, loser_id = away_id, home_id
                winner_sets, loser_sets = away_score, home_score
            else:
                winner_name, loser_name = (home_name, away_name) if home_score > away_score else (away_name, home_//name)
                winner_id, loser_id = (home_id, away_id) if home_score > away_score else (away_id, home_id)
                winner_sets, loser_sets = (home_score, away_score) if home_score > away_score else (away_score, home_score)

            partido = {
                "event_id": event_id, "tourney_id": tournament_data.get("id"),
                "tourney_name": tournament_data.get("name", "Unknown"), "tourney_date": fecha,
                "round": evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface": evento.get("groundType") or tournament_data.get("groundType"),
                "winner_id": winner_id, "winner_name": winner_name,
                "loser_id": loser_id, "loser_name": loser_name,
                "winner_sets": winner_sets, "loser_sets": loser_sets,
                "scrape_date": datetime.now().strftime("%Y%m%d"),
                "ALL_aces_home": "0/0 (0%)", "ALL_aces_home": "0/0 (0%)", # ... default stats
            }

            try:
                stats_raw = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
                if stats_raw: partido.update(parsear_estadisticas(stats_raw))
            except: pass

            partidos.append(partido)
        except Exception as e:
            logging.warning(f"Error evento {evento.get('id')}: {e}")
            
    return partidos

def append_to_csv(partidos, archivo):
    if not partidos: return
    os.makedirs(os.path.*_




