import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
import json
import random
from curl_cffi import requests as cffi_requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ===================== CONFIG =====================
CARPETA_SALIDA = "datos"
ARCHIVO_PARTIDOS = os.path.join(CARPETA_SALIDA, "tenis_historico.csv")
ARCHIVO_COOKIES = os.path.join(CARPETA_SALIDA, "cookies.txt")

# FECHA DE INICIO POR DEFECTO (Si el CSV no existe o está vacío)
FECHA_INICIO_DEFAULT = datetime(2024, 1, 1).date() 

CIRCUITOS_NOMBRES = ["atp", "wta", "challenger"]
GUARDAR_CADA_N_PARTIDOS = 10
PAUSA_ENTRE_REQUESTS = 0.6 

ESTADOS_FINALIZADOS = {"finished", "completed", "ended", "closed", "final", "done"}
CHROME_VERSIONS = ["chrome136", "chrome131", "chrome124"]

HEADERS_BASE = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es,es-ES;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,es-CO;q=0.5,ar;q=0.4",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": "https://www.sofascore.com",
    "Referer": "https://www.sofascore.com/tennis",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0",
    "sec-ch-ua": '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "priority": "u=1, i",
    "Connection": "keep-alive",
}

# ===================== SESIÓN Y API =====================

def _cargar_cookies() -> dict:
    if not os.path.exists(ARCHIVO_COOKIES): return {}
    try:
        with open(ARCHIVO_COOKIES, "r", encoding="utf-8") as f:
            cont = f.read().strip()
        if cont.startswith("["):
            data = json.loads(cont)
            return {item.get("name"): item.get("value") for item in data if item.get("name")}
        else:
            cookies = {}
            for par in cont.split(";"):
                if "=" in par:
                    k, v = par.strip().split("=", 1)
                    cookies[k] = v
            return cookies
    except Exception as e:
        logging.error(f"Error cookies: {e}")
        return {}

def _nueva_sesion() -> cffi_requests.Session:
    impersonate = random.choice(CHROME_VERSIONS)
    s = cffi_requests.Session(impersonate=impersonate)
    cookies = _cargar_cookies()
    if cookies: s.cookies.update(cookies)
    s.headers.update(HEADERS_BASE)
    return s

SESSION = _nueva_sesion()
_403_consecutivos = 0

def api_get(url: str, intentos: int = 4) -> dict:
    global SESSION, _403_consecutivos
    if "/event/" in url:
        event_part = url.split("/event/")[1].split("/")[0]
        SESSION.headers.update({"Referer": f"https://www.sofascore.com/tennis/match/{event_part}"})
    else:
        SESSION.headers.update({"Referer": "https://www.sofascore.com/tennis"})

    for i in range(1, intentos + 1):
        try:
            time.sleep(PAUSA_ENTRE_REQUESTS + random.uniform(0.1, 0.6))
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200:
                _403_consecutivos = 0
                return r.json()
            elif r.status_code == 403:
                _403_consecutivos += 1
                if _403_consecutivos >= 3:
                    time.sleep(120 * i)
                    SESSION = _nueva_sesion()
                    _403_consecutivos = 0
                else: time.sleep(20 * i)
            elif r.status_code == 429: time.sleep(90 * i)
            elif r.status_code == 404: return {}
            else: time.sleep(10 * i)
        except Exception as e:
            logging.error(f"Error en {url}: {e}")
            time.sleep(10 * i)
    return {}

# ===================== PARSERS CORREGIDOS =====================

