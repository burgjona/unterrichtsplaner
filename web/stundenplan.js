/* U27b — Bereich „Mein Stundenplan": persönliches Wochenraster mit A/B-Wochen,
   editierbaren Klingelzeiten, Eintragstypen und Plänen.

   Eigenständiges Modul: app.js wird NICHT angefasst. Registrierung zur Laufzeit über
   die script-übergreifend geteilte `titles`-Registry und einen Klick-Listener auf den
   Nav-Button (läuft NACH app.js' generischem showView-Handler → Section ist sichtbar).
   ALLE Top-Level-Bezeichner tragen das Präfix `tt`/`ttState`, weil app.js (und U27c)
   sich denselben globalen Scope teilen — Namenskollision = Laufzeit-SyntaxError.
   Wiederverwendete Helfer aus app.js/api.js: esc, $, toast, state, API, titles. */
"use strict";

/* Titel-Registry erweitern (script-übergreifend mutierbar; app.js hat sie zuerst angelegt). */
titles.stundenplan = ["Mein Stundenplan", "Dein Wochenraster mit A/B-Wochen und Klingelzeiten."];

const ttWEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"];
/* Fachfarben (wie Backend): Deutsch grün, WTH orange. */
const ttSUBJECT_COLORS = { "Deutsch": "#16a34a", "WTH": "#f97316" };
const ttDEFAULT_COLOR = "#94a3b8";

const ttState = {
  loaded: false, loading: false,
  kinds: [], slots: [], plans: [], entries: [],
  planId: null,
  settings: { weekAParity: "odd", isoWeek: 0, currentWeekType: "A" },
  week: "A",            // aktuell ANGEZEIGTE A/B-Woche (aus currentWeekType vorbelegt)
  editorsOpen: false,   // Editoren-Bereich (Klingelzeiten/Typen/A-B) ein-/ausgeklappt
};

/* ---------- kleine Helfer ---------- */
function ttTodayIso() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function ttTodayWeekday() {         // 0=Mo … 4=Fr, sonst -1 (Wochenende)
  const wd = (new Date().getDay() + 6) % 7;
  return wd <= 4 ? wd : -1;
}
function ttPickActivePlan(plans) {  // größtes validFrom <= heute, Fallback erster Plan
  if (!plans.length) return null;
  const today = ttTodayIso();
  let best = null;
  for (const p of plans) {
    if (p.validFrom <= today && (!best || p.validFrom > best.validFrom)) best = p;
  }
  return (best || plans[0]).id;
}

/* Farb-Herkunft (konsistent zum Backend /resolved): Eintrag-Farbe → Fachfarbe der
   Klasse → Typ-Farbe → Default. */
function ttEntryColor(e) {
  if (e.color) return e.color;
  if (e.classId != null) {
    const c = state.classes.find((x) => x.id === e.classId);
    if (c && ttSUBJECT_COLORS[c.subject]) return ttSUBJECT_COLORS[c.subject];
  }
  const k = ttState.kinds.find((x) => x.id === e.kindId);
  return (k && k.color) ? k.color : ttDEFAULT_COLOR;
}
/* Titel (wie Backend): Label → „{Klasse} {Fach}" → Typ-Name. */
function ttEntryTitle(e) {
  if (e.label) return e.label;
  if (e.classId != null) {
    const c = state.classes.find((x) => x.id === e.classId);
    if (c) return `${c.name} ${c.subject}`;
  }
  const k = ttState.kinds.find((x) => x.id === e.kindId);
  return k ? k.name : "";
}
/* Getönter Chip aus EINER Farbe (kein Vollton, kein Farbstreifen-Rand). color-mix ok
   (Single-User, moderner Browser). Farbwert escapen (fließt ins style-Attribut). */
function ttChipStyle(color) {
  const c = esc(color);
  return `background:color-mix(in srgb, ${c} 16%, var(--surface));` +
         `color:color-mix(in srgb, ${c} 78%, #10231a);`;
}

