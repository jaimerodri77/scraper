import requests
import json

# ID del partido que me diste
TEST_EVENT_ID = "16012171"
url = f"https://api.sofascore.com/api/v1/event/{TEST_EVENT_ID}"

headers = {
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/tennis",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

print(f"Probando conexión con partido {TEST_EVENT_ID}...")
response = requests.get(url, headers=headers)

if response.status_code == 200:
    data = response.json()
    evento = data.get('event', {})
    nombre = evento.get('homeTeam', {}).get('name') + " vs " + evento.get('awayTeam', {}).get('name')
    estado = evento.get('status', {}).get('type', {}).get('name', 'unknown')
    fecha = evento.get('startTimestamp')
    
    print(f"✅ ÉXITO: La API funciona.")
    print(f"   Partido: {nombre}")
    print(f"   Estado: {estado}")
    print(f"   Fecha (Timestamp): {fecha}")
else:
    print(f"❌ ERROR: La API no responde. Código {response.status_code}")
    print(response.text)






