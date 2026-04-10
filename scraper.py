"""
Tennis Stats Scraper - ATP (avanzadas) + WTA (básicas)
=====================================================
ATP: Endpoints JSON internos de Infosys/ATP (sin API key)
     Stats: aces, df, % saque, velocidad, puntos ganados, break points, etc.
WTA: Scraping de wtatennis.com resultados
     Stats: ganador, perdedor, score, torneo, ronda, superficie

No requiere ninguna API key ni registro.
"""

import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
import time
import os
import re

# ── Configuración ──────────────────────────────────────────────────────────────
YEAR          = datetime.now().year
CSV_ATP       = f"atp_stats_{YEAR}.csv"
CSV_WTA       = f"wta_stats_{YEAR}.csv"
DELAY         = 2   # segundos entre requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.atptour.com/",
}

# ── Endpoints ATP/Infosys ─────────────────────────────────────────────────────
ATP_CALENDAR   = f"https://www.atptour.com/en/scores/results-archive?year={YEAR}"
ATP_TOURNEY    = "https://www.atptour.com/en/scores/results/{slug}/{tourn_id}/{year}/results"
ATP_KEYSTATS   = (
    "https://itp-atp-sls.infosys-platforms.com/static/prod/stats-plus"
    "/{year}/{tourn_id}/{match_id}/keystats.json"
)
ATP_RALLY      = (
    "https://itp-atp-sls.infosys-platforms.com/static/prod/rally-analysis"
    "/{year}/{tourn_id}/{match_id}/data.json"
)

# ── Endpoints WTA ─────────────────────────────────────────────────────────────
WTA_RESULTS    = f"https://www.wtatennis.com/scores/results/{YEAR}"

# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN ATP
# ══════════════════════════════════════════════════════════════════════════════

