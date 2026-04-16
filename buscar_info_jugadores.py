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
        time.sleep(0.3)  # Evitar rate limiting
        response = page.request.get(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.sofascore.com/tennis",
            },
            timeout=30000,
        )
        if response.status == 200:
            return response.json()
        return {}
    except Exception as e:
        logging.warning(f"Error en {url}: {e}")
        return {}


def buscar_player_id(page, nombre_jugador: str) -> int | None:
    """Busca el ID del jugador en SofaScore por nombre."""
    # Buscar en la API de SofaScore
    query = nombre_jugador.replace(" ", "%20")
    url = f"https://api.sofascore.com/api/v1/search?q={query}"
    
    data = api_get(page, url)
    
    if not data:
        return None
    
    # Buscar en resultados de jugadores
    jugadores = data.get("results", [])
    
    for resultado in jugadores:
        if resultado.get("type") == "player":
            player = resultado.get("player", {})
            sport = player.get("sport", {})
            
            # Verificar que sea tenis
            if sport.get("name", "").lower() == "tennis":
                return player.get("id")
    
    return None


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
        except:
            pass
    
    pais = jugador.get("country", {}) if isinstance(jugador.get("country"), dict) else {}
    
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
    
    # Verificar que existe el archivo de pendientes
    if not os.path.exists(archivo_pendientes):
        print("[!] No existe el archivo de jugadores pendientes.")
        print("    Ejecuta primero: python extraer_jugadores_csv.py")
        return
    
    # Cargar jugadores pendientes
    df_pendientes = pd.read_csv(archivo_pendientes)
    print(f"[*] Jugadores pendientes: {len(df_pendientes)}")
    
    # Filtrar jugadores de dobles
    df_individuales = df_pendientes[~df_pendientes['nombre'].apply(es_jugador_dobles)]
    print(f"[*] Jugadores individuales (sin dobles): {len(df_individuales)}")
    
    # Cargar jugadores ya procesados
    if os.path.exists(archivo_completos):
        df_existentes = pd.read_csv(archivo_completos)
        nombres_existentes = set(df_existentes['nombre'].dropna().unique())
        player_ids_existentes = set(df_existentes['player_id'].dropna().astype(int).unique())
        print(f"[*] Jugadores ya procesados: {len(nombres_existentes)}")
    else:
        nombres_existentes = set()
        player_ids_existentes = set()
        df_existentes = pd.DataFrame()
    
    # Filtrar solo los nuevos
    df_nuevos = df_individuales[~df_individuales['nombre'].isin(nombres_existentes)]
    print(f"[*] Jugadores nuevos a procesar: {len(df_nuevos)}")
    
    if len(df_nuevos) == 0:
        print("\n[OK] No hay jugadores nuevos para procesar.")
        return
    
    # Iniciar navegador
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Ir a SofaScore para obtener cookies necesarias
        page.goto("https://www.sofascore.com/tennis")
        page.wait_for_timeout(3000)
        
        jugadores_encontrados = []
        total = len(df_nuevos)
        errores = 0
        
        for i, (_, row) in enumerate(df_nuevos.iterrows(), 1):
            nombre = row['nombre']
            
            print(f"\r[{i}/{total}] Buscando: {nombre[:40]:<40}", end="", flush=True)
            
            try:
                # Buscar player_id
                player_id = buscar_player_id(page, nombre)
                
                if not player_id:
                    errores += 1
                    continue
                
                if player_id in player_ids_existentes:
                    continue
                
                # Obtener datos del jugador
                datos = get_player_data(page, player_id)
                
                if not datos:
                    errores += 1
                    continue
                
                # Obtener ranking
                ranking = get_ranking(page, player_id)
                datos.update(ranking)
                
                # Normalizar mano dominante
                datos['mano'] = normalizar_mano(datos.get('mano_dominante'))
                
                jugadores_encontrados.append(datos)
                player_ids_existentes.add(player_id)
                
            except Exception as e:
                logging.error(f"Error procesando {nombre}: {e}")
                errores += 1
                continue
        
        print()
        browser.close()
    
    print(f"\n[*] Jugadores encontrados: {len(jugadores_encontrados)}")
    print(f"[*] Errores/No encontrados: {errores}")
    
    # Guardar resultados
    if jugadores_encontrados:
        df_nuevos_datos = pd.DataFrame(jugadores_encontrados)
        
        if len(df_existentes) > 0:
            df_final = pd.concat([df_existentes, df_nuevos_datos], ignore_index=True)
            df_final = df_final.drop_duplicates(subset=['player_id'], keep='last')
        else:
            df_final = df_nuevos_datos
        
        df_final.to_csv(archivo_completos, index=False)
        print(f"\n[OK] Archivo guardado: {archivo_completos}")
        print(f"    Total jugadores en archivo: {len(df_final)}")
        
        # Mostrar estadisticas de mano dominante
        con_mano = df_final[df_final['mano'].notna()]
        print(f"\n[*] Jugadores con mano dominante: {len(con_mano)}/{len(df_final)}")
        print(f"    - Derechos (R): {len(con_mano[con_mano['mano'] == 'R'])}")
        print(f"    - Zurdos (L): {len(con_mano[con_mano['mano'] == 'L'])}")


if __name__ == "__main__":
    main()
