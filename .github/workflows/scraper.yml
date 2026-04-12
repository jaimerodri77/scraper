import pandas as pd
from datetime import datetime
import os
import time
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

URL_BASE = "https://www.tennis-abstract.com/results.html"
ARCHIVO_SALIDA = f"tml_{datetime.now().year}.csv"

def get_html():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            java_script_enabled=True,
        )
        page = context.new_page()

        # Ocultar automatizacion
        page.add_init_script("""
            Object.defineProperty(navigator, "webdriver", {get: () => undefined});
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, "plugins", {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, "languages", {get: () => ["en-US", "en"]});
        """)

        page.set_default_timeout(60000)
        for attempt in range(3):
            try:
                print(f"Intento {attempt+1} de conexion...")
                page.goto(URL_BASE, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(8000)
                html = page.content()
                browser.close()
                print(f"HTML obtenido: {len(html)} caracteres")
                return html
            except Exception as e:
                print(f"Intento {attempt+1} fallido: {e}")
                if attempt < 2:
                    time.sleep(5)
        browser.close()
        return None

def parse_matches():
    html = get_html()
    if not html:
        print("No se pudo obtener el HTML de la pagina")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Debug: ver que tablas encuentra
    all_tables = soup.find_all("table")
    print(f"Tablas encontradas: {len(all_tables)}")
    results_tables = soup.find_all("table", {"class": "results"})
    print(f"Tablas con clase results: {len(results_tables)}")

    all_matches = []
    for table in results_tables:
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
