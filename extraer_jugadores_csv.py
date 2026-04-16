import pandas as pd
import os
from datetime import datetime

def extraer_jugadores_unicos(archivos_csv: list[str]) -> pd.DataFrame:
    """
    Extrae todos los jugadores únicos de los archivos CSV de partidos.
    Combina winner_name y loser_name en una sola lista de jugadores únicos.
    """
    jugadores = set()
    
    for archivo in archivos_csv:
        if not os.path.exists(archivo):
            print(f"⚠️ Archivo no encontrado: {archivo}")
            continue
            
        print(f"📖 Leyendo: {archivo}")
        df = pd.read_csv(archivo)
        
        # Extraer nombres de ganadores y perdedores
        if 'winner_name' in df.columns:
            jugadores.update(df['winner_name'].dropna().unique())
            print(f"   - Ganadores encontrados: {len(df['winner_name'].dropna().unique())}")
        
        if 'loser_name' in df.columns:
            jugadores.update(df['loser_name'].dropna().unique())
            print(f"   - Perdedores encontrados: {len(df['loser_name'].dropna().unique())}")
    
    print(f"\n✅ Total jugadores únicos: {len(jugadores)}")
    
    # Crear DataFrame con los jugadores
    df_jugadores = pd.DataFrame({
        'nombre': sorted(list(jugadores)),
        'fecha_extraccion': datetime.now().strftime("%Y-%m-%d")
    })
    
    return df_jugadores


def verificar_jugadores_existentes(archivo_salida: str) -> set:
    """
    Verifica si ya existe un archivo de jugadores y retorna los nombres existentes.
    """
    if os.path.exists(archivo_salida):
        df_existente = pd.read_csv(archivo_salida)
        return set(df_existente['nombre'].dropna().unique())
    return set()


def main():
    # Archivos de entrada
    archivos_entrada = [
        "datos/tenis_2026.csv",
        "datos/tenis_historico.csv"
    ]
    
    # Archivo de salida
    archivo_salida = "datos/jugadores_pendientes.csv"
    
    print("=" * 50)
    print("🎾 EXTRACTOR DE JUGADORES DE TENIS")
    print("=" * 50)
    
    # Verificar jugadores ya existentes
    jugadores_existentes = verificar_jugadores_existentes(archivo_salida)
    if jugadores_existentes:
        print(f"📋 Jugadores ya registrados: {len(jugadores_existentes)}")
    
    # Extraer jugadores de los archivos
    df_jugadores = extraer_jugadores_unicos(archivos_entrada)
    
    # Filtrar jugadores nuevos
    if jugadores_existentes:
        df_nuevos = df_jugadores[~df_jugadores['nombre'].isin(jugadores_existentes)]
        print(f"🆕 Jugadores nuevos: {len(df_nuevos)}")
    else:
        df_nuevos = df_jugadores
    
    # Guardar resultados
    os.makedirs("datos", exist_ok=True)
    
    if os.path.exists(archivo_salida):
        # Combinar con existentes
        df_existente = pd.read_csv(archivo_salida)
        df_combined = pd.concat([df_existente, df_nuevos]).drop_duplicates(subset=['nombre'], keep='first')
        df_combined.to_csv(archivo_salida, index=False)
        print(f"\n💾 Archivo actualizado: {archivo_salida}")
        print(f"   Total jugadores en archivo: {len(df_combined)}")
    else:
        df_jugadores.to_csv(archivo_salida, index=False)
        print(f"\n💾 Archivo creado: {archivo_salida}")
        print(f"   Total jugadores: {len(df_jugadores)}")
    
    # Mostrar muestra de jugadores
    print("\n📝 Muestra de jugadores extraídos:")
    print(df_jugadores.head(10).to_string(index=False))
    
    return df_jugadores


if __name__ == "__main__":
    main()
