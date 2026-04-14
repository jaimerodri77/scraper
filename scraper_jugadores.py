import pandas as pd
from datetime import datetime
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


def get_player_ids_desde_csv(archivo_partidos: str) -> set[int]:
    """
    Extrae los IDs de jugadores directamente desde el CSV de partidos.
    Usa la columna 'event_id' para volver a consultar el evento y obtener
    los IDs reales de los jugadores (homeTeam.id / awayTeam.id).
    Retorna el set de event_ids para consultar.
    """
    if not os.path.exists(archivo_partidos):
        logging.error(f"No existe el archivo de partidos: {archivo_partidos}")
        return set()
    df = pd.read_csv(archivo_partidos)
    ids = set(df["event_id"].dropna().astype(int).tolist())
    logging.info(f"Event IDs a consultar para extraer jugadores: {len(ids)}")
    return ids


def get_player_ids_desde_eventos(page, event_ids: set[int]) -> set[int]:
    """
    Consulta cada evento para extraer los IDs reales de los jugadores
    (homeTeam.id y awayTeam.id en la respuesta de Sofascore).
    """
    player_ids = set()
    total = len(event_ids)
    for i, event_id in enumerate(event_ids, 1):
        print(f"\r  Extrayendo jugadores de eventos [{i}/{total}]", end="", flush=True)
        data = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}")
        evento = data.get("event", {})
        home_id = evento.get("homeTeam", {}).get("id")
        away_id = evento.get("awayTeam", {}).get("id")
        if home_id:
            player_ids.add(int(home_id))
        if away_id:
            player_ids.add(int(away_id))
    if event_ids:
        print()
    logging.info(f"Player IDs únicos encontrados: {len(player_ids)}")
    return player_ids


def get_player_data(page, player_id: int) -> dict | None:
    """
    Consulta el endpoint de jugador en Sofascore y extrae los campos relevantes.
    Retorna un dict con los datos del jugador o None si falla.
    """
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}")
    jugador = data.get("player")
    if not jugador:
        return None

    # Fecha de nacimiento
    fecha_nac = None
    if jugador.get("dateOfBirthTimestamp"):
        try:
            fecha_nac = datetime.utcfromtimestamp(
                jugador["dateOfBirthTimestamp"]
            ).strftime("%Y-%m-%d")
        except Exception:
            pass

    # País
    pais_nombre = jugador.get("country", {}).get("name") if isinstance(jugador.get("country"), dict) else None
    pais_alpha2 = jugador.get("country", {}).get("alpha2") if isinstance(jugador.get("country"), dict) else None

    return {
        "player_id": player_id,
        "nombre": jugador.get("name"),
        "nombre_corto": jugador.get("shortName"),
        "fecha_nacimiento": fecha_nac,
        "edad": jugador.get("age"),
        "mano_dominante": jugador.get("plays"),          # "Right", "Left", "Two-Handed", etc.
        "altura_cm": jugador.get("height"),
        "peso_kg": jugador.get("weight"),
        "pais": pais_nombre,
        "pais_codigo": pais_alpha2,
        "genero": jugador.get("gender"),
        "actualizado": datetime.now().strftime("%Y-%m-%d"),
    }


def get_ranking(page, player_id: int) -> dict:
    """
    Consulta el ranking actual del jugador.
    Retorna {'ranking_singles': N, 'ranking_dobles': M} o vacío.
    """
    resultado = {}
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}/rankings")
    rankings = data.get("rankings", [])
    for r in rankings:
        tipo = r.get("type", "").lower()
        pos = r.get("ranking")
        if "double" in tipo or "doble" in tipo:
            resultado["ranking_dobles"] = pos
        else:
            resultado["ranking_singles"] = pos
    return resultado


def save_jugadores_csv(jugadores: list[dict], archivo: str):
    if not jugadores:
        logging.warning("No hay jugadores para guardar.")
        return
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df_nuevo = pd.DataFrame(jugadores)
    if os.path.exists(archivo):
        df_viejo = pd.read_csv(archivo)
        df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(
            subset=["player_id"], keep="last"   # keep="last" actualiza rankings/edad
        )
    else:
        df = df_nuevo
    df.to_csv(archivo, index=False)
    logging.info(f"Total jugadores: {len(df)} → {archivo}")


if __name__ == "__main__":
    archivo_partidos = os.path.join(CARPETA_SALIDA, f"tenis_{ANO}.csv")
    archivo_jugadores = os.path.join(CARPETA_SALIDA, f"jugadores_{ANO}.csv")

    # Cargar jugadores ya procesados para no repetir llamadas innecesarias
    if os.path.exists(archivo_jugadores):
        df_existente = pd.read_csv(archivo_jugadores)
        ids_existentes = set(df_existente["player_id"].dropna().astype(int).tolist())
        logging.info(f"Jugadores ya en CSV: {len(ids_existentes)}")
    else:
        ids_existentes = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="es-ES",
        )
        page = context.new_page()
        logging.info("Iniciando sesión en Sofascore...")
        page.goto(
            "https://www.sofascore.com/tennis",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(3000)

        # 1. Obtener event_ids del CSV de partidos
        event_ids = get_player_ids_desde_csv(archivo_partidos)

        # 2. Resolver player_ids reales consultando cada evento
        player_ids_todos = get_player_ids_desde_eventos(page, event_ids)

        # 3. Filtrar sólo los nuevos (no procesados aún)
        player_ids_nuevos = player_ids_todos - ids_existentes
        logging.info(f"Jugadores nuevos a descargar: {len(player_ids_nuevos)}")

        # 4. Descargar datos de cada jugador nuevo
        jugadores = []
        total = len(player_ids_nuevos)
        for i, pid in enumerate(player_ids_nuevos, 1):
            print(f"\r  [{i}/{total}] Descargando jugador {pid}", end="", flush=True)
            datos = get_player_data(page, pid)
            if datos:
                ranking = get_ranking(page, pid)
                datos.update(ranking)
                jugadores.append(datos)

        if player_ids_nuevos:
            print()

        browser.close()

    save_jugadores_csv(jugadores, archivo_jugadores)
