/* Lehrer-Dashboard – Frontend-Logik (M3). Ersetzt den localStorage-Prototyp durch
   echte API-Calls (api.js). Daten kommen ausschließlich aus dem Backend. */
"use strict";

const meyerMerkmale = [
  "Klare Strukturierung", "Hoher Anteil echter Lernzeit", "Lernförderliches Klima",
  "Inhaltliche Klarheit", "Sinnstiftendes Kommunizieren", "Methodenvielfalt",
  "Individuelles Fördern", "Intelligentes Üben", "Transparente Leistungserwartungen",
  "Vorbereitete Umgebung",
];
const phaseNames = ["Einstieg", "Erarbeitung", "Sicherung", "Abschluss"];
const TRANSPARENT_PX = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";

const $ = (id) => document.getElementById(id);
const state = {
  user: null, classes: [], lessons: [], reflections: [], open: [], materials: [], todos: [],
  schoolYears: [], schoolDates: [], calendar: [],
};
const lbCache = {};                 // Lernbereiche je Fach|Stufe|Bildungsgang
let calMode = "month";
let calCursor = new Date();

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
    row.innerHTML =
      `<span class="name">${i + 1}. ${esc(name)}</span>
       <div class="ampel-select" data-idx="${i}">
         <button type="button" class="ampel-btn g" data-val="gruen"></button>
         <button type="button" class="ampel-btn y" data-val="gelb"></button>
         <button type="button" class="ampel-btn r" data-val="rot"></button>
       </div>`;
    wrap.appendChild(row);
  });
  wrap.querySelectorAll(".ampel-select").forEach((sel) => {
    sel.querySelectorAll(".ampel-btn").forEach((btn) => {
      btn.onclick = () => {
        sel.querySelectorAll(".ampel-btn").forEach((b) => b.classList.remove("selected"));
        btn.classList.add("selected");
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
function resetMeyerGrid(containerId) {
  $(containerId).querySelectorAll(".ampel-btn.selected").forEach((b) => b.classList.remove("selected"));
}
function setMeyerGrid(containerId, values) {
  $(containerId).querySelectorAll(".ampel-select").forEach((sel, i) => {
    sel.querySelectorAll(".ampel-btn").forEach((b) => b.classList.remove("selected"));
    const v = (values || [])[i];
    if (v) { const t = sel.querySelector(`.ampel-btn[data-val="${v}"]`); if (t) t.classList.add("selected"); }
  });
}

/* ---------- Phasentabelle ---------- */
function buildPhases() {
  const wrap = $("phases");
  wrap.innerHTML = "";
  phaseNames.forEach((p, i) => {
    const div = document.createElement("div");
    div.className = "phase";
    div.innerHTML =
      `<strong>${p}</strong>
       <div class="row-4" style="margin-top:10px;">
         <input placeholder="Zeit (Min.)" id="time${i}" />
         <select id="social${i}"><option>EA</option><option>PA</option><option>GA</option><option>Plenum</option></select>
         <input placeholder="Methode" id="method${i}" />
         <input placeholder="Material/Raum" id="material${i}" />
       </div>
       <label>Lehrertätigkeit</label><textarea id="teacher${i}"></textarea>
       <label>Schülertätigkeit</label><textarea id="student${i}"></textarea>
       <label>Differenzierung (G/M/E)</label><textarea id="gme${i}"></textarea>`;
    wrap.appendChild(div);
  });
}
function readPhases() {
  const phases = [];
  phaseNames.forEach((name, i) => {
    const minutes = $("time" + i).value.trim();
    const method = $("method" + i).value.trim();
    const material = $("material" + i).value.trim();
    const teacher = $("teacher" + i).value.trim();
    const student = $("student" + i).value.trim();
    const gme = $("gme" + i).value.trim();
    if (minutes || method || material || teacher || student || gme) {
      phases.push({
        phaseName: name,
        minutes: minutes ? Number(minutes) : null,
        socialForm: $("social" + i).value,
        method, material, teacherActivity: teacher, studentActivity: student, gme,
      });
    }
  });
  return phases;
}
function clearLessonForm() {
  ["lessonIdeas", "lessonTitle", "lessonDate", "klafki1", "klafki2", "klafki3", "klafki4", "klafki5",
   "biboxWerk", "biboxSeite", "biboxNotiz"].forEach((id) => ($(id).value = ""));
  $("lessonClass").value = "";
  phaseNames.forEach((_, i) =>
    ["time", "method", "material", "teacher", "student", "gme"].forEach((k) => ($(k + i).value = "")));
  resetMeyerGrid("meyerPlanGrid");
  $("diff").value = "ja";
  $("lernen").value = "ja";
}

/* ---------- Laden & Rendern ---------- */
async function loadAll() {
  const [classes, lessons, reflections, open, materials, todos, schoolYears, calendar] = await Promise.all([
    API.get("/classes"), API.get("/lessons"), API.get("/reflections"),
    API.get("/reflections/open"), API.get("/materials"), API.get("/todos"),
    API.get("/school-years"), API.get("/calendar"),
  ]);
  let schoolDates = [];
  for (const sy of schoolYears) {
    try { schoolDates = schoolDates.concat(await API.get(`/school-years/${sy.id}/dates`)); }
    catch (e) { /* best effort */ }
  }
  Object.assign(state, { classes, lessons, reflections, open, materials, todos, schoolYears, calendar, schoolDates });
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
  $("kpiClasses").textContent = state.classes.length;
  $("kpiLessons").textContent = state.lessons.length;
  $("kpiReflect").textContent = state.reflections.length;
  $("kpiMaterial").textContent = state.materials.length;
  $("openReflectCount").textContent =
    state.open.length + (state.open.length === 1 ? " Reflexion offen" : " Reflexionen offen");
  $("openLessonCount").textContent =
    state.lessons.length + (state.lessons.length === 1 ? " Stunde geplant" : " Stunden geplant");

  renderClassTable();
  renderLessonTable();
  renderTodayList();
  renderReflectSelect();
  renderReflectTable();
  renderOpenReflections();
  renderTodos();
  renderClassSelects();
  renderClassToggles();
  renderSchoolYears();
  renderCalendar();
  renderTimeline();
  renderMaterialList();
  renderAsuvLessonSelect();
}

function renderClassTable() {
  const b = document.querySelector("#classTable tbody");
  b.innerHTML = "";
  state.classes.forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${esc(c.name)}</td><td>${esc(c.subject)}</td><td>${esc(c.grade)}</td>` +
      `<td>${esc(c.track || "")}</td><td>${esc(c.weeklyHours)}</td><td>${esc(c.parallelGroup || "")}</td>` +
      `<td><button class="btn small danger" data-del-class="${c.id}">entfernen</button></td>`;
    b.appendChild(tr);
  });
  b.querySelectorAll("[data-del-class]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("Klasse archivieren? Bereits geplante Stunden bleiben erhalten.")) return;
      try { await API.del("/classes/" + btn.dataset.delClass); await refresh(); toast("Klasse archiviert."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

function renderLessonTable() {
  const b = document.querySelector("#lessonTable tbody");
  b.innerHTML = "";
  state.lessons.forEach((l) => {
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

function renderTodayList() {
  const list = $("todayLessonList");
  list.innerHTML = "";
  if (!state.lessons.length) {
    list.innerHTML = '<p class="small" style="color:#dcfce7;">Noch keine Stunden geplant.</p>';
    return;
  }
  state.lessons.forEach((l) => {
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
      try { await API.post("/reflections/skip", { lessonId: Number(btn.dataset.skip) }); await refresh(); toast("Übersprungen."); }
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
    div.innerHTML =
      `<input type="checkbox" ${t.done ? "checked" : ""} data-todo="${t.id}"/>` +
      `<span class="todo-src ${t.source}">${esc(t.source)}</span>` +
      `<span style="flex:1">${esc(t.text)}</span>` +
      `<button class="btn small danger" data-del-todo="${t.id}">✕</button>`;
    list.appendChild(div);
  });
  list.querySelectorAll("[data-todo]").forEach((cb) => {
    cb.onchange = async () => {
      try { await API.put("/todos/" + cb.dataset.todo, { done: cb.checked }); await refresh(); }
      catch (e) { toast(e.message, false); }
    };
  });
  list.querySelectorAll("[data-del-todo]").forEach((btn) => {
    btn.onclick = async () => {
      try { await API.del("/todos/" + btn.dataset.delTodo); await refresh(); }
      catch (e) { toast(e.message, false); }
    };
  });
}

/* ---------- Auswahllisten / Filter / Schuljahre ---------- */
function renderClassSelects() {
  const opts = state.classes.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.subject)})</option>`).join("");
  $("lessonClass").innerHTML = '<option value="">– keine –</option>' + opts;
  $("calEntryClass").innerHTML = opts;
  $("planClass").innerHTML = opts;
  $("planYear").innerHTML = state.schoolYears.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join("");
  $("matYear").innerHTML = '<option value="">– kein Schuljahr –</option>' +
    state.schoolYears.map((s) => `<option value="${s.id}">${esc(s.label)}</option>`).join("");
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
      `<span class="tag-row">${tags}<button class="btn small danger" data-del-mat="${m.id}">✕</button></span>`;
    wrap.appendChild(div);
  });
  wrap.querySelectorAll("[data-del-mat]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Material löschen?")) return;
      try { await API.del("/materials/" + b.dataset.delMat); await refresh(); toast("Material gelöscht."); }
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

function renderClassToggles() {
  const row = $("classToggleRow");
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
      try { await API.put("/classes/" + inp.dataset.id, { visibleInCalendar: inp.checked }); await refresh(); }
      catch (e) { toast(e.message, false); }
    };
  });
}

