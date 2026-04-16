import pandas as pd
import os
import time
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

CARPETA_SALIDA = "datos"


def api_get(page, url: str) -> dict:
    """Realiza peticion GET a la API de SofaScore."""
    try:
        time.sleep(0.7)
        response = page.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.sofascore.com/",
                "Origin": "https://www.sofascore.com",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            },
            timeout=30000,
        )
        if response.status == 200:
            return response.json()
        logging.warning(f"Status {response.status} en {url}")
        return {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}


def buscar_player_id(page, nombre_jugador: str) -> int | None:
    """
    Busca el ID del jugador en SofaScore.
    Prueba múltiples endpoints de búsqueda por si cambia la API.
    """
    query = nombre_jugador.strip().replace(" ", "%20")

    # --- Endpoint 1: /search/all (estructura nueva) ---
    url1 = f"https://api.sofascore.com/api/v1/search/all?q={query}"
    data = api_get(page, url1)

    if data:
        # Estructura nueva: {"players": [{"player": {...}}, ...]}
        for jugador_wrap in data.get("players", []):
            jugador = jugador_wrap.get("player") or jugador_wrap
            sport = jugador.get("sport", {})
            if isinstance(sport, dict) and sport.get("name", "").lower() == "tennis":
                pid = jugador.get("id")
                if pid:
                    return pid

        # Estructura vieja: {"results": [{"type": "players", "entities": [...]}]}
        for categoria in data.get("results", []):
            tipo = categoria.get("type", "")
            entidades = categoria.get("entities", [])
            if tipo == "players" or entidades:
                for entidad in entidades:
                    sport = entidad.get("sport", {})
                    if isinstance(sport, dict) and sport.get("name", "").lower() == "tennis":
                        pid = entidad.get("id")
                        if pid:
                            return pid

        # Estructura plana: lista de jugadores directamente
        if isinstance(data, list):
            for jugador in data:
                sport = jugador.get("sport", {})
                if isinstance(sport, dict) and sport.get("name", "").lower() == "tennis":
                    pid = jugador.get("id")
                    if pid:
                        return pid

    # --- Endpoint 2: /search/player-team-unique-tournament ---
    url2 = f"https://api.sofascore.com/api/v1/search/player-team-unique-tournament?q={query}&sport=tennis"
    data2 = api_get(page, url2)

    if data2:
        for jugador_wrap in data2.get("players", []):
            jugador = jugador_wrap.get("player") or jugador_wrap
            pid = jugador.get("id")
            if pid:
                return pid

    # --- Endpoint 3: suggest (endpoint legacy) ---
    url3 = f"https://api.sofascore.com/api/v1/suggest?q={query}"
    data3 = api_get(page, url3)

    if data3:
        for key in ("players", "results"):
            for item in data3.get(key, []):
                jugador = item.get("player") or item
                sport = jugador.get("sport", {})
                if isinstance(sport, dict) and sport.get("name", "").lower() == "tennis":
                    pid = jugador.get("id")
                    if pid:
                        return pid

    return None


def simplificar_nombre(nombre: str) -> list[str]:
    """
    Genera variantes del nombre para reintentar la búsqueda.
    Ej: "A. Blinkova" -> ["Blinkova", "Anna Blinkova"]
    """
    variantes = []
    partes = nombre.strip().split()

    # Sin iniciales (solo apellido si hay inicial al inicio)
    sin_inicial = [p for p in partes if len(p) > 2 or not p.endswith(".")]
    if sin_inicial and sin_inicial != partes:
        variantes.append(" ".join(sin_inicial))

    # Solo la última palabra (apellido)
    if len(partes) > 1:
        variantes.append(partes[-1])

    # Sin acentos
    nombre_ascii = nombre.encode("ascii", "ignore").decode("ascii")
    if nombre_ascii != nombre:
        variantes.append(nombre_ascii)

    return variantes


def get_player_data(page, player_id: int) -> dict | None:
    """Obtiene datos del jugador desde la API de SofaScore."""
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}")
    jugador = data.get("player")

    if not jugador:
        return None

    fecha_nac = None
    if jugador.get("dateOfBirthTimestamp"):
        try:
            fecha_nac = datetime.utcfromtimestamp(
                jugador["dateOfBirthTimestamp"]
            ).strftime("%Y-%m-%d")
        except Exception:
            pass

    pais = jugador.get("country", {})
    if not isinstance(pais, dict):
        pais = {}

    return {
        "player_id": player_id,
        "nombre": jugador.get("name"),
        "nombre_corto": jugador.get("shortName"),
        "fecha_nacimiento": fecha_nac,
        "edad": jugador.get("age"),
        "mano_dominante": jugador.get("plays"),
        "altura_cm": jugador.get("height"),
        "peso_kg": jugador.get("weight"),
        "pais": pais.get("name"),
        "pais_codigo": pais.get("alpha2"),
        "genero": jugador.get("gender"),
        "actualizado": datetime.now().strftime("%Y-%m-%d"),
    }


def normalizar_mano(mano_raw: str) -> str | None:
    """Normaliza el valor de mano dominante."""
    if not mano_raw:
        return None
    mano_raw = mano_raw.lower()
    if "right" in mano_raw:
        return "R"
    elif "left" in mano_raw:
        return "L"
    return None


