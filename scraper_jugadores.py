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


def get_event_ids_desde_csv(archivo_partidos: str) -> set[int]:
    """Extrae los event_ids del CSV de partidos ya scrapeados."""
    if not os.path.exists(archivo_partidos):
        logging.error(f"No existe el archivo de partidos: {archivo_partidos}")
        return set()
    df = pd.read_csv(archivo_partidos)
    ids = set(df["event_id"].dropna().astype(int).tolist())
    logging.info(f"Event IDs a consultar: {len(ids)}")
    return ids


def extraer_player_ids_de_equipo(equipo: dict) -> list[int]:
    """
    Dado un dict de homeTeam o awayTeam, devuelve los player IDs individuales.

    - Singles:  type == "player" -> devuelve [equipo["id"]]
    - Dobles:   type == "team"   -> expande subTeams y devuelve sus IDs
    - Sin tipo: intenta subTeams, si no asume singles
    """
    tipo = equipo.get("type", "")
    eid = equipo.get("id")

    if tipo == "player":
        return [int(eid)] if eid else []

    if tipo == "team":
        sub_teams = equipo.get("subTeams") or []
        ids = [int(s["id"]) for s in sub_teams if s.get("id")]
        if ids:
            return ids
        logging.debug(f"Equipo de dobles sin subTeams: id={eid}, name={equipo.get('name')}")
        return []

    # Fallback sin campo type
    sub_teams = equipo.get("subTeams") or []
    if sub_teams:
        return [int(s["id"]) for s in sub_teams if s.get("id")]
    return [int(eid)] if eid else []


def get_player_ids_desde_eventos(page, event_ids: set[int]) -> set[int]:
    """
    Consulta cada evento y extrae los IDs individuales de los jugadores,
    manejando correctamente singles (type=player) y dobles (type=team -> subTeams).
    """
    player_ids = set()
    total = len(event_ids)
    singles_count = dobles_count = skip_count = 0

    for i, event_id in enumerate(event_ids, 1):
        print(
            f"\r  Extrayendo jugadores [{i}/{total}] — "
            f"singles: {singles_count} dobles: {dobles_count} skip: {skip_count}",
            end="", flush=True
        )
        data = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}")
        evento = data.get("event", {})
        if not evento:
            skip_count += 1
            continue

        home = evento.get("homeTeam", {})
        away = evento.get("awayTeam", {})

        es_dobles = home.get("type") == "team" or away.get("type") == "team"
        if es_dobles:
            dobles_count += 1
        else:
            singles_count += 1

        for equipo in [home, away]:
            for pid in extraer_player_ids_de_equipo(equipo):
                player_ids.add(pid)

    if event_ids:
        print()

    logging.info(
        f"Eventos — singles: {singles_count}, dobles: {dobles_count}, "
        f"skip: {skip_count} | Player IDs unicos: {len(player_ids)}"
    )
    return player_ids


def get_player_data(page, player_id: int) -> dict | None:
    """
    Consulta el endpoint de jugador en Sofascore y extrae los campos relevantes.
    Retorna None si el ID no corresponde a un jugador individual (404 silencioso).
    """
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}")
    jugador = data.get("player")
    if not jugador:
        return None

    fecha_nac = None
    if jugador.get("dateOfBirthTimestamp"):
        try:
            fecha_nac = datetime.utcfromtimestamp(
                jugador["dateOfBirthTimestamp"]
            ).strftime("%Y-%m-%d")
        except Exception:
            pass

    pais = jugador.get("country", {}) if isinstance(jugador.get("country"), dict) else {}

    return {
        "player_id": player_id,
        "nombre": jugador.get("name"),
        "nombre_corto": jugador.get("shortName"),
        "fecha_nacimiento": fecha_nac,
        "edad": jugador.get("age"),
        "mano_dominante": jugador.get("plays"),
        "altura_cm": jugador.get("height"),
        "peso_kg": jugador.get("weight"),
        "pais": pais.get("name"),
        "pais_codigo": pais.get("alpha2"),
        "genero": jugador.get("gender"),
        "actualizado": datetime.now().strftime("%Y-%m-%d"),
    }


def get_ranking(page, player_id: int) -> dict:
    """Consulta el ranking actual del jugador (singles y dobles)."""
    resultado = {}
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}/rankings")
    for r in data.get("rankings", []):
        tipo = r.get("type", "").lower()
        pos = r.get("ranking")
        if "double" in tipo or "doble" in tipo:
            resultado["ranking_dobles"] = pos
        else:
            resultado["ranking_singles"] = pos
    return resultado


def save_jugadores_csv(jugadores: list[dict], archivo: str):
    if not jugadores:
        logging.warning("No hay jugadores nuevos para guardar.")
        return
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df_nuevo = pd.DataFrame(jugadores)
    if os.path.exists(archivo):
        df_viejo = pd.read_csv(archivo)
        df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["player_id"], keep="last")
    else:
        df = df_nuevo
    df.to_csv(archivo, index=False)
    logging.info(f"Total jugadores guardados: {len(df)} -> {archivo}")


if __name__ == "__main__":
    archivo_partidos = os.path.join(CARPETA_SALIDA, f"tenis_{ANO}.csv")
    archivo_jugadores = os.path.join(CARPETA_SALIDA, f"jugadores_{ANO}.csv")

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
        logging.info("Iniciando sesion en Sofascore...")
        page.goto(
            "https://www.sofascore.com/tennis",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.wait_for_timeout(3000)

        event_ids = get_event_ids_desde_csv(archivo_partidos)
        player_ids_todos = get_player_ids_desde_eventos(page, event_ids)
        player_ids_nuevos = player_ids_todos - ids_existentes
        logging.info(f"Jugadores nuevos a descargar: {len(player_ids_nuevos)}")

        jugadores = []
        total = len(player_ids_nuevos)
        for i, pid in enumerate(player_ids_nuevos, 1):
            print(f"\r  [{i}/{total}] Descargando jugador {pid}", end="", flush=True)
            datos = get_player_data(page, pid)
            if datos:
                datos.update(get_ranking(page, pid))
                jugadores.append(datos)

        if player_ids_nuevos:
            print()

        browser.close()

    save_jugadores_csv(jugadores, archivo_jugadores)
