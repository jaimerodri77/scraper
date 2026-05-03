import pandas as pd
from datetime import datetime
import os
import logging
from curl_cffi import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")

SUPERFICIE_MAP = {
    0: "Dura",
    1: "Arcilla",
    2: "Hierba",
    3: "Moqueta",
    4: "Indoor Dura",
    "hard": "Dura",
    "clay": "Arcilla",
    "grass": "Hierba",
    "carpet": "Moqueta",
    "indoor": "Indoor",
    "indoor hard": "Indoor Dura",
}

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
_cache_superficie = {}

def api_get(url):
    try:
        response = SESSION.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logging.warning(f"Error: {e}")
    return {}

def normalizar_superficie(valor):
    if valor is None:
        return None
    try:
        return SUPERFICIE_MAP.get(int(valor), f"Tipo {valor}")
    except (ValueError, TypeError):
        pass
    return SUPERFICIE_MAP.get(str(valor).lower(), str(valor).capitalize())

def obtener_superficie(unique_id):
    if not unique_id:
        return "Desconocida"
    if unique_id in _cache_superficie:
        return _cache_superficie[unique_id]

    url = f"https://api.sofascore.com/api/v1/unique-tournament/{unique_id}"
    data = api_get(url)

    ut = data.get("uniqueTournament", {})
    ground = ut.get("groundType") or data.get("groundType")

    superficie = normalizar_superficie(ground) or "Desconocida"
    _cache_superficie[unique_id] = superficie
    logging.info(f"  Superficie unique_tournament {unique_id}: {superficie} (groundType={ground})")
    return superficie

def obtener_calendario_hoy():
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Obteniendo calendario de partidos para hoy: {hoy_str}...")

    url = f"https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/{hoy_str}"
    data = api_get(url)
    eventos = data.get("events", [])
    logging.info(f"Eventos encontrados: {len(eventos)}")

    partidos = []

    for e in eventos:
        try:
            torneo_data = e.get("tournament", {})
            torneo      = torneo_data.get("name", "Desconocido")
            torneo_id   = torneo_data.get("id", "")
            categoria   = torneo_data.get("category", {}).get("name", "")

            # uniqueTournament puede venir dentro de tournament{} o en la raiz del evento
            unique_obj = (
                torneo_data.get("uniqueTournament")
                or e.get("uniqueTournament")
                or {}
            )
            unique_id = unique_obj.get("id", "")

            # Intentar groundType directo antes de hacer llamada extra
            ground_directo = (
                torneo_data.get("groundType")
                or unique_obj.get("groundType")
                or e.get("groundType")
            )

            if ground_directo is not None:
                superficie = normalizar_superficie(ground_directo) or "Desconocida"
                if unique_id:
                    _cache_superficie[unique_id] = superficie
            else:
                superficie = obtener_superficie(unique_id)

            home    = e.get("homeTeam", {}).get("name", "Unknown")
            home_id = e.get("homeTeam", {}).get("id", "")
            away    = e.get("awayTeam", {}).get("name", "Unknown")
            away_id = e.get("awayTeam", {}).get("id", "")

            timestamp  = e.get("startTimestamp")
            hora_local = "Sin hora"
            fecha      = hoy_str
            if timestamp:
                dt         = datetime.fromtimestamp(timestamp)
                hora_local = dt.strftime("%H:%M")
                fecha      = dt.strftime("%Y-%m-%d")

            partidos.append({
                "Fecha":                         fecha,
                "Torneo":                        torneo,
                "Torneo_ID_Sofascore":           torneo_id,
                "Categoria":                     categoria,
                "Superficie":                    superficie,
                "Ronda":                         e.get("roundInfo", {}).get("name", ""),
                "Hora_Aprox":                    hora_local,
                "Jugador_Local":                 home,
                "Jugador_Local_ID_Sofascore":    home_id,
                "Jugador_Visitante":             away,
                "Jugador_Visitante_ID_Sofascore": away_id,
            })
        except Exception:
            pass

    archivo  = os.path.join("datos", "calendario.csv")
    os.makedirs("datos", exist_ok=True)
    columnas = [
        "Fecha", "Torneo", "Torneo_ID_Sofascore", "Categoria", "Superficie",
        "Ronda", "Hora_Aprox", "Jugador_Local", "Jugador_Local_ID_Sofascore",
        "Jugador_Visitante", "Jugador_Visitante_ID_Sofascore",
    ]

    if partidos:
        df = pd.DataFrame(partidos)
        df = df.sort_values(by=["Fecha", "Hora_Aprox"])
        df.to_csv(archivo, index=False, encoding="utf-8-sig")
        logging.info(f"\n¡Éxito! {len(partidos)} partidos guardados en {archivo}.")

        print("\n--- Próximos partidos de hoy (Muestra de los siguientes 15) ---")
        print(
            df.assign(VS="vs")[
                ["Fecha", "Hora_Aprox", "Categoria", "Superficie",
                 "Jugador_Local", "VS", "Jugador_Visitante"]
            ]
            .head(15)
            .to_string(index=False)
        )
        print("\n--- Superficies detectadas ---")
        print(df["Superficie"].value_counts().to_string())
    else:
        df_vacio = pd.DataFrame(columns=columnas)
        df_vacio.to_csv(archivo, index=False, encoding="utf-8-sig")
        logging.info("No se encontraron partidos. El archivo calendario.csv ha sido limpiado.")

if __name__ == "__main__":
    obtener_calendario_hoy()

