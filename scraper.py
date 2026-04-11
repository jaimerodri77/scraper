import pandas as pd
from datetime import datetime
import os
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

URL_BASE = "https://www.tennis-abstract.com/results.html"
ARCHIVO_SALIDA = f"tml_{datetime.now().year}.csv"

def get_html():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL_BASE, wait_until="networkidle")
        html = page.content()
        browser.close()
        return html

def parse_matches():
    html = get_html()
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    all_matches = []
    tables = soup.find_all("table", {"class": "results"})

    for table in tables:
        tourney_name = table.find_previous("b")
        t_name = tourney_name.text.strip() if tourney_name else "Unknown Tournament"

        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            try:
                winner = cols[0].text.strip()
                loser = cols[1].text.strip()
                score = cols[2].text.strip()
                if winner == "Winner" or winner == "":
                    continue

                all_matches.append({
                    "tourney_id": "S_LIVE",
                    "tourney_name": t_name,
                    "surface": "Unknown",
                    "draw_size": None,
                    "tourney_level": "A",
                    "indoor": "O",
                    "tourney_date": datetime.now().strftime("%Y%m%d"),
                    "match_num": None,
                    "winner_name": winner,
                    "loser_name": loser,
                    "score": score,
                    "best_of": 3,
                    "round": "Unknown",
                    "minutes": None
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
        df = pd.concat([old_df, df]).drop_duplicates(subset=["winner_name", "loser_name", "score"])

    df.to_csv(ARCHIVO_SALIDA, index=False)
    print(f"Guardados {len(matches)} partidos en {ARCHIVO_SALIDA}")

if __name__ == "__main__":
    matches_data = parse_matches()
    save_to_csv(matches_data)