def parsear_marcador_detallado(detalles: dict, home_wins: bool) -> str:
    if not detalles: return "N/A"
    event = detalles.get("event") or detalles
    sets_list = None
    for path in [lambda e: e.get("score", {}).get("sets"), lambda e: e.get("sets"), 
                 lambda e: e.get("eventScore", {}).get("sets"), lambda e: e.get("periods")]:
        res = path(event)
        if isinstance(res, list) and len(res) > 0:
            sets_list = res
            break

    if sets_list:
        scores = []
        for s in sets_list:
            h = s.get("homeScore") if s.get("homeScore") is not None else s.get("games", {}).get("home")
            if h is None: h = s.get("value")
            a = s.get("awayScore") if s.get("awayScore") is not None else s.get("games", {}).get("away")
            if a is None: a = s.get("value")
            if h is not None and a is not None:
                scores.append(f"{int(h)}-{int(a)}" if home_wins else f"{int(a)}-{int(h)}")
        if scores: return " ".join(scores)

    for key in ["displayScore", "scoreString", "currentScore"]:
        val = event.get(key)
        if val and isinstance(val, str): return val.strip()

    h_obj = event.get("homeScore")
    a_obj = event.get("awayScore")
    h_s = h_obj.get("current") if isinstance(h_obj, dict) else h_obj
    a_s = a_obj.get("current") if isinstance(a_obj, dict) else a_obj
    
    if home_wins:
        return f"{h_s if h_s is not None else '?'}-{a_s if a_s is not None else '?'}"
    else:
        return f"{a_s if a_s is not None else '?'}-{h_s if h_s is not None else '?'}"

def formatear_valor(val):
    if isinstance(val, dict):
        v = val.get("value", 0)
        t = val.get("total", 0)
        return f"{v}/{t} ({(v/t)*100:.0f}%)" if t > 0 else f"{v}/{t}"
    return val

def parsear_estadisticas(stats_data: dict) -> dict:
    resultado = {}
    for periodo in stats_data.get("statistics", []):
        p_name = periodo.get("period", "ALL").upper()
        for grupo in periodo.get("groups", []):
            for item in grupo.get("statisticsItems", []):
                nombre = item.get("name", "").replace(" ", "_").replace(".", "").lower()
                resultado[f"{p_name}_{nombre}_home"] = formatear_valor(item.get("home"))
                resultado[f"{p_name}_{nombre}_away"] = formatear_valor(item.get("away"))
    return resultado

def es_partido_sencillos(evento: dict) -> bool:
    return not any(x in str(evento).lower() for x in ["doubles", "dobles", "mixed", "mixtos"])

def detectar_circuito(evento: dict):
    t = evento.get("tournament", {})
    texto = (str(t.get("category", {}).get("name", "")) + str(t.get("name", ""))).lower()
    for c in CIRCUITOS_NOMBRES:
        if c in texto: return c.upper()
    return None

def es_partido_finalizado(evento: dict) -> bool:
    s = evento.get("status", {})
    return str(s.get("type") or s.get("description") or "").lower() in ESTADOS_FINALIZADOS

# ===================== CSV =====================

def ultima_fecha_csv(archivo):
    """Lee la última fecha en el CSV. Si no existe, devuelve la fecha por defecto."""
    if not os.path.exists(archivo) or os.path.getsize(archivo) == 0:
        logging.info(f"Archivo {archivo} no encontrado o vacío. Usando fecha inicio por defecto.")
        return FECHA_INICIO_DEFAULT
    try:
        df = pd.read_csv(archivo)
        # Convertimos la columna de fecha y buscamos la máxima
        ultima_f = pd.to_datetime(df['tourney_date']).max().date()
        if pd.isna(ultima_f):
            return FECHA_INICIO_DEFAULT
        return ultima_f
    except Exception as e:
        logging.error(f"Error leyendo última fecha: {e}")
        return FECHA_INICIO_DEFAULT

def append_to_csv(partidos, archivo):
    if not partidos: return
    os.makedirs(os.path.dirname(archivo), exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)
    if os.path.exists(archivo) and os.path.getsize(archivo) > 0:
        try:
            df_viejo = pd.read_csv(archivo)
            df_final = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["event_id"], keep="last")
        except: df_final = df_nuevo
    else:
        df_final = df_nuevo
    df_final.to_csv(archivo, index=False)

# ===================== PROCESAMIENTO =====================

