import pandas as pd
from datetime import datetime
import logging
import os
import time
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

URL_BASE = "https://www.tennis-abstract.com/results.html"
CARPETA_SALIDA = "datos"
ARCHIVO_SALIDA = os.path.join(CARPETA_SALIDA, f"tml_{datetime.now().year}.csv")


def get_html():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(60000)
        for attempt in range(3):
            try:
                page.goto(URL_BASE, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                html = page.content()
                browser.close()
                return html
            except Exception as e:
                logging.warning(f"Intento {attempt + 1} fallido: {e}")
                if attempt < 2:
                    time.sleep(5)
        browser.close()
        return None


def parse_matches():
    html = get_html()
    if not html:
        logging.error("No se pudo obtener el HTML de la pagina.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    all_matches = []
    tables = soup.find_all("table", {"class": "results"})

    if not tables:
        logging.warning("No se encontraron tablas con clase 'results' en el HTML.")

    for table in tables:
        # Busca el <b> más cercano que sea hermano anterior o ancestro,
        # evitando capturar cualquier <b> no relacionado del DOM.
        t_name = "Unknown Tournament"
        for sibling in table.find_all_previous():
            if sibling.name == "b" and sibling.text.strip():
                t_name = sibling.text.strip()
                break

        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            try:
                winner = cols[0].text.strip()
                loser = cols[1].text.strip()
                score = cols[2].text.strip()

                # Saltar encabezados o filas vacías
                if not winner or winner.lower() in ("winner", "w"):
                    continue
                if not loser or not score:
                    continue

                all_matches.append({
                    "tourney_id": "S_LIVE",
                    "tourney_name": t_name,
                    "surface": None,         # No disponible en la fuente
                    "draw_size": None,
                    "tourney_level": "A",
                    "indoor": None,          # No disponible en la fuente
                    "tourney_date": datetime.now().strftime("%Y%m%d"),
                    "match_num": None,
                    "winner_name": winner,
                    "loser_name": loser,
                    "score": score,
                    "best_of": 3,
                    "round": "Unknown",
                    "minutes": None,
                })
            except Exception as e:
                logging.warning(f"Error procesando fila: {e} | Fila: {row}")
                continue

    logging.info(f"Partidos parseados: {len(all_matches)}")
    return all_matches


def save_to_csv(matches):
    if not matches:
        logging.warning("No se encontraron partidos nuevos.")
        return

    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df = pd.DataFrame(matches)

    if os.path.exists(ARCHIVO_SALIDA):
        old_df = pd.read_csv(ARCHIVO_SALIDA)
        df = pd.concat([old_df, df]).drop_duplicates(
            # Incluir tourney_name para no eliminar el mismo partido en torneos distintos
            subset=["tourney_name", "winner_name", "loser_name", "score"]
        )

    df.to_csv(ARCHIVO_SALIDA, index=False)
    logging.info(f"Guardados {len(df)} registros totales en {ARCHIVO_SALIDA}")


if __name__ == "__main__":
    matches_data = parse_matches()
    save_to_csv(matches_data)
