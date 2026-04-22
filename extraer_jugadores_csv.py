import pandas as pd
import os
from datetime import datetime

def extraer_jugadores_unicos(archivos_csv: list[str]) -> pd.DataFrame:
    """
    Extrae todos los jugadores únicos de los archivos CSV de partidos.
    Combina winner_id/winner_name y loser_id/loser_name en una sola tabla.
    Si las columnas *_id no existen, sigue funcionando solo con nombres.
    """
    # dict {player_id -> nombre}  — id=None cuando no está disponible
    jugadores: dict = {}

    for archivo in archivos_csv:
        if not os.path.exists(archivo):
            print(f"⚠️ Archivo no encontrado: {archivo}")
            continue

        print(f"📖 Leyendo: {archivo}")
        df = pd.read_csv(archivo, low_memory=False)

        tiene_ids = "winner_id" in df.columns and "loser_id" in df.columns

        for rol in ("winner", "loser"):
            col_nombre = f"{rol}_name"
            col_id     = f"{rol}_id"
            if col_nombre not in df.columns:
                continue

            sub = df[[col_nombre]].copy()
            if tiene_ids:
                sub[col_id] = df[col_id]
            else:
                sub[col_id] = None

            sub = sub.dropna(subset=[col_nombre])
            encontrados = len(sub[col_nombre].unique())
            print(f"   - {rol.capitalize()}es encontrados: {encontrados}")

            for _, row in sub.iterrows():
                nombre = row[col_nombre]
                pid    = int(row[col_id]) if pd.notna(row.get(col_id)) else None
                # Si ya lo tenemos con ID, no pisar con None
                if nombre not in jugadores or jugadores[nombre] is None:
                    jugadores[nombre] = pid

    print(f"\n✅ Total jugadores únicos: {len(jugadores)}")

    df_jugadores = pd.DataFrame([
        {"sofascore_id": pid, "nombre": nombre, "fecha_extraccion": datetime.now().strftime("%Y-%m-%d")}
        for nombre, pid in sorted(jugadores.items())
    ])

    return df_jugadores


def verificar_jugadores_existentes(archivo_salida: str) -> set:
    """Retorna el conjunto de nombres ya registrados en el archivo de salida."""
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
        df_existente = pd.read_csv(archivo_salida)
        df_combined = (
            pd.concat([df_existente, df_nuevos], ignore_index=True)
            .drop_duplicates(subset=['nombre'], keep='last')  # keep='last' para actualizar sofascore_id si antes era None
            .sort_values('nombre')
        )
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
