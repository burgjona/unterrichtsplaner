/* Lehrer-Dashboard – Frontend-Logik (M3). Ersetzt den localStorage-Prototyp durch
   echte API-Calls (api.js). Daten kommen ausschließlich aus dem Backend. */
"use strict";

const meyerMerkmale = [
  "Klare Strukturierung", "Hoher Anteil echter Lernzeit", "Lernförderliches Klima",
  "Inhaltliche Klarheit", "Sinnstiftendes Kommunizieren", "Methodenvielfalt",
  "Individuelles Fördern", "Intelligentes Üben", "Transparente Leistungserwartungen",
  "Vorbereitete Umgebung",
];
const BLOOM_STUFEN = ["Erinnern", "Verstehen", "Anwenden", "Analysieren", "Bewerten", "Erschaffen"];
const TRANSPARENT_PX = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
const ZIEL_BADGE = "display:inline-block;padding:1px 7px;border-radius:8px;background:#e0e7ff;color:#3730a3;font-size:11px;font-weight:700;";

const $ = (id) => document.getElementById(id);
const state = {
  user: null, classes: [], lessons: [], reflections: [], open: [], materials: [], todos: [],
  notes: [],   // U17: Notizen ("Gedanken sammeln")
  schoolYears: [], schoolDates: [], calendar: [], calendarCategories: [],
  appearance: { theme: "fruehling", darkMode: false, font: "verspielt" },
  stoffPreview: [], stoffPlans: [],   // aktuell angezeigter Vorschlag + gespeicherte Pläne (U12)
  activePlans: {},                    // U15: classId → { planId, title, blocks[] } des aktiven Stoffplans
};
const lbCache = {};                 // Lernbereiche je Fach|Stufe|Bildungsgang
let lessonSlotsCache = null;        // Klingelraster-Stunden (für "Stunde"-Auswahl im Kalender-Neuer-Termin-Panel)
let calMode = "month";
let calCursor = new Date();
let calSelectedDate = null;  // U28: im Monatsmodus ausgewählter Tag (Tages-Agenda unten im Grid)

/* ---------- kleine Helfer ---------- */
function toast(msg, ok = true) {
  let t = $("toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.style.cssText =
      "position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:200;" +
      "padding:11px 16px;border-radius:12px;font-size:13px;font-weight:700;box-shadow:0 12px 30px rgba(0,0,0,.2);";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.background = ok ? "#dcfce7" : "#fecaca";
  t.style.color = ok ? "#14532d" : "#7f1d1d";
  t.style.opacity = "1";
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.style.opacity = "0"), 2600);
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ---------- Rückgängig (ein Schritt zurück) ----------
   Nur die letzte Aktion wird gemerkt (lastUndo), kein mehrstufiger Verlauf. Jede neue
   mutierende Aktion überschreibt den vorherigen Eintrag. Genutzt von Stoffplan-Bearbeitung,
   Sequenzplanung sowie Material-/Termin-Archivierung (dort ruft run() einfach /restore auf). */
let lastUndo = null;   // { label, run: async () => void }

function setUndo(label, run) {
  lastUndo = { label, run };
  renderUndoBar();
}

function renderUndoBar() {
  let bar = $("undoBar");
  if (!lastUndo) {
    if (bar) bar.remove();
    return;
  }
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "undoBar";
    bar.style.cssText =
      "position:fixed;bottom:66px;left:50%;transform:translateX(-50%);z-index:200;" +
      "display:flex;align-items:center;gap:10px;background:#1f2937;color:#fff;" +
      "padding:9px 14px;border-radius:12px;font-size:13px;box-shadow:0 12px 30px rgba(0,0,0,.25);";
    document.body.appendChild(bar);
  }
  bar.innerHTML = `<span>${esc(lastUndo.label)}</span>
    <button class="btn tiny" id="undoBarBtn" style="white-space:nowrap;">Rückgängig</button>
    <button class="btn tiny secondary" id="undoBarClose" style="white-space:nowrap;" aria-label="Hinweis schließen">✕</button>`;
  bar.querySelector("#undoBarBtn").onclick = runUndo;
  bar.querySelector("#undoBarClose").onclick = () => { lastUndo = null; renderUndoBar(); };
}

async function runUndo() {
  if (!lastUndo) return;
  const action = lastUndo;
  lastUndo = null;
  renderUndoBar();
  try {
    await action.run();
    toast("Rückgängig gemacht.");
  } catch (e) { toast(e.message, false); }
}

// Ersetzt alle Sequenzstunden eines Blocks 1:1 durch targetRows (löschen + neu anlegen –
// einfacher und robuster als ein Diff, IDs müssen dabei nicht erhalten bleiben).
async function restoreSequenzStunden(blockId, targetRows) {
  const current = await SyncEngine.materialize("sequenz_stunden").then(
    (all) => all.filter((r) => r.blockId === blockId)
  );
  for (const r of current) await SyncEngine.remove("sequenz_stunden", r.id);
  for (const t of targetRows) {
    await SyncEngine.create("sequenz_stunden", {
      blockId, title: t.title, grobziel: t.grobziel || null,
      isLk: t.isLk, isReferat: t.isReferat, isKomplexeArbeit: t.isKomplexeArbeit,
      isKlassenarbeit: t.isKlassenarbeit, weitereNotenart: t.weitereNotenart || null,
      date: t.date || null,
    });
  }
}

/* ---------- Lokales Block-Undo (Unterrichtsplanung): Phasentabelle, Klafki-Reflexion,
   Lernziel-Karten. Anders als das server-seitige Undo oben: rein im Browser, ein dauerhaft
   sichtbarer (bis zur Nutzung deaktivierter) Button je Block macht die letzte lokale Änderung
   dieses einen Blocks rückgängig – auch bevor „Stunde speichern" gedrückt wurde. Ein Block ist
   ein Container mit [data-local-undo-block="<key>"] und genau einem [data-local-undo-btn] darin.
   Delegiert auf document, damit es auch für später (z. B. bei renderLernziele()) neu ins DOM
   eingefügte Blöcke ohne erneutes Verdrahten funktioniert. */
const localUndoSnapshots = new Map();   // blockKey -> Array der Feldwerte vor der ersten Änderung

// Die Phasen-Bezeichnung (data-phase-kind) bleibt außen vor: sie ändert die Struktur der
// Tabelle (Nummerierung, Reihenfolge) und wird beim Wechsel ohnehin neu gerendert.
function localUndoFields(block) {
  return [...block.querySelectorAll("input, textarea, select:not([data-phase-kind])")];
}

document.addEventListener("focusin", (e) => {
  const block = e.target.closest("[data-local-undo-block]");
  if (!block) return;
  const key = block.dataset.localUndoBlock;
  if (!localUndoSnapshots.has(key)) {
    localUndoSnapshots.set(key, localUndoFields(block).map((f) => f.value));
  }
});
["input", "change"].forEach((evt) => document.addEventListener(evt, (e) => {
  const block = e.target.closest("[data-local-undo-block]");
  if (!block || !localUndoSnapshots.has(block.dataset.localUndoBlock)) return;
  const btn = block.querySelector("[data-local-undo-btn]");
  if (btn) btn.disabled = false;
}));
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-local-undo-btn]");
  if (!btn) return;
  const block = btn.closest("[data-local-undo-block]");
  const key = block.dataset.localUndoBlock;
  const snapshot = localUndoSnapshots.get(key);
  if (!snapshot) return;
  localUndoFields(block).forEach((f, i) => { f.value = snapshot[i]; });
  localUndoSnapshots.delete(key);
  btn.disabled = true;
});

// Verwirft gemerkte Block-Änderungen (z. B. beim Laden einer anderen Stunde) und deaktiviert
// die zugehörigen Buttons wieder. Ohne keyPrefix: alles zurücksetzen.
function resetLocalUndo(keyPrefix) {
  [...localUndoSnapshots.keys()].forEach((key) => {
    if (!keyPrefix || key.startsWith(keyPrefix)) localUndoSnapshots.delete(key);
  });
  document.querySelectorAll("[data-local-undo-block]").forEach((block) => {
    if (keyPrefix && !block.dataset.localUndoBlock.startsWith(keyPrefix)) return;
    const btn = block.querySelector("[data-local-undo-btn]");
    if (btn) btn.disabled = true;
  });
}

function isoWeek(d) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dayNum = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - dayNum + 3);
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  const diff = (date - firstThursday) / 86400000;
  return 1 + Math.round((diff - 3 - firstThursday.getUTCDay() + 6) / 7);
}
function ampelColor(v) {
  return v === "gruen" ? "#22c55e" : v === "gelb" ? "#eab308" : v === "rot" ? "#ef4444" : "#cbd5e1";
}
function summarizeAmpel(arr) {
  const g = arr.filter((v) => v === "gruen").length;
  const y = arr.filter((v) => v === "gelb").length;
  const r = arr.filter((v) => v === "rot").length;
  return `${g} grün / ${y} gelb / ${r} rot`;
}

/* ---------- Meyer-Ampel-Raster ---------- */
function buildMeyerGrid(containerId) {
  const wrap = $(containerId);
  wrap.innerHTML = "";
  meyerMerkmale.forEach((name, i) => {
    const row = document.createElement("div");
    row.className = "meyer-row";
    const nm = `${i + 1}. ${esc(name)}`;
    row.innerHTML =
      `<span class="name" id="${containerId}-m${i}">${nm}</span>
       <div class="ampel-select" data-idx="${i}" role="radiogroup" aria-labelledby="${containerId}-m${i}">
         <button type="button" class="ampel-btn g" data-val="gruen" role="radio" aria-checked="false" aria-label="gut umsetzbar"></button>
         <button type="button" class="ampel-btn y" data-val="gelb" role="radio" aria-checked="false" aria-label="teilweise"></button>
         <button type="button" class="ampel-btn r" data-val="rot" role="radio" aria-checked="false" aria-label="noch offen / Risiko"></button>
       </div>`;
    wrap.appendChild(row);
  });
  wrap.querySelectorAll(".ampel-select").forEach((sel) => {
    const btns = Array.from(sel.querySelectorAll(".ampel-btn"));
    const pick = (btn) => {
      btns.forEach((b) => {
        const on = b === btn;
        b.classList.toggle("selected", on);
        b.setAttribute("aria-checked", on ? "true" : "false");
        b.tabIndex = on ? 0 : -1;
      });
      btn.focus();
    };
    btns.forEach((btn, bi) => {
      btn.tabIndex = bi === 0 ? 0 : -1;
      btn.onclick = () => pick(btn);
      btn.onkeydown = (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); pick(btns[(bi + 1) % btns.length]); }
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); pick(btns[(bi - 1 + btns.length) % btns.length]); }
      };
    });
  });
}
function readMeyerGrid(containerId) {
  const out = [];
  $(containerId).querySelectorAll(".ampel-select").forEach((sel) => {
    const s = sel.querySelector(".ampel-btn.selected");
    out.push(s ? s.dataset.val : "");
  });
  return out;
}
function _ampelSync(sel) {
  sel.querySelectorAll(".ampel-btn").forEach((b, bi) => {
    const on = b.classList.contains("selected");
    b.setAttribute("aria-checked", on ? "true" : "false");
    b.tabIndex = on ? 0 : (bi === 0 && !sel.querySelector(".ampel-btn.selected") ? 0 : -1);
  });
}
function resetMeyerGrid(containerId) {
  $(containerId).querySelectorAll(".ampel-select").forEach((sel) => {
    sel.querySelectorAll(".ampel-btn.selected").forEach((b) => b.classList.remove("selected"));
    _ampelSync(sel);
  });
}
function setMeyerGrid(containerId, values) {
  $(containerId).querySelectorAll(".ampel-select").forEach((sel, i) => {
    sel.querySelectorAll(".ampel-btn").forEach((b) => b.classList.remove("selected"));
    const v = (values || [])[i];
    if (v) { const t = sel.querySelector(`.ampel-btn[data-val="${v}"]`); if (t) t.classList.add("selected"); }
    _ampelSync(sel);
  });
}

/* ---------- Phasentabelle ----------
   Die Phasen einer Stunde sind frei zusammenstellbar: Grundgerüst Einstieg/Erarbeitung/
   Sicherung/Ausstieg, nach einer Sicherung darf eine weitere Erarbeitung folgen. Die
   römische Nummerierung (Erarbeitung I, II …) entsteht automatisch und nur dann, wenn eine
   Bezeichnung mehrfach vorkommt – bei einer einzelnen Erarbeitung bleibt es „Erarbeitung“. */
const PHASE_KINDS = ["Einstieg", "Erarbeitung", "Sicherung", "Ausstieg", "Puffer"];
const SOCIAL_FORMS = ["EA", "PA", "GA", "Plenum"];
const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
// [{kind, minutes, socialForm, method, material, teacher, student, gme}] – Quelle der Wahrheit
// für Anzahl/Reihenfolge der Phasen; die Feldwerte werden vor jedem Neuaufbau aus dem DOM
// zurückgelesen (syncPhasesFromDom), damit Tippen kein Re-Render auslöst.
let lessonPhases = [];

function emptyPhase(kind, minutes) {
  return { kind, minutes: minutes == null ? "" : String(minutes), socialForm: "EA",
           method: "", material: "", teacher: "", student: "", gme: "" };
}
function defaultPhases() {
  return ["Einstieg", "Erarbeitung", "Sicherung", "Ausstieg"].map((k) => emptyPhase(k));
}
function phaseDisplayNames(phases) {
  const total = {};
  phases.forEach((p) => (total[p.kind] = (total[p.kind] || 0) + 1));
  const seen = {};
  return phases.map((p) => {
    seen[p.kind] = (seen[p.kind] || 0) + 1;
    return total[p.kind] > 1 ? `${p.kind} ${ROMAN[seen[p.kind] - 1] || seen[p.kind]}` : p.kind;
  });
}
// Umkehrung für gespeicherte Stunden: „Erarbeitung II“ → „Erarbeitung“. Unbekannte
// Bezeichnungen (z. B. „Abschluss“ aus älteren Stunden) bleiben unverändert erhalten.
function phaseKindFromName(name) {
  const m = String(name || "").match(/^(.+?)\s+(?:I|II|III|IV|V|VI|VII|VIII|IX|X)$/);
  return (m ? m[1] : String(name || "")).trim();
}
function setPhasesFromLesson(phases) {
  const list = (phases || []).map((p) => ({
    kind: phaseKindFromName(p.phaseName) || "Erarbeitung",
    minutes: p.minutes == null ? "" : String(p.minutes),
    socialForm: SOCIAL_FORMS.includes(p.socialForm) ? p.socialForm : "EA",
    method: p.method || "", material: p.material || "",
    teacher: p.teacherActivity || "", student: p.studentActivity || "", gme: p.gme || "",
  }));
  lessonPhases = list.length ? list : defaultPhases();
  renderPhases();
}

function renderPhases() {
  const wrap = $("phases");
  if (!wrap) return;
  resetLocalUndo("phase-");
  const names = phaseDisplayNames(lessonPhases);
  wrap.innerHTML = lessonPhases.map((p, i) => {
    const kinds = PHASE_KINDS.includes(p.kind) ? PHASE_KINDS : PHASE_KINDS.concat([p.kind]);
    const kindOpts = kinds.map((k) =>
      `<option value="${esc(k)}" ${k === p.kind ? "selected" : ""}>${esc(k)}</option>`).join("");
    const socialOpts = SOCIAL_FORMS.map((s) =>
      `<option ${s === p.socialForm ? "selected" : ""}>${s}</option>`).join("");
    return `<div class="phase" data-local-undo-block="phase-${i}">
      <div class="phase-head">
        <span class="phase-title">
          <strong>${esc(names[i])}</strong>
          <select data-phase-kind="${i}" class="phase-kind-select" title="Bezeichnung dieser Phase">${kindOpts}</select>
        </span>
        <span class="phase-head-actions">
          <button class="btn tiny secondary" data-phase-move="${i}" data-dir="-1" ${i === 0 ? "disabled" : ""} title="Phase nach oben">↑</button>
          <button class="btn tiny secondary" data-phase-move="${i}" data-dir="1" ${i === lessonPhases.length - 1 ? "disabled" : ""} title="Phase nach unten">↓</button>
          <button class="btn tiny secondary" data-local-undo-btn disabled title="Letzte Änderung in dieser Phase rückgängig machen">Rückgängig</button>
          <button class="btn tiny danger" data-phase-del="${i}" title="Diese Phase entfernen">Entfernen</button>
        </span>
      </div>
      <div class="row-4" style="margin-top:10px;">
        <input placeholder="Zeit (Min.)" id="time${i}" value="${esc(p.minutes)}" />
        <select id="social${i}">${socialOpts}</select>
        <input placeholder="Methode" id="method${i}" value="${esc(p.method)}" />
        <input placeholder="Material/Raum" id="material${i}" value="${esc(p.material)}" />
      </div>
      <label>Lehrertätigkeit</label><textarea id="teacher${i}">${esc(p.teacher)}</textarea>
      <label>Schülertätigkeit</label><textarea id="student${i}">${esc(p.student)}</textarea>
      <label>Differenzierung (G/M/E)</label><textarea id="gme${i}">${esc(p.gme)}</textarea>
    </div>`;
  }).join("");
  wrap.querySelectorAll("[data-phase-kind]").forEach((sel) => (sel.onchange = () => {
    syncPhasesFromDom();
    lessonPhases[Number(sel.dataset.phaseKind)].kind = sel.value;
    renderPhases();
  }));
  wrap.querySelectorAll("[data-phase-del]").forEach((btn) => (btn.onclick = () => {
    syncPhasesFromDom();
    lessonPhases.splice(Number(btn.dataset.phaseDel), 1);
    renderPhases();
  }));
  wrap.querySelectorAll("[data-phase-move]").forEach((btn) => (btn.onclick = () => {
    syncPhasesFromDom();
    const from = Number(btn.dataset.phaseMove), to = from + Number(btn.dataset.dir);
    if (to < 0 || to >= lessonPhases.length) return;
    lessonPhases.splice(to, 0, lessonPhases.splice(from, 1)[0]);
    renderPhases();
  }));
  validatePhaseTimes();
  renderLernziele();   // Phasen-Auswahl der Lernziele hängt an Namen/Anzahl der Phasen
}

// Neue Phase vorbelegt mit der noch nicht verplanten Restzeit (damit die Stundendauer weiter
// exakt aufgeht) und eingefügt vor den abschließenden Phasen (Ausstieg/Puffer) – eine weitere
// Erarbeitung gehört vor den Ausstieg, nicht dahinter. Reihenfolge bleibt per ↑/↓ änderbar.
function addPhase() {
  syncPhasesFromDom();
  const duration = Number($("lessonDuration").value) || 45;
  const sum = lessonPhases.reduce((acc, p) => acc + (Number(p.minutes) || 0), 0);
  const rest = duration - sum;
  let at = lessonPhases.length;
  while (at > 0 && ["Ausstieg", "Puffer"].includes(lessonPhases[at - 1].kind)) at--;
  lessonPhases.splice(at, 0, emptyPhase("Erarbeitung", rest > 0 ? rest : ""));
  renderPhases();
}

function syncPhasesFromDom() {
  lessonPhases.forEach((p, i) => {
    if (!$("time" + i)) return;
    p.minutes = $("time" + i).value.trim();
    p.socialForm = $("social" + i).value;
    p.method = $("method" + i).value;
    p.material = $("material" + i).value;
    p.teacher = $("teacher" + i).value;
    p.student = $("student" + i).value;
    p.gme = $("gme" + i).value;
  });
}

// Zuordnung Phasen-Index im Formular → sort_order der gespeicherten Phase. Leere Phasen
// werden nicht gespeichert, dadurch verschieben sich die Indizes; readLernziele() rechnet
// phaseSortOrder darüber um (sonst zeigte ein Feinziel auf die falsche Phase).
let phaseIndexMap = {};

function readPhases() {
  syncPhasesFromDom();
  const names = phaseDisplayNames(lessonPhases);
  const out = [];
  phaseIndexMap = {};
  lessonPhases.forEach((p, i) => {
    const minutes = String(p.minutes).trim();
    if (!minutes && !p.method && !p.material && !p.teacher && !p.student && !p.gme) return;
    phaseIndexMap[i] = out.length;
    out.push({
      phaseName: names[i],
      minutes: minutes ? Number(minutes) : null,
      socialForm: p.socialForm,
      method: p.method.trim(), material: p.material.trim(),
      teacherActivity: p.teacher.trim(), studentActivity: p.student.trim(), gme: p.gme.trim(),
    });
  });
  return out;
}

// Live-Validierung: Die Summe aller Phasenzeiten (inkl. Puffer) muss die Stundendauer
// (45/90 Min.) exakt ausfüllen. Anzeige unter der Tabelle; beim Speichern wird zusätzlich
// nachgefragt (siehe saveLesson).
function validatePhaseTimes() {
  const duration = Number($("lessonDuration").value) || 45;
  syncPhasesFromDom();
  const sum = lessonPhases.reduce((acc, p) => acc + (Number(p.minutes) || 0), 0);
  const rest = duration - sum;
  lessonPhases.forEach((_, i) => {
    const el = $("time" + i);
    if (el) el.classList.toggle("input-error", rest !== 0);
  });
  const msg = $("phaseTimeError");
  if (msg) {
    msg.textContent = rest === 0
      ? `Zeit exakt verplant: ${sum} von ${duration} Min.`
      : rest > 0
        ? `Noch ${rest} Min. zu verplanen (${sum} von ${duration} Min.).`
        : `${-rest} Min. zu viel verplant (${sum} von ${duration} Min.).`;
    msg.classList.toggle("ok", rest === 0);
    msg.classList.remove("hidden");
  }
  return rest;
}
function clearPhaseTimeError() {
  lessonPhases.forEach((_, i) => { const el = $("time" + i); if (el) el.classList.remove("input-error"); });
  const msg = $("phaseTimeError");
  if (msg) { msg.textContent = ""; msg.classList.add("hidden"); msg.classList.remove("ok"); }
}

/* ---------- Sozialform-Monotonie-Warnung (regelbasiert, kein KI-Call) ----------
   Warnt, wenn die letzten 3 geplanten Stunden derselben Klasse dieselbe überwiegende
   Sozialform hatten (Meyer-Merkmal 4, Methodenvielfalt). Reines Auszählen über die
   bereits geladenen state.lessons (inkl. Phasen) – kein zusätzlicher API-Call nötig. */
const SOCIAL_FORM_LABELS = { EA: "Einzelarbeit", PA: "Partnerarbeit", GA: "Gruppenarbeit", Plenum: "Plenum" };

// Häufigste Sozialform unter den Phasen einer Stunde (leere Phasen zählen nicht mit).
function dominantSocialForm(lesson) {
  const counts = {};
  (lesson.phases || []).forEach((p) => {
    if (!p.socialForm) return;
    counts[p.socialForm] = (counts[p.socialForm] || 0) + 1;
  });
  let best = null, bestCount = 0;
  Object.keys(counts).forEach((k) => {
    if (counts[k] > bestCount) { best = k; bestCount = counts[k]; }
  });
  return best;
}

// Letzte 3 terminierten Stunden der Klasse (ohne die aktuell bearbeitete) – wenn alle
// dieselbe überwiegende Sozialform haben, deren Code zurückgeben, sonst null.
function checkSozialformMonotonie(classId, excludeLessonId) {
  const past = state.lessons
    .filter((l) => l.classId === classId && l.date && l.id !== excludeLessonId)
    .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
    .slice(0, 3);
  if (past.length < 3) return null;
  const forms = past.map(dominantSocialForm);
  if (forms.some((f) => !f)) return null;
  return (forms[0] === forms[1] && forms[1] === forms[2]) ? forms[0] : null;
}

function updateSozialformMonotonyHint() {
  const box = $("sozialformHint");
  if (!box) return;
  const classId = $("lessonClass").value ? Number($("lessonClass").value) : null;
  const form = classId ? checkSozialformMonotonie(classId, editingLessonId) : null;
  if (form) {
    box.textContent = `Die letzten 3 geplanten Stunden dieser Klasse waren überwiegend ${SOCIAL_FORM_LABELS[form] || form} – für Methodenvielfalt (Meyer-Merkmal 4) ggf. eine andere Sozialform wählen.`;
    box.classList.remove("hidden");
  } else {
    box.classList.add("hidden");
  }
}

/* ---------- Lernziele-Editor (M11) ---------- */
let lessonZiele = [];   // [{kind:'grob'|'fein', text, bloomStufe, phaseSortOrder}]
let lessonTafelbild = { titel: "", bloecke: [] };   // KI-Tafelbild-Vorschlag (U31)
let lessonTafelbildBildId = null;   // Material-id eines eigenen Tafelbild-Fotos (U31b), sonst null

function renderLernziele() {
  const wrap = $("lernzieleList");
  if (!wrap) return;
  resetLocalUndo("lernziel-");   // Karten-Indizes verschieben sich hier ggf. – alte Snapshots wären falsch zugeordnet.
  if (!lessonZiele.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine Lernziele. „Ziel hinzufügen“ oder „✨ Lernziele vorschlagen“.</p>';
    return;
  }
  wrap.innerHTML = lessonZiele.map((z, i) => {
    const isGrob = z.kind === "grob";
    const bloomOpts = ['<option value="">– Bloom-Stufe –</option>']
      .concat(BLOOM_STUFEN.map((b) => `<option value="${b}" ${z.bloomStufe === b ? "selected" : ""}>${b}</option>`)).join("");
    const phaseOpts = ['<option value="">– keine Phase –</option>']
      .concat(phaseDisplayNames(lessonPhases).map((p, pi) => `<option value="${pi}" ${String(z.phaseSortOrder) === String(pi) ? "selected" : ""}>${esc(p)}</option>`)).join("");
    return `<div class="phase" style="margin-top:8px;" data-local-undo-block="lernziel-${i}">
      <div class="phase-head">
        <strong>Lernziel ${i + 1}</strong>
        <button class="btn tiny secondary" data-local-undo-btn disabled title="Letzte Änderung an diesem Lernziel rückgängig machen">Rückgängig</button>
      </div>
      <div class="row-4" style="margin-top:10px;">
        <select data-zk="${i}"><option value="grob" ${isGrob ? "selected" : ""}>Grobziel</option><option value="fein" ${!isGrob ? "selected" : ""}>Feinziel</option></select>
        <select data-zb="${i}">${bloomOpts}</select>
        <select data-zp="${i}">${phaseOpts}</select>
        <button class="btn small danger" data-zdel="${i}">löschen</button>
      </div>
      <textarea data-zt="${i}" rows="2" placeholder="Lernziel (aus Schülersicht) …" style="${isGrob ? "font-weight:700;" : ""}">${esc(z.text)}</textarea>
    </div>`;
  }).join("");
  wrap.querySelectorAll("[data-zk]").forEach((el) =>
    (el.onchange = () => { lessonZiele[+el.dataset.zk].kind = el.value; renderLernziele(); }));
  wrap.querySelectorAll("[data-zb]").forEach((el) =>
    (el.onchange = () => { lessonZiele[+el.dataset.zb].bloomStufe = el.value || null; }));
  wrap.querySelectorAll("[data-zp]").forEach((el) =>
    (el.onchange = () => { lessonZiele[+el.dataset.zp].phaseSortOrder = el.value === "" ? null : Number(el.value); }));
  wrap.querySelectorAll("[data-zt]").forEach((el) =>
    (el.oninput = () => { lessonZiele[+el.dataset.zt].text = el.value; }));
  wrap.querySelectorAll("[data-zdel]").forEach((el) =>
    (el.onclick = () => { lessonZiele.splice(+el.dataset.zdel, 1); renderLernziele(); }));
}
function addLernziel() {
  lessonZiele.push({ kind: lessonZiele.some((z) => z.kind === "grob") ? "fein" : "grob", text: "", bloomStufe: null, phaseSortOrder: null });
  renderLernziele();
}
// indexMap: Formular-Phasenindex → sort_order der gespeicherten Phase (siehe readPhases).
// Ohne Map (Aufrufe außerhalb des Speicherns) bleibt phaseSortOrder unverändert.
function readLernziele(indexMap) {
  const mapped = (v) => {
    if (v == null) return null;
    if (!indexMap) return Number(v);
    return indexMap[v] == null ? null : indexMap[v];
  };
  return lessonZiele
    .filter((z) => (z.text || "").trim())
    .map((z, i) => ({ kind: z.kind, text: z.text.trim(), bloomStufe: z.bloomStufe || null,
                      phaseSortOrder: mapped(z.phaseSortOrder), sortOrder: i }));
}

// Datei, die im Erstellungsformular gewählt aber erst nach saveLesson() (sobald die lessonId
// existiert) tatsächlich hochgeladen/verknüpft wird – analog zu pendingSeqLinkIds.
let pendingLessonMaterialFile = null;
let pendingLessonMaterialSubject = "";

function clearLessonForm() {
  ["lessonIdeas", "lessonTitle", "lessonDate", "klafki1", "klafki2", "klafki3", "klafki4", "klafki5",
   "biboxWerk", "biboxSeite", "biboxNotiz", "lessonMatSubject",
   "tafelbildEingabe", "tafelbildNotiz", "hefteintrag"].forEach((id) => ($(id).value = ""));
  lessonTafelbild = { titel: "", bloecke: [] };
  lessonTafelbildBildId = null;
  renderTafelbild();
  if ($("tafelbildBildFile")) $("tafelbildBildFile").value = "";
  if ($("lessonMatFile")) $("lessonMatFile").value = "";
  if (lessonAutosaveTimer) { clearTimeout(lessonAutosaveTimer); lessonAutosaveTimer = null; }
  lessonPendingLinksApplied = false;
  lessonFormOpenedAsNew = true;
  lessonSetStatus("");
  pendingLessonMaterialFile = null;
  pendingLessonMaterialSubject = "";
  if ($("lessonMaterials")) $("lessonMaterials").innerHTML = "";
  $("lessonClass").value = "";
  $("lessonDuration").value = "45";
  if ($("lessonTime")) $("lessonTime").value = "";
  if ($("lessonSlot")) $("lessonSlot").value = "";
  lessonZiele = [];
  lessonPhases = defaultPhases();
  renderPhases();          // rendert die Lernziele gleich mit
  clearPhaseTimeError();
  resetMeyerGrid("meyerPlanGrid");
  $("diff").value = "ja";
  $("lernen").value = "ja";
  $("lueHint").classList.toggle("hidden", $("lessonType").value !== "Übungsstunde vor LUE");
  updateLessonLbOptions(null);
  pendingSeqLinkIds = [];
  updateLessonSeqOptions();
  pendingCalendarEntryLink = null;
  updateSozialformMonotonyHint();   // Klasse gerade zurückgesetzt → blendet den Hinweis aus
  resetLocalUndo();   // andere/neue Stunde geladen – alte Block-Snapshots (Phasen, Klafki, Lernziele) wären falsch.
}

// U30: Aus dem Termin-Bearbeiten-Fenster heraus in die Unterrichtsplanung springen und
// Klasse/Fach/Klassenstufe/Datum aus dem Termin vorbefüllen. Der Termin wird erst nach dem
// ersten Speichern der neuen Stunde verlinkt (pendingCalendarEntryLink, siehe saveLesson()).
function planLessonFromCalendarEntry(e) {
  closeModal();
  showView("stunde");
  clearLessonForm();
  // U30: manuelle Termine tragen die Klasse(n) in classIds (Mehrfachauswahl); classId (singular)
  // ist nur bei auto-generierten Stundenterminen gepflegt. Für die Vorbefüllung reicht eine Klasse.
  const firstClassId = (e.classIds && e.classIds.length) ? e.classIds[0] : e.classId;
  const cls = firstClassId != null ? state.classes.find((c) => c.id === firstClassId) : null;
  if (cls) {
    $("lessonClass").value = String(cls.id);
    if (cls.subject) $("lessonSubject").value = cls.subject;
    if (cls.grade != null) $("lessonGrade").value = String(cls.grade);
  }
  $("lessonDate").value = e.entryDate || "";
  if ($("lessonTime")) $("lessonTime").value = e.allDay ? "" : (e.startTime || "");
  updateLessonLbOptions(null);
  updateSozialformMonotonyHint();
  pendingCalendarEntryLink = e.id;
}

/* ---------- Bearbeitungsmodus Unterrichtsplanung ---------- */
let editingLessonId = null;
// U30: Termin, aus dem heraus "jetzt Unterrichtsstunde planen" die neue Stunde anlegt —
// wird nach dem ersten Speichern mit dem Termin verlinkt (siehe saveLesson()).
let pendingCalendarEntryLink = null;

// Autosave (Formular-Freitext + Struktur): debounced, still, per Event-Delegation auf die
// gesamte #stunde-Sektion (input+change) statt einzelner Feld-Listener – das Formular ist zu
// groß/dynamisch (Phasen, Lernziele werden nachträglich ins DOM gerendert), um jedes Feld
// einzeln zu verdrahten. lessonPendingLinksApplied entkoppelt die einmaligen Seiteneffekte
// (Material-Upload, Termin-/Sequenzstunden-Verknüpfung) davon, OB der Autosave die Stunde
// bereits im Hintergrund angelegt hat – sonst würde ein späterer manueller Klick auf
// "Stunde speichern" sie fälschlich als reines Update ansehen und die Verknüpfungen nie
// anwenden (isNew wäre dann schon false).
const LESSON_AUTOSAVE_EXCLUDE = new Set(["lessonIdeas", "lessonMatFile", "lessonMatSubject", "lessonTodoInput"]);
let lessonAutosaveTimer = null;
let lessonPendingLinksApplied = false;
let lessonFormOpenedAsNew = true;   // für die "gespeichert"/"aktualisiert"-Toast-Formulierung

function lessonSetStatus(text) {
  const el = $("lessonSaveStatus");
  if (el) el.textContent = text;
}

function scheduleLessonAutosave() {
  if (!$("lessonTitle").value.trim()) {
    if (lessonAutosaveTimer) { clearTimeout(lessonAutosaveTimer); lessonAutosaveTimer = null; }
    lessonSetStatus("");
    return;
  }
  lessonSetStatus("Ungespeicherte Änderungen …");
  if (lessonAutosaveTimer) clearTimeout(lessonAutosaveTimer);
  lessonAutosaveTimer = setTimeout(silentSaveLesson, 1200);
}

function buildLessonBody() {
  const meyer = readMeyerGrid("meyerPlanGrid");
  const phases = readPhases();          // setzt phaseIndexMap für readLernziele()
  return {
    title: $("lessonTitle").value.trim(), subject: $("lessonSubject").value, grade: Number($("lessonGrade").value),
    lessonType: $("lessonType").value,
    durationMinutes: Number($("lessonDuration").value) || 45,
    classId: $("lessonClass").value ? Number($("lessonClass").value) : null,
    lernbereichId: $("lessonLb") && $("lessonLb").value ? Number($("lessonLb").value) : null,
    date: $("lessonDate").value || null,
    time: $("lessonTime").value || null,
    klafki: {
      gegenwart: $("klafki1").value, zukunft: $("klafki2").value, exemplarisch: $("klafki3").value,
      zugang: $("klafki4").value, struktur: $("klafki5").value,
    },
    meyerPlan: meyer.some((v) => v) ? meyer : null,
    diff: $("diff").value, selbstLernen: $("lernen").value,
    bibox: { werk: $("biboxWerk").value, seite: $("biboxSeite").value, notiz: $("biboxNotiz").value },
    tafelbildEingabe: $("tafelbildEingabe").value, tafelbild: lessonTafelbild,
    tafelbildNotiz: $("tafelbildNotiz").value,
    hefteintrag: $("hefteintrag").value,
    tafelbildBildMaterialId: lessonTafelbildBildId,
    phases,
    lernziele: readLernziele(phaseIndexMap),
  };
}

// Legt die Stunde beim ersten Aufruf an (create), jeder weitere Aufruf aktualisiert dieselbe
// Zeile – von saveLesson() und silentSaveLesson() gleichermaßen genutzt.
async function persistLessonBody(body) {
  if (editingLessonId) return await SyncEngine.update("lessons", editingLessonId, body);
  const saved = await SyncEngine.createAndSync("lessons", body);
  editingLessonId = saved.id;
  return saved;
}

// Material-Upload/Kalender-Verknüpfung/Sequenz-Verknüpfung: einmalige Seiteneffekte, sobald die
// Stunde erstmals eine echte id hat (egal ob durch Autosave oder manuelles Speichern ausgelöst).
async function applyPendingLessonLinks(saved, body) {
  if (lessonPendingLinksApplied) return;
  lessonPendingLinksApplied = true;
  if (pendingLessonMaterialFile) {
    const fd = new FormData();
    fd.append("file", pendingLessonMaterialFile);
    fd.append("subject", pendingLessonMaterialSubject || body.subject);
    if (body.grade) fd.append("grade", body.grade);
    fd.append("lessonId", saved.id);
    try { await API.upload("/materials/upload", fd); }
    catch (e2) { toast("Stunde gespeichert, Material-Upload ist aber fehlgeschlagen: " + e2.message, false); }
    pendingLessonMaterialFile = null;
    pendingLessonMaterialSubject = "";
  }
  if (pendingCalendarEntryLink) {
    const linkId = pendingCalendarEntryLink;
    pendingCalendarEntryLink = null;
    try {
      await SyncEngine.update("calendar_entries", linkId, { lessonId: saved.id });
      // s. Kommentar in der ursprünglichen saveLesson()-Fassung: verwaisten Auto-Kalendereintrag
      // entfernen, der beim Anlegen der Stunde nebenbei entstanden ist.
      await SyncEngine.pull();
      const dupes = (await SyncEngine.materialize("calendar_entries")).filter(
        (c) => c.lessonId === saved.id && c.id !== linkId && c.autoGenerated
      );
      for (const d of dupes) await SyncEngine.remove("calendar_entries", d.id);
    } catch (e2) { toast("Stunde gespeichert, Verknüpfung mit dem Termin ist aber fehlgeschlagen: " + e2.message, false); }
  }
  for (const seqId of pendingSeqLinkIds) {
    const seqInfo = seqOptionsCache.find((x) => x.id === seqId);
    try {
      await API.post(`/sequenz-stunden/${seqId}/link`, { lessonId: saved.id });
      await offerSeqCalendarEntry(seqId, seqInfo, body.date);
    }
    catch (e) { toast("Stunde gespeichert, Verknüpfung mit der Sequenzstunde ist aber fehlgeschlagen: " + e.message, false); }
  }
  pendingSeqLinkIds = [];
}

async function silentSaveLesson() {
  lessonAutosaveTimer = null;
  if (!$("lessonTitle").value.trim()) { lessonSetStatus(""); return; }
  validatePhaseTimes();   // aktualisiert nur die Inline-Anzeige – kein Confirm-Dialog beim Autosave
  const body = buildLessonBody();
  try {
    const saved = await persistLessonBody(body);
    await applyPendingLessonLinks(saved, body);
    lessonSetStatus("Automatisch gespeichert.");
  } catch (e) { lessonSetStatus("Automatisches Speichern fehlgeschlagen."); }
}

// Vor View-Wechsel aufrufen, damit ein ausstehender Autosave nicht verworfen wird.
async function flushLessonAutosave() {
  if (lessonAutosaveTimer) { clearTimeout(lessonAutosaveTimer); lessonAutosaveTimer = null; await silentSaveLesson(); }
}

function resetLessonEditState() {
  editingLessonId = null;
  $("editHint").classList.add("hidden");
  const h = $("stundeEinordnungHint");
  if (h) { h.classList.add("hidden"); $("stundeEinordnungResult").textContent = ""; }
}
function loadLessonIntoForm(l) {
  clearLessonForm();
  editingLessonId = l.id;
  lessonFormOpenedAsNew = false;
  syncHash("stunde");
  $("lessonTitle").value = l.title || "";
  $("lessonSubject").value = l.subject || "Deutsch";
  if (l.grade != null) $("lessonGrade").value = String(l.grade);
  if (l.lessonType) $("lessonType").value = l.lessonType;
  $("lueHint").classList.toggle("hidden", $("lessonType").value !== "Übungsstunde vor LUE");
  const clsVal = l.classId == null ? "" : String(l.classId);
  if (clsVal && !$("lessonClass").querySelector(`option[value="${clsVal}"]`)) {
    // Klasse ist archiviert: Zuordnung sichtbar erhalten statt beim Speichern still zu verlieren.
    const opt = document.createElement("option");
    opt.value = clsVal;
    opt.textContent = "(archivierte Klasse)";
    $("lessonClass").appendChild(opt);
  }
  $("lessonClass").value = clsVal;
  updateSozialformMonotonyHint();
  $("lessonDate").value = l.date || "";
  $("lessonDuration").value = String(l.durationMinutes || 45);
  $("lessonTime").value = l.time || "";
  const matchingSlot = (lessonSlotsCache || []).find((s) => s.startTime === l.time);
  $("lessonSlot").value = matchingSlot ? String(matchingSlot.id) : "";
  lessonZiele = (l.lernziele || []).map((z) => ({
    kind: z.kind === "grob" ? "grob" : "fein", text: z.text || "",
    bloomStufe: z.bloomStufe || null, phaseSortOrder: z.phaseSortOrder == null ? null : Number(z.phaseSortOrder),
  }));
  renderLernziele();
  const k = l.klafki || {};
  $("klafki1").value = k.gegenwart || ""; $("klafki2").value = k.zukunft || "";
  $("klafki3").value = k.exemplarisch || ""; $("klafki4").value = k.zugang || "";
  $("klafki5").value = k.struktur || "";
  setMeyerGrid("meyerPlanGrid", l.meyerPlan || []);
  if (l.diff) $("diff").value = l.diff;
  if (l.selbstLernen) $("lernen").value = l.selbstLernen;
  const b = l.bibox || {};
  $("biboxWerk").value = b.werk || ""; $("biboxSeite").value = b.seite || ""; $("biboxNotiz").value = b.notiz || "";
  $("tafelbildEingabe").value = l.tafelbildEingabe || "";
  lessonTafelbild = l.tafelbild || { titel: "", bloecke: [] };
  lessonTafelbildBildId = l.tafelbildBildMaterialId != null ? l.tafelbildBildMaterialId : null;
  renderTafelbild();
  $("tafelbildNotiz").value = l.tafelbildNotiz || "";
  $("hefteintrag").value = l.hefteintrag || "";
  setPhasesFromLesson(l.phases);
  $("editHintTitle").textContent = l.title || "";
  $("editHint").classList.remove("hidden");
  // Freie Stunde ohne Lernbereich: KI-Einordnungshinweis anbieten.
  const h = $("stundeEinordnungHint");
  if (h) {
    $("stundeEinordnungResult").textContent = "";
    h.classList.toggle("hidden", l.lernbereichId != null);
  }
  updateLessonLbOptions(l.lernbereichId ?? null);
  updateLessonSeqOptions();
  loadLessonMaterials(l.id);
}

// Stunde duplizieren: alle Felder wie beim Bearbeiten übernehmen, aber ohne die bestehende
// ID (Speichern legt eine neue Stunde an) und ohne Datum/Material – Klasse und Datum lassen
// sich danach frei ändern, bevor gespeichert wird.
function duplicateLessonIntoForm(l) {
  loadLessonIntoForm(l);
  editingLessonId = null;
  lessonFormOpenedAsNew = true;
  $("lessonDate").value = "";
  if ($("lessonMaterials")) $("lessonMaterials").innerHTML = '<p class="muted small">Noch kein Material verknüpft.</p>';
  $("editHint").classList.add("hidden");
  toast("Stunde dupliziert – Klasse/Datum prüfen und speichern.", true);
}

async function loadLessonMaterials(lessonId) {
  const wrap = $("lessonMaterials");
  if (!wrap) return;
  try {
    const mats = await API.get(`/lessons/${lessonId}/materials`);
    wrap.innerHTML = mats.length
      ? mats.map((m) => `<div class="file-chip"><span><a href="/api/materials/${m.id}/download">${esc(m.filename)}</a></span><button class="btn small danger" data-del-mat="${m.id}" aria-label="Material entfernen">✕</button></div>`).join("")
      : '<p class="muted small">Noch kein Material verknüpft.</p>';
    wireMaterialDeleteButtons(wrap, () => loadLessonMaterials(lessonId));
  } catch (e) { wrap.innerHTML = ""; }
}

// Löschen (Archivieren) von Material direkt aus einer Stunden-Materialliste heraus —
// gleiches Verhalten wie in der Materialbibliothek: Archiv statt Hard-Delete, per Undo wiederherstellbar.
function wireMaterialDeleteButtons(wrap, onDeleted) {
  wrap.querySelectorAll("[data-del-mat]").forEach((b) => {
    b.onclick = async (ev) => {
      ev.stopPropagation();
      const id = b.dataset.delMat;
      if (!confirm("Material archivieren? Es lässt sich im Archiv wiederherstellen.")) return;
      try {
        await API.post("/materials/" + id + "/archive");
        toast("Material archiviert.");
        setUndo("Material archiviert.", async () => { await API.post("/materials/" + id + "/restore"); await onDeleted(); });
        await onDeleted();
      } catch (e) { toast(e.message, false); }
    };
  });
}

/* ---------- U29: LB-Zuordnung in der Unterrichtsplanung (aus aktivem Stoffverteilungsplan) ---------- */
// Befüllt das LB-Select anhand des aktiven Stoffplans der gewählten Klasse; blendet die Zeile aus, wenn
// keine Klasse gewählt ist oder kein aktiver Plan existiert (Stunde bleibt dann ohne LB anlegbar).
async function updateLessonLbOptions(preselectLbId) {
  const row = $("lessonLbRow"), sel = $("lessonLb");
  if (!row || !sel) return;
  const clsId = $("lessonClass").value ? Number($("lessonClass").value) : null;
  const ap = clsId ? state.activePlans[clsId] : null;
  if (!clsId || !ap || !ap.blocks.length) {
    row.classList.add("hidden");
    sel.innerHTML = '<option value="">– kein Lernbereich –</option>';
    $("lessonLbProgress").textContent = "";
    return;
  }
  const cls = state.classes.find((c) => c.id === clsId);
  const lbList = cls
    ? await getLernbereiche({ subject: cls.subject, grade: cls.grade, track: resolveTrack(cls.subject, cls.grade, cls.track) })
    : [];
  const resolved = ap.blocks
    .map((b) => ({ block: b, lb: lbList.find((l) => l.code === b.lbCode) }))
    .filter((x) => x.lb);
  sel.innerHTML = '<option value="">– kein Lernbereich –</option>' +
    resolved.map((x) => `<option value="${x.lb.id}" data-ustd="${esc(x.block.ustd ?? "")}">${esc(x.block.lbCode)} ${esc(x.block.title || "")}</option>`).join("");
  if (preselectLbId != null && !sel.querySelector(`option[value="${preselectLbId}"]`)) {
    const opt = document.createElement("option");
    opt.value = String(preselectLbId);
    opt.textContent = "(Lernbereich außerhalb des aktiven Plans)";
    sel.appendChild(opt);
  }
  sel.value = preselectLbId != null ? String(preselectLbId) : "";
  row.classList.remove("hidden");
  updateLessonLbProgress();
}

// Zeigt "X von Y Stunden verplant" für den aktuell im LB-Select gewählten Lernbereich.
// X = Summe der Dauer (in 45-Min.-Einheiten) aller Stunden der Klasse mit diesem LB, Y = Sollstunden (ustd) des Blocks.
function updateLessonLbProgress() {
  const out = $("lessonLbProgress");
  if (!out) return;
  const opt = $("lessonLb").selectedOptions[0];
  const clsId = $("lessonClass").value ? Number($("lessonClass").value) : null;
  const lbId = $("lessonLb").value ? Number($("lessonLb").value) : null;
  if (!clsId || !lbId || !opt || opt.dataset.ustd === undefined || opt.dataset.ustd === "") { out.textContent = ""; return; }
  const soll = Number(opt.dataset.ustd);
  const planned = state.lessons
    .filter((l) => l.classId === clsId && l.lernbereichId === lbId)
    .reduce((sum, l) => sum + (Number(l.durationMinutes) || 45) / 45, 0);
  out.textContent = `${planned % 1 === 0 ? planned : planned.toFixed(1)} von ${soll} Stunden verplant`;
}

// Sequenzstunde(n) (max. 2, für eine Doppelstunde), die beim nächsten Speichern der Stunde
// verknüpft werden sollen (gesetzt durch Auswahl in #lessonSeqList, verbraucht/zurückgesetzt
// in saveLesson()/clearLessonForm()).
let pendingSeqLinkIds = [];
let seqOptionsCache = [];   // [{id, blockId, title, grobziel, lernbereichId, isLk, isReferat, isKomplexeArbeit, isKlassenarbeit}]

// Befüllt #lessonSeqList mit den noch unverknüpften Sequenzstunden aller Blöcke des aktiven
// Stoffplans der gewählten Klasse (analog updateLessonLbOptions). Checkbox-Liste statt Select,
// damit bis zu 2 Stunden (Doppelstunde) oder auch keine (z. B. Vertretung) gewählt werden können.
async function updateLessonSeqOptions() {
  const row = $("lessonSeqRow"), list = $("lessonSeqList");
  if (!row || !list) return;
  const clsId = $("lessonClass").value ? Number($("lessonClass").value) : null;
  const ap = clsId ? state.activePlans[clsId] : null;
  seqOptionsCache = [];
  pendingSeqLinkIds = [];
  collapsedSeqBlocks.clear();
  lastAutoSeqTitle = "";
  if (!clsId || !ap || !ap.blocks.length) {
    row.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  const cls = state.classes.find((c) => c.id === clsId);
  const lbList = cls
    ? await getLernbereiche({ subject: cls.subject, grade: cls.grade, track: resolveTrack(cls.subject, cls.grade, cls.track) })
    : [];
  const perBlock = await Promise.all(ap.blocks.map(async (b) => {
    try {
      const rows = await API.get(`/sequenz-stunden?blockId=${b.id}`);
      const lb = lbList.find((l) => l.code === b.lbCode);
      return rows.filter((r) => r.lessonId == null)
        .map((r) => ({ id: r.id, blockId: b.id, title: r.title, grobziel: r.grobziel,
                       lernbereichId: lb ? lb.id : null, blockLabel: `${b.lbCode || ""} ${b.title || ""}`.trim(),
                       isLk: r.isLk, isReferat: r.isReferat,
                       isKomplexeArbeit: r.isKomplexeArbeit, isKlassenarbeit: r.isKlassenarbeit }));
    } catch (e) { return []; }
  }));
  seqOptionsCache = perBlock.flat();
  renderLessonSeqList();
  row.classList.toggle("hidden", seqOptionsCache.length === 0);
}

// Eingeklappte Lernbereich-Blöcke der Sequenzstunden-Auswahl (blockId). Bleibt über
// Re-Renders hinweg erhalten, wird beim Klassenwechsel in updateLessonSeqOptions geleert.
const collapsedSeqBlocks = new Set();

function renderLessonSeqList() {
  const list = $("lessonSeqList");
  if (!list) return;
  if (!seqOptionsCache.length) { list.innerHTML = '<p class="muted small">Keine offenen Sequenzstunden.</p>'; return; }
  const capped = pendingSeqLinkIds.length >= 2;
  // Nach Lernbereich-Block gruppieren (Reihenfolge wie im Stoffverteilungsplan).
  const blocks = [];
  seqOptionsCache.forEach((s) => {
    let b = blocks.find((x) => x.blockId === s.blockId);
    if (!b) { b = { blockId: s.blockId, label: s.blockLabel, items: [] }; blocks.push(b); }
    b.items.push(s);
  });
  list.innerHTML = blocks.map((b) => {
    const collapsed = collapsedSeqBlocks.has(b.blockId);
    const chosen = b.items.filter((s) => pendingSeqLinkIds.includes(s.id)).length;
    const rows = collapsed ? "" : b.items.map((s) => {
      const checked = pendingSeqLinkIds.includes(s.id);
      const disabled = capped && !checked;
      return `<label class="small" style="display:block; margin:4px 0 4px 18px;">
        <input type="checkbox" data-lesson-seq="${s.id}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} style="width:auto;" />
        ${esc(s.title)}
      </label>`;
    }).join("");
    return `<div class="lesson-seq-block">
      <button type="button" class="lesson-seq-block-head" data-seq-block="${b.blockId}"
              aria-expanded="${collapsed ? "false" : "true"}" title="${collapsed ? "Ausklappen" : "Einklappen"}">
        <span class="lesson-seq-caret">${collapsed ? "▸" : "▾"}</span>
        <strong>${esc(b.label || "Lernbereich")}</strong>
        <span class="muted small">${b.items.length} Stunde(n)${chosen ? ` · ${chosen} gewählt` : ""}</span>
      </button>${rows}
    </div>`;
  }).join("");
  list.querySelectorAll("[data-seq-block]").forEach((btn) => {
    btn.onclick = () => {
      const id = Number(btn.dataset.seqBlock);
      if (collapsedSeqBlocks.has(id)) collapsedSeqBlocks.delete(id); else collapsedSeqBlocks.add(id);
      renderLessonSeqList();
    };
  });
  list.querySelectorAll("[data-lesson-seq]").forEach((cb) => {
    cb.onchange = () => toggleLessonSeqSelection(Number(cb.dataset.lessonSeq), cb.checked);
  });
}

// Titel, den applyLessonSeqSelection zuletzt selbst eingetragen hat – so wird ein manuell
// überschriebener Titel beim nächsten Toggle nicht wieder verdrängt.
let lastAutoSeqTitle = "";

function toggleLessonSeqSelection(id, checked) {
  if (checked) {
    if (pendingSeqLinkIds.length >= 2) return;
    pendingSeqLinkIds.push(id);
  } else {
    pendingSeqLinkIds = pendingSeqLinkIds.filter((x) => x !== id);
  }
  applyLessonSeqSelection();
  renderLessonSeqList();
}

function applyLessonSeqSelection() {
  const selected = pendingSeqLinkIds.map((id) => seqOptionsCache.find((x) => x.id === id)).filter(Boolean);
  const joinedTitle = selected.map((s) => s.title).filter(Boolean).join(" / ");
  if (joinedTitle && ($("lessonTitle").value.trim() === "" || $("lessonTitle").value === lastAutoSeqTitle)) {
    $("lessonTitle").value = joinedTitle;
  }
  lastAutoSeqTitle = joinedTitle;
  const lb = selected.find((s) => s.lernbereichId != null);
  if (lb) { $("lessonLb").value = String(lb.lernbereichId); updateLessonLbProgress(); }
  selected.forEach((s) => {
    if (s.grobziel && !lessonZiele.some((z) => z.kind === "grob" && z.text === s.grobziel)) {
      lessonZiele.push({ kind: "grob", text: s.grobziel, bloomStufe: null, phaseSortOrder: null, sortOrder: lessonZiele.length });
    }
  });
  renderLernziele();
  if (selected.length === 2) $("lessonDuration").value = "90";
}

// Bietet nach dem Verknüpfen einer Sequenzstunde mit Notenart-Flag an, den bereits
// automatisch erzeugten Kalendereintrag entsprechend zu typisieren (nur wenn die Stunde ein
// echtes Datum hat – ohne Datum existiert noch kein Kalendereintrag zum Anpassen).
async function offerSeqCalendarEntry(seqId, seqInfo, lessonDate) {
  if (!seqInfo || !lessonDate) return;
  const isExam = seqInfo.isKlassenarbeit || seqInfo.isKomplexeArbeit;
  const isLu = seqInfo.isLk || seqInfo.isReferat;
  if (!isExam && !isLu) return;
  const label = seqInfo.isKlassenarbeit ? "Klassenarbeit" : seqInfo.isKomplexeArbeit ? "komplexe Arbeit"
    : seqInfo.isReferat ? "Referat" : "Lernkontrolle";
  const wants = window.confirm(`Diese Stunde ist als ${label} markiert. Jetzt entsprechend im Kalender eintragen?`);
  if (!wants) return;
  try {
    await API.post(`/sequenz-stunden/${seqId}/apply-calendar-entry`, { type: isExam ? "exam" : "lu" });
    toast("Kalendereintrag aktualisiert.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- Laden & Rendern ---------- */
async function loadAll() {
  // notes: über die Sync-Engine (Pull holt Server-Änderungen in OfflineDB, materialize()
  // legt noch unbestätigte lokale Mutationen darüber) statt direkt per API.get — dadurch
  // bleiben offline angelegte/geänderte Notizen sichtbar. pull() ist offline ein No-Op,
  // materialize() liefert dann den zuletzt bekannten Stand + Warteschlange.
  await SyncEngine.pull();
  const [classesAll, lessonsAll, reflectionsAll, open, materials, todosAll, notes, schoolYearsAll, calendarAll, calendarCategoriesAll, asuvDrafts] = await Promise.all([
    SyncEngine.materialize("classes"), SyncEngine.materialize("lessons"), SyncEngine.materialize("reflections"),
    API.get("/reflections/open"), API.get("/materials"), SyncEngine.materialize("todos"),
    SyncEngine.materialize("notes"), SyncEngine.materialize("school_years"), SyncEngine.materialize("calendar_entries"),
    SyncEngine.materialize("calendar_categories"), API.get("/asuv"),
  ]);
  // Archivierte Termine bleiben wie bisher außerhalb von state.calendar (eigene Abfrage in
  // der Archiv-Ansicht, renderArchivKalender), Reihenfolge wie ORDER BY entry_date.
  const calendar = calendarAll.filter((e) => e.archivedAt == null)
    .sort((a, b) => String(a.entryDate).localeCompare(String(b.entryDate)));
  // materialize() sortiert nicht — Reihenfolge wie der bisherige Backend-Endpunkt
  // (ORDER BY id, hier über createdAt als stabiles Anlage-Datum nachgebildet).
  const lessons = lessonsAll.slice()
    .sort((a, b) => String(a.createdAt || "").localeCompare(String(b.createdAt || "")) || String(a.id).localeCompare(String(b.id)));
  // Archivierte To-dos bleiben wie bisher außerhalb von state.todos (eigene Abfrage in der
  // Archiv-Ansicht, renderArchivTodos) — materialize() liefert wie die DB-Tabelle alle Zeilen.
  const todos = todosAll.filter((t) => t.archivedAt == null);
  // materialize() sortiert nicht (IndexedDB liefert nach localId) — Reihenfolge wie der
  // bisherige Backend-Endpunkt (ORDER BY sort_order, id) hier client-seitig herstellen.
  const calendarCategories = calendarCategoriesAll.slice()
    .sort((a, b) => (a.sortOrder - b.sortOrder) || (String(a.id).localeCompare(String(b.id))));
  const schoolYears = schoolYearsAll.slice()
    .sort((a, b) => String(a.startDate).localeCompare(String(b.startDate)));
  // Archivierte Klassen bleiben wie bisher außerhalb von state.classes (eigene Abfrage in
  // der Archiv-Ansicht, renderArchivKlassen), Reihenfolge wie ORDER BY name.
  const classes = classesAll.filter((c) => c.archivedAt == null)
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  // materialize() sortiert nicht — Reihenfolge wie der bisherige Backend-Endpunkt (ORDER BY id DESC).
  const reflections = reflectionsAll.slice()
    .sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")) || String(b.id).localeCompare(String(a.id)));
  let schoolDates = [];
  for (const sy of schoolYears) {
    try { schoolDates = schoolDates.concat(await API.get(`/school-years/${sy.id}/dates`)); }
    catch (e) { /* best effort */ }
  }
  Object.assign(state, { classes, lessons, reflections, open, materials, todos, notes, schoolYears, calendar, calendarCategories, schoolDates, asuvDrafts });
  await loadActivePlans();
}

// U15: aktive Stoffpläne aller Klassen laden (nur Lesezugriff auf bestehende Endpunkte).
// Ergebnis: state.activePlans[classId] = { planId, title, blocks:[{lbCode,title,ustd,startDate,endDate}] }
async function loadActivePlans() {
  const activePlans = {};
  let allStoffPlans = [];
  try { allStoffPlans = await SyncEngine.materialize("stoff_plans"); } catch (e) { /* offline: activePlans bleibt leer */ }
  for (const c of state.classes) {
    const active = allStoffPlans.find((p) => String(p.classId) === String(c.id) && p.status === "aktiv");
    if (!active) continue;
    activePlans[c.id] = { planId: active.id, title: active.title, blocks: active.blocks || [] };
  }
  state.activePlans = activePlans;
}

async function getLernbereiche(c) {
  const key = `${c.subject}|${c.grade}|${c.track || ""}`;
  if (!lbCache[key] || lbCache[key].length === 0) {   // leere Ergebnisse nicht dauerhaft cachen
    lbCache[key] = await API.get(
      `/lernbereiche?subject=${encodeURIComponent(c.subject)}&grade=${c.grade}&track=${encodeURIComponent(c.track || "")}`);
  }
  return lbCache[key];
}

function renderAll() {
  renderClassTable();
  renderLessonFilterOptions();
  renderLessonTable();
  renderTodayList();
  renderHefterReminders();
  renderWeekOverview();
  renderReflectSelect();
  renderReflectTable();
  renderOpenReflections();
  renderTodos();
  reconcileHefterTodos();
  renderClassSelects();
  renderLessonSubjectOptions();
  renderClassToggles();
  renderSchoolYears();
  renderCategoryManager();
  renderCategorySelect();
  renderCalendar();
  renderCalendarLegend();
  renderTimeline();
  renderMaterialList();
  renderAsuvLibrary();
  renderAsuvLessonSelect();
  renderPraesentControls();
  renderSpruchDesTages();
}

function renderClassTable() {
  const b = document.querySelector("#classTable tbody");
  b.innerHTML = "";
  state.classes.forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><a href="#" class="class-name-link" data-open-class="${c.id}">${esc(c.name)}</a></td>` +
      `<td>${esc(c.subject)}</td><td>${esc(c.grade)}</td>` +
      `<td>${esc(c.track || "")}</td><td>${esc(c.weeklyHours)}</td><td>${esc(c.parallelGroup || "")}</td>` +
      `<td class="cd-row-actions">` +
      `<button class="btn small secondary" data-edit-class="${c.id}">bearbeiten</button> ` +
      `<button class="btn small danger" data-del-class="${c.id}">entfernen</button></td>`;
    b.appendChild(tr);
  });
  b.querySelectorAll("[data-open-class]").forEach((a) => {
    a.onclick = (e) => { e.preventDefault(); openClassDetail(Number(a.dataset.openClass)); };
  });
  b.querySelectorAll("[data-edit-class]").forEach((btn) => {
    btn.onclick = () => {
      const c = state.classes.find((x) => String(x.id) === btn.dataset.editClass);
      if (c) editClass(c);
    };
  });
  b.querySelectorAll("[data-del-class]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("Klasse archivieren? Bereits geplante Stunden bleiben erhalten.")) return;
      try { await SyncEngine.remove("classes", btn.dataset.delClass); await refresh(); toast("Klasse archiviert."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

/* ---------- Klasse anlegen/bearbeiten ---------- */
let editingClassId = null;
function resetClassForm() {
  editingClassId = null;
  $("className").value = ""; $("classGroup").value = "";
  $("saveClass").textContent = "Klasse speichern";
}
function editClass(c) {
  editingClassId = c.id;
  showView("klassen");
  $("className").value = c.name || "";
  $("classSubject").value = c.subject || "Deutsch";
  $("classGrade").value = String(c.grade);
  if (c.track) $("classTrack").value = c.track;
  $("classHours").value = String(c.weeklyHours || 2);
  $("classGroup").value = c.parallelGroup || "";
  $("saveClass").textContent = "Klasse aktualisieren";
  $("className").scrollIntoView({ behavior: "smooth", block: "center" });
}

/* ---------- Klassen-Detailseite (U14) ---------- */
// M6 U1: mehrere Klassen-Detailseiten offenhalten – ab M6 U2 Teil der globalen Tab-Leiste
// (siehe registerActiveTab/tabKeyFor), die auch andere Views als Tabs verwaltet. Die Tabs
// teilen sich denselben Datenbestand (state.classes etc.) – jeder Tab merkt sich nur, welche
// classId gerade angezeigt wird; nicht aktive Tabs werden nicht separat im DOM gehalten.
let detailClassId = null;

function openClassDetail(cid) {
  detailClassId = Number(cid);
  openStoffPlanId = null;            // U19: kein Stoffplan aus einer anderen Klasse offen halten
  showView("klasse-detail");
  renderClassDetail();
}

function renderClassDetail() {
  const c = state.classes.find((x) => String(x.id) === String(detailClassId));
  if (!c) { toast("Klasse nicht gefunden.", false); showView("klassen"); return; }
  $("cdTitle").textContent = `${c.name} (${c.subject})`;
  const meta = [
    ["Fach", c.subject], ["Klassenstufe", c.grade], ["Bildungsgang", c.track || "–"],
    ["Wochenstunden", c.weeklyHours], ["Parallelgruppe", c.parallelGroup || "–"],
  ];
  $("cdMeta").innerHTML = meta
    .map(([k, v]) => `<div class="cd-meta-item"><span class="cd-meta-k">${esc(k)}</span><span>${esc(v)}</span></div>`)
    .join("");

  const lessons = state.lessons.filter((l) => String(l.classId) === String(c.id));
  const wrap = $("cdLessons");
  wrap.innerHTML = "";
  if (!lessons.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine Stunden für diese Klasse geplant.</p>';
  } else {
    const asuvByLesson = new Set((state.asuvDrafts || []).map((a) => a.lessonId));
    lessons.forEach((l) => {
      const div = document.createElement("div");
      div.className = "mini-item";
      div.style.cursor = "pointer";
      const asuvBadge = asuvByLesson.has(l.id) ? '<span class="badge ok">ASUV</span>' : "";
      div.innerHTML =
        `<span class="time">${esc(l.date || "–")}</span>` +
        `<span>${esc(l.title)} <span class="muted small">(${esc(l.lessonType || "Stunde")})</span></span>${asuvBadge}`;
      div.onclick = () => openLessonModal(l);
      wrap.appendChild(div);
    });
  }
  renderClassStudents();
  renderClassDupControl();
  getSeatPlanModule().then((m) => m.initSeatPlan());
  renderClassDetailHefter();
  renderClassDetailLehrplan();
  renderClassDetailStoffPlans();
  renderClassDetailNotes();
}

/* ---------- Lehrplan-Abhakmodul: Ziele der Klassenstufe + Lernbereiche abhaken ----------
   Referenz kommt aus /lehrplan/checklist (nach Fach/Klassenstufe/Bildungsgang der Klasse
   gefiltert); der Abhak-Status hängt an DIESER Klasse (schuljahres-spezifisch). Reines
   Online-REST, kein Offline-Sync. Abgehakte Einträge bleiben sichtbar (durchgestrichen). */
let _cdLehrplanData = null;
const _cdLehrplanOpen = new Set();   // aufgeklappte Lernbereiche (id), sitzungsweit
let _cdLehrplanExtracting = false;

async function renderClassDetailLehrplan() {
  const wrap = $("cdLehrplan");
  const progBox = $("cdLehrplanProgress");
  if (!wrap) return;
  const clsId = detailClassId;
  wrap.innerHTML = '<p class="muted small" style="margin-top:0;">Lädt …</p>';
  if (progBox) progBox.innerHTML = "";
  try {
    _cdLehrplanData = await API.get("/lehrplan/checklist?classId=" + encodeURIComponent(clsId));
  } catch (e) {
    _cdLehrplanData = null;
    wrap.innerHTML = `<p class="muted small" style="margin-top:0;">Lehrplan konnte nicht geladen werden: ${esc(e.message)}</p>`;
    return;
  }
  if (String(detailClassId) !== String(clsId)) return; // Klasse zwischenzeitlich gewechselt
  _renderCdLehrplan();
}

// Alle abhakbaren Einträge flach (Ziele + Lernbereiche + Feinziele) – für den Gesamtzähler.
function _cdLehrplanCounts() {
  const d = _cdLehrplanData;
  const all = [...d.ziele, ...d.lernbereiche];
  d.lernbereiche.forEach((lb) => all.push(...(lb.lernziele || [])));
  return { done: all.filter((i) => i.checkedAt).length, total: all.length };
}

function _lpRow(item, type, opts) {
  const o = opts || {};
  const badge = item.richtwertUstd != null
    ? ` <span class="lp-check-ustd">${esc(item.richtwertUstd)} Ustd.</span>` : "";
  const code = o.code ? `<span class="lp-check-code">${esc(o.code)}</span> ` : "";
  const inhalte = item.inhalte
    ? ` <span class="lp-check-inhalte">(${esc(item.inhalte)})</span>` : "";
  const date = item.checkedAt ? `<span class="lp-check-date">${esc(deDate(item.checkedAt))}</span>` : "";
  return (
    `<label class="lp-check-item${item.checkedAt ? " done" : ""}${o.cls ? " " + o.cls : ""}">` +
    `<input type="checkbox" data-lp-type="${type}" data-lp-ref="${item.id}"${item.checkedAt ? " checked" : ""}/>` +
    `<span class="lp-check-text">${code}${esc(item.text)}${badge}${inhalte}</span>` +
    date +
    `</label>`
  );
}

function _renderCdLehrplan() {
  const wrap = $("cdLehrplan");
  const progBox = $("cdLehrplanProgress");
  const d = _cdLehrplanData;
  if (!wrap || !d) return;

  if (progBox) {
    const c = _cdLehrplanCounts();
    progBox.innerHTML = `<span class="lp-progress">${c.done}/${c.total} abgehakt</span>`;
  }

  const trackNames = { RS: "Realschulbildungsgang", HS: "Hauptschulbildungsgang", gemischt: "gemischt" };
  let head = "";
  if (d.trackFallback) {
    const shown = trackNames[d.track] || d.track;
    head +=
      `<p class="lp-hint">Bildungsgang der Klasse ist „${esc(d.classTrack || "—")}", ` +
      `der Lehrplan trennt hier aber nach Bildungsgang. Angezeigt wird der <strong>${esc(shown)}</strong>. ` +
      `Für den anderen den Bildungsgang der Klasse über „Stammdaten bearbeiten" anpassen.</p>`;
  } else if (d.ziele.length === 0 && d.lernbereiche.length === 0) {
    head += `<p class="lp-hint">Für Fach „${esc(d.subject)}" / Klassenstufe ${esc(d.grade)} liegt kein Lehrplan in der App vor.</p>`;
  }
  if (d.lernbereiche.length && d.lernzieleMissing > 0) {
    head +=
      `<div class="lp-extract">` +
      `<p class="muted small" style="margin:0;">Die einzelnen Lernziele aus dem Lehrplan (linke Spalte) ` +
      `werden einmalig per KI aus dem Lehrplantext erzeugt – für ${esc(d.lernzieleMissing)} von ` +
      `${esc(d.lernbereiche.length)} Lernbereichen dieser Klasse fehlen sie noch.</p>` +
      `<button class="btn small" id="cdLehrplanExtractBtn"${_cdLehrplanExtracting ? " disabled" : ""}>` +
      `${_cdLehrplanExtracting ? "Feinziele werden erzeugt …" : "Feinziele aus dem Lehrplan erzeugen"}</button>` +
      `</div>`;
  }

  // Ziele der Klassenstufe
  const zieleDone = d.ziele.filter((i) => i.checkedAt).length;
  let zieleHtml =
    `<div class="lp-check-group"><h4>Ziele der Klassenstufe ` +
    `<span class="muted small">(${zieleDone}/${d.ziele.length})</span></h4>` +
    (d.ziele.length ? d.ziele.map((i) => _lpRow(i, "ziel", {})).join("")
                    : '<p class="muted small">Keine Einträge im Lehrplan.</p>') +
    `</div>`;

  // Lernbereiche mit aufklappbaren Feinzielen
  const lbHtml = d.lernbereiche.map((lb) => {
    const kids = lb.lernziele || [];
    const kidsDone = kids.filter((k) => k.checkedAt).length;
    const open = _cdLehrplanOpen.has(lb.id);
    const frac = kids.length ? `${kidsDone}/${kids.length}` : "—";
    const toggle = kids.length
      ? `<button type="button" class="lp-lb-toggle" data-lb-toggle="${lb.id}" aria-expanded="${open}">` +
        `<span class="lp-lb-frac">${frac}</span><span class="lp-lb-caret">${open ? "▾" : "▸"}</span></button>`
      : `<span class="lp-lb-frac muted">${frac}</span>`;
    const kidRows = kids.map((k) => _lpRow(k, "lernziel", { cls: "lp-check-kid" })).join("");
    return (
      `<div class="lp-lb">` +
      `<div class="lp-lb-head">${_lpRow(lb, "lb", { code: lb.code })}${toggle}</div>` +
      (kids.length ? `<div class="lp-lb-kids"${open ? "" : " hidden"}>${kidRows}</div>` : "") +
      `</div>`
    );
  }).join("");
  const lbDone = d.lernbereiche.filter((i) => i.checkedAt).length;
  const lbGroup =
    `<div class="lp-check-group"><h4>Lernbereiche ` +
    `<span class="muted small">(${lbDone}/${d.lernbereiche.length})</span></h4>` +
    (d.lernbereiche.length ? lbHtml : '<p class="muted small">Keine Einträge im Lehrplan.</p>') +
    `</div>`;

  wrap.innerHTML = head + zieleHtml + lbGroup;

  const btn = $("cdLehrplanExtractBtn");
  if (btn) btn.onclick = () => _cdLehrplanRunExtract();

  wrap.querySelectorAll("[data-lb-toggle]").forEach((t) => {
    t.onclick = () => {
      const id = Number(t.dataset.lbToggle);
      if (_cdLehrplanOpen.has(id)) _cdLehrplanOpen.delete(id); else _cdLehrplanOpen.add(id);
      _renderCdLehrplan();
    };
  });

  wrap.querySelectorAll('input[type="checkbox"][data-lp-type]').forEach((cb) => {
    cb.onchange = async () => {
      const type = cb.dataset.lpType;
      const ref = Number(cb.dataset.lpRef);
      const checked = cb.checked;
      cb.disabled = true;
      try {
        const res = await API.put("/lehrplan/checks", {
          classId: detailClassId, itemType: type, itemRef: ref, checked,
        });
        let it = null;
        if (type === "ziel") it = _cdLehrplanData.ziele.find((x) => x.id === ref);
        else if (type === "lb") it = _cdLehrplanData.lernbereiche.find((x) => x.id === ref);
        else _cdLehrplanData.lernbereiche.forEach((lb) => {
          const hit = (lb.lernziele || []).find((k) => k.id === ref);
          if (hit) it = hit;
        });
        if (it) it.checkedAt = res.checkedAt || null;
        _renderCdLehrplan();
      } catch (e) {
        cb.checked = !checked;
        cb.disabled = false;
        toast(e.message, false);
      }
    };
  });
}

async function _cdLehrplanRunExtract() {
  if (_cdLehrplanExtracting) return;
  _cdLehrplanExtracting = true;
  _renderCdLehrplan();
  const btn = $("cdLehrplanExtractBtn");
  try {
    const { jobId } = await API.post("/lehrplan/lernziele/extract");
    while (true) {
      await new Promise((r) => setTimeout(r, 2500));
      const s = await API.get("/lehrplan/lernziele/extract/" + jobId);
      if (btn && s.progress) {
        btn.textContent = `Feinziele werden erzeugt … ${s.progress.processed}/${s.progress.total}`;
      }
      if (s.status === "done") { toast("Feinziele aus dem Lehrplan erzeugt."); break; }
      if (s.status === "error") { toast(s.error || "Extraktion fehlgeschlagen.", false); break; }
    }
  } catch (e) {
    toast(e.message, false);
  } finally {
    _cdLehrplanExtracting = false;
    if (String(detailClassId)) renderClassDetailLehrplan();
  }
}

/* ---------- Hefter der SuS: chronologische Übersicht der Heftereinträge dieser Klasse ----------
   Der Hefter folgt 1:1 der Stundenchronologie – kein eigenes Datenmodell, nur lessons.hefteintrag.
   Jede Zeile ist direkt editierbar (debounced Autosave über den Offline-Sync, wie modalTbNotiz). */
let cdHefterOnlyFilled = false;
let _cdHefterTimers = {};

function renderClassDetailHefter() {
  const wrap = $("cdHefter");
  const filterBox = $("cdHefterFilter");
  if (!wrap) return;
  const all = state.lessons
    .filter((l) => String(l.classId) === String(detailClassId))
    .sort((a, b) => (a.date || "9999").localeCompare(b.date || "9999") || (a.time || "").localeCompare(b.time || ""));
  const withEntry = all.filter((l) => (l.hefteintrag || "").trim()).length;

  if (filterBox) {
    filterBox.innerHTML =
      `<button class="btn small ${cdHefterOnlyFilled ? "" : "secondary"}" id="cdHefterToggle">` +
      `${cdHefterOnlyFilled ? "Alle Stunden zeigen" : "Nur mit Eintrag"}</button>`;
    $("cdHefterToggle").onclick = () => { cdHefterOnlyFilled = !cdHefterOnlyFilled; renderClassDetailHefter(); };
  }

  const lessons = cdHefterOnlyFilled ? all.filter((l) => (l.hefteintrag || "").trim()) : all;
  if (!all.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine Stunden für diese Klasse geplant.</p>';
    return;
  }
  wrap.innerHTML =
    `<p class="muted small" style="margin-top:0;">${withEntry} von ${all.length} Stunden mit Heftereintrag.</p>` +
    '<div class="table-scroll"><table class="hefter-table"><thead><tr>' +
    "<th>Datum</th><th>Stunde / Thema</th><th>Heftereintrag der SuS</th>" +
    "</tr></thead><tbody></tbody></table></div>";
  const tb = wrap.querySelector("tbody");
  lessons.forEach((l) => {
    const tr = document.createElement("tr");
    const dateCell = l.date
      ? `${esc(deDate(l.date))}${l.time ? `<small>${esc(l.time)}</small>` : ""}`
      : '<span class="muted">ohne Datum</span>';
    tr.innerHTML =
      `<td class="hefter-date">${dateCell}</td>` +
      `<td class="hefter-thema"><a href="#" data-open-lesson="${l.id}">${esc(l.title || "Stunde")}</a>` +
      `<span class="muted small">${esc(l.lessonType || "")}</span></td>` +
      `<td class="hefter-entry"></td>`;
    const ta = document.createElement("textarea");
    ta.className = "hefter-input";
    ta.rows = 2;
    ta.placeholder = "— noch kein Eintrag —";
    ta.value = l.hefteintrag || "";
    ta.addEventListener("input", () => {
      if (_cdHefterTimers[l.id]) clearTimeout(_cdHefterTimers[l.id]);
      _cdHefterTimers[l.id] = setTimeout(async () => {
        try {
          await SyncEngine.update("lessons", l.id, { hefteintrag: ta.value });
          l.hefteintrag = ta.value;
          if (editingLessonId === l.id && $("hefteintrag")) $("hefteintrag").value = ta.value;
        } catch (e) { toast(e.message, false); }
      }, 900);
    });
    tr.querySelector(".hefter-entry").appendChild(ta);
    tr.querySelector("[data-open-lesson]").onclick = (e) => {
      e.preventDefault();
      const les = state.lessons.find((x) => x.id === l.id);
      if (les) openLessonModal(les);
    };
    tb.appendChild(tr);
  });
}

/* ---------- U17-Anbindung: Notizen zu dieser Klasse in der Klassen-Detailansicht ----------
   Mini-Ausgabe desselben Arbeitsbereichs wie die Notizen-Hauptansicht (s. u.), auf die
   aktuelle Klasse gefiltert. Liste und Editor sind eigene DOM-Container, damit ein
   Autosave der Liste nie den Editor (und damit Fokus/Cursor) neu aufbaut. */
let cdNoteSelectedId = null;
let cdNoteIsDraft = false;
let cdNoteTimer = null;
let cdNoteSaving = false;
let cdNoteClassId = null;

function renderClassDetailNotes() {
  cdNoteClassId = detailClassId;
  cdNoteSelectedId = null;
  cdNoteIsDraft = false;
  if (cdNoteTimer) { clearTimeout(cdNoteTimer); cdNoteTimer = null; }
  const panel = $("cdNotesPanel");
  if (!panel) return;
  panel.innerHTML =
    `<div id="cdNoteListWrap" class="notiz-ws-mini-list"></div>` +
    `<div class="notiz-ws-mini-editor" id="cdNoteEditorWrap"></div>`;
  renderCdNoteList();
  renderCdNoteEditor();
}

function renderCdNoteList() {
  const wrap = $("cdNoteListWrap");
  if (!wrap) return;
  const notes = activeNotesSorted((n) => n.scope === "klasse" && n.classId === cdNoteClassId);
  if (!notes.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine Notizen für diese Klasse.</p>';
  } else {
    wrap.innerHTML = notes.map((n) => `
      <div class="notiz-mini-item${n.id === cdNoteSelectedId && !cdNoteIsDraft ? " active" : ""}" data-note-id="${n.id}">
        <span class="notiz-mini-title">${esc(noteTitle(n))}</span>
        <span class="notiz-mini-meta">${esc(noteDateLabel(n.updatedAt))}</span>
      </div>`).join("");
    wrap.querySelectorAll("[data-note-id]").forEach((el) => {
      el.onclick = async () => {
        await flushCdNoteSave();
        cdNoteSelectedId = parseNoteId(el.dataset.noteId);
        cdNoteIsDraft = false;
        renderCdNoteList();
        renderCdNoteEditor();
      };
    });
  }
}

function renderCdNoteEditor() {
  const wrap = $("cdNoteEditorWrap");
  if (!wrap) return;
  if (cdNoteTimer) { clearTimeout(cdNoteTimer); cdNoteTimer = null; }
  if (cdNoteIsDraft) {
    wrap.innerHTML =
      `<textarea id="cdNoteText" class="notizen-text" placeholder="Gedanken zu dieser Klasse …"></textarea>` +
      `<div class="notizen-foot"><span class="small muted" id="cdNoteStatus"></span>` +
      `<button class="btn small secondary" id="cdNoteCancelBtn">Verwerfen</button></div>`;
    const ta = $("cdNoteText");
    ta.value = "";
    ta.oninput = scheduleCdNoteSave;
    ta.focus();
    $("cdNoteCancelBtn").onclick = () => { cdNoteIsDraft = false; renderCdNoteEditor(); };
    return;
  }
  const note = state.notes.find((n) => n.id === cdNoteSelectedId && n.archivedAt == null);
  if (!note) {
    cdNoteSelectedId = null;
    wrap.innerHTML = '<p class="muted small" style="padding:2px 2px 8px;">Notiz auswählen oder „+ Neue Notiz" anlegen.</p>';
    return;
  }
  wrap.innerHTML =
    `<textarea id="cdNoteText" class="notizen-text" placeholder="Gedanken zu dieser Klasse …"></textarea>` +
    `<div class="notizen-foot"><span class="small muted" id="cdNoteStatus"></span>` +
    `<button class="btn small secondary" id="cdNoteArchiveBtn">Notiz archivieren</button></div>`;
  const ta = $("cdNoteText");
  ta.value = note.bodyMd || "";
  ta.oninput = scheduleCdNoteSave;
  $("cdNoteArchiveBtn").onclick = archiveCdNote;
}

function scheduleCdNoteSave() {
  const status = $("cdNoteStatus");
  if (status) status.textContent = "…";
  if (cdNoteTimer) clearTimeout(cdNoteTimer);
  cdNoteTimer = setTimeout(saveCdNote, 900);
}

async function flushCdNoteSave() {
  if (cdNoteTimer) { clearTimeout(cdNoteTimer); cdNoteTimer = null; await saveCdNote(); }
}

async function saveCdNote() {
  const ta = $("cdNoteText");
  if (!ta) return;
  if (cdNoteSaving) { scheduleCdNoteSave(); return; }
  const body = ta.value;
  cdNoteSaving = true;
  try {
    if (cdNoteIsDraft) {
      if (!body.trim()) { cdNoteSaving = false; return; }   // leere Entwürfe nicht anlegen
      const created = await SyncEngine.create("notes", { scope: "klasse", classId: cdNoteClassId, bodyMd: body });
      state.notes.push(created);
      cdNoteIsDraft = false;
      cdNoteSelectedId = created.id;
      renderCdNoteList();
      promoteCdDraftFoot();
    } else if (cdNoteSelectedId != null) {
      const updated = await SyncEngine.update("notes", cdNoteSelectedId, { bodyMd: body });
      const idx = state.notes.findIndex((n) => n.id === cdNoteSelectedId);
      if (idx >= 0) state.notes[idx] = updated;
      renderCdNoteList();
    }
    const st = $("cdNoteStatus"); if (st) st.textContent = "Gespeichert.";
  } catch (e) {
    const st = $("cdNoteStatus"); if (st) st.textContent = "";
    toast(e.message, false);
  } finally {
    cdNoteSaving = false;
  }
}

// Ersetzt nur die Fußzeile (Entwurf → gespeicherte Notiz), damit Fokus/Cursor im Textfeld erhalten bleiben.
function promoteCdDraftFoot() {
  const foot = document.querySelector("#cdNoteEditorWrap .notizen-foot");
  if (!foot) return;
  foot.innerHTML = `<span class="small muted" id="cdNoteStatus"></span><button class="btn small secondary" id="cdNoteArchiveBtn">Notiz archivieren</button>`;
  $("cdNoteArchiveBtn").onclick = archiveCdNote;
}

async function archiveCdNote() {
  if (cdNoteIsDraft || cdNoteSelectedId == null) return;
  if (!confirm("Diese Notiz archivieren? Sie wandert ins Archiv der Materialbibliothek.")) return;
  try {
    await flushCdNoteSave();
    await API.post(`/notes/${cdNoteSelectedId}/archive`);
    cdNoteSelectedId = null;
    await refresh();
    renderCdNoteList();
    renderCdNoteEditor();
    toast("Notiz archiviert.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- U16: Plan für Parallelklasse duplizieren (Klassen-Detail) ---------- */
async function renderClassDupControl() {
  const wrap = $("cdDupBody");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let plans = [];
  try {
    const all = await SyncEngine.materialize("stoff_plans");
    plans = all.filter((p) => String(p.classId) === String(detailClassId));
  } catch (e) { wrap.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
  if (!plans.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine gespeicherten Pläne für diese Klasse.</p>';
    return;
  }
  const targets = state.classes.filter((c) => !c.archivedAt && String(c.id) !== String(detailClassId));
  const planOpts = plans.map((p) =>
    `<option value="${p.id}">${esc(p.title)} (${esc(p.status)})</option>`).join("");
  const classOpts = targets.length
    ? targets.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.subject)})</option>`).join("")
    : "";
  const yearOpts = ['<option value="">(Schuljahr des Quellplans)</option>']
    .concat(state.schoolYears.map((y) => `<option value="${y.id}">${esc(y.label)}</option>`)).join("");
  if (!targets.length) {
    wrap.innerHTML = '<p class="muted small">Keine weitere Klasse vorhanden – lege zuerst eine Zielklasse an.</p>';
    return;
  }
  wrap.innerHTML = `
    <div class="dup-grid">
      <div><label class="small">Plan</label><select id="cdDupPlan">${planOpts}</select></div>
      <div><label class="small">Zielklasse</label><select id="cdDupClass">${classOpts}</select></div>
      <div><label class="small">Zielschuljahr</label><select id="cdDupYear">${yearOpts}</select></div>
      <div><label class="small">Modus</label><select id="cdDupMode">
        <option value="deterministisch">Zeiträume neu berechnen</option>
        <option value="kopie">1:1 kopieren</option>
        <option value="ki">KI-Anpassung</option>
      </select></div>
    </div>
    <div style="margin-top:10px;">
      <button class="btn small" id="cdDupBtn">Duplizieren</button>
    </div>`;
  $("cdDupBtn").onclick = async () => {
    const body = {
      targetClassId: Number($("cdDupClass").value),
      mode: $("cdDupMode").value,
    };
    const y = $("cdDupYear").value;
    if (y) body.targetSchoolYearId = Number(y);
    // Duplizieren (KI/Zeitraum-Neuberechnung) bleibt eine reine Online-REST-Aktion (analog
    // der KI-Gating-Vorentscheidung aus F5) — ein noch nicht synchronisierter Quellplan hat
    // nur eine lokale "loc_..."-id, Number() davon wäre NaN, daher hier eine klare Meldung
    // statt eines stillen Fehlschlags.
    const planId = Number($("cdDupPlan").value);
    if (!planId) { toast("Dieser Plan ist noch nicht synchronisiert – bitte online abwarten.", false); return; }
    $("cdDupBtn").disabled = true;
    try {
      await API.post(`/stoff-plans/${planId}/duplicate`, body);
      await refresh();
      toast("Plan dupliziert (als Entwurf für die Zielklasse).");
    } catch (e) { toast(e.message, false); }
    finally { const b = $("cdDupBtn"); if (b) b.disabled = false; }
  };
}

/* ---------- U19: Stoffpläne in der Klassen-Detailansicht ---------- */
let detailStoffPlans = [];
let openStoffPlanId = null;
let editingCdStoffPlanId = null;

async function renderClassDetailStoffPlans() {
  const wrap = $("cdStoffPlans");
  if (!wrap) return;
  try {
    const all = await SyncEngine.materialize("stoff_plans");
    detailStoffPlans = all.filter((p) => String(p.classId) === String(detailClassId));
  } catch (e) { detailStoffPlans = []; }
  if (!detailStoffPlans.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine gespeicherten Stoffverteilungspläne für diese Klasse.</p>';
    return;
  }
  wrap.innerHTML = detailStoffPlans.map((p) => {
    const badge = p.status === "aktiv"
      ? '<span class="badge ok">aktiv</span>' : '<span class="badge warn">Entwurf</span>';
    const meta = `${esc((p.blocks || []).length)} Blöcke · zuletzt geändert ${esc((p.updatedAt || "").slice(0, 10))}`;
    return `<div class="cd-stoff-row" data-cd-plan="${p.id}">
      <div class="cd-stoff-head">
        <div><strong>${esc(p.title)}</strong> ${badge}<br><span class="small muted">${meta}</span></div>
        <div class="cd-stoff-actions">
          <button class="btn small" data-cd-open="${p.id}">Öffnen</button>
          <button class="btn small secondary" data-cd-edit="${p.id}">Bearbeiten</button>
          <button class="btn small secondary" data-cd-pdf="${p.id}">Als PDF</button>
        </div>
      </div>
      <div class="cd-stoff-blocks" data-cd-blocks="${p.id}"></div>
      <div class="stoff-plan-editor" data-cd-editor="${p.id}"></div>
    </div>`;
  }).join("");
  // Nicht Number()-erzwingen: eine noch nicht synchronisierte "loc_..."-id würde zu NaN.
  wrap.querySelectorAll("[data-cd-open]").forEach((b) => b.onclick = () => toggleClassDetailStoffPlan(b.dataset.cdOpen));
  wrap.querySelectorAll("[data-cd-edit]").forEach((b) => b.onclick = () => toggleClassDetailStoffPlanEditor(b.dataset.cdEdit));
  wrap.querySelectorAll("[data-cd-pdf]").forEach((b) => b.onclick = () => downloadStoffPlanPdf(b.dataset.cdPdf));
  if (openStoffPlanId != null) showClassDetailStoffBlocks(openStoffPlanId);
  if (editingCdStoffPlanId != null) renderClassDetailStoffPlanEditor(editingCdStoffPlanId);
}

function toggleClassDetailStoffPlanEditor(id) {
  editingCdStoffPlanId = (String(editingCdStoffPlanId) === String(id)) ? null : id;
  renderClassDetailStoffPlans();
}

async function renderClassDetailStoffPlanEditor(id) {
  const box = document.querySelector(`[data-cd-editor="${id}"]`);
  if (!box) return;
  const p = detailStoffPlans.find((x) => String(x.id) === String(id));
  if (!p) { toast("Plan nicht gefunden.", false); return; }
  const rows = (p.blocks || []).map((b, i) =>
    `<tr data-i="${i}">
      <td>${esc(b.lbCode || "")}</td>
      <td><input type="text" data-f="title" value="${esc(b.title || "")}" /></td>
      <td><input type="number" data-f="ustd" min="0" value="${esc(b.ustd ?? "")}" style="width:70px;" /></td>
      <td><input type="text" readonly class="date-picker-input" data-f="startDate" value="${esc(b.startDate || "")}" placeholder="jjjj-mm-tt" /></td>
      <td><input type="text" readonly class="date-picker-input" data-f="endDate" value="${esc(b.endDate || "")}" placeholder="jjjj-mm-tt" /></td>
    </tr>
    <tr class="stoff-note-row">
      <td colspan="5" class="stoff-note-cell">
        <label class="small stoff-note-label">Hinweis</label>
        <textarea class="stoff-note-textarea" data-note-i="${i}" data-f="conflictNote" rows="2">${esc(b.conflictNote || "")}</textarea>
      </td>
    </tr>`).join("");
  box.innerHTML = `
    <div class="stoff-plan-edit-inner">
      <label class="small">Titel</label>
      <input type="text" data-edit-title value="${esc(p.title)}" style="width:100%; margin-bottom:8px;" />
      <div class="table-scroll"><table class="stoff-edit-table">
        <thead><tr><th>LB</th><th>Thema</th><th>Ustd.</th><th>Beginn</th><th>Ende</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="muted small">Keine Blöcke.</td></tr>'}</tbody>
      </table></div>
      <div style="margin-top:10px;">
        <button class="btn small" data-cd-sp-save="${id}">Änderungen speichern</button>
        <button class="btn small secondary" data-cd-sp-cancel="${id}">Schließen</button>
      </div>
    </div>`;
  box.querySelector(`[data-cd-sp-save="${id}"]`).onclick = () => saveClassDetailStoffPlanEdits(id);
  box.querySelector(`[data-cd-sp-cancel="${id}"]`).onclick = () => { editingCdStoffPlanId = null; renderClassDetailStoffPlans(); };
  box.querySelectorAll(".date-picker-input").forEach((inp) => inp.addEventListener("click", () => openDatePicker(inp)));
  box.querySelectorAll('[data-f="endDate"]').forEach((inp) => inp.addEventListener("change", (e) => {
    const tr = e.target.closest("tr[data-i]");
    if (tr) cascadeStoffPlanDates(box, Number(tr.dataset.i));
  }));
}

async function saveClassDetailStoffPlanEdits(id) {
  const box = document.querySelector(`[data-cd-editor="${id}"]`);
  if (!box) return;
  const title = box.querySelector("[data-edit-title]").value;
  const blocks = [...box.querySelectorAll("tbody tr[data-i]")].map((tr) => {
    const get = (f) => { const el = tr.querySelector(`[data-f="${f}"]`); return el ? el.value : ""; };
    const noteEl = box.querySelector(`[data-note-i="${tr.dataset.i}"]`);
    return {
      lbCode: tr.children[0].textContent || null,
      title: get("title") || null,
      ustd: get("ustd") === "" ? null : Number(get("ustd")),
      startDate: get("startDate") || null,
      endDate: get("endDate") || null,
      conflictNote: (noteEl ? noteEl.value : "") || null,
    };
  });
  try {
    await SyncEngine.update("stoff_plans", id, { title, blocks });
    toast("Plan aktualisiert.");
    editingCdStoffPlanId = null;
    if (String(openStoffPlanId) === String(id)) await showClassDetailStoffBlocks(id);
    await renderClassDetailStoffPlans();
  } catch (e) { toast(e.message, false); }
}

async function toggleClassDetailStoffPlan(id) {
  openStoffPlanId = (String(openStoffPlanId) === String(id)) ? null : id;
  // andere geöffnete Blöcke einklappen
  document.querySelectorAll("#cdStoffPlans [data-cd-blocks]").forEach((el) => { el.innerHTML = ""; });
  if (openStoffPlanId != null) await showClassDetailStoffBlocks(openStoffPlanId);
}

async function showClassDetailStoffBlocks(id) {
  const box = document.querySelector(`#cdStoffPlans [data-cd-blocks="${id}"]`);
  if (!box) return;
  const p = detailStoffPlans.find((x) => String(x.id) === String(id));
  if (!p) { toast("Plan nicht gefunden.", false); return; }
  const blocks = p.blocks || [];
  if (!blocks.length) {
    box.innerHTML = '<p class="muted small">Keine Blöcke in diesem Plan.</p>';
    return;
  }
  const rows = blocks.map((b) => {
    const zeit = (b.startDate || b.endDate) ? `${esc(deDate(b.startDate) || "?")} – ${esc(deDate(b.endDate) || "?")}` : "—";
    const noteRow = b.conflictNote
      ? `<tr class="stoff-note-row"><td colspan="5" class="stoff-note-cell"><span class="stoff-note-label">Bemerkung:</span> ${esc(b.conflictNote)}</td></tr>`
      : "";
    return `<tr>
      <td>${esc(b.lbCode || "")}</td>
      <td>${esc(b.title || "")}</td>
      <td>${esc(b.ustd ?? "")}</td>
      <td>${esc(b.weeks ?? "—")}</td>
      <td>${zeit}</td>
    </tr>${noteRow}`;
  }).join("");
  box.innerHTML = `<div class="table-scroll"><table class="cd-stoff-table">
    <thead><tr><th>LB</th><th>Thema</th><th>Ustd.</th><th>Wochen</th><th>Zeitraum</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

function downloadStoffPlanPdf(id) {
  const a = document.createElement("a");
  a.href = `/api/stoff-plans/${id}/export?format=pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// Auch von der Stoffplan-View (web/stoffplan.js) genutzt – bleibt hier, weil die
// Klassen-Detail-Ansicht (renderClassDetailStoffPlanEditor oben) sie direkt braucht.
// Zieht ab fromIndex+1 die Start-/Enddaten der Folgeblöcke nach (Start = nächster Montag nach
// Vorgänger-Ende, Dauer des Folgeblocks bleibt erhalten). Bricht ab, sobald ein Folgeblock
// bereits passt (kein weiterer Effekt).
function cascadeStoffPlanDates(box, fromIndex) {
  const rows = [...box.querySelectorAll("tbody tr[data-i]")];
  for (let i = fromIndex; i < rows.length - 1; i++) {
    const curEnd = rows[i].querySelector('[data-f="endDate"]').value;
    if (!curEnd) break;
    const nextStartEl = rows[i + 1].querySelector('[data-f="startDate"]');
    const nextEndEl = rows[i + 1].querySelector('[data-f="endDate"]');
    const oldStart = nextStartEl.value;
    const newStart = nextMonday(curEnd);
    if (oldStart === newStart) break;
    if (oldStart && nextEndEl.value) {
      const deltaDays = Math.round((parseIso(newStart) - parseIso(oldStart)) / 86400000);
      const newEnd = new Date(parseIso(nextEndEl.value));
      newEnd.setDate(newEnd.getDate() + deltaDays);
      nextEndEl.value = isoDate(newEnd);
    }
    nextStartEl.value = newStart;
  }
}

let detailStudents = [];
// Offline-Sync (Rollout Tranche 2): materialize() liefert ALLE Schüler des Nutzers (wie die
// IndexedDB-Tabelle) — hier client-seitig nach Klasse filtern und wie der bisherige Backend-
// Endpunkt (ORDER BY sort_order, id) sortieren.
async function materializeStudentsForClass(cid) {
  const all = await SyncEngine.materialize("students");
  return all.filter((s) => s.classId === cid)
    .sort((a, b) => (a.sortOrder - b.sortOrder) || String(a.id).localeCompare(String(b.id)));
}
async function renderClassStudents() {
  const wrap = $("cdStudentList");
  if (!wrap) return;
  try {
    detailStudents = await materializeStudentsForClass(detailClassId);
  } catch (e) { toast(e.message, false); return; }
  // U18: Sitzplan-Dropdowns hängen an der Schülerliste – nach (Neu-)Laden aktualisieren.
  // Nur re-rendern, wenn das Sitzplan-Modul bereits geladen ist (kein Nachladen erzwingen).
  if (_seatPlanModuleInstance && _seatPlanModuleInstance.hasGrid()) _seatPlanModuleInstance.renderSeatGrid();
  wrap.innerHTML = "";
  if (!detailStudents.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine Schüler erfasst.</p>';
    return;
  }
  detailStudents.forEach((s, idx) => {
    const row = document.createElement("div");
    row.className = "cd-student-row";
    row.innerHTML =
      `<span class="cd-student-no">${idx + 1}.</span>` +
      `<input class="cd-student-input" value="${esc(s.name)}" data-student-name="${s.id}" />` +
      `<button class="btn small secondary" data-student-up="${s.id}" ${idx === 0 ? "disabled" : ""}>↑</button>` +
      `<button class="btn small secondary" data-student-down="${s.id}" ${idx === detailStudents.length - 1 ? "disabled" : ""}>↓</button>` +
      `<button class="btn small danger" data-student-del="${s.id}" aria-label="Schüler entfernen">✕</button>`;
    wrap.appendChild(row);
  });
  wrap.querySelectorAll("[data-student-name]").forEach((inp) => {
    inp.onchange = async () => {
      const name = inp.value.trim();
      if (!name) { renderClassStudents(); return; }
      try { await SyncEngine.update("students", inp.dataset.studentName, { name }); toast("Name gespeichert."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-student-del]").forEach((btn) => {
    btn.onclick = async () => {
      try { await SyncEngine.remove("students", btn.dataset.studentDel); await renderClassStudents(); toast("Schüler entfernt."); }
      catch (e) { toast(e.message, false); }
    };
  });
  // Opaque id (Zahl oder "loc_..." bei noch unsynced) — nicht per Number() erzwingen (siehe
  // Kinds-/Slots-Editor im Stundenplan).
  wrap.querySelectorAll("[data-student-up]").forEach((btn) =>
    (btn.onclick = () => moveStudent(btn.dataset.studentUp, -1)));
  wrap.querySelectorAll("[data-student-down]").forEach((btn) =>
    (btn.onclick = () => moveStudent(btn.dataset.studentDown, 1)));
}

async function moveStudent(sid, dir) {
  const idx = detailStudents.findIndex((s) => String(s.id) === String(sid));
  const other = idx + dir;
  if (idx < 0 || other < 0 || other >= detailStudents.length) return;
  const a = detailStudents[idx], b = detailStudents[other];
  try {
    await SyncEngine.update("students", a.id, { sortOrder: b.sortOrder });
    await SyncEngine.update("students", b.id, { sortOrder: a.sortOrder });
    await renderClassStudents();
  } catch (e) { toast(e.message, false); }
}

async function addStudent() {
  const name = $("cdStudentName").value.trim();
  if (!name) return;
  try {
    await SyncEngine.create("students", { classId: detailClassId, name });
    $("cdStudentName").value = "";
    await renderClassStudents(); toast("Schüler hinzugefügt.");
  } catch (e) { toast(e.message, false); }
}

async function addStudentsBulk() {
  const names = $("cdStudentBulk").value.split("\n").map((n) => n.trim()).filter(Boolean);
  if (!names.length) { toast("Keine Namen eingegeben.", false); return; }
  // Kein Bulk-Op im generischen Sync-Modell (eine Mutation = eine Entität) — einzeln anlegen,
  // wie es die Sync-Engine ohnehin für jeden Schüler tun würde.
  try {
    for (const name of names) await SyncEngine.create("students", { classId: detailClassId, name });
    $("cdStudentBulk").value = "";
    await renderClassStudents(); toast(`${names.length} Namen hinzugefügt.`);
  } catch (e) { toast(e.message, false); }
}

function showClassInPraesent() {
  praesent.mode = "jahresplan";
  praesent.classId = String(detailClassId);
  showView("praesentation");
  const sel = $("praesentClass");
  if (sel) sel.value = String(detailClassId);
  renderPraesentation();
}

/* ===================== U18: Sitzplan ===================== */
// Ausgelagert nach sitzplan.js (ES-Modul), per dynamischem import() erst beim ersten
// Öffnen einer Klassen-Detailseite nachgeladen (Machbarkeitsprobe app.js-Splitting).
// app.js selbst bleibt ein klassisches <script> — der Rest der Datei ist unverändert.
let _seatPlanModulePromise = null;
let _seatPlanModuleInstance = null;
function getSeatPlanModule() {
  if (!_seatPlanModulePromise) {
    _seatPlanModulePromise = import("./sitzplan.js").then((mod) => {
      _seatPlanModuleInstance = mod.createSeatPlanModule({
        $, esc, API, toast, SyncEngine,
        getDetailClassId: () => detailClassId,
        getDetailStudents: () => detailStudents,
      });
      return _seatPlanModuleInstance;
    });
  }
  return _seatPlanModulePromise;
}
/* =================== /U18: Sitzplan =================== */

// Filteroptionen für "Gespeicherte Stunden" (Klasse/Fach dynamisch aus vorhandenen Daten,
// Typ aus der festen Liste des Stundentyp-Selects) – aktuelle Auswahl bleibt beim Neu-Rendern erhalten.
function renderLessonFilterOptions() {
  const clsSel = $("lessonFilterClass");
  if (clsSel) {
    const current = clsSel.value;
    clsSel.innerHTML = '<option value="">Alle Klassen</option>' +
      state.classes.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.subject)})</option>`).join("");
    if (state.classes.some((c) => String(c.id) === current)) clsSel.value = current;
  }
  const subSel = $("lessonFilterSubject");
  if (subSel) {
    const current = subSel.value;
    const subjects = Array.from(new Set(state.lessons.map((l) => l.subject).filter(Boolean))).sort((a, b) => a.localeCompare(b, "de"));
    subSel.innerHTML = '<option value="">Alle Fächer</option>' + subjects.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    if (subjects.includes(current)) subSel.value = current;
  }
  const typeSel = $("lessonFilterType");
  if (typeSel && typeSel.options.length <= 1 && $("lessonType")) {
    typeSel.innerHTML = '<option value="">Alle Typen</option>' +
      Array.from($("lessonType").options).map((o) => `<option value="${esc(o.value)}">${esc(o.textContent)}</option>`).join("");
  }
}
function renderLessonTable() {
  const b = document.querySelector("#lessonTable tbody");
  b.innerHTML = "";
  const fClass = $("lessonFilterClass") ? $("lessonFilterClass").value : "";
  const fSubject = $("lessonFilterSubject") ? $("lessonFilterSubject").value : "";
  const fType = $("lessonFilterType") ? $("lessonFilterType").value : "";
  state.lessons
    .filter((l) => (!fClass || String(l.classId) === fClass) && (!fSubject || l.subject === fSubject) && (!fType || l.lessonType === fType))
    .forEach((l) => {
      const tr = document.createElement("tr");
      const werk = l.bibox && l.bibox.werk ? `${l.bibox.werk} ${l.bibox.seite || ""}` : "–";
      tr.innerHTML =
        `<td>${esc(l.title)}</td><td>${esc(l.subject)}</td><td>${esc(l.grade || "")}</td>` +
        `<td>${esc(l.lessonType || "")}</td><td>${esc(werk)}</td>`;
      tr.style.cursor = "pointer";
      tr.onclick = () => openLessonModal(l);
      b.appendChild(tr);
    });
}

function todayFallbackList(list, todayStr) {
  const todays = state.lessons.filter((l) => l.date === todayStr);
  if (!todays.length) {
    list.innerHTML = '<p class="small" style="color:#dcfce7;">Noch keine Stunden geplant.</p>';
    return;
  }
  todays.forEach((l) => {
    const complete = (l.phases || []).some((p) => p.teacherActivity || p.studentActivity);
    const badge = complete ? '<span class="badge ok">geplant</span>' : '<span class="badge warn">Phasen offen</span>';
    const div = document.createElement("div");
    div.className = "mini-item";
    div.innerHTML =
      `<span class="time">${esc(l.time || "–")}</span>` +
      `<span>${esc(l.subject)} – ${esc(l.grade || "?")}. Kl. – ${esc(l.title)}</span>${badge}`;
    div.onclick = () => openLessonModal(l);
    list.appendChild(div);
  });
}

// U29: zeigt den heutigen Ausschnitt des persönlichen Stundenplans (U27) mit laufender/nächsten Stunde;
// fällt auf die klassischen, für heute datierten Lessons zurück, wenn kein Stundenplan hinterlegt ist.
async function renderTodayList() {
  const list = $("todayLessonList");
  list.innerHTML = "";
  const todayStr = isoDate(new Date());
  const wd = new Date().getDay(); // 0=So … 6=Sa
  if (wd >= 1 && wd <= 5) {
    try {
      const d = new Date();
      d.setDate(d.getDate() - ((d.getDay() + 6) % 7));      // Montag der aktuellen Woche
      const data = await calTtFetch(isoDate(d));
      const day = data.days.find((dd) => dd.date === todayStr);
      if (day && day.items.length) {
        const now = String(new Date().getHours()).padStart(2, "0") + ":" + String(new Date().getMinutes()).padStart(2, "0");
        const lessonsToday = state.lessons.filter((l) => l.date === todayStr);
        day.items.forEach((it) => {
          const [start, end] = (it.timeRange || "").split("–");
          const isNow = start && end && now >= start && now < end;
          const isPast = end && now >= end;
          const match = lessonsToday.find((l) => l.classId === it.classId);
          const div = document.createElement("div");
          div.className = "mini-item";
          if (isPast) div.style.opacity = "0.55";
          const statusBadge = isNow ? '<span class="badge ok">jetzt</span>'
            : match ? '<span class="badge ok">geplant</span>' : '<span class="badge warn">nicht geplant</span>';
          div.innerHTML = `<span class="time">${esc(it.timeRange || "")}</span><span>${esc(it.title)}</span>${statusBadge}`;
          if (match) div.onclick = () => openLessonModal(match);
          list.appendChild(div);
        });
        return;
      }
    } catch (e) { /* kein Stundenplan hinterlegt oder Fehler → Fallback unten */ }
  }
  todayFallbackList(list, todayStr);
}

// Erinnerung im "Guten Tag!"-Panel, den Heftereintrag (was die SuS ins Heft geschrieben
// haben) nachzupflegen. Vor Stundenende: dezenter Hinweis "noch offen". Nach Stundenende
// bzw. für zurückliegende Tage: To-do "nachpflegen". Rein berechnet aus state.lessons –
// verschwindet automatisch, sobald das Feld gefüllt ist. Die persistente Spiegelung in
// "Aufgaben & To-dos" übernimmt reconcileHefterTodos().
function hefterLessonEnd(l) {
  if (!l.time || !/^\d{2}:\d{2}$/.test(l.time)) return null;
  const [h, m] = l.time.split(":").map(Number);
  const t = h * 60 + m + (l.durationMinutes || 45);
  if (t >= 24 * 60) return "23:59";   // Stunde reicht über Mitternacht: heute gilt sie als "noch nicht vorbei"
  return String(Math.floor(t / 60)).padStart(2, "0") + ":" + String(t % 60).padStart(2, "0");
}
// Status einer Stunde bzgl. Heftereintrag: null = nichts zu tun, "hinweis" = Stunde heute
// noch nicht vorbei, "todo" = Stunde vorbei / liegt zurück und Feld leer.
function hefterReminderStatus(l, todayStr, now) {
  if ((l.hefteintrag || "").trim()) return null;
  if (!l.date || l.date > todayStr) return null;
  if (l.date < todayStr) return "todo";
  const end = hefterLessonEnd(l);
  if (end && now >= end) return "todo";
  return "hinweis";
}
function renderHefterReminders() {
  const block = $("hefterReminderBlock");
  const list = $("hefterReminderList");
  if (!block || !list) return;
  const todayStr = isoDate(new Date());
  const now = String(new Date().getHours()).padStart(2, "0") + ":" + String(new Date().getMinutes()).padStart(2, "0");
  const items = state.lessons
    .map((l) => ({ l, status: hefterReminderStatus(l, todayStr, now) }))
    .filter((x) => x.status)
    .sort((a, b) => (a.l.date + (a.l.time || "")).localeCompare(b.l.date + (b.l.time || "")));
  list.innerHTML = "";
  if (!items.length) { block.classList.add("hidden"); return; }
  block.classList.remove("hidden");
  items.forEach(({ l, status }) => {
    const div = document.createElement("div");
    div.className = "mini-item";
    const when = l.date === todayStr ? (l.time || "heute") : deDate(l.date);
    const badge = status === "todo"
      ? '<span class="badge warn">nachpflegen</span>'
      : '<span class="badge">noch offen</span>';
    div.innerHTML =
      `<span class="time">${esc(when)}</span>` +
      `<span>Heftereintrag: ${esc(l.title || "Stunde")}</span>${badge}`;
    div.onclick = () => openLessonModal(l);
    list.appendChild(div);
  });
}

// Spiegelt den "nachpflegen"-Zustand (Stunde vorbei, Heftereintrag leer) in echte, abhakbare
// To-dos in "Aufgaben & To-dos". Ein Hefter-To-do = system-To-do mit hefterLessonId. Anlegen
// nur bei Status "todo"; automatisch archivieren, sobald das Feld gefüllt ist (Status ≠ "todo").
// Dedup gegen ALLE To-dos inkl. archivierte: ein einmal weggeklickter Hefter-To-do kommt nicht
// wieder. Läuft aus renderAll heraus (fire-and-forget), schreibt nur bei echter Differenz.
let _hefterReconcileBusy = false;
async function reconcileHefterTodos() {
  if (_hefterReconcileBusy || !state.lessons) return;
  _hefterReconcileBusy = true;
  try {
    const todayStr = isoDate(new Date());
    const now = String(new Date().getHours()).padStart(2, "0") + ":" + String(new Date().getMinutes()).padStart(2, "0");
    const allTodos = await SyncEngine.materialize("todos");
    const todoByLesson = new Map();
    allTodos.forEach((t) => { if (t.hefterLessonId != null) todoByLesson.set(t.hefterLessonId, t); });
    let changed = false;
    for (const l of state.lessons) {
      if (hefterReminderStatus(l, todayStr, now) !== "todo" || todoByLesson.has(l.id)) continue;
      await SyncEngine.create("todos", {
        text: `Heftereintrag nachpflegen: ${l.title || "Stunde"} (${deDate(l.date)})`,
        source: "system",
        hefterLessonId: l.id,
      });
      changed = true;
    }
    for (const t of allTodos) {
      if (t.hefterLessonId == null || t.archivedAt != null) continue;
      const l = state.lessons.find((x) => x.id === t.hefterLessonId);
      if (!l || hefterReminderStatus(l, todayStr, now) !== "todo") {
        try { await API.post("/todos/" + t.id + "/archive"); changed = true; } catch (e) { /* offline */ }
      }
    }
    if (changed) await refresh();
  } catch (e) { /* offline / Sync noch nicht bereit — beim nächsten renderAll erneut */ }
  finally { _hefterReconcileBusy = false; }
}

const WEEKDAY_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const WEEKDAY_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
function weekdayOf(dateStr) { return (new Date(dateStr + "T00:00:00").getDay() + 6) % 7; }

// Rendert eine "Woche im Blick"-Liste gruppiert nach Wochentag (Tagesüberschrift statt
// Wiederholung pro Zeile) statt einer Karte pro Eintrag – hält die Liste bei vielen
// Terminen kompakt. `getWeekday` liefert den Index (0=Mo…6=So), `toRow` die Zeilendaten.
function renderDayGroups(container, items, getWeekday, toRow) {
  container.innerHTML = "";
  const byDay = new Map();
  items.forEach((item) => {
    const wd = getWeekday(item);
    if (!byDay.has(wd)) byDay.set(wd, []);
    byDay.get(wd).push(item);
  });
  [...byDay.keys()].sort((a, b) => a - b).forEach((wd) => {
    const group = document.createElement("div");
    group.className = "day-group";
    const heading = document.createElement("div");
    heading.className = "day-heading";
    heading.textContent = WEEKDAY_LONG[wd];
    const rows = document.createElement("div");
    rows.className = "day-rows";
    byDay.get(wd).forEach((item) => {
      const { time, title, badgeClass, badgeLabel, onClick } = toRow(item);
      const row = document.createElement("div");
      row.className = "day-row";
      row.innerHTML =
        `<span class="row-time">${esc(time)}</span>` +
        `<span class="row-title">${esc(title)}</span>` +
        `<span class="badge ${badgeClass}">${esc(badgeLabel)}</span>`;
      row.onclick = onClick;
      rows.appendChild(row);
    });
    group.append(heading, rows);
    container.appendChild(group);
  });
}

// „Woche im Blick": ungeplante Stunden (Stundenplan-Slot mit Klasse ohne passende Unterrichts-
// planung an dem Tag, Ferien/Feiertage ausgenommen) + alle Kalendertermine dieser Woche
// (Kalendereinträge sind nie Unterrichtsstunden selbst – die laufen separat über die Lessons).
async function renderWeekOverview() {
  const unplannedEl = $("weekUnplannedList");
  const apptEl = $("weekAppointmentsList");
  if (!unplannedEl || !apptEl) return;

  const monday = new Date();
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  const mondayStr = isoDate(monday);
  const weekEnd = new Date(monday);
  weekEnd.setDate(weekEnd.getDate() + 6);
  const weekEndStr = isoDate(weekEnd);

  const vis = visibleClassIds();
  const todayStr = isoDate(new Date());
  const allAppts = state.calendar
    .filter((e) => {
      const end = e.endDate || e.entryDate;
      const cids = entryClassIds(e);
      return e.entryDate <= weekEndStr && end >= mondayStr && (cids.length === 0 || cids.some((cid) => vis.includes(cid)));
    })
    .sort((a, b) => (a.entryDate + (a.startTime || "")).localeCompare(b.entryDate + (b.startTime || "")));

  // Termine des heutigen Tages erscheinen nur im "Guten Tag!"-Panel (todayAppointmentsList),
  // nicht zusätzlich in der Wochenübersicht.
  const appts = allAppts.filter((e) => !(e.entryDate <= todayStr && (e.endDate || e.entryDate) >= todayStr));

  const apptRow = (e) => {
    const badgeClass = e.entryType === "lu" ? "bad" : e.entryType === "exam" ? "warn" : "ok";
    const badgeLabel = e.entryType === "lu" ? "LEK" : e.entryType === "exam" ? "Prüfung" : "Termin";
    return {
      time: e.startTime || "",
      title: e.title,
      badgeClass, badgeLabel,
      onClick: () => openCalendarEventModal(e.id),
    };
  };

  apptEl.innerHTML = "";
  if (!appts.length) {
    apptEl.innerHTML = '<p class="mini-empty">Keine Termine diese Woche.</p>';
  } else {
    renderDayGroups(apptEl, appts, (e) => weekdayOf(e.entryDate), apptRow);
  }

  const todayApptEl = $("todayAppointmentsList");
  if (todayApptEl) {
    const todayAppts = allAppts.filter((e) => e.entryDate <= todayStr && (e.endDate || e.entryDate) >= todayStr);
    todayApptEl.innerHTML = "";
    if (!todayAppts.length) {
      todayApptEl.innerHTML = '<p class="mini-empty" style="color:#dcfce7;">Keine Termine heute.</p>';
    } else {
      todayAppts.forEach((e) => {
        const { time, title, badgeClass, badgeLabel, onClick } = apptRow(e);
        const div = document.createElement("div");
        div.className = "mini-item";
        div.innerHTML = `<span class="time">${esc(time)}</span><span>${esc(title)}</span><span class="badge ${badgeClass}">${esc(badgeLabel)}</span>`;
        div.onclick = onClick;
        todayApptEl.appendChild(div);
      });
    }
  }

  unplannedEl.innerHTML = '<p class="mini-empty">Lade …</p>';
  try {
    const data = await calTtFetch(mondayStr);
    const unplanned = [];
    (data.days || []).forEach((day) => {
      if (day.date === todayStr) return;     // Heute steht bereits im "Guten Tag!"-Panel
      if (schoolDateFor(day.date)) return;   // Ferien/Feiertag → an dem Tag ohnehin keine Stunde
      (day.items || []).forEach((it) => {
        if (it.classId == null) return;      // kein Klassen-Slot (z. B. Aufsicht) → nicht relevant
        const planned = state.lessons.some((l) => l.classId === it.classId && l.date === day.date);
        if (!planned) unplanned.push({ date: day.date, weekday: day.weekday, title: it.title, timeRange: it.timeRange });
      });
    });
    unplannedEl.innerHTML = "";
    if (!unplanned.length) {
      unplannedEl.innerHTML = '<p class="mini-empty">Keine ungeplanten Stunden diese Woche.</p>';
    } else {
      renderDayGroups(unplannedEl, unplanned, (u) => u.weekday, (u) => ({
        time: u.timeRange || "",
        title: u.title,
        badgeClass: "warn",
        badgeLabel: "planen",
        onClick: () => showView("stunde"),
      }));
    }
  } catch (e) {
    unplannedEl.innerHTML = '<p class="mini-empty">Stundenplan konnte nicht geladen werden.</p>';
  }
}

// Spruch des Tages: feste Liste in zwei Kategorien, deterministisch nach Datum gewählt
// (bleibt über den Tag stabil). "spruch" = reflektierte Unterrichtsweisheit, "motivation" =
// kurzer, energiegebender Impuls für den Tag.
const SAYING_CAT_LABELS = { spruch: "Spruch", motivation: "Motivation" };
const SAYINGS = [
  { cat: "spruch", text: "Guter Unterricht beginnt mit einer guten Frage." },
  { cat: "spruch", text: "Fehler sind Fußspuren auf dem Weg zum Verstehen." },
  { cat: "spruch", text: "Wer Fragen stellt, hat schon zugehört." },
  { cat: "spruch", text: "Ruhe im Klassenzimmer beginnt mit Ruhe am Pult." },
  { cat: "spruch", text: "Ein Lob zur rechten Zeit wirkt länger als jede Note." },
  { cat: "spruch", text: "Nicht jede Stunde muss perfekt sein – manche muss nur ehrlich sein." },
  { cat: "spruch", text: "Die beste Tafel ist die, die am Ende voller Ideen der Klasse ist." },
  { cat: "spruch", text: "Geduld ist das leiseste Unterrichtsprinzip – und das wirksamste." },
  { cat: "spruch", text: "Wer differenziert, sieht mehr als nur eine Klasse." },
  { cat: "spruch", text: "Ein Klassenraum ist immer auch ein Übungsraum für Vertrauen." },
  { cat: "spruch", text: "Die Pausenklingel unterbricht die Stunde, nicht das Lernen." },
  { cat: "spruch", text: "Kleine Rituale tragen große Klassen durch das Schuljahr." },
  { cat: "spruch", text: "Vorbereitung ist die Höflichkeit gegenüber der eigenen Klasse." },
  { cat: "spruch", text: "Wer zuhört, unterrichtet schon." },
  { cat: "spruch", text: "Jede Klasse hat ihr eigenes Tempo – finde es, bevor du planst." },
  { cat: "spruch", text: "Struktur gibt Freiheit, kein Korsett." },
  { cat: "spruch", text: "Ein gutes Beispiel erklärt mehr als drei gute Sätze." },
  { cat: "spruch", text: "Wer Fehler zulässt, macht Lernen erst möglich." },
  { cat: "spruch", text: "Der Stundenplan ist ein Gerüst, kein Gesetz." },
  { cat: "spruch", text: "Auch die leiseste Klasse hat etwas zu sagen." },
  { cat: "spruch", text: "Reflexion ist der Unterricht nach dem Unterricht." },
  { cat: "spruch", text: "Ein aufgeräumtes Pult macht noch keinen aufgeräumten Kopf – aber es hilft." },
  { cat: "spruch", text: "Wer differenziert plant, muss seltener improvisieren." },
  { cat: "spruch", text: "Die beste Disziplin ist eine gute Aufgabe." },
  { cat: "spruch", text: "Manchmal ist die wichtigste Frage: Wie geht es dir heute?" },
  { cat: "spruch", text: "Aus Kreide wird Kreidestaub, aus Mühe wird Können." },
  { cat: "spruch", text: "Ein Klassenzimmer wächst mit jedem Schuljahr ein Stück mit." },
  { cat: "spruch", text: "Wer plant, gewinnt Zeit für die Momente, die man nicht planen kann." },
  { cat: "spruch", text: "Verstehen braucht Zeit – auch wenn die Stunde nur 45 Minuten hat." },
  { cat: "spruch", text: "Der Unterricht endet mit der Stunde, das Lernen selten." },
  { cat: "motivation", text: "Motivation wächst dort, wo jemand zuerst geglaubt hat." },
  { cat: "motivation", text: "Interesse steckt an – auch das eigene." },
  { cat: "motivation", text: "Heute reicht ein guter Moment – der Rest kommt von allein." },
  { cat: "motivation", text: "Du musst nicht alles schaffen. Nur den nächsten Schritt." },
  { cat: "motivation", text: "Ein einziges Aha-Erlebnis rechtfertigt eine ganze Stunde." },
  { cat: "motivation", text: "Was du heute vorbereitest, trägt du morgen leichter." },
  { cat: "motivation", text: "Auch ein durchwachsener Tag zählt zur Erfahrung." },
  { cat: "motivation", text: "Kleine Fortschritte sind immer noch Fortschritte." },
  { cat: "motivation", text: "Du bist nicht allein im Klassenzimmer – die Klasse trägt mit." },
  { cat: "motivation", text: "Atme kurz durch. Dann weiter." },
  { cat: "motivation", text: "Dein Einsatz heute wirkt länger nach, als du siehst." },
  { cat: "motivation", text: "Es muss nicht glänzen – es muss nur weitergehen." },
  { cat: "motivation", text: "Du hast heute schon mehr geschafft, als auf deiner Liste steht." },
  { cat: "motivation", text: "Ein guter Tag beginnt mit einem kleinen Ziel." },
  { cat: "motivation", text: "Auch die ruhigen Erfolge zählen." },
];
function spruchIndexForToday() {
  const d = isoDate(new Date());
  let h = 0;
  for (let i = 0; i < d.length; i++) h = (h * 31 + d.charCodeAt(i)) >>> 0;
  return h % SAYINGS.length;
}
function renderSpruchDesTages() {
  const el = $("spruchText"), catEl = $("spruchCat"), card = $("spruchCard");
  const s = SAYINGS[spruchIndexForToday()];
  if (el) el.textContent = s.text;
  if (catEl) catEl.textContent = "· " + SAYING_CAT_LABELS[s.cat];
  if (card) card.style.backgroundImage =
    `linear-gradient(155deg, rgba(11,47,26,0.88), rgba(12,56,32,0.82)), url("${ssBackgroundForToday()}")`;
}

// Spruch-Kachel und Vollbild teilen sich am selben Tag dasselbe Hintergrundfoto.
const SS_BACKGROUNDS = [
  "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1920&q=80", // Wald, Sonnenlicht
  "https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?w=1920&q=80", // Berge, Nebel
  "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=1920&q=80", // Bergsee
  "https://images.unsplash.com/photo-1518495973542-4542c06a5843?w=1920&q=80", // Sonnenaufgang Feld
  "https://images.unsplash.com/photo-1447752875215-b2761acb3c5d?w=1920&q=80", // Wald von oben
  "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=1920&q=80", // Berge, weites Tal
  "https://images.unsplash.com/photo-1508739773434-c26b3d09e071?w=1920&q=80", // Milchstraße, Berge
  "https://images.unsplash.com/photo-1500534623283-312aade485b7?w=1920&q=80", // Herbstwald
];
function ssBackgroundForToday() {
  const d = isoDate(new Date());
  let h = 0;
  for (let i = 0; i < d.length; i++) h = (h * 17 + d.charCodeAt(i)) >>> 0;
  return SS_BACKGROUNDS[h % SS_BACKGROUNDS.length];
}
function openScreensaver() {
  const s = SAYINGS[spruchIndexForToday()];
  $("ssQuoteText").textContent = s.text;
  $("ssCat").textContent = SAYING_CAT_LABELS[s.cat];
  $("ssBg").style.backgroundImage = `url("${ssBackgroundForToday()}")`;
  $("screensaver").classList.remove("hidden");
  $("ssClose").focus();
}
function closeScreensaver() { $("screensaver").classList.add("hidden"); }

function renderReflectSelect() {
  $("reflectLesson").innerHTML = state.lessons
    .map((l) => `<option value="${l.id}">${esc(l.title)} (${esc(l.subject)} ${esc(l.grade || "")})</option>`)
    .join("");
}

function renderReflectTable() {
  const b = document.querySelector("#reflectTable tbody");
  b.innerHTML = "";
  state.reflections.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${esc(r.lessonTitle || "")}</td><td>${esc(r.ampelSummary || "")}</td><td>${esc(r.text || "")}</td>`;
    b.appendChild(tr);
  });
}

function renderOpenReflections() {
  const wrap = $("openReflectList");
  wrap.innerHTML = "";
  if (!state.open.length) { wrap.innerHTML = '<p class="muted small">Keine offenen Reflexionen</p>'; return; }
  state.open.forEach((o) => {
    const row = document.createElement("div");
    row.className = "open-reflect-row";
    row.innerHTML =
      `<span>${esc(o.subject)} Kl. ${esc(o.grade || "")} – ${esc(o.title)}</span>` +
      `<span><button class="btn small" data-reflect="${o.lessonId}">Reflektieren</button> ` +
      `<button class="btn small danger" data-skip="${o.lessonId}">Überspringen</button></span>`;
    wrap.appendChild(row);
  });
  wrap.querySelectorAll("[data-reflect]").forEach((btn) => {
    btn.onclick = () => {
      showView("reflexion");
      $("reflectLesson").value = btn.dataset.reflect;
      $("reflectLesson").scrollIntoView({ behavior: "smooth", block: "center" });
    };
  });
  wrap.querySelectorAll("[data-skip]").forEach((btn) => {
    btn.onclick = async () => {
      // reflection_skipped ist ein normales lessons-Feld (siehe Kommentar in
      // _apply_update_lesson) — SyncEngine.update statt der dedizierten REST-Route, damit
      // „Überspringen" grundsätzlich offline-fähig ist (o.lessonId stammt hier zwar aus dem
      // weiterhin Online-REST-Endpunkt /reflections/open, ist also immer eine echte id).
      try { await SyncEngine.update("lessons", btn.dataset.skip, { reflectionSkipped: true }); await refresh(); toast("Übersprungen."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

function renderTodos() {
  const list = $("todoList");
  list.innerHTML = "";
  if (!state.todos.length) { list.innerHTML = '<p class="muted small">Keine Aufgaben.</p>'; }
  state.todos.forEach((t) => {
    const div = document.createElement("div");
    div.className = "todo-item" + (t.done ? " done" : "");
    const isHefter = t.hefterLessonId != null;
    const srcClass = isHefter ? "hefter" : t.source;
    const srcLabel = isHefter ? "Hefter" : t.source;
    const textCell = isHefter
      ? `<a href="#" class="todo-hefter-link" data-hefter-lesson="${t.hefterLessonId}" style="flex:1">${esc(t.text)}</a>`
      : `<span style="flex:1">${esc(t.text)}</span>`;
    div.innerHTML =
      `<input type="checkbox" ${t.done ? "checked" : ""} data-todo="${t.id}"/>` +
      `<span class="todo-src ${srcClass}">${esc(srcLabel)}</span>` +
      textCell +
      `<button class="btn small danger" data-del-todo="${t.id}" aria-label="Aufgabe entfernen">✕</button>`;
    list.appendChild(div);
  });
  list.querySelectorAll("[data-todo]").forEach((cb) => {
    cb.onchange = async () => {
      try { await SyncEngine.update("todos", cb.dataset.todo, { done: cb.checked }); await refresh(); }
      catch (e) { toast(e.message, false); }
    };
  });
  list.querySelectorAll("[data-del-todo]").forEach((btn) => {
    btn.onclick = async () => {
      try { await API.post("/todos/" + btn.dataset.delTodo + "/archive"); await refresh(); toast("To-Do archiviert."); }
      catch (e) { toast(e.message, false); }
    };
  });
  list.querySelectorAll("[data-hefter-lesson]").forEach((a) => {
    a.onclick = (e) => {
      e.preventDefault();
      const l = state.lessons.find((x) => x.id === Number(a.dataset.hefterLesson));
      if (l) openLessonModal(l);
    };
  });
}

/* ---------- Auswahllisten / Filter / Schuljahre ---------- */
// Fach-Auswahl in der Unterrichtsplanung: feste Grundfächer + bereits verwendete freie
// Fächer (z. B. für Vertretungsstunden ohne eigenen Lehrplan) aus vorhandenen Stunden – so
// bleibt ein einmal angelegtes Fach dauerhaft im Dropdown, ohne eigene Fächerverwaltung.
const LESSON_SUBJECT_DEFAULTS = ["Deutsch", "WTH"];
function renderLessonSubjectOptions() {
  const sel = $("lessonSubject");
  if (!sel) return;
  const current = sel.value;
  const extra = Array.from(new Set(state.lessons.map((l) => l.subject).filter(Boolean)))
    .filter((s) => !LESSON_SUBJECT_DEFAULTS.includes(s))
    .sort((a, b) => a.localeCompare(b, "de"));
  const subjects = LESSON_SUBJECT_DEFAULTS.concat(extra);
  sel.innerHTML = subjects.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("")
    + '<option value="__new__">+ Neues Fach anlegen…</option>';
  if (subjects.includes(current)) sel.value = current;
}
function renderClassSelects() {
  const opts = state.classes.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.subject)})</option>`).join("");
  $("lessonClass").innerHTML = '<option value="">– keine –</option>' + opts;
  renderClassCheckboxes($("calEntryClasses"), []);
  // Jahres-Stoffverteilungsplan setzt ein einheitliches Fach voraus – "kein Fach"-Klassen
  // (z. B. stellvertretende Klassenleitung) werden hier ausgeblendet, Stunden bleiben über
  // die Unterrichtsplanung mit freier Fachwahl pro Stunde planbar.
  $("planClass").innerHTML = state.classes
    .filter((c) => c.subject !== "kein Fach")
    .map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.subject)})</option>`).join("");
  $("planYear").innerHTML = state.schoolYears.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join("");
  $("matYear").innerHTML = '<option value="">– kein Schuljahr –</option>' +
    state.schoolYears.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join("");
  // Nur neu laden, wenn die jeweiligen Module schon aktiv sind (kein Nachladen erzwingen) –
  // sonst würde jeder Datenrefresh sie eager laden, egal welche View gerade offen ist.
  if (_stoffplanModuleInstance) _stoffplanModuleInstance.loadPlanNotes();
  if (_sequenzplanModuleInstance) {
    _sequenzplanModuleInstance.renderSeqClassSelect();
    _sequenzplanModuleInstance.renderSeqBlockSelect();
  }
}

/* ---------- Materialbibliothek ---------- */
function renderMaterialList() {
  const wrap = $("materialList");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!state.materials.length) { wrap.innerHTML = '<p class="muted small">Noch keine Materialien.</p>'; return; }
  state.materials.forEach((m) => {
    const tags = [m.subject, m.grade ? "Kl. " + m.grade : null, m.lbLabel, m.status, m.tag]
      .filter(Boolean).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
    const link = m.externalLink ? ` · <a href="${esc(m.externalLink)}" target="_blank" rel="noopener">Link</a>` : "";
    const div = document.createElement("div");
    div.className = "file-chip";
    div.innerHTML =
      `<span><a href="/api/materials/${m.id}/download">${esc(m.filename)}</a>` +
      `${m.extracted ? ' <span class="badge ok">durchsuchbar</span>' : ""}${link}</span>` +
      `<span class="tag-row">${tags}<button class="btn small danger" data-del-mat="${m.id}" aria-label="Material entfernen">✕</button></span>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-del-mat]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.delMat;
      if (!confirm("Material archivieren? Es lässt sich im Archiv wiederherstellen.")) return;
      try {
        await API.post("/materials/" + id + "/archive");
        await refresh(); toast("Material archiviert.");
        setUndo("Material archiviert.", async () => {
          await API.post("/materials/" + id + "/restore");
          await refresh();
        });
      } catch (e) { toast(e.message, false); }
    };
  });
}

// U29: gespeicherte ASUV-Entwürfe als eigener "Ordner" der Materialbibliothek (virtuell, kein materials-Datensatz).
function renderAsuvLibrary() {
  const wrap = $("asuvLibraryList");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!state.asuvDrafts || !state.asuvDrafts.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine gespeicherten ASUV-Entwürfe.</p>';
    return;
  }
  state.asuvDrafts.forEach((a) => {
    const tags = [a.subject, a.grade ? "Kl. " + a.grade : null, a.className]
      .filter(Boolean).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
    const div = document.createElement("div");
    div.className = "file-chip";
    div.innerHTML =
      `<span>${esc(a.lessonTitle)}</span>` +
      `<span class="tag-row">${tags}` +
      `<a class="btn small secondary" href="/api/lessons/${a.lessonId}/asuv/export?format=pdf" target="_blank" rel="noopener">Anzeigen/Drucken</a>` +
      `<a class="btn small secondary" href="/api/lessons/${a.lessonId}/asuv/export?format=docx" target="_blank" rel="noopener">Word speichern</a>` +
      `<button class="btn small" data-asuv-edit="${a.lessonId}">Bearbeiten</button></span>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-asuv-edit]").forEach((b) => {
    b.onclick = () => {
      showView("asuv");
      $("asuvLesson").value = b.dataset.asuvEdit;
      loadAsuv(b.dataset.asuvEdit);
    };
  });
}

/* ---------- Archiv (U13, erweitert): Klassen | Planungen | To-Dos | Notizen | Material | Termine ---------- */
let archivTab = "klassen";

function setArchivTab(name) {
  archivTab = name;
  document.querySelectorAll(".archiv-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.archiv === name));
  ["klassen", "planungen", "todos", "notizen", "material", "kalender"].forEach((n) => {
    const panel = $("archiv" + n.charAt(0).toUpperCase() + n.slice(1));
    if (panel) panel.classList.toggle("hidden", n !== name);
  });
  renderArchivPanel(name);
}

async function renderArchivPanel(name) {
  if (name === "klassen") return renderArchivKlassen();
  if (name === "todos") return renderArchivTodos();
  if (name === "planungen") return renderArchivPlanungen();
  if (name === "notizen") return renderArchivNotizen();
  if (name === "material") return renderArchivMaterial();
  if (name === "kalender") return renderArchivKalender();
  const panel = $("archiv" + name.charAt(0).toUpperCase() + name.slice(1));
  if (panel) panel.innerHTML = '<p class="muted small">Noch keine archivierten Einträge.</p>';
}

async function renderArchivMaterial() {
  const wrap = $("archivMaterial");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let rows = [];
  try { rows = await API.get("/materials?archived=true"); }
  catch (e) { wrap.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
  wrap.innerHTML = "";
  if (!rows.length) { wrap.innerHTML = '<p class="muted small">Keine archivierten Materialien.</p>'; return; }
  rows.forEach((m) => {
    const meta = [m.subject, m.grade ? "Kl. " + m.grade : null, m.lbLabel].filter(Boolean).join(" · ");
    const div = document.createElement("div");
    div.className = "archiv-row";
    div.innerHTML =
      `<span class="archiv-main">${esc(m.filename)}</span>` +
      `<span class="muted small">${esc(meta)}</span>` +
      `<span class="archiv-actions">` +
      `<button class="btn small secondary" data-restore-mat="${m.id}">Wiederherstellen</button>` +
      `<button class="btn small danger" data-hard-mat="${m.id}">Endgültig löschen</button></span>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-restore-mat]").forEach((b) => {
    b.onclick = async () => {
      try { await API.post("/materials/" + b.dataset.restoreMat + "/restore"); await refresh(); renderArchivMaterial(); toast("Material wiederhergestellt."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-hard-mat]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Material endgültig löschen? Das kann nicht rückgängig gemacht werden.")) return;
      try { await API.del("/materials/" + b.dataset.hardMat); renderArchivMaterial(); toast("Material endgültig gelöscht."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

async function renderArchivKalender() {
  const wrap = $("archivKalender");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let rows = [];
  try {
    const all = await SyncEngine.materialize("calendar_entries");
    rows = all.filter((e) => e.archivedAt != null);
  } catch (e) { wrap.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
  wrap.innerHTML = "";
  if (!rows.length) { wrap.innerHTML = '<p class="muted small">Keine archivierten Termine.</p>'; return; }
  rows.forEach((e) => {
    const div = document.createElement("div");
    div.className = "archiv-row";
    div.innerHTML =
      `<span class="archiv-main">${esc(e.title)}</span>` +
      `<span class="muted small">${esc(e.entryDate)}</span>` +
      `<span class="archiv-actions">` +
      `<button class="btn small secondary" data-restore-cal="${e.id}">Wiederherstellen</button>` +
      `<button class="btn small danger" data-hard-cal="${e.id}">Endgültig löschen</button></span>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-restore-cal]").forEach((b) => {
    b.onclick = async () => {
      try { await API.post("/calendar/" + b.dataset.restoreCal + "/restore"); await refresh(); renderArchivKalender(); toast("Termin wiederhergestellt."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-hard-cal]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Termin endgültig löschen? Das kann nicht rückgängig gemacht werden.")) return;
      try { await API.del("/calendar/" + b.dataset.hardCal); renderArchivKalender(); toast("Termin endgültig gelöscht."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

/* ---------- U16: Archiv „Planungen" – Plan auf neues Schuljahr übernehmen ---------- */
async function renderArchivPlanungen() {
  const wrap = $("archivPlanungen");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let plans = [];
  try { plans = await SyncEngine.materialize("stoff_plans"); }
  catch (e) { wrap.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
  if (!plans.length) { wrap.innerHTML = '<p class="muted small">Noch keine gespeicherten Pläne.</p>'; return; }
  const clsName = (id) => {
    const c = state.classes.find((x) => String(x.id) === String(id));
    return c ? `${c.name} (${c.subject})` : "unbekannte Klasse";
  };
  const yearLbl = (id) => {
    const y = state.schoolYears.find((x) => String(x.id) === String(id));
    return y ? y.label : "–";
  };
  const yearOpts = state.schoolYears.map((y) => `<option value="${y.id}">${esc(y.label)}</option>`).join("");
  wrap.innerHTML = plans.map((p) => `
    <div class="archiv-row dup-plan-row" data-dup-plan="${p.id}">
      <span class="archiv-main">${esc(p.title)}</span>
      <span class="muted small">${esc(clsName(p.classId))} · ${esc(yearLbl(p.schoolYearId))} · ${esc((p.blocks || []).length)} Blöcke</span>
      <span class="archiv-actions dup-take">
        <select data-dup-year="${p.id}">${yearOpts || '<option value="">(kein Schuljahr)</option>'}</select>
        <select data-dup-mode="${p.id}">
          <option value="deterministisch">neu berechnen</option>
          <option value="ki">KI-Anpassung</option>
        </select>
        <button class="btn small" data-dup-take="${p.id}">Auf neues Schuljahr übernehmen</button>
      </span>
    </div>`).join("");
  wrap.querySelectorAll("[data-dup-take]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.dupTake;
      if (String(id).startsWith("loc_")) { toast("Dieser Plan ist noch nicht synchronisiert – bitte online abwarten.", false); return; }
      const p = plans.find((x) => String(x.id) === String(id));
      const yearSel = wrap.querySelector(`[data-dup-year="${id}"]`);
      const modeSel = wrap.querySelector(`[data-dup-mode="${id}"]`);
      const body = { targetClassId: p.classId, mode: modeSel.value };
      if (yearSel && yearSel.value) body.targetSchoolYearId = Number(yearSel.value);
      b.disabled = true;
      try {
        await API.post(`/stoff-plans/${id}/duplicate`, body);
        await refresh();
        renderArchivPlanungen();
        toast("Plan auf neues Schuljahr übernommen (als Entwurf).");
      } catch (e) { toast(e.message, false); b.disabled = false; }
    };
  });
}

async function renderArchivKlassen() {
  const wrap = $("archivKlassen");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let all = [];
  try { all = await API.get("/classes?includeArchived=true"); }
  catch (e) { wrap.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
  const rows = all.filter((c) => c.archivedAt);
  wrap.innerHTML = "";
  if (!rows.length) { wrap.innerHTML = '<p class="muted small">Keine archivierten Klassen.</p>'; return; }
  rows.forEach((c) => {
    const meta = [c.subject, c.grade ? "Kl. " + c.grade : null, c.track].filter(Boolean).join(" · ");
    const div = document.createElement("div");
    div.className = "archiv-row";
    div.innerHTML =
      `<span class="archiv-main">${esc(c.name)}</span>` +
      `<span class="muted small">${esc(meta)}</span>` +
      `<span class="archiv-actions">` +
      `<button class="btn small secondary" data-restore-class="${c.id}">Wiederherstellen</button>` +
      `<button class="btn small danger" data-hard-class="${c.id}">Endgültig löschen</button></span>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-restore-class]").forEach((b) => {
    b.onclick = async () => {
      try { await API.post("/classes/" + b.dataset.restoreClass + "/restore"); await refresh(); renderArchivKlassen(); toast("Klasse wiederhergestellt."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-hard-class]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Klasse endgültig löschen? Das kann nicht rückgängig gemacht werden.")) return;
      try { await API.del("/classes/" + b.dataset.hardClass + "?hard=true"); await refresh(); renderArchivKlassen(); toast("Klasse endgültig gelöscht."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

async function renderArchivTodos() {
  const wrap = $("archivTodos");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let rows = [];
  try { rows = await API.get("/todos?archived=true"); }
  catch (e) { wrap.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
  wrap.innerHTML = "";
  if (!rows.length) { wrap.innerHTML = '<p class="muted small">Keine archivierten To-Dos.</p>'; return; }
  rows.forEach((t) => {
    const div = document.createElement("div");
    div.className = "archiv-row";
    div.innerHTML =
      `<span class="archiv-main">${esc(t.text)}</span>` +
      `<span class="todo-src ${esc(t.source)}">${esc(t.source)}</span>` +
      `<span class="archiv-actions">` +
      `<button class="btn small secondary" data-restore-todo="${t.id}">Wiederherstellen</button>` +
      `<button class="btn small danger" data-hard-todo="${t.id}">Endgültig löschen</button></span>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-restore-todo]").forEach((b) => {
    b.onclick = async () => {
      try { await API.post("/todos/" + b.dataset.restoreTodo + "/restore"); await refresh(); renderArchivTodos(); toast("To-Do wiederhergestellt."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-hard-todo]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("To-Do endgültig löschen? Das kann nicht rückgängig gemacht werden.")) return;
      try { await API.del("/todos/" + b.dataset.hardTodo); await refresh(); renderArchivTodos(); toast("To-Do endgültig gelöscht."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

async function saveMaterial() {
  const f = $("matFile").files[0];
  if (!f) { toast("Bitte eine Datei wählen.", false); return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("subject", $("matSubject").value);
  fd.append("grade", $("matGrade").value);
  if ($("matYear").value) fd.append("schoolYearId", $("matYear").value);
  if ($("matLB").value.trim()) fd.append("lbLabel", $("matLB").value.trim());
  fd.append("status", $("matStatus").value);
  if ($("matTag").value.trim()) fd.append("tag", $("matTag").value.trim());
  if ($("matLink").value.trim()) fd.append("externalLink", $("matLink").value.trim());
  try {
    await API.upload("/materials/upload", fd);
    ["matFile", "matLB", "matTag", "matLink"].forEach((id) => ($(id).value = ""));
    await refresh(); toast("Material hochgeladen.");
  } catch (e) { toast(e.message, false); }
}

async function runSearch() {
  const q = $("matSearch").value.trim();
  const wrap = $("searchResults");
  wrap.innerHTML = "";
  if (!q) return;
  try {
    const hits = await API.get("/materials/search?q=" + encodeURIComponent(q));
    if (!hits.length) { wrap.innerHTML = '<p class="muted small">Keine Treffer.</p>'; return; }
    hits.forEach((h) => {
      const pages = "S. " + h.pageFrom + (h.pageTo && h.pageTo !== h.pageFrom ? "–" + h.pageTo : "");
      const div = document.createElement("div");
      div.className = "file-chip";
      div.innerHTML =
        `<span><a href="/api/materials/${h.materialId}/download">${esc(h.filename)}</a> ` +
        `<span class="muted small">${esc(pages)}</span><br><span class="small">${esc(h.snippet)}</span></span>`;
      wrap.appendChild(div);
    });
  } catch (e) { toast(e.message, false); }
}

// U31: Mehrfachauswahl Klassen für Kalendertermine (Chip-Checkboxen wie beim Kalender-Klassenfilter).
function renderClassCheckboxes(wrap, selectedIds) {
  if (!wrap) return;
  const sel = new Set((selectedIds || []).map(Number));
  wrap.innerHTML = state.classes.map((c) =>
    `<label class="class-toggle"><input type="checkbox" value="${c.id}"${sel.has(c.id) ? " checked" : ""}/> ${esc(c.name)} (${esc(c.subject)})</label>`
  ).join("") || '<span class="muted small">Keine Klassen angelegt.</span>';
}
function getCheckedClassIds(wrap) {
  return wrap ? [...wrap.querySelectorAll("input:checked")].map((i) => Number(i.value)) : [];
}

// Ab >5 Klassen wird die Chip-Liste hinter einem Summary-Button eingeklappt (sonst wächst sie
// unkontrolliert in die Höhe); der Aufklapp-Zustand bleibt über Re-Renders hinweg erhalten.
let classToggleExpanded = false;

function renderClassToggles() {
  const row = $("classToggleRow");
  const summaryBtn = $("classToggleSummaryBtn");
  if (!row) return;
  row.innerHTML = "";
  state.classes.forEach((c) => {
    const l = document.createElement("label");
    l.className = "class-toggle";
    l.innerHTML = `<input type="checkbox" data-id="${c.id}" ${c.visibleInCalendar !== false ? "checked" : ""}/> ${esc(c.name)} (${esc(c.subject)})`;
    row.appendChild(l);
  });
  row.querySelectorAll("input").forEach((inp) => {
    inp.onchange = async () => {
      try { await SyncEngine.update("classes", inp.dataset.id, { visibleInCalendar: inp.checked }); await refresh(); }
      catch (e) { toast(e.message, false); }
    };
  });

  if (!summaryBtn) return;
  const total = state.classes.length;
  if (total > 5) {
    const visible = state.classes.filter((c) => c.visibleInCalendar !== false).length;
    summaryBtn.hidden = false;
    summaryBtn.textContent = `${visible}/${total} Klassen sichtbar`;
    summaryBtn.setAttribute("aria-expanded", String(classToggleExpanded));
    row.classList.toggle("collapsed", !classToggleExpanded);
    summaryBtn.onclick = () => { classToggleExpanded = !classToggleExpanded; renderClassToggles(); };
  } else {
    summaryBtn.hidden = true;
    row.classList.remove("collapsed");
  }
}

// Effektiver Bildungsgang für die Anzeige (Deutsch 'gemischt' ab Kl. 7 → RS;
// Deutsch Kl. 5/6 hat keinen HS/RS-Split im Lehrplan → immer 'gemischt', s. resolve_track()).
function resolveTrack(subject, grade, track) {
  if (subject === "Deutsch" && grade != null && grade < 7) return "gemischt";
  if (subject === "Deutsch" && track === "gemischt" && (grade || 0) >= 7) return "RS";
  return track;
}

// Deutsch: LB1/LB2 nicht als eigene Blöcke; ihre Stunden proportional aufschlagen
// (Largest-Remainder, Gesamtsumme bleibt erhalten). WTH unverändert.
function effectiveBlocks(subject, lbs) {
  if (subject !== "Deutsch") return lbs.slice();
  const isLB12 = (e) => e.code === "LB1" || e.code === "LB2";
  const removed = lbs.filter(isLB12);
  const keep = lbs.filter((e) => !isLB12(e)).map((e) => Object.assign({}, e));
  if (!removed.length || !keep.length) return lbs.slice();
  const extra = removed.reduce((s, e) => s + (e.richtwertUstd || 0), 0);
  const base = keep.map((e) => e.richtwertUstd || 0);
  const baseSum = base.reduce((s, v) => s + v, 0);
  const totalTarget = baseSum + extra;
  const weights = baseSum > 0 ? base : keep.map(() => 1);
  const wsum = baseSum > 0 ? baseSum : keep.length;
  const floats = keep.map((_, i) => base[i] + extra * (weights[i] / wsum));
  const floors = floats.map((f) => Math.floor(f));
  let remainder = totalTarget - floors.reduce((s, v) => s + v, 0);
  const order = keep.map((_, i) => i).sort((a, b) => (floats[b] - floors[b]) - (floats[a] - floors[a]));
  for (let i = 0; i < remainder; i++) floors[order[i]] += 1;
  keep.forEach((e, i) => { e.richtwertUstd = floors[i]; });
  return keep;
}

// U22: Terminübersicht je Klasse — Lernbereiche als aufklappbare Datums-Abfolge.
// Klick auf einen LB klappt Zeitraum + Leistungsüberprüfungen auf; Klick auf ein Datum
// springt (via U15-Logik) in den Kalender und hebt den Tag kurz hervor.
async function renderTimeline() {
  const wrap = $("classTimeline");
  if (!wrap) return;
  wrap.innerHTML = "";
  let any = false;
  for (const c of state.classes) {
    if (c.visibleInCalendar === false || c.archivedAt) continue;
    let lbs = [];
    try { lbs = await getLernbereiche({ subject: c.subject, grade: c.grade, track: resolveTrack(c.subject, c.grade, c.track) }); } catch (e) { /* ignore */ }
    const eff = effectiveBlocks(c.subject, lbs);
    const planMap = activePlanBlocksByCode(c.id);
    const rows = eff.map((e) => {
      const pb = planMap[e.code];
      const dateLabel = pb && pb.startDate
        ? `${esc(pb.startDate)}${pb.endDate ? " – " + esc(pb.endDate) : ""}`
        : "kein Datum";
      return `<div class="cal-lb-row" data-lb-code="${esc(e.code)}" data-cls="${c.id}">` +
        `<span class="cal-lb-title">${esc(e.code)} · ${esc(e.title)}</span>` +
        `<span class="cal-lb-date">${dateLabel} <span class="cal-lb-caret">&#9656;</span></span></div>` +
        `<div class="cal-lb-detail hidden"></div>`;
    }).join("");
    const classDiv = document.createElement("div");
    classDiv.className = "cal-lb-class";
    classDiv.innerHTML = `<div class="cal-lb-class-head">${esc(c.name)} (${esc(c.subject)})</div>` +
      (rows || '<p class="muted small">Kein aktiver Stoffplan.</p>');
    wrap.appendChild(classDiv);
    any = true;
  }
  if (!any) { wrap.innerHTML = '<p class="muted small">Keine sichtbare Klasse. Klassen im Klassenfilter aktivieren.</p>'; return; }
  wrap.querySelectorAll(".cal-lb-row").forEach((row) => { row.onclick = () => toggleLbDetail(row); });
}

// U22: Detailbereich eines LB auf-/zuklappen und beim ersten Öffnen befüllen.
function toggleLbDetail(row) {
  const detail = row.nextElementSibling;
  if (!detail || !detail.classList.contains("cal-lb-detail")) return;
  const caret = row.querySelector(".cal-lb-caret");
  const nowHidden = detail.classList.toggle("hidden");
  if (caret) caret.classList.toggle("open", !nowHidden);
  if (nowHidden || detail.dataset.filled === "1") return;
  const code = row.dataset.lbCode, cid = Number(row.dataset.cls);
  const pb = activePlanBlocksByCode(cid)[code];
  let html;
  if (pb && pb.startDate) {
    const end = pb.endDate || pb.startDate;
    html = `<div><span class="muted small">Zeitraum:</span> ` +
      `<span class="date-chip" data-jump="${esc(pb.startDate)}">${esc(pb.startDate)} – ${esc(end)}</span></div>`;
    const lues = state.calendar.filter((e) =>
      entryClassIds(e).includes(cid) && (e.entryType === "lu" || e.entryType === "exam") &&
      (e.endDate || e.entryDate) >= pb.startDate && e.entryDate <= end);
    html += lues.length
      ? `<div style="margin-top:6px;"><span class="muted small">Leistungsüberprüfungen:</span> ` +
          lues.map((e) => `<span class="date-chip lue" data-jump="${esc(e.entryDate)}">${esc(e.entryDate)} · ${esc(e.title)}</span>`).join("") + `</div>`
      : `<div style="margin-top:6px;"><span class="muted small">Keine Leistungsüberprüfung in diesem Zeitraum.</span></div>`;
  } else {
    html = `<span class="muted small">Für diesen Lernbereich ist noch kein Datum geplant (im Stoffverteilungsplan festlegen).</span>`;
  }
  detail.innerHTML = html;
  detail.dataset.filled = "1";
  detail.querySelectorAll("[data-jump]").forEach((el) => {
    el.onclick = (ev) => { ev.stopPropagation(); jumpCalendarToDate(el.dataset.jump); };
  });
}

// U22: Termin-Popover öffnen (optional mit vorbefülltem Datum) bzw. schließen.
function openCalEntryPanel(dateStr) {
  const panel = $("calEntryPanel");
  if (!panel) return;
  panel.classList.remove("hidden");
  if (dateStr && $("calEntryDate")) $("calEntryDate").value = dateStr;
  panel.scrollIntoView({ behavior: "smooth", block: "center" });
  if ($("calEntryTitle")) $("calEntryTitle").focus();
  fillCalEntrySlotSelect();
}

// Stunden-Auswahl im "Neuer Termin"-Panel: aus den Klingelzeiten befüllen (lazy geladen, gecacht).
async function fillCalEntrySlotSelect() {
  const sel = $("calEntrySlot");
  if (!sel) return;
  if (!lessonSlotsCache) {
    try { lessonSlotsCache = (await API.get("/stundenplan/slots")).filter((s) => s.slotType === "lesson"); }
    catch (e) { lessonSlotsCache = []; }
  }
  sel.innerHTML = '<option value="">– manuell –</option>' +
    lessonSlotsCache.map((s) => `<option value="${s.id}" data-start="${esc(s.startTime)}" data-end="${esc(s.endTime)}">${esc(s.label)} · ${esc(s.startTime)}–${esc(s.endTime)}</option>`).join("");
}
function closeCalEntryPanel() { const p = $("calEntryPanel"); if (p) p.classList.add("hidden"); }

// Stunden-Auswahl in der Unterrichtsplanung (wie im "Neuer Termin"-Panel): Auswahl einer
// Stunde aus den Klingelzeiten füllt die Uhrzeit; "– manuell –" lässt sie frei editierbar.
async function fillLessonSlotSelect() {
  const sel = $("lessonSlot");
  if (!sel) return;
  if (!lessonSlotsCache) {
    try { lessonSlotsCache = (await API.get("/stundenplan/slots")).filter((s) => s.slotType === "lesson"); }
    catch (e) { lessonSlotsCache = []; }
  }
  const current = sel.value;
  sel.innerHTML = '<option value="">– manuell –</option>' +
    lessonSlotsCache.map((s) => `<option value="${s.id}" data-start="${esc(s.startTime)}">${esc(s.label)} · ${esc(s.startTime)}–${esc(s.endTime)}</option>`).join("");
  sel.value = current;
}

// U15: lbCode → Block-Objekt des aktiven Stoffplans einer Klasse (leeres Objekt ohne Plan).
function activePlanBlocksByCode(classId) {
  const ap = state.activePlans[classId];
  const map = {};
  if (ap) ap.blocks.forEach((b) => { if (b.lbCode) map[b.lbCode] = b; });
  return map;
}

function renderSchoolYears() {
  const wrap = $("schoolYearList");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!state.schoolYears.length) { wrap.innerHTML = '<p class="muted small">Noch kein Schuljahr angelegt.</p>'; return; }
  state.schoolYears.forEach((s) => {
    const div = document.createElement("div");
    div.className = "file-chip";
    div.innerHTML = `<span>${esc(s.label)} <span class="muted small">(${esc(s.startDate)} – ${esc(s.endDate)})</span></span>` +
      `<button class="btn small secondary" data-refresh-sy="${s.id}">Ferien aktualisieren</button>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-refresh-sy]").forEach((b) => {
    b.onclick = async () => {
      try { await API.post("/school-years/" + b.dataset.refreshSy + "/refresh-dates"); await refresh(); toast("Ferien/Feiertage aktualisiert."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

/* ---------- Kalender ---------- */
function isoDate(d) {
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
// U15: "YYYY-MM-DD" → lokales Date (ohne Zeitzonen-Verschiebung).
function parseIso(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}
// "YYYY-MM-DD" → deutsches Anzeigeformat "TT.MM.JJJJ".
function deDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "";
}

/* ---------- U28: Stoffplan-Datepicker mit grau hinterlegten Ferien ---------- */
// Nächster Montag ECHT NACH dateStr (fällt dateStr selbst auf einen Montag, wird eine Woche weitergesprungen).
function nextMonday(dateStr) {
  const d = parseIso(dateStr);
  if (!d) return null;
  const day = d.getDay(); // 0=So … 6=Sa
  let add = (8 - day) % 7;
  if (add === 0) add = 7;
  d.setDate(d.getDate() + add);
  return isoDate(d);
}

let _datePickerEl = null;
function closeDatePicker() {
  if (_datePickerEl) { _datePickerEl.remove(); _datePickerEl = null; }
  document.removeEventListener("mousedown", _datePickerOutsideHandler, true);
}
function _datePickerOutsideHandler(e) {
  if (_datePickerEl && !_datePickerEl.contains(e.target)) closeDatePicker();
}
// Öffnet ein kleines Monats-Popover unter inputEl; Ferien/Feiertage grau/gelb hinterlegt (wie im Kalender).
function openDatePicker(inputEl) {
  closeDatePicker();
  const base = parseIso(inputEl.value) || new Date();
  let viewYear = base.getFullYear(), viewMonth = base.getMonth();
  const pop = document.createElement("div");
  pop.className = "date-picker-popover";
  document.body.appendChild(pop);
  _datePickerEl = pop;
  const rect = inputEl.getBoundingClientRect();
  pop.style.position = "absolute";
  pop.style.top = `${window.scrollY + rect.bottom + 4}px`;
  pop.style.left = `${window.scrollX + rect.left}px`;

  function render() {
    const first = new Date(viewYear, viewMonth, 1);
    const startOffset = (first.getDay() + 6) % 7; // Woche beginnt Montag
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const monthLabel = first.toLocaleDateString("de-DE", { month: "long", year: "numeric" });
    let cells = "";
    for (let i = 0; i < startOffset; i++) cells += `<div class="dp-cell dp-empty"></div>`;
    for (let day = 1; day <= daysInMonth; day++) {
      const d = new Date(viewYear, viewMonth, day);
      const dStr = isoDate(d);
      const sd = schoolDateFor(dStr);
      const isSel = dStr === inputEl.value;
      let style = "";
      if (sd) style = `style="background:${cssVar(sd.kind === "feiertag" ? "--cal-holiday" : "--cal-vacation", sd.kind === "feiertag" ? "#fde68a" : "#e5e7eb")};"`;
      cells += `<div class="dp-cell${isSel ? " dp-selected" : ""}" data-date="${dStr}" ${style} title="${sd ? esc(sd.name) : ""}">${day}</div>`;
    }
    pop.innerHTML = `
      <div class="dp-header">
        <button type="button" class="dp-nav" data-nav="-1">‹</button>
        <span class="dp-month-label">${esc(monthLabel)}</span>
        <button type="button" class="dp-nav" data-nav="1">›</button>
      </div>
      <div class="dp-grid dp-weekdays">${["Mo","Di","Mi","Do","Fr","Sa","So"].map((d) => `<div class="dp-cell dp-wd">${d}</div>`).join("")}</div>
      <div class="dp-grid">${cells}</div>`;
    pop.querySelector('[data-nav="-1"]').onclick = () => { viewMonth--; if (viewMonth < 0) { viewMonth = 11; viewYear--; } render(); };
    pop.querySelector('[data-nav="1"]').onclick = () => { viewMonth++; if (viewMonth > 11) { viewMonth = 0; viewYear++; } render(); };
    pop.querySelectorAll(".dp-cell[data-date]").forEach((c) => c.onclick = () => {
      inputEl.value = c.dataset.date;
      inputEl.dispatchEvent(new Event("change", { bubbles: true }));
      closeDatePicker();
    });
  }
  render();
  setTimeout(() => document.addEventListener("mousedown", _datePickerOutsideHandler, true), 0);
}

/* ---------- U27c: blasse Stundenplan-Ebene im Wochen-Kalender ----------
   Rein additive, abschaltbare Kalender-Ebene (nur Wochen-Modus). Die A/B-Woche
   liefert der Server FERTIG (weekType) — NIE clientseitig aus der KW nachrechnen.
   Alle Top-Level-Namen mit Präfix calTt (U27b belegt tt* im selben Scope). */
const CAL_TT_KEY = "ldb_cal_tt_layer";
let calTtOn = true;                                      // Default: an
try { calTtOn = localStorage.getItem(CAL_TT_KEY) !== "0"; } catch (e) { /* Storage evtl. blockiert */ }
let calTtAvailable = false;                              // erst nach erfolgreichem Fetch (404-Degradation)
let calTtGen = 0;                                        // Render-Generation gegen veraltete Async-Anwendung
const calTtCache = new Map();                            // mondayStr → { data, time } | { promise, time }

// Filter „Nur Stundenplan“: blendet reguläre Termine + Stoffplan-Streifen aus (Monat + Woche),
// zeigt ausschließlich die Stundenplan-Ebene. Persistiert wie calTtOn.
const CAL_ONLY_TT_KEY = "ldb_cal_only_tt";
let calOnlyTt = false;
try { calOnlyTt = localStorage.getItem(CAL_ONLY_TT_KEY) === "1"; } catch (e) { /* Storage evtl. blockiert */ }

// Nur Hex-Farben zulassen → keine CSS-Injection über das style-Attribut; sonst neutraler Fallback.
function calTtSafeColor(c) {
  return (typeof c === "string" && /^#[0-9a-fA-F]{3,8}$/.test(c)) ? c : "#94a3b8";
}
// Lesbare Schriftfarbe (weiß/dunkel) für eine beliebige Kategorie-Hintergrundfarbe (WCAG-Näherung per Luminanz).
function readableTextColor(hex) {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const r = parseInt(full.slice(0, 2), 16) / 255, g = parseInt(full.slice(2, 4), 16) / 255, b = parseInt(full.slice(4, 6), 16) / 255;
  const lin = (v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return L > 0.55 ? "#14261a" : "#ffffff";
}
// Resolved-Woche holen: Cache je Montag (TTL 5 Min), In-Flight-Dedupe über gespeicherte Promise.
async function calTtFetch(mondayStr) {
  const now = Date.now();
  const hit = calTtCache.get(mondayStr);
  if (hit) {
    if (hit.promise) return hit.promise;                 // läuft schon → dedupe
    if (now - hit.time < 300000) return hit.data;        // frisch → aus Cache
  }
  const promise = API.get("/stundenplan/resolved?start=" + encodeURIComponent(mondayStr));
  calTtCache.set(mondayStr, { promise, time: now });
  try {
    const data = await promise;
    calTtCache.set(mondayStr, { data, time: Date.now() });
    return data;
  } catch (e) {
    calTtCache.delete(mondayStr);                        // Fehler nicht cachen (Retry erlauben)
    throw e;
  }
}
// Blasse Chips (Farbpunkt + zarte Tönung + Titel) in die Mo–Fr-Kacheln injizieren — nach .cal-daynum.
// U27d: zusätzlich pro Wochentag ein Toggle-Chip, um den Tag als Tropentag (verkürzter
// Unterricht bei Hitze) zu markieren — unabhängig davon, ob Einträge vorhanden sind.
function calTtApplyToCells(data) {
  const grid = $("calGrid");
  if (!grid || !data || !Array.isArray(data.days)) return;
  data.days.forEach((day) => {
    if (!day || !day.date) return;
    const cell = grid.querySelector('.cal-cell[data-date="' + day.date + '"]');
    if (!cell) return;
    // Re-Anwendung (z. B. nach Tropentag-Toggle) räumt zuerst die vorherige Injektion weg —
    // sonst verdoppeln sich Toggle-Chip und Strip bei jedem erneuten calTtApplyToCells-Aufruf.
    cell.querySelectorAll(".cal-tt-daytoggle, .cal-tt-strip").forEach((el) => el.remove());
    const dayNum = cell.querySelector(".cal-daynum");

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "cal-tt-daytoggle" + (day.isTropentag ? " active" : "");
    toggle.textContent = "Tropenplan";
    toggle.title = day.isTropentag
      ? "Tropenplan für diesen Tag aufheben"
      : "Diesen Tag als Tropentag markieren (verkürzter Unterricht)";
    toggle.onclick = (ev) => { ev.stopPropagation(); calTtToggleTropentag(day.date, !day.isTropentag); };
    cell.insertBefore(toggle, dayNum ? dayNum.nextSibling : cell.firstChild);

    if (!Array.isArray(day.items) || !day.items.length) return;
    const strip = document.createElement("div");
    strip.className = "cal-tt-strip";
    strip.innerHTML = day.items.map((it, idx) => {
      const color = calTtSafeColor(it.color);            // nur Hex → im style-Attribut abgesichert
      const tip = [it.timeRange, it.subtitle].filter(Boolean).join(" · ");
      // U30: Vertretungen (source="override") sind einmalig und per Klick auf das „×" wieder entfernbar.
      const delBtn = it.source === "override"
        ? '<button type="button" class="cal-tt-chip-del" data-tt-override-del="' + it.entryId + '" ' +
          'title="Vertretung entfernen" aria-label="Vertretung entfernen">×</button>'
        : "";
      return '<span class="cal-tt-chip" data-tt-item="' + idx + '" style="--cal-tt-c:' + esc(color) + '" title="' + esc(tip) + '">' +
        '<span class="cal-tt-dot"></span>' +
        '<span class="cal-tt-title">' + esc(it.title) + '</span>' + delBtn + '</span>';
    }).join("");
    cell.insertBefore(strip, toggle.nextSibling);
    // U35: Klick auf eine Stunde des Stundenplans → geplante Stunde oder „Stunde jetzt planen".
    strip.querySelectorAll("[data-tt-item]").forEach((chip) => {
      chip.onclick = (ev) => {
        if (ev.target.closest("[data-tt-override-del]")) return;
        ev.stopPropagation();
        openTimetableSlotModal(day.date, day.items[Number(chip.dataset.ttItem)]);
      };
    });
    strip.querySelectorAll("[data-tt-override-del]").forEach((btn) => {
      btn.onclick = (ev) => { ev.stopPropagation(); calTtDeleteOverride(Number(btn.dataset.ttOverrideDel)); };
    });
  });
}
// U33: Filter „Nur Stundenplan“ in der Monatsansicht — die volle .cal-tt-strip-Ebene würde
// in den kleinen Monatskacheln überlaufen, daher hier dieselben dezenten Farbpunkte wie bei
// regulären Terminen (Fantastical-Stil), nur eben aus der Stundenplan-Ebene gespeist.
function calTtApplyMonthDots(data) {
  const grid = $("calGrid");
  if (!grid || !data || !Array.isArray(data.days)) return;
  data.days.forEach((day) => {
    if (!day || !day.date || !Array.isArray(day.items) || !day.items.length) return;
    const cell = grid.querySelector('.cal-cell[data-date="' + day.date + '"]');
    const dayNum = cell && cell.querySelector(".cal-daynum");
    if (!cell || !dayNum) return;
    const dots = document.createElement("div");
    dots.className = "cal-dots";
    dots.innerHTML = day.items.slice(0, 5).map((it) => {
      const color = calTtSafeColor(it.color);
      const tip = [it.timeRange, it.title].filter(Boolean).join(" ");
      return '<span class="cal-dot" style="background:' + color + '" title="' + esc(tip) + '"></span>';
    }).join("") + (day.items.length > 5 ? '<span class="cal-dot-more">+' + (day.items.length - 5) + '</span>' : "");
    cell.insertBefore(dots, dayNum.nextSibling);
  });
}
// Holt und wendet die Stundenplan-Ebene für mehrere Wochen an (Monatsraster: bis zu 6 Montage).
async function calOnlyTtRenderMonth(mondayStrs, gen) {
  for (const mondayStr of mondayStrs) {
    let data;
    try { data = await calTtFetch(mondayStr); } catch (e) { continue; }
    if (gen !== calTtGen || calMode !== "month" || !calOnlyTt) return;
    calTtApplyMonthDots(data);
  }
}
// U30: Vertretung aus der blassen Stundenplan-Ebene löschen (Cache invalidieren + Woche neu einspielen).
async function calTtDeleteOverride(overrideId) {
  if (!confirm("Diese Vertretung wirklich entfernen?")) return;
  try {
    await SyncEngine.remove("timetable_overrides", overrideId);
    calTtCache.clear();
    await renderTodayList();
    await renderWeekOverview();
    renderCalendar();
    toast("Vertretung entfernt.");
  } catch (e) { toast(e.message, false); }
}
// U27d: Tropentag umschalten (PUT + Cache invalidieren + Woche neu einspielen).
async function calTtToggleTropentag(dateStr, active) {
  try {
    await API.put("/stundenplan/tropentage/" + encodeURIComponent(dateStr), { active });
    const d = parseIso(dateStr);
    if (!d) return;
    const monday = new Date(d);
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    const mondayStr = isoDate(monday);
    calTtCache.delete(mondayStr);
    if (calMode === "week") await calTtRenderWeek(mondayStr, ++calTtGen);
    toast(active ? "Tropentag markiert – Zeiten in der Woche angepasst." : "Tropentag aufgehoben.");
  } catch (e) { toast(e.message, false); }
}
// Wochen-Render-Nachlauf: Verfügbarkeit ermitteln, Toggle/Badge pflegen, Chips einspielen.
async function calTtRenderWeek(mondayStr, gen) {
  let data;
  try {
    data = await calTtFetch(mondayStr);
  } catch (e) {
    if (e && e.status === 404) {                         // Route/Backend fehlt → sauber degradieren
      calTtAvailable = false;
      const tgl = $("calTtToggle"); if (tgl) tgl.classList.add("hidden");
      const bdg = $("calWeekBadge"); if (bdg) bdg.classList.add("hidden");
    }
    return;                                              // andere Fehler (offline) still schlucken
  }
  if (gen !== calTtGen || calMode !== "week") return;    // Render veraltet/Modus gewechselt → nichts anwenden
  calTtAvailable = true;
  const tgl = $("calTtToggle");
  // U33: Bei aktivem „Nur Stundenplan“-Filter ist die Ebene immer an — der Ein-/Aus-Toggle
  // wäre dann irreführend, deshalb ausblenden statt ihn separat deaktiviert anzuzeigen.
  if (tgl) { tgl.classList.toggle("hidden", calOnlyTt); tgl.classList.toggle("active", calTtOn); }
  const bdg = $("calWeekBadge");
  if (bdg) {
    const wt = data.weekType;
    if (wt === "A" || wt === "B") { bdg.textContent = wt + "-Woche"; bdg.classList.remove("hidden"); }
    else bdg.classList.add("hidden");
  }
  if (calTtOn || calOnlyTt) calTtApplyToCells(data);
}
/* ---------- U35: Klick auf eine Stunde der Stundenplan-Ebene ----------
   Ist für diesen Tag und diese Klasse bereits eine Stunde geplant, öffnet sich deren
   Detailansicht (mit „Stunde bearbeiten“); sonst ein kleines Fenster mit „Stunde jetzt
   planen“, das die Unterrichtsplanung mit Datum/Klasse/Zeit/Dauer vorbefüllt. */
function ttStartTime(item) {
  return String(item.timeRange || "").split("–")[0].trim().slice(0, 5);
}
function minutesOfTime(t) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(t || "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}
// Zuordnung Stundenplan-Stunde → geplante Stunde: gleiche Klasse am selben Tag, Uhrzeit
// nahe am Stundenbeginn (Toleranz 20 Min., da Stunden auch manuell erfasst werden).
// Stunden ohne Uhrzeit gelten als passend, solange keine bessere Übereinstimmung existiert.
function findLessonForTimetableItem(dStr, item) {
  if (item.classId == null) return null;
  const cands = state.lessons.filter((l) => l.date === dStr && l.classId === item.classId);
  if (!cands.length) return null;
  const start = minutesOfTime(ttStartTime(item));
  const near = start == null ? null : cands.find((l) => {
    const t = minutesOfTime(l.time);
    return t != null && Math.abs(t - start) <= 20;
  });
  return near || cands.find((l) => !l.time) || null;
}

function planLessonFromTimetableItem(dStr, item) {
  closeModal();
  showView("stunde");
  resetLessonEditState();
  clearLessonForm();
  const cls = item.classId != null ? state.classes.find((c) => c.id === item.classId) : null;
  if (cls) {
    $("lessonClass").value = String(cls.id);
    if (cls.subject && $("lessonSubject").querySelector(`option[value="${CSS.escape(cls.subject)}"]`)) {
      $("lessonSubject").value = cls.subject;
    }
    if (cls.grade != null) $("lessonGrade").value = String(cls.grade);
  }
  $("lessonDate").value = dStr;
  const start = ttStartTime(item);
  if (start) $("lessonTime").value = start;
  const slot = (lessonSlotsCache || []).find((s) => s.id === item.slotId);
  if (slot) $("lessonSlot").value = String(slot.id);
  $("lessonDuration").value = (item.spanSlots || 1) >= 2 ? "90" : "45";
  updateLessonLbOptions(null);
  updateLessonSeqOptions();
  updateSozialformMonotonyHint();
  validatePhaseTimes();
}

function openTimetableSlotModal(dStr, item) {
  const planned = findLessonForTimetableItem(dStr, item);
  if (planned) { openLessonModal(planned); return; }
  const d = parseIso(dStr);
  const dateLabel = d ? d.toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" }) : dStr;
  const cls = item.classId != null ? state.classes.find((c) => c.id === item.classId) : null;
  $("modalRoot").innerHTML =
    `<div class="modal-overlay" id="modalOverlay"><div class="modal-box">
      <button class="modal-close" id="modalCloseBtn">Schließen</button>
      <h2>${esc(item.title || "Stunde")}</h2>
      <p class="muted small">${esc(dateLabel)}${item.timeRange ? " – " + esc(item.timeRange) : ""}${item.slotLabel ? " – " + esc(item.slotLabel) : ""}</p>
      <div class="modal-section">
        <p class="small">Für diese Stunde laut Stundenplan ist noch keine Unterrichtsstunde geplant.</p>
        ${cls ? "" : '<p class="muted small">Dieser Eintrag ist keiner Klasse zugeordnet – Klasse in der Planung bitte selbst wählen.</p>'}
        <button class="btn" id="ttPlanNowBtn">Stunde jetzt planen</button>
      </div>
    </div></div>`;
  $("modalOverlay").onclick = (e) => { if (e.target.id === "modalOverlay") closeModal(); };
  $("modalCloseBtn").onclick = closeModal;
  $("ttPlanNowBtn").onclick = () => planLessonFromTimetableItem(dStr, item);
}

// U15: Kalender auf ein Datum springen lassen und den Tag kurz farblich hervorheben.
function jumpCalendarToDate(dStr) {
  const d = parseIso(dStr);
  if (!d) return;
  calCursor = d;
  calSelectedDate = dStr;
  renderCalendar();
  const grid = $("calGrid");
  if (grid) grid.scrollIntoView({ behavior: "smooth", block: "center" });
  requestAnimationFrame(() => {
    const cell = document.querySelector(`#calGrid .cal-cell[data-date="${dStr}"]`);
    if (!cell) return;
    cell.classList.add("cal-flash");
    setTimeout(() => cell.classList.remove("cal-flash"), 1500);
  });
}
function visibleClassIds() { return state.classes.filter((c) => c.visibleInCalendar !== false).map((c) => c.id); }
function catById(id) { return id == null ? null : state.calendarCategories.find((c) => c.id === id); }
// U31: Termine können mehreren Klassen zugeordnet sein (classIds); auto-generierte
// Stundentermine tragen weiterhin nur classId. Bei lessonId-Verknüpfung ist die Lesson die
// Single Source of Truth für die Klasse — classId zuerst, sonst könnte ein veralteter
// calendar_entry_classes-Eintrag (z. B. nach Klassenwechsel der Stunde) die falsche Klasse
// anzeigen, obwohl class_id längst aktuell ist.
function entryClassIds(e) {
  if (e.lessonId != null) return e.classId != null ? [e.classId] : [];
  return (e.classIds && e.classIds.length) ? e.classIds : (e.classId != null ? [e.classId] : []);
}
// Klassen-Kennzeichnung für Kalendertermine in Tages-/Wochenansicht: "(Name, Fach)",
// bei mehreren Klassen je Klasse durch "; " getrennt. Ohne zugeordnete Klasse leer.
function entryClassSuffix(e) {
  const ids = entryClassIds(e);
  if (!ids.length) return "";
  const labels = ids.map((cid) => {
    const c = state.classes.find((x) => x.id === cid);
    return c ? `${c.name}, ${c.subject}` : null;
  }).filter(Boolean);
  return labels.length ? ` (${labels.join("; ")})` : "";
}
function entriesForDate(dStr) {
  const vis = visibleClassIds();
  // Klassenlose Termine sind immer sichtbar; mehrtägige Termine erscheinen an jedem Tag
  // zwischen entryDate und endDate (inklusive).
  return state.calendar.filter((e) => {
    const end = e.endDate || e.entryDate;
    const inRange = e.entryDate <= dStr && dStr <= end;
    const cids = entryClassIds(e);
    return inRange && (cids.length === 0 || cids.some((cid) => vis.includes(cid)));
  });
}
function schoolDateFor(dStr) {
  return state.schoolDates.find((s) => s.startDate <= dStr && dStr <= s.endDate);
}
function renderCalendar() {
  const grid = $("calGrid");
  if (!grid) return;
  grid.innerHTML = "";
  grid.classList.toggle("with-kw", calMode === "month");
  const ttGen = ++calTtGen;  // U27c: jede Neurenderung entwertet noch laufende Stundenplan-Fetches
  if (calMode === "month") { const h = document.createElement("div"); h.className = "cal-head"; h.textContent = "KW"; grid.appendChild(h); }
  ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].forEach((d) => {
    const h = document.createElement("div"); h.className = "cal-head"; h.textContent = d; grid.appendChild(h);
  });
  const todayStr = isoDate(new Date());
  // U15: Segmente des aktiven Stoffplans (nur sichtbare Klassen) als Kalender-Ebene vorbereiten.
  const tlColors = timelineColors();
  const planSegs = [];
  visibleClassIds().forEach((cid) => {
    const ap = state.activePlans[cid];
    if (!ap) return;
    const cls = state.classes.find((c) => c.id === cid);
    ap.blocks.forEach((b, i) => {
      if (!b.startDate) return;
      const end = b.endDate || b.startDate;
      const tip = `${cls ? esc(cls.name) + ": " : ""}${esc(b.lbCode || "")} ${esc(b.title || "")} (${esc(b.startDate)}${b.endDate ? " – " + esc(b.endDate) : ""})`.trim();
      planSegs.push({ start: b.startDate, end, code: b.lbCode || "", color: tlColors[i % tlColors.length], tip });
    });
  });
  const entryDotColor = (e) => {
    const cat = catById(e.categoryId);
    if (cat) return calTtSafeColor(cat.color);
    return e.entryType === "lu" ? "var(--bad)" : e.entryType === "exam" ? "var(--orange)" : "var(--primary)";
  };
  const makeCell = (d, other, isMonth) => {
    const dStr = isoDate(d);
    const cell = document.createElement("div");
    cell.className = "cal-cell" + (other ? " otherMonth" : "") + (dStr === todayStr ? " today" : "");
    cell.dataset.date = dStr;
    const sd = schoolDateFor(dStr);
    if (sd) { cell.style.background = cssVar(sd.kind === "feiertag" ? "--cal-holiday" : "--cal-vacation", sd.kind === "feiertag" ? "#fde68a" : "#e5e7eb"); cell.title = sd.name; }
    // U33: Filter „Nur Stundenplan“ blendet Stoffplan-Streifen und reguläre Termine aus —
    // die Stundenplan-Ebene wird davon unabhängig weiter unten (calTt*) eingespielt.
    const strips = calOnlyTt ? [] : planSegs.filter((s) => s.start <= dStr && dStr <= s.end);
    const stripHtml = strips.length
      ? `<div class="cal-plan-strips">` + strips.map((s) =>
          `<span class="cal-plan-strip" style="background:${s.color}" title="${s.tip}">${esc(s.code)}</span>`).join("") + `</div>`
      : "";
    const entries = calOnlyTt ? [] : entriesForDate(dStr);
    // U28: Im Monatsraster nur dezente Farbpunkte (Fantastical-Stil) — die Tages-Agenda unten
    // zeigt Titel/Zeit im Klartext, damit die winzigen Kacheln nicht überladen wirken.
    const entriesHtml = isMonth
      ? (entries.length ? `<div class="cal-dots">` +
          entries.slice(0, 5).map((e) => {
            const tip = ((!e.allDay && e.startTime) ? e.startTime + " " : "") + e.title + (e.room ? ` (Zimmer ${e.room})` : "");
            return `<span class="cal-dot" style="background:${entryDotColor(e)}" title="${esc(tip)}"></span>`;
          }).join("") +
          (entries.length > 5 ? `<span class="cal-dot-more">+${entries.length - 5}</span>` : "") + `</div>`
          : "")
      : entries.map((e) => {
          const cat = catById(e.categoryId);
          const color = cat ? calTtSafeColor(cat.color) : null;
          const style = color ? ` style="background:${color};color:${readableTextColor(color)}"` : "";
          const time = (!e.allDay && e.startTime) ? esc(e.startTime) + " " : "";
          return `<div class="cal-entry ${esc(e.entryType)}" data-lesson="${e.lessonId == null ? "" : e.lessonId}" data-entry-id="${e.id}"${style}>${time}${esc(e.title)}${esc(entryClassSuffix(e))}</div>`;
        }).join("");
    cell.innerHTML = `<div class="cal-daynum">${d.getDate()}</div>` + stripHtml + entriesHtml;
    return cell;
  };
  let monthStartStr = null, monthEndStr = null;
  if (calMode === "month") {
    const y = calCursor.getFullYear(), m = calCursor.getMonth();
    $("calLabel").textContent = calCursor.toLocaleDateString("de-DE", { month: "long", year: "numeric" });
    const startOffset = (new Date(y, m, 1).getDay() + 6) % 7;
    const startDate = new Date(y, m, 1 - startOffset);
    const mondays = [];                                  // U33: je Rasterzeile ein Montag (Stundenplan-Ebene)
    for (let i = 0; i < 42; i++) {
      const d = new Date(startDate); d.setDate(startDate.getDate() + i);
      if (i % 7 === 0) {
        const kw = document.createElement("div"); kw.className = "cal-kw"; kw.textContent = isoWeek(d); grid.appendChild(kw);
        mondays.push(isoDate(d));
      }
      grid.appendChild(makeCell(d, d.getMonth() !== m, true));
    }
    // U27c: Stundenplan-Ebene ist Wochen-only → Toggle + KW-Badge im Monatsmodus verstecken.
    const bdg = $("calWeekBadge"); if (bdg) bdg.classList.add("hidden");
    const tgl = $("calTtToggle"); if (tgl) tgl.classList.add("hidden");
    // U33: „Nur Stundenplan“ gilt auch im Monat — Stundenplan-Ebene je Rasterzeile nachladen.
    if (calOnlyTt) calOnlyTtRenderMonth(mondays, ttGen);
    monthStartStr = isoDate(new Date(y, m, 1)); monthEndStr = isoDate(new Date(y, m + 1, 0));
  } else {
    const d0 = new Date(calCursor); d0.setDate(d0.getDate() - ((d0.getDay() + 6) % 7));
    const d6 = new Date(d0); d6.setDate(d0.getDate() + 6);
    const monthLabel = d0.getMonth() === d6.getMonth()
      ? d0.toLocaleDateString("de-DE", { month: "long", year: "numeric" })
      : d0.toLocaleDateString("de-DE", { month: "short" }) + " / " + d6.toLocaleDateString("de-DE", { month: "long", year: "numeric" });
    $("calLabel").textContent = "Woche " + isoWeek(d0) + ", " + monthLabel;
    for (let i = 0; i < 7; i++) { const d = new Date(d0); d.setDate(d0.getDate() + i); grid.appendChild(makeCell(d, false, false)); }
    // U27c: Stundenplan-Ebene laden und (falls verfuegbar) blasse Chips einspielen.
    calTtRenderWeek(isoDate(d0), ttGen);
  }
  if (calMode === "month") {
    // U28: Termine bleiben in den kleinen Monatskacheln unklickbar → Klick wählt den Tag,
    // die Tages-Agenda darunter übernimmt Anzeige und Bearbeiten-Klicks (Fantastical-Stil).
    if (!calSelectedDate || calSelectedDate < monthStartStr || calSelectedDate > monthEndStr) {
      calSelectedDate = (todayStr >= monthStartStr && todayStr <= monthEndStr) ? todayStr : monthStartStr;
    }
    grid.querySelectorAll(".cal-cell").forEach((cell) => {
      cell.addEventListener("click", () => renderDayAgenda(cell.dataset.date));
    });
    renderDayAgenda(calSelectedDate);
  } else {
    const agenda = $("calDayAgenda"); if (agenda) agenda.classList.add("hidden");
    grid.querySelectorAll(".cal-entry").forEach((el) => {
      const lid = el.dataset.lesson;
      if (lid) {
        // U26: Stundentermin → direkt in die Stunden-Detailansicht springen (wie bisher).
        el.onclick = () => { const l = state.lessons.find((x) => String(x.id) === lid); if (l) openLessonModal(l); };
      } else if (el.dataset.entryId) {
        // U26: manueller/Google-/Import-Termin → Bearbeiten-Modal (wie Google Kalender).
        el.onclick = () => openCalendarEventModal(el.dataset.entryId);
      }
    });
    // U29: Klick auf die Tageszahl öffnet die Tages-Agenda (wie in der Monatsansicht),
    // ohne das Termin-Popover per Klick auf die freie Fläche zu verlieren.
    grid.querySelectorAll(".cal-daynum").forEach((num) => {
      num.addEventListener("click", (ev) => {
        ev.stopPropagation();
        renderDayAgenda(num.closest(".cal-cell").dataset.date);
      });
    });
    // U22: Klick auf die freie Fläche eines Tages öffnet das Termin-Popover (vorbefülltes Datum).
    grid.querySelectorAll(".cal-cell").forEach((cell) => {
      cell.addEventListener("click", (ev) => {
        // U27c/U27d: Klicks auf die (blasse) Stundenplan-Ebene oder den Tropentag-Toggle
        // öffnen kein Termin-Popover.
        if (ev.target.closest(".cal-entry, .cal-tt-strip, .cal-tt-daytoggle, .cal-daynum")) return;
        openCalEntryPanel(cell.dataset.date);
      });
    });
  }
}
// U28: Tages-Agenda unter dem Monatsgitter — zeigt die Termine eines Tages als Liste
// (Klick öffnet Bearbeiten/Detail); ersetzt das direkte Öffnen aus der Mini-Kachel heraus.
// U34: Bei aktivem Filter „Nur Stundenplan“ zeigt die Tages-Agenda stattdessen die
// Stundenplan-Stunden des Tages (wie Termine) statt der ausgeblendeten Meldung.
async function renderDayAgenda(dStr) {
  calSelectedDate = dStr;
  const panel = $("calDayAgenda");
  if (!panel) return;
  document.querySelectorAll("#calGrid .cal-cell").forEach((c) => c.classList.toggle("selected", c.dataset.date === dStr));
  const d = parseIso(dStr);
  $("calDayAgendaDate").textContent = d ? d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" }) : dStr;
  const addBtn = $("calDayAgendaAddBtn");
  if (addBtn) addBtn.onclick = () => openCalEntryPanel(dStr);
  if (calOnlyTt) {
    await renderDayAgendaTt(dStr);
    panel.classList.remove("hidden");
    return;
  }
  const items = entriesForDate(dStr).slice().sort((a, b) => {
    if (a.allDay !== b.allDay) return a.allDay ? -1 : 1;
    return (a.startTime || "").localeCompare(b.startTime || "");
  });
  const list = $("calDayAgendaList");
  list.innerHTML = items.length ? items.map((e) => {
    const cat = catById(e.categoryId);
    const color = cat ? calTtSafeColor(cat.color) : null;
    const style = color ? ` style="background:${color};color:${readableTextColor(color)}"` : "";
    const time = e.allDay ? "Ganztägig" : ([e.startTime, e.endTime].filter(Boolean).join(" – ") || "—");
    return `<div class="cal-day-agenda-item ${esc(e.entryType)}" data-lesson="${e.lessonId == null ? "" : e.lessonId}" data-entry-id="${e.id}"${style}>` +
      `<span class="cal-day-agenda-time">${esc(time)}</span><span class="cal-day-agenda-title">${esc(e.title)}${esc(entryClassSuffix(e))}${e.room ? ` <span class="muted small">· Zimmer ${esc(e.room)}</span>` : ""}</span></div>`;
  }).join("") : `<p class="muted small cal-day-agenda-empty">Keine Termine an diesem Tag.</p>`;
  list.querySelectorAll(".cal-day-agenda-item").forEach((el) => {
    const lid = el.dataset.lesson;
    if (lid) el.onclick = () => { const l = state.lessons.find((x) => String(x.id) === lid); if (l) openLessonModal(l); };
    else if (el.dataset.entryId) el.onclick = () => openCalendarEventModal(el.dataset.entryId);
  });
  panel.classList.remove("hidden");
}
// U34: Stundenplan-Stunden eines Tages in der Tages-Agenda anzeigen (Filter „Nur Stundenplan“).
async function renderDayAgendaTt(dStr) {
  const list = $("calDayAgendaList");
  const dd = parseIso(dStr);
  if (!dd) { list.innerHTML = `<p class="muted small cal-day-agenda-empty">Keine Stunden an diesem Tag.</p>`; return; }
  const monday = new Date(dd); monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  const mondayStr = isoDate(monday);
  let data;
  try { data = await calTtFetch(mondayStr); } catch (e) { data = null; }
  if (calSelectedDate !== dStr) return;                 // U34: Auswahl inzwischen weitergesprungen → Ergebnis verwerfen
  const day = data && Array.isArray(data.days) ? data.days.find((x) => x.date === dStr) : null;
  const items = day && Array.isArray(day.items) ? day.items : [];
  list.innerHTML = items.length ? items.map((it, idx) => {
    const color = calTtSafeColor(it.color);
    const style = ` style="background:${color};color:${readableTextColor(color)}"`;
    const delBtn = it.source === "override"
      ? `<button type="button" class="cal-tt-chip-del" data-tt-override-del="${it.entryId}" title="Vertretung entfernen" aria-label="Vertretung entfernen">×</button>`
      : "";
    // U35: geplante Stunde erkennbar machen – Klick öffnet sie bzw. bietet das Planen an.
    const planned = findLessonForTimetableItem(dStr, it);
    return `<div class="cal-day-agenda-item" data-tt-item="${idx}"${style}>` +
      `<span class="cal-day-agenda-time">${esc(it.timeRange || "")}</span>` +
      `<span class="cal-day-agenda-title">${esc(planned ? planned.title : it.title)}` +
      `${it.subtitle ? ` <span class="muted small">· ${esc(it.subtitle)}</span>` : ""}` +
      `${planned ? "" : ' <span class="muted small">· noch nicht geplant</span>'}</span>${delBtn}</div>`;
  }).join("") : `<p class="muted small cal-day-agenda-empty">Keine Stunden an diesem Tag.</p>`;
  list.querySelectorAll("[data-tt-item]").forEach((el) => {
    el.onclick = (ev) => {
      if (ev.target.closest("[data-tt-override-del]")) return;
      openTimetableSlotModal(dStr, items[Number(el.dataset.ttItem)]);
    };
  });
  list.querySelectorAll("[data-tt-override-del]").forEach((btn) => {
    btn.onclick = (ev) => { ev.stopPropagation(); calTtDeleteOverride(Number(btn.dataset.ttOverrideDel)); };
  });
}

async function saveCalendarEntry() {
  const title = $("calEntryTitle").value.trim(), date = $("calEntryDate").value;
  if (!title || !date) { toast("Bitte Titel und Datum angeben.", false); return; }
  const endDate = $("calEntryEndDate").value || null;
  if (endDate && endDate < date) { toast("Enddatum darf nicht vor dem Startdatum liegen.", false); return; }
  const allDay = $("calEntryAllDay").checked;
  try {
    await SyncEngine.create("calendar_entries", {
      title, entryDate: date, endDate,
      allDay,
      startTime: allDay ? null : ($("calEntryStartTime").value || null),
      endTime: allDay ? null : ($("calEntryEndTime").value || null),
      entryType: $("calEntryType").value,
      categoryId: $("calEntryCategory").value ? Number($("calEntryCategory").value) : null,
      classIds: getCheckedClassIds($("calEntryClasses")),
      isFixed: $("calEntryFixed").checked,
      room: $("calEntryRoom").value.trim() || null,
      notes: $("calEntryNotes").value.trim() || null,
    });
    $("calEntryTitle").value = ""; $("calEntryEndDate").value = "";
    $("calEntryStartTime").value = ""; $("calEntryEndTime").value = "";
    $("calEntryAllDay").checked = true; $("calEntryTimeRow").style.display = "none";
    $("calEntryFixed").checked = false; $("calEntryRoom").value = "";
    $("calEntrySlot").value = ""; $("calEntryNotes").value = "";
    renderClassCheckboxes($("calEntryClasses"), []);
    closeCalEntryPanel();
    await refresh(); toast("Termin gespeichert.");
  } catch (e) { toast(e.message, false); }
}

// U26: Klick auf einen (nicht stundengebundenen) Termin öffnet ein Bearbeiten-Modal
// (wie Google Kalender). Google-verknüpfte Termine sind bearbeitbar und mit Badge markiert.
function openCalendarEventModal(entryId) {
  const e = state.calendar.find((x) => String(x.id) === String(entryId));
  if (!e) return;
  const catOpts = `<option value="">— keine —</option>` +
    state.calendarCategories.map((c) => `<option value="${c.id}"${c.id === e.categoryId ? " selected" : ""}>${esc(c.name)}</option>`).join("");
  const typeOpts = [["lu", "Lernerfolgskontrolle"], ["exam", "Klassenarbeit/Präsentation"], ["normal", "Sonstiges"]]
    .map(([v, lab]) => `<option value="${v}"${e.entryType === v ? " selected" : ""}>${lab}</option>`).join("");
  const gBadge = e.googleEventId ? ` <span class="badge google">Google</span>` : "";
  $("modalRoot").innerHTML =
    `<div class="modal-overlay" id="modalOverlay"><div class="modal-box">
      <button class="modal-close" id="modalCloseBtn">Schließen</button>
      <h2>Termin bearbeiten${gBadge}</h2>
      <div class="modal-section">
        <div class="row">
          <div><label>Titel</label><input id="evtTitle" value="${esc(e.title)}" /></div>
          <div><label>Datum (von)</label><input id="evtDate" type="date" value="${esc(e.entryDate)}" /></div>
        </div>
        <div class="row">
          <div><label>Enddatum (optional, mehrtägig)</label><input id="evtEndDate" type="date" value="${esc(e.endDate || "")}" /></div>
          <div><label>Kategorie</label><select id="evtCategory">${catOpts}</select></div>
        </div>
        <label style="display:flex; align-items:center; gap:8px; margin-top:8px;"><input type="checkbox" id="evtAllDay" style="width:auto;"${e.allDay ? " checked" : ""} /> Ganztägig</label>
        <div class="row" id="evtTimeRow" style="margin-top:8px; display:${e.allDay ? "none" : "flex"};">
          <div><label>Uhrzeit von</label><input id="evtStartTime" type="time" value="${esc(e.startTime || "")}" /></div>
          <div><label>Uhrzeit bis</label><input id="evtEndTime" type="time" value="${esc(e.endTime || "")}" /></div>
        </div>
        <div class="row" style="margin-top:8px;">
          <div><label>Klassen</label><div class="class-toggle-row" id="evtClasses"></div></div>
          <div><label>Typ</label><select id="evtType">${typeOpts}</select></div>
        </div>
        <div class="row" style="margin-top:8px;">
          <div><label>Zimmer</label><input id="evtRoom" value="${esc(e.room || "")}" placeholder="z. B. 204" /></div>
        </div>
        <div style="margin-top:8px;"><label>Notizen</label><textarea id="evtNotes" rows="3" placeholder="Notizen zu diesem Termin">${esc(e.notes || "")}</textarea></div>
        <label style="display:flex; align-items:center; gap:8px; margin-top:8px;"><input type="checkbox" id="evtFixed" style="width:auto;"${e.isFixed ? " checked" : ""} /> Fixer Termin (nicht durch die Verplanung verschiebbar)</label>
        ${e.googleEventId ? `<p class="muted small" style="margin-top:8px;">Mit Google-Kalender verknüpft — Änderungen werden beim nächsten Sync übertragen.</p>` : ""}
      </div>
      <div style="margin-top:14px; display:flex; gap:8px; flex-wrap:wrap;">
        <button class="btn" id="evtSaveBtn">Speichern</button>
        ${((e.classIds && e.classIds.length) || e.classId != null) ? `<button class="btn secondary" id="evtPlanLessonBtn">Jetzt Unterrichtsstunde planen</button>` : ""}
        <button class="btn danger" id="evtDeleteBtn">Löschen</button>
        <button class="btn secondary" id="evtCancelBtn">Abbrechen</button>
      </div>
    </div></div>`;
  renderClassCheckboxes($("evtClasses"), e.classIds || (e.classId != null ? [e.classId] : []));
  $("modalOverlay").onclick = (ev) => { if (ev.target.id === "modalOverlay") closeModal(); };
  $("modalCloseBtn").onclick = closeModal;
  $("evtCancelBtn").onclick = closeModal;
  $("evtAllDay").onchange = () => { $("evtTimeRow").style.display = $("evtAllDay").checked ? "none" : "flex"; };
  $("evtSaveBtn").onclick = () => saveCalendarEventModal(e.id);
  $("evtDeleteBtn").onclick = () => deleteCalendarEventModal(e.id);
  if ($("evtPlanLessonBtn")) $("evtPlanLessonBtn").onclick = () => planLessonFromCalendarEntry(e);
}

async function saveCalendarEventModal(id) {
  const title = $("evtTitle").value.trim(), date = $("evtDate").value;
  if (!title || !date) { toast("Bitte Titel und Datum angeben.", false); return; }
  const endDate = $("evtEndDate").value || null;
  if (endDate && endDate < date) { toast("Enddatum darf nicht vor dem Startdatum liegen.", false); return; }
  const allDay = $("evtAllDay").checked;
  try {
    await SyncEngine.update("calendar_entries", id, {
      title, entryDate: date, endDate, allDay,
      startTime: allDay ? null : ($("evtStartTime").value || null),
      endTime: allDay ? null : ($("evtEndTime").value || null),
      entryType: $("evtType").value,
      categoryId: $("evtCategory").value ? Number($("evtCategory").value) : null,
      classIds: getCheckedClassIds($("evtClasses")),
      isFixed: $("evtFixed").checked,
      room: $("evtRoom").value.trim() || null,
      notes: $("evtNotes").value.trim() || null,
    });
    closeModal();
    await refresh(); toast("Termin aktualisiert.");
  } catch (err) { toast(err.message, false); }
}

async function deleteCalendarEventModal(id) {
  if (!confirm("Diesen Termin archivieren? Er lässt sich im Archiv (Reiter „Termine“) wiederherstellen.")) return;
  try {
    // Generischer Sync-Op 'delete' bildet auf Soft-Archiv ab (siehe SYNC_HANDLER-Kommentar in
    // calendar.py) — Undo nutzt weiterhin die REST-/restore-Route (online-only, analog
    // classes/todos: restore ist die seltene Ausnahme, kein alltäglicher Offline-Fall).
    await SyncEngine.remove("calendar_entries", id);
    closeModal();
    await refresh(); toast("Termin archiviert.");
    setUndo("Termin archiviert.", async () => {
      await API.post("/calendar/" + id + "/restore");
      await refresh();
    });
  } catch (err) { toast(err.message, false); }
}

/* ---------- U30: Vertretung (einmaliger Stundenplan-Eintrag) über den Dashboard-Quicklink ----------
   Eine Vertretung ist meist ein FREMDES Fach/eine fremde Klasse (nicht zwingend eine der
   eigenen state.classes) – daher Freitext statt Klassen-Dropdown; class_id bleibt leer. */
async function openVertretungModal() {
  let slots, kinds;
  try {
    // /stundenplan/settings löst serverseitig das Seeding der Default-Typen/Klingelzeiten aus
    // (analog ttLoad() in stundenplan.js) — bei einem frisch angelegten Konto, das die
    // Stundenplan-Ansicht noch nie geöffnet hat, wären timetable_kinds/_slots sonst leer.
    await API.get("/stundenplan/settings");
    await SyncEngine.pull();
    [slots, kinds] = await Promise.all([
      SyncEngine.materialize("timetable_slots"),
      SyncEngine.materialize("timetable_kinds"),
    ]);
  } catch (e) { toast(e.message, false); return; }
  const lessonSlots = slots.filter((s) => s.slotType === "lesson");
  const defKind = kinds.find((k) => k.isDefault) || kinds[0];
  if (!lessonSlots.length || !defKind) { toast("Bitte zuerst im Stundenplan Klingelzeiten und Typen anlegen.", false); return; }

  const slotOpts = lessonSlots.map((s) =>
    `<option value="${s.id}">${esc(s.label)} · ${esc(s.startTime)}–${esc(s.endTime)}</option>`).join("");

  $("modalRoot").innerHTML =
    `<div class="modal-overlay" id="vtModalOverlay"><div class="modal-box" style="max-width:460px;">
      <button class="modal-close" id="vtModalClose">Schließen</button>
      <h2>Vertretung hinzufügen</h2>
      <div class="modal-section">
        <label>Fach / Klasse</label>
        <input id="vtLabel" placeholder="z. B. 7b Biologie" />
        <div class="row" style="margin-top:8px;">
          <div><label>Datum</label><input id="vtDate" type="date" value="${esc(isoDate(new Date()))}" /></div>
          <div><label>Stunde</label><select id="vtSlot">${slotOpts}</select></div>
        </div>
        <p class="muted small" style="margin-top:8px;">Gilt nur für diesen einen Termin – kein wiederkehrender Eintrag.</p>
      </div>
      <div style="margin-top:14px; display:flex; gap:8px; flex-wrap:wrap;">
        <button class="btn" id="vtSaveBtn">Vertretung eintragen</button>
        <button class="btn secondary" id="vtCancelBtn">Abbrechen</button>
      </div>
    </div></div>`;
  $("vtModalOverlay").onclick = (ev) => { if (ev.target.id === "vtModalOverlay") closeModal(); };
  $("vtModalClose").onclick = closeModal;
  $("vtCancelBtn").onclick = closeModal;
  $("vtSaveBtn").onclick = () => saveVertretung(defKind.id);
  $("vtLabel").focus();
}

async function saveVertretung(kindId) {
  const label = $("vtLabel").value.trim();
  const date = $("vtDate").value;
  const slotId = $("vtSlot").value;
  if (!label) { toast("Bitte Fach/Klasse angeben.", false); return; }
  if (!date) { toast("Bitte ein Datum angeben.", false); return; }
  try {
    // ttFkValue (stundenplan.js, teilt sich den globalen Scope) wrappt eine noch nicht
    // synchronisierte "loc_..."-id als $localId-Platzhalter statt sie per Number() zu NaN
    // zu machen — siehe dortiger Kommentar.
    await SyncEngine.create("timetable_overrides", {
      date, slotId: ttFkValue(slotId), kindId: ttFkValue(kindId), label,
    });
    closeModal();
    calTtCache.clear();               // Woche(n) neu vom Server holen (Override eingerechnet)
    await renderTodayList();
    await renderWeekOverview();
    renderCalendar();                 // blasse Stundenplan-Ebene im Planungskalender aktualisieren
    toast("Vertretung eingetragen.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- M1d: Schulmanager-Abgleich (Glocke + Schublade, Konzept B) ----------
Referenzpunkt Unterricht (Vertretung/Ausfall) = U27-Stundenplan, Aufsicht = Planungskalender
(schulmanager_diff.py, Server). "Ignorieren" ist bewusst nur clientseitig für diese Sitzung –
keine Persistenz, blendet nur bis zum nächsten vollständigen Neuladen aus. */
let smChanges = null;        // letzter Abgleich-Stand vom Server (kategorisiert)
const smIgnored = new Set(); // Schlüssel ignorierter Änderungen, nur für diese Sitzung

function smChangeKey(kind, c) {
  return kind + "|" + ((c.actual && c.actual.uid) || (c.date + "T" + c.start));
}

function smVisibleChanges() {
  const empty = { vertretung: [], ausfall: [], aufsichtNeu: [], aufsichtGeaendert: [] };
  if (!smChanges) return empty;
  const filt = (kind, list) => (list || []).filter((c) => !smIgnored.has(smChangeKey(kind, c)));
  return {
    vertretung: filt("vertretung", smChanges.vertretung),
    ausfall: filt("ausfall", smChanges.ausfall),
    aufsichtNeu: filt("aufsichtNeu", smChanges.aufsichtNeu),
    aufsichtGeaendert: filt("aufsichtGeaendert", smChanges.aufsichtGeaendert),
  };
}

function smTotalCount(v) {
  return v.vertretung.length + v.ausfall.length + v.aufsichtNeu.length + v.aufsichtGeaendert.length;
}

// Bell nur sichtbar, wenn ein ICS-Link hinterlegt ist; Abruf-Fehler (Feed nicht erreichbar)
// lassen die Glocke stehen, aber ohne Badge – kein Toast bei jedem Seitenaufruf.
async function refreshSchulmanagerChanges() {
  const bell = $("smBellBtn");
  if (!bell) return;
  let iconSet = false;
  try { iconSet = Boolean((await API.get("/settings")).schulmanagerIcalSet); } catch (e) { /* ignore */ }
  if (!iconSet) { bell.classList.add("hidden"); smChanges = null; return; }
  bell.classList.remove("hidden");
  try { smChanges = await API.get("/schulmanager/changes"); }
  catch (e) { smChanges = null; }
  renderSchulmanagerBell();
}

function renderSchulmanagerBell() {
  const dot = $("smBellCount");
  if (!dot) return;
  const count = smTotalCount(smVisibleChanges());
  dot.textContent = String(count);
  dot.classList.toggle("hidden", count === 0);
}

function smLabelFor(kind) {
  return { vertretung: "Vertretung", ausfall: "Ausfall", aufsichtNeu: "Neu", aufsichtGeaendert: "Geändert" }[kind] || kind;
}
function smChipClassFor(kind) {
  return kind === "vertretung" ? "vertretung" : kind === "ausfall" ? "ausfall" : "aufsicht";
}

async function openSchulmanagerDrawer() {
  $("smDrawerOverlay").classList.remove("hidden");
  await refreshSchulmanagerChanges();  // frischer Stand bei jedem Öffnen
  renderSchulmanagerDrawer();
}
function closeSchulmanagerDrawer() { $("smDrawerOverlay").classList.add("hidden"); }

function renderSchulmanagerDrawer() {
  const body = $("smDrawerBody");
  if (!body) return;
  const v = smVisibleChanges();
  const items = [
    ...v.vertretung.map((c) => ({ kind: "vertretung", c })),
    ...v.ausfall.map((c) => ({ kind: "ausfall", c })),
    ...v.aufsichtNeu.map((c) => ({ kind: "aufsichtNeu", c })),
    ...v.aufsichtGeaendert.map((c) => ({ kind: "aufsichtGeaendert", c })),
  ].sort((a, b) => (a.c.date + a.c.start).localeCompare(b.c.date + b.c.start));

  if (!items.length) {
    body.innerHTML = `<p class="sm-drawer-empty">Keine offenen Änderungen.</p>`;
    return;
  }

  let html = "";
  let lastDate = null;
  items.forEach(({ kind, c }, idx) => {
    if (c.date !== lastDate) {
      lastDate = c.date;
      const d = parseIso(c.date);
      html += `<div class="sm-drawer-day">${d ? esc(d.toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "2-digit" })) : esc(c.date)}</div>`;
    }
    const titleNow = (c.actual && c.actual.title) || (c.expected && c.expected.title) || "";
    const isUnterricht = kind === "vertretung" || kind === "ausfall";
    const actionLabel = isUnterricht ? "Ausarbeiten" : "Übernehmen";
    html += `<div class="sm-drawer-item">
      <div class="sm-di-top">
        <div class="sm-di-title">${esc(titleNow)}, ${esc(c.start)}${c.end ? "–" + esc(c.end) : ""}</div>
        <span class="sm-chip ${smChipClassFor(kind)}">${esc(smLabelFor(kind))}</span>
      </div>
      <div class="sm-di-compare">
        ${c.expected ? `<div class="row"><span class="lbl">Dein Plan</span><span class="old">${esc((c.expected.title || "") + (c.expected.room ? " · " + c.expected.room : ""))}</span></div>` : ""}
        <div class="row"><span class="lbl">Jetzt</span><span class="new">${c.actual ? esc((c.actual.title || "") + (c.actual.room ? " · " + c.actual.room : "")) : "entfällt"}</span></div>
      </div>
      <div class="sm-di-actions">
        <button class="btn" data-sm-act="act" data-sm-idx="${idx}">${actionLabel}</button>
        <button class="btn ghost" data-sm-act="ignore" data-sm-idx="${idx}">Ignorieren</button>
      </div>
    </div>`;
  });
  body.innerHTML = html;

  body.querySelectorAll("[data-sm-act]").forEach((btn) => {
    btn.onclick = () => {
      const { kind, c } = items[Number(btn.dataset.smIdx)];
      if (btn.dataset.smAct === "ignore") { smIgnoreChange(kind, c); return; }
      smActOnChange(kind, c);
    };
  });
}

function smIgnoreChange(kind, c) {
  smIgnored.add(smChangeKey(kind, c));
  renderSchulmanagerDrawer();
  renderSchulmanagerBell();
}

// "Ausarbeiten"/"Übernehmen": übernimmt nichts blind, sondern öffnet den passenden
// bestehenden Editor vorausgefüllt – der eigentliche Kalendereintrag entsteht erst,
// wenn dort gespeichert wird (Absprache mit dem Nutzer).
function smActOnChange(kind, c) {
  smIgnored.add(smChangeKey(kind, c));  // aus der Schublade nehmen, sobald in Bearbeitung
  renderSchulmanagerBell();
  closeSchulmanagerDrawer();
  if (kind === "vertretung" || kind === "ausfall") {
    const item = {
      classId: c.classId != null ? c.classId : null,
      title: (c.expected && c.expected.title) || (c.actual && c.actual.title) || "",
      timeRange: c.start + "–" + (c.end || c.start),
      slotLabel: "", spanSlots: 1,
    };
    openTimetableSlotModal(c.date, item);
  } else if (kind === "aufsichtNeu") {
    showView("kalender");
    openCalEntryPanel(c.date);
    if ($("calEntryTitle")) $("calEntryTitle").value = (c.actual && c.actual.title) || "Aufsicht";
    if ($("calEntryAllDay")) $("calEntryAllDay").checked = false;
    if ($("calEntryTimeRow")) $("calEntryTimeRow").style.display = "flex";
    if ($("calEntryStartTime")) $("calEntryStartTime").value = c.start;
    if ($("calEntryEndTime")) $("calEntryEndTime").value = c.end || "";
    if ($("calEntryRoom") && c.actual) $("calEntryRoom").value = c.actual.room || "";
  } else if (kind === "aufsichtGeaendert" && c.entryId != null) {
    showView("kalender");
    openCalendarEventModal(c.entryId);
  }
}

/* ---------- Kalender-Kategorien (U11) ---------- */
function renderCategorySelect() {
  const sel = $("calEntryCategory");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = `<option value="">— keine —</option>` +
    state.calendarCategories.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  sel.value = prev;
}

function renderCalendarLegend() {
  const wrap = $("calLegend");
  if (!wrap) return;
  const typeItems = [
    { color: cssVar("--bad", "#dc2626"), label: "Lernerfolgskontrolle" },
    { color: cssVar("--orange", "#f97316"), label: "Klassenarbeit/Präsentation" },
  ];
  const catItems = state.calendarCategories.map((c) => ({ color: c.color, label: c.name }));
  wrap.innerHTML = typeItems.concat(catItems).map((it) =>
    `<span class="cal-legend-item"><span class="cal-legend-dot" style="background:${esc(it.color)}"></span>${esc(it.label)}</span>`).join("");
}

function renderCategoryManager() {
  const wrap = $("calCategoryList");
  if (!wrap) return;
  wrap.innerHTML = "";
  if (!state.calendarCategories.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine Kategorien.</p>';
    return;
  }
  state.calendarCategories.forEach((c) => {
    const div = document.createElement("div");
    div.className = "cal-cat-row";
    div.innerHTML =
      `<input type="color" value="${esc(c.color)}" data-cat-color="${c.id}" />` +
      `<input type="text" value="${esc(c.name)}" data-cat-name="${c.id}" />` +
      `<button class="btn small secondary" data-cat-save="${c.id}">Speichern</button>` +
      `<button class="btn small danger" data-cat-del="${c.id}">Löschen</button>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-cat-save]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.catSave;
      const name = wrap.querySelector(`[data-cat-name="${id}"]`).value.trim();
      const color = wrap.querySelector(`[data-cat-color="${id}"]`).value;
      if (!name) { toast("Bitte einen Namen angeben.", false); return; }
      try { await SyncEngine.update("calendar_categories", id, { name, color }); await refresh(); toast("Kategorie gespeichert."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-cat-del]").forEach((b) => {
    b.onclick = async () => {
      try { await SyncEngine.remove("calendar_categories", b.dataset.catDel); await refresh(); toast("Kategorie gelöscht."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

async function addCategory() {
  const name = $("newCatName").value.trim(), color = $("newCatColor").value;
  if (!name) { toast("Bitte einen Namen angeben.", false); return; }
  try {
    await SyncEngine.create("calendar_categories", { name, color });
    $("newCatName").value = "";
    await refresh(); toast("Kategorie angelegt.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- Jahresplan-Import (U20) ---------- */
let importSuggestions = [];  // zuletzt von der KI erkannte Terminvorschläge

function importCategoryOptions(selectedId) {
  const opts = ['<option value="">— keine —</option>'].concat(
    state.calendarCategories.map((c) =>
      `<option value="${c.id}"${String(c.id) === String(selectedId) ? " selected" : ""}>${esc(c.name)}</option>`));
  return opts.join("");
}

function matchCategoryId(name) {
  if (!name) return "";
  const hit = state.calendarCategories.find(
    (c) => c.name.trim().toLowerCase() === String(name).trim().toLowerCase());
  return hit ? hit.id : "";
}

function renderImportSuggestions() {
  if (!importSuggestions.length) {
    $("modalRoot").innerHTML = "";
    toast("Keine Termine erkannt.", false);
    return;
  }
  const rows = importSuggestions.map((s, i) => {
    const range = s.endDatum ? `${esc(s.datum)} – ${esc(s.endDatum)}` : esc(s.datum);
    return `<div class="import-row">
      <input type="checkbox" data-import-cb="${i}" checked />
      <span class="import-date">${range}</span>
      <span class="import-title">${esc(s.titel)}</span>
      <select data-import-cat="${i}">${importCategoryOptions(matchCategoryId(s.kategorieVorschlag))}</select>
    </div>`;
  }).join("");
  $("modalRoot").innerHTML =
    `<div class="modal-overlay" id="modalOverlay"><div class="modal-box" style="max-width:820px;">
      <button class="modal-close" id="modalCloseBtn">Schließen</button>
      <h2>Jahresplan-Import</h2>
      <div class="modal-section">
        <p class="small muted">${importSuggestions.length} Termin(e) erkannt – Auswahl prüfen und übernehmen.</p>
        ${rows}
        <div style="margin-top:14px;"><button class="btn" id="importCommitBtn">Ausgewählte übernehmen</button></div>
      </div>
    </div></div>`;
  $("modalOverlay").onclick = (ev) => { if (ev.target.id === "modalOverlay") closeModal(); };
  $("modalCloseBtn").onclick = closeModal;
  $("importCommitBtn").onclick = commitJahresplanImport;
}

async function analyzeJahresplan() {
  const f = $("importFile").files[0];
  if (!f) { toast("Bitte eine PDF-Datei wählen.", false); return; }
  const btn = $("importAnalyzeBtn");
  btn.disabled = true; btn.textContent = "Analysiere …";
  try {
    const fd = new FormData();
    fd.append("file", f);
    importSuggestions = await API.upload("/calendar/import/analyze", fd);
    renderImportSuggestions();
    toast(`${importSuggestions.length} Termin(e) erkannt.`);
  } catch (e) {
    toast(e.message, false);
  } finally {
    btn.disabled = false; btn.textContent = "PDF analysieren";
  }
}

async function commitJahresplanImport() {
  const wrap = $("modalRoot");
  const entries = [];
  wrap.querySelectorAll("[data-import-cb]").forEach((cb) => {
    if (!cb.checked) return;
    const i = cb.dataset.importCb;
    const s = importSuggestions[i];
    const catVal = wrap.querySelector(`[data-import-cat="${i}"]`).value;
    entries.push({
      datum: s.datum, endDatum: s.endDatum || null, titel: s.titel,
      categoryId: catVal ? Number(catVal) : null,
    });
  });
  if (!entries.length) { toast("Keine Termine ausgewählt.", false); return; }
  try {
    const created = await API.post("/calendar/import/commit", { entries });
    importSuggestions = []; $("importFile").value = ""; closeModal();
    await refresh(); toast(`${created.length} Termin(e) übernommen.`);
  } catch (e) { toast(e.message, false); }
}

async function saveSchoolYear() {
  const label = $("syLabel").value.trim(), start = $("syStart").value, end = $("syEnd").value;
  if (!label || !start || !end) { toast("Bitte Bezeichnung, Beginn und Ende angeben.", false); return; }
  try {
    await SyncEngine.create("school_years", { label, startDate: start, endDate: end });
    $("syLabel").value = ""; await refresh(); toast("Schuljahr angelegt (Ferien/Feiertage abgerufen).");
  } catch (e) { toast(e.message, false); }
}

/* ---------- Stoffverteilungsplan-View (U12/U16/U19), inkl. "Kumulierte Ansicht" ----------
   Ausgelagert nach web/stoffplan.js (ES-Modul, app.js-Splitting, dritter Kandidat nach
   sitzplan.js/notizen.js), per dynamischem import() erst beim ersten Öffnen der
   Stoffverteilungsplan-Ansicht nachgeladen. downloadStoffPlanPdf und cascadeStoffPlanDates
   (Zeile ~1131) bleiben in app.js, weil die Klassen-Detail-Ansicht sie direkt braucht. */
let _stoffplanModulePromise = null;
let _stoffplanModuleInstance = null;
function getStoffplanModule() {
  if (!_stoffplanModulePromise) {
    _stoffplanModulePromise = import("./stoffplan.js").then((mod) => {
      _stoffplanModuleInstance = mod.createStoffplanModule({
        $, esc, API, toast, state, refresh, setUndo, SyncEngine,
        deDate, nextMonday, parseIso, isoDate, openDatePicker,
        resetLocalUndo, restoreSequenzStunden, getLernbereiche, resolveTrack,
        downloadStoffPlanPdf, cascadeStoffPlanDates,
      });
      return _stoffplanModuleInstance;
    });
  }
  return _stoffplanModulePromise;
}

/* ---------- Sequenzplanung-View: Einzelstunden je Stoffplan-Block ----------
   Ausgelagert nach web/sequenzplan.js (ES-Modul, app.js-Splitting, vierter Kandidat),
   per dynamischem import() erst beim ersten Öffnen der Sequenzplanung-Ansicht
   nachgeladen. restoreSequenzStunden (Zeile ~100) bleibt in app.js – wird bereits für
   stoffplan.js injiziert und hier genauso mitbenutzt. */
let _sequenzplanModulePromise = null;
let _sequenzplanModuleInstance = null;
function getSequenzplanModule() {
  if (!_sequenzplanModulePromise) {
    _sequenzplanModulePromise = import("./sequenzplan.js").then((mod) => {
      _sequenzplanModuleInstance = mod.createSequenzplanModule({
        $, esc, API, toast, state, setUndo, resetLocalUndo, restoreSequenzStunden, deDate,
      });
      return _sequenzplanModuleInstance;
    });
  }
  return _sequenzplanModulePromise;
}

/* ---------- Stunden-Detail-Modal ---------- */
function openLessonModal(l) {
  const meyer = (l.meyerPlan || [])
    .map((v, i) => `<span class="mini-meyer-chip" style="background:${ampelColor(v)}">${i + 1}. ${esc(meyerMerkmale[i])}</span>`)
    .join(" ");
  const ziele = l.lernziele || [];
  const bloomBadge = (z) => z.bloomStufe ? ` <span style="${ZIEL_BADGE}">${esc(z.bloomStufe)}</span>` : "";
  const zielMark = (p) => (ziele
    .filter((z) => z.kind === "fein" && z.phaseSortOrder != null && String(z.phaseSortOrder) === String(p.sortOrder))
    .map((z) => `<br><span style="${ZIEL_BADGE}">🎯 ${esc((z.text || "").slice(0, 45))}${(z.text || "").length > 45 ? "…" : ""}</span>`)
    .join(""));
  const phases = (l.phases || [])
    .map((p) =>
      `<div class="phase"><strong>${esc(p.phaseName)}</strong> (${esc(p.minutes ?? "–")} Min., ${esc(p.socialForm || "–")})<br>` +
      `<span class="small muted">Methode: ${esc(p.method || "–")} – Material: ${esc(p.material || "–")}</span><br>` +
      `<span class="small">L: ${esc(p.teacherActivity || "–")}</span><br>` +
      `<span class="small">S: ${esc(p.studentActivity || "–")}</span>${zielMark(p)}</div>`)
    .join("") || '<p class="muted small">Noch keine Phasen erfasst.</p>';
  const zieleHtml = ziele.length
    ? (ziele.filter((z) => z.kind === "grob").map((z) => `<p class="small"><strong>Grobziel:</strong> ${esc(z.text)}${bloomBadge(z)}</p>`).join("") +
       ziele.filter((z) => z.kind === "fein").map((z) => `<p class="small">• ${esc(z.text)}${bloomBadge(z)}` +
         `${z.phaseSortOrder != null ? ` <span class="muted small">(${esc(((l.phases || [])[z.phaseSortOrder] || {}).phaseName || "Phase")})</span>` : ""}</p>`).join(""))
    : '<p class="muted small">Noch keine Lernziele erfasst.</p>';
  const k = l.klafki || {};
  const kLabels = [["gegenwart", "Gegenwartsbedeutung"], ["zukunft", "Zukunftsbedeutung"],
    ["exemplarisch", "Exemplarische Bedeutung"], ["zugang", "Zugänglichkeit/Einstieg"], ["struktur", "Struktur des Inhalts"]];
  const klafki = kLabels.filter(([f]) => k[f]).map(([f, lab]) => `<p class="small"><strong>${lab}:</strong> ${esc(k[f])}</p>`).join("")
    || '<p class="muted small">Noch keine Angaben.</p>';
  const bibox = l.bibox && l.bibox.werk
    ? `<p class="small"><strong>Lehrwerk:</strong> ${esc(l.bibox.werk)} – ${esc(l.bibox.seite || "")} ${l.bibox.notiz ? "– " + esc(l.bibox.notiz) : ""}</p>`
    : '<p class="muted small">Keine Lehrbuch-Referenz hinterlegt.</p>';
  const moveBtn = l.classId != null
    ? '<button class="btn small secondary" id="modalMoveBtn" style="float:right; margin-right:10px;">Stunde verschieben</button>'
    : "";
  const tbBoard = tafelbildBoardHtml(l.tafelbild);
  const tbImg = l.tafelbildBildMaterialId != null
    ? `<img src="/api/materials/${l.tafelbildBildMaterialId}/download" alt="Tafelbild" style="max-width:100%;border-radius:8px;display:block;margin-bottom:8px;">
       <button class="btn small danger" id="modalTbImgRemove" style="margin-bottom:10px;">Bild entfernen</button>`
    : "";
  const tbEmpty = (!tbBoard && !tbImg) ? '<p class="muted small">Kein Tafelbild geplant.</p>' : "";
  $("modalRoot").innerHTML =
    `<div class="modal-overlay" id="modalOverlay"><div class="modal-box">
      <button class="modal-close" id="modalCloseBtn">Schließen</button>
      <button class="btn small secondary" id="modalAsuvBtn" style="float:right; margin-right:10px;">ASUV-Entwurf</button>
      <button class="btn small secondary" id="modalDuplicateBtn" style="float:right; margin-right:10px;">Duplizieren</button>
      <button class="btn small secondary" id="modalEditBtn" style="float:right; margin-right:10px;">Stunde bearbeiten</button>
      ${moveBtn}
      <button class="btn small danger" id="modalDeleteBtn" style="float:right; margin-right:10px;">Löschen</button>
      <h2>${esc(l.title)}</h2>
      <p class="muted small">${esc(l.subject)} – Klasse ${esc(l.grade || "?")} – ${esc(l.lessonType || "")} – ${esc(l.durationMinutes || 45)} Min. ${l.time ? "– " + esc(l.time) + " Uhr" : ""}</p>
      <div id="modalMoveSlots"></div>
      <div class="modal-section"><h3>Tafelbild</h3>
        ${tbImg}
        ${tbBoard ? `<div class="tafelbild-board">${tbBoard}</div>` : ""}
        ${tbEmpty}
        <label class="small" style="display:block; margin-top:10px;">Notizen</label>
        <textarea id="modalTbNotiz" style="width:100%; min-height:60px;" placeholder="Eigene Ergänzungen zum Tafelbild ...">${esc(l.tafelbildNotiz || "")}</textarea>
        <div style="margin-top:8px;">
          <input type="file" id="modalTbImgFile" accept="image/*" />
          <button class="btn small" id="modalTbImgUpload" style="margin-top:6px;">Eigenes Bild hochladen</button>
        </div>
      </div>
      <div class="modal-section"><h3>Lernziele</h3>${zieleHtml}</div>
      <div class="modal-section"><h3>Phasentabelle</h3>${phases}</div>
      <div class="modal-section"><h3>Lehrbuch-Referenz</h3>${bibox}</div>
      <div class="modal-section"><h3>Klafki</h3>${klafki}</div>
      <div class="modal-section"><h3>Meyer-Merkmale (geplant)</h3>${meyer || '<p class="muted small">Noch keine Angaben.</p>'}</div>
      <div class="modal-section"><h3>Material zu dieser Stunde</h3>
        <div id="modalMaterials" class="file-list" style="margin-bottom:8px;"></div>
        <input type="file" id="modalMatFile" />
        <button class="btn small" id="modalMatUpload" style="margin-top:6px;">Hochladen &amp; verknüpfen</button>
      </div>
    </div></div>`;
  $("modalOverlay").onclick = (e) => { if (e.target.id === "modalOverlay") closeModal(); };
  $("modalCloseBtn").onclick = closeModal;
  $("modalAsuvBtn").onclick = () => { closeModal(); showView("asuv"); loadAsuv(l.id); };
  $("modalEditBtn").onclick = () => { closeModal(); showView("stunde"); loadLessonIntoForm(l); };
  $("modalDuplicateBtn").onclick = () => { closeModal(); showView("stunde"); duplicateLessonIntoForm(l); };
  if ($("modalMoveBtn")) $("modalMoveBtn").onclick = () => loadMoveSlotsPanel(l);
  $("modalDeleteBtn").onclick = async () => {
    if (!window.confirm("Diese Stunde wirklich löschen?")) return;
    try {
      await SyncEngine.remove("lessons", l.id);
      if (editingLessonId === l.id) { resetLessonEditState(); clearLessonForm(); }
      closeModal();
      await refresh();
      toast("Stunde gelöscht.");
    } catch (e) { toast(e.message, false); }
  };
  loadModalMaterials(l);
  wireModalTafelbild(l);
  $("modalMatUpload").onclick = async () => {
    const f = $("modalMatFile").files[0];
    if (!f) { toast("Bitte eine Datei wählen.", false); return; }
    const fd = new FormData();
    fd.append("file", f);
    fd.append("subject", l.subject);
    if (l.grade) fd.append("grade", l.grade);
    fd.append("lessonId", l.id);
    try { await API.upload("/materials/upload", fd); await refresh(); loadModalMaterials(l); toast("Material verknüpft."); }
    catch (e) { toast(e.message, false); }
  };
}
// Tafelbild-Sektion im Stunden-Detail-Modal: Notizen direkt editierbar (debounced Autosave),
// eigenes Bild hochladen/entfernen. Änderungen laufen über den Offline-Sync wie im Formular;
// ist dieselbe Stunde gerade im Bearbeiten-Formular offen, wird dessen Vorschau mitgezogen.
let _modalTbNotizTimer = null;
function wireModalTafelbild(l) {
  const ta = $("modalTbNotiz");
  if (ta) {
    ta.addEventListener("input", () => {
      if (_modalTbNotizTimer) clearTimeout(_modalTbNotizTimer);
      _modalTbNotizTimer = setTimeout(async () => {
        try {
          await SyncEngine.update("lessons", l.id, { tafelbildNotiz: ta.value });
          l.tafelbildNotiz = ta.value;
          if (editingLessonId === l.id && $("tafelbildNotiz")) $("tafelbildNotiz").value = ta.value;
        } catch (e) { toast(e.message, false); }
      }, 900);
    });
  }
  const up = $("modalTbImgUpload");
  if (up) up.onclick = async () => {
    const f = $("modalTbImgFile").files[0];
    if (!f) { toast("Bitte ein Bild wählen.", false); return; }
    const fd = new FormData();
    fd.append("file", f);
    fd.append("subject", l.subject);
    if (l.grade) fd.append("grade", l.grade);
    fd.append("lessonId", l.id);
    up.disabled = true;
    try {
      const m = await API.upload("/materials/upload", fd);
      await SyncEngine.update("lessons", l.id, { tafelbildBildMaterialId: m.id });
      l.tafelbildBildMaterialId = m.id;
      if (editingLessonId === l.id) { lessonTafelbildBildId = m.id; renderTafelbildBild(); }
      toast("Bild hinzugefügt.");
      openLessonModal(l);
    } catch (e) { up.disabled = false; toast(e.message, false); }
  };
  const rm = $("modalTbImgRemove");
  if (rm) rm.onclick = async () => {
    try {
      await SyncEngine.update("lessons", l.id, { tafelbildBildMaterialId: null });
      l.tafelbildBildMaterialId = null;
      if (editingLessonId === l.id) { lessonTafelbildBildId = null; renderTafelbildBild(); }
      toast("Bild entfernt.");
      openLessonModal(l);
    } catch (e) { toast(e.message, false); }
  };
}

async function loadModalMaterials(l) {
  const wrap = document.getElementById("modalMaterials");
  if (!wrap) return;
  try {
    const mats = await API.get(`/lessons/${l.id}/materials`);
    wrap.innerHTML = mats.length
      ? mats.map((m) => `<div class="file-chip"><span><a href="/api/materials/${m.id}/download">${esc(m.filename)}</a></span><button class="btn small danger" data-del-mat="${m.id}" aria-label="Material entfernen">✕</button></div>`).join("")
      : '<p class="muted small">Noch kein Material verknüpft.</p>';
    wireMaterialDeleteButtons(wrap, () => loadModalMaterials(l));
  } catch (e) { wrap.innerHTML = ""; }
}
function closeModal() { $("modalRoot").innerHTML = ""; }

/* A11y: Fokus-Falle, Esc-Schließen und Fokus-Rückgabe für alle #modalRoot-Dialoge
   und das Login-Overlay. Ergänzt die bestehende Overlay-Klick-Logik, ohne sie zu ersetzen. */
(function setupModalA11y() {
  const root = document.getElementById("modalRoot");
  const auth = document.getElementById("authOverlay");
  if (!root || !auth) return;
  let restoreTo = null;
  const focusablesIn = (box) =>
    Array.from(box.querySelectorAll(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
    )).filter((el) => el.offsetWidth || el.offsetHeight || el === document.activeElement);
  function activate(box) {
    if (!box || box.dataset.a11yOn) return;
    box.dataset.a11yOn = "1";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.tabIndex = -1;
    restoreTo = document.activeElement;
    const f = focusablesIn(box);
    (f[0] || box).focus();
  }
  document.addEventListener("keydown", (e) => {
    const overlay = root.querySelector(".modal-overlay") || (!auth.classList.contains("hidden") ? auth : null);
    if (!overlay) return;
    const box = overlay.querySelector(".modal-box") || overlay;
    if (e.key === "Escape") {
      if (root.contains(overlay)) { e.preventDefault(); closeModal(); }
      return;
    }
    if (e.key !== "Tab") return;
    const f = focusablesIn(box);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  new MutationObserver(() => {
    const box = root.querySelector(".modal-box");
    if (box) activate(box);
    else if (restoreTo && restoreTo.focus) { try { restoreTo.focus(); } catch (_) { /* egal */ } restoreTo = null; }
  }).observe(root, { childList: true });
  new MutationObserver(() => {
    const box = auth.querySelector(".modal-box");
    if (!box) return;
    if (!auth.classList.contains("hidden")) activate(box);
    else { delete box.dataset.a11yOn; if (restoreTo && restoreTo.focus) { try { restoreTo.focus(); } catch (_) { /* egal */ } restoreTo = null; } }
  }).observe(auth, { attributes: true, attributeFilter: ["class"] });
})();

// "Stunde verschieben" (Planungskalender u.a. Aufrufer von openLessonModal): Zieldatum nur aus
// den nächsten laut Stundenplan realen Terminen der Klasse wählbar (kein Freitext-Datum) –
// Liste kommt vom Server (/lessons/{id}/upcoming-slots), das eigentliche Verschieben inkl.
// Sequenzplan-Kaskade läuft über /lessons/{id}/move-to-slot (s. dortiger Serverkommentar:
// Ursprungszeile bleibt mit "verschoben nach ..."-Hinweis stehen, neue Zeile am Zielort).
async function loadMoveSlotsPanel(l) {
  const box = $("modalMoveSlots");
  if (!box) return;
  box.innerHTML = '<p class="muted small" style="margin-top:10px;">Lade nächste Termine laut Stundenplan …</p>';
  let slots = [];
  try { slots = await API.get(`/lessons/${l.id}/upcoming-slots?count=8`); }
  catch (e) { box.innerHTML = `<p class="muted small" style="margin-top:10px;">${esc(e.message)}</p>`; return; }
  if (!slots.length) {
    box.innerHTML = '<p class="muted small" style="margin-top:10px;">Kein künftiger Stundenplan-Termin für diese Klasse gefunden.</p>';
    return;
  }
  const rows = slots.map((s, i) => {
    const wd = WEEKDAY_SHORT[weekdayOf(s.date)];
    const label = `${wd} ${esc(deDate(s.date))}${s.time ? ", " + esc(s.time) + " Uhr" : ""}`;
    return `<button class="btn tiny secondary" data-move-slot="${i}" style="margin:2px;">${label}</button>`;
  }).join("");
  box.innerHTML = `<div class="note-box" style="margin-top:10px;">
    <strong>Auf welchen Termin verschieben?</strong><br>${rows}
  </div>`;
  box.querySelectorAll("[data-move-slot]").forEach((b) => b.onclick = () =>
    moveLessonToSlot(l, slots[Number(b.dataset.moveSlot)]));
}

async function moveLessonToSlot(l, slot) {
  const withCalendar = window.confirm(
    "Auch bereits terminierte, verknüpfte Sequenzstunden automatisch nachrücken lassen?"
  );
  try {
    const res = await API.post(`/lessons/${l.id}/move-to-slot`, { date: slot.date, time: slot.time, withCalendar });
    closeModal();
    await refresh();
    if (res.newSequenzStundeId != null) {
      toast(res.overBudget
        ? `Verschoben. Achtung: ${res.plannedCount} Stunden geplant, Richtwert ${res.richtwertUstd ?? "?"} Ustd. im Sequenzplan.`
        : "Verschoben – im Sequenzplan als neue Karte übernommen.");
    } else {
      toast("Stunde verschoben.");
    }
  } catch (e) { toast(e.message, false); }
}

/* ---------- Speichern ---------- */
async function saveClass() {
  const name = $("className").value.trim();
  if (!name) { toast("Bitte einen Klassennamen angeben.", false); return; }
  const body = {
    name, subject: $("classSubject").value, grade: Number($("classGrade").value),
    track: $("classTrack").value, weeklyHours: Number($("classHours").value) || 2,
    parallelGroup: $("classGroup").value.trim() || null,
  };
  try {
    if (editingClassId) {
      await SyncEngine.update("classes", editingClassId, body);
    } else {
      await SyncEngine.create("classes", body);
    }
    resetClassForm();
    await refresh(); toast("Klasse gespeichert.");
  } catch (e) { toast(e.message, false); }
}

async function saveLesson() {
  if (lessonAutosaveTimer) { clearTimeout(lessonAutosaveTimer); lessonAutosaveTimer = null; }
  if (!$("lessonTitle").value.trim()) { toast("Bitte einen Titel angeben.", false); return; }
  const rest = validatePhaseTimes();
  if (rest !== 0) {
    const duration = Number($("lessonDuration").value) || 45;
    const hint = rest > 0 ? `${rest} Min. sind noch nicht verplant` : `${-rest} Min. sind zu viel verplant`;
    if (!window.confirm(`Die Phasenzeiten füllen die ${duration} Minuten nicht exakt aus – ${hint}. Trotzdem speichern?`)) return;
  }
  const body = buildLessonBody();
  try {
    // Material-Upload/Kalender-Verknüpfung/Sequenz-Verknüpfung (in applyPendingLessonLinks)
    // brauchen zwingend die echte Server-id (eigene REST-Calls, kein Sync-Payload) —
    // createAndSync() wartet den Push einmalig ab statt nur optimistisch die lokale id
    // zurückzugeben (siehe Kommentar dort). Offline schlägt das bewusst fehl, statt eine
    // lokale id vorzutäuschen.
    const saved = await persistLessonBody(body);
    await applyPendingLessonLinks(saved, body);
    const wasNew = lessonFormOpenedAsNew;
    resetLessonEditState();
    clearLessonForm(); await refresh();
    toast(wasNew ? "Stunde gespeichert." : "Stunde aktualisiert.");
  } catch (e) { toast(e.message, false); }
}

async function deleteLesson() {
  if (!editingLessonId) return;
  if (!window.confirm("Diese Stunde wirklich löschen?")) return;
  try {
    await SyncEngine.remove("lessons", editingLessonId);
    resetLessonEditState();
    clearLessonForm();
    await refresh();
    toast("Stunde gelöscht.");
  } catch (e) { toast(e.message, false); }
}

async function saveReflect() {
  const lessonIdRaw = $("reflectLesson").value;
  if (!lessonIdRaw) { toast("Bitte eine Stunde wählen.", false); return; }
  const meyer = readMeyerGrid("meyerReflectGrid");
  try {
    // ttFkValue (stundenplan.js, teilt sich den globalen Scope) wrappt eine noch nicht
    // synchronisierte "loc_..."-Stunden-id als $localId-Platzhalter statt sie per Number()
    // zu NaN zu machen — siehe dortiger Kommentar.
    await SyncEngine.create("reflections", {
      lessonId: ttFkValue(lessonIdRaw), meyerIst: meyer.some((v) => v) ? meyer : null, text: $("reflectText").value,
    });
    $("reflectText").value = ""; resetMeyerGrid("meyerReflectGrid");
    await refresh(); toast("Reflexion gespeichert.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- Einstellungen ---------- */
async function loadSettings() {
  try {
    const s = await API.get("/settings");
    const badge = $("apiKeyStatus");
    if (s.apiKeyStatus === "aktiv") {
      badge.className = "badge ok"; badge.textContent = "API-Key aktiv";
      $("apiKeyMeta").textContent = `endet auf …${s.apiKeyLast4} (seit ${s.apiKeySetAt || "?"})`;
    } else {
      badge.className = "badge bad"; badge.textContent = "Kein API-Key hinterlegt";
      $("apiKeyMeta").textContent = "";
    }
    $("apiKeyWarn").classList.toggle("hidden", s.secretConfigured);
    $("saveApiKey").disabled = !s.secretConfigured;
    // U21: Google-Kalender-Status übernehmen.
    state.google = { keySet: s.googleKeySet, calendarId: s.googleCalendarId, lastSync: s.googleLastSync };
    $("googleKeyWarn").classList.toggle("hidden", s.secretConfigured);
    $("saveGoogleKey").disabled = !s.secretConfigured;
    if (s.googleCalendarId && !$("googleCalendarIdInput").value) $("googleCalendarIdInput").value = s.googleCalendarId;
    applyGoogleStatus();
    // M1a: Schulmanager-ICS-Status übernehmen.
    $("schulmanagerWarn").classList.toggle("hidden", s.secretConfigured);
    $("saveSchulmanagerUrl").disabled = !s.secretConfigured;
    applySchulmanagerStatus(s);
    state.aiActive = s.apiKeyStatus === "aktiv";
    applyAiGating(state.aiActive);
    applyAppearance(s.theme, s.darkMode, s.font);
    renderAiUsage();
    refreshLogoPreview();
    $("deployTime").textContent = s.deployTime || "unbekannt";
    $("deployCommit").textContent = s.deployCommit || "unbekannt";
  } catch (e) { toast(e.message, false); }
}

/* ---------- Google-Kalender-Sync (U21) ---------- */
// Status auf beide Karten anwenden (Einstellungen + Planungskalender). Nutzt state.google.
function applyGoogleStatus() {
  const g = state.google || {};
  const badge = $("googleKeyStatus");
  if (badge) {
    badge.className = g.keySet ? "badge ok" : "badge bad";
    badge.textContent = g.keySet ? "Verbunden" : "Nicht verbunden";
    const meta = $("googleKeyMeta");
    if (meta) meta.textContent = g.keySet && g.lastSync ? `zuletzt synchronisiert: ${g.lastSync}` : "";
  }
  const cBadge = $("calGoogleStatus");
  if (cBadge) {
    cBadge.className = g.keySet ? "badge ok" : "badge bad";
    if (!g.keySet) cBadge.textContent = "Nicht verbunden";
    else cBadge.textContent = g.lastSync ? `verbunden – zuletzt ${g.lastSync}` : "verbunden";
  }
  const cBtn = $("calGoogleSyncBtn");
  // F5: Google-Kalender-Sync ist wie die KI-Funktionen zwingend online (externer Service).
  if (cBtn) cBtn.disabled = !g.keySet || navigator.onLine === false;
}

// Status sicherstellen, wenn der Kalender geöffnet wird, ohne dass zuvor die Einstellungen liefen.
async function ensureGoogleStatus() {
  if (state.google) { applyGoogleStatus(); return; }
  try {
    const s = await API.get("/settings");
    state.google = { keySet: s.googleKeySet, calendarId: s.googleCalendarId, lastSync: s.googleLastSync };
  } catch (_) { /* Status bleibt „nicht verbunden" */ }
  applyGoogleStatus();
}

/* ---------- Auto-Sync (U24): A) beim Kalender-Öffnen  B) periodisch, solange App offen ---------- */
let googleSyncing = false;          // verhindert überlappende Syncs (manuell + automatisch)
let googleLastAutoSync = 0;         // Zeitstempel des letzten Auto-Syncs (Drosselung bei A)
let googleAutoTimer = null;         // Intervall-Handle (B)
const GOOGLE_AUTO_INTERVAL_MS = 10 * 60 * 1000;  // B: alle 10 Minuten
const GOOGLE_AUTO_THROTTLE_MS = 2 * 60 * 1000;   // A: nicht öfter als alle 2 Minuten beim Öffnen

// Stiller Hintergrund-Sync: kein Erfolgs-Toast, keine Fehlermeldung (der manuelle Button
// meldet Fehler weiterhin). Neu gezeichnet wird nur bei `rerender` UND tatsächlicher Änderung,
// damit laufende Eingaben in anderen Ansichten nicht überschrieben werden.
async function autoSyncGoogle(rerender) {
  if (googleSyncing) return;
  if (document.visibilityState === "hidden") return;  // im Hintergrund-Tab nicht syncen
  if (navigator.onLine === false) return;              // F5: offline gar nicht erst versuchen
  await ensureGoogleStatus();
  if (!state.google || !state.google.keySet) return;  // nur mit hinterlegtem Schlüssel
  googleSyncing = true;
  const cBadge = $("calGoogleStatus");
  if (cBadge) cBadge.textContent = "synchronisiere …";
  try {
    const r = await API.post("/calendar/google/sync");
    googleLastAutoSync = Date.now();
    state.google = null;
    await ensureGoogleStatus();
    if (rerender && (r.pulled + r.deleted) > 0) await refresh();
  } catch (_) {
    /* still bleiben */
  } finally {
    googleSyncing = false;
    applyGoogleStatus();
  }
}

// A: beim Öffnen des Kalenders synchronisieren (gedrosselt, mit Neuzeichnen erlaubt).
function maybeAutoSyncOnOpen() {
  if (Date.now() - googleLastAutoSync < GOOGLE_AUTO_THROTTLE_MS) return;
  autoSyncGoogle(true);
}

// B: periodischen Auto-Sync starten (einmalig; self-guard auf Schlüssel/Sichtbarkeit).
function startGoogleAutoSync() {
  if (googleAutoTimer) clearInterval(googleAutoTimer);
  googleAutoTimer = setInterval(() => {
    // Neu zeichnen nur, wenn der Kalender gerade sichtbar ist – sonst nur stiller DB-Abgleich.
    const onCal = !$("kalender").classList.contains("hidden");
    autoSyncGoogle(onCal);
  }, GOOGLE_AUTO_INTERVAL_MS);
}

async function saveGoogleKey() {
  const keyJson = $("googleKeyInput").value.trim();
  const calendarId = $("googleCalendarIdInput").value.trim();
  if (!keyJson) { toast("Bitte den JSON-Schlüssel einfügen.", false); return; }
  if (!calendarId) { toast("Bitte die Kalender-ID eintragen.", false); return; }
  try {
    await API.put("/settings/google-key", { keyJson, calendarId });
    $("googleKeyInput").value = "";  // Schlüssel nicht im Formular stehen lassen
    await loadSettings();
    toast("Google-Kalender verbunden.");
  } catch (e) { toast(e.message, false); }
}

async function removeGoogleKey() {
  try {
    await API.del("/settings/google-key");
    $("googleCalendarIdInput").value = "";
    await loadSettings();
    toast("Google-Verbindung entfernt.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- M1a: Schulmanager-Online-ICS-Link (Einstellungen) ---------- */
function applySchulmanagerStatus(s) {
  const badge = $("schulmanagerStatus");
  if (!badge) return;
  badge.className = s.schulmanagerIcalSet ? "badge ok" : "badge bad";
  badge.textContent = s.schulmanagerIcalSet ? "Verbunden" : "Nicht verbunden";
  const meta = $("schulmanagerMeta");
  if (meta) meta.textContent = s.schulmanagerIcalSet && s.schulmanagerLastSync ? `zuletzt abgerufen: ${s.schulmanagerLastSync}` : "";
}

async function saveSchulmanagerUrl() {
  const url = $("schulmanagerUrlInput").value.trim();
  if (!url) { toast("Bitte den ICS-Link einfügen.", false); return; }
  try {
    await API.put("/settings/schulmanager-ical", { url });
    $("schulmanagerUrlInput").value = "";  // Link nicht im Formular stehen lassen (Geheimnis)
    await loadSettings();
    refreshSchulmanagerChanges();
    toast("Schulmanager verbunden.");
  } catch (e) { toast(e.message, false); }
}

async function removeSchulmanagerUrl() {
  try {
    await API.del("/settings/schulmanager-ical");
    await loadSettings();
    refreshSchulmanagerChanges();
    toast("Schulmanager-Verbindung entfernt.");
  } catch (e) { toast(e.message, false); }
}

async function syncGoogle() {
  if (googleSyncing) return;        // läuft bereits ein (Auto-)Sync → nicht doppelt anstoßen
  googleSyncing = true;
  const btn = $("calGoogleSyncBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Synchronisiere …"; }
  try {
    const r = await API.post("/calendar/google/sync");
    googleLastAutoSync = Date.now();  // zählt auch als jüngster Sync für die A-Drosselung
    state.google = null;            // Status inkl. neuem last_sync frisch laden
    await ensureGoogleStatus();
    await refresh();                // Kalender mit übernommenen Terminen neu zeichnen
    toast(`Sync fertig: ${r.pushed} hoch, ${r.pulled} runter, ${r.deleted} gelöscht.`);
  } catch (e) {
    toast(e.message, false);
  } finally {
    googleSyncing = false;
    if (btn) btn.textContent = "Mit Google synchronisieren";
    applyGoogleStatus();
  }
}

/* ---------- Branding: Profilbild & Logo (M12/U10) ---------- */
function refreshFavicon() {
  const link = document.getElementById("faviconLink");
  if (link) link.href = `/favicon.ico?t=${Date.now()}`;
}

function refreshLogoPreview() {
  const img = $("logoPreview");
  if (!img) return;
  img.onerror = () => { img.onerror = null; img.src = TRANSPARENT_PX; };
  img.src = `/api/settings/logo?t=${Date.now()}`;
}

async function uploadAvatar(file) {
  if (!file) return;
  if (!state.user) { toast("Nicht angemeldet.", false); return; }
  const fd = new FormData();
  fd.append("file", file);
  try {
    const u = await API.upload(`/users/${state.user.id}/avatar`, fd);
    state.user.avatarPath = u.avatarPath;
    $("avatarImg").src = `/api/users/${state.user.id}/avatar?t=${Date.now()}`;
    toast("Profilbild aktualisiert.");
  } catch (e) { toast(e.message, false); }
}

async function uploadLogo(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    await API.upload("/settings/logo", fd);
    refreshLogoPreview();
    refreshFavicon();
    toast("Logo gespeichert.");
  } catch (e) { toast(e.message, false); }
}

async function removeLogo() {
  try {
    await API.del("/settings/logo");
    refreshLogoPreview();
    refreshFavicon();
    toast("Logo entfernt.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- Darstellung (Themes/Schriftart, U9) ---------- */
// Themebare Farbe aus CSS-Variable lesen, damit JS-Inline-Farben mit dem Theme wechseln.
function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
function timelineColors() {
  const fb = ["#16a34a", "#eab308", "#f97316", "#0ea5e9", "#22c55e", "#a855f7"];
  return fb.map((hex, i) => cssVar(`--tl-${i + 1}`, hex));
}

const SEASONS = [
  { key: "fruehling", label: "Frühling", dots: ["#16a34a", "#a3e635", "#eab308"] },
  { key: "sommer", label: "Sommer", dots: ["#0891b2", "#22d3ee", "#f59e0b"] },
  { key: "herbst", label: "Herbst", dots: ["#ea580c", "#ca8a04", "#7c2d12"] },
  { key: "winter", label: "Winter", dots: ["#2563eb", "#7dd3fc", "#1e293b"] },
];
const SEASON_KEYS = SEASONS.map((s) => s.key);

// Aktuelle Auswahl auf <html> anwenden + Hero-Tag/Steuerung synchronisieren.
function applyAppearance(theme, darkMode, font) {
  const t = SEASON_KEYS.includes(theme) ? theme : "fruehling";
  const f = font === "standard" ? "standard" : "verspielt";
  const dark = darkMode === true || darkMode === 1 || darkMode === "1";
  state.appearance = { theme: t, darkMode: dark, font: f };
  const root = document.documentElement;
  root.setAttribute("data-theme", t);
  root.setAttribute("data-dark", dark ? "1" : "0");
  root.setAttribute("data-font", f);
  syncAppearanceControls();
}

function buildThemeSwatches() {
  const wrap = $("themeSwatches");
  if (!wrap || wrap.dataset.built === "1") return;
  wrap.innerHTML = SEASONS.map((s) =>
    `<button type="button" class="theme-swatch" data-theme="${esc(s.key)}">` +
    `<span class="dots">${s.dots.map((c) => `<span class="dot" style="background:${esc(c)}"></span>`).join("")}</span>` +
    `<span>${esc(s.label)}</span></button>`
  ).join("");
  wrap.dataset.built = "1";
  wrap.querySelectorAll(".theme-swatch").forEach((btn) => {
    btn.onclick = () => saveAppearance({ theme: btn.dataset.theme });
  });
}

// Aktive Zustände der Swatches/Toggles an state.appearance angleichen.
function syncAppearanceControls() {
  const a = state.appearance || { theme: "fruehling", darkMode: false, font: "verspielt" };
  document.querySelectorAll("#themeSwatches .theme-swatch").forEach((b) =>
    b.classList.toggle("active", b.dataset.theme === a.theme));
  document.querySelectorAll("#darkToggle button").forEach((b) =>
    b.classList.toggle("active", (b.dataset.dark === "1") === a.darkMode));
  document.querySelectorAll("#fontToggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.font === a.font));
}

// Teil-Update: Vorschau sofort anwenden, dann persistieren.
async function saveAppearance(patch) {
  const cur = state.appearance || { theme: "fruehling", darkMode: false, font: "verspielt" };
  const next = { theme: cur.theme, darkMode: cur.darkMode, font: cur.font, ...patch };
  applyAppearance(next.theme, next.darkMode, next.font);  // sofortige Vorschau
  try {
    await API.put("/settings/appearance", {
      theme: next.theme, darkMode: next.darkMode, font: next.font,
    });
  } catch (e) {
    toast(e.message, false);
    applyAppearance(cur.theme, cur.darkMode, cur.font);   // Rollback bei Fehler
  }
}

function wireAppearance() {
  buildThemeSwatches();
  document.querySelectorAll("#darkToggle button").forEach((btn) => {
    btn.onclick = () => saveAppearance({ darkMode: btn.dataset.dark === "1" });
  });
  document.querySelectorAll("#fontToggle button").forEach((btn) => {
    btn.onclick = () => saveAppearance({ font: btn.dataset.font });
  });
}

/* ---------- ASUV ---------- */
const ASUV_FIELDS = [
  ["bedingung_org", "bedingungOrg"], ["bedingung_lern", "bedingungLern"], ["bedingung_einordnung", "bedingungEinordnung"],
  ["ziele", "ziele"], ["sachanalyse", "sachanalyse"], ["quellen", "quellen"],
  ["didaktisch", "didaktisch"], ["reduktion", "reduktion"], ["methodisch", "methodisch"], ["anhang", "anhang"],
  ["schule", "schule"], ["pruefer", "pruefer"], ["deckblatt_datum", "deckblattDatum"],
];
const ASUV_CHECKS = [
  ["Bedingungsanalyse", "Relevante organisatorisch-technische Bedingungen dargestellt?"],
  ["Bedingungsanalyse", "Lernvoraussetzungen der Schüler:innen beschrieben?"],
  ["Ziele", "Haupt- und Teilziele formuliert und überprüfbar?"],
  ["Ziele", "Lernziele passen zu den geplanten Phasen?"],
  ["Sachanalyse", "Lerngegenstand fachwissenschaftlich dargestellt, Fachliteratur einbezogen?"],
  ["Didaktik", "Wahl des Lerngegenstands begründet, Legitimation durch Lehrplan?"],
  ["Didaktik", "Didaktische Reduktion begründet?"],
  ["Didaktik", "Faktoren aus Kapitel 1 werden in Kapitel 4 wieder aufgegriffen?"],
  ["Methodik", "Methoden geeignet für die Lernziele und begründet?"],
  ["Verlauf", "Zeitlicher, inhaltlicher und methodisch-didaktischer Verlauf stimmig?"],
  ["Formalien", "Deckblatt und Inhaltsverzeichnis mit Seitenzahlen vorhanden?"],
  ["Formalien", "Quellen normgerecht, Materialanhang vollständig?"],
  ["Formalien", "Arial 11, Zeilenabstand 1,5, Blocksatz eingehalten?"],
  ["Formalien", "Unterschriebene Selbständigkeitserklärung beigelegt?"],
];
let asuvLessonId = null;
let asuvSaved = false;   // vom zuletzt geladenen Entwurf — steuert create vs. update beim Speichern

function renderAsuvLessonSelect() {
  const sel = $("asuvLesson");
  if (!sel) return;
  sel.innerHTML = state.lessons.map((l) => `<option value="${l.id}">${esc(l.title)} (${esc(l.subject)} ${esc(l.grade || "")})</option>`).join("");
}

async function loadAsuv(lessonId) {
  // ASUV-Entwürfe hängen fest an einer bereits existierenden Stunde (asuv_drafts.lesson_id
  // ist eine FK, kein eigenständig anlegbarer Datensatz) — eine noch nicht synchronisierte
  // Stunde ("loc_..."-id) hat serverseitig noch keine Zeile, an die sich ein Entwurf hängen
  // ließe. Number() auf einer solchen id wäre NaN statt eines klaren Hinweises.
  if (String(lessonId).startsWith("loc_")) {
    toast("Diese Stunde ist noch nicht synchronisiert – bitte online abwarten.", false);
    return;
  }
  asuvLessonId = Number(lessonId);
  if (!asuvLessonId) return;
  syncHash("asuv");
  $("asuvLesson").value = String(asuvLessonId);
  const lesson = state.lessons.find((l) => l.id === asuvLessonId);
  $("asuvHeadline").textContent = "ASUV-Entwurf: " + (lesson ? lesson.title : "");
  try {
    // Ob als create oder update gespeichert wird, hängt davon ab, ob überhaupt schon ein
    // Datensatz existiert — nicht vom a.saved-Feld: eine gerade erst offline/optimistisch
    // angelegte Zeile hat dieses Feld (noch) nicht (es ist Teil der Server-Antwort, nicht des
    // gesendeten Payloads), wäre also fälschlich falsy.
    const fromLocal = await SyncEngine.materialize("asuv_drafts").then(
      (all) => all.find((x) => x.id === asuvLessonId)
    );
    const a = fromLocal || await API.get(`/lessons/${asuvLessonId}/asuv`);
    asuvSaved = !!fromLocal || !!a.saved;
    ASUV_FIELDS.forEach(([id, key]) => { $(`asuv_${id}`).value = a[key] || ""; });
    $("asuvBiboxHint").style.display = a.biboxEmpty ? "block" : "none";
    // WTH: fachspezifische Struktur-Hinweise (Leitfaden Fischer) nur bei WTH-Stunden einblenden.
    const isWth = (lesson && lesson.subject || "").toUpperCase() === "WTH";
    document.querySelectorAll(".asuv-wth-hint").forEach((el) => el.classList.toggle("hidden", !isWth));
    const cl = $("asuvChecklist");
    cl.innerHTML = "";
    ASUV_CHECKS.forEach((item, i) => {
      const div = document.createElement("div");
      div.className = "todo-item";
      div.innerHTML = `<input type="checkbox" data-check="${i}" ${a.checks && a.checks[i] ? "checked" : ""}>` +
        `<span class="todo-src system">${esc(item[0])}</span><span style="flex:1">${esc(item[1])}</span>`;
      cl.appendChild(div);
    });
    if (lesson) {
      const ziele = lesson.lernziele || [];
      const zielMark = (p) => ziele
        .filter((z) => z.kind === "fein" && z.phaseSortOrder != null && String(z.phaseSortOrder) === String(p.sortOrder))
        .map((z) => `<br><span style="${ZIEL_BADGE}">🎯 ${esc((z.text || "").slice(0, 45))}${(z.text || "").length > 45 ? "…" : ""}</span>`)
        .join("");
      $("asuvPhases").innerHTML = (lesson.phases || []).map((p) =>
        `<div class="phase"><strong>${esc(p.phaseName)}</strong> (${esc(p.minutes == null ? "–" : p.minutes)} Min., ${esc(p.socialForm || "–")})<br>` +
        `<span class="small muted">Methode: ${esc(p.method || "–")} – Material: ${esc(p.material || "–")}</span><br>` +
        `<span class="small">L: ${esc(p.teacherActivity || "–")} · S: ${esc(p.studentActivity || "–")}</span>${zielMark(p)}</div>`).join("")
        || '<p class="muted small">Noch keine Phasen erfasst.</p>';
      $("asuvBibox").textContent = lesson.bibox && lesson.bibox.werk
        ? `Lehrwerk: ${lesson.bibox.werk} – ${lesson.bibox.seite || ""} ${lesson.bibox.notiz || ""}`
        : "Keine Lehrbuch-Referenz hinterlegt.";
      // Freie Stunde (kein Lernbereich): KI-Einordnung anbieten; der Button füllt nur ein leeres Feld.
      const box = $("asuvEinordnungBox");
      if (box) {
        box.classList.toggle("hidden", lesson.lernbereichId != null);
        $("asuvEinordnungResult").textContent = "";
      }
    }
  } catch (e) { toast(e.message, false); }
}

async function saveAsuv() {
  if (!asuvLessonId) { toast("Bitte eine Stunde wählen.", false); return; }
  const body = {};
  ASUV_FIELDS.forEach(([id, key]) => { body[key] = $(`asuv_${id}`).value; });
  const checks = {};
  $("asuvChecklist").querySelectorAll("input[type=checkbox]").forEach((cb) => { checks[cb.dataset.check] = cb.checked; });
  body.checks = checks;
  try {
    if (asuvSaved) {
      await SyncEngine.update("asuv_drafts", asuvLessonId, body);
    } else {
      await SyncEngine.create("asuv_drafts", { ...body, lessonId: asuvLessonId });
      asuvSaved = true;
    }
    toast("ASUV gespeichert.");
  } catch (e) { toast(e.message, false); }
}

function exportAsuv(fmt) {
  if (!asuvLessonId) { toast("Bitte eine Stunde wählen.", false); return; }
  const a = document.createElement("a");
  a.href = `/api/lessons/${asuvLessonId}/asuv/export?format=${fmt}`;
  a.target = "_blank"; // sonst navigiert die SPA weg (Browser-PDF-Viewer ignoriert Content-Disposition: attachment)
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ---------- KI (Meilenstein 7) ---------- */
function applyAiGating(active) {
  // F5: KI-Funktionen brauchen zwingend die externe Anthropic-API — offline zusätzlich
  // ausgrauen (unabhängig vom API-Key-Status), damit kein Klick einen garantiert
  // fehlschlagenden Request auslöst.
  const offline = navigator.onLine === false;
  const effectiveActive = active && !offline;
  ["aiPlanBtn", "stoffAiBtn", "seqAiBtn", "asuvAiBtn", "aiLernzieleBtn", "asuvEinordnungBtn", "stundeEinordnungBtn", "spAiBtn", "tafelbildBtn"].forEach((id) => {
    const b = $(id);
    if (b) {
      b.disabled = !effectiveActive;
      b.title = effectiveActive ? "" : offline ? "Offline nicht verfügbar" : "Kein API-Key hinterlegt – in den Einstellungen eintragen";
    }
  });
}
async function refreshAiStatus() {
  try {
    const s = await API.get("/settings");
    state.aiActive = s.apiKeyStatus === "aktiv";
    applyAppearance(s.theme, s.darkMode, s.font);  // Theme/Schriftart beim Start anwenden
  }
  catch (e) { state.aiActive = false; }
  applyAiGating(state.aiActive);
}
async function renderAiUsage() {
  const wrap = $("aiUsage");
  if (!wrap) return;
  try {
    const u = await API.get("/ai/usage");
    if (!u.rows.length) { wrap.innerHTML = '<p class="muted small">Noch keine KI-Nutzung.</p>'; return; }
    const rows = u.rows.map((r) =>
      `<div class="file-chip"><span>${esc(r.month)} · ${esc(r.model)}</span>` +
      `<span class="small muted">${r.inputTokens + r.outputTokens} Tokens · ~$${r.costUsd.toFixed(4)}</span></div>`).join("");
    wrap.innerHTML = `<p class="small"><strong>Gesamt: ~$${u.totalUsd.toFixed(4)}</strong></p>` + rows;
  } catch (e) { /* ignore */ }
}

async function aiLessonSuggest() {
  const ideas = $("lessonIdeas").value.trim();
  const title = $("lessonTitle").value.trim();
  if (!ideas && !title) { toast("Bitte Ideen im Ideenfeld oder einen Titel eintragen.", false); return; }
  const btn = $("aiPlanBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ generiere …";
  try {
    const res = await API.post("/ai/lesson-suggestion", {
      ideas, title,
      subject: $("lessonSubject").value, grade: Number($("lessonGrade").value),
      lessonType: $("lessonType").value,
      classId: $("lessonClass").value ? Number($("lessonClass").value) : null,
      date: $("lessonDate").value || null,
      durationMinutes: Number($("lessonDuration").value) || 45,
    });
    const s = res.suggestion || {};
    if (s.title && !$("lessonTitle").value) $("lessonTitle").value = s.title;
    if (s.klafki) {
      $("klafki1").value = s.klafki.gegenwart || ""; $("klafki2").value = s.klafki.zukunft || "";
      $("klafki3").value = s.klafki.exemplarisch || ""; $("klafki4").value = s.klafki.zugang || "";
      $("klafki5").value = s.klafki.struktur || "";
    }
    if (Array.isArray(s.meyerPlan)) setMeyerGrid("meyerPlanGrid", s.meyerPlan);
    if (Array.isArray(s.phases) && s.phases.length) setPhasesFromLesson(s.phases);
    toast(res.cached ? "KI-Vorschlag (aus Cache) eingefügt." : "KI-Vorschlag eingefügt – bitte prüfen.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; btn.textContent = label; }
}

// Tafelbild (U31): rendert das KI-Ergebnis als Kacheln (flex-wrap – die KI entscheidet frei,
// wie viele Blöcke sinnvoll sind, kein fester Spaltenzwang), hervorgehobene Blöcke als Merksatz-Kasten.
// Reines Rendering des KI-Tafelbilds als HTML-String (ohne DOM-Seiteneffekte) – auch vom
// Stunden-Detail-Modal genutzt. Leerer String, wenn kein Inhalt.
function tafelbildBoardHtml(tb) {
  tb = tb || { titel: "", bloecke: [] };
  if (!(tb.titel || (tb.bloecke && tb.bloecke.length))) return "";
  const title = tb.titel ? `<div class="tafelbild-title">${esc(tb.titel)}</div>` : "";
  const blocks = (tb.bloecke || []).map((b) => {
    const head = b.ueberschrift ? `<div class="tafelbild-block-head">${esc(b.ueberschrift)}</div>` : "";
    const pts = (b.punkte || []).map((p) => `<li>${esc(p)}</li>`).join("");
    return `<div class="tafelbild-block${b.hervorgehoben ? " hervorgehoben" : ""}">${head}<ul>${pts}</ul></div>`;
  }).join("");
  return `${title}<div class="tafelbild-blocks">${blocks}</div>`;
}

function renderTafelbild() {
  const board = $("tafelbildBoard");
  if (board) {
    const html = tafelbildBoardHtml(lessonTafelbild);
    board.classList.toggle("hidden", !html);
    board.innerHTML = html;
  }
  renderTafelbildBild();
}

// Eigenes Tafelbild-Foto im Bearbeiten-Formular (Vorschau + „entfernen").
function renderTafelbildBild() {
  const wrap = $("tafelbildBildWrap");
  if (!wrap) return;
  const has = lessonTafelbildBildId != null;
  wrap.classList.toggle("hidden", !has);
  if (has) $("tafelbildBildImg").src = `/api/materials/${lessonTafelbildBildId}/download`;
}

async function aiTafelbildSuggest() {
  const eingabe = $("tafelbildEingabe").value.trim();
  if (!eingabe) { toast("Bitte eintragen, was an die Tafel soll.", false); return; }
  const btn = $("tafelbildBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ generiere …";
  try {
    const res = await API.post("/ai/tafelbild", {
      eingabe, subject: $("lessonSubject").value, grade: Number($("lessonGrade").value) || null,
      title: $("lessonTitle").value.trim() || null,
    });
    lessonTafelbild = res.suggestion || { titel: "", bloecke: [] };
    renderTafelbild();
    scheduleLessonAutosave();
    toast(res.cached ? "Tafelbild (aus Cache) eingefügt." : "Tafelbild eingefügt – bitte prüfen.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; btn.textContent = label; }
}

// Eigenes Tafelbild-Foto: als normales Material hochladen (mit lessonId verknüpft) und die
// Material-id in der Stunde hinterlegen. Braucht eine bereits gespeicherte Stunde.
async function uploadTafelbildBild() {
  const f = $("tafelbildBildFile").files[0];
  if (!f) { toast("Bitte ein Bild wählen.", false); return; }
  if (!editingLessonId) {
    toast("Bitte die Stunde zuerst speichern – danach lässt sich ein Bild hochladen.", false);
    return;
  }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("subject", $("lessonSubject").value);
  const grade = Number($("lessonGrade").value);
  if (grade) fd.append("grade", grade);
  fd.append("lessonId", editingLessonId);
  const btn = $("tafelbildBildUpload"); btn.disabled = true;
  try {
    const m = await API.upload("/materials/upload", fd);
    lessonTafelbildBildId = m.id;
    await SyncEngine.update("lessons", editingLessonId, { tafelbildBildMaterialId: m.id });
    renderTafelbildBild();
    $("tafelbildBildFile").value = "";
    toast("Bild hochgeladen.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; }
}

async function removeTafelbildBild() {
  lessonTafelbildBildId = null;
  renderTafelbildBild();
  if (editingLessonId) {
    try { await SyncEngine.update("lessons", editingLessonId, { tafelbildBildMaterialId: null }); }
    catch (e) { toast(e.message, false); }
  }
}

async function aiLernzieleSuggest() {
  if (!editingLessonId) {
    toast("Bitte die Stunde zuerst speichern – Lernziele werden aus den gespeicherten Phasen und dem Lernbereich abgeleitet.", false);
    return;
  }
  const btn = $("aiLernzieleBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ generiere …";
  try {
    const res = await API.post(`/ai/lernziele/${editingLessonId}`, {});
    const ziele = (res.suggestion && res.suggestion.ziele) || [];
    // Vorschläge anhängen – vom Nutzer angelegte Ziele bleiben unverändert erhalten.
    ziele.forEach((z) => lessonZiele.push({
      kind: z.kind === "grob" ? "grob" : "fein", text: z.text || "",
      bloomStufe: z.bloomStufe || null, phaseSortOrder: z.phaseSortOrder == null ? null : Number(z.phaseSortOrder),
    }));
    renderLernziele();
    toast(res.cached ? "KI-Lernziele (aus Cache) angehängt – bitte prüfen." : "KI-Lernziele angehängt – bitte prüfen und speichern.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; btn.textContent = label; }
}

async function aiAsuvSuggest() {
  if (!asuvLessonId) { toast("Bitte eine Stunde wählen.", false); return; }
  const btn = $("asuvAiBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ Wird ausformuliert…";
  const startedFor = asuvLessonId; // Stunde merken – Nutzer kann während des Wartens wechseln
  try {
    // Hintergrund-Job mit Polling (Cloudflare-Timeout-sicher).
    const res = await API.aiJob(`/ai/asuv/${startedFor}`, {},
      (sec) => { btn.textContent = `✨ Wird ausformuliert… ${sec} s`; });
    if (asuvLessonId !== startedFor) {
      toast("Stunde wurde gewechselt – KI-Vorschlag verworfen. Bitte erneut ausformulieren.", false);
      return;
    }
    const s = res.suggestion || {};
    // Nur leere Felder befüllen – vom Nutzer Ausgefülltes nie überschreiben.
    ASUV_FIELDS.forEach(([id, key]) => {
      const el = $(`asuv_${id}`);
      if (s[key] && !el.value.trim()) el.value = s[key];
    });
    toast(res.cached ? "ASUV-Vorschlag (aus Cache)." : "ASUV ausformuliert – bitte prüfen.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; btn.textContent = label; }
}

/* ---------- Einordnung freier Stunden (M12/U7) ---------- */
function formatEinordnung(s) {
  const code = [s.lernbereichCode, s.lernbereichTitle].filter(Boolean).join(" – ");
  return [code ? `Lernbereich: ${code}` : "", s.lernzielHinweis ? `Lernziel: ${s.lernzielHinweis}` : "",
          s.begruendung ? `Begründung: ${s.begruendung}` : ""].filter(Boolean).join("\n");
}
// Holt den KI-Einordnungsvorschlag für eine freie Stunde und liefert das Suggestion-Objekt.
async function fetchEinordnung(lessonId, btn) {
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ ordne ein …";
  try {
    const res = await API.post(`/ai/einordnung/${lessonId}`, {});
    if (res.cached) toast("Einordnung (aus Cache) – bitte prüfen.");
    return res.suggestion || {};
  } finally { btn.disabled = false; btn.textContent = label; }
}
async function asuvEinordnungSuggest() {
  if (!asuvLessonId) { toast("Bitte eine Stunde wählen.", false); return; }
  const btn = $("asuvEinordnungBtn");
  try {
    const s = await fetchEinordnung(asuvLessonId, btn);
    const ta = $("asuv_bedingung_einordnung");
    const text = formatEinordnung(s);
    const out = $("asuvEinordnungResult");
    if (out) out.textContent = text;                 // Vorschlag immer sichtbar machen
    if (!ta.value.trim()) { ta.value = text; toast("Einordnung eingetragen – bitte prüfen."); }
    else { toast("Feld schon ausgefüllt – Vorschlag unten angezeigt, nicht überschrieben."); }
  } catch (e) { toast(e.message, false); }
}
async function stundeEinordnungSuggest() {
  if (!editingLessonId) { toast("Bitte die Stunde zuerst speichern.", false); return; }
  const btn = $("stundeEinordnungBtn"), out = $("stundeEinordnungResult");
  try {
    const s = await fetchEinordnung(editingLessonId, btn);
    out.textContent = formatEinordnung(s);
  } catch (e) { toast(e.message, false); }
}

/* ---------- Schüleransicht / Präsentationsmodus (M12 U8) ----------
   Read-only Ansicht für Beamer/Tafel mit drei Unteransichten:
   Jahresplan, Lernbereichsplanung, Unterrichtsablauf heute. */
const PRAESENT_COLORS = ["#16a34a", "#eab308", "#f97316", "#0ea5e9", "#22c55e", "#a855f7"];
const praesent = { mode: "jahresplan", classId: "", lessonId: null, sequenzStundeId: null, phaseIdx: 0, editMode: false };
// { classId, time } der laut Stundenplan aktuell laufenden/nächsten Stunde heute, FALLS dafür
// noch keine lessons-Zeile existiert – von suggestPraesentLessonId() mitgeführt, treibt den
// "Jetzt planen"-Button im Ablauf-Tab (renderPraesentAblauf).
let praesentTodaySlot = null;
let praesentSeqCache = [];   // aktuell im Lernbereich-Tab angezeigte Sequenzstunden (für Klick -> Ablauf)
// Individuelle Anzeige-Einstellungen für "Unterrichtsablauf heute" (persistiert, gilt auch im
// Vollbild) – nur im Bearbeitungsmodus änderbar.
const praesentAblaufPrefs = (() => {
  try { return { showZiele: true, ...JSON.parse(localStorage.getItem("praesentAblaufPrefs") || "{}") }; }
  catch (e) { return { showZiele: true }; }
})();
function savePraesentAblaufPrefs() {
  try { localStorage.setItem("praesentAblaufPrefs", JSON.stringify(praesentAblaufPrefs)); } catch (e) { /* ignore */ }
}
let praesentToken = 0;   // Guard gegen veraltete async-Renderings (Jahresplan lädt Lernbereiche)

function lessonOptionLabel(l) {
  const dat = l.date ? l.date + " · " : "";
  return `${dat}${l.title} (${l.subject} ${l.grade || ""})`;
}
function todayLessons() {
  const todayStr = isoDate(new Date());
  return state.lessons.filter((l) => l.date === todayStr);
}

// Steuer-Selects befüllen (aus renderAll aufgerufen). Auswahl möglichst beibehalten.
function renderPraesentControls() {
  const clsSel = $("praesentClass");
  if (clsSel) {
    const prev = praesent.classId;
    clsSel.innerHTML = '<option value="">Alle Klassen</option>' +
      state.classes.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.subject)})</option>`).join("");
    clsSel.value = state.classes.some((c) => String(c.id) === String(prev)) ? prev : "";
    praesent.classId = clsSel.value;
  }
  const lesSel = $("praesentLesson");
  if (lesSel) {
    const prev = praesent.lessonId;
    const filtered = praesent.classId
      ? state.lessons.filter((l) => String(l.classId) === String(praesent.classId))
      : state.lessons;
    lesSel.innerHTML = filtered.length
      ? filtered.map((l) => `<option value="${l.id}">${esc(lessonOptionLabel(l))}</option>`).join("")
      : '<option value="">Keine Stunden</option>';
    if (filtered.some((l) => String(l.id) === String(prev))) lesSel.value = String(prev);
    praesent.lessonId = lesSel.value ? Number(lesSel.value) : (filtered[0] ? filtered[0].id : null);
    if (praesent.lessonId != null) lesSel.value = String(praesent.lessonId);
  }
}

// Ermittelt die laut Stundenplan gerade laufende bzw. nächste Stunde (heute, optional auf die
// gewählte Klasse eingeschränkt) und liefert die passende Lesson-ID, sonst die erste Stunde
// des Tages bzw. null. Manuelle Auswahl im Select bleibt jederzeit möglich. Nebenbei wird
// praesentTodaySlot gepflegt: findet sich für die aktuelle/nächste Stundenplan-Stunde heute
// KEINE passende lessons-Zeile, steht dort Klasse+Uhrzeit für den "Jetzt planen"-Button.
async function suggestPraesentLessonId() {
  praesentTodaySlot = null;
  let candidates = todayLessons();
  if (praesent.classId) candidates = candidates.filter((l) => String(l.classId) === String(praesent.classId));
  const fallback = candidates[0] ? candidates[0].id : null;
  const wd = new Date().getDay();
  if (wd < 1 || wd > 5) return fallback;
  try {
    const monday = new Date();
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    const data = await calTtFetch(isoDate(monday));
    const todayStr = isoDate(new Date());
    const day = data.days.find((d) => d.date === todayStr);
    if (!day) return fallback;
    const now = String(new Date().getHours()).padStart(2, "0") + ":" + String(new Date().getMinutes()).padStart(2, "0");
    const items = day.items
      .filter((it) => it.classId != null)
      .filter((it) => !praesent.classId || String(it.classId) === String(praesent.classId))
      .map((it) => { const [start, end] = (it.timeRange || "").split("–"); return { it, start, end }; })
      .filter((x) => x.start && x.end)
      .sort((a, b) => a.start.localeCompare(b.start));
    const pick = items.find((x) => now >= x.start && now < x.end) || items.find((x) => x.start > now);
    const match = pick && candidates.find((l) => l.classId === pick.it.classId);
    if (match) return match.id;
    if (pick) praesentTodaySlot = { classId: pick.it.classId, time: pick.start };
    return fallback;
  } catch (e) { return fallback; }   // kein Stundenplan hinterlegt o. Ä. → Fallback
}

async function applyPraesentLessonSuggestion() {
  const id = await suggestPraesentLessonId();
  if (id == null) {
    // Keine Stunde vorgeschlagen, aber ggf. steht jetzt praesentTodaySlot (aktuelle Stundenplan-
    // Stunde ohne lessons-Zeile) – dafür muss der "Jetzt planen"-Button trotzdem nachgerendert
    // werden, sonst bleibt die vorherige (evtl. veraltete) Anzeige unverändert stehen.
    if (praesentTodaySlot) renderPraesentation();
    return;
  }
  praesent.lessonId = id;
  const sel = $("praesentLesson");
  if (sel) sel.value = String(id);
  praesent.phaseIdx = 0;
  renderPraesentation();
}

function renderPraesentation() {
  praesentToken++;   // laufende async-Renderings entwerten
  const clsSel = $("praesentClass"), lesSel = $("praesentLesson");
  const prevBtn = $("praesentPrevBtn"), nextBtn = $("praesentNextBtn");
  // Steuerungssichtbarkeit je Unteransicht – Klassenfilter überall (schränkt Jahresplan-Klassen
  // bzw. die Stundenauswahl der anderen beiden Modi ein), Stundenauswahl nur außerhalb Jahresplan.
  if (clsSel) clsSel.style.display = "";
  if (lesSel) lesSel.style.display = (praesent.mode === "lernbereich" || praesent.mode === "ablauf") ? "" : "none";
  const showPhaseNav = praesent.mode === "ablauf";
  if (prevBtn) prevBtn.style.display = showPhaseNav ? "" : "none";
  if (nextBtn) nextBtn.style.display = showPhaseNav ? "" : "none";
  const editBtn = $("praesentEditBtn");
  if (editBtn) {
    // Bearbeiten-Button nur im Ablauf-Tab, nie im Vollbild, und nur wenn eine echte
    // Unterrichtsstunde verknüpft ist (bei einer noch nicht angelegten Sequenzstunde gibt es
    // nichts zu bearbeiten).
    const showEditBtn = showPhaseNav && !isPraesentFullscreen() && praesent.lessonId != null;
    editBtn.style.display = showEditBtn ? "" : "none";
    editBtn.classList.toggle("active", praesent.editMode);
    editBtn.textContent = praesent.editMode ? "Fertig" : "Bearbeiten";
  }
  if (!showPhaseNav || isPraesentFullscreen()) praesent.editMode = false;
  document.querySelectorAll(".praesent-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.praesent === praesent.mode));

  if (praesent.mode === "jahresplan") renderPraesentJahresplan();
  else if (praesent.mode === "lernbereich") renderPraesentLernbereich();
  else renderPraesentAblauf();
}

async function renderPraesentJahresplan() {
  const stage = $("praesentStage");
  if (!stage) return;
  const token = praesentToken;
  const classes = state.classes.filter((c) => c.visibleInCalendar !== false);
  if (!classes.length) {
    stage.innerHTML = '<h2 class="praesent-h">Jahresplan</h2><div class="praesent-empty">Noch keine Klassen angelegt.</div>';
    return;
  }
  const shown = praesent.classId ? classes.filter((c) => String(c.id) === String(praesent.classId)) : classes;
  stage.innerHTML = '<h2 class="praesent-h">Jahresplan</h2><div class="praesent-loading">Lernbereiche werden geladen …</div>';
  const rows = [];
  for (const c of shown) {
    let lbs = [];
    try { lbs = await getLernbereiche({ subject: c.subject, grade: c.grade, track: resolveTrack(c.subject, c.grade, c.track) }); }
    catch (e) { /* ignore */ }
    if (token !== praesentToken) return;   // Nutzer hat inzwischen umgeschaltet
    const eff = effectiveBlocks(c.subject, lbs);
    const blocks = eff.map((e, j) =>
      `<div class="praesent-lb" style="background:${PRAESENT_COLORS[j % PRAESENT_COLORS.length]}">` +
      `<span class="praesent-lb-code">${esc(e.code)}</span>` +
      `<span class="praesent-lb-title">${esc(e.title)}</span>` +
      `<span class="praesent-lb-std">${e.richtwertUstd == null ? "?" : e.richtwertUstd} Std.</span></div>`).join("");
    rows.push(`<div class="praesent-jp-row"><div class="praesent-jp-label">${esc(c.name)} · ${esc(c.subject)}</div>` +
      `<div class="praesent-jp-track">${blocks || '<span class="praesent-empty" style="padding:10px;">Kein Plan</span>'}</div></div>`);
  }
  if (token !== praesentToken) return;
  stage.innerHTML = '<h2 class="praesent-h">Jahresplan</h2><div class="praesent-jp">' + rows.join("") + "</div>";
}

// Ermittelt den "aktuellen" Block des aktiven Stoffplans einer Klasse: den, dessen Zeitraum
// heute enthält, sonst den nächsten noch bevorstehenden, sonst schlicht den ersten Block.
function activeBlockForClass(classId) {
  const ap = classId ? state.activePlans[classId] : null;
  if (!ap || !ap.blocks.length) return null;
  const today = isoDate(new Date());
  return ap.blocks.find((b) => b.startDate && b.endDate && b.startDate <= today && today <= b.endDate)
    || ap.blocks.find((b) => b.endDate && b.endDate >= today)
    || ap.blocks[0];
}

// Zeigt die Sequenzstunden (Themen + Grobziel) des aktuellen Lernbereichs-Blocks der gewählten
// Klasse als Kacheln. Klick auf eine Kachel springt in die Ablauf-Ansicht dieser Stunde – mit
// verknüpfter lessons-Zeile (voller Ablauf) oder, falls noch nicht angelegt, als Kurzvorschau.
async function renderPraesentLernbereich() {
  const stage = $("praesentStage");
  if (!stage) return;
  const token = praesentToken;
  const classId = praesent.classId ? Number(praesent.classId) : null;
  const block = classId ? activeBlockForClass(classId) : null;
  if (!classId || !block) {
    praesentSeqCache = [];
    stage.innerHTML = '<div class="praesent-empty">Bitte eine Klasse mit aktivem Stoffverteilungsplan wählen.</div>';
    return;
  }
  const heading = `${esc(block.lbCode || "")} ${esc(block.title || "")}`.trim();
  stage.innerHTML = `<h2 class="praesent-h">${heading}</h2><div class="praesent-loading">Sequenzstunden werden geladen …</div>`;
  let rows = [];
  try { rows = await API.get(`/sequenz-stunden?blockId=${block.id}`); } catch (e) { /* ignore */ }
  if (token !== praesentToken) return;   // Nutzer hat inzwischen umgeschaltet
  praesentSeqCache = rows;
  if (!rows.length) {
    stage.innerHTML = `<h2 class="praesent-h">${heading}</h2>` +
      '<div class="praesent-empty">Für diesen Lernbereich sind noch keine Sequenzstunden geplant.</div>';
    return;
  }
  const tiles = rows.map((s, i) =>
    `<div class="praesent-seq-tile" data-seq-tile="${s.id}">` +
    `<span class="praesent-seq-num">${i + 1}.</span>` +
    `<div class="praesent-seq-body"><span class="praesent-seq-title">${esc(s.title)}</span>` +
    (s.grobziel ? `<span class="praesent-seq-goal">${esc(s.grobziel)}</span>` : "") + `</div></div>`
  ).join("");
  stage.innerHTML = `<h2 class="praesent-h">${heading}</h2><div class="praesent-seq-tiles">${tiles}</div>`;
  stage.querySelectorAll("[data-seq-tile]").forEach((el) => {
    el.onclick = () => {
      const s = praesentSeqCache.find((x) => String(x.id) === el.dataset.seqTile);
      if (!s) return;
      praesent.mode = "ablauf";
      praesent.sequenzStundeId = s.id;
      praesent.lessonId = s.lessonId != null ? s.lessonId : null;
      praesent.phaseIdx = 0;
      const lesSel = $("praesentLesson");
      if (lesSel) lesSel.value = s.lessonId != null ? String(s.lessonId) : "";
      renderPraesentation();
    };
  });
}

let praesentEditZielId = null;   // Lernziel-ID, das gerade inline bearbeitet wird (nur außerhalb Vollbild)

function isPraesentFullscreen() { return !!document.fullscreenElement; }

// Lernziel-Zeile im Ablauf: außerhalb des echten Vollbildmodus gibt es einen kleinen
// „bearbeiten"-Button (Vorbereitung/Kontrolle vor der Präsentation); im Vollbild selbst
// (vor der Klasse) ist nur die reine Anzeige sichtbar.
function renderPraesentGoalRow(z) {
  if (praesentEditZielId === z.id) {
    return `<div class="praesent-step-goal praesent-step-goal-edit">
      <textarea class="praesent-goal-edit-input" data-goal-edit="${z.id}" rows="2">${esc(z.text)}</textarea>
      <div class="praesent-goal-edit-actions">
        <button class="btn small" data-goal-save="${z.id}">Speichern</button>
        <button class="btn small secondary" data-goal-cancel="${z.id}">Abbrechen</button>
      </div>
    </div>`;
  }
  const editBtn = praesent.editMode ?
    `<button class="btn tiny secondary praesent-goal-editbtn" data-goal-edit-open="${z.id}" title="Lernziel bearbeiten">bearbeiten</button>` : "";
  return `<div class="praesent-step-goal">🎯 ${esc(z.text)}${editBtn}</div>`;
}

async function savePraesentZiel(l, zielId) {
  const box = document.querySelector(`[data-goal-edit="${zielId}"]`);
  if (!box) return;
  const text = box.value.trim();
  if (!text) { toast("Lernziel darf nicht leer sein.", false); return; }
  const lernziele = (l.lernziele || []).map((z) => ({
    kind: z.kind, text: z.id === zielId ? text : z.text,
    bloomStufe: z.bloomStufe || null, phaseSortOrder: z.phaseSortOrder, sortOrder: z.sortOrder,
  }));
  try {
    const updated = await SyncEngine.update("lessons", l.id, {
      title: l.title, subject: l.subject, grade: l.grade, lessonType: l.lessonType,
      durationMinutes: l.durationMinutes, classId: l.classId, lernbereichId: l.lernbereichId,
      date: l.date, klafki: l.klafki, meyerPlan: l.meyerPlan, diff: l.diff, selbstLernen: l.selbstLernen,
      bibox: l.bibox, phases: l.phases, lernziele,
    });
    const idx = state.lessons.findIndex((x) => x.id === l.id);
    if (idx !== -1) state.lessons[idx] = updated;
    praesentEditZielId = null;
    renderPraesentAblauf();
    toast("Lernziel aktualisiert.");
  } catch (e) { toast(e.message, false); }
}

// Geplante Zeit einer Phase im Bearbeitungsmodus ändern oder entfernen (minutes = null).
async function savePraesentPhaseMinutes(l, phaseIdx, minutes) {
  const phases = (l.phases || []).map((p, i) => i === phaseIdx ? { ...p, minutes } : p);
  try {
    const updated = await SyncEngine.update("lessons", l.id, {
      title: l.title, subject: l.subject, grade: l.grade, lessonType: l.lessonType,
      durationMinutes: l.durationMinutes, classId: l.classId, lernbereichId: l.lernbereichId,
      date: l.date, klafki: l.klafki, meyerPlan: l.meyerPlan, diff: l.diff, selbstLernen: l.selbstLernen,
      bibox: l.bibox, phases, lernziele: l.lernziele || [],
    });
    const idx = state.lessons.findIndex((x) => x.id === l.id);
    if (idx !== -1) state.lessons[idx] = updated;
    renderPraesentAblauf();
    toast("Geplante Zeit aktualisiert.");
  } catch (e) { toast(e.message, false); }
}

// Klickbarer Hinweis für den Ablauf-Tab: Für die laut Stundenplan aktuelle/nächste Stunde
// heute existiert (noch) keine lessons-Zeile – bietet einen Sprung in die Unterrichtsplanung
// an, statt nur eine andere (ggf. veraltete) "frei gewählte Stunde" anzuzeigen. Nie im
// Vollbildmodus (Schülersicht auf dem Beamer) – das Planen bleibt Sache des Lehrers am Pult.
function praesentPlanButtonHtml() {
  if (!praesentTodaySlot || isPraesentFullscreen()) return "";
  const cls = state.classes.find((c) => c.id === praesentTodaySlot.classId);
  const label = cls ? `${esc(cls.name)} (${esc(cls.subject)})` : "diese Klasse";
  const timeLabel = praesentTodaySlot.time ? `, ${esc(praesentTodaySlot.time)} Uhr` : "";
  return `<div class="praesent-sub" style="color:var(--orange);">
    Für die aktuelle Stunde (${label}${timeLabel}) ist noch keine Unterrichtsstunde geplant.
    <button class="btn tiny" id="praesentPlanBtn">Jetzt planen</button>
  </div>`;
}
function wirePraesentPlanBtn(stage) {
  const btn = stage.querySelector("#praesentPlanBtn");
  if (btn) btn.onclick = planTodayFromPraesent;
}
// Springt aus dem Ablauf-Tab in die Unterrichtsplanung, Klasse+Datum(heute)+Uhrzeit aus
// praesentTodaySlot vorbefüllt – analog planLessonFromCalendarEntry() beim Sprung aus einem
// Kalendertermin.
function planTodayFromPraesent() {
  if (!praesentTodaySlot) return;
  const { classId, time } = praesentTodaySlot;
  showView("stunde");
  clearLessonForm();
  const cls = state.classes.find((c) => c.id === classId);
  if (cls) {
    $("lessonClass").value = String(cls.id);
    if (cls.subject) $("lessonSubject").value = cls.subject;
    if (cls.grade != null) $("lessonGrade").value = String(cls.grade);
  }
  $("lessonDate").value = isoDate(new Date());
  if ($("lessonTime")) $("lessonTime").value = time || "";
  updateLessonLbOptions(null);
  updateSozialformMonotonyHint();
}

function renderPraesentAblauf() {
  const stage = $("praesentStage");
  if (!stage) return;
  const l = state.lessons.find((x) => String(x.id) === String(praesent.lessonId));
  if (!l) {
    // Über die Lernbereich-Kacheln kann eine Sequenzstunde ausgewählt sein, die noch mit
    // keiner lessons-Zeile verknüpft ist – dann gibt es keinen Ablauf, nur eine Kurzvorschau.
    if (praesent.sequenzStundeId != null) {
      const s = praesentSeqCache.find((x) => x.id === praesent.sequenzStundeId);
      if (s) {
        stage.innerHTML =
          `<h2 class="praesent-h">${esc(s.title)}</h2>` +
          '<div class="praesent-sub" style="color:var(--orange);">Diese Sequenzstunde ist noch nicht in der Unterrichtsplanung angelegt.</div>' +
          (s.grobziel
            ? `<div class="praesent-goals"><div class="praesent-goal grob"><span class="praesent-goal-kind">Grobziel</span><span class="praesent-goal-text">${esc(s.grobziel)}</span></div></div>`
            : '<div class="praesent-empty">Für diese Stunde ist noch kein Grobziel hinterlegt.</div>') +
          praesentPlanButtonHtml();
        wirePraesentPlanBtn(stage);
        return;
      }
    }
    stage.innerHTML = '<div class="praesent-empty">Noch keine Stunden geplant. Lege eine Stunde in der Unterrichtsplanung an.</div>' +
      praesentPlanButtonHtml();
    wirePraesentPlanBtn(stage);
    return;
  }
  const phases = l.phases || [];
  const ziele = l.lernziele || [];
  const isToday = l.date === isoDate(new Date());
  const hint = (isToday ? "" :
    '<div class="praesent-sub" style="color:var(--orange);">Diese Stunde ist nicht für heute geplant – frei gewählte Stunde.</div>') +
    praesentPlanButtonHtml();
  if (!phases.length) {
    stage.innerHTML = `<h2 class="praesent-h">${esc(l.title)}</h2>${hint}` +
      '<div class="praesent-empty">Für diese Stunde sind noch keine Phasen erfasst.</div>';
    wirePraesentPlanBtn(stage);
    return;
  }
  if (praesent.phaseIdx >= phases.length) praesent.phaseIdx = phases.length - 1;
  if (praesent.phaseIdx < 0) praesent.phaseIdx = 0;
  const showZiele = praesentAblaufPrefs.showZiele;
  const settingsBar = praesent.editMode ? `<div class="praesent-edit-settings">
    <label class="praesent-edit-check"><input type="checkbox" id="praesentShowZieleCheck" ${showZiele ? "checked" : ""}> Lernziele in dieser Ansicht anzeigen</label>
  </div>` : "";
  const steps = phases.map((p, i) => {
    const active = i === praesent.phaseIdx;
    const cls = "praesent-step" + (active ? " active" : "") + (i < praesent.phaseIdx ? " done" : "");
    const timeMeta = praesent.editMode
      ? `<span class="praesent-time-edit">
          <input type="number" min="0" class="praesent-time-input" data-phase-time="${i}" value="${p.minutes == null ? "" : esc(p.minutes)}" placeholder="Min."> Min.
          ${p.minutes != null ? `<button class="btn tiny secondary" data-phase-time-clear="${i}" title="Geplante Zeit entfernen" aria-label="Geplante Zeit entfernen">×</button>` : ""}
        </span>`
      : (p.minutes != null ? `${esc(p.minutes)} Min.` : null);
    const meta = [
      timeMeta,
      p.socialForm ? esc(p.socialForm) : null,
      p.method ? esc(p.method) : null,
    ].filter(Boolean).join(" · ");
    const stepZiele = showZiele ? ziele
      .filter((z) => z.kind === "fein" && z.phaseSortOrder != null && String(z.phaseSortOrder) === String(p.sortOrder))
      .map((z) => renderPraesentGoalRow(z)).join("") : "";
    const here = active ? '<span class="praesent-here">📍 Wir sind hier</span>' : "";
    return `<div class="${cls}" data-phaseidx="${i}">` +
      `<div class="praesent-step-num">${i + 1}</div>` +
      `<div class="praesent-step-body"><div class="praesent-step-title">${esc(p.phaseName)}${here}</div>` +
      (meta ? `<div class="praesent-step-meta">${meta}</div>` : "") +
      (stepZiele ? `<div class="praesent-step-goals">${stepZiele}</div>` : "") +
      `</div></div>`;
  }).join("");
  stage.innerHTML = `<h2 class="praesent-h">${esc(l.title)}</h2>${hint}${settingsBar}<div class="praesent-steps">${steps}</div>`;
  wirePraesentPlanBtn(stage);
  stage.querySelectorAll("[data-phaseidx]").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest("[data-goal-edit-open],[data-goal-save],[data-goal-cancel],.praesent-goal-edit-input,.praesent-time-edit")) return;
      praesent.phaseIdx = Number(el.dataset.phaseidx); renderPraesentAblauf(); updatePraesentPhaseButtons();
    };
  });
  stage.querySelectorAll("[data-goal-edit-open]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); praesentEditZielId = Number(b.dataset.goalEditOpen); renderPraesentAblauf();
  });
  stage.querySelectorAll("[data-goal-cancel]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); praesentEditZielId = null; renderPraesentAblauf();
  });
  stage.querySelectorAll("[data-goal-save]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); savePraesentZiel(l, Number(b.dataset.goalSave));
  });
  stage.querySelectorAll("[data-phase-time]").forEach((el) => {
    el.onclick = (e) => e.stopPropagation();
    el.onchange = (e) => {
      const val = e.target.value.trim();
      savePraesentPhaseMinutes(l, Number(el.dataset.phaseTime), val ? Number(val) : null);
    };
  });
  stage.querySelectorAll("[data-phase-time-clear]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation(); savePraesentPhaseMinutes(l, Number(b.dataset.phaseTimeClear), null);
  });
  const zieleCheck = $("praesentShowZieleCheck");
  if (zieleCheck) zieleCheck.onchange = (e) => {
    praesentAblaufPrefs.showZiele = e.target.checked;
    savePraesentAblaufPrefs();
    renderPraesentAblauf();
  };
  updatePraesentPhaseButtons();
}

function updatePraesentPhaseButtons() {
  const l = state.lessons.find((x) => String(x.id) === String(praesent.lessonId));
  const n = l && l.phases ? l.phases.length : 0;
  const prevBtn = $("praesentPrevBtn"), nextBtn = $("praesentNextBtn");
  if (prevBtn) prevBtn.disabled = praesent.phaseIdx <= 0 || n === 0;
  if (nextBtn) nextBtn.disabled = praesent.phaseIdx >= n - 1 || n === 0;
}

function setPraesentMode(mode) {
  praesent.mode = mode;
  if (mode === "ablauf") praesent.phaseIdx = 0;
  renderPraesentation();
  // Beim Wechsel in Lernbereich/Ablauf die laufende/nächste Stunde vorschlagen, sofern noch keine
  // für heute passende Auswahl getroffen wurde – weitere Stunden bleiben über das Select wählbar.
  if (mode === "lernbereich" || mode === "ablauf") {
    const today = todayLessons();
    if (!today.some((l) => String(l.id) === String(praesent.lessonId))) applyPraesentLessonSuggestion();
  }
}

function praesentFullscreen() {
  const el = document.documentElement;
  try {
    if (document.fullscreenElement) {
      if (document.exitFullscreen) document.exitFullscreen();
    } else if (el.requestFullscreen) {
      el.requestFullscreen().catch(() => { /* z. B. per Policy blockiert */ });
    }
  } catch (e) { /* Fullscreen nicht verfügbar */ }
}

/* ---------- Navigation ---------- */
const titles = {
  heute: ["Schulalltag heute", "Dein Tag auf einen Blick."],
  klassen: ["Klassen", "Klassen und Parallelgruppen anlegen und verwalten."],
  "klasse-detail": ["Klassendetails", "Stammdaten, Stunden und Schülerliste einer Klasse."],
  kalender: ["Planungskalender", "Monat, Woche und Lernbereichs-Zeitleiste."],
  praesentation: ["Schüleransicht", "Präsentationsmodus für Beamer/Tafel – Jahresplan, Lernbereich, heutiger Ablauf."],
  stoff: ["Stoffverteilungsplan", "Lehrplanbasierte Jahresplanung."],
  sequenzplan: ["Sequenzplanung", "Einzelstunden je Block des Stoffverteilungsplans, mit Grobziel und Notenart."],
  stunde: ["Unterrichtsplanung", "Ideenfeld, Phasentabelle und abschließende Klafki-/Meyer-Reflexion."],
  reflexion: ["Reflexion", "Offene Reflexionen ansehen, überspringen oder erfassen."],
  notizen: ["Notizen", "Gedanken sammeln – allgemein oder je Klasse, mit Autosave."],
  asuv: ["ASUV-Entwürfe", "Ausführlicher schriftlicher Unterrichtsentwurf je Stunde."],
  material: ["Materialbibliothek", "Material hochladen, taggen und wiederfinden."],
  settings: ["Einstellungen", "API-Key und Konto."],
  suche: ["Suche", "Volltextsuche über alle Inhalte."],
  mehr: ["Mehr", "Weitere Bereiche und Einstellungen."],
};
// Mobile Bottom-Nav: Views ohne eigenen Tab landen als "aktiv" auf dem Mehr-Tab.
const BOTTOM_NAV_VIEWS = new Set(["stundenplan", "kalender", "heute", "stunde"]);

/* ---------- M6 U2: globale In-App-Tab-Leiste (beliebige Views als Tabs offenhalten) ----------
   Jeder Aufruf von showView() registriert automatisch einen Tab – kein Aufruf-Ort muss dafür
   angepasst werden. "klasse-detail" bekommt pro Klasse einen eigenen Tab (wie bisher), alle
   anderen Views sind Singleton-Tabs (ein Tab pro View-Typ, erneutes Navigieren aktiviert ihn
   nur). Tabs teilen sich den bestehenden globalen State – hier wird nur gemerkt, WAS offen ist,
   nicht wessen Daten dupliziert werden. */
let openTabs = [];        // [{ key, view }] in Öffnungsreihenfolge
let activeTabKey = null;

function tabKeyFor(view) {
  return view === "klasse-detail" && detailClassId != null ? `klasse-detail:${detailClassId}` : view;
}

function tabLabelFor(t) {
  if (t.view === "klasse-detail") {
    const cid = Number(t.key.split(":")[1]);
    const c = state.classes.find((x) => x.id === cid);
    return c ? `${c.name} (${c.subject})` : "Klasse";
  }
  return (titles[t.view] && titles[t.view][0]) || t.view;
}

function registerActiveTab(view) {
  const key = tabKeyFor(view);
  if (!openTabs.some((t) => t.key === key)) openTabs.push({ key, view });
  activeTabKey = key;
  renderGlobalTabs();
}

// Pfeil-Icon in der Navigation: öffnet den Tab im Hintergrund, ohne die aktuelle Ansicht zu
// verlassen (wie „Link in neuem Tab öffnen"). Nur für Singleton-Views (Navigation verlinkt nie
// direkt auf klasse-detail).
function openTabInBackground(view) {
  const key = tabKeyFor(view);
  if (!openTabs.some((t) => t.key === key)) openTabs.push({ key, view });
  renderGlobalTabs();
  toast(`${(titles[view] && titles[view][0]) || view} als Tab geöffnet.`);
}

function renderGlobalTabs() {
  const wrap = $("globalTabs");
  if (!wrap) return;
  if (openTabs.length < 2) { wrap.innerHTML = ""; return; }   // ab 2 offenen Tabs sichtbar
  wrap.innerHTML = openTabs.map((t) => {
    const active = t.key === activeTabKey ? " active" : "";
    return `<div class="g-tab${active}" data-tab-key="${esc(t.key)}">` +
      `<span class="g-tab-label">${esc(tabLabelFor(t))}</span>` +
      `<button class="g-tab-close" data-tab-close="${esc(t.key)}" aria-label="Tab schließen">×</button></div>`;
  }).join("") + `<button class="g-tabs-close-all" id="closeAllTabsBtn" type="button" title="Alle Tabs schließen" aria-label="Alle Tabs schließen">Alle schließen</button>`;
  wrap.querySelectorAll("[data-tab-key]").forEach((el) => el.onclick = () => activateTab(el.dataset.tabKey));
  wrap.querySelectorAll("[data-tab-close]").forEach((el) =>
    el.onclick = (e) => { e.stopPropagation(); closeTab(el.dataset.tabClose); });
  $("closeAllTabsBtn").onclick = closeAllTabs;
}

function closeAllTabs() {
  openTabs = [];
  activeTabKey = null;
  renderGlobalTabs();
  showView("heute");
}

function activateTab(key) {
  const t = openTabs.find((x) => x.key === key);
  if (!t) return;
  if (t.view === "klasse-detail") {
    detailClassId = Number(key.split(":")[1]);
    showView("klasse-detail");
    renderClassDetail();
  } else {
    showView(t.view);
  }
}

function closeTab(key) {
  const idx = openTabs.findIndex((t) => t.key === key);
  if (idx === -1) return;
  const wasActive = key === activeTabKey;
  openTabs.splice(idx, 1);
  if (!wasActive) { renderGlobalTabs(); return; }
  const next = openTabs[idx] || openTabs[idx - 1];
  if (next) activateTab(next.key);
  else { activeTabKey = null; showView("heute"); }
}

// Klappt die Sektion auf, in der die Ziel-View liegt (falls sie zugeklappt war), damit der
// aktive Menüpunkt sichtbar bleibt.
function expandSidebarSectionFor(view) {
  const btn = document.querySelector(`.nav-btn[data-view="${view}"]`);
  const section = btn ? btn.closest(".nav-section") : null;
  if (!section || !section.classList.contains("collapsed")) return;
  const key = section.dataset.section;
  section.classList.remove("collapsed");
  const toggleBtn = document.querySelector(`[data-section-toggle="${key}"]`);
  if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "true");
  const stateNow = loadSidebarCollapsed();
  stateNow[key] = false;
  saveSidebarCollapsed(stateNow);
}

function showView(view) {
  // Ausstehende Autosaves der bisherigen Ansicht sichern, bevor umgeschaltet wird (Fire-and-
  // forget – die Requests laufen im Hintergrund weiter, auch wenn die DOM schon wechselt).
  flushLessonAutosave().catch(() => {});
  if (_sequenzplanModuleInstance) _sequenzplanModuleInstance.flushSeqAutosave().catch(() => {});
  if (_stoffplanModuleInstance) _stoffplanModuleInstance.flushStoffplanAutosave().catch(() => {});
  expandSidebarSectionFor(view);
  document.querySelectorAll(".nav-btn").forEach((b) => {
    const on = b.dataset.view === view;
    b.classList.toggle("active", on);
    if (on) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  document.querySelectorAll(".bn-item").forEach((b) => {
    const bv = b.dataset.view;
    b.classList.toggle("active", bv === view || (bv === "mehr" && !BOTTOM_NAV_VIEWS.has(view)));
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $(view).classList.remove("hidden");
  $("pageTitle").textContent = titles[view][0];
  $("pageSub").textContent = titles[view][1];
  document.title = titles[view][0] + " · Lehrer-Dashboard";
  // Verlässt man die Klassen-Ansicht mit offenem Bearbeiten-Modus, den Update-Modus
  // zurücksetzen – sonst würde ein späteres "Klasse speichern" versehentlich updaten.
  if (view !== "klassen" && editingClassId) resetClassForm();
  if (view === "settings") loadSettings();
  if (view === "kalender") { ensureGoogleStatus(); maybeAutoSyncOnOpen(); }  // U21/U24: Status + Auto-Sync (A)
  if (view === "stundenplan") ttShow();  // U28: vormals eigener Klick-Listener in stundenplan.js
  if (view === "asuv" && state.lessons.length) loadAsuv(asuvLessonId || state.lessons[0].id);
  if (view === "stoff") getStoffplanModule().then((m) => m.loadStoffPlans());
  if (view === "sequenzplan") getSequenzplanModule().then((m) => {
    m.renderSeqClassSelect(); m.renderSeqBlockSelect(); m.loadSeqCardsFromServer();
  });
  if (view === "praesentation") renderPraesentation();
  if (view === "notizen") getNotizenModule().then((m) => m.renderNotizen());
  if (view === "material") renderArchivPanel(archivTab);
  closeMobileNav();
  syncHash(view);
  registerActiveTab(view);
}

// U28: URL-Hash spiegelt die aktuelle Ansicht, damit ein zweiter Browser-Tab
// (oder ein neu geöffnetes Fenster der installierten App) direkt dort landet.
// history.replaceState statt location.hash, damit kein eigener Verlaufseintrag
// entsteht und kein hashchange-Loop ausgelöst wird.
function syncHash(view) {
  let seg = view;
  if (view === "klasse-detail" && detailClassId) seg += "/" + detailClassId;
  else if (view === "stunde" && editingLessonId) seg += "/" + editingLessonId;
  else if (view === "asuv" && asuvLessonId) seg += "/" + asuvLessonId;
  const hash = "#" + seg;
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

// Löst einen eingehenden Hash auf (initialer Aufruf, neuer Tab, Zurück/Vor, manuelle URL).
function routeFromHash() {
  const raw = decodeURIComponent(location.hash.slice(1));
  if (!raw) return;
  const [view, rawId] = raw.split("/");
  if (!titles[view]) return;
  const id = rawId ? Number(rawId) : null;
  if (view === "klasse-detail" && id) { openClassDetail(id); return; }
  if (view === "stunde" && id) {
    const l = state.lessons.find((x) => x.id === id);
    showView("stunde");
    if (l) loadLessonIntoForm(l);
    return;
  }
  if (view === "asuv" && id) { showView("asuv"); loadAsuv(id); return; }
  showView(view);
}
window.addEventListener("hashchange", routeFromHash);
function closeMobileNav() { $("sidebarNav").classList.remove("open"); $("navBackdrop").classList.remove("open"); }

/* Sidebar am Desktop ein-/ausklappen (M10 U3) */
const NAV_COLLAPSED_KEY = "ldb_nav_collapsed";
function setNavCollapsed(collapsed) {
  document.querySelector(".app").classList.toggle("nav-collapsed", collapsed);
  const btn = $("navCollapseBtn");
  btn.textContent = collapsed ? "›" : "‹";
  const label = collapsed ? "Navigation ausklappen" : "Navigation einklappen";
  btn.title = label;
  btn.setAttribute("aria-label", label);
  try { localStorage.setItem(NAV_COLLAPSED_KEY, collapsed ? "1" : "0"); } catch (e) { /* egal */ }
}

/* ---------- Globale Volltextsuche (U25; Typ-Metadaten siehe SEARCH_TYPE_META) ---------- */
let searchState = { q: "", type: null, subject: null, grade: null };

function runGlobalSearch(q) {
  searchState = { q: (q || "").trim(), type: null, subject: null, grade: null };
  showView("suche");
  renderSearchResults();
}

// Snippet-Marker [[…]] des Servers → <mark>; Inhalt vorher escapen (XSS-sicher; esc lässt [ ] unberührt).
function highlightSnippet(s) {
  return esc(s || "").split("[[").join("<mark>").split("]]").join("</mark>");
}

// U27 (Variante C): Facetten als Filter-Seitenleiste (Boxen Typ/Fach/Klasse mit farbigen Punkten + Zählern).
function renderSearchFacets(facets) {
  const item = (dim, key, label, count, active, dotColor) =>
    `<button class="search-fitem${active ? " on" : ""}" data-fdim="${dim}" data-fkey="${esc(String(key))}">` +
    `<span class="search-fdot"${dotColor ? ` style="background:${dotColor}"` : ""}></span>` +
    `<span class="search-flabel">${esc(label)}</span><span class="search-fn">${count}</span></button>`;
  const box = (title, inner) => `<div class="search-fbox"><h4>${title}</h4>${inner}</div>`;
  const groups = [];
  if (facets.types && facets.types.length) {
    const total = facets.types.reduce((s, f) => s + f.count, 0);
    let inner = item("type", "", "Alle", total, !searchState.type, "");
    inner += facets.types.map((f) => item("type", f.key, cmdTypeMeta(f.key).pl, f.count, searchState.type === f.key, cmdTypeMeta(f.key).color)).join("");
    groups.push(box("Typ", inner));
  }
  if (facets.subjects && facets.subjects.length)
    groups.push(box("Fach", facets.subjects.map((f) => item("subject", f.key, f.key, f.count, searchState.subject === f.key, "")).join("")));
  if (facets.grades && facets.grades.length)
    groups.push(box("Klasse", facets.grades.map((f) => item("grade", f.key, "Klasse " + f.key, f.count, String(searchState.grade) === f.key, "")).join("")));
  return groups.join("");
}

// U27 (Variante C): dichte Trefferzeile mit farbigem Typ-Icon + farbigem Typ-Label.
function renderSearchResultCard(r) {
  const m = cmdTypeMeta(r.type);
  const meta = [];
  if (r.subject) meta.push(esc(r.subject));
  if (r.grade != null) meta.push("Kl. " + esc(String(r.grade)));
  if (r.date) meta.push(esc(r.date));
  if (r.type === "material" && r.pageFrom != null)
    meta.push("S. " + esc(String(r.pageFrom)) + (r.pageTo && r.pageTo !== r.pageFrom ? "–" + esc(String(r.pageTo)) : ""));
  const metaHtml = meta.length ? ` <span class="search-meta">${meta.join(" · ")}</span>` : "";
  const snip = r.snippet ? `<div class="search-snippet">${highlightSnippet(r.snippet)}</div>` : "";
  const nav = r.type !== "lernbereich";   // Lernbereiche haben kein Navigationsziel (nur Anzeige)
  return `<div class="search-result${nav ? " nav" : ""}"${nav ? ` data-type="${esc(r.type)}" data-id="${r.id}"` : ""}>` +
    `<span class="search-result-ic" style="background:${cmdTint(m.color, .13)}; color:${m.color}">${cmdSvg(m.icon)}</span>` +
    `<div class="search-result-body"><div class="search-result-head">` +
    `<span class="search-type-badge" style="color:${m.color}">${esc(m.label)}</span> ` +
    `<strong class="search-result-title">${esc(r.title || "(ohne Titel)")}</strong>${metaHtml}</div>${snip}</div></div>`;
}

async function renderSearchResults() {
  const heading = $("searchHeading"), summary = $("searchSummary");
  const facetsWrap = $("searchFacets"), resWrap = $("searchResultsGlobal");
  if (!heading) return;
  const q = searchState.q;
  if (!q) {
    heading.textContent = "Suche"; summary.textContent = "Gib oben einen Suchbegriff ein.";
    facetsWrap.innerHTML = ""; resWrap.innerHTML = ""; return;
  }
  heading.textContent = "Suche: „" + q + "“";
  summary.textContent = "Suche läuft …";
  const params = new URLSearchParams({ q });
  if (searchState.type) params.set("type", searchState.type);
  if (searchState.subject) params.set("subject", searchState.subject);
  if (searchState.grade != null) params.set("grade", searchState.grade);
  let data;
  try { data = await API.get("/search?" + params.toString()); }
  catch (e) { facetsWrap.innerHTML = ""; resWrap.innerHTML = ""; summary.textContent = "Fehler bei der Suche: " + e.message; return; }
  const active = searchState.type || searchState.subject || searchState.grade != null;
  summary.textContent = data.total + " Treffer" + (active ? " (gefiltert)" : "");
  facetsWrap.innerHTML = renderSearchFacets(data.facets);
  resWrap.innerHTML = data.results.length
    ? data.results.map(renderSearchResultCard).join("")
    : '<p class="muted small">Keine Treffer.</p>';
  facetsWrap.querySelectorAll(".search-fitem").forEach((btn) => {
    btn.onclick = () => {
      const dim = btn.dataset.fdim, key = btn.dataset.fkey;
      if (dim === "grade") searchState.grade = (String(searchState.grade) === key) ? null : Number(key);
      else searchState[dim] = (key === "" || searchState[dim] === key) ? null : key;   // "" = „Alle" (Filter leeren)
      renderSearchResults();
    };
  });
  resWrap.querySelectorAll(".search-result.nav").forEach((el) => {
    el.onclick = () => openSearchResult(el.dataset.type, Number(el.dataset.id));
  });
}

// Klick auf ein Suchergebnis → passende Ansicht/Detail öffnen.
function openSearchResult(type, id) {
  if (type === "lesson") {
    const l = state.lessons.find((x) => x.id === id);
    if (l) openLessonModal(l); else toast("Stunde nicht gefunden.", false);
  } else if (type === "asuv") {
    showView("asuv"); loadAsuv(id);                 // id = lesson_id
  } else if (type === "material") {
    showView("material");
    const inp = $("matSearch"); if (inp) { inp.value = searchState.q; runSearch(); }
  } else if (type === "calendar") {
    showView("kalender");
    const e = state.calendar.find((x) => x.id === id);
    if (e) jumpCalendarToDate(e.entryDate);
  } else if (type === "class") {
    openClassDetail(id);
  } else if (type === "note") {
    // Modul zuerst laden und die pending-id setzen, DANN showView (das intern selbst
    // getNotizenModule() aufruft) – sonst könnte renderNotizen() vor setPendingOpenId laufen.
    getNotizenModule().then((m) => { m.setPendingOpenId(id); showView("notizen"); });
  } else if (type === "reflection") {
    showView("reflexion");
  } else if (type === "todo") {
    showView("heute");
  } else if (type === "stoffplan") {
    showView("stoff");
  }
}

/* ---------- Kommando-Palette (U27, Variante C): globale Suche + Sprünge (⌘K/Strg+K/„/") ---------- */
// Typ-Metadaten: Farbe + Icon-Pfad + Plural. Statisch (keine Nutzerdaten → in svg/Style kein esc nötig).
const SEARCH_TYPE_META = {
  lesson:      { label: "Stunde",      pl: "Stunden",       color: "#16a34a", icon: "M12 6.3c-1.5-1.2-3.9-1.7-7.2-1.7V17c3.3 0 5.7.5 7.2 1.7 1.5-1.2 3.9-1.7 7.2-1.7V4.6c-3.3 0-5.7.5-7.2 1.7Z M12 6.3v12.4" },
  material:    { label: "Material",    pl: "Materialien",   color: "#0284c7", icon: "M7 3.5h6.5L18 8v11.5a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z M13.3 3.6V8H18" },
  calendar:    { label: "Termin",      pl: "Termine",       color: "#ea580c", icon: "M4.5 6.5A1.5 1.5 0 0 1 6 5h12a1.5 1.5 0 0 1 1.5 1.5v11A1.5 1.5 0 0 1 18 19H6a1.5 1.5 0 0 1-1.5-1.5Z M4.5 9.3h15 M8.3 3.5v3 M15.7 3.5v3" },
  stoffplan:   { label: "Stoffplan",   pl: "Stoffpläne",    color: "#0d9488", icon: "M9 6.2h11 M9 12h11 M9 17.8h11 M4.6 6.2h.01 M4.6 12h.01 M4.6 17.8h.01" },
  reflection:  { label: "Reflexion",   pl: "Reflexionen",   color: "#b45309", icon: "M4.5 5.5h15v9h-8.7L6 18v-3.5H4.5Z M8.4 10h.01 M12 10h.01 M15.6 10h.01" },
  note:        { label: "Notiz",       pl: "Notizen",       color: "#db2777", icon: "M4 20h4L19 9l-4-4L4 16Z M14.2 5.8 18 9.6" },
  asuv:        { label: "ASUV",        pl: "ASUV-Entwürfe", color: "#15803d", icon: "M7 3.5h6.5L18 8v11.5a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z M13.3 3.6V8H18 M9.4 14.4l1.9 1.9 3.4-3.9" },
  todo:        { label: "To-do",       pl: "To-dos",        color: "#059669", icon: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M8.4 12l2.3 2.3L15.6 9.2" },
  class:       { label: "Klasse",      pl: "Klassen",       color: "#9333ea", icon: "M9 11.2a3.1 3.1 0 1 0 0-6.2 3.1 3.1 0 0 0 0 6.2Z M3.4 19.4c0-3.1 2.6-4.8 5.6-4.8s5.6 1.7 5.6 4.8 M16.4 5.3a3 3 0 0 1 0 5.7 M17.3 14.8c2.2.4 3.8 1.8 3.8 4.6" },
  lernbereich: { label: "Lernbereich", pl: "Lernbereiche",  color: "#475569", icon: "M7 4h10v16l-5-3.8L7 20Z" },
};
const CMD_SEARCH_ICON = "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z M20 20l-3.6-3.6";
const CMD_BOLT_ICON = "M13 3 5.2 13H10l-1 8 7.8-10H12l1-8Z";
function cmdTypeMeta(t) { return SEARCH_TYPE_META[t] || { label: t, pl: t, color: "#475569", icon: CMD_BOLT_ICON }; }
function cmdSvg(d) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
}
function cmdTint(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// Sprünge = reine Ansichts-Navigation (Umfang: „Suche + Sprünge", kein Anlegen).
const CMD_ACTIONS = [
  { label: "Schulalltag heute", view: "heute", kw: "heute start dashboard tag todo" },
  { label: "Klassen", view: "klassen", kw: "klassen klasse schueler schüler" },
  { label: "Planungskalender", view: "kalender", kw: "kalender termine termin planung" },
  { label: "Stoffverteilungsplan", view: "stoff", kw: "stoff stoffverteilung jahresplan plan" },
  { label: "Sequenzplanung", view: "sequenzplan", kw: "sequenz sequenzplan stunden grobziel" },
  { label: "Unterrichtsplanung", view: "stunde", kw: "stunde unterricht planen neue" },
  { label: "Reflexion", view: "reflexion", kw: "reflexion reflektieren journal ampel" },
  { label: "Notizen", view: "notizen", kw: "notiz notizen gedanken" },
  { label: "ASUV-Entwürfe", view: "asuv", kw: "asuv entwurf lehrprobe" },
  { label: "Materialbibliothek", view: "material", kw: "material datei upload bibliothek" },
  { label: "Schüleransicht", view: "praesentation", kw: "praesentation präsentation schueler schüler beamer" },
  { label: "Einstellungen", view: "settings", kw: "einstellungen settings api schuljahr darstellung" },
];

let cmdState = { open: false, q: "", entries: [], selectable: [], activeIdx: -1, seq: 0 };
let _cmdTimer = null, _cmdOpener = null;
const cmdIsMac = (() => {
  try { return /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || ""); }
  catch (e) { return false; }
})();
const cmdShortcutLabel = cmdIsMac ? "⌘K" : "Strg+K";

function openCmdPalette() {
  const pal = $("cmdPalette"); if (!pal) return;
  _cmdOpener = document.activeElement;
  cmdState.open = true;
  pal.classList.remove("hidden");
  document.body.classList.add("cmd-open");
  const inp = $("cmdInput");
  inp.value = cmdState.q || "";
  inp.focus(); inp.select();
  cmdRunSearch(inp.value);
}
function closeCmdPalette() {
  const pal = $("cmdPalette"); if (!pal) return;
  cmdState.open = false;
  clearTimeout(_cmdTimer);
  pal.classList.add("hidden");
  document.body.classList.remove("cmd-open");
  if (_cmdOpener && _cmdOpener.focus) { try { _cmdOpener.focus(); } catch (e) { /* egal */ } }
}
function toggleCmdPalette() { cmdState.open ? closeCmdPalette() : openCmdPalette(); }

function cmdMatchActions(q) {
  const s = q.trim().toLowerCase();
  const base = s
    ? CMD_ACTIONS.filter((a) => a.label.toLowerCase().includes(s) || a.kw.includes(s))
    : CMD_ACTIONS.slice(0, 6);
  return base.slice(0, 6);
}

// Entprellte Live-Suche; veraltete Antworten werden per Sequenznummer verworfen.
function cmdRunSearch(q) {
  cmdState.q = q;
  clearTimeout(_cmdTimer);
  const term = (q || "").trim();
  const seq = ++cmdState.seq;
  if (term.length < 2) { cmdBuild({ results: [], facets: { types: [] }, total: 0 }, term); return; }
  _cmdTimer = setTimeout(async () => {
    try {
      const data = await API.get("/search?" + new URLSearchParams({ q: term, limit: "30" }).toString());
      if (seq !== cmdState.seq) return;
      cmdBuild(data, term);
    } catch (e) {
      if (seq !== cmdState.seq) return;
      cmdBuild({ results: [], facets: { types: [] }, total: 0, error: e.message }, term);
    }
  }, 200);
}

// Ordnet Treffer nach Typ, ergänzt Sprünge + „Alle Ergebnisse"; baut die flache Auswahl-Liste.
function cmdBuild(data, term) {
  const entries = [];
  const groups = {};
  (data.results || []).forEach((r) => { (groups[r.type] = groups[r.type] || []).push(r); });
  const order = (data.facets && data.facets.types) ? data.facets.types.map((f) => f.key) : Object.keys(groups);
  const counts = {};
  if (data.facets && data.facets.types) data.facets.types.forEach((f) => (counts[f.key] = f.count));

  order.forEach((t) => {
    const rows = (groups[t] || []).slice(0, 4);
    if (!rows.length) return;
    const m = cmdTypeMeta(t);
    entries.push({ t: "header", label: m.pl, color: m.color, count: counts[t] != null ? counts[t] : rows.length });
    rows.forEach((r) => entries.push({ t: "result", type: r.type, id: r.id, r }));
  });

  const actions = cmdMatchActions(term);
  if (actions.length) {
    entries.push({ t: "header", label: "Sprünge" });
    actions.forEach((a) => entries.push({ t: "action", label: a.label, view: a.view }));
  }
  if (term.length >= 2) entries.push({ t: "all", term, total: data.total || 0 });

  cmdState.entries = entries;
  cmdState.selectable = entries.map((e, i) => (e.t !== "header" ? i : -1)).filter((i) => i >= 0);
  cmdState.activeIdx = cmdState.selectable.length ? cmdState.selectable[0] : -1;
  cmdRender(data, term);
}

function cmdRender(data, term) {
  const box = $("cmdResults"); if (!box) return;
  const entries = cmdState.entries || [];
  let html = "";
  if (data && data.error) html += `<div class="cmd-empty">Fehler bei der Suche: ${esc(data.error)}</div>`;
  if (!entries.length) {
    html += `<div class="cmd-empty">${term && term.length >= 2 ? "Keine Treffer." : "Mindestens zwei Zeichen tippen, um zu suchen."}</div>`;
  }
  entries.forEach((e, i) => {
    if (e.t === "header") {
      html += `<div class="cmd-sec">${esc(e.label)}` +
        (e.count != null ? ` <span class="cmd-sec-n" style="background:${e.color}">${esc(String(e.count))}</span>` : "") + `</div>`;
      return;
    }
    const sel = i === cmdState.activeIdx;
    const cls = "cmd-row" + (e.t === "all" ? " cmd-row-all" : "") + (sel ? " active" : "");
    const attrs = ` role="option" data-idx="${i}" aria-selected="${sel ? "true" : "false"}"`;
    if (e.t === "result") {
      const m = cmdTypeMeta(e.type);
      const meta = [];
      if (e.r.subject) meta.push(esc(e.r.subject));
      if (e.r.grade != null) meta.push("Kl. " + esc(String(e.r.grade)));
      if (e.r.date) meta.push(esc(e.r.date));
      if (e.type === "material" && e.r.pageFrom != null)
        meta.push("S. " + esc(String(e.r.pageFrom)) + (e.r.pageTo && e.r.pageTo !== e.r.pageFrom ? "–" + esc(String(e.r.pageTo)) : ""));
      html += `<div class="${cls}"${attrs}>` +
        `<span class="cmd-ic" style="background:${cmdTint(m.color, .14)}; color:${m.color}">${cmdSvg(m.icon)}</span>` +
        `<span class="cmd-main"><span class="cmd-title">${esc(e.r.title || "(ohne Titel)")}</span>` +
        `<span class="cmd-sub">${esc(m.label)}${meta.length ? " · " + meta.join(" · ") : ""}</span></span>` +
        (e.r.snippet ? `<span class="cmd-snip">${highlightSnippet(e.r.snippet)}</span>` : "<span></span>") +
        `</div>`;
    } else if (e.t === "action") {
      html += `<div class="${cls}"${attrs}>` +
        `<span class="cmd-ic" style="background:${cmdTint("#16a34a", .12)}; color:#16a34a">${cmdSvg(CMD_BOLT_ICON)}</span>` +
        `<span class="cmd-main"><span class="cmd-title">${esc(e.label)}</span><span class="cmd-sub">Ansicht öffnen</span></span>` +
        `<span class="cmd-tag">Sprung</span></div>`;
    } else if (e.t === "all") {
      html += `<div class="${cls}"${attrs}>` +
        `<span class="cmd-ic" style="background:${cmdTint("#16a34a", .12)}; color:#16a34a">${cmdSvg(CMD_SEARCH_ICON)}</span>` +
        `<span class="cmd-main"><span class="cmd-title">Alle Ergebnisse für „${esc(e.term)}" anzeigen</span>` +
        `<span class="cmd-sub">${esc(String(e.total))} Treffer · öffnet die Ergebnisseite</span></span><span></span></div>`;
    }
  });
  box.innerHTML = html;
  box.querySelectorAll(".cmd-row").forEach((el) => {
    const idx = Number(el.dataset.idx);
    el.addEventListener("mousemove", () => { if (idx !== cmdState.activeIdx) { cmdState.activeIdx = idx; cmdSyncActive(); } });
    el.addEventListener("click", () => cmdActivate(idx));
  });
  cmdScrollActive();
}

function cmdSyncActive() {
  const box = $("cmdResults"); if (!box) return;
  box.querySelectorAll(".cmd-row").forEach((el) => {
    const on = Number(el.dataset.idx) === cmdState.activeIdx;
    el.classList.toggle("active", on);
    el.setAttribute("aria-selected", on ? "true" : "false");
  });
  cmdScrollActive();
}
function cmdScrollActive() {
  const box = $("cmdResults"); if (!box) return;
  const el = box.querySelector(".cmd-row.active");
  if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
}
function cmdMove(dir) {
  const sel = cmdState.selectable || [];
  if (!sel.length) return;
  let pos = sel.indexOf(cmdState.activeIdx);
  pos = (pos + dir + sel.length) % sel.length;
  cmdState.activeIdx = sel[pos];
  cmdSyncActive();
}
function cmdActivate(idx) {
  const e = (cmdState.entries || [])[idx];
  if (!e) return;
  if (e.t === "result") {
    searchState.q = cmdState.q;          // Material-Deeplink in openSearchResult nutzt searchState.q
    closeCmdPalette();
    openSearchResult(e.type, e.id);
  } else if (e.t === "action") {
    closeCmdPalette();
    showView(e.view);
  } else if (e.t === "all") {
    closeCmdPalette();
    runGlobalSearch(e.term);
  }
}
function cmdInputKeydown(e) {
  if (e.key === "ArrowDown") { e.preventDefault(); cmdMove(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); cmdMove(-1); }
  else if (e.key === "Enter") { e.preventDefault(); if (cmdState.activeIdx >= 0) cmdActivate(cmdState.activeIdx); }
  else if (e.key === "Escape") { e.preventDefault(); closeCmdPalette(); }
}
function cmdIsTypingTarget(t) {
  if (!t || !t.tagName) return false;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return true;
  return !!t.isContentEditable;
}
function cmdAuthOpen() { const o = $("authOverlay"); return !!(o && !o.classList.contains("hidden")); }
function cmdGlobalKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && !e.altKey && (e.key === "k" || e.key === "K")) {
    e.preventDefault(); if (!cmdAuthOpen()) toggleCmdPalette(); return;
  }
  if (cmdState.open) { if (e.key === "Escape") { e.preventDefault(); closeCmdPalette(); } return; }
  if (e.key === "/" && !cmdIsTypingTarget(e.target) && !cmdAuthOpen()) { e.preventDefault(); openCmdPalette(); }
}
function wireCmdPalette() {
  const pal = $("cmdPalette"); if (!pal) return;
  const inp = $("cmdInput");
  inp.addEventListener("input", () => cmdRunSearch(inp.value));
  inp.addEventListener("keydown", cmdInputKeydown);
  pal.querySelectorAll("[data-cmd-close]").forEach((el) => (el.onclick = closeCmdPalette));
  const trg = $("cmdOpenBtn"); if (trg) trg.onclick = openCmdPalette;
  const kbd = $("cmdOpenBtnKbd"); if (kbd) kbd.textContent = cmdShortcutLabel;
  document.addEventListener("keydown", cmdGlobalKeydown);
}

/* ---------- Refresh ---------- */
async function refresh() { await loadAll(); renderAll(); }

/* ---------- Auth ---------- */
let authMode = "login";
function showAuth(show) {
  $("authOverlay").classList.toggle("hidden", !show);
}
function setAuthMode(mode) {
  authMode = mode;
  const reg = mode === "register";
  $("authTitle").textContent = reg ? "Erstes Konto anlegen" : "Anmelden";
  $("authIntro").textContent = reg
    ? "Lege dein (einziges) Konto an – danach ist die Registrierung gesperrt."
    : "Bitte melde dich an.";
  $("authNameRow").classList.toggle("hidden", !reg);
  $("authSubmit").textContent = reg ? "Konto anlegen" : "Anmelden";
  $("authToggle").textContent = reg ? "Zurück zum Login" : "Erstes Konto anlegen";
  $("authError").classList.add("hidden");
}
async function submitAuth() {
  const email = $("authEmail").value.trim();
  const password = $("authPassword").value;
  const errBox = $("authError");
  errBox.classList.add("hidden");
  try {
    if (authMode === "register") {
      await API.post("/auth/register", { email, displayName: $("authDisplayName").value.trim() || email, password });
    } else {
      await API.post("/auth/login", { email, password });
    }
    await startApp();
    showAuth(false);
  } catch (e) {
    errBox.textContent = e.message;
    errBox.classList.remove("hidden");
  }
}

/* ---------- Start ---------- */
async function startApp() {
  const me = await API.get("/auth/me");
  state.user = me;
  $("navUser").textContent = me.displayName;
  $("settingsUser").textContent = `${me.displayName} (${me.email})`;
  $("avatarImg").src = me.avatarPath ? `/api/users/${me.id}/avatar?t=${Date.now()}` : TRANSPARENT_PX;
  const now = new Date();
  $("sidebarDate").textContent = now.toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "long" });
  $("sidebarKW").textContent = "Kalenderwoche " + isoWeek(now);
  await refresh();
  if (location.hash) routeFromHash();  // U28: Deep-Link aus URL (neuer Tab/Fenster, Reload)
  await refreshAiStatus();
  startGoogleAutoSync();  // U24: periodischer Auto-Sync (B), solange die App offen ist
  refreshSchulmanagerChanges();  // M1d: Glocke initial befüllen (kein await – blockiert den Start nicht)
}

// Sidebar-Sektionen ein-/ausklappbar (Burgermenü Variante B): Zustand je Sektion in
// localStorage, Default = aufgeklappt (kein Eintrag = expanded).
function loadSidebarCollapsed() {
  try { return JSON.parse(localStorage.getItem("sidebarCollapsed") || "{}"); }
  catch (e) { return {}; }
}
function saveSidebarCollapsed(state_) {
  try { localStorage.setItem("sidebarCollapsed", JSON.stringify(state_)); } catch (e) { /* ignore */ }
}
function initSidebarSections() {
  const collapsed = loadSidebarCollapsed();
  const activeBtn = document.querySelector(".nav-btn.active");
  const activeSection = activeBtn ? activeBtn.closest(".nav-section") : null;
  document.querySelectorAll("[data-section-toggle]").forEach((btn) => {
    const key = btn.dataset.sectionToggle;
    const section = document.querySelector(`.nav-section[data-section="${key}"]`);
    if (!section) return;
    // Die Sektion der initial aktiven View bleibt immer aufgeklappt sichtbar, auch wenn sie
    // zuvor zugeklappt gespeichert wurde.
    const isCollapsed = section === activeSection ? false : Boolean(collapsed[key]);
    section.classList.toggle("collapsed", isCollapsed);
    btn.setAttribute("aria-expanded", String(!isCollapsed));
    btn.onclick = () => {
      const next = !section.classList.contains("collapsed");
      section.classList.toggle("collapsed", next);
      btn.setAttribute("aria-expanded", String(!next));
      const stateNow = loadSidebarCollapsed();
      stateNow[key] = next;
      saveSidebarCollapsed(stateNow);
    };
  });
}

function wireEvents() {
  buildMeyerGrid("meyerPlanGrid");
  buildMeyerGrid("meyerReflectGrid");
  initSidebarSections();
  lessonPhases = defaultPhases();
  renderPhases();
  wireAppearance();
  // U25: Globale Volltextsuche aus der Topbar (Enter/Button).
  const gsf = $("globalSearchForm");
  if (gsf) gsf.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("globalSearchInput").value.trim();
    if (q) runGlobalSearch(q);
  });
  wireCmdPalette();   // U27 (Variante C): Kommando-Palette (⌘K / Strg+K / „/")
  const scBtn = $("syncConflictBtn");
  if (scBtn) scBtn.onclick = () => getSyncConflictsModule().then((m) => m.openOverlay());

  // U17-Umbau: Notizen-Arbeitsbereich (neue Notiz, Suche)
  $("notizNewBtn").onclick = () => getNotizenModule().then((m) => m.startNewDraft());
  $("notizSearch").addEventListener("input", (e) => {
    getNotizenModule().then((m) => m.setSearchQuery(e.target.value));
  });

  // Dashboard-Quicklinks: direkt zur passenden Aktion in der jeweiligen Ansicht springen.
  $("qlNoteBtn").onclick = () => { showView("notizen"); $("notizNewBtn").click(); };
  $("qlCalendarBtn").onclick = () => { showView("kalender"); openCalEntryPanel(isoDate(new Date())); };
  $("qlUploadBtn").onclick = () => {
    showView("material");
    const el = $("matFile");
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.click(); }
  };
  $("qlVertretungBtn").onclick = openVertretungModal;

  // M1d: Schulmanager-Abgleich
  $("smBellBtn").onclick = openSchulmanagerDrawer;
  $("smDrawerCloseBtn").onclick = closeSchulmanagerDrawer;
  $("smDrawerOverlay").onclick = (ev) => { if (ev.target.id === "smDrawerOverlay") closeSchulmanagerDrawer(); };

  // Spruch des Tages: Kachel öffnet Vollbild-Vorschau (Klick/Enter/Leertaste); Schließen per „×"/Esc.
  $("spruchCard").onclick = openScreensaver;
  $("spruchCard").onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openScreensaver(); } };
  $("ssClose").onclick = closeScreensaver;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("screensaver").classList.contains("hidden")) closeScreensaver();
  });

  // .nav-btn sind jetzt <a href="#view"> (U28) – Klick/Strg-Klick/Mittelklick übernimmt der Browser nativ,
  // die eigentliche Ansicht wird über den hashchange-Listener (routeFromHash) aktiviert.
  document.querySelectorAll("[data-view-target]").forEach((el) => (el.onclick = () => showView(el.dataset.viewTarget)));
  document.querySelectorAll(".bn-item, .mehr-item").forEach((btn) => (btn.onclick = () => showView(btn.dataset.view)));

  // Pfeil-Icon je Navigationspunkt: öffnet als Tab im Hintergrund, statt dorthin zu wechseln.
  document.querySelectorAll("[data-tab-open]").forEach((el) => {
    el.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); openTabInBackground(el.dataset.tabOpen); });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault(); e.stopPropagation(); openTabInBackground(el.dataset.tabOpen);
      }
    });
  });

  const burger = $("burgerBtn");
  burger.onclick = () => {
    const open = $("sidebarNav").classList.toggle("open");
    $("navBackdrop").classList.toggle("open", open);
  };
  $("navBackdrop").onclick = closeMobileNav;

  $("navCollapseBtn").onclick = () =>
    setNavCollapsed(!document.querySelector(".app").classList.contains("nav-collapsed"));
  try {
    if (localStorage.getItem(NAV_COLLAPSED_KEY) === "1") setNavCollapsed(true);
  } catch (e) { /* egal */ }

  $("saveClass").onclick = saveClass;

  // Klassen-Detail (U14)
  $("cdBackBtn").onclick = () => showView("klassen");
  $("cdEditBtn").onclick = () => {
    const c = state.classes.find((x) => String(x.id) === String(detailClassId));
    if (c) editClass(c);
  };
  $("cdPraesentBtn").onclick = showClassInPraesent;
  $("cdNoteNewBtn").onclick = async () => {
    await flushCdNoteSave();
    cdNoteIsDraft = true;
    cdNoteSelectedId = null;
    renderCdNoteList();
    renderCdNoteEditor();
  };
  $("cdStudentName").addEventListener("keydown", (e) => { if (e.key === "Enter") addStudent(); });
  $("cdStudentBulkBtn").onclick = addStudentsBulk;
  // U18: Sitzplan
  $("spBuildBtn").onclick = () => getSeatPlanModule().then((m) => m.spBuildGrid());
  $("spSaveBtn").onclick = () => getSeatPlanModule().then((m) => m.saveSeatPlan());
  $("spNewBtn").onclick = () => getSeatPlanModule().then((m) => m.initSeatPlan());
  $("spAiBtn").onclick = () => getSeatPlanModule().then((m) => m.aiArrangeSeats());
  $("saveLesson").onclick = saveLesson;
  $("cancelEditBtn").onclick = () => { resetLessonEditState(); clearLessonForm(); toast("Formular geleert – neue Stunde."); };
  // Autosave-Trigger per Delegation statt Einzel-Listener je Feld (Formular ist groß und Phasen/
  // Lernziele werden dynamisch nachgerendert). Ideenfeld/Material/To-do-Eingabe ausgenommen –
  // die gehören nicht zum lessons-Datensatz, den saveLesson()/buildLessonBody() speichert.
  ["input", "change"].forEach((evt) => $("stunde").addEventListener(evt, (e) => {
    if (!e.target || LESSON_AUTOSAVE_EXCLUDE.has(e.target.id)) return;
    scheduleLessonAutosave();
  }));
  $("deleteLessonBtn").onclick = deleteLesson;
  $("lessonClass").addEventListener("change", () => { updateLessonLbOptions(null); updateLessonSeqOptions(); updateSozialformMonotonyHint(); });
  fillLessonSlotSelect();
  $("lessonSlot").addEventListener("change", () => {
    const opt = $("lessonSlot").selectedOptions[0];
    if (opt && opt.dataset.start) $("lessonTime").value = opt.dataset.start;
  });
  $("phases").addEventListener("input", (ev) => { if (/^time\d+$/.test(ev.target.id || "")) validatePhaseTimes(); });
  $("lessonDuration").addEventListener("change", validatePhaseTimes);
  $("addPhaseBtn").onclick = addPhase;
  ["lessonFilterClass", "lessonFilterSubject", "lessonFilterType"].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener("change", renderLessonTable);
  });
  $("lessonSubject").addEventListener("change", () => {
    const sel = $("lessonSubject");
    if (sel.value !== "__new__") return;
    const name = (window.prompt("Name des neuen Fachs (z. B. für Vertretungsstunden):") || "").trim();
    if (!name) { sel.value = LESSON_SUBJECT_DEFAULTS[0]; return; }
    if (!Array.from(sel.options).some((o) => o.value === name)) {
      const opt = document.createElement("option");
      opt.value = name; opt.textContent = name;
      sel.insertBefore(opt, sel.querySelector('option[value="__new__"]'));
    }
    sel.value = name;
  });
  $("lessonMatUpload").onclick = async () => {
    const f = $("lessonMatFile").files[0];
    if (!f) { toast("Bitte eine Datei wählen.", false); return; }
    const subjectOverride = $("lessonMatSubject").value.trim();
    if (!editingLessonId) {
      // Neue Stunde: Verknüpfung erst nach dem Speichern möglich (fehlende lessonId) – merken.
      pendingLessonMaterialFile = f;
      pendingLessonMaterialSubject = subjectOverride;
      $("lessonMaterials").innerHTML =
        `<div class="file-chip"><span>${esc(f.name)} (wird beim Speichern der Stunde hochgeladen)</span></div>`;
      return;
    }
    const fd = new FormData();
    fd.append("file", f);
    fd.append("subject", subjectOverride || $("lessonSubject").value);
    const grade = Number($("lessonGrade").value);
    if (grade) fd.append("grade", grade);
    fd.append("lessonId", editingLessonId);
    try {
      await API.upload("/materials/upload", fd);
      await refresh();
      loadLessonMaterials(editingLessonId);
      $("lessonMatFile").value = ""; $("lessonMatSubject").value = "";
      toast("Material verknüpft.");
    } catch (e) { toast(e.message, false); }
  };
  $("lessonLb").addEventListener("change", updateLessonLbProgress);
  $("saveReflect").onclick = saveReflect;

  // Kalender
  $("calPrevBtn").onclick = () => { calCursor.setDate(calCursor.getDate() - (calMode === "week" ? 7 : 30)); renderCalendar(); };
  $("calNextBtn").onclick = () => { calCursor.setDate(calCursor.getDate() + (calMode === "week" ? 7 : 30)); renderCalendar(); };
  $("calMonthBtn").onclick = () => { calMode = "month"; $("calMonthBtn").classList.add("active"); $("calWeekBtn").classList.remove("active"); renderCalendar(); };
  $("calWeekBtn").onclick = () => { calMode = "week"; $("calWeekBtn").classList.add("active"); $("calMonthBtn").classList.remove("active"); renderCalendar(); };
  // U27c: blasse Stundenplan-Ebene ein-/ausschalten (persistiert, nur Wochen-Modus).
  $("calTtToggle").onclick = () => {
    calTtOn = !calTtOn;
    try { localStorage.setItem(CAL_TT_KEY, calTtOn ? "1" : "0"); } catch (e) { /* egal */ }
    $("calTtToggle").classList.toggle("active", calTtOn);
    renderCalendar();
  };
  // U33: Filter „Nur Stundenplan“ ein-/ausschalten (persistiert, Monat + Woche).
  $("calOnlyTtBtn").onclick = () => {
    calOnlyTt = !calOnlyTt;
    try { localStorage.setItem(CAL_ONLY_TT_KEY, calOnlyTt ? "1" : "0"); } catch (e) { /* egal */ }
    $("calOnlyTtBtn").classList.toggle("active", calOnlyTt);
    renderCalendar();
  };
  $("calOnlyTtBtn").classList.toggle("active", calOnlyTt);
  $("calSaveEntryBtn").onclick = saveCalendarEntry;
  $("calEntryAllDay").onchange = () => {
    $("calEntryTimeRow").style.display = $("calEntryAllDay").checked ? "none" : "flex";
  };
  // Stunde auswählen -> Uhrzeiten aus dem Klingelraster übernehmen (Ganztägig automatisch abwählen).
  $("calEntrySlot").onchange = () => {
    const opt = $("calEntrySlot").selectedOptions[0];
    if (!opt || !opt.value) return;
    $("calEntryAllDay").checked = false;
    $("calEntryTimeRow").style.display = "flex";
    $("calEntryStartTime").value = opt.dataset.start || "";
    $("calEntryEndTime").value = opt.dataset.end || "";
  };
  // U22: Termin-Popover öffnen/schließen; Werkzeug-Seitenleiste ein-/ausklappen.
  $("calNewEntryBtn").onclick = () => openCalEntryPanel(isoDate(new Date()));
  $("calEntryCancel").onclick = closeCalEntryPanel;
  $("calSideToggle").onclick = () => $("calLayout").classList.toggle("side-collapsed");
  $("addCatBtn").onclick = addCategory;
  $("importAnalyzeBtn").onclick = analyzeJahresplan;  // U20: Jahresplan-Import
  $("saveSchoolYear").onclick = saveSchoolYear;
  $("stoffUpload").onclick = () => getStoffplanModule().then((m) => m.stoffUpload());
  $("planSaveBtn").onclick = () => getStoffplanModule().then((m) => m.saveStoffPlan());
  $("planClass").addEventListener("change", () => getStoffplanModule().then((m) => m.onClassChanged()));
  $("planYear").addEventListener("change", () => getStoffplanModule().then((m) => m.loadPlanNotes()));
  $("planNotes").addEventListener("input", () => getStoffplanModule().then((m) => m.schedulePlanNotesSave()));
  $("planNotesSave").onclick = () => getStoffplanModule().then((m) => m.savePlanNotes(false));

  // Material
  $("saveMaterial").onclick = saveMaterial;
  $("matSearch").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

  // ASUV
  $("asuvLesson").addEventListener("change", (e) => loadAsuv(e.target.value));
  $("asuvSave").onclick = saveAsuv;
  $("asuvExportDocx").onclick = () => exportAsuv("docx");
  $("asuvExportPdf").onclick = () => exportAsuv("pdf");

  // KI (M7)
  $("aiPlanBtn").onclick = aiLessonSuggest;
  $("tafelbildBtn").onclick = aiTafelbildSuggest;
  $("tafelbildBildUpload").onclick = uploadTafelbildBild;
  $("tafelbildBildRemove").onclick = removeTafelbildBild;
  $("stoffAiBtn").onclick = () => getStoffplanModule().then((m) => m.aiStoffplan());
  $("seqAiBtn").onclick = () => getSequenzplanModule().then((m) => m.aiSequenzplan());
  $("seqAddBtn").onclick = () => getSequenzplanModule().then((m) => m.seqAddCard());
  $("seqSaveBtn").onclick = () => getSequenzplanModule().then((m) => m.saveSequenzplan());
  $("seqClass").addEventListener("change", () => getSequenzplanModule().then((m) => {
    m.renderSeqBlockSelect(); m.loadSeqCardsFromServer();
  }));
  $("seqBlock").addEventListener("change", () => getSequenzplanModule().then((m) => m.loadSeqCardsFromServer()));
  $("asuvAiBtn").onclick = aiAsuvSuggest;
  $("addLernzielBtn").onclick = addLernziel;
  $("aiLernzieleBtn").onclick = aiLernzieleSuggest;
  $("asuvEinordnungBtn").onclick = asuvEinordnungSuggest;
  $("stundeEinordnungBtn").onclick = stundeEinordnungSuggest;
  $("lessonType").addEventListener("change", (e) =>
    $("lueHint").classList.toggle("hidden", e.target.value !== "Übungsstunde vor LUE"));

  // Schüleransicht / Präsentationsmodus (M12 U8)
  document.querySelectorAll(".praesent-tab").forEach((btn) =>
    (btn.onclick = () => setPraesentMode(btn.dataset.praesent)));
  $("praesentClass").addEventListener("change", (e) => {
    praesent.classId = e.target.value;
    praesent.lessonId = null;
    praesent.sequenzStundeId = null;
    renderPraesentControls();   // Stundenauswahl auf die gewählte Klasse neu filtern
    renderPraesentation();
    if (praesent.mode === "lernbereich" || praesent.mode === "ablauf") applyPraesentLessonSuggestion();
  });
  $("praesentLesson").addEventListener("change", (e) => {
    praesent.lessonId = e.target.value ? Number(e.target.value) : null;
    praesent.sequenzStundeId = null;
    praesent.phaseIdx = 0;
    renderPraesentation();
  });
  $("praesentPrevBtn").onclick = () => { if (praesent.phaseIdx > 0) { praesent.phaseIdx--; renderPraesentAblauf(); } };
  $("praesentNextBtn").onclick = () => { praesent.phaseIdx++; renderPraesentAblauf(); };
  $("praesentEditBtn").onclick = () => {
    praesent.editMode = !praesent.editMode;
    if (!praesent.editMode) praesentEditZielId = null;
    renderPraesentation();
  };
  $("praesentFullscreenBtn").onclick = praesentFullscreen;
  document.addEventListener("fullscreenchange", () => {
    if (praesent.mode === "ablauf") renderPraesentation();   // Bearbeiten-Buttons/-Modus ein-/ausblenden
  });
  document.addEventListener("keydown", (e) => {
    const view = $("praesentation");
    if (!view || view.classList.contains("hidden") || praesent.mode !== "ablauf") return;
    if (e.target && /^(INPUT|SELECT|TEXTAREA|BUTTON|A)$/.test(e.target.tagName)) return;
    if (e.target && e.target.getAttribute && e.target.getAttribute("role") === "button") return;
    if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); praesent.phaseIdx++; renderPraesentAblauf(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); if (praesent.phaseIdx > 0) { praesent.phaseIdx--; renderPraesentAblauf(); } }
  });

  // Archiv-Reiter (U13)
  document.querySelectorAll(".archiv-tab").forEach((btn) =>
    (btn.onclick = () => setArchivTab(btn.dataset.archiv)));

  $("newTodoInput").addEventListener("keydown", async (e) => {
    if (e.key === "Enter" && e.target.value.trim()) {
      try { await SyncEngine.create("todos", { text: e.target.value.trim(), source: "manuell" }); e.target.value = ""; await refresh(); }
      catch (err) { toast(err.message, false); }
    }
  });

  $("lessonTodoInput").addEventListener("keydown", async (e) => {
    if (e.key === "Enter" && e.target.value.trim()) {
      try {
        await SyncEngine.create("todos", { text: e.target.value.trim(), source: "manuell" });
        e.target.value = "";
        await refresh();
        toast("To-Do hinzugefügt.");
      } catch (err) { toast(err.message, false); }
    }
  });

  $("saveApiKey").onclick = async () => {
    const key = $("apiKeyInput").value.trim();
    if (!key) { toast("Bitte einen API-Key eingeben.", false); return; }
    try { await API.put("/settings/api-key", { apiKey: key }); $("apiKeyInput").value = ""; await loadSettings(); toast("API-Key gespeichert."); }
    catch (e) { toast(e.message, false); }
  };
  $("removeApiKey").onclick = async () => {
    try { await API.del("/settings/api-key"); await loadSettings(); toast("API-Key entfernt."); }
    catch (e) { toast(e.message, false); }
  };
  // U21: Google-Kalender-Sync
  $("saveGoogleKey").onclick = saveGoogleKey;
  $("removeGoogleKey").onclick = removeGoogleKey;
  $("saveSchulmanagerUrl").onclick = saveSchulmanagerUrl;
  $("removeSchulmanagerUrl").onclick = removeSchulmanagerUrl;
  $("calGoogleSyncBtn").onclick = syncGoogle;
  $("logoutBtn").onclick = async () => {
    try { await API.post("/auth/logout"); } catch (e) { /* egal */ }
    location.reload();
  };
  $("clearCacheBtn").onclick = async () => {
    try {
      if ("serviceWorker" in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map((r) => r.unregister()));
      }
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
      // Service-Worker-CacheStorage allein reicht nicht — der normale HTTP-Disk-Cache
      // des Browsers bleibt davon unberührt (das erklärt den Unterschied zwischen Chrome
      // und Edge). Clear-Site-Data ist der einzige Weg, auch den zuverlässig zu leeren.
      await API.post("/settings/clear-cache");
    } catch (e) { /* egal — trotzdem neu laden */ }
    location.reload();
  };

  // Branding: Profilbild & Logo (M12/U10)
  $("avatarUploadBtn").onclick = () => $("avatarFileInput").click();
  $("avatarFileInput").addEventListener("change", (e) => {
    uploadAvatar(e.target.files[0]); e.target.value = "";
  });
  $("logoUploadBtn").onclick = () => $("logoFileInput").click();
  $("logoFileInput").addEventListener("change", (e) => {
    uploadLogo(e.target.files[0]); e.target.value = "";
  });
  $("logoRemoveBtn").onclick = removeLogo;

  $("authSubmit").onclick = submitAuth;
  $("authToggle").onclick = () => setAuthMode(authMode === "login" ? "register" : "login");
  $("authPassword").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); });
}

/* =========================================================================
   U17: Notizen ("Gedanken sammeln"). Der Editor (Liste + Autosave-Textfeld,
   vormals additiver Block hier) ist nach web/notizen.js ausgelagert (ES-Modul,
   app.js-Splitting, zweiter Kandidat nach sitzplan.js) und wird per dynamischem
   import() erst beim ersten Öffnen der Notizen-Ansicht nachgeladen.
   Die winzigen Formatierungs-Helfer bleiben hier, weil sie auch von der
   parallelen Klassen-Detail-Notizen-Ansicht (cdNote*) mitbenutzt werden.
   ========================================================================= */
function noteFirstLine(bodyMd) {
  return (bodyMd || "").split("\n").map((s) => s.trim()).find((s) => s) || "";
}
function noteTitle(n) {
  return noteFirstLine(n.bodyMd) || "Neue Notiz";
}
function notePreviewText(n) {
  const lines = (n.bodyMd || "").split("\n").map((s) => s.trim()).filter((s) => s);
  return lines.slice(1).join(" ");
}
function noteScopeLabel(n) {
  if (n.scope === "allgemein") return "Allgemein";
  const c = state.classes.find((x) => x.id === n.classId);
  return c ? `${c.name} (${c.subject})` : "Klasse";
}
function noteDateLabel(iso) {
  if (!iso) return "";
  const datePart = iso.split(" ")[0] || iso.split("T")[0] || "";
  const [y, m, d] = datePart.split("-");
  return y ? `${d}.${m}.${y}` : "";
}
// dataset-Werte sind immer Strings; eine synchronisierte Notiz hat eine numerische Server-id
// (muss für Vergleiche mit n.id zurück in eine Zahl), eine noch nicht synchronisierte Notiz
// eine "loc_..."-localId (muss String bleiben) — siehe Identitäts-Kommentar in sync-engine.js.
function parseNoteId(raw) {
  return /^\d+$/.test(raw) ? Number(raw) : raw;
}
function activeNotesSorted(filterFn) {
  return state.notes
    .filter((n) => n.archivedAt == null && (!filterFn || filterFn(n)))
    .sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""));
}

// Offline-Sync (F5): Vorschau-Renderer je Entität für die generische Konflikt-UI —
// pro Rollout-Entität hier um einen Eintrag ergänzen; ohne Eintrag greift dort ein
// generischer Key-Value-Fallback.
const SYNC_ENTITY_RENDERERS = {
  notes: (n) => ({ title: noteTitle(n), preview: notePreviewText(n) }),
  todos: (t) => ({ title: t.text, preview: t.done ? "erledigt" : "offen" }),
  calendar_categories: (c) => ({ title: c.name, preview: c.color }),
  school_years: (s) => ({ title: s.label, preview: `${s.startDate} – ${s.endDate}` }),
  plan_notes: (n) => ({ title: "Jahresplan-Ideen", preview: n.text }),
  timetable_kinds: (k) => ({ title: k.name, preview: k.color }),
  timetable_slots: (s) => ({ title: s.label, preview: `${s.startTime}–${s.endTime}` }),
  tropenplan_slots: (s) => ({ title: s.label, preview: `${s.startTime}–${s.endTime}` }),
  classes: (c) => ({ title: c.name, preview: `${c.subject} · Klasse ${c.grade}` }),
  students: (s) => ({ title: s.name, preview: `Position ${s.sortOrder}` }),
  timetable_plans: (p) => ({ title: p.name || "Plan", preview: `gültig ab ${p.validFrom}` }),
  lessons: (l) => ({ title: l.title, preview: `${l.subject}${l.date ? " · " + l.date : ""}` }),
  stoff_plans: (p) => ({ title: p.title, preview: `${(p.blocks || []).length} Blöcke · ${p.status}` }),
  timetable_entries: (e) => ({ title: e.label || "Stundenplan-Eintrag", preview: `${e.weekday != null ? ttWEEKDAYS[e.weekday] : ""} · ${e.weekType}` }),
  timetable_overrides: (o) => ({ title: o.label || "Vertretung", preview: o.date }),
  calendar_entries: (e) => ({ title: e.title, preview: e.entryDate }),
  reflections: (r) => ({ title: r.lessonTitle || "Reflexion", preview: r.ampelSummary || "" }),
  asuv_drafts: (a) => ({ title: "ASUV-Entwurf", preview: a.ziele ? a.ziele.slice(0, 60) : "" }),
  sequenz_stunden: (s) => ({ title: s.title, preview: s.date || "kein Datum" }),
  seat_plans: (p) => ({ title: p.name, preview: `${p.rows || "?"}×${p.cols || "?"}` }),
};

let _syncConflictsModulePromise = null;
function getSyncConflictsModule() {
  if (!_syncConflictsModulePromise) {
    _syncConflictsModulePromise = import("./sync-conflicts.js").then((mod) => mod.createSyncConflictsModule({
      $, esc, toast, SyncEngine, entityRenderers: SYNC_ENTITY_RENDERERS,
    }));
  }
  return _syncConflictsModulePromise;
}

// Sidebar-Badge: zeigt/versteckt sich je nachdem, ob ungelöste Sync-Konflikte oder
// fehlgeschlagene Mutationen vorliegen (jede Entität, nicht nur notes) — aktualisiert bei
// jeder SyncEngine-Änderung. "failed" sonst unsichtbar in der Queue stecken (siehe push()).
async function updateSyncConflictBadge() {
  const btn = $("syncConflictBtn");
  if (!btn) return;
  const [conflicts, failed] = await Promise.all([SyncEngine.getConflicts(), SyncEngine.getFailed()]);
  const total = conflicts.length + failed.length;
  btn.classList.toggle("hidden", total === 0);
  const label = $("syncConflictBtnLabel");
  if (label) label.textContent = `Sync-Probleme (${total})`;
}

let _notizenModulePromise = null;
function getNotizenModule() {
  if (!_notizenModulePromise) {
    _notizenModulePromise = import("./notizen.js").then((mod) => mod.createNotizenModule({
      $, esc, API, toast, state, refresh, SyncEngine, parseNoteId,
      noteTitle, notePreviewText, noteScopeLabel, noteDateLabel, activeNotesSorted,
    }));
  }
  return _notizenModulePromise;
}

async function renderArchivNotizen() {
  const wrap = $("archivNotizen");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let rows = [];
  try { rows = await API.get("/notes?archived=true"); }
  catch (e) { wrap.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
  wrap.innerHTML = "";
  if (!rows.length) { wrap.innerHTML = '<p class="muted small">Keine archivierten Notizen.</p>'; return; }
  rows.forEach((n) => {
    const cls = n.classId ? state.classes.find((c) => c.id === n.classId) : null;
    const label = n.scope === "allgemein" ? "Allgemein" : (cls ? cls.name : "Klasse (archiviert)");
    const preview = (n.bodyMd || "").trim().replace(/\s+/g, " ").slice(0, 80) || "(leer)";
    const div = document.createElement("div");
    div.className = "archiv-row";
    div.innerHTML =
      `<span class="archiv-main">${esc(label)}</span>` +
      `<span class="muted small">${esc(preview)}</span>` +
      `<span class="archiv-actions">` +
      `<button class="btn small secondary" data-restore-note="${n.id}">Wiederherstellen</button>` +
      `<button class="btn small danger" data-hard-note="${n.id}">Endgültig löschen</button></span>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-restore-note]").forEach((b) => {
    b.onclick = async () => {
      try { await API.post("/notes/" + b.dataset.restoreNote + "/restore"); await refresh(); renderArchivNotizen(); toast("Notiz wiederhergestellt."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-hard-note]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Notiz endgültig löschen? Das kann nicht rückgängig gemacht werden.")) return;
      try { await API.del("/notes/" + b.dataset.hardNote); await refresh(); renderArchivNotizen(); toast("Notiz endgültig gelöscht."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

async function init() {
  wireEvents();
  initOfflineSupport();  // U23: Service Worker + Offline-Banner
  try {
    await startApp();  // vorhandene Session?
  } catch (e) {
    setAuthMode("login");
    showAuth(true);
  }
}
document.addEventListener("DOMContentLoaded", init);

/* ===== U23: Offline (nur lesen) — additiver Block ===================================
   - Registriert den Service Worker (Shell-Precache + API-GET-Cache).
   - Zeigt ein dezentes Banner, solange keine Internetverbindung besteht.
   - Meldet fehlgeschlagene Schreibversuche offline als klare Toast-Meldung. */
function updateOfflineBanner() {
  const banner = $("offlineBanner");
  if (banner) banner.classList.toggle("hidden", navigator.onLine !== false);
  // Online-Gating (F5) für zwingend netzabhängige Features an dieselbe online/offline-
  // Umschaltung koppeln, die auch das Banner steuert.
  applyAiGating(state.aiActive);
  applyGoogleStatus();
}
function initOfflineSupport() {
  // Service Worker registrieren (nur über HTTPS/localhost verfügbar; robust gekapselt).
  if ("serviceWorker" in navigator) {
    try {
      navigator.serviceWorker.register("/sw.js").catch(() => { /* SW optional — kein Absturz */ });
    } catch (_) { /* nicht unterstützt — ignorieren */ }
  }
  window.addEventListener("online", updateOfflineBanner);
  window.addEventListener("offline", updateOfflineBanner);
  updateOfflineBanner();
  SyncEngine.init();
  SyncEngine.onChange(updateSyncConflictBadge);
  updateSyncConflictBadge();
}
/* ===== Ende U23-Block =============================================================== */

/* ===== Offline-Sync (Fundament, F4): Klassen-Detail-Mini-Notizen (cdNote*) auf
   Hintergrund-Sync-Ergebnisse reagieren lassen — Pull/Push laufen unabhängig vom aktuell
   sichtbaren View; ohne diese Subscription bliebe state.notes nach einem Hintergrund-Sync
   veraltet, bis der Nutzer manuell neu lädt. Die parallele Notizen-Hauptansicht abonniert
   unabhängig in notizen.js selbst (eigene Selektions-Variable, siehe dortiger Kommentar). */
SyncEngine.onChange(async (entityType, info) => {
  if (entityType !== "notes") return;
  if (info.idRemaps) {
    const remap = info.idRemaps.find((r) => r.oldId === cdNoteSelectedId);
    if (remap) cdNoteSelectedId = remap.newId;
  }
  state.notes = await SyncEngine.materialize("notes");
  renderCdNoteList();
  renderCdNoteEditor();
});

// Rollout (Tranche 1): todos — Heute-Ansicht nach Hintergrund-Sync aktuell halten. Keine
// Auswahl-id zu remappen (Checkbox/Löschen-Button greifen nicht auf eine gehaltene id zu,
// sondern lesen dataset bei jedem Render neu), daher einfacher als der notes-Fall.
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "todos") return;
  const all = await SyncEngine.materialize("todos");
  state.todos = all.filter((t) => t.archivedAt == null);
  renderTodos();
});

// Rollout (Tranche 1): calendar_categories — Kategorie-Manager in den Einstellungen und
// die Kalender-Legende hängen an state.calendarCategories.
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "calendar_categories") return;
  const all = await SyncEngine.materialize("calendar_categories");
  state.calendarCategories = all.slice()
    .sort((a, b) => (a.sortOrder - b.sortOrder) || (String(a.id).localeCompare(String(b.id))));
  renderCategoryManager();
  renderCalendarLegend();
});

// Rollout (Tranche 1): school_years — nur "anlegen" ist verdrahtet (keine Update/Delete-UI
// im Frontend vorhanden); Ferien/Feiertage (school_dates) bleiben separat online-only.
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "school_years") return;
  const all = await SyncEngine.materialize("school_years");
  state.schoolYears = all.slice().sort((a, b) => String(a.startDate).localeCompare(String(b.startDate)));
  renderSchoolYears();
});

// Rollout (Tranche 2): classes — praktisch überall referenziert (Klassenliste, Auswahllisten,
// Kalender-Legende, Detailseite). Archivierte Klassen bleiben außerhalb von state.classes
// (eigene Abfrage in der Archiv-Ansicht, renderArchivKlassen), wie bisher.
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "classes") return;
  const all = await SyncEngine.materialize("classes");
  state.classes = all.filter((c) => c.archivedAt == null)
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  renderClassTable();
  renderClassSelects();
});

// Rollout (Tranche 2): students — nur relevant, während die Klassen-Detailseite offen ist.
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "students" || !detailClassId) return;
  if (!document.getElementById("cdStudentList")) return; // Detailseite gerade nicht sichtbar
  await renderClassStudents();
});

// Rollout (Tranche 3): lessons — Stundenliste, Filteroptionen und Home-„heute"-Liste hängen
// an state.lessons; renderAll() ist günstig genug (rein synchrones DOM-Rendering aus state),
// hier wie bei classes/todos direkt aufgerufen statt einzelner View-Funktionen.
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "lessons") return;
  const all = await SyncEngine.materialize("lessons");
  state.lessons = all.slice()
    .sort((a, b) => String(a.createdAt || "").localeCompare(String(b.createdAt || "")) || String(a.id).localeCompare(String(b.id)));
  renderLessonFilterOptions();
  renderLessonTable();
  await renderTodayList();
});

// Rollout (Tranche 3): stoff_plans — drei Anzeigeorte teilen sich die Entität: die
// dedizierte Stoffplan-Ansicht (lazy-Modul, nur nachziehen falls schon geöffnet), die
// Klassen-Detailseite und die Home-„aktive Pläne"-Vorschau (state.activePlans).
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "stoff_plans") return;
  if (_stoffplanModuleInstance) await _stoffplanModuleInstance.loadStoffPlans();
  if (document.getElementById("cdStoffPlans")) await renderClassDetailStoffPlans();
  await loadActivePlans();   // state.activePlans wird von Kalender/Präsentation erst beim nächsten eigenen Render gelesen
});

// Rollout (Tranche 3): timetable_overrides — fließen serverseitig in /stundenplan/resolved
// ein (blasse Stundenplan-Ebene im Kalender), das der Client per calTtCache cached. Nach
// Hintergrund-Sync bleibt nur die Cache-Invalidierung + ein Re-Render nötig, kein eigener
// Materialize-Zyklus (die Wochenansicht holt sich die aufgelöste Ansicht ohnehin neu vom Server).
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "timetable_overrides") return;
  calTtCache.clear();
  await renderTodayList();
  await renderWeekOverview();
  renderCalendar();
});

// Rollout (Tranche 4): reflections — reines Journal (kein Update/Delete). /reflections/open
// bleibt Online-REST (serverseitig berechnete Sicht), daher hier nur das Journal selbst
// (state.reflections) nachziehen.
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "reflections") return;
  const all = await SyncEngine.materialize("reflections");
  state.reflections = all.slice()
    .sort((a, b) => String(b.createdAt || "").localeCompare(String(a.createdAt || "")) || String(b.id).localeCompare(String(a.id)));
  renderReflectTable();
});

// Rollout (Tranche 4 — letzte Einheit): seat_plans — Liste in der Klassen-Detailseite nur
// nachziehen, falls das Sitzplan-Modul schon geladen wurde (lazy import, siehe sitzplan.js).
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "seat_plans" || !_seatPlanModuleInstance) return;
  await _seatPlanModuleInstance.renderSeatPlanList();
});

// Rollout (Tranche 4): asuv_drafts — bewusst KEINE onChange-Subscription. Anders als
// Listen-Ansichten ist der ASUV-Editor ein Formular für genau EINEN Entwurf, das der Nutzer
// gerade aktiv bearbeitet; ein automatisches Re-Render bei jedem Hintergrund-Sync-Ereignis
// würde ungespeicherte Eingaben überschreiben. loadAsuv() liest bereits bei jedem Öffnen den
// aktuellen Stand (materialize() mit REST-Fallback), das genügt.

// Rollout (Tranche 3 — letzte Einheit): calendar_entries. Archivierte Einträge bleiben wie
// bisher außerhalb von state.calendar (eigene Abfrage in renderArchivKalender, analog
// classes/todos), Reihenfolge wie ORDER BY entry_date.
SyncEngine.onChange(async (entityType) => {
  if (entityType !== "calendar_entries") return;
  const all = await SyncEngine.materialize("calendar_entries");
  state.calendar = all.filter((e) => e.archivedAt == null)
    .sort((a, b) => String(a.entryDate).localeCompare(String(b.entryDate)));
  await renderTodayList();
  await renderWeekOverview();
  renderCalendar();
});
