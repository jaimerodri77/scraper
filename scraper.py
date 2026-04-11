import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import os

# --- CONFIGURACIÓN ---
URL_BASE = "https://www.tennis-abstract.com/results.html" 
# El archivo se llamará según el año actual (ej: tml_2026.csv)
ARCHIVO_SALIDA = f"tml_{datetime.now().year}.csv"

def get_soup():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(URL_BASE, headers=headers, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"Error conectando a la web: {e}")
        return None

def parse_matches():
    soup = get_soup()
    if not soup: return []

    all_matches = []
    tables = soup.find_all('table', {'class': 'results'})
    
    for table in tables:
        tourney_name = table.find_previous('b')
        t_name = tourney_name.text.strip() if tourney_name else "Unknown Tournament"
        
        rows = table.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 3: continue 
            
            try:
                winner = cols[0].text.strip()
                loser = cols[1].text.strip()
                score = cols[2].text.strip()
                if winner == "Winner" or winner == "": continue

                all_matches.append({
                    'tourney_id': 'S_LIVE',
                    'tourney_name': t_name,
                    'surface': 'Unknown',
                    'draw_size': None,
                    'tourney_level': 'A',
                    'indoor': 'O',
                    'tourney_date': datetime.now().strftime('%Y%m%d'),
                    'match_num': None,
                    'winner_name': winner,
                    'loser_name': loser,
                    'score': score,
                    'best_of': 3,
                    'round': 'Unknown',
                    'minutes': None
                })
            except Exception as e:
                continue
                
    return all_matches

def save_to_csv(matches):
    if not matches:
        print("No se encontraron partidos nuevos.")
        return

    df = pd.DataFrame(matches)
    if os.path.exists(ARCHIVO_SALIDA):
        old_df = pd.read_csv(ARCHIVO_SALIDA)
        df = pd.concat([old_df, df]).drop_duplicates(subset=['winner_name', 'loser_name', 'score'])

    df.to_csv(ARCHIVO_SALIDA, index=False)
    print(f"✅ Guardados {len(matches)} partidos en {ARCHIVO_SALIDA}")

if __name__ == "__main__":
    matches_data = parse_matches()
    save_to_csv(matches_data)