/* ---------- Laden ---------- */
async function ttLoad() {
  ttState.loading = true;
  try {
    const settings = await API.get("/stundenplan/settings");   // löst serverseitiges Seeding aus
    ttState.settings = settings;
    ttState.week = settings.currentWeekType || "A";            // Woche vorbelegen (nur beim Erst-Laden)
    const [kinds, slots, plans] = await Promise.all([
      API.get("/stundenplan/kinds"),
      API.get("/stundenplan/slots"),
      API.get("/stundenplan/plans"),
    ]);
    ttState.kinds = kinds;
    ttState.slots = slots;
    ttState.plans = plans;
    ttState.planId = ttPickActivePlan(plans);
    await ttReloadEntries();
    ttState.loaded = true;
  } finally {
    ttState.loading = false;
  }
}
async function ttReloadEntries() {
  ttState.entries = ttState.planId
    ? await API.get("/stundenplan/entries?planId=" + ttState.planId)
    : [];
}
async function ttReloadSlots() { ttState.slots = await API.get("/stundenplan/slots"); }
async function ttReloadKinds() { ttState.kinds = await API.get("/stundenplan/kinds"); }

/* ---------- Ein-/Anzeigen ---------- */
async function ttShow() {
  if (ttState.loading) return;
  if (!ttState.loaded) {
    ttRenderSkeleton();
    try { await ttLoad(); }
    catch (e) { toast(e.message || "Stundenplan konnte nicht geladen werden.", false); return; }
  }
  ttRenderView();
  ttRenderEditors();
}

/* ---------- Rendern: Skeleton (kein Spinner) ---------- */
function ttRenderSkeleton() {
  const grid = $("ttGrid");
  grid.style.gridTemplateColumns = "56px repeat(5, minmax(0,1fr))";
  grid.style.gridTemplateRows = "auto " + Array(8).fill("52px").join(" ");
  let h = `<div class="tt-corner" style="grid-column:1;grid-row:1;"></div>`;
  for (let w = 0; w < 5; w++)
    h += `<div class="tt-dayhead" style="grid-column:${w + 2};grid-row:1;"><span class="tt-skel tt-skel-head"></span></div>`;
  for (let i = 0; i < 8; i++) {
    h += `<div class="tt-time" style="grid-column:1;grid-row:${i + 2};"><span class="tt-skel tt-skel-time"></span></div>`;
    for (let w = 0; w < 5; w++)
      h += `<div style="grid-column:${w + 2};grid-row:${i + 2};padding:2px;"><span class="tt-skel"></span></div>`;
  }
  grid.innerHTML = h;
  $("ttEmpty").classList.add("hidden");
  $("ttLegend").innerHTML = "";
}

/* ---------- Rendern: Ansicht (Toolbar + Raster + Legende) ---------- */
function ttRenderView() {
  ttRenderToolbar();
  ttRenderGrid();
  ttRenderLegend();
}

function ttRenderToolbar() {
  const s = ttState.settings;
  const planOpts = ttState.plans.map((p) =>
    `<option value="${p.id}"${p.id === ttState.planId ? " selected" : ""}>` +
    `${esc(p.name || "Plan")} · ab ${esc(p.validFrom)}</option>`).join("");
  $("ttToolbar").innerHTML =
    `<div class="tt-toolbar-row">
       <div class="tt-weekinfo">
         <span class="tt-kw">KW ${esc(String(s.isoWeek))}</span>
         <span class="tt-weektype tt-weektype-${esc(s.currentWeekType)}">${esc(s.currentWeekType)}-Woche</span>
       </div>
       <div class="view-toggle tt-abtoggle" role="group" aria-label="A- oder B-Woche anzeigen">
         <button type="button" data-tt-week="A" class="${ttState.week === "A" ? "active" : ""}">A-Woche</button>
         <button type="button" data-tt-week="B" class="${ttState.week === "B" ? "active" : ""}">B-Woche</button>
       </div>
       <div class="tt-toolbar-actions">
         <label class="tt-plan-label">Plan
           <select id="ttPlanSelect" aria-label="Plan auswählen">${planOpts}</select>
         </label>
         <button type="button" class="btn small secondary" id="ttAddPlanBtn">+ Plan</button>
         <button type="button" class="btn small secondary" id="ttSlotsBtn">Klingelzeiten</button>
         <button type="button" class="btn small" id="ttAddEntryBtn">+ Eintrag</button>
       </div>
     </div>`;
  $("ttToolbar").querySelectorAll("[data-tt-week]").forEach((b) => {
    b.onclick = () => { ttState.week = b.dataset.ttWeek; ttRenderView(); };
  });
  $("ttPlanSelect").onchange = ttOnPlanChange;
  $("ttAddPlanBtn").onclick = ttOpenPlanModal;
  $("ttSlotsBtn").onclick = ttToggleEditors;
  $("ttAddEntryBtn").onclick = () => ttOpenEntryModal(null, null);
}

