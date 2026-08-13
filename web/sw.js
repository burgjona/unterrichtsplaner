/* U23 Service Worker — Offline (nur lesen).
   Cached die App-Shell und die zuletzt geladenen API-GET-Antworten, damit die
   Oberfläche ohne Netz einsehbar bleibt. Schreibvorgänge (POST/PUT/DELETE) werden
   NIE abgefangen — sie gehen direkt ans Netz und schlagen offline bewusst fehl.

   Deploy-Frische: Die App-Shell (index.html, app.js, CSS, …) wird NETZ-FIRST ausgeliefert –
   online kommt also nach jedem Deploy sofort der neue Code, offline greift der Cache-Fallback.
   Damit ist kein manuelles VERSION-Hochzählen mehr nötig, um neuen Code zu sehen; die VERSION
   dient nur noch dem einmaligen Verwerfen alter Caches beim activate-Schritt (skipWaiting +
   clients.claim übernehmen den neuen SW sofort). */

const VERSION = "v3";
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
  "/stundenplan.js",
  "/sitzplan.js",
  "/notizen.js",
  "/stoffplan.js",
  "/sequenzplan.js",
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

  // API-GETs: immer Netz-First, damit nach Schreibvorgängen (POST/PUT/DELETE) sofort
  // die aktuellen Daten erscheinen — der Cache dient nur noch als Offline-Fallback.
  // (Stale-While-Revalidate lieferte hier sonst nach dem Anlegen/Ändern eines Termins
  // erst beim übernächsten Aufruf die frischen Daten — daher weg damit.)
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(req, DATA_CACHE));
    return;
  }

  // Statische Shell-Assets (app.js, CSS, Manifest, …): Netz-First mit Cache-Fallback.
  // So wird nach jedem Deploy online sofort der neue Code geladen; offline greift der Cache.
  event.respondWith(networkFirst(req, SHELL_CACHE));
});
