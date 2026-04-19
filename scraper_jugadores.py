import pandas as pd
from datetime import datetime
import logging
import os
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

CARPETA_SALIDA = "datos"
ANO = datetime.now().year


def api_get(page, url: str) -> dict:
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
        return {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}


def get_event_ids_desde_csv(archivo_partidos: str) -> set[int]:
    if not os.path.exists(archivo_partidos):
        logging.error(f"No existe el archivo de partidos: {archivo_partidos}")
        return set()
    df = pd.read_csv(archivo_partidos)
    return set(df["event_id"].dropna().astype(int).tolist())


def extraer_player_ids_de_equipo(equipo: dict) -> list[int]:
    tipo = equipo.get("type", "")
    eid = equipo.get("id")

    if tipo == "player":
        return [int(eid)] if eid else []

    if tipo == "team":
        sub_teams = equipo.get("subTeams") or []
        return [int(s["id"]) for s in sub_teams if s.get("id")]

    sub_teams = equipo.get("subTeams") or []
    if sub_teams:
        return [int(s["id"]) for s in sub_teams if s.get("id")]

    return [int(eid)] if eid else []


def get_player_ids_desde_eventos(page, event_ids: set[int]) -> set[int]:
    player_ids = set()

    for event_id in event_ids:
        data = api_get(page, f"https://api.sofascore.com/api/v1/event/{event_id}")
        evento = data.get("event", {})
        if not evento:
            continue

        for equipo in [evento.get("homeTeam", {}), evento.get("awayTeam", {})]:
            for pid in extraer_player_ids_de_equipo(equipo):
                player_ids.add(pid)

    logging.info(f"Player IDs únicos encontrados: {len(player_ids)}")
    return player_ids


def get_player_data(page, player_id: int) -> dict | None:
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
        except:
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


def normalizar_mano(mano_raw: str):
    if not mano_raw:
        return None

    mano_raw = mano_raw.lower()

    if "right" in mano_raw:
        return "R"
    elif "left" in mano_raw:
        return "L"
    return None


def get_ranking(page, player_id: int) -> dict:
    resultado = {}
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}/rankings")

    for r in data.get("rankings", []):
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
        try:
            df_viejo = pd.read_csv(archivo)
            df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["player_id"], keep="last")
        except pd.errors.EmptyDataError:
            df = df_nuevo
    else:
        df = df_nuevo

    df.to_csv(archivo, index=False)
    logging.info(f"Jugadores guardados: {len(df)} -> {archivo}")


if __name__ == "__main__":
    archivo_partidos = os.path.join(CARPETA_SALIDA, f"tenis_{ANO}.csv")
    archivo_jugadores = os.path.join(CARPETA_SALIDA, f"jugadores_{ANO}.csv")

    if os.path.exists(archivo_jugadores):
        try:
            df_existente = pd.read_csv(archivo_jugadores)
            ids_existentes = set(df_existente["player_id"].dropna().astype(int).tolist())
        except pd.errors.EmptyDataError:
            ids_existentes = set()
    else:
        ids_existentes = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        page.goto("https://www.sofascore.com/tennis")
        page.wait_for_timeout(3000)

        event_ids = get_event_ids_desde_csv(archivo_partidos)
        player_ids = get_player_ids_desde_eventos(page, event_ids)
        player_ids_nuevos = player_ids - ids_existentes

        jugadores = []
        total = len(player_ids_nuevos)

        for i, pid in enumerate(player_ids_nuevos, 1):
            print(f"\r[{i}/{total}] Jugador {pid}", end="")

            datos = get_player_data(page, pid)
            if not datos:
                continue

            ranking = get_ranking(page, pid)

            # 🔴 FILTRO ATP/WTA
            if not ranking.get("ranking_singles"):
                continue

            if not datos.get("nombre") or not datos.get("pais"):
                continue

            # 🔥 FILTRO CLAVE: MANO OBLIGATORIA
            mano = normalizar_mano(datos.get("mano_dominante"))
            if not mano:
                continue

            datos["mano"] = mano

            datos.update(ranking)
            jugadores.append(datos)

            # Guardado progresivo cada 50 jugadores procesados
            if i % 50 == 0 and jugadores:
                save_jugadores_csv(jugadores, archivo_jugadores)
                jugadores = []

        print()
        browser.close()

    if jugadores:
        save_jugadores_csv(jugadores, archivo_jugadores)