function ttRenderGrid() {
  const grid = $("ttGrid");
  const slots = ttState.slots;
  grid.style.gridTemplateColumns = "56px repeat(5, minmax(0,1fr))";
  grid.style.gridTemplateRows =
    ["auto"].concat(slots.map((s) => s.slotType === "break" ? "34px" : "62px")).join(" ");

  const todayWd = ttTodayWeekday();
  let h = `<div class="tt-corner" style="grid-column:1;grid-row:1;"></div>`;
  for (let w = 0; w < 5; w++) {
    const today = w === todayWd;
    h += `<div class="tt-dayhead" style="grid-column:${w + 2};grid-row:1;">` +
         `<span class="tt-day-pill${today ? " tt-today" : ""}">${esc(ttWEEKDAYS[w])}</span></div>`;
  }
  // Zeitspalte + Pausen-Bänder (Bänder ZUERST → Chips/Zellen darüber gemalt).
  slots.forEach((s, i) => {
    const row = i + 2;
    if (s.slotType === "break") {
      h += `<div class="tt-time tt-time-break" style="grid-column:1;grid-row:${row};">` +
           `<span class="tt-time-range">${esc(s.startTime)}</span></div>`;
      h += `<div class="tt-break-band" style="grid-column:2 / span 5;grid-row:${row};">` +
           `<span class="tt-break-label">${esc(s.label)}</span></div>`;
    } else {
      h += `<div class="tt-time" style="grid-column:1;grid-row:${row};">` +
           `<span class="tt-time-num">${esc(s.label)}</span>` +
           `<span class="tt-time-range">${esc(s.startTime)}</span></div>`;
    }
  });

  // Nur Einträge dieser Woche (both + A|B). Belegte Zellen (inkl. Doppelstunden) merken.
  const idxById = new Map(slots.map((s, i) => [s.id, i]));
  const visible = ttState.entries.filter((e) => e.weekType === "both" || e.weekType === ttState.week);
  const covered = new Set();
  for (const e of visible) {
    const si = idxById.get(e.slotId);
    if (si == null) continue;
    const span = Math.min(e.spanSlots, slots.length - si);
    for (let k = 0; k < span; k++) covered.add(e.weekday + ":" + (si + k));
  }
  // Leere (klickbare) Zellen für nicht belegte Slot/Wochentag-Paare.
  for (let w = 0; w < 5; w++) {
    for (let i = 0; i < slots.length; i++) {
      if (covered.has(w + ":" + i)) continue;
      const isBreak = slots[i].slotType === "break";
      h += `<div class="tt-cell${isBreak ? " tt-cell-break" : ""}" tabindex="0" role="button" ` +
           `aria-label="Eintrag am ${esc(ttWEEKDAYS[w])} anlegen" ` +
           `data-tt-slot="${slots[i].id}" data-tt-wd="${w}" ` +
           `style="grid-column:${w + 2};grid-row:${i + 2};"></div>`;
    }
  }
  // Eintrags-Chips (inline platziert; Doppelstunden spannen Zeilen).
  for (const e of visible) {
    const si = idxById.get(e.slotId);
    if (si == null) continue;
    const span = Math.min(e.spanSlots, slots.length - si);
    const color = ttEntryColor(e);
    const title = ttEntryTitle(e);
    const abPill = e.weekType !== "both" ? `<span class="tt-chip-ab">${esc(e.weekType)}</span>` : "";
    const sub = e.room ? `<span class="tt-chip-sub">${esc(e.room)}</span>` : "";
    h += `<div class="tt-chip" data-tt-entry="${e.id}" tabindex="0" role="button" ` +
         `aria-label="${esc(title)} bearbeiten" ` +
         `style="grid-column:${e.weekday + 2};grid-row:${si + 2} / span ${span};${ttChipStyle(color)}">` +
         abPill +
         `<span class="tt-chip-dot" style="background:${esc(color)}"></span>` +
         `<span class="tt-chip-main"><span class="tt-chip-title">${esc(title)}</span>${sub}</span>` +
         `</div>`;
  }
  grid.innerHTML = h;

  // Verdrahten (Chips = bearbeiten, Zellen = neu). Tastatur: Enter/Space.
  grid.querySelectorAll("[data-tt-entry]").forEach((el) => {
    const open = () => ttOpenEntryModal(
      ttState.entries.find((x) => x.id === Number(el.dataset.ttEntry)) || null, null);
    el.onclick = open;
    el.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } };
  });
  grid.querySelectorAll("[data-tt-slot]").forEach((el) => {
    const open = () => ttOpenEntryModal(null,
      { slotId: Number(el.dataset.ttSlot), weekday: Number(el.dataset.ttWd) });
    el.onclick = open;
    el.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } };
  });

  // Empty-State / Hinweis.
  const emptyEl = $("ttEmpty");
  if (!slots.length) {
    emptyEl.textContent = "Noch keine Klingelzeiten – lege sie im Editor darunter an.";
    emptyEl.classList.remove("hidden");
  } else if (!ttState.entries.length) {
    emptyEl.textContent = "Noch keine Einträge – tippe auf eine Zelle.";
    emptyEl.classList.remove("hidden");
  } else {
    emptyEl.classList.add("hidden");
  }
}

