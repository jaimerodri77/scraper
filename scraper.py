import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

CARPETA_SALIDA = "datos"
ANO = datetime.now().year
FECHA_HOY = datetime.now().strftime("%Y-%m-%d")
FECHA_AYER = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
}

# Categorías ATP y WTA en Sofascore (IDs estables)
CIRCUITOS = {
    "ATP": 2,   # category_id ATP
    "WTA": 6,   # category_id WTA
}


def get_eventos_del_dia(fecha: str) -> list[dict]:
    """Obtiene todos los partidos de tenis de una fecha dada."""
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        eventos = r.json().get("events", [])
        logging.info(f"[{fecha}] Total eventos de tenis: {len(eventos)}")
        return eventos
    except Exception as e:
        logging.error(f"Error obteniendo eventos para {fecha}: {e}")
        return []


def get_estadisticas(event_id: int) -> dict:
    """Obtiene estadísticas detalladas de un partido por su ID."""
    url = f"https://api.sofascore.com/api/v1/event/{event_id}/statistics"
    try:
        time.sleep(0.5)  # Respetar rate limit
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.warning(f"Error obteniendo stats del evento {event_id}: {e}")
        return {}


def parsear_estadisticas(stats_data: dict) -> dict:
    """Aplana las estadísticas en un dict plano para el CSV."""
    resultado = {}
    for periodo in stats_data.get("statistics", []):
        periodo_nombre = periodo.get("period", "ALL").upper()
        for grupo in periodo.get("groups", []):
            for item in grupo.get("statisticsItems", []):
                nombre = item.get("name", "").replace(" ", "_").lower()
                clave_home = f"{periodo_nombre}_{nombre}_home"
                clave_away = f"{periodo_nombre}_{nombre}_away"
                resultado[clave_home] = item.get("home")
                resultado[clave_away] = item.get("away")
    return resultado


def procesar_eventos(eventos: list[dict], fecha: str) -> list[dict]:
    """Filtra ATP/WTA y extrae datos + estadísticas por partido."""
    partidos = []

    for evento in eventos:
        try:
            # Filtrar solo ATP y WTA singles
            torneo = evento.get("tournament", {})
            categoria = torneo.get("category", {})
            categoria_id = categoria.get("id")
            circuito_nombre = None
            for nombre, cid in CIRCUITOS.items():
                if categoria_id == cid:
                    circuito_nombre = nombre
                    break
            if not circuito_nombre:
                continue

            estado = evento.get("status", {}).get("type", {}).get("name", "")
            # Solo partidos terminados
            if estado not in ("finished",):
                continue

            event_id = evento.get("id")
            home = evento.get("homeTeam", {}).get("name", "Unknown")
            away = evento.get("awayTeam", {}).get("name", "Unknown")
            home_score = evento.get("homeScore", {}).get("current", 0)
            away_score = evento.get("awayScore", {}).get("current", 0)

            if home_score > away_score:
                winner, loser = home, away
            else:
                winner, loser = away, home

            # Score por sets
            sets_home = [str(s) for s in evento.get("homeScore", {}).values() if isinstance(s, int)]
            sets_away = [str(s) for s in evento.get("awayScore", {}).values() if isinstance(s, int)]
            score = " ".join(f"{h}-{a}" for h, a in zip(sets_home, sets_away))

            ronda = evento.get("roundInfo", {}).get("name", "Unknown")
            superficie = evento.get("groundType", None)

            partido = {
                "event_id": event_id,
                "circuito": circuito_nombre,
                "tourney_name": torneo.get("name", "Unknown"),
                "tourney_date": fecha,
                "round": ronda,
                "surface": superficie,
                "winner_name": winner,
                "loser_name": loser,
                "score": score,
                "scrape_date": datetime.now().strftime("%Y%m%d"),
            }

            # Agregar estadísticas detalladas
            stats_raw = get_estadisticas(event_id)
            if stats_raw:
                stats_planas = parsear_estadisticas(stats_raw)
                partido.update(stats_planas)
                logging.info(f"  ✓ Stats obtenidas: {winner} vs {loser} ({len(stats_planas)} campos)")
            else:
                logging.warning(f"  ✗ Sin stats: {winner} vs {loser}")

            partidos.append(partido)

        except Exception as e:
            logging.warning(f"Error procesando evento {evento.get('id')}: {e}")
            continue

    logging.info(f"[{fecha}] Partidos ATP/WTA procesados: {len(partidos)}")
    return partidos


def save_to_csv(partidos: list[dict]):
    if not partidos:
        logging.warning("No se encontraron partidos para guardar.")
        return

    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    archivo = os.path.join(CARPETA_SALIDA, f"tenis_{ANO}.csv")
    df_nuevo = pd.DataFrame(partidos)

    if os.path.exists(archivo):
        df_viejo = pd.read_csv(archivo)
        df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(
            subset=["event_id"]
        )
    else:
        df = df_nuevo

    df.to_csv(archivo, index=False)
    logging.info(f"Total registros guardados: {len(df)} → {archivo}")


if __name__ == "__main__":
    todos = []
    for fecha in [FECHA_AYER, FECHA_HOY]:
        eventos = get_eventos_del_dia(fecha)
        todos.extend(procesar_eventos(eventos, fecha))
    save_to_csv(todos)
