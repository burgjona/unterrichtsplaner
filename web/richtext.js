/* Kleiner Formatier-Editor für die beiden Freitextfelder, die die Lehrkraft selbst tippt:
   "Notizen" im Tafelbild und "Heftereintrag der SuS". Kann genau vier Dinge — fett, kursiv,
   unterstrichen, Schriftfarbe aus fester Palette — und nichts sonst.

   Klassisches <script> wie api.js (kein ES-Modul): app.js ist ein klassisches Script und
   käme an die Bindings eines Moduls nicht heran; der Editor wird im Stundenformular sofort
   gebraucht, ein dynamisches import() wie bei sitzplan.js wäre hier nur Umweg.

   Die <textarea> bleibt als Wertträger im DOM (versteckt) und enthält weiterhin genau das,
   was gespeichert wird — nur eben HTML statt Klartext. Damit funktionieren vorhandene
   input-Listener (Autosave) unverändert weiter.

   Farbe steckt als Klasse im Markup (rt-rot, rt-blau, …), nicht als Hex: nur so bleibt sie
   in den vier dunklen Themes lesbar. Weil document.execCommand aber Inline-Styles
   zusammenführt und Klassen nicht kennt, wird für den Moment des Farbbefehls hin- und
   zurückgewandelt (siehe applyColor). */
