/* Web-Push-Benachrichtigungen – Einstellungskarte "Benachrichtigungen".
   Jedes Gerät (Handy, iPad, PC) wird einzeln angemeldet: Browser-Erlaubnis + Push-
   Subscription, die der Server speichert (/api/push). Die Nachrichten selbst zeigt der
   Service Worker an (sw.js, "push"-Event), auch wenn die App geschlossen ist.
   iPhone/iPad: Push nur aus der installierten App ("Zum Home-Bildschirm", ab iOS 16.4). */
const PushUi = (() => {
  // iPadOS meldet sich als Mac – nur die Touch-Punkte verraten es.
  const isIpad = () => /iPad/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isIos = () => /iPhone|iPod/.test(navigator.userAgent) || isIpad();
  const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches
    || navigator.standalone === true;
  const supported = () => "serviceWorker" in navigator && "PushManager" in window
    && "Notification" in window;

  function deviceLabel() {
    const ua = navigator.userAgent;
    let device = "Gerät";
    if (/iPhone/.test(ua)) device = "iPhone";
    else if (isIpad()) device = "iPad";
    else if (/Android/.test(ua)) device = "Android";
    else if (/Windows/.test(ua)) device = "Windows-PC";
    else if (/Macintosh/.test(ua)) device = "Mac";
    else if (/Linux/.test(ua)) device = "Linux";
    let browser = "";
    if (/Edg\//.test(ua)) browser = "Edge";
    else if (/Firefox\//.test(ua)) browser = "Firefox";
    else if (/Chrome\//.test(ua)) browser = "Chrome";
    else if (/Safari\//.test(ua)) browser = "Safari";
    return browser ? `${device} · ${browser}` : device;
  }

  function keyBytes(b64url) {
    const b64 = (b64url + "===".slice((b64url.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  }

  // Gehört die bestehende Anmeldung zum aktuellen Server-Schlüssel? Sonst neu anmelden.
  function sameKey(sub, bytes) {
    const k = sub.options && sub.options.applicationServerKey;
    if (!k) return true;  // nicht auslesbar -> nicht unnötig neu anmelden
    const a = new Uint8Array(k);
    return a.length === bytes.length && a.every((v, i) => v === bytes[i]);
  }

  async function currentSub() {
    if (!supported()) return null;
    const reg = await navigator.serviceWorker.getRegistration();
    return reg ? reg.pushManager.getSubscription() : null;
  }

  async function register(sub) {
    const j = sub.toJSON();
    await API.post("/push/subscriptions", { endpoint: j.endpoint, keys: j.keys, label: deviceLabel() });
  }

  async function enable() {
    // requestPermission zuerst und ohne vorheriges await: Safari verlangt eine direkte Nutzergeste.
    const perm = await Notification.requestPermission();
    if (perm !== "granted") {
      toast("Benachrichtigungen wurden nicht erlaubt.", false);
      return render();
    }
    const btn = $("pushEnableBtn");
    btn.disabled = true;
    try {
      const { publicKey } = await API.get("/push/public-key");
      const key = keyBytes(publicKey);
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();
      if (sub && !sameKey(sub, key)) { await sub.unsubscribe(); sub = null; }
      if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      await register(sub);
      toast("Benachrichtigungen auf diesem Gerät aktiviert.");
    } catch (e) {
      toast(e.message || "Aktivieren fehlgeschlagen.", false);
    } finally {
      btn.disabled = false;
      render();
    }
  }

  async function disable() {
    try {
      const sub = await currentSub();
      if (sub) {
        await API.post("/push/unsubscribe", { endpoint: sub.endpoint });  // offline -> Fehler, lokal bleibt alles
        await sub.unsubscribe();
      }
      toast("Benachrichtigungen auf diesem Gerät deaktiviert.");
    } catch (e) { toast(e.message, false); }
    render();
  }

  async function sendTest() {
    try {
      const r = await API.post("/push/test");
      if (r.sent) toast(`Test an ${r.sent} ${r.sent === 1 ? "Gerät" : "Geräte"} gesendet.`);
      else toast("Test konnte an kein Gerät zugestellt werden.", false);
    } catch (e) { toast(e.message, false); }
    render();
  }

  // Beim App-Start: bestehende Anmeldung erneut melden (idempotent). Holt ein Gerät zurück,
  // das der Server entfernt hat, und hält das Label aktuell. Still – kein Toast.
  async function renew() {
    try {
      if (!supported() || Notification.permission !== "granted") return;
      const sub = await currentSub();
      if (sub) await register(sub);
    } catch (_) { /* still */ }
  }

  async function render() {
    const badge = $("pushStatus");
    if (!badge) return;
    const show = (id, on) => $(id).classList.toggle("hidden", !on);
    let status = "off";
    let hint = "";
    if (!supported()) {
      status = "unsupported";
      hint = isIos() && !isStandalone()
        ? "Auf iPhone und iPad kommen Benachrichtigungen nur in der installierten App: in Safari auf Teilen → „Zum Home-Bildschirm“ tippen und das Dashboard dann über das neue Symbol öffnen (ab iOS 16.4)."
        : "Dieser Browser unterstützt keine Benachrichtigungen.";
    } else if (Notification.permission === "denied") {
      status = "denied";
      hint = "Benachrichtigungen sind für diese Seite blockiert. Erlaube sie in den Browser- bzw. Systemeinstellungen und lade die Seite danach neu.";
    } else if (Notification.permission === "granted" && await currentSub()) {
      status = "on";
    }
    badge.className = status === "on" ? "badge ok" : status === "off" ? "badge warn" : "badge bad";
    badge.textContent = {
      on: "Aktiv auf diesem Gerät", off: "Aus auf diesem Gerät",
      denied: "Blockiert", unsupported: "Nicht verfügbar",
    }[status];
    $("pushHint").textContent = hint;
    show("pushHint", !!hint);
    show("pushEnableBtn", status === "off");
    show("pushDisableBtn", status === "on");

    // Der Test geht an alle Geräte – sinnvoll, sobald irgendeins angemeldet ist.
    let devices = [];
    try { devices = await API.get("/push/subscriptions"); } catch (_) { /* offline */ }
    show("pushTestBtn", devices.length > 0);
    $("pushDevices").textContent = devices.length
      ? "Angemeldet: " + devices.map((d) => d.label || "Gerät").join(", ")
      : "Noch kein Gerät angemeldet.";
  }

  function init() {
    if (!$("pushCard")) return;
    $("pushEnableBtn").onclick = enable;
    $("pushDisableBtn").onclick = disable;
    $("pushTestBtn").onclick = sendTest;
  }

  return { init, render, renew };
})();
