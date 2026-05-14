import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
from curl_cffi import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA = "datos"
ARCHIVO_PARTIDOS = os.path.join(CARPETA_SALIDA, "tenis_historico.csv")
# Ampliado para incluir ITF, Challenger, UTR, etc.
CIRCUITOS_NOMBRES = ["atp", "wta", "itf", "challenger", "utr", "exhibition", "world tennis tour"]
PAUSA_ENTRE_REQUESTS = 0.6

# Estados de partidos finalizados (ampliado)
ESTADOS_FINALIZADOS = ["finished", "completed", "ended", "closed", "final", "done"]

def _session():
    s = requests.Session(impersonate="chrome120")
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.sofascore.com/tennis",
        "Origin": "https://www.sofascore.com",
    })
    return s

SESSION = _session()

def api_get(url: str, intentos: int = 3) -> dict:
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
                logging.warning(f"403 en {url} (intento {intento}/{intentos}). SofaScore bloqueó la request.")
                time.sleep(15 * intento)
            elif resp.status_code == 404:
                # Para estadísticas que no existen
                logging.debug(f"404 en {url} (no encontrado)")
                return {}
            else:
                logging.warning(f"HTTP {resp.status_code} en {url}")
                return {}
        except Exception as e:
            logging.warning(f"Excepcion en {url} (intento {intento}/{intentos}): {e}")
            time.sleep(5 * intento)
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
    """Detecta si un partido es de sencillos (no dobles ni mixtos)"""
    tourney_name = evento.get("tournament", {}).get("name", "").lower()
    cat_name = evento.get("tournament", {}).get("category", {}).get("name", "").lower()
    round_name = evento.get("roundInfo", {}).get("name", "").lower()
    
    # Palabras que indican dobles o mixtos
    palabras_dobles = ["doubles", "dobles", "mixed", "mixtos", "double", "doble"]
    
    # Rechazar si el torneo o categoría contiene palabras de dobles
    for palabra in palabras_dobles:
        if palabra in tourney_name or palabra in cat_name or palabra in round_name:
            return False
    
    # Revisar nombres de jugadores: si hay "&", "/" o "and", probablemente dobles
    home_name = evento.get("homeTeam", {}).get("name", "")
    away_name = evento.get("awayTeam", {}).get("name", "")
    
    indicadores_dobles = ["&", "/", " and ", " y "]
    for indicador in indicadores_dobles:
        if indicador in home_name or indicador in away_name:
            return False
    
    return True

def detectar_circuito(evento: dict):
    """Detecta el circuito del torneo (ATP, WTA, ITF, Challenger, etc.)"""
    tournament = evento.get("tournament", {})
    categoria = tournament.get("category", {})
    
    if not isinstance(categoria, dict):
        return "UNKNOWN"
    
    # Intentar obtener nombre y slug de la categoría
    cat_name = categoria.get("name", "").lower()
    cat_slug = categoria.get("slug", "").lower()
    tourney_name = tournament.get("name", "").lower()
    
    # Primero, verificar si es un torneo conocido
    for circuito in CIRCUITOS_NOMBRES:
        if circuito in cat_name or circuito in cat_slug or circuito in tourney_name:
            return circuito.upper()
    
    # Si no se detecta circuito específico pero es sencillos, marcarlo como UNKNOWN
    if es_partido_sencillos(evento):
        return "UNKNOWN"
    
    return None

def get_estado(evento: dict) -> str:
    """Obtiene el estado del partido (finished, inprogress, etc.)"""
    status = evento.get("status", {})
    
    if isinstance(status, str):
        return status.lower()
    
    if isinstance(status, dict):
        # Probar diferentes campos donde puede estar el estado
        for campo in ["type", "name", "description", "code"]:
            valor = status.get(campo)
            if isinstance(valor, dict):
                return valor.get("name", "unknown").lower()
            elif isinstance(valor, str):
                return valor.lower()
    
    return "unknown"

def es_partido_finalizado(evento: dict) -> bool:
    """Verifica si el partido ya terminó"""
    estado = get_estado(evento)
    return estado in ESTADOS_FINALIZADOS

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

def get_eventos_del_dia(fecha):
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    data = api_get(url)
    return data.get('events', [])

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

