import pandas as pd
from datetime import datetime
import logging
import os
import time
import argparse
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA = "datos"
ARCHIVO_JUGADORES = os.path.join(CARPETA_SALIDA, "jugadores_maestro.csv")
ARCHIVO_PARTIDOS = os.path.join(CARPETA_SALIDA, "tenis_historico.csv")

def api_get(page, url: str) -> dict:
    try:
        time.sleep(0.6) # Pausa para evitar el bloqueo 429
        response = page.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.sofascore.com/tennis",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            },
            timeout=30000,
        )
        if response.status == 200:
            return response.json()
        elif response.status == 429:
            logging.warning("Rate limit (429) - Esperando 30s...")
            time.sleep(30)
            return api_get(page, url)
        return {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}

def normalizar_mano(mano_raw) -> str | None:
    if not mano_raw: return None
    m = str(mano_raw).lower()
    if "right" in m or m in ("r", "d", "diestro", "derecha"): return "R"
    if "left" in m or m in ("l", "z", "zurdo", "izquierda"): return "L"
    return None

def get_player_data(page, player_id: int) -> dict | None:
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}")
    jugador = data.get("player")
    if not jugador: return None

    fecha_nac = None
    ts = jugador.get("dateOfBirthTimestamp")
    if ts:
        try:
            fecha_nac = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
        except: pass

    pais_raw = jugador.get("country")
    pais = pais_raw if isinstance(pais_raw, dict) else {}

    return {
        "sofascore_id": player_id,
        "nombre": jugador.get("name"),
        "nombre_corto": jugador.get("shortName"),
        "fecha_nacimiento": fecha_nac,
        "edad": jugador.get("age"),
        "mano": normalizar_mano(jugador.get("plays")),
        "altura_cm": jugador.get("height"),
        "peso_kg": jugador.get("weight"),
        "pais": pais.get("name"),
        "pais_codigo": pais.get("alpha2"),
        "genero": jugador.get("gender"),
        "actualizado": datetime.now().strftime("%Y-%m-%d"),
    }

def get_ranking(page, player_id: int) -> dict:
    resultado = {}
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}/rankings")
    rankings = data.get("rankings", [])
    for r in rankings:
        tipo = r.get("type", "").lower()
        pos = r.get("ranking")
        if "double" in tipo:
            resultado["ranking_dobles"] = pos
        else:
            resultado["ranking_singles"] = pos
    return resultado

def save_jugadores_csv(jugadores: list[dict], archivo: str):
    if not jugadores: return
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df_nuevo = pd.DataFrame(jugadores)

    if os.path.exists(archivo):
        try:
            df_viejo = pd.read_csv(archivo)
            # UNIÓN Y ELIMINACIÓN DE DUPLICADOS
            # keep='last' asegura que el dato nuevo (ranking actualizado) reemplace al viejo
            df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["sofascore_id"], keep="last")
        except:
            df = df_nuevo
    else:
        df = df_nuevo

    columnas_orden = [
        "sofascore_id", "nombre", "pais", "pais_codigo", "genero",
        "fecha_nacimiento", "edad", "mano", "altura_cm", "peso_kg",
        "ranking_singles", "ranking_dobles", "actualizado"
    ]
    columnas_finales = [c for c in columnas_orden if c in df.columns]
    df = df[columnas_finales]

    df.to_csv(archivo, index=False)
    logging.info(f"Base de datos actualizada: {len(df)} jugadores.")

if __name__ == "__main__":
    if not os.path.exists(ARCHIVO_PARTIDOS):
        logging.error("No se encontró tenis_historico.csv.")
        exit(1)
    
    # Leer todos los IDs que aparecen en los partidos
    df_partidos = pd.read_csv(ARCHIVO_PARTIDOS)
    all_ids = set(df_partidos["winner_id"].dropna().astype(int).tolist())
    all_ids.update(df_partidos["loser_id"].dropna().astype(int).tolist())
    
    # IMPORTANTE: Ya no filtramos los ids_existentes aquí.
    # Procesamos todos los IDs encontrados para actualizar sus rankings.
    logging.info(f"Total de jugadores a procesar/actualizar: {len(all_ids)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        page.goto("https://www.sofascore.com/tennis")

        jugadores_lista = []
        total = len(all_ids)

        for i, pid in enumerate(all_ids, 1):
            print(f"\r[{i}/{total}] Actualizando Jugador ID: {pid}", end="")
            
            datos = get_player_data(page, pid)
            if datos:
                ranking = get_ranking(page, pid)
                datos.update(ranking)
                jugadores_lista.append(datos)
            
            # Guardado cada 50 para no perder progreso
            if i % 50 == 0 and jugadores_lista:
                save_jugadores_csv(jugadores_lista, ARCHIVO_JUGADORES)
                jugadores_lista = []

        browser.close()

    if jugadores_lista:
        save_jugadores_csv(jugadores_lista, ARCHIVO_JUGADORES)
    
    logging.info("\nSincronización de jugadores y rankings completada.")