def procesar_dia(fecha):
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    data = api_get(url)
    if not data: return 0

    eventos = data.get("events", [])
    candidatos = [(e, detectar_circuito(e)) for e in eventos if es_partido_finalizado(e) and es_partido_sencillos(e) and detectar_circuito(e)]
    
    buffer = []
    for i, (evento, circuito) in enumerate(candidatos, 1):
        event_id = evento.get("id")
        try:
            home = evento.get("homeTeam", {})
            away = evento.get("awayTeam", {})
            h_score = evento.get("homeScore", {}) or {}
            a_score = evento.get("awayScore", {}) or {}

            home_sets = h_score.get("current") or h_score.get("display") or 0
            away_sets = a_score.get("current") or a_score.get("display") or 0
            home_wins = int(home_sets) > int(away_sets)

            detalles = api_get(f"https://api.sofascore.com/api/v1/event/{event_id}")
            detailed_score = parsear_marcador_detallado(detalles, home_wins)
            
            stats_raw = api_get(f"https://api.sofascore.com/api/v1/event/{event_id}/statistics")

            partido = {
                "event_id": event_id,
                "circuito": circuito,
                "tourney_id": evento.get("tournament", {}).get("id"),
                "tourney_name": evento.get("tournament", {}).get("name"),
                "tourney_date": fecha,
                "round": evento.get("roundInfo", {}).get("name", "Unknown"),
                "surface": evento.get("groundType") or "Unknown",
                "home_player_id": home.get("id"),
                "away_player_id": away.get("id"),
                "home_wins": 1 if home_wins else 0,
                "winner_id": home.get("id") if home_wins else away.get("id"),
                "winner_name": home.get("name") if home_wins else away.get("name"),
                "loser_id": away.get("id") if home_wins else home.get("id"),
                "loser_name": away.get("name") if home_wins else home.get("name"),
                "winner_sets": int(home_sets) if home_wins else int(away_sets),
                "loser_sets": int(away_sets) if home_wins else int(home_sets),
                "detailed_score": detailed_score,
                "scrape_date": datetime.now().strftime("%Y-%m-%d"),
            }

            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))

            buffer.append(partido)
            logging.info(f"  [{i:3d}/{len(candidatos)}] ✅ {partido['winner_name']} def. {partido['loser_name']} → {detailed_score}")

            if len(buffer) >= GUARDAR_CADA_N_PARTIDOS:
                append_to_csv(buffer, ARCHIVO_PARTIDOS)
                buffer.clear()

        except Exception as e:
            logging.error(f"💥 Error evento {event_id}: {e}")

    if buffer: append_to_csv(buffer, ARCHIVO_PARTIDOS)
    return len(candidatos)

if __name__ == "__main__":
    logging.info("🚀 Iniciando Scraper Profesional v2...")
    
    # 1. Obtener la última fecha guardada
    ultima_fecha = ultima_fecha_csv(ARCHIVO_PARTIDOS)
    
    # 2. Definir la fecha de inicio (el día siguiente a la última fecha guardada)
    # Para evitar procesar el mismo día dos veces
    fecha_inicio = ultima_fecha + timedelta(days=1)
    hoy = datetime.now().date()
    
    logging.info(f"📅 Rango de descarga: Desde {fecha_inicio} hasta {hoy}")

    # 3. Generar la lista de fechas si la fecha de inicio es anterior o igual a hoy
    if fecha_inicio <= hoy:
        num_dias = (hoy - fecha_inicio).days + 1
        fechas = [(fecha_inicio + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_dias)]
    else:
        fechas = []
        logging.info("✅ Todos los datos están actualizados hasta hoy.")

    total = 0
    for idx, fecha in enumerate(fechas, 1):
        logging.info(f"─── Día {idx}/{len(fechas)}: {fecha} ───")
        total += procesar_dia(fecha)
        time.sleep(random.uniform(10, 20))

    logging.info(f"✅ ¡Completado! Total partidos nuevos descargados: {total}")