async function renderTimeline() {
  const wrap = $("classTimeline");
  if (!wrap) return;
  wrap.innerHTML = "";
  const colors = ["#16a34a", "#eab308", "#f97316", "#0ea5e9", "#22c55e", "#a855f7"];
  for (const c of state.classes) {
    if (c.visibleInCalendar === false) continue;
    let lbs = [];
    try { lbs = await getLernbereiche(c); } catch (e) { /* ignore */ }
    const blocks = lbs.map((e, j) =>
      `<div class="timeline-block" style="background:${colors[j % colors.length]}">${esc(e.code)} ${esc(e.title)} (${e.richtwertUstd == null ? "?" : e.richtwertUstd} Std.)</div>`).join("");
    const rowEl = document.createElement("div");
    rowEl.className = "timeline-row";
    rowEl.innerHTML = `<div class="timeline-label">${esc(c.name)} (${esc(c.subject)})</div><div class="timeline-track">${blocks || '<span class="muted small">Kein Plan</span>'}</div>`;
    wrap.appendChild(rowEl);
  }
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
function visibleClassIds() { return state.classes.filter((c) => c.visibleInCalendar !== false).map((c) => c.id); }
function entriesForDate(dStr) {
  const vis = visibleClassIds();
  return state.calendar.filter((e) => e.entryDate === dStr && (e.classId == null || vis.includes(e.classId)));
}
function schoolDateFor(dStr) {
  return state.schoolDates.find((s) => s.startDate <= dStr && dStr <= s.endDate);
}
function renderCalendar() {
  const grid = $("calGrid");
  if (!grid) return;
  grid.innerHTML = "";
  ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].forEach((d) => {
    const h = document.createElement("div"); h.className = "cal-head"; h.textContent = d; grid.appendChild(h);
  });
  const todayStr = isoDate(new Date());
  const makeCell = (d, other) => {
    const dStr = isoDate(d);
    const cell = document.createElement("div");
    cell.className = "cal-cell" + (other ? " otherMonth" : "") + (dStr === todayStr ? " today" : "");
    const sd = schoolDateFor(dStr);
    if (sd) { cell.style.background = sd.kind === "feiertag" ? "#fde68a" : "#e5e7eb"; cell.title = sd.name; }
    cell.innerHTML = `<div class="cal-daynum">${d.getDate()}</div>` +
      entriesForDate(dStr).map((e) =>
        `<div class="cal-entry ${esc(e.entryType)}" data-lesson="${e.lessonId == null ? "" : e.lessonId}">${esc(e.title)}</div>`).join("");
    return cell;
  };
  if (calMode === "month") {
    const y = calCursor.getFullYear(), m = calCursor.getMonth();
    $("calLabel").textContent = calCursor.toLocaleDateString("de-DE", { month: "long", year: "numeric" });
    const startOffset = (new Date(y, m, 1).getDay() + 6) % 7;
    const startDate = new Date(y, m, 1 - startOffset);
    for (let i = 0; i < 42; i++) { const d = new Date(startDate); d.setDate(startDate.getDate() + i); grid.appendChild(makeCell(d, d.getMonth() !== m)); }
  } else {
    const d0 = new Date(calCursor); d0.setDate(d0.getDate() - ((d0.getDay() + 6) % 7));
    $("calLabel").textContent = "Woche " + isoWeek(d0) + ", " + d0.toLocaleDateString("de-DE", { year: "numeric" });
    for (let i = 0; i < 7; i++) { const d = new Date(d0); d.setDate(d0.getDate() + i); grid.appendChild(makeCell(d, false)); }
  }
  grid.querySelectorAll("[data-lesson]").forEach((el) => {
    const lid = el.dataset.lesson;
    if (lid) el.onclick = () => { const l = state.lessons.find((x) => String(x.id) === lid); if (l) openLessonModal(l); };
  });
}

