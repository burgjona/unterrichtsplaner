/* U23 Service Worker — Offline (nur lesen).
   Cached die App-Shell und die zuletzt geladenen API-GET-Antworten, damit die
   Oberfläche ohne Netz einsehbar bleibt. Schreibvorgänge (POST/PUT/DELETE) werden
   NIE abgefangen — sie gehen direkt ans Netz und schlagen offline bewusst fehl.

   Deploy-Invalidierung: bei jedem neuen Deploy die VERSION erhöhen. Der activate-Schritt
   löscht dann alle Caches mit abweichendem Namen; skipWaiting + clients.claim sorgen
   dafür, dass der neue SW sofort übernimmt (keine veraltete Shell). */

const VERSION = "v1";
const SHELL_CACHE = "ldb-shell-" + VERSION;
const DATA_CACHE = "ldb-data-" + VERSION;

/* App-Shell: statische Dateien, die real unter web/ existieren, plus das dynamische
   Manifest. Precache ist resilient (allSettled) — eine einzelne fehlende Datei lässt
   die Installation NICHT fehlschlagen. */
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/app.js",
  "/api.js",
  "/styles.css",
  "/themes.css",
  "/praesentation.css",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) =>
      // Jede Datei einzeln laden, Fehler tolerieren (z. B. wenn eine Datei fehlt).
      Promise.allSettled(
        SHELL_ASSETS.map((url) =>
          fetch(url, { credentials: "same-origin" }).then((res) => {
            if (res && res.ok) return cache.put(url, res.clone());
          })
        )
      )
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE && k !== DATA_CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

/* Netz-First mit Cache-Fallback (für Navigation und Auth). */
async function networkFirst(request, cacheName, fallbackUrl) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(request);
    if (res && res.ok) cache.put(request, res.clone());
    return res;
  } catch (_) {
    const cached = await cache.match(request);
    if (cached) return cached;
    if (fallbackUrl) {
      const fb = await cache.match(fallbackUrl);
      if (fb) return fb;
    }
    throw _;
  }
}

/* Stale-While-Revalidate: sofort aus Cache liefern, im Hintergrund aktualisieren;
   offline → letzte gecachte Antwort. `event` hält den SW via waitUntil am Leben,
   bis die Hintergrund-Aktualisierung geschrieben ist. */
async function staleWhileRevalidate(event, cacheName) {
  const request = event.request;
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((res) => {
      if (res && res.ok) return cache.put(request, res.clone()).then(() => res);
      return res;
    })
    .catch(() => null);
  if (cached) {
    event.waitUntil(network);   // Revalidierung abschließen, auch nach Antwort.
    return cached;
  }
  return (await network) || Promise.reject(new Error("offline und kein Cache"));
}

self.addEventListener("fetch", (event) => {
  const req = event.request;

  // NUR GET behandeln — POST/PUT/DELETE niemals abfangen/cachen.
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Nur eigene Origin bedienen (keine externen Ressourcen abfangen).
  if (url.origin !== self.location.origin) return;

  // Navigations-Requests: Netz-First, offline → gecachte /index.html (App-Shell).
  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req, SHELL_CACHE, "/index.html"));
    return;
  }

  // API-GETs.
  if (url.pathname.startsWith("/api/")) {
    // Auth network-first, damit ein abgemeldeter Zustand nicht „hängt".
    if (url.pathname.startsWith("/api/auth/")) {
      event.respondWith(networkFirst(req, DATA_CACHE));
    } else {
      event.respondWith(staleWhileRevalidate(event, DATA_CACHE));
    }
    return;
  }

  // Statische Shell-Assets: Cache-First mit Netz-Fallback.
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req)
        .then((res) => {
          if (res && res.ok && (url.pathname === "/" || SHELL_ASSETS.includes(url.pathname))) {
            const copy = res.clone();
            caches.open(SHELL_CACHE).then((c) => c.put(req, copy));
          }
          return res;
        });
    })
  );
});
