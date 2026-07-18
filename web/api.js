/* Schlanke fetch-Schicht gegen /api. Session-Cookie via credentials:'include'. */
const API = (() => {
  const BASE = "/api";
  function parseJson(text, status) {
    // Nicht-JSON (z. B. HTML-Fehlerseite eines Proxys/Tunnels) lesbar melden statt Parse-Crash.
    if (!text) return null;
    try { return JSON.parse(text); }
    catch (_) {
      const err = new Error(`Server-Fehler (HTTP ${status}) – Antwort war kein JSON.`);
      err.status = status;
      throw err;
    }
  }
  async function req(method, path, body) {
    const opts = { method, credentials: "include", headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(BASE + path, opts);
    } catch (netErr) {
      // U23: Netzwerkfehler (offline) klar melden statt kryptischem TypeError.
      // Schreibvorgänge offline schlagen bewusst fehl (nur-lesen-Modus).
      const offline = (typeof navigator !== "undefined" && navigator.onLine === false);
      let msg;
      if (offline) {
        msg = method === "GET"
          ? "Keine Internetverbindung – Daten evtl. nicht aktuell."
          : "Keine Internetverbindung – Änderung nicht gespeichert.";
      } else if (method !== "GET") {
        msg = "Server nicht erreichbar – Änderung nicht gespeichert.";
      } else {
        msg = "Server nicht erreichbar – Daten evtl. nicht aktuell.";
      }
      const err = new Error(msg); err.offline = offline; throw err;
    }
    if (res.status === 204) return null;
    const text = await res.text();
    const data = parseJson(text, res.status);
    if (!res.ok) {
      let detail = res.statusText;
      if (data && data.detail) {
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return data;
  }
  async function upload(path, formData) {
    let res;
    try {
      res = await fetch(BASE + path, { method: "POST", credentials: "include", body: formData });
    } catch (netErr) {
      // U23: Upload offline schlägt bewusst fehl (nur-lesen-Modus).
      const err = new Error("Keine Internetverbindung – Änderung nicht gespeichert.");
      err.offline = true; throw err;
    }
    const text = await res.text();
    const data = parseJson(text, res.status);
    if (!res.ok) {
      let detail = res.statusText;
      if (data && data.detail) detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      const err = new Error(detail); err.status = res.status; throw err;
    }
    return data;
  }
  return {
    get: (p) => req("GET", p),
    post: (p, b) => req("POST", p, b),
    put: (p, b) => req("PUT", p, b),
    del: (p, b) => req("DELETE", p, b),
    upload,
  };
})();
