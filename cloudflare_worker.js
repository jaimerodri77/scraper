/**
 * CLOUDFLARE WORKER — Proxy para SofaScore API
 * =============================================
 * CÓMO DEPLOYAR (es gratis, ~5 minutos):
 *
 * 1. Ve a https://dash.cloudflare.com → Workers & Pages → Create Worker
 * 2. Pega este código completo en el editor
 * 3. Haz clic en "Save and Deploy"
 * 4. Copia la URL que te da (ej: tennis-proxy.TU-USUARIO.workers.dev)
 * 5. En tu repositorio de GitHub, ve a Settings → Secrets → Actions
 *    Crea dos secrets:
 *      - PROXY_URL  → https://tennis-proxy.TU-USUARIO.workers.dev
 *      - PROXY_TOKEN → cualquier contraseña larga que inventes (ej: mi-clave-secreta-2025)
 * 6. En el Worker, en la línea SECRET_TOKEN, pon la misma contraseña
 *
 * PLAN GRATUITO de Cloudflare Workers:
 *   - 100,000 requests/día gratis
 *   - El scraper hace ~2 requests por partido (eventos + stats)
 *   - Para 365 días × ~50 partidos = ~36,500 requests → muy dentro del límite
 */

// Cambia esto por tu contraseña secreta (debe coincidir con el secret PROXY_TOKEN en GitHub)
const SECRET_TOKEN = "CAMBIA_ESTO_POR_TU_CONTRASEÑA_SECRETA";

export default {
  async fetch(request, env, ctx) {
    // ── Autenticación ──────────────────────────────────────────────────────
    const token = request.headers.get("X-Proxy-Token");
    if (token !== SECRET_TOKEN) {
      return new Response("Unauthorized", { status: 401 });
    }

    // ── Construir URL de destino ───────────────────────────────────────────
    // El scraper pasa la ruta como query param: ?path=/api/v1/sport/tennis/...
    const url = new URL(request.url);
    const targetPath = url.searchParams.get("path");

    if (!targetPath || !targetPath.startsWith("/api/v1/")) {
      return new Response("Invalid path", { status: 400 });
    }

    const targetUrl = `https://api.sofascore.com${targetPath}`;

    // ── Hacer la request a SofaScore desde la red de Cloudflare ───────────
    const sofascoreResponse = await fetch(targetUrl, {
      headers: {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.sofascore.com/tennis",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
      },
    });

    // ── Devolver la respuesta al scraper ───────────────────────────────────
    const body = await sofascoreResponse.text();
    return new Response(body, {
      status: sofascoreResponse.status,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};
