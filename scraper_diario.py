import pandas as pd
from datetime import datetime, timedelta
import logging
import os
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CARPETA_SALIDA = "datos"
ARCHIVO_PARTIDOS = os.path.join(CARPETA_SALIDA, f"tenis_{datetime.now().year}.csv")

def api_get(page, url):
    try:
        response = page.request.get(url, headers={
            "Accept": "application/json",
            "Referer": "https://www.sofascore.com/tennis",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        return response.json() if response.status == 200 else {}
    except Exception as e:
        logging.warning(f"Error API {url}: {e}")
        return {}

def ultima_fecha_csv(archivo):
    if not os.path.exists(archivo):
        return datetime.now().date() - timedelta(days=365)  # Empezar 1 año atrás si no existe
    df = pd.read_csv(archivo)
    if 'tourney_date' not in df.columns:
        return datetime.now().date() - timedelta(days=365)
    fechas = pd.to_datetime(df['tourney_date']).dt.date
    return max(fechas)

def generar_fechas_desde(ultima_fecha):
    hoy = datetime.now().date()
    fechas = []
    actual = ultima_fecha + timedelta(days=1)
    while actual <= hoy:
        fechas.append(actual.strftime("%Y-%m-%d"))
        actual += timedelta(days=1)
    return fechas

def get_eventos_del_dia(page, fecha):
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    data = api_get(page, url)
    return data.get('events', [])

def procesar_dia(page, fecha):
    eventos = get_eventos_del_dia(page, fecha)
    partidos = []
    for evento in eventos:
        try:
            # Filtrar solo tenis ATP/WTA/ITF relevantes
            tournament = evento.get('tournament', {})
            if tournament.get('category', {}).get('name') in ['ATP', 'WTA', 'ITF']:
                partido = {
                    'event_id': evento['id'],
                    'tourney_date': fecha,
                    'tourney_name': tournament.get('name', 'Unknown'),
                    'round': evento.get('roundInfo', {}).get('name', 'Unknown'),
                    # Agregar más campos si necesario: scores, players, etc.
                }
                partidos.append(partido)
        except Exception as e:
            logging.warning(f"Error procesando evento {evento.get('id')}: {e}")
    return partidos

def append_to_csv(partidos, archivo):
    if not partidos:
        return
    os.makedirs(os.path.dirname(archivo), exist_ok=True)
    df_nuevo = pd.DataFrame(partidos)
    event_ids_nuevos = set(df_nuevo['event_id'])
    
    if os.path.exists(archivo):
        df_viejo = pd.read_csv(archivo)
        event_ids_viejos = set(df_viejo['event_id'].dropna().astype(int))
        df_nuevo = df_nuevo[~df_nuevo['event_id'].isin(event_ids_viejos)]
    
    if not df_nuevo.empty:
        df_final = pd.concat([pd.read_csv(archivo) if os.path.exists(archivo) else pd.DataFrame(), df_nuevo], ignore_index=True)
        df_final.to_csv(archivo, index=False)
        logging.info(f"Agregados {len(df_nuevo)} partidos nuevos a {archivo}")
    else:
        logging.info("No hay partidos nuevos")

if __name__ == "__main__":
    logging.info(f"Actualizando partidos desde última fecha hasta hoy en {ARCHIVO_PARTIDOS}")
    
    ultima = ultima_fecha_csv(ARCHIVO_PARTIDOS)
    fechas = generar_fechas_desde(ultima)
    logging.info(f"Fechas a procesar ({len(fechas)}): {ultima + timedelta(days=1)} a {datetime.now().date()}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto("https://www.sofascore.com/tennis")
        page.wait_for_timeout(2000)
        
        for fecha in fechas:
            logging.info(f"Procesando {fecha}...")
            partidos = procesar_dia(page, fecha)
            append_to_csv(partidos, ARCHIVO_PARTIDOS)
        
        browser.close()
    
    logging.info("✓ Scraper diario completado")
