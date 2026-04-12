import requests
from datetime import datetime, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
}

hoy = datetime.now().strftime("%Y-%m-%d")
ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

for fecha in [ayer, hoy]:
    print(f"\n=== {fecha} ===")
    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{fecha}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        print(f"Status HTTP: {r.status_code}")
        data = r.json()
        eventos = data.get("events", [])
        print(f"Total eventos: {len(eventos)}")

        # Mostrar categorias unicas
        categorias = {}
        estados = {}
        for e in eventos:
            cat_id = e.get("tournament", {}).get("category", {}).get("id")
            cat_name = e.get("tournament", {}).get("category", {}).get("name", "?")
            estado = e.get("status", {}).get("type", {}).get("name", "?")
            categorias[cat_id] = cat_name
            estados[estado] = estados.get(estado, 0) + 1

        print(f"Estados: {estados}")
        print(f"IDs de categorias ATP/WTA:")
        for cid, cname in sorted(categorias.items(), key=lambda x: str(x[0])):
            if any(k in str(cname).upper() for k in ["ATP", "WTA"]):
                print(f"  id={cid} → {cname}")

    except Exception as e:
        print(f"ERROR: {e}")