function ttRenderLegend() {
  $("ttLegend").innerHTML = ttState.kinds.map((k) =>
    `<span class="tt-legend-item"><span class="tt-legend-dot" style="background:${esc(k.color)}"></span>` +
    `${esc(k.name)}</span>`).join("");
}

/* ---------- Plan-Wechsel ---------- */
async function ttOnPlanChange() {
  ttState.planId = Number($("ttPlanSelect").value);
  try { await ttReloadEntries(); }
  catch (e) { toast(e.message, false); ttState.entries = []; }
  ttRenderView();
}

/* ---------- Eintrag-Modal (Baumuster openCalendarEventModal, #modalRoot) ---------- */
function ttCloseModal() { $("modalRoot").innerHTML = ""; }

function ttOpenEntryModal(entry, prefill) {
  const kinds = ttState.kinds;
  if (!kinds.length) { toast("Bitte zuerst einen Typ anlegen.", false); return; }
  if (!ttState.slots.length) { toast("Bitte zuerst Klingelzeiten anlegen.", false); return; }
  const isEdit = !!entry;

  let defKind = kinds.find((k) => k.isDefault) || kinds[0];
  if (prefill) {   // Klick auf eine Pausen-Zelle → „Aufsicht" vorschlagen, falls vorhanden
    const slot = ttState.slots.find((s) => s.id === prefill.slotId);
    if (slot && slot.slotType === "break") {
      const auf = kinds.find((k) => /aufsicht/i.test(k.name));
      if (auf) defKind = auf;
    }
  }
  const cur = entry || {
    kindId: defKind.id, classId: null, label: "", room: "", weekType: "both",
    weekday: prefill ? prefill.weekday : 0,
    slotId: prefill ? prefill.slotId : ttState.slots[0].id,
    spanSlots: 1, color: null,
  };

  const kindOpts = kinds.map((k) =>
    `<option value="${k.id}"${k.id === cur.kindId ? " selected" : ""}>${esc(k.name)}</option>`).join("");
  const classOpts = `<option value="">— keine —</option>` +
    state.classes.filter((c) => !c.archivedAt).map((c) =>
      `<option value="${c.id}"${c.id === cur.classId ? " selected" : ""}>${esc(c.name)} (${esc(c.subject)})</option>`).join("");
  const slotOpts = ttState.slots.map((s) =>
    `<option value="${s.id}"${s.id === cur.slotId ? " selected" : ""}>` +
    `${esc(s.label)} · ${esc(s.startTime)}–${esc(s.endTime)}${s.slotType === "break" ? " (Pause)" : ""}</option>`).join("");
  const wdOpts = ttWEEKDAYS.map((n, i) =>
    `<option value="${i}"${i === cur.weekday ? " selected" : ""}>${esc(n)}</option>`).join("");
  const weekOpts = [["both", "Beide Wochen"], ["A", "Nur A-Woche"], ["B", "Nur B-Woche"]].map(
    ([v, l]) => `<option value="${v}"${cur.weekType === v ? " selected" : ""}>${l}</option>`).join("");
  const spanOpts = [1, 2, 3, 4].map((n) =>
    `<option value="${n}"${n === cur.spanSlots ? " selected" : ""}>${n === 1 ? "1 Stunde" : n + " Stunden"}</option>`).join("");
  const autoColor = !cur.color;
  const colorVal = cur.color || "#16a34a";

  $("modalRoot").innerHTML =
    `<div class="modal-overlay" id="ttModalOverlay"><div class="modal-box">
      <button class="modal-close" id="ttModalClose">Schließen</button>
      <h2>${isEdit ? "Eintrag bearbeiten" : "Neuer Eintrag"}</h2>
      <div class="modal-section">
        <div class="row">
          <div><label>Typ</label><select id="ttfKind">${kindOpts}</select></div>
          <div><label>Klasse</label><select id="ttfClass">${classOpts}</select></div>
        </div>
        <div class="row">
          <div><label>Bezeichnung (optional)</label><input id="ttfLabel" value="${esc(cur.label || "")}" placeholder="überschreibt Klasse/Fach" /></div>
          <div><label>Raum (optional)</label><input id="ttfRoom" value="${esc(cur.room || "")}" /></div>
        </div>
        <div class="row-3">
          <div><label>Wochentag</label><select id="ttfWeekday">${wdOpts}</select></div>
          <div><label>Stunde / Slot</label><select id="ttfSlot">${slotOpts}</select></div>
          <div><label>Dauer</label><select id="ttfSpan">${spanOpts}</select></div>
        </div>
        <div class="row">
          <div><label>Woche</label><select id="ttfWeek">${weekOpts}</select></div>
          <div>
            <label>Farbe</label>
            <div class="tt-color-row">
              <input type="color" id="ttfColor" value="${esc(colorVal)}"${autoColor ? " disabled" : ""} />
              <label class="tt-auto-color"><input type="checkbox" id="ttfAutoColor"${autoColor ? " checked" : ""} /> automatisch</label>
            </div>
          </div>
        </div>
      </div>
      <div style="margin-top:14px; display:flex; gap:8px; flex-wrap:wrap;">
        <button class="btn" id="ttfSave">Speichern</button>
        ${isEdit ? `<button class="btn danger" id="ttfDelete">Löschen</button>` : ""}
        <button class="btn secondary" id="ttfCancel">Abbrechen</button>
      </div>
    </div></div>`;
  $("ttModalOverlay").onclick = (ev) => { if (ev.target.id === "ttModalOverlay") ttCloseModal(); };
  $("ttModalClose").onclick = ttCloseModal;
  $("ttfCancel").onclick = ttCloseModal;
  $("ttfAutoColor").onchange = () => { $("ttfColor").disabled = $("ttfAutoColor").checked; };
  $("ttfSave").onclick = () => ttSaveEntry(isEdit ? entry.id : null);
  if (isEdit) $("ttfDelete").onclick = () => ttDeleteEntry(entry.id);
}

