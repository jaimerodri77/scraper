from curl_cffi import requests

url = "https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/2025-08-12"
headers = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://www.sofascore.com/tennis",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Origin": "https://www.sofascore.com"
}

# Use Chrome 120 TLS fingerprint
response = requests.get(url, headers=headers, impersonate="chrome120")
print(f"STATUS CODE: {response.status_code}")
if response.status_code == 200:
    print(f"SUCCESS! Snippet: {response.text[:200]}")
else:
    print(f"ERROR: {response.text[:200]}")
