import pandas as pd
from datetime import datetime, timedelta
import logging
import os
import time
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

CARPETA_SALIDA = "datos"
ANO = datetime.now().year
FECHA_HOY = datetime.now().strftime("%Y-%m-%d")
FECHA_AYER = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# Nombres de circuito tal como aparecen en el campo category.name de Sofascore
# Se usa coincidencia parcial, así es robusto ante cambios menores de texto
CIRCUITOS_NOMBRES = ["atp", "wta"]


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


def detectar_circuito(evento: dict) -> str | None:
    """
    Detecta si el evento pertenece a ATP o WTA usando el nombre de categoría.
    Usa coincidencia parcial en minúsculas para ser robusto ante cambios de API.
    Retorna 'ATP', 'WTA' o None si no aplica.
    """
    categoria = evento.get("tournament", {}).get("category", {})
    cat_name = categoria.get("name", "").lower()
    cat_slug = categoria.get("slug", "").lower()

    for circuito in CIRCUITOS_NOMBRES:
        if circuito in cat_name or circuito in cat_slug:
            return circuito.upper()
    return None


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
    categorias_vistas = {}

    for evento in eventos:
        try:
            # -- Debug: registrar todas las categorías que llegan --
            categoria = evento.get("tournament", {}).get("category", {})
            cat_id = categoria.get("id")
            cat_name = categoria.get("name", "?")
            clave = f"{cat_id}:{cat_name}"
            categorias_vistas[clave] = categorias_vistas.get(clave, 0) + 1

            # -- Detectar circuito por nombre, no por ID --
            circuito_nombre = detectar_circuito(evento)

            # -- Registrar estado SIEMPRE (para diagnóstico) --
            estado = evento.get("status", {}).get("type", {}).get("name", "unknown")
            estados_vistos[estado] = estados_vistos.get(estado, 0) + 1

            if not circuito_nombre or estado != "finished":
                continue

            candidatos.append((evento, circuito_nombre))
        except Exception as e:
            logging.warning(f"Error filtrando evento: {e}")
            continue

    # Log de diagnóstico: top 10 categorías y todos los estados
    top_cats = sorted(categorias_vistas.items(), key=lambda x: -x[1])[:10]
    logging.info(f"[{fecha}] Top categorías (id:nombre): {top_cats}")
    logging.info(f"[{fecha}] Estados: {estados_vistos} | ATP/WTA terminados: {len(candidatos)}")

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

            # Surface: primero groundType, luego dentro de tournament
            surface = (
                evento.get("groundType")
                or evento.get("tournament", {}).get("groundType")
                or None
            )

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