async function ttSaveEntry(id) {
  if (!ttState.planId) { toast("Kein Plan ausgewählt.", false); return; }
  const body = {
    planId: ttState.planId,
    slotId: Number($("ttfSlot").value),
    kindId: Number($("ttfKind").value),
    classId: $("ttfClass").value ? Number($("ttfClass").value) : null,
    weekday: Number($("ttfWeekday").value),
    weekType: $("ttfWeek").value,
    spanSlots: Number($("ttfSpan").value),
    label: $("ttfLabel").value.trim() || null,
    room: $("ttfRoom").value.trim() || null,
    color: $("ttfAutoColor").checked ? null : $("ttfColor").value,
  };
  try {
    if (id) await API.put("/stundenplan/entries/" + id, body);
    else await API.post("/stundenplan/entries", body);
    ttCloseModal();
    await ttReloadEntries();
    ttRenderView();
    toast(id ? "Eintrag aktualisiert." : "Eintrag angelegt.");
  } catch (e) { toast(e.message, false); }
}

async function ttDeleteEntry(id) {
  if (!confirm("Diesen Eintrag wirklich löschen?")) return;
  try {
    await API.del("/stundenplan/entries/" + id);
    ttCloseModal();
    await ttReloadEntries();
    ttRenderView();
    toast("Eintrag gelöscht.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- Plan-Modal (+ Plan) ---------- */
function ttOpenPlanModal() {
  $("modalRoot").innerHTML =
    `<div class="modal-overlay" id="ttModalOverlay"><div class="modal-box" style="max-width:460px;">
      <button class="modal-close" id="ttModalClose">Schließen</button>
      <h2>Neuer Plan</h2>
      <div class="modal-section">
        <label>Name (optional)</label>
        <input id="ttpName" placeholder="z. B. Halbjahr 2" />
        <label>Gültig ab</label>
        <input id="ttpFrom" type="date" value="${esc(ttTodayIso())}" />
        <label class="tt-auto-color" style="margin-top:12px;">
          <input type="checkbox" id="ttpCopy" /> Einträge aus dem aktuellen Plan übernehmen
        </label>
      </div>
      <div style="margin-top:14px; display:flex; gap:8px; flex-wrap:wrap;">
        <button class="btn" id="ttpSave">Plan anlegen</button>
        <button class="btn secondary" id="ttpCancel">Abbrechen</button>
      </div>
    </div></div>`;
  $("ttModalOverlay").onclick = (ev) => { if (ev.target.id === "ttModalOverlay") ttCloseModal(); };
  $("ttModalClose").onclick = ttCloseModal;
  $("ttpCancel").onclick = ttCloseModal;
  $("ttpSave").onclick = ttSavePlan;
}

async function ttSavePlan() {
  const validFrom = $("ttpFrom").value;
  if (!validFrom) { toast("Bitte ein Datum angeben, ab dem der Plan gilt.", false); return; }
  const body = {
    name: $("ttpName").value.trim(),
    validFrom,
    copyFromPlanId: $("ttpCopy").checked ? ttState.planId : null,
  };
  try {
    const plan = await API.post("/stundenplan/plans", body);
    ttCloseModal();
    ttState.plans = await API.get("/stundenplan/plans");
    ttState.planId = plan.id;
    await ttReloadEntries();
    ttRenderView();
    toast("Plan angelegt.");
  } catch (e) { toast(e.message, false); }
}

/* ---------- Editoren (Klingelzeiten / Typen / A-B-Parität) ---------- */
function ttToggleEditors() {
  ttState.editorsOpen = !ttState.editorsOpen;
  ttRenderEditors();
  if (ttState.editorsOpen) $("ttEditors").scrollIntoView({ behavior: "smooth", block: "start" });
}

function ttRenderEditors() {
  const wrap = $("ttEditors");
  wrap.classList.toggle("hidden", !ttState.editorsOpen);
  if (!ttState.editorsOpen) { wrap.innerHTML = ""; return; }
  wrap.innerHTML = ttRenderSlotsEditor() + ttRenderKindsEditor() + ttRenderParityEditor();
  ttWireSlotsEditor(wrap);
  ttWireKindsEditor(wrap);
  ttWireParityEditor(wrap);
}

function ttRenderSlotsEditor() {
  const rows = ttState.slots.map((s) => `
    <tr data-tt-slotrow="${s.id}">
      <td><input data-f="label" value="${esc(s.label)}" /></td>
      <td><select data-f="slotType">
        <option value="lesson"${s.slotType === "lesson" ? " selected" : ""}>Stunde</option>
        <option value="break"${s.slotType === "break" ? " selected" : ""}>Pause</option>
      </select></td>
      <td><input type="time" data-f="startTime" value="${esc(s.startTime)}" /></td>
      <td><input type="time" data-f="endTime" value="${esc(s.endTime)}" /></td>
      <td><input type="number" data-f="position" value="${esc(String(s.position))}" style="width:64px;" /></td>
      <td class="tt-row-actions">
        <button type="button" class="btn small secondary" data-tt-slotsave="${s.id}">Speichern</button>
        <button type="button" class="btn small danger" data-tt-slotdel="${s.id}">Löschen</button>
      </td>
    </tr>`).join("");
  return `<div class="card tt-editor-card">
    <h3>Klingelzeiten</h3>
    <p class="muted small">Stunden und Pausen des Rasters. „Löschen" entfernt auch die daran hängenden Einträge.</p>
    <div class="table-scroll"><table class="tt-slot-table">
      <thead><tr><th>Label</th><th>Art</th><th>von</th><th>bis</th><th>Pos.</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <button type="button" class="btn small secondary" id="ttSlotAdd" style="margin-top:8px;">+ Zeile</button>
  </div>`;
}

function ttWireSlotsEditor(wrap) {
  wrap.querySelectorAll("[data-tt-slotsave]").forEach((b) => {
    b.onclick = async () => {
      const id = Number(b.dataset.ttSlotsave);
      const tr = wrap.querySelector(`[data-tt-slotrow="${id}"]`);
      const g = (f) => tr.querySelector(`[data-f="${f}"]`).value;
      const body = {
        label: g("label").trim(), slotType: g("slotType"),
        startTime: g("startTime"), endTime: g("endTime"), position: Number(g("position")),
      };
      if (!body.label) { toast("Bitte ein Label angeben.", false); return; }
      if (!body.startTime || !body.endTime) { toast("Bitte Start- und Endzeit angeben.", false); return; }
      try {
        await API.put("/stundenplan/slots/" + id, body);
        await ttReloadSlots(); await ttReloadEntries();
        ttRenderView(); ttRenderEditors(); toast("Klingelzeit gespeichert.");
      } catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-tt-slotdel]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Diese Zeile löschen? Daran hängende Einträge werden entfernt.")) return;
      try {
        await API.del("/stundenplan/slots/" + Number(b.dataset.ttSlotdel));
        await ttReloadSlots(); await ttReloadEntries();
        ttRenderView(); ttRenderEditors(); toast("Klingelzeit gelöscht.");
      } catch (e) { toast(e.message, false); }
    };
  });
  const add = wrap.querySelector("#ttSlotAdd");
  if (add) add.onclick = async () => {
    const maxPos = ttState.slots.reduce((m, s) => Math.max(m, s.position), -1);
    try {
      await API.post("/stundenplan/slots",
        { position: maxPos + 1, slotType: "lesson", label: "Neu", startTime: "07:00", endTime: "07:45" });
      await ttReloadSlots(); ttRenderView(); ttRenderEditors(); toast("Zeile hinzugefügt.");
    } catch (e) { toast(e.message, false); }
  };
}

function ttRenderKindsEditor() {
  const rows = ttState.kinds.map((k) => `
    <div class="cal-cat-row" data-tt-kindrow="${k.id}">
      <input type="color" value="${esc(k.color)}" data-f="color" />
      <input type="text" value="${esc(k.name)}" data-f="name" />
      ${k.isDefault ? `<span class="badge tt-default-badge">Standard</span>` : ""}
      <button type="button" class="btn small secondary" data-tt-kindsave="${k.id}">Speichern</button>
      ${k.isDefault ? "" : `<button type="button" class="btn small danger" data-tt-kinddel="${k.id}">Löschen</button>`}
    </div>`).join("");
  return `<div class="card tt-editor-card">
    <h3>Typen</h3>
    <p class="muted small">Farbe und Name der Eintragstypen. Der Standard-Typ kann nicht gelöscht werden.</p>
    ${rows}
    <div class="tt-kind-add">
      <input type="color" id="ttKindNewColor" value="#0ea5e9" />
      <input type="text" id="ttKindNewName" placeholder="Neuer Typ" />
      <button type="button" class="btn small" id="ttKindAdd">+ Typ</button>
    </div>
  </div>`;
}

function ttWireKindsEditor(wrap) {
  wrap.querySelectorAll("[data-tt-kindsave]").forEach((b) => {
    b.onclick = async () => {
      const id = Number(b.dataset.ttKindsave);
      const row = wrap.querySelector(`[data-tt-kindrow="${id}"]`);
      const name = row.querySelector('[data-f="name"]').value.trim();
      const color = row.querySelector('[data-f="color"]').value;
      if (!name) { toast("Bitte einen Namen angeben.", false); return; }
      try {
        await API.put("/stundenplan/kinds/" + id, { name, color });
        await ttReloadKinds(); ttRenderView(); ttRenderEditors(); toast("Typ gespeichert.");
      } catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-tt-kinddel]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Diesen Typ löschen? Einträge dieses Typs wechseln auf den Standard-Typ.")) return;
      try {
        await API.del("/stundenplan/kinds/" + Number(b.dataset.ttKinddel));
        await ttReloadKinds(); await ttReloadEntries();
        ttRenderView(); ttRenderEditors(); toast("Typ gelöscht.");
      } catch (e) { toast(e.message, false); }
    };
  });
  const add = wrap.querySelector("#ttKindAdd");
  if (add) add.onclick = async () => {
    const name = wrap.querySelector("#ttKindNewName").value.trim();
    const color = wrap.querySelector("#ttKindNewColor").value;
    if (!name) { toast("Bitte einen Namen angeben.", false); return; }
    const maxSort = ttState.kinds.reduce((m, k) => Math.max(m, k.sortOrder), -1);
    try {
      await API.post("/stundenplan/kinds", { name, color, sortOrder: maxSort + 1 });
      await ttReloadKinds(); ttRenderView(); ttRenderEditors(); toast("Typ angelegt.");
    } catch (e) { toast(e.message, false); }
  };
}

function ttRenderParityEditor() {
  const s = ttState.settings;
  return `<div class="card tt-editor-card">
    <h3>A/B-Wochen</h3>
    <label>A-Woche liegt auf</label>
    <select id="ttParitySelect">
      <option value="odd"${s.weekAParity === "odd" ? " selected" : ""}>ungeraden Kalenderwochen</option>
      <option value="even"${s.weekAParity === "even" ? " selected" : ""}>geraden Kalenderwochen</option>
    </select>
    <p class="muted small" style="margin-top:8px;">Aktuell: KW ${esc(String(s.isoWeek))} = ${esc(s.currentWeekType)}-Woche.</p>
  </div>`;
}

function ttWireParityEditor(wrap) {
  const sel = wrap.querySelector("#ttParitySelect");
  if (!sel) return;
  sel.onchange = async () => {
    try {
      ttState.settings = await API.put("/stundenplan/settings", { weekAParity: sel.value });
      ttRenderView(); ttRenderEditors(); toast("A/B-Einstellung gespeichert.");
    } catch (e) { toast(e.message, false); }
  };
}

/* ---------- Registrierung: Klick auf den Nav-Button (nach app.js' showView) ---------- */
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.querySelector('.nav-btn[data-view="stundenplan"]');
  if (btn) btn.addEventListener("click", ttShow);
});
