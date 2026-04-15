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

# Contadores de diagnóstico
stats = {
    "sin_datos": 0,
    "sin_ranking": 0,
    "sin_nombre_o_pais": 0,
    "sin_mano": 0,
    "aceptados": 0,
}


def api_get(page, url: str) -> dict:
    # FIX 1: delay aumentado a 0.5s para evitar rate limiting de SofaScore
    try:
        time.sleep(0.5)
        response = page.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.sofascore.com/tennis",
                # FIX 2: headers adicionales para simular mejor un navegador real
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            timeout=30000,
        )
        if response.status == 200:
            return response.json()
        # FIX 3: loggear el status code para detectar bloqueos (403, 429, etc.)
        logging.warning(f"HTTP {response.status} en {url}")
        return {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}


def get_event_ids_desde_csv(archivo_partidos: str) -> set[int]:
    if not os.path.exists(archivo_partidos):
        logging.error(f"No existe el archivo de partidos: {archivo_partidos}")
        return set()
    df = pd.read_csv(archivo_partidos)
    ids = set(df["event_id"].dropna().astype(int).tolist())
    logging.info(f"Event IDs leídos del CSV: {len(ids)}")
    return ids


def extraer_player_ids_de_equipo(equipo: dict) -> list[int]:
    """
    FIX 4: lógica mejorada para extraer player IDs.
    En tenis individual, homeTeam/awayTeam tiene type='player' y el id es el player_id.
    En dobles, type='team' y los jugadores están en subTeams o players.
    """
    if not equipo:
        return []

    tipo = equipo.get("type", "")
    eid = equipo.get("id")

    if tipo == "player":
        return [int(eid)] if eid else []

    if tipo == "team":
        # Intentar subTeams primero
        sub_teams = equipo.get("subTeams") or []
        if sub_teams:
            return [int(s["id"]) for s in sub_teams if s.get("id")]

        # FIX 5: algunos equipos de dobles usan campo "players" en lugar de "subTeams"
        players = equipo.get("players") or []
        if players:
            return [int(p["id"]) for p in players if p.get("id")]

        # Fallback: el propio id del equipo (no siempre es un jugador, pero por si acaso)
        return [int(eid)] if eid else []

    # Tipo desconocido: intentar subTeams, players, o el propio id
    sub_teams = equipo.get("subTeams") or []
    if sub_teams:
        return [int(s["id"]) for s in sub_teams if s.get("id")]

    players = equipo.get("players") or []
    if players:
        return [int(p["id"]) for p in players if p.get("id")]

    return [int(eid)] if eid else []


def get_player_ids_desde_eventos(page, event_ids: set[int]) -> set[int]:
    player_ids = set()
    total = len(event_ids)

    for i, event_id in enumerate(event_ids, 1):
        print(f"\r[{i}/{total}] Obteniendo jugadores del evento {event_id}", end="")
        data = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}")
        evento = data.get("event", {})
        if not evento:
            logging.debug(f"Evento {event_id} sin datos")
            continue

        for equipo in [evento.get("homeTeam", {}), evento.get("awayTeam", {})]:
            for pid in extraer_player_ids_de_equipo(equipo):
                player_ids.add(pid)

    print()
    logging.info(f"Player IDs únicos encontrados: {len(player_ids)}")
    return player_ids


def get_player_data(page, player_id: int) -> dict | None:
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}")
    jugador = data.get("player")
    if not jugador:
        logging.debug(f"Sin datos para player_id={player_id}")
        return None

    fecha_nac = None
    if jugador.get("dateOfBirthTimestamp"):
        try:
            fecha_nac = datetime.utcfromtimestamp(
                jugador["dateOfBirthTimestamp"]
            ).strftime("%Y-%m-%d")
        except Exception:
            pass

    # FIX 6: "country" puede ser None, un dict, o estar ausente
    pais_raw = jugador.get("country")
    pais = pais_raw if isinstance(pais_raw, dict) else {}

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


