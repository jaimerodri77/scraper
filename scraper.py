import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import time

ARCHIVO_SALIDA = f"tml_{datetime.now().year}.csv"

def get_matches(date_str):
    """Obtiene partidos de tenis de Sofascore para una fecha dada."""
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{date_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    for attempt in range(3):
        try:
            print(f"Intento {attempt+1} para fecha {date_str}...")
            response = requests.get(url, headers=headers, timeout=30)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                events = data.get("events", [])
                print(f"Eventos encontrados: {len(events)}")
                return events
            else:
                print(f"Error HTTP: {response.status_code}")
        except Exception as e:
            print(f"Intento {attempt+1} fallido: {e}")
            time.sleep(3)
    return []

def parse_events(events):
    """Convierte los eventos de Sofascore en partidos para el CSV."""
    matches = []
    for event in events:
        try:
            tournament = event.get("tournament", {})
            tournament_name = tournament.get("name", "Unknown Tournament")
            category = tournament.get("category", {})
            category_name = category.get("name", "")

            # Filtrar solo ATP y WTA
            if "ATP" not in category_name and "WTA" not in category_name and "Grand Slam" not in category_name:
                continue

            home_team = event.get("homeTeam", {})
            away_team = event.get("awayTeam", {})
            home_name = home_team.get("name", "")
            away_name = away_team.get("name", "")

            if not home_name or not away_name:
                continue

            # Resultado
            home_score = event.get("homeScore", {})
            away_score = event.get("awayScore", {})
            scores = []
            for i in range(1, 6):
                hs = home_score.get(f"period{i}")
                aws = away_score.get(f"period{i}")
                if hs is not None and aws is not None:
                    scores.append(f"{hs}-{aws}")
            score_str = " ".join(scores) if scores else ""

            # Estado del partido
            status = event.get("status", {})
            status_type = status.get("type", "unknown")
            if status_type != "finished":
                continue  # Solo partidos terminados

            # Superficie
            surface = "Unknown"
            ground = event.get("ground", {})
            if ground:
                surface = ground.get("name", "Unknown")

            # Ronda
            round_info = event.get("roundInfo", {})
            round_name = round_info.get("round", "Unknown")

            # Determinar ganador y perdedor
            winner = event.get("winner", None)
            if winner is not None:
                winner_name = home_name if winner.get("id") == home_team.get("id") else away_name
                loser_name = away_name if winner.get("id") == home_team.get("id") else home_name
            else:
                winner_name = home_name
                loser_name = away_name

            matches.append({
                "tourney_id": "S_LIVE",
                "tourney_name": tournament_name,
                "surface": surface,
                "draw_size": None,
                "tourney_level": category_name,
                "indoor": "O",
                "tourney_date": date_str.replace("-", ""),
                "match_num": event.get("id", None),
                "winner_name": winner_name,
                "loser_name": loser_name,
                "score": score_str,
                "best_of": 3,
                "round": str(round_name),
                "minutes": None
            })
        except Exception as e:
            print(f"Error parseando evento: {e}")
            continue

    return matches

def save_to_csv(matches):
    if not matches:
        print("No se encontraron partidos terminados de ATP/WTA.")
        return

    df = pd.DataFrame(matches)
    if os.path.exists(ARCHIVO_SALIDA):
        old_df = pd.read_csv(ARCHIVO_SALIDA)
        df = pd.concat([old_df, df]).drop_duplicates(subset=["winner_name", "loser_name", "score"])

    df.to_csv(ARCHIVO_SALIDA, index=False)
    print(f"Guardados {len(matches)} partidos en {ARCHIVO_SALIDA}")

if __name__ == "__main__":
    # Obtener partidos de hoy y ayer
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    all_matches = []
    for date in [yesterday, today]:
        print(f"Buscando partidos para {date}...")
        events = get_matches(date)
        matches = parse_events(events)
        print(f"Partidos ATP/WTA terminados encontrados: {len(matches)}")
        all_matches.extend(matches)

    save_to_csv(all_matches)