def atp_get_tournaments():
    print(f"\n📅 [ATP] Obteniendo torneos {YEAR}...")
    try:
        r = requests.get(ATP_CALENDAR, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        torneos = []
        seen    = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if f"/en/scores/results/" in href and f"/{YEAR}/results" in href:
                parts = href.strip("/").split("/")
                if len(parts) >= 6:
                    slug     = parts[3]
                    tourn_id = parts[4]
                    key      = (slug, tourn_id)
                    if key not in seen:
                        seen.add(key)
                        name = a.get_text(strip=True) or slug
                        torneos.append({"name": name, "slug": slug, "id": tourn_id, "tour": "ATP"})
        print(f"   ✅ {len(torneos)} torneos ATP encontrados")
        return torneos
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return []


def atp_get_match_ids(tourn):
    url = ATP_TOURNEY.format(slug=tourn["slug"], tourn_id=tourn["id"], year=YEAR)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        ids  = []
        # data-match-id en elementos HTML
        for el in soup.find_all(attrs={"data-match-id": True}):
            mid = el["data-match-id"]
            if mid and mid not in ids:
                ids.append(mid)
        # Fallback: buscar en scripts
        if not ids:
            for script in soup.find_all("script"):
                text  = script.string or ""
                found = re.findall(r'"(?:matchId|match_id)"\s*:\s*"([^"]+)"', text)
                for f in found:
                    if f not in ids:
                        ids.append(f)
        return ids
    except Exception as e:
        print(f"      ⚠️  Error en {tourn['name']}: {e}")
        return []


def atp_get_keystats(tourn_id, match_id):
    url = ATP_KEYSTATS.format(year=YEAR, tourn_id=tourn_id, match_id=match_id)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def atp_get_rally(tourn_id, match_id):
    url = ATP_RALLY.format(year=YEAR, tourn_id=tourn_id, match_id=match_id)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def atp_parse_match(ks_raw, rally_raw, tourn, match_id):
    """Combina keystats + rally analysis en filas planas por set."""
    if not ks_raw or not ks_raw.get("matchCompleted"):
        return []

    players = ks_raw.get("players", [])
    if len(players) < 2:
        return []

    p1 = players[0]
    p2 = players[1]
    rows = []

    for set_key, stats_list in ks_raw.get("setStats", {}).items():
        set_num = int(set_key.replace("set", ""))
        if not stats_list:
            continue

        row = {
            "tour":          "ATP",
            "year":          YEAR,
            "tournament":    tourn["name"],
            "tourn_id":      tourn["id"],
            "match_id":      match_id,
            "set":           "total" if set_num == 0 else set_num,
            "p1_name":       p1.get("player1Name", ""),
            "p1_id":         p1.get("player1Id",   ""),
            "p1_seed":       p1.get("seed",         ""),
            "p2_name":       p2.get("player1Name", ""),
            "p2_id":         p2.get("player1Id",   ""),
            "p2_seed":       p2.get("seed",         ""),
        }

        # Key-stats dinámicas
        for stat in stats_list:
            name = (stat.get("name", "")
                    .lower()
                    .replace(" ", "_")
                    .replace("%", "pct")
                    .replace("/", "_per_"))
            row[f"p1_{name}"] = stat.get("player1", "")
            row[f"p2_{name}"] = stat.get("player2", "")

        # Rally analysis (solo set total = set_num 0)
        if rally_raw and set_num == 0:
            try:
                rally = rally_raw.get("rallyAnalysis", {})
                for side, prefix in [("home", "p1"), ("away", "p2")]:
                    rd = rally.get(side, {})
                    row[f"{prefix}_rally_avg_len"]       = rd.get("averageRallyLength", "")
                    row[f"{prefix}_rally_max_len"]       = rd.get("maxRallyLength",     "")
                    row[f"{prefix}_winners_off_rally"]   = rd.get("winnersOffRally",    "")
                    row[f"{prefix}_errors_off_rally"]    = rd.get("errorsOffRally",     "")
            except Exception:
                pass

        row["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        rows.append(row)

    return rows


def scrape_atp():
    print("\n" + "═" * 60)
    print("  🎾 SCRAPING ATP")
    print("═" * 60)

    ids_existentes, df_old = cargar_existentes(CSV_ATP)
    print(f"📂 Partidos ATP ya guardados: {len(ids_existentes)}")

    torneos  = atp_get_tournaments()
    all_rows = []

    for tourn in torneos:
        print(f"\n🏆 {tourn['name']} ({tourn['id']})")
        match_ids = atp_get_match_ids(tourn)
        print(f"   🔢 {len(match_ids)} partidos")

        nuevos = 0
        for mid in match_ids:
            if mid in ids_existentes:
                continue
            time.sleep(DELAY)
            ks   = atp_get_keystats(tourn["id"], mid)
            time.sleep(0.5)
            rally = atp_get_rally(tourn["id"], mid)
            filas = atp_parse_match(ks, rally, tourn, mid)
            if filas:
                all_rows.extend(filas)
                ids_existentes.add(mid)
                nuevos += 1
                print(f"   ✅ {mid}: {len(filas)} sets")

        if nuevos == 0:
            print("   ℹ️  Sin partidos nuevos")

    guardar_csv(all_rows, df_old, CSV_ATP, "ATP")


# ══════════════════════════════════════════════════════════════════════════════
#  SECCIÓN WTA
# ══════════════════════════════════════════════════════════════════════════════

def wta_get_results():
    """Scraping de resultados WTA desde wtatennis.com."""
    print(f"\n📅 [WTA] Obteniendo resultados {YEAR}...")
    rows = []
    try:
        r = requests.get(WTA_RESULTS, headers={**HEADERS, "Referer": "https://www.wtatennis.com/"}, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Buscar bloques de partidos — la WTA los agrupa por torneo
        match_blocks = soup.find_all(class_=re.compile(r"match|result|score", re.I))

        for block in match_blocks:
            try:
                # Extraer jugadoras
                players = block.find_all(class_=re.compile(r"player|name", re.I))
                if len(players) < 2:
                    continue
                p1 = players[0].get_text(strip=True)
                p2 = players[1].get_text(strip=True)
                if not p1 or not p2 or p1 == p2:
                    continue

                # Score
                score_el = block.find(class_=re.compile(r"score", re.I))
                score    = score_el.get_text(strip=True) if score_el else ""

                # Torneo
                tourney_el = block.find_previous(class_=re.compile(r"tournament|event|tourney", re.I))
                tourney    = tourney_el.get_text(strip=True) if tourney_el else ""

                # Round
                round_el = block.find(class_=re.compile(r"round", re.I))
                rnd      = round_el.get_text(strip=True) if round_el else ""

                # ID único
                match_id = f"wta_{p1[:4]}_{p2[:4]}_{score[:6]}".replace(" ", "")

                rows.append({
                    "tour":       "WTA",
                    "year":       YEAR,
                    "tournament": tourney,
                    "match_id":   match_id,
                    "set":        "total",
                    "p1_name":    p1,
                    "p2_name":    p2,
                    "score":      score,
                    "round":      rnd,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
            except Exception:
                continue

        # Fallback: buscar en JSON embebido en scripts (Next.js / React)
        if not rows:
            rows = wta_parse_json_scripts(soup)

        print(f"   ✅ {len(rows)} partidos WTA encontrados")
    except Exception as e:
        print(f"   ❌ Error WTA: {e}")

    return rows


def wta_parse_json_scripts(soup):
    """Intenta extraer datos de JSON embebido en scripts (sites modernos)."""
    rows = []
    for script in soup.find_all("script"):
        text = script.string or ""
        if "matchScore" not in text and "playerName" not in text:
            continue
        try:
            # Buscar bloques JSON con datos de partidos
            matches = re.findall(
                r'\{[^{}]*"playerName"[^{}]*"matchScore"[^{}]*\}', text
            )
            for m in matches:
                import json as _json
                data = _json.loads(m)
                rows.append({
                    "tour":       "WTA",
                    "year":       YEAR,
                    "tournament": data.get("tournamentName", ""),
                    "match_id":   f"wta_{data.get('matchId','')}",
                    "set":        "total",
                    "p1_name":    data.get("playerName", ""),
                    "p2_name":    data.get("opponentName", ""),
                    "score":      data.get("matchScore", ""),
                    "round":      data.get("round", ""),
                    "surface":    data.get("surface", ""),
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
        except Exception:
            continue
    return rows


def scrape_wta():
    print("\n" + "═" * 60)
    print("  🎾 SCRAPING WTA")
    print("═" * 60)

    ids_existentes, df_old = cargar_existentes(CSV_WTA)
    print(f"📂 Partidos WTA ya guardados: {len(ids_existentes)}")

    rows     = wta_get_results()
    nuevos   = [r for r in rows if r["match_id"] not in ids_existentes]

    guardar_csv(nuevos, df_old, CSV_WTA, "WTA")


# ══════════════════════════════════════════════════════════════════════════════
#  UTILIDADES COMPARTIDAS
# ══════════════════════════════════════════════════════════════════════════════

def cargar_existentes(csv_path):
    if not os.path.exists(csv_path):
        return set(), pd.DataFrame()
    try:
        df  = pd.read_csv(csv_path)
        ids = set(df["match_id"].astype(str).unique())
        return ids, df
    except Exception:
        return set(), pd.DataFrame()


def guardar_csv(new_rows, df_old, csv_path, tour_label):
    if not new_rows:
        print(f"\n⚠️  [{tour_label}] Sin datos nuevos para guardar.")
        return
    df_new = pd.DataFrame(new_rows)
    if not df_old.empty:
        df_final = pd.concat([df_old, df_new], ignore_index=True)
        df_final = df_final.drop_duplicates(subset=["match_id", "set"])
    else:
        df_final = df_new
    df_final.to_csv(csv_path, index=False)
    print(f"\n💾 [{tour_label}] {csv_path} → {len(new_rows)} nuevos | {len(df_final)} total")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"🚀 Tennis Scraper ATP+WTA - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    scrape_atp()
    scrape_wta()
    print("\n🏁 Proceso completado.")