async function saveCalendarEntry() {
  const title = $("calEntryTitle").value.trim(), date = $("calEntryDate").value;
  if (!title || !date) { toast("Bitte Titel und Datum angeben.", false); return; }
  try {
    await API.post("/calendar", {
      title, entryDate: date, entryType: $("calEntryType").value,
      classId: $("calEntryClass").value ? Number($("calEntryClass").value) : null,
      isFixed: $("calEntryFixed").checked,
    });
    $("calEntryTitle").value = ""; $("calEntryFixed").checked = false;
    await refresh(); toast("Termin gespeichert.");
  } catch (e) { toast(e.message, false); }
}

async function saveSchoolYear() {
  const label = $("syLabel").value.trim(), start = $("syStart").value, end = $("syEnd").value;
  if (!label || !start || !end) { toast("Bitte Bezeichnung, Beginn und Ende angeben.", false); return; }
  try {
    await API.post("/school-years", { label, startDate: start, endDate: end });
    $("syLabel").value = ""; await refresh(); toast("Schuljahr angelegt (Ferien/Feiertage abgerufen).");
  } catch (e) { toast(e.message, false); }
}

/* ---------- Jahres-Verplanung ---------- */
async function runPlanning() {
  const syId = Number($("planYear").value), clsId = Number($("planClass").value);
  if (!syId || !clsId) { toast("Bitte Schuljahr und Klasse wählen.", false); return; }
  try {
    const res = await API.post("/planning/preview", { schoolYearId: syId, classId: clsId });
    $("planSummary").textContent =
      `${res.planned} von ${res.planned + res.unplaced} Lernbereichen verplant · ${res.teachingWeeks} Unterrichtswochen`;
    const b = document.querySelector("#planTable tbody");
    b.innerHTML = "";
    res.blocks.forEach((x) => {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${esc(x.code)}</td><td>${esc(x.title)}</td><td>${esc(x.ustd)}</td><td>${esc(x.weeks)}</td>` +
        `<td>${esc(x.startDate)} – ${esc(x.endDate)}</td>` +
        `<td>${x.conflictWithFixed ? '<span class="badge bad">Konflikt fixer Termin</span>' : "—"}</td>`;
      b.appendChild(tr);
    });
    // Direkt-Upload zu einem Lernbereich freischalten
    const card = $("stoffUploadCard");
    $("stoffLb").innerHTML = res.blocks.filter((x) => x.lernbereichId)
      .map((x) => `<option value="${x.lernbereichId}">${esc(x.code)} ${esc(x.title)}</option>`).join("");
    card.dataset.syId = syId;
    card.dataset.clsId = clsId;
    card.style.display = res.blocks.length ? "block" : "none";
  } catch (e) { toast(e.message, false); }
}

async function stoffUpload() {
  const f = $("stoffFile").files[0];
  const lbId = $("stoffLb").value;
  if (!f || !lbId) { toast("Bitte Lernbereich und Datei wählen.", false); return; }
  const card = $("stoffUploadCard");
  const cls = state.classes.find((c) => String(c.id) === card.dataset.clsId);
  const fd = new FormData();
  fd.append("file", f);
  if (cls) { fd.append("subject", cls.subject); fd.append("grade", cls.grade); }
  if (card.dataset.syId) fd.append("schoolYearId", card.dataset.syId);
  fd.append("lernbereichId", lbId);
  try { await API.upload("/materials/upload", fd); $("stoffFile").value = ""; await refresh(); toast("Material mit Lernbereich verknüpft."); }
  catch (e) { toast(e.message, false); }
}

/* ---------- Stunden-Detail-Modal ---------- */
function openLessonModal(l) {
  const meyer = (l.meyerPlan || [])
    .map((v, i) => `<span class="mini-meyer-chip" style="background:${ampelColor(v)}">${i + 1}. ${esc(meyerMerkmale[i])}</span>`)
    .join(" ");
  const phases = (l.phases || [])
    .map((p) =>
      `<div class="phase"><strong>${esc(p.phaseName)}</strong> (${esc(p.minutes ?? "–")} Min., ${esc(p.socialForm || "–")})<br>` +
      `<span class="small muted">Methode: ${esc(p.method || "–")} – Material: ${esc(p.material || "–")}</span><br>` +
      `<span class="small">L: ${esc(p.teacherActivity || "–")}</span><br>` +
      `<span class="small">S: ${esc(p.studentActivity || "–")}</span></div>`)
    .join("") || '<p class="muted small">Noch keine Phasen erfasst.</p>';
  const k = l.klafki || {};
  const kLabels = [["gegenwart", "Gegenwartsbedeutung"], ["zukunft", "Zukunftsbedeutung"],
    ["exemplarisch", "Exemplarische Bedeutung"], ["zugang", "Zugänglichkeit/Einstieg"], ["struktur", "Struktur des Inhalts"]];
  const klafki = kLabels.filter(([f]) => k[f]).map(([f, lab]) => `<p class="small"><strong>${lab}:</strong> ${esc(k[f])}</p>`).join("")
    || '<p class="muted small">Noch keine Angaben.</p>';
  const bibox = l.bibox && l.bibox.werk
    ? `<p class="small"><strong>Lehrwerk:</strong> ${esc(l.bibox.werk)} – ${esc(l.bibox.seite || "")} ${l.bibox.notiz ? "– " + esc(l.bibox.notiz) : ""}</p>`
    : '<p class="muted small">Keine Lehrbuch-Referenz hinterlegt.</p>';
  $("modalRoot").innerHTML =
    `<div class="modal-overlay" id="modalOverlay"><div class="modal-box">
      <button class="modal-close" id="modalCloseBtn">Schließen</button>
      <button class="btn small secondary" id="modalAsuvBtn" style="float:right; margin-right:10px;">ASUV-Entwurf</button>
      <h2>${esc(l.title)}</h2>
      <p class="muted small">${esc(l.subject)} – Klasse ${esc(l.grade || "?")} – ${esc(l.lessonType || "")} ${l.time ? "– " + esc(l.time) + " Uhr" : ""}</p>
      <div class="modal-section"><h3>Klafki</h3>${klafki}</div>
      <div class="modal-section"><h3>Meyer-Merkmale (geplant)</h3>${meyer || '<p class="muted small">Noch keine Angaben.</p>'}</div>
      <div class="modal-section"><h3>Phasentabelle</h3>${phases}</div>
      <div class="modal-section"><h3>Lehrbuch-Referenz</h3>${bibox}</div>
      <div class="modal-section"><h3>Material zu dieser Stunde</h3>
        <div id="modalMaterials" class="file-list" style="margin-bottom:8px;"></div>
        <input type="file" id="modalMatFile" />
        <button class="btn small" id="modalMatUpload" style="margin-top:6px;">Hochladen &amp; verknüpfen</button>
      </div>
    </div></div>`;
  $("modalOverlay").onclick = (e) => { if (e.target.id === "modalOverlay") closeModal(); };
  $("modalCloseBtn").onclick = closeModal;
  $("modalAsuvBtn").onclick = () => { closeModal(); showView("asuv"); loadAsuv(l.id); };
  loadModalMaterials(l);
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
async function loadModalMaterials(l) {
  const wrap = document.getElementById("modalMaterials");
  if (!wrap) return;
  try {
    const mats = await API.get(`/lessons/${l.id}/materials`);
    wrap.innerHTML = mats.length
      ? mats.map((m) => `<div class="file-chip"><span><a href="/api/materials/${m.id}/download">${esc(m.filename)}</a></span></div>`).join("")
      : '<p class="muted small">Noch kein Material verknüpft.</p>';
  } catch (e) { wrap.innerHTML = ""; }
}
function closeModal() { $("modalRoot").innerHTML = ""; }

/* ---------- Speichern ---------- */
async function saveClass() {
  const name = $("className").value.trim();
  if (!name) { toast("Bitte einen Klassennamen angeben.", false); return; }
  try {
    await API.post("/classes", {
      name, subject: $("classSubject").value, grade: Number($("classGrade").value),
      track: $("classTrack").value, weeklyHours: Number($("classHours").value) || 2,
      parallelGroup: $("classGroup").value.trim() || null,
    });
    $("className").value = ""; $("classGroup").value = "";
    await refresh(); toast("Klasse gespeichert.");
  } catch (e) { toast(e.message, false); }
}

async function saveLesson() {
  const title = $("lessonTitle").value.trim();
  if (!title) { toast("Bitte einen Titel angeben.", false); return; }
  const meyer = readMeyerGrid("meyerPlanGrid");
  try {
    await API.post("/lessons", {
      title, subject: $("lessonSubject").value, grade: Number($("lessonGrade").value),
      lessonType: $("lessonType").value, time: null,
      classId: $("lessonClass").value ? Number($("lessonClass").value) : null,
      date: $("lessonDate").value || null,
      klafki: {
        gegenwart: $("klafki1").value, zukunft: $("klafki2").value, exemplarisch: $("klafki3").value,
        zugang: $("klafki4").value, struktur: $("klafki5").value,
      },
      meyerPlan: meyer.some((v) => v) ? meyer : null,
      diff: $("diff").value, selbstLernen: $("lernen").value,
      bibox: { werk: $("biboxWerk").value, seite: $("biboxSeite").value, notiz: $("biboxNotiz").value },
      phases: readPhases(),
    });
    clearLessonForm(); await refresh(); toast("Stunde gespeichert.");
  } catch (e) { toast(e.message, false); }
}

async function saveReflect() {
  const lessonId = Number($("reflectLesson").value);
  if (!lessonId) { toast("Bitte eine Stunde wählen.", false); return; }
  const meyer = readMeyerGrid("meyerReflectGrid");
  try {
    await API.post("/reflections", {
      lessonId, meyerIst: meyer.some((v) => v) ? meyer : null, text: $("reflectText").value,
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
    state.aiActive = s.apiKeyStatus === "aktiv";
    applyAiGating(state.aiActive);
    renderAiUsage();
  } catch (e) { toast(e.message, false); }
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

function renderAsuvLessonSelect() {
  const sel = $("asuvLesson");
  if (!sel) return;
  sel.innerHTML = state.lessons.map((l) => `<option value="${l.id}">${esc(l.title)} (${esc(l.subject)} ${esc(l.grade || "")})</option>`).join("");
}

async function loadAsuv(lessonId) {
  asuvLessonId = Number(lessonId);
  if (!asuvLessonId) return;
  $("asuvLesson").value = String(asuvLessonId);
  const lesson = state.lessons.find((l) => l.id === asuvLessonId);
  $("asuvHeadline").textContent = "ASUV-Entwurf: " + (lesson ? lesson.title : "");
  try {
    const a = await API.get(`/lessons/${asuvLessonId}/asuv`);
    ASUV_FIELDS.forEach(([id, key]) => { $(`asuv_${id}`).value = a[key] || ""; });
    $("asuvBiboxHint").style.display = a.biboxEmpty ? "block" : "none";
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
      $("asuvPhases").innerHTML = (lesson.phases || []).map((p) =>
        `<div class="phase"><strong>${esc(p.phaseName)}</strong> (${esc(p.minutes == null ? "–" : p.minutes)} Min., ${esc(p.socialForm || "–")})<br>` +
        `<span class="small muted">Methode: ${esc(p.method || "–")} – Material: ${esc(p.material || "–")}</span><br>` +
        `<span class="small">L: ${esc(p.teacherActivity || "–")} · S: ${esc(p.studentActivity || "–")}</span></div>`).join("")
        || '<p class="muted small">Noch keine Phasen erfasst.</p>';
      $("asuvBibox").textContent = lesson.bibox && lesson.bibox.werk
        ? `Lehrwerk: ${lesson.bibox.werk} – ${lesson.bibox.seite || ""} ${lesson.bibox.notiz || ""}`
        : "Keine Lehrbuch-Referenz hinterlegt.";
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
  try { await API.put(`/lessons/${asuvLessonId}/asuv`, body); toast("ASUV gespeichert."); }
  catch (e) { toast(e.message, false); }
}

function exportAsuv(fmt) {
  if (!asuvLessonId) { toast("Bitte eine Stunde wählen.", false); return; }
  const a = document.createElement("a");
  a.href = `/api/lessons/${asuvLessonId}/asuv/export?format=${fmt}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/* ---------- KI (Meilenstein 7) ---------- */
function applyAiGating(active) {
  ["aiPlanBtn", "stoffAiBtn", "asuvAiBtn"].forEach((id) => {
    const b = $(id);
    if (b) { b.disabled = !active; b.title = active ? "" : "Kein API-Key hinterlegt – in den Einstellungen eintragen"; }
  });
}
async function refreshAiStatus() {
  try { const s = await API.get("/settings"); state.aiActive = s.apiKeyStatus === "aktiv"; }
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
  if (!ideas) { toast("Bitte zuerst Ideen im Ideenfeld eintragen.", false); return; }
  const btn = $("aiPlanBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ generiere …";
  try {
    const res = await API.post("/ai/lesson-suggestion",
      { ideas, subject: $("lessonSubject").value, grade: Number($("lessonGrade").value) });
    const s = res.suggestion || {};
    if (s.title && !$("lessonTitle").value) $("lessonTitle").value = s.title;
    if (s.klafki) {
      $("klafki1").value = s.klafki.gegenwart || ""; $("klafki2").value = s.klafki.zukunft || "";
      $("klafki3").value = s.klafki.exemplarisch || ""; $("klafki4").value = s.klafki.zugang || "";
      $("klafki5").value = s.klafki.struktur || "";
    }
    if (Array.isArray(s.meyerPlan)) setMeyerGrid("meyerPlanGrid", s.meyerPlan);
    (s.phases || []).forEach((p, i) => {
      if (i >= phaseNames.length) return;
      $("time" + i).value = p.minutes == null ? "" : p.minutes;
      $("social" + i).value = p.socialForm || "EA";
      $("method" + i).value = p.method || ""; $("material" + i).value = p.material || "";
      $("teacher" + i).value = p.teacherActivity || ""; $("student" + i).value = p.studentActivity || "";
      $("gme" + i).value = p.gme || "";
    });
    toast(res.cached ? "KI-Vorschlag (aus Cache) eingefügt." : "KI-Vorschlag eingefügt – bitte prüfen.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; btn.textContent = label; }
}

async function aiStoffplan() {
  const syId = Number($("planYear").value), clsId = Number($("planClass").value);
  if (!syId || !clsId) { toast("Bitte Schuljahr und Klasse wählen.", false); return; }
  const btn = $("stoffAiBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ generiere …";
  try {
    const res = await API.post("/ai/stoffplan", { schoolYearId: syId, classId: clsId });
    const blocks = (res.suggestion && res.suggestion.blocks) || [];
    $("planSummary").textContent = `KI-Vorschlag: ${blocks.length} Lernbereiche` + (res.cached ? " (aus Cache)" : "");
    const b = document.querySelector("#planTable tbody");
    b.innerHTML = "";
    blocks.forEach((x) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(x.code)}</td><td>${esc(x.title)}</td><td>${esc(x.ustd)}</td>` +
        `<td>${esc(x.weeks)}</td><td>—</td><td>${esc(x.note || "")}</td>`;
      b.appendChild(tr);
    });
    toast(res.cached ? "KI-Stoffplan (aus Cache)." : "KI-Stoffplan-Vorschlag erzeugt.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; btn.textContent = label; }
}

async function aiAsuvSuggest() {
  if (!asuvLessonId) { toast("Bitte eine Stunde wählen.", false); return; }
  const btn = $("asuvAiBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ formuliere …";
  try {
    const res = await API.post(`/ai/asuv/${asuvLessonId}`, {});
    const s = res.suggestion || {};
    ASUV_FIELDS.forEach(([id, key]) => { if (s[key]) $(`asuv_${id}`).value = s[key]; });
    toast(res.cached ? "ASUV-Vorschlag (aus Cache)." : "ASUV ausformuliert – bitte prüfen.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; btn.textContent = label; }
}

/* ---------- Navigation ---------- */
const titles = {
  heute: ["Schulalltag heute", "Dein Tag auf einen Blick."],
  klassen: ["Klassen", "Klassen und Parallelgruppen anlegen und verwalten."],
  kalender: ["Planungskalender", "Monat, Woche und Lernbereichs-Zeitleiste (folgt in M4)."],
  stoff: ["Stoffverteilungsplan", "Lehrplanbasierte Jahresplanung (folgt in M4)."],
  stunde: ["Unterrichtsplanung", "Ideenfeld, Phasentabelle und abschließende Klafki-/Meyer-Reflexion."],
  reflexion: ["Reflexion", "Offene Reflexionen ansehen, überspringen oder erfassen."],
  asuv: ["ASUV-Entwürfe", "Ausführlicher schriftlicher Unterrichtsentwurf je Stunde (folgt in M6)."],
  material: ["Materialbibliothek", "Material hochladen, taggen und wiederfinden (folgt in M5)."],
  settings: ["Einstellungen", "API-Key und Konto."],
};
function showView(view) {
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $(view).classList.remove("hidden");
  $("pageTitle").textContent = titles[view][0];
  $("pageSub").textContent = titles[view][1];
  if (view === "settings") loadSettings();
  if (view === "asuv" && state.lessons.length) loadAsuv(asuvLessonId || state.lessons[0].id);
  closeMobileNav();
}
function closeMobileNav() { $("sidebarNav").classList.remove("open"); $("navBackdrop").classList.remove("open"); }

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
    showAuth(false);
    await startApp();
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
  $("avatarImg").src = me.avatarPath || TRANSPARENT_PX;
  const now = new Date();
  $("sidebarDate").textContent = now.toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "long" });
  $("sidebarKW").textContent = "Kalenderwoche " + isoWeek(now);
  await refresh();
  await refreshAiStatus();
}

function wireEvents() {
  buildMeyerGrid("meyerPlanGrid");
  buildMeyerGrid("meyerReflectGrid");
  buildPhases();

  document.querySelectorAll(".nav-btn").forEach((btn) => (btn.onclick = () => showView(btn.dataset.view)));
  document.querySelectorAll("[data-view-target]").forEach((el) => (el.onclick = () => showView(el.dataset.viewTarget)));

  const burger = $("burgerBtn");
  burger.onclick = () => {
    const open = $("sidebarNav").classList.toggle("open");
    $("navBackdrop").classList.toggle("open", open);
  };
  $("navBackdrop").onclick = closeMobileNav;

  $("saveClass").onclick = saveClass;
  $("saveLesson").onclick = saveLesson;
  $("saveReflect").onclick = saveReflect;

  // Kalender
  $("calPrevBtn").onclick = () => { calCursor.setDate(calCursor.getDate() - (calMode === "week" ? 7 : 30)); renderCalendar(); };
  $("calNextBtn").onclick = () => { calCursor.setDate(calCursor.getDate() + (calMode === "week" ? 7 : 30)); renderCalendar(); };
  $("calMonthBtn").onclick = () => { calMode = "month"; $("calMonthBtn").classList.add("active"); $("calWeekBtn").classList.remove("active"); renderCalendar(); };
  $("calWeekBtn").onclick = () => { calMode = "week"; $("calWeekBtn").classList.add("active"); $("calMonthBtn").classList.remove("active"); renderCalendar(); };
  $("calSaveEntryBtn").onclick = saveCalendarEntry;
  $("saveSchoolYear").onclick = saveSchoolYear;
  $("planPreviewBtn").onclick = runPlanning;
  $("stoffUpload").onclick = stoffUpload;

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
  $("stoffAiBtn").onclick = aiStoffplan;
  $("asuvAiBtn").onclick = aiAsuvSuggest;
  $("lessonType").addEventListener("change", (e) =>
    $("lueHint").classList.toggle("hidden", e.target.value !== "Übungsstunde vor LUE"));

  $("newTodoInput").addEventListener("keydown", async (e) => {
    if (e.key === "Enter" && e.target.value.trim()) {
      try { await API.post("/todos", { text: e.target.value.trim(), source: "manuell" }); e.target.value = ""; await refresh(); }
      catch (err) { toast(err.message, false); }
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
  $("logoutBtn").onclick = async () => {
    try { await API.post("/auth/logout"); } catch (e) { /* egal */ }
    location.reload();
  };

  $("authSubmit").onclick = submitAuth;
  $("authToggle").onclick = () => setAuthMode(authMode === "login" ? "register" : "login");
  $("authPassword").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); });
}

async function init() {
  wireEvents();
  try {
    await startApp();  // vorhandene Session?
  } catch (e) {
    setAuthMode("login");
    showAuth(true);
  }
}
document.addEventListener("DOMContentLoaded", init);