window.RichText = (function () {
  "use strict";

  // hex = nur der Zwischenwert für execCommand; im Dokument steht am Ende die Klasse.
  // Die tatsächlichen Farbwerte je Theme stehen in styles.css.
  var PALETTE = [
    { cls: "rt-rot", hex: "#c0392b", label: "Rot" },
    { cls: "rt-orange", hex: "#b35309", label: "Orange" },
    { cls: "rt-gruen", hex: "#15803d", label: "Grün" },
    { cls: "rt-blau", hex: "#1d4ed8", label: "Blau" },
    { cls: "rt-violett", hex: "#7e22ce", label: "Violett" },
  ];

  function el(x) { return typeof x === "string" ? document.getElementById(x) : x; }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* Klartext (Altbestand ohne Formatierung) als Editor-Inhalt darstellen. */
  function plainToHtml(text) {
    if (!text) return "";
    return escapeHtml(text).replace(/\r\n|\r|\n/g, "<br>");
  }

  function rgbToHex(value) {
    var m = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(value || "");
    if (!m) return (value || "").toLowerCase();
    return "#" + [m[1], m[2], m[3]].map(function (n) {
      return ("0" + parseInt(n, 10).toString(16)).slice(-2);
    }).join("");
  }

  /* Klassen -> Inline-Styles, damit execCommand die vorhandene Farbe kennt und beim
     Umfärben korrekt ersetzt statt zu verschachteln (sonst gewänne die innere Farbe). */
  function classesToStyles(root) {
    Array.prototype.forEach.call(root.querySelectorAll("span[class]"), function (sp) {
      for (var i = 0; i < PALETTE.length; i++) {
        if (sp.classList.contains(PALETTE[i].cls)) {
          sp.removeAttribute("class");
          sp.style.color = PALETTE[i].hex;
          return;
        }
      }
    });
  }

  /* Rückweg: alles Eingefärbte auf die Palettenklassen abbilden. Was sich keiner Palette
     zuordnen lässt (fremde Farbe aus einem Paste, <font> älterer Browser), verliert seine
     Hülle — der Text bleibt. Der Server verwirft es ohnehin.

     Wichtig: die Farbe landet nicht immer an einem span. Färbt man bereits fetten Text ein,
     hängt der Browser sie als style an das vorhandene <b> — der Server lässt <b> zwar durch,
     wirft das style-Attribut aber weg, und die Farbe wäre beim Speichern still verschwunden.
     Deshalb wird an solchen Tags die Farbe in ein eigenes span nach innen verlagert. */
  function stylesToClasses(root) {
    Array.prototype.forEach.call(root.querySelectorAll('[style*="color"], font'), function (node) {
      var raw = node.style && node.style.color ? node.style.color : node.getAttribute("color");
      var hex = rgbToHex(raw);
      var hit = null;
      for (var i = 0; i < PALETTE.length; i++) if (PALETTE[i].hex === hex) hit = PALETTE[i];
      var tag = node.tagName.toLowerCase();

      if (tag === "span" || tag === "font") {
        var span = node;
        if (tag === "font") {
          span = document.createElement("span");
          while (node.firstChild) span.appendChild(node.firstChild);
          node.parentNode.replaceChild(span, node);
        }
        span.removeAttribute("style");
        span.removeAttribute("color");
        if (hit) {
          span.className = hit.cls;
        } else {
          var parent = span.parentNode;
          while (span.firstChild) parent.insertBefore(span.firstChild, span);
          parent.removeChild(span);
        }
        return;
      }

      node.removeAttribute("style");
      if (!hit) return;
      var inner = document.createElement("span");
      inner.className = hit.cls;
      while (node.firstChild) inner.appendChild(node.firstChild);
      node.appendChild(inner);
    });
  }

  function exec(cmd, value, useCss) {
    // styleWithCSS bewusst je Befehl setzen: fett/kursiv/unterstrichen sollen <b>/<i>/<u>
    // ergeben (steht so auf der Erlaubnisliste des Servers), Farbe dagegen ein span.
    try { document.execCommand("styleWithCSS", false, !!useCss); } catch (e) { /* egal */ }
    document.execCommand(cmd, false, value == null ? null : value);
  }

  function applyColor(input, entry) {
    classesToStyles(input);
    exec("foreColor", entry.hex, true);
    stylesToClasses(input);
  }

  function makeButton(label, title, cls) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "rt-btn" + (cls ? " " + cls : "");
    b.innerHTML = label;
    b.title = title;
    b.setAttribute("aria-label", title);
    // Ohne das verliert der Editor beim Klick die Auswahl und der Befehl liefe ins Leere.
    b.addEventListener("mousedown", function (e) { e.preventDefault(); });
    return b;
  }

  /* Baut Toolbar + Eingabefeld vor die textarea und versteckt sie. Mehrfachaufrufe auf
     demselben Feld sind folgenlos (die Hefter-Tabelle wird bei jedem Sync neu gezeichnet). */
  function enhance(target) {
    var ta = el(target);
    if (!ta || ta._rt) return ta && ta._rt ? ta._rt : null;

    var wrap = document.createElement("div");
    wrap.className = "rt-wrap";
    var bar = document.createElement("div");
    bar.className = "rt-bar";
    var input = document.createElement("div");
    input.className = "rt-input";
    input.contentEditable = "true";
    input.setAttribute("role", "textbox");
    input.setAttribute("aria-multiline", "true");
    if (ta.placeholder) input.setAttribute("data-placeholder", ta.placeholder);
    if (ta.id) input.setAttribute("aria-labelledby", ta.id + "-label");
    if (ta.rows && ta.rows <= 3) input.classList.add("rt-input-compact");

    [["bold", "<b>F</b>", "Fett (Strg+B)"],
     ["italic", "<i>K</i>", "Kursiv (Strg+I)"],
     ["underline", "<u>U</u>", "Unterstrichen (Strg+U)"]].forEach(function (spec) {
      var b = makeButton(spec[1], spec[2]);
      b.addEventListener("click", function () {
        input.focus();
        exec(spec[0], null, false);
        sync();
      });
      bar.appendChild(b);
    });

    var sep = document.createElement("span");
    sep.className = "rt-sep";
    bar.appendChild(sep);

    PALETTE.forEach(function (entry) {
      var b = makeButton("A", entry.label, "rt-swatch " + entry.cls);
      b.addEventListener("click", function () {
        input.focus();
        applyColor(input, entry);
        sync();
      });
      bar.appendChild(b);
    });

    var clear = makeButton("A̶", "Formatierung entfernen");
    clear.addEventListener("click", function () {
      input.focus();
      exec("removeFormat", null, false);
      stylesToClasses(input);
      sync();
    });
    bar.appendChild(clear);

    function sync() {
      ta.value = input.innerHTML === "<br>" ? "" : input.innerHTML;
      // Vorhandene Autosave-Listener hängen an der textarea und sollen weiter greifen.
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }

    input.addEventListener("input", function () { stylesToClasses(input); sync(); });
    input.addEventListener("blur", sync);

    // Einfügen immer als Klartext: sonst landet die halbe Formatierung fremder Seiten im Feld.
    input.addEventListener("paste", function (e) {
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData("text/plain");
      document.execCommand("insertText", false, text);
    });

    // Strg/Cmd+B/I/U selbst behandeln: der Browser würde sonst je nach zuletzt gesetztem
    // styleWithCSS ein <span style="font-weight:bold"> erzeugen, das der Server verwirft.
    input.addEventListener("keydown", function (e) {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      var cmd = { b: "bold", i: "italic", u: "underline" }[(e.key || "").toLowerCase()];
      if (!cmd) return;
      e.preventDefault();
      exec(cmd, null, false);
      sync();
    });

    ta.parentNode.insertBefore(wrap, ta);
    wrap.appendChild(bar);
    wrap.appendChild(input);
    wrap.appendChild(ta);
    ta.classList.add("rt-source");

    var api = { wrap: wrap, input: input, textarea: ta };
    ta._rt = api;
    // Was schon in der textarea stand (z. B. serverseitig gerenderter Klartext), übernehmen.
    setContent(api, ta.value, "");
    return api;
  }

  function setContent(api, html, plainFallback) {
    api.input.innerHTML = html ? html : plainToHtml(plainFallback);
    api.textarea.value = api.input.innerHTML;
  }

  /* Inhalt setzen: html gewinnt, sonst wird der Klartext dargestellt (Altbestand). */
  function set(target, html, plainFallback) {
    var ta = el(target);
    if (!ta) return;
    var api = ta._rt || enhance(ta);
    if (api) setContent(api, html, plainFallback);
    else ta.value = html || plainFallback || "";
  }

  function get(target) {
    var ta = el(target);
    if (!ta) return "";
    if (ta._rt) ta._rt.textarea.value = ta._rt.input.innerHTML === "<br>" ? "" : ta._rt.input.innerHTML;
    return ta.value || "";
  }

  /* Klartext aus dem HTML — dieselbe Regel wie serverseitig (Umbruch am Blockanfang,
     siehe src/lib/richtext.py). Gebraucht, weil SyncEngine.update() den optimistischen
     LOKALEN Datensatz zurückgibt und nicht die Server-Ableitung: ohne diesen Spiegel bliebe
     der Klartext offline auf dem alten Stand und Zähler wie "Heftereinträge offen" logen. */
  function toText(html) {
    if (!html) return "";
    var box = document.createElement("div");
    box.innerHTML = String(html);
    var out = "";
    (function walk(node) {
      for (var n = node.firstChild; n; n = n.nextSibling) {
        if (n.nodeType === 3) { out += n.nodeValue; continue; }
        if (n.nodeType !== 1) continue;
        var tag = n.tagName.toLowerCase();
        if (tag === "br" || tag === "div" || tag === "p") out += "\n";
        walk(n);
      }
    })(box);
    return out.replace(/\u00a0/g, " ").replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n").trim();
  }

  /* Beide Spalten auf einmal für einen Sync-/Formular-Payload: {feld, feldHtml}. Der Server
     leitet den Klartext ohnehin selbst ab (und gewinnt damit) — mitgeschickt wird er, damit
     der lokale Offline-Datensatz sofort stimmt. */
  function payload(target, baseName) {
    var html = get(target);
    var body = {};
    body[baseName] = toText(html);
    body[baseName + "Html"] = html;
    return body;
  }

  return {
    enhance: enhance, set: set, get: get, toText: toText, payload: payload,
    plainToHtml: plainToHtml, PALETTE: PALETTE,
  };
})();
