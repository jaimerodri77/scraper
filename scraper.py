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

CARPETA_SALIDA = "datos"
ARCHIVO_SALIDA = os.path.join(CARPETA_SALIDA, f"tenis_{datetime.now().year}.csv")

FUENTES = [
    {
        "url": "https://www.flashscore.com/tennis/atp-singles/results/",
        "circuito": "ATP",
    },
    {
        "url": "https://www.flashscore.com/tennis/wta-singles/results/",
        "circuito": "WTA",
    },
]


def get_html(url: str) -> str | None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page.set_default_timeout(60000)
        for attempt in range(3):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                # Esperar a que carguen los resultados dinámicos
                page.wait_for_selector(".event__match", timeout=15000)
                # Scroll para cargar más resultados
                for _ in range(5):
                    page.keyboard.press("End")
                    page.wait_for_timeout(1000)
                html = page.content()
                browser.close()
                return html
            except Exception as e:
                logging.warning(f"[{url}] Intento {attempt + 1} fallido: {e}")
                if attempt < 2:
                    time.sleep(5)
        browser.close()
        return None


def parse_matches(html: str, circuito: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    # Detectar el torneo activo
    tourney_name = "Unknown Tournament"

    for element in soup.find_all(True):
        # Encabezado de torneo
        if "event__title" in (element.get("class") or []):
            tourney_name = element.get_text(strip=True)

        # Fila de partido
        if "event__match" in (element.get("class") or []):
            try:
                home = element.select_one(".event__participant--home")
                away = element.select_one(".event__participant--away")
                score_el = element.select_one(".event__scores")

                if not home or not away or not score_el:
                    continue

                home_name = home.get_text(strip=True)
                away_name = away.get_text(strip=True)
                score_text = score_el.get_text(strip=True)

                # Determinar ganador por la clase "winner" en el nombre
                if "winner" in (home.get("class") or []):
                    winner, loser = home_name, away_name
                elif "winner" in (away.get("class") or []):
                    winner, loser = away_name, home_name
                else:
                    # Si no hay clase winner, asumir home como ganador
                    winner, loser = home_name, away_name

                if not winner or not score_text:
                    continue

                matches.append({
                    "circuito": circuito,
                    "tourney_name": tourney_name,
                    "tourney_date": datetime.now().strftime("%Y%m%d"),
                    "winner_name": winner,
                    "loser_name": loser,
                    "score": score_text,
                    "surface": None,
                    "round": None,
                    "best_of": 5 if circuito == "ATP" and "Grand Slam" in tourney_name else 3,
                })
            except Exception as e:
                logging.warning(f"Error procesando partido: {e}")
                continue

    logging.info(f"[{circuito}] Partidos parseados: {len(matches)}")
    return matches


def save_to_csv(matches: list[dict]):
    if not matches:
        logging.warning("No se encontraron partidos.")
        return

    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    df = pd.DataFrame(matches)

    if os.path.exists(ARCHIVO_SALIDA):
        old_df = pd.read_csv(ARCHIVO_SALIDA)
        df = pd.concat([old_df, df]).drop_duplicates(
            subset=["circuito", "tourney_name", "winner_name", "loser_name", "score"]
        )

    df.to_csv(ARCHIVO_SALIDA, index=False)
    logging.info(f"Total registros guardados: {len(df)} → {ARCHIVO_SALIDA}")


if __name__ == "__main__":
    all_matches = []
    for fuente in FUENTES:
        logging.info(f"Scrapeando {fuente['circuito']}: {fuente['url']}")
        html = get_html(fuente["url"])
        if html:
            all_matches.extend(parse_matches(html, fuente["circuito"]))
        else:
            logging.error(f"No se pudo obtener HTML de {fuente['url']}")

    save_to_csv(all_matches)
