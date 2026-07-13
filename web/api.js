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
    const res = await fetch(BASE + path, opts);
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
    const res = await fetch(BASE + path, { method: "POST", credentials: "include", body: formData });
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
