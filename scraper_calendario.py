import pandas as pd
from datetime import datetime
import time
import os
import logging
from curl_cffi import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")

def _session():
    s = requests.Session(impersonate="chrome120")
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.sofascore.com/tennis",
        "Origin": "https://www.sofascore.com",
    })
    return s

SESSION = _session()

def api_get(url):
    try:
        response = SESSION.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logging.warning(f"Error: {e}")
    return {}

def obtener_calendario_hoy():
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Obteniendo calendario de partidos para hoy: {hoy_str}...")
    
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{hoy_str}"
    data = api_get(url)
    eventos = data.get('events', [])
    
    partidos = []
    for e in eventos:
        try:
            torneo = e.get('tournament', {}).get('name', 'Desconocido')
            categoria = e.get('tournament', {}).get('category', {}).get('name', '')
            
            home = e.get('homeTeam', {}).get('name', 'Unknown')
            away = e.get('awayTeam', {}).get('name', 'Unknown')
            
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
            
    archivo = os.path.join("datos", "calendario.csv")
    os.makedirs("datos", exist_ok=True)
    columnas = ["Torneo", "Categoria", "Ronda", "Hora_Aprox", "Jugador_Local", "Jugador_Visitante"]

    if partidos:
        df = pd.DataFrame(partidos)
        df = df.sort_values(by="Hora_Aprox")
        df.to_csv(archivo, index=False, encoding='utf-8-sig')
        logging.info(f"\n¡Éxito! Se ha guardado el calendario con {len(partidos)} partidos de hoy en {archivo}.")
        
        print("\n--- Próximos partidos de hoy (Muestra de los siguientes 15) ---")
        print(df.assign(VS="vs")[['Hora_Aprox', 'Categoria', 'Jugador_Local', 'VS', 'Jugador_Visitante']].head(15).to_string(index=False))
    else:
        df_vacio = pd.DataFrame(columns=columnas)
        df_vacio.to_csv(archivo, index=False, encoding='utf-8-sig')
        logging.info("No se encontraron partidos programados. El archivo calendario.csv ha sido limpiado.")

if __name__ == "__main__":
    obtener_calendario_hoy()

