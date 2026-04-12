from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = context.new_page()
    page.goto("https://www.sofascore.com/tennis", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    r = page.request.get(
        "https://api.sofascore.com/api/v1/sport/tennis/scheduled-events/2026-04-11",
        headers={"Accept": "application/json", "Referer": "https://www.sofascore.com/tennis"},
        timeout=30000,
    )
    data = r.json()
    eventos = data.get("events", [])
    print(f"Total eventos: {len(eventos)}")

    # Imprimir estructura completa del primer evento
    if eventos:
        print("\n=== ESTRUCTURA PRIMER EVENTO ===")
        print(json.dumps(eventos[0], indent=2))

    browser.close()
