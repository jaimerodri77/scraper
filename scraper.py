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
        time.sleep(0.5) # Evitar bloqueo de API
        response = page.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.sofascore.com/tennis",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            },
            timeout=30000,
        )
        return response.json() if response.status == 200 else {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}

def normalizar_mano(mano_raw) -> str | None:
    """Convierte 'Right', 'Left' o variantes en 'R' o 'L'."""
    if not mano_raw: return None
    m = str(mano_raw).lower()
    if "right" in m or m in ("r", "d", "diestro", "derecha"): return "R"
    if "left" in m or m in ("l", "z", "zurdo", "izquierda"): return "L"
    return None

def get_player_data(page, player_id: int) -> dict | None:
    """Extrae datos básicos, país y fecha de nacimiento."""
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}")
    jugador = data.get("player")
    if not jugador: return None

    # Conversión de Timestamp a Fecha de Nacimiento
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
    """Extrae el ranking de sencillos y dobles."""
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
            # Eliminar duplicados por sofascore_id, manteniendo el registro más nuevo
            df = pd.concat([df_viejo, df_nuevo]).drop_duplicates(subset=["sofascore_id"], keep="last")
        except:
            df = df_nuevo
    else:
        df = df_nuevo

    # Ordenar columnas para que sea legible
    columnas_orden = [
        "sofascore_id", "nombre", "pais", "pais_codigo", "genero",
        "fecha_nacimiento", "edad", "mano", "altura_cm", "peso_kg",
        "ranking_singles", "ranking_dobles", "actualizado"
    ]
    # Solo mantener columnas que realmente existan en el DF
    columnas_finales = [c for c in columnas_orden if c in df.columns]
    df = df[columnas_finales]

    df.to_csv(archivo, index=False)
    logging.info(f"Base de datos de jugadores actualizada: {len(df)} registros.")

if __name__ == "__main__":
    # 1. Obtener todos los IDs de jugadores desde el archivo maestro de partidos
    if not os.path.exists(ARCHIVO_PARTIDOS):
        logging.error("No hay archivo tenis_historico.csv. Ejecuta primero los scrapers de partidos.")
        exit(1)
    
    df_partidos = pd.read_csv(ARCHIVO_PARTIDOS)
    all_ids = set(df_partidos["winner_id"].dropna().astype(int).tolist())
    all_ids.update(df_partidos["loser_id"].dropna().astype(int).tolist())
    
    # 2. Ver quiénes ya están en la base de datos para no repetirlos
    ids_existentes = set()
    if os.path.exists(ARCHIVO_JUGADORES):
        try:
            df_ext = pd.read_csv(ARCHIVO_JUGADORES)
            ids_existentes = set(df_ext["sofascore_id"].dropna().astype(int).tolist())
        except: pass

    ids_nuevos = all_ids - ids_existentes
    logging.info(f"Jugadores totales: {len(all_ids)} | Nuevos a procesar: {len(ids_nuevos)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        page.goto("https://www.sofascore.com/tennis")

        jugadores_lista = []
        total = len(ids_nuevos)

        for i, pid in enumerate(ids_nuevos, 1):
            print(f"\r[{i}/{total}] Extrayendo Jugador ID: {pid}", end="")
            
            datos = get_player_data(page, pid)
            if datos:
                # Agregar el Ranking al perfil del jugador
                ranking = get_ranking(page, pid)
                datos.update(ranking)
                jugadores_lista.append(datos)
            
            # Guardado progresivo cada 50 jugadores para evitar pérdida de datos
            if i % 50 == 0 and jugadores_lista:
                save_jugadores_csv(jugadores_lista, ARCHIVO_JUGADORES)
                jugadores_lista = []

        browser.close()

    if jugadores_lista:
        save_jugadores_csv(jugadores_lista, ARCHIVO_JUGADORES)
    
    logging.info("\nProceso de extracción de jugadores completado.")


