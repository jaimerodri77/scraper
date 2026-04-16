import pandas as pd
import os
import time
import json
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

CARPETA_SALIDA = "datos"


class SofaScoreClient:
    """
    Cliente que usa Playwright para hacer peticiones a SofaScore
    interceptando el token de sesión real del navegador.
    """

    def __init__(self, page):
        self.page = page
        self.session_headers = {}

    def inicializar(self):
        """Carga SofaScore y extrae headers/cookies de sesión reales."""
        print("[*] Cargando SofaScore y extrayendo sesión...")

        intercepted_headers = {}

        def on_request(request):
            if "api.sofascore.com/api/v1" in request.url:
                intercepted_headers.update(dict(request.headers))

        self.page.on("request", on_request)

        self.page.goto("https://www.sofascore.com/tennis", wait_until="domcontentloaded")
        self.page.wait_for_timeout(6000)

        try:
            self.page.goto(
                "https://www.sofascore.com/tennis/atp-singles",
                wait_until="domcontentloaded",
                timeout=15000
            )
            self.page.wait_for_timeout(4000)
        except Exception:
            pass

        if intercepted_headers:
            self.session_headers = {
                k: v for k, v in intercepted_headers.items()
                if k.lower() in (
                    "cookie", "x-requested-with", "accept", "accept-language",
                    "user-agent", "referer", "origin", "sec-fetch-site",
                    "sec-fetch-mode", "sec-ch-ua", "sec-ch-ua-platform",
                    "authorization", "x-auth-token"
                )
            }
            print(f"[*] Headers capturados: {list(self.session_headers.keys())}")
        else:
            print("[!] No se capturaron headers de API — usando headers manuales")

        self.session_headers.update({
            "Accept": "application/json",
            "Referer": "https://www.sofascore.com/",
            "Origin": "https://www.sofascore.com",
        })

        cookies = self.page.context.cookies()
        if cookies:
            cookies_str = "; ".join(
                f"{c['name']}={c['value']}" for c in cookies
                if "sofascore" in c.get("domain", "")
            )
            if cookies_str:
                self.session_headers["Cookie"] = cookies_str
                print(f"[*] Cookies capturadas: {len(cookies)}")

    def get(self, url: str) -> dict:
        """Hace una petición GET a la API usando los headers de sesión reales."""
        try:
            time.sleep(0.8)
            response = self.page.request.get(
                url,
                headers=self.session_headers,
                timeout=30000,
            )
            if response.status == 200:
                return response.json()
            elif response.status == 429:
                logging.warning("Rate limit alcanzado, esperando 15s...")
                time.sleep(15)
                response = self.page.request.get(url, headers=self.session_headers, timeout=30000)
                if response.status == 200:
                    return response.json()
            elif response.status == 403:
                logging.warning(f"403 en {url} — refrescando sesión...")
                self.page.goto("https://www.sofascore.com/tennis", wait_until="domcontentloaded")
                self.page.wait_for_timeout(3000)
                response = self.page.request.get(url, headers=self.session_headers, timeout=30000)
                if response.status == 200:
                    return response.json()
            logging.warning(f"Status {response.status} en {url}")
            return {}
        except Exception as e:
            logging.warning(f"Error en {url}: {e}")
            return {}

    def buscar_jugador(self, nombre: str) -> int | None:
        """Busca el player_id de un jugador de tenis en SofaScore."""
        query = nombre.strip().replace(" ", "%20")

        data = self.get(f"https://api.sofascore.com/api/v1/search/all?q={query}")
        if data:
            pid = self._extraer_id_tennis(data)
            if pid:
                return pid

        data2 = self.get(
            f"https://api.sofascore.com/api/v1/search/player-team-unique-tournament"
            f"?q={query}&sport=tennis"
        )
        if data2:
            pid = self._extraer_id_tennis(data2)
            if pid:
                return pid

        return None

    def _extraer_id_tennis(self, data: dict) -> int | None:
        """Extrae el player_id de tenis de distintas estructuras de respuesta."""
        if not data or not isinstance(data, dict):
            return None

        # Estructura nueva: {"players": [{"player": {...}}, ...]}
        for wrap in data.get("players", []):
            jugador = wrap.get("player") or wrap
            if self._es_tennis(jugador):
                pid = jugador.get("id")
                if pid:
                    return pid

        # Estructura vieja: {"results": [{"type": "players", "entities": [...]}]}
        for categoria in data.get("results", []):
            for entidad in categoria.get("entities", []):
                if self._es_tennis(entidad):
                    pid = entidad.get("id")
                    if pid:
                        return pid

        return None

    def _es_tennis(self, jugador: dict) -> bool:
        sport = jugador.get("sport", {})
        if isinstance(sport, dict):
            return sport.get("name", "").lower() == "tennis"
        if isinstance(sport, str):
            return sport.lower() == "tennis"
        return True

    def get_player_data(self, player_id: int) -> dict | None:
        data = self.get(f"https://api.sofascore.com/api/v1/player/{player_id}")
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

    def get_ranking(self, player_id: int) -> dict:
        resultado = {}
        data = self.get(f"https://api.sofascore.com/api/v1/player/{player_id}/rankings")
        for r in data.get("rankings", []):
            tipo = r.get("type", "").lower()
            pos = r.get("ranking")
            if "double" in tipo:
                resultado["ranking_dobles"] = pos
            else:
                resultado["ranking_singles"] = pos
        return resultado


