import requests
import yaml
import csv
import time

def load_config():
    with open("config.yml", "r") as f:
        return yaml.safe_load(f)['settings']

def get_matches_data(config):
    # URL de la API de Sofascore para obtener eventos por fecha
    url = f"https://api.sofascore.com/api/v1/event/list"
    
    params = {
        "sportId": config['sport_id'],
        "date": config['date']
    }
    
    headers = {
        "User-Agent": config['user_agent']
    }

    print(f"Consultando datos para la fecha: {config['date']}...")
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status() 
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error al conectar con la API: {e}")
        return None

def save_to_csv(events, filename):
    # Extraemos la lista de eventos del JSON
    events_list = events.get('events', [])
    
    if not events_list:
        print("No se encontraron eventos para esta fecha.")
        return

    # Definimos las columnas que queremos guardar
    # Nota: Guardamos el ID del evento, que es la llave para entrar a ver los jugadores
    fieldnames = ['event_id', 'home_team', 'away_team', 'status']

    with open(filename, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for event in events_list:
            writer.writerow({
                'event_id': event.get('id'),
                'home_team': event.get('homeTeam', {}).get('name'),
                'away_team': event.get('awayTeam', {}).get('name'),
                'status': event.get('status', {}).get('type')
            })
    
    print(f"✅ Datos guardados exitosamente en {filename}. Total eventos: {len(events_list)}")

def main():
    # 1. Cargar configuración
    config = load_config()
    
    # 2. Obtener datos de la API
    data = get_matches_data(config)
    
    if data:
        # 3. Guardar en CSV
        save_to_csv(data, config['output_file'])

if __name__ == "__main__":
    main()