def normalizar_mano(mano_raw) -> str | None:
    if not mano_raw:
        return None
    mano_raw = str(mano_raw).lower()
    if "right" in mano_raw:
        return "R"
    elif "left" in mano_raw:
        return "L"
    # FIX 7: algunos registros usan abreviaturas o valores en español
    elif mano_raw in ("r", "d", "diestro", "derecha"):
        return "R"
    elif mano_raw in ("l", "z", "zurdo", "izquierda"):
        return "L"
    return None


def get_ranking(page, player_id: int) -> dict:
    resultado = {}
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}/rankings")

    rankings = data.get("rankings", [])
    if not rankings:
        logging.debug(f"Sin rankings para player_id={player_id}")
        return resultado

    for r in rankings:
        tipo = r.get("type", "").lower()
        pos = r.get("ranking")

        if "double" in tipo:
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
        df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["player_id"], keep="last")
    else:
        df = df_nuevo

    df.to_csv(archivo, index=False)
    logging.info(f"Jugadores guardados: {len(df)} -> {archivo}")


if __name__ == "__main__":
    archivo_partidos = os.path.join(CARPETA_SALIDA, f"tenis_{ANO}.csv")
    archivo_jugadores = os.path.join(CARPETA_SALIDA, f"jugadores_{ANO}.csv")

    if os.path.exists(archivo_jugadores):
        df_existente = pd.read_csv(archivo_jugadores)
        ids_existentes = set(df_existente["player_id"].dropna().astype(int).tolist())
        logging.info(f"Jugadores ya existentes en CSV: {len(ids_existentes)}")
    else:
        ids_existentes = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            # FIX 8: user agent realista en el contexto del navegador
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        page.goto("https://www.sofascore.com/tennis")
        page.wait_for_timeout(3000)

        event_ids = get_event_ids_desde_csv(archivo_partidos)
        if not event_ids:
            logging.error("Sin event_ids. Verifica que exista el archivo de partidos.")
            browser.close()
            exit(1)

        player_ids = get_player_ids_desde_eventos(page, event_ids)
        player_ids_nuevos = player_ids - ids_existentes
        logging.info(f"Player IDs nuevos a procesar: {len(player_ids_nuevos)}")

        jugadores = []
        total = len(player_ids_nuevos)

        for i, pid in enumerate(player_ids_nuevos, 1):
            print(f"\r[{i}/{total}] Jugador {pid}", end="")

            datos = get_player_data(page, pid)
            if not datos:
                stats["sin_datos"] += 1
                continue

            ranking = get_ranking(page, pid)

            # FIX 9: filtro de ranking relajado — se acepta si tiene ranking_singles O ranking_dobles
            # (antes solo aceptaba singles, descartando a doublistas y jugadores sin ranking aún)
            tiene_ranking = ranking.get("ranking_singles") or ranking.get("ranking_dobles")
            if not tiene_ranking:
                stats["sin_ranking"] += 1
                logging.debug(f"Descartado sin ranking: {datos.get('nombre')} (pid={pid})")
                continue

            if not datos.get("nombre") or not datos.get("pais"):
                stats["sin_nombre_o_pais"] += 1
                logging.debug(f"Descartado sin nombre/país: pid={pid}")
                continue

            # FIX 10: mano ya no es obligatoria — se guarda como None si no está disponible
            # (antes descartaba silenciosamente a jugadores sin este campo)
            mano = normalizar_mano(datos.get("mano_dominante"))
            datos["mano"] = mano  # puede ser None

            datos.update(ranking)
            jugadores.append(datos)
            stats["aceptados"] += 1

        print()
        browser.close()

    # FIX 11: reporte final de diagnóstico
    logging.info("=== RESUMEN DE DESCARTE ===")
    logging.info(f"  Sin datos del jugador : {stats['sin_datos']}")
    logging.info(f"  Sin ranking           : {stats['sin_ranking']}")
    logging.info(f"  Sin nombre o país     : {stats['sin_nombre_o_pais']}")
    logging.info(f"  Sin mano (no bloqueó) : {stats['sin_mano']}")
    logging.info(f"  Aceptados             : {stats['aceptados']}")

    save_jugadores_csv(jugadores, archivo_jugadores)
