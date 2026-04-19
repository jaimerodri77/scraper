import pandas as pd
from datetime import datetime
import time
import os
import logging
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

logging.basicConfig(level=logging.INFO, format="%(message)s")

def api_get(page, url):
    try:
        response = page.request.get(
            url,
            headers={"Accept": "application/json", "Referer": "https://www.sofascore.com/tennis"}
        )
        if response.status == 200:
            return response.json()
    except Exception as e:
        logging.warning(f"Error: {e}")
    return {}

def obtener_calendario_hoy():
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Obteniendo calendario de partidos para hoy: {hoy_str}...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        
        page.goto("https://www.sofascore.com/tennis", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        
        # Endpoint de Sofascore para ver los partidos de una fecha exacta
        url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{hoy_str}"
        data = api_get(page, url)
        eventos = data.get('events', [])
        
        partidos = []
        for e in eventos:
            try:
                torneo = e.get('tournament', {}).get('name', 'Desconocido')
                categoria = e.get('tournament', {}).get('category', {}).get('name', '')
                
                # Si solo te importan los torneos profesionales grandes, 
                # puedes descomentar la siguiente línea:
                # if categoria not in ['ATP', 'WTA']: continue
                
                home = e.get('homeTeam', {}).get('name', 'Unknown')
                away = e.get('awayTeam', {}).get('name', 'Unknown')
                
                # Calcular la hora en que empieza (Convertir timestamp)
                timestamp = e.get('startTimestamp')
                hora_local = "Sin hora"
                if timestamp:
                    hora_local = datetime.fromtimestamp(timestamp).strftime("%H:%M")
                
                partidos.append({
                    "Torneo": torneo,
                    "Categoria": categoria,
                    "Ronda": e.get('roundInfo', {}).get('name', ''),
                    "Hora_Aprox": hora_local,
                    "Jugador_Local": home,
                    "Jugador_Visitante": away
                })
            except Exception:
                pass
                
        browser.close()
        
    # Definir el archivo y asegurar que la carpeta existe
    archivo = os.path.join("datos", "calendario.csv")
    os.makedirs("datos", exist_ok=True)

    # Columnas esperadas
    columnas = ["Torneo", "Categoria", "Ronda", "Hora_Aprox", "Jugador_Local", "Jugador_Visitante"]

    if partidos:
        df = pd.DataFrame(partidos)
        # Ordenar por hora en la que van a jugar
        df = df.sort_values(by="Hora_Aprox")
        
        # Guardar (esto sobreescribe lo que haya)
        df.to_csv(archivo, index=False, encoding='utf-8-sig')
        logging.info(f"\n¡Éxito! Se ha guardado el calendario con {len(partidos)} partidos de hoy en {archivo}.")
        
        # Imprimir una vista previa en la consola
        print("\n--- Próximos partidos de hoy (Muestra de los siguientes 15) ---")
        print(df.assign(VS="vs")[['Hora_Aprox', 'Categoria', 'Jugador_Local', 'VS', 'Jugador_Visitante']].head(15).to_string(index=False))
    else:
        # Si no hay partidos, guardamos un archivo vacío con solo los encabezados
        # para que "limpie" los partidos del día anterior.
        df_vacio = pd.DataFrame(columns=columnas)
        df_vacio.to_csv(archivo, index=False, encoding='utf-8-sig')
        logging.info("No se encontraron partidos programados. El archivo calendario.csv ha sido limpiado.")

if __name__ == "__main__":
    obtener_calendario_hoy()

