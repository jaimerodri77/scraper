import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
import requests
import sys

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

CIRCUITOS = {
    "ATP": 2,
    "WTA": 6,
}


def get_eventos_del_dia(fecha: str) -> list[dict]:
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        eventos = r.json().get("events", [])
        logging.info(f"[{fecha}] Eventos encontrados: {len(eventos)}")
        return eventos
    except Exception as e:
        logging.error(f"Error obteniendo eventos para {fecha}: {e}")
        return []


def get_estadisticas(event_id: int) -> dict:
    url = f"https://api.sofascore.com/api/v1/event/{event_id}/statistics"
    try:
        time.sleep(0.2)  # Reducido de 0.5 a 0.2
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.warning(f"Error stats evento {event_id}: {e}")
        return {}


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


def procesar_eventos(eventos: list[dict], fecha: str) -> list[dict]:
    partidos = []

    # Filtrar solo ATP/WTA terminados primero
    candidatos = []
    for evento in eventos:
        try:
            categoria_id = evento.get("tournament", {}).get("category", {}).get("id")
            circuito_nombre = next((n for n, cid in CIRCUITOS.items() if categoria_id == cid), None)
            if not circuito_nombre:
                continue
            estado = evento.get("status", {}).get("type", {}).get("name", "")
            if estado != "finished":
                continue
            candidatos.append((evento, circuito_nombre))
        except Exception:
            continue

    total = len(candidatos)
    logging.info(f"[{fecha}] Partidos ATP/WTA terminados: {total}")

    for i, (evento, circuito_nombre) in enumerate(candidatos, 1):
        try:
            event_id = evento.get("id")
            home = evento.get("homeTeam", {}).get("name", "Unknown")
            away = evento.get("awayTeam", {}).get("name", "Unknown")
            home_score = evento.get("homeScore", {}).get("current", 0)
            away_score = evento.get("awayScore", {}).get("current", 0)
            winner, loser = (home, away) if home_score > away_score else (away, home)

            torneo = evento.get("tournament", {})
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
                "scrape_date": datetime.now().strftime("%Y%m%d"),
            }

            # Barra de progreso en log
            pct = int((i / total) * 20)
            barra = "█" * pct + "░" * (20 - pct)
            print(f"\r  [{barra}] {i}/{total} — {winner} vs {loser}", end="", flush=True)

            stats_raw = get_estadisticas(event_id)
            if stats_raw:
                partido.update(parsear_estadisticas(stats_raw))

            partidos.append(partido)

        except Exception as e:
            logging.warning(f"Error procesando evento {evento.get('id')}: {e}")
            continue

    print()  # Salto de línea tras la barra
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


def recolectar_rango(fecha_inicio: str, fecha_fin: str, archivo_salida: str):
    """Recolecta partidos entre dos fechas (formato YYYY-MM-DD)."""
    inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    fin = datetime.strptime(fecha_fin, "%Y-%m-%d")
    total_dias = (fin - inicio).days + 1
    logging.info(f"Recolectando {total_dias} días: {fecha_inicio} → {fecha_fin}")

    todos = []
    dia_actual = inicio
    for d in range(total_dias):
        fecha_str = dia_actual.strftime("%Y-%m-%d")
        logging.info(f"── Día {d+1}/{total_dias}: {fecha_str}")
        eventos = get_eventos_del_dia(fecha_str)
        partidos = procesar_eventos(eventos, fecha_str)
        todos.extend(partidos)
        # Guardar progreso cada 7 días por si se interrumpe
        if (d + 1) % 7 == 0 and todos:
            save_to_csv(todos, archivo_salida)
            todos = []
        dia_actual += timedelta(days=1)

    if todos:
        save_to_csv(todos, archivo_salida)

    logging.info("¡Recolección histórica completada!")


if __name__ == "__main__":
    # Modo histórico: python scraper.py 2025-01-01 2025-12-31
    if len(sys.argv) == 3:
        fecha_inicio = sys.argv[1]
        fecha_fin = sys.argv[2]
        ano = fecha_inicio[:4]
        archivo = os.path.join(CARPETA_SALIDA, f"tenis_{ano}.csv")
        recolectar_rango(fecha_inicio, fecha_fin, archivo)
    else:
        # Modo diario normal (hoy + ayer)
        archivo = os.path.join(CARPETA_SALIDA, f"tenis_{ANO}.csv")
        todos = []
        for fecha in [FECHA_AYER, FECHA_HOY]:
            eventos = get_eventos_del_dia(fecha)
            todos.extend(procesar_eventos(eventos, fecha))
        save_to_csv(todos, archivo)