def get_ranking(page, player_id: int) -> dict:
    """Obtiene el ranking del jugador."""
    resultado = {}
    data = api_get(page, f"https://api.sofascore.com/api/v1/player/{player_id}/rankings")

    for r in data.get("rankings", []):
        tipo = r.get("type", "").lower()
        pos = r.get("ranking")
        if "double" in tipo:
            resultado["ranking_dobles"] = pos
        else:
            resultado["ranking_singles"] = pos

    return resultado


def es_jugador_dobles(nombre: str) -> bool:
    """Detecta si el nombre es de un equipo de dobles."""
    return "/" in nombre


def main():
    archivo_pendientes = os.path.join(CARPETA_SALIDA, "jugadores_pendientes.csv")
    archivo_completos = os.path.join(CARPETA_SALIDA, "jugadores_info.csv")

    print("=" * 60)
    print("BUSCADOR DE INFORMACION DE JUGADORES - SOFASCORE")
    print("=" * 60)

    if not os.path.exists(archivo_pendientes):
        print("[!] No existe el archivo de jugadores pendientes.")
        print("    Ejecuta primero: python extraer_jugadores_csv.py")
        return

    df_pendientes = pd.read_csv(archivo_pendientes)
    print(f"[*] Jugadores pendientes: {len(df_pendientes)}")

    df_individuales = df_pendientes[~df_pendientes["nombre"].apply(es_jugador_dobles)]
    print(f"[*] Jugadores individuales (sin dobles): {len(df_individuales)}")

    if os.path.exists(archivo_completos):
        df_existentes = pd.read_csv(archivo_completos)
        nombres_existentes = set(df_existentes["nombre"].dropna().unique())
        player_ids_existentes = set(
            df_existentes["player_id"].dropna().astype(int).unique()
        )
        print(f"[*] Jugadores ya procesados: {len(nombres_existentes)}")
    else:
        nombres_existentes = set()
        player_ids_existentes = set()
        df_existentes = pd.DataFrame()

    df_nuevos = df_individuales[~df_individuales["nombre"].isin(nombres_existentes)]
    print(f"[*] Jugadores nuevos a procesar: {len(df_nuevos)}")

    if len(df_nuevos) == 0:
        print("\n[OK] No hay jugadores nuevos para procesar.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        print("[*] Iniciando navegador y cargando SofaScore...")
        page.goto("https://www.sofascore.com/tennis")
        page.wait_for_timeout(5000)

        jugadores_encontrados = []
        total = len(df_nuevos)
        errores = 0
        no_encontrados = []

        print(f"[*] Procesando {total} jugadores...\n")

        for i, (_, row) in enumerate(df_nuevos.iterrows(), 1):
            nombre = row["nombre"]
            print(f"[{i}/{total}] {nombre[:50]}", end=" -> ", flush=True)

            try:
                # Intento 1: nombre original
                player_id = buscar_player_id(page, nombre)

                # Intento 2: variantes simplificadas
                if not player_id:
                    for variante in simplificar_nombre(nombre):
                        player_id = buscar_player_id(page, variante)
                        if player_id:
                            print(f"(variante: '{variante}') ", end="", flush=True)
                            break

                if not player_id:
                    print("NO ENCONTRADO")
                    no_encontrados.append(nombre)
                    errores += 1
                    continue

                if player_id in player_ids_existentes:
                    print(f"ya existe (id={player_id})")
                    continue

                datos = get_player_data(page, player_id)
                if not datos:
                    print("sin datos")
                    no_encontrados.append(f"{nombre} (sin datos)")
                    errores += 1
                    continue

                ranking = get_ranking(page, player_id)
                datos.update(ranking)
                datos["mano"] = normalizar_mano(datos.get("mano_dominante"))

                jugadores_encontrados.append(datos)
                player_ids_existentes.add(player_id)

                print(
                    f"OK | id={player_id} | "
                    f"{datos.get('pais', 'N/A')} | "
                    f"singles={ranking.get('ranking_singles', '-')}"
                )

            except Exception as e:
                logging.error(f"Error procesando {nombre}: {e}")
                errores += 1
                continue

        browser.close()

    print(f"\n{'='*60}")
    print(f"[*] Jugadores encontrados: {len(jugadores_encontrados)}")
    print(f"[*] No encontrados / errores: {errores}")

    if no_encontrados:
        print(f"\n[!] Jugadores no encontrados ({len(no_encontrados)}):")
        for nombre in no_encontrados[:20]:
            print(f"    - {nombre}")

    if jugadores_encontrados:
        df_nuevos_datos = pd.DataFrame(jugadores_encontrados)

        if len(df_existentes) > 0:
            df_final = pd.concat([df_existentes, df_nuevos_datos], ignore_index=True)
            df_final = df_final.drop_duplicates(subset=["player_id"], keep="last")
        else:
            df_final = df_nuevos_datos

        df_final.to_csv(archivo_completos, index=False)
        print(f"\n[OK] Archivo guardado: {archivo_completos}")
        print(f"     Total jugadores en archivo: {len(df_final)}")

        con_mano = df_final[df_final["mano"].notna()]
        print(f"\n[*] Jugadores con mano dominante: {len(con_mano)}/{len(df_final)}")
        print(f"    - Derechos (R): {len(con_mano[con_mano['mano'] == 'R'])}")
        print(f"    - Zurdos (L):   {len(con_mano[con_mano['mano'] == 'L'])}")
    else:
        print("\n[!] No se encontraron jugadores nuevos.")


if __name__ == "__main__":
    main()