def normalizar_mano(mano_raw: str) -> str | None:
    if not mano_raw:
        return None
    mano_raw = mano_raw.lower()
    if "right" in mano_raw:
        return "R"
    elif "left" in mano_raw:
        return "L"
    return None


def es_jugador_dobles(nombre: str) -> bool:
    return "/" in nombre


def variantes_nombre(nombre: str) -> list:
    variantes = []
    partes = nombre.strip().split()

    if len(partes) > 1:
        variantes.append(partes[-1])

    sin_inicial = [p for p in partes if not (len(p) <= 2 and p.endswith("."))]
    if sin_inicial and sin_inicial != partes:
        variantes.append(" ".join(sin_inicial))

    ascii_nombre = nombre.encode("ascii", "ignore").decode("ascii")
    if ascii_nombre != nombre:
        variantes.append(ascii_nombre)

    return list(dict.fromkeys(variantes))


def _guardar_parcial(df_existentes, jugadores_encontrados, archivo):
    df_nuevos_datos = pd.DataFrame(jugadores_encontrados)
    if len(df_existentes) > 0:
        df_final = pd.concat([df_existentes, df_nuevos_datos], ignore_index=True)
        df_final = df_final.drop_duplicates(subset=["player_id"], keep="last")
    else:
        df_final = df_nuevos_datos
    df_final.to_csv(archivo, index=False)
    return df_final


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
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()

        client = SofaScoreClient(page)
        client.inicializar()

        jugadores_encontrados = []
        total = len(df_nuevos)
        errores = 0
        no_encontrados = []

        print(f"[*] Procesando {total} jugadores...\n")

        for i, (_, row) in enumerate(df_nuevos.iterrows(), 1):
            nombre = row["nombre"]
            print(f"[{i}/{total}] {nombre[:45]}", end=" -> ", flush=True)

            try:
                player_id = client.buscar_jugador(nombre)

                variante_usada = None
                if not player_id:
                    for v in variantes_nombre(nombre):
                        player_id = client.buscar_jugador(v)
                        if player_id:
                            variante_usada = v
                            break

                if not player_id:
                    print("NO ENCONTRADO")
                    no_encontrados.append(nombre)
                    errores += 1
                    continue

                if player_id in player_ids_existentes:
                    print(f"ya existe (id={player_id})")
                    continue

                datos = client.get_player_data(player_id)
                if not datos:
                    print("sin datos")
                    no_encontrados.append(f"{nombre} (sin datos)")
                    errores += 1
                    continue

                ranking = client.get_ranking(player_id)
                datos.update(ranking)
                datos["mano"] = normalizar_mano(datos.get("mano_dominante"))

                jugadores_encontrados.append(datos)
                player_ids_existentes.add(player_id)

                extra = f" [variante: {variante_usada}]" if variante_usada else ""
                print(
                    f"OK | id={player_id} | "
                    f"{datos.get('pais', '?')} | "
                    f"S={ranking.get('ranking_singles', '-')}{extra}"
                )

                # Guardar cada 50 jugadores para no perder progreso
                if len(jugadores_encontrados) % 50 == 0:
                    _guardar_parcial(df_existentes, jugadores_encontrados, archivo_completos)
                    print(f"\n  [GUARDADO PARCIAL: {len(jugadores_encontrados)} jugadores]\n")

            except Exception as e:
                logging.error(f"Error procesando {nombre}: {e}")
                errores += 1

        browser.close()

    print(f"\n{'='*60}")
    print(f"[*] Jugadores encontrados: {len(jugadores_encontrados)}")
    print(f"[*] No encontrados: {errores}")

    if no_encontrados:
        archivo_no_enc = os.path.join(CARPETA_SALIDA, "jugadores_no_encontrados.txt")
        with open(archivo_no_enc, "w", encoding="utf-8") as f:
            f.write("\n".join(no_encontrados))
        print(f"[!] Lista de no encontrados: {archivo_no_enc}")
        for n in no_encontrados[:10]:
            print(f"    - {n}")

    if jugadores_encontrados:
        df_final = _guardar_parcial(df_existentes, jugadores_encontrados, archivo_completos)
        print(f"\n[OK] Archivo final: {archivo_completos}")
        print(f"     Total jugadores: {len(df_final)}")

        con_mano = df_final[df_final["mano"].notna()]
        print(f"\n[*] Con mano dominante: {len(con_mano)}/{len(df_final)}")
        print(f"    Derechos (R): {len(con_mano[con_mano['mano'] == 'R'])}")
        print(f"    Zurdos   (L): {len(con_mano[con_mano['mano'] == 'L'])}")
    else:
        print("\n[!] No se encontraron jugadores nuevos.")


if __name__ == "__main__":
    main()