def procesar_dia(fecha):
    """Procesa todos los partidos de una fecha específica"""
    eventos = get_eventos_del_dia(fecha)
    
    # Log para depuración
    logging.info(f"📊 Total eventos encontrados en {fecha}: {len(eventos)}")
    
    # Contar por categoría (para depuración)
    categorias = {}
    for e in eventos:
        cat = e.get("tournament", {}).get("category", {}).get("name", "Unknown")
        categorias[cat] = categorias.get(cat, 0) + 1
    
    logging.info(f"Categorías encontradas: {categorias}")
    
    candidatos = []
    eventos_filtrados = 0
    eventos_no_finalizados = 0
    eventos_dobles = 0
    
    for evento in eventos:
        # Verificar si está finalizado
        if not es_partido_finalizado(evento):
            eventos_no_finalizados += 1
            continue
        
        # Verificar si es sencillos
        if not es_partido_sencillos(evento):
            eventos_dobles += 1
            continue
        
        # Detectar circuito
        circuito_nombre = detectar_circuito(evento)
        if circuito_nombre is None:
            eventos_filtrados += 1
            continue
        
        candidatos.append((evento, circuito_nombre))
    
    logging.info(f"  - No finalizados: {eventos_no_finalizados}")
    logging.info(f"  - Dobles/Mixtos: {eventos_dobles}")
    logging.info(f"  - Sin circuito detectado: {eventos_filtrados}")
    logging.info(f"  ✅ Partidos a procesar: {len(candidatos)}")
    
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
            
            # Obtener superficie (puede estar en varios lugares)
            surface = evento.get("groundType")
            if not surface:
                surface = tournament_data.get("groundType")
            if not surface:
                surface = evento.get("tournament", {}).get("surface", "Unknown")

            partido = {
                "event_id": event_id,
                "circuito": circuito_nombre,
                "tourney_id": tournament_data.get("id"),
                "tourney_name": tournament_data.get("name", "Unknown"),
                "tourney_date": fecha,
                "round": evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface": surface,
                "winner_id": winner_id,
                "winner_name": winner_name,
                "loser_id": loser_id,
                "loser_name": loser_name,
                "winner_sets": home_score if home_wins else away_score,
                "loser_sets": away_score if home_wins else home_score,
                "scrape_date": datetime.now().strftime("%Y%m%d"),
            }

            # Intentar obtener estadísticas (si falla, continuar sin ellas)
            try:
                stats_raw = api_get(f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")
                if stats_raw:
                    partido.update(parsear_estadisticas(stats_raw))
            except Exception as e:
                logging.debug(f"No se pudieron obtener estadísticas para evento {event_id}: {e}")
            
            partidos.append(partido)
            logging.debug(f"  Procesado {i}/{len(candidatos)}: {winner_name} vs {loser_name} ({circuito_nombre})")
            
        except Exception as e:
            logging.warning(f"Error procesando evento {evento.get('id')}: {e}")
            continue

    return partidos

def append_to_csv(partidos, archivo):
    if not partidos:
        logging.info("No hay partidos nuevos para agregar")
        return
    
    os.makedirs(os.path.dirname(archivo), exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)

    if os.path.exists(archivo) and os.path.getsize(archivo) > 0:
        try:
            df_viejo = pd.read_csv(archivo)
            df_final = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["event_id"], keep='last')
            logging.info(f"Registros existentes: {len(df_viejo)} - Nuevos: {len(df_nuevo)} - Total: {len(df_final)}")
        except Exception as e:
            logging.warning(f"Error al leer CSV existente: {e}")
            df_final = df_nuevo
    else:
        df_final = df_nuevo
        logging.info(f"Creando nuevo archivo con {len(df_final)} registros")

    df_final.to_csv(archivo, index=False)
    logging.info(f"🚀 CSV MAESTRO ACTUALIZADO: {archivo}")

if __name__ == "__main__":
    logging.info(f"Actualizando partidos diarios en {ARCHIVO_PARTIDOS}")
    ultima = ultima_fecha_csv(ARCHIVO_PARTIDOS)
    fechas = generar_fechas_desde(ultima)
    
    logging.info(f"Fechas a procesar: {len(fechas)} días ({fechas[0] if fechas else 'ninguna'} a {fechas[-1] if fechas else 'ninguna'})")
    
    total_partidos = 0
    for fecha in fechas:
        logging.info(f"\n📅 Procesando {fecha}...")
        partidos = procesar_dia(fecha)
        if partidos:
            append_to_csv(partidos, ARCHIVO_PARTIDOS)
            total_partidos += len(partidos)
        time.sleep(1)  # Pequeña pausa entre días
    
    logging.info(f"\n✓ Scraper completado! Total partidos nuevos procesados: {total_partidos}")








