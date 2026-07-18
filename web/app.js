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
let editingStoffPlanId = null;        // gerade im Inline-Editor geöffneter Plan (U12)
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
/* ---------- Lernziele-Editor (M11) ---------- */
let lessonZiele = [];   // [{kind:'grob'|'fein', text, bloomStufe, phaseSortOrder}]

function renderLernziele() {
  const wrap = $("lernzieleList");
  if (!wrap) return;
  if (!lessonZiele.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine Lernziele. „Ziel hinzufügen“ oder „✨ Lernziele vorschlagen“.</p>';
    return;
  }
  wrap.innerHTML = lessonZiele.map((z, i) => {
    const isGrob = z.kind === "grob";
    const bloomOpts = ['<option value="">– Bloom-Stufe –</option>']
      .concat(BLOOM_STUFEN.map((b) => `<option value="${b}" ${z.bloomStufe === b ? "selected" : ""}>${b}</option>`)).join("");
    const phaseOpts = ['<option value="">– keine Phase –</option>']
      .concat(phaseNames.map((p, pi) => `<option value="${pi}" ${String(z.phaseSortOrder) === String(pi) ? "selected" : ""}>${esc(p)}</option>`)).join("");
    return `<div class="phase" style="margin-top:8px;">
      <div class="row-4" style="margin-top:0;">
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
function readLernziele() {
  return lessonZiele
    .filter((z) => (z.text || "").trim())
    .map((z, i) => ({ kind: z.kind, text: z.text.trim(), bloomStufe: z.bloomStufe || null,
                      phaseSortOrder: z.phaseSortOrder == null ? null : Number(z.phaseSortOrder), sortOrder: i }));
}

function clearLessonForm() {
  ["lessonIdeas", "lessonTitle", "lessonDate", "klafki1", "klafki2", "klafki3", "klafki4", "klafki5",
   "biboxWerk", "biboxSeite", "biboxNotiz"].forEach((id) => ($(id).value = ""));
  $("lessonClass").value = "";
  $("lessonDuration").value = "45";
  phaseNames.forEach((_, i) =>
    ["time", "method", "material", "teacher", "student", "gme"].forEach((k) => ($(k + i).value = "")));
  resetMeyerGrid("meyerPlanGrid");
  $("diff").value = "ja";
  $("lernen").value = "ja";
  lessonZiele = [];
  renderLernziele();
  $("lueHint").classList.toggle("hidden", $("lessonType").value !== "Übungsstunde vor LUE");
}

/* ---------- Bearbeitungsmodus Unterrichtsplanung ---------- */
let editingLessonId = null;
function resetLessonEditState() {
  editingLessonId = null;
  $("editHint").classList.add("hidden");
  const h = $("stundeEinordnungHint");
  if (h) { h.classList.add("hidden"); $("stundeEinordnungResult").textContent = ""; }
}
function loadLessonIntoForm(l) {
  clearLessonForm();
  editingLessonId = l.id;
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
  $("lessonDate").value = l.date || "";
  $("lessonDuration").value = String(l.durationMinutes || 45);
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
  (l.phases || []).forEach((p) => {
    const i = phaseNames.indexOf(p.phaseName);
    if (i < 0) return;
    $("time" + i).value = p.minutes == null ? "" : p.minutes;
    $("social" + i).value = p.socialForm || "EA";
    $("method" + i).value = p.method || ""; $("material" + i).value = p.material || "";
    $("teacher" + i).value = p.teacherActivity || ""; $("student" + i).value = p.studentActivity || "";
    $("gme" + i).value = p.gme || "";
  });
  $("editHintTitle").textContent = l.title || "";
  $("editHint").classList.remove("hidden");
  // Freie Stunde ohne Lernbereich: KI-Einordnungshinweis anbieten.
  const h = $("stundeEinordnungHint");
  if (h) {
    $("stundeEinordnungResult").textContent = "";
    h.classList.toggle("hidden", l.lernbereichId != null);
  }
}

/* ---------- Laden & Rendern ---------- */
async function loadAll() {
  const [classes, lessons, reflections, open, materials, todos, notes, schoolYears, calendar, calendarCategories] = await Promise.all([
    API.get("/classes"), API.get("/lessons"), API.get("/reflections"),
    API.get("/reflections/open"), API.get("/materials"), API.get("/todos"),
    API.get("/notes"), API.get("/school-years"), API.get("/calendar"), API.get("/calendar-categories"),
  ]);
  let schoolDates = [];
  for (const sy of schoolYears) {
    try { schoolDates = schoolDates.concat(await API.get(`/school-years/${sy.id}/dates`)); }
    catch (e) { /* best effort */ }
  }
  Object.assign(state, { classes, lessons, reflections, open, materials, todos, notes, schoolYears, calendar, calendarCategories, schoolDates });
  await loadActivePlans();
}

// U15: aktive Stoffpläne aller Klassen laden (nur Lesezugriff auf bestehende Endpunkte).
// Ergebnis: state.activePlans[classId] = { planId, title, blocks:[{lbCode,title,ustd,startDate,endDate}] }
async function loadActivePlans() {
  const activePlans = {};
  await Promise.all(state.classes.map(async (c) => {
    try {
      const plans = await API.get(`/stoff-plans?classId=${c.id}`);
      const active = plans.find((p) => p.status === "aktiv");
      if (!active) return;
      const detail = await API.get(`/stoff-plans/${active.id}`);
      activePlans[c.id] = { planId: active.id, title: detail.title, blocks: detail.blocks || [] };
    } catch (e) { /* best effort – ohne aktiven Plan bleibt das bisherige Verhalten */ }
  }));
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
  renderCategoryManager();
  renderCategorySelect();
  renderCalendar();
  renderCalendarLegend();
  renderTimeline();
  renderMaterialList();
  renderAsuvLessonSelect();
  renderPraesentControls();
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
      try { await API.del("/classes/" + btn.dataset.delClass); await refresh(); toast("Klasse archiviert."); }
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
let detailClassId = null;
function openClassDetail(cid) {
  detailClassId = cid;
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
    lessons.forEach((l) => {
      const div = document.createElement("div");
      div.className = "mini-item";
      div.style.cursor = "pointer";
      div.innerHTML =
        `<span class="time">${esc(l.date || "–")}</span>` +
        `<span>${esc(l.title)} <span class="muted small">(${esc(l.lessonType || "Stunde")})</span></span>`;
      div.onclick = () => openLessonModal(l);
      wrap.appendChild(div);
    });
  }
  renderClassStudents();
  renderClassDupControl();
  initSeatPlan();
  renderClassDetailStoffPlans();
}

/* ---------- U16: Plan für Parallelklasse duplizieren (Klassen-Detail) ---------- */
async function renderClassDupControl() {
  const wrap = $("cdDupBody");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let plans = [];
  try { plans = await API.get(`/stoff-plans?classId=${detailClassId}`); }
  catch (e) { wrap.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
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
    const planId = Number($("cdDupPlan").value);
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

async function renderClassDetailStoffPlans() {
  const wrap = $("cdStoffPlans");
  if (!wrap) return;
  try {
    detailStoffPlans = await API.get(`/stoff-plans?classId=${detailClassId}`);
  } catch (e) { detailStoffPlans = []; }
  if (!detailStoffPlans.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine gespeicherten Stoffverteilungspläne für diese Klasse.</p>';
    return;
  }
  wrap.innerHTML = detailStoffPlans.map((p) => {
    const badge = p.status === "aktiv"
      ? '<span class="badge ok">aktiv</span>' : '<span class="badge warn">Entwurf</span>';
    const meta = `${esc(p.blockCount ?? 0)} Blöcke · zuletzt geändert ${esc((p.updatedAt || "").slice(0, 10))}`;
    return `<div class="cd-stoff-row" data-cd-plan="${p.id}">
      <div class="cd-stoff-head">
        <div><strong>${esc(p.title)}</strong> ${badge}<br><span class="small muted">${meta}</span></div>
        <div class="cd-stoff-actions">
          <button class="btn small" data-cd-open="${p.id}">Öffnen</button>
          <button class="btn small secondary" data-cd-pdf="${p.id}">Als PDF</button>
        </div>
      </div>
      <div class="cd-stoff-blocks" data-cd-blocks="${p.id}"></div>
    </div>`;
  }).join("");
  wrap.querySelectorAll("[data-cd-open]").forEach((b) => b.onclick = () => toggleClassDetailStoffPlan(Number(b.dataset.cdOpen)));
  wrap.querySelectorAll("[data-cd-pdf]").forEach((b) => b.onclick = () => downloadStoffPlanPdf(Number(b.dataset.cdPdf)));
  if (openStoffPlanId != null) showClassDetailStoffBlocks(openStoffPlanId);
}

async function toggleClassDetailStoffPlan(id) {
  openStoffPlanId = (openStoffPlanId === id) ? null : id;
  // andere geöffnete Blöcke einklappen
  document.querySelectorAll("#cdStoffPlans [data-cd-blocks]").forEach((el) => { el.innerHTML = ""; });
  if (openStoffPlanId != null) await showClassDetailStoffBlocks(openStoffPlanId);
}

async function showClassDetailStoffBlocks(id) {
  const box = document.querySelector(`#cdStoffPlans [data-cd-blocks="${id}"]`);
  if (!box) return;
  let p;
  try { p = await API.get(`/stoff-plans/${id}`); }
  catch (e) { toast(e.message, false); return; }
  const blocks = p.blocks || [];
  if (!blocks.length) {
    box.innerHTML = '<p class="muted small">Keine Blöcke in diesem Plan.</p>';
    return;
  }
  const rows = blocks.map((b) => {
    const zeit = (b.startDate || b.endDate) ? `${esc(b.startDate || "?")} – ${esc(b.endDate || "?")}` : "—";
    return `<tr>
      <td>${esc(b.lbCode || "")}</td>
      <td>${esc(b.title || "")}</td>
      <td>${esc(b.ustd ?? "")}</td>
      <td>${zeit}</td>
      <td>${esc(b.conflictNote || "—")}</td>
    </tr>`;
  }).join("");
  box.innerHTML = `<div class="table-scroll"><table class="cd-stoff-table">
    <thead><tr><th>LB</th><th>Thema</th><th>Ustd.</th><th>Zeitraum</th><th>Bemerkung</th></tr></thead>
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

let detailStudents = [];
async function renderClassStudents() {
  const wrap = $("cdStudentList");
  if (!wrap) return;
  try {
    detailStudents = await API.get(`/classes/${detailClassId}/students`);
  } catch (e) { toast(e.message, false); return; }
  // U18: Sitzplan-Dropdowns hängen an der Schülerliste – nach (Neu-)Laden aktualisieren.
  if (typeof seatPlan !== "undefined" && seatPlan.grid.length) renderSeatGrid();
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
      `<button class="btn small danger" data-student-del="${s.id}">✕</button>`;
    wrap.appendChild(row);
  });
  wrap.querySelectorAll("[data-student-name]").forEach((inp) => {
    inp.onchange = async () => {
      const name = inp.value.trim();
      if (!name) { renderClassStudents(); return; }
      try { await API.put("/students/" + inp.dataset.studentName, { name }); toast("Name gespeichert."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-student-del]").forEach((btn) => {
    btn.onclick = async () => {
      try { await API.del("/students/" + btn.dataset.studentDel); await renderClassStudents(); toast("Schüler entfernt."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-student-up]").forEach((btn) =>
    (btn.onclick = () => moveStudent(Number(btn.dataset.studentUp), -1)));
  wrap.querySelectorAll("[data-student-down]").forEach((btn) =>
    (btn.onclick = () => moveStudent(Number(btn.dataset.studentDown), 1)));
}

async function moveStudent(sid, dir) {
  const idx = detailStudents.findIndex((s) => s.id === sid);
  const other = idx + dir;
  if (idx < 0 || other < 0 || other >= detailStudents.length) return;
  const a = detailStudents[idx], b = detailStudents[other];
  try {
    await API.put("/students/" + a.id, { sortOrder: b.sortOrder });
    await API.put("/students/" + b.id, { sortOrder: a.sortOrder });
    await renderClassStudents();
  } catch (e) { toast(e.message, false); }
}

async function addStudent() {
  const name = $("cdStudentName").value.trim();
  if (!name) return;
  try {
    await API.post(`/classes/${detailClassId}/students`, { name });
    $("cdStudentName").value = "";
    await renderClassStudents(); toast("Schüler hinzugefügt.");
  } catch (e) { toast(e.message, false); }
}

async function addStudentsBulk() {
  const names = $("cdStudentBulk").value.split("\n").map((n) => n.trim()).filter(Boolean);
  if (!names.length) { toast("Keine Namen eingegeben.", false); return; }
  try {
    await API.post(`/classes/${detailClassId}/students/bulk`, { names });
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
// state: aktuell im Editor bearbeiteter Sitzplan (grid = Matrix[row][col] -> {studentId,name}|null)
const seatPlan = { editId: null, rows: 4, cols: 5, grid: [] };

function spEmptyGrid(rows, cols) {
  return Array.from({ length: rows }, () => Array.from({ length: cols }, () => null));
}

function initSeatPlan() {
  seatPlan.editId = null;
  seatPlan.rows = 4;
  seatPlan.cols = 5;
  $("spName").value = "";
  $("spRows").value = "4";
  $("spCols").value = "5";
  $("spAiDesc").value = "";
  seatPlan.grid = spEmptyGrid(seatPlan.rows, seatPlan.cols);
  renderSeatGrid();
  renderSeatPlanList();
  $("spExportBtn").disabled = true;
}

// Baut das Raster aus den Feldern rows/cols neu auf und überträgt bereits gesetzte Plätze.
function spBuildGrid() {
  const rows = Math.max(1, Math.min(12, parseInt($("spRows").value, 10) || 1));
  const cols = Math.max(1, Math.min(12, parseInt($("spCols").value, 10) || 1));
  const next = spEmptyGrid(rows, cols);
  for (let r = 0; r < Math.min(rows, seatPlan.grid.length); r++) {
    for (let c = 0; c < Math.min(cols, seatPlan.grid[r].length); c++) {
      next[r][c] = seatPlan.grid[r][c];
    }
  }
  seatPlan.rows = rows;
  seatPlan.cols = cols;
  seatPlan.grid = next;
  renderSeatGrid();
}

// Namen, die noch keinem Platz zugewiesen sind (für die Dropdowns).
function spAssignedIds() {
  const ids = new Set();
  seatPlan.grid.forEach((row) => row.forEach((cell) => { if (cell && cell.studentId != null) ids.add(cell.studentId); }));
  return ids;
}

function renderSeatGrid() {
  const wrap = $("spGridWrap");
  if (!wrap) return;
  const assigned = spAssignedIds();
  let html = '<div class="sp-board">Tafel / Vorne</div>';
  html += '<div class="sp-grid" style="grid-template-columns:repeat(' + seatPlan.cols + ',minmax(96px,1fr));">';
  for (let r = 0; r < seatPlan.rows; r++) {
    for (let c = 0; c < seatPlan.cols; c++) {
      const cell = seatPlan.grid[r][c];
      const opts = ['<option value="">— leer —</option>'];
      detailStudents.forEach((s) => {
        const sel = cell && String(cell.studentId) === String(s.id) ? " selected" : "";
        const used = assigned.has(s.id) && !(cell && cell.studentId === s.id);
        opts.push(`<option value="${s.id}"${sel}${used ? " disabled" : ""}>${esc(s.name)}</option>`);
      });
      html += `<div class="sp-seat"><span class="sp-seat-pos">R${r + 1}·S${c + 1}</span>` +
        `<select class="sp-seat-select" data-r="${r}" data-c="${c}">${opts.join("")}</select></div>`;
    }
  }
  html += "</div>";
  wrap.innerHTML = html;
  wrap.querySelectorAll(".sp-seat-select").forEach((sel) => {
    sel.onchange = () => {
      const r = Number(sel.dataset.r), c = Number(sel.dataset.c);
      const sid = sel.value ? Number(sel.value) : null;
      if (sid == null) { seatPlan.grid[r][c] = null; }
      else {
        const st = detailStudents.find((s) => s.id === sid);
        seatPlan.grid[r][c] = st ? { studentId: st.id, name: st.name } : null;
      }
      renderSeatGrid();  // neu rendern, damit belegte Namen anderswo deaktiviert werden
    };
  });
}

// Editor-Grid -> layoutJson für die API.
function spLayoutFromGrid() {
  const seats = [];
  for (let r = 0; r < seatPlan.rows; r++) {
    for (let c = 0; c < seatPlan.cols; c++) {
      const cell = seatPlan.grid[r][c];
      if (cell) seats.push({ row: r, col: c, studentId: cell.studentId, name: cell.name });
    }
  }
  return { seats };
}

// layoutJson (aus API/KI) -> Editor-Grid.
function spGridFromLayout(layout, rows, cols) {
  const grid = spEmptyGrid(rows, cols);
  (layout && layout.seats ? layout.seats : []).forEach((s) => {
    if (s.row >= 0 && s.row < rows && s.col >= 0 && s.col < cols) {
      grid[s.row][s.col] = { studentId: s.studentId != null ? s.studentId : null, name: s.name || "" };
    }
  });
  return grid;
}

async function renderSeatPlanList() {
  const wrap = $("spList");
  if (!wrap) return;
  let plans = [];
  try { plans = await API.get(`/classes/${detailClassId}/seat-plans`); }
  catch (e) { toast(e.message, false); return; }
  if (!plans.length) { wrap.innerHTML = '<p class="muted small">Noch keine Sitzpläne gespeichert.</p>'; return; }
  wrap.innerHTML = "";
  plans.forEach((p) => {
    const row = document.createElement("div");
    row.className = "mini-item";
    const count = (p.layoutJson && p.layoutJson.seats ? p.layoutJson.seats.length : 0);
    row.innerHTML =
      `<span>${esc(p.name)} <span class="muted small">(${p.rows || "?"}×${p.cols || "?"}, ${count} Plätze)</span></span>` +
      `<span class="sp-list-actions">` +
      `<button class="btn small secondary" data-sp-load="${p.id}">Laden</button>` +
      `<button class="btn small secondary" data-sp-pdf="${p.id}">PDF</button>` +
      `<button class="btn small danger" data-sp-del="${p.id}">✕</button></span>`;
    wrap.appendChild(row);
  });
  wrap.querySelectorAll("[data-sp-load]").forEach((b) => (b.onclick = () => loadSeatPlan(Number(b.dataset.spLoad))));
  wrap.querySelectorAll("[data-sp-pdf]").forEach((b) => (b.onclick = () => exportSeatPlan(Number(b.dataset.spPdf))));
  wrap.querySelectorAll("[data-sp-del]").forEach((b) => (b.onclick = () => deleteSeatPlan(Number(b.dataset.spDel))));
}

async function loadSeatPlan(pid) {
  try {
    const p = await API.get(`/seat-plans/${pid}`);
    seatPlan.editId = p.id;
    seatPlan.rows = p.rows || 1;
    seatPlan.cols = p.cols || 1;
    seatPlan.grid = spGridFromLayout(p.layoutJson, seatPlan.rows, seatPlan.cols);
    $("spName").value = p.name;
    $("spRows").value = String(seatPlan.rows);
    $("spCols").value = String(seatPlan.cols);
    renderSeatGrid();
    $("spExportBtn").disabled = false;
    $("spExportBtn").onclick = () => exportSeatPlan(p.id);
    toast("Sitzplan geladen.");
  } catch (e) { toast(e.message, false); }
}

async function saveSeatPlan() {
  const name = $("spName").value.trim();
  if (!name) { toast("Bitte einen Namen für den Sitzplan eingeben.", false); return; }
  const body = { name, rows: seatPlan.rows, cols: seatPlan.cols, layoutJson: spLayoutFromGrid() };
  try {
    let saved;
    if (seatPlan.editId) saved = await API.put(`/seat-plans/${seatPlan.editId}`, body);
    else saved = await API.post(`/classes/${detailClassId}/seat-plans`, body);
    seatPlan.editId = saved.id;
    $("spExportBtn").disabled = false;
    $("spExportBtn").onclick = () => exportSeatPlan(saved.id);
    await renderSeatPlanList();
    toast("Sitzplan gespeichert.");
  } catch (e) { toast(e.message, false); }
}

async function deleteSeatPlan(pid) {
  try {
    await API.del(`/seat-plans/${pid}`);
    if (seatPlan.editId === pid) { seatPlan.editId = null; $("spExportBtn").disabled = true; }
    await renderSeatPlanList();
    toast("Sitzplan gelöscht.");
  } catch (e) { toast(e.message, false); }
}

function exportSeatPlan(pid) {
  const a = document.createElement("a");
  a.href = `/api/seat-plans/${pid}/export?format=pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function aiArrangeSeats() {
  const description = $("spAiDesc").value.trim();
  if (!detailStudents.length) { toast("Diese Klasse hat noch keine Schüler.", false); return; }
  const btn = $("spAiBtn");
  btn.disabled = true;
  try {
    const res = await API.post(`/classes/${detailClassId}/seat-plans/ai-arrange`, {
      rows: seatPlan.rows, cols: seatPlan.cols, description,
    });
    const seats = res.suggestion && res.suggestion.seats ? res.suggestion.seats : [];
    seatPlan.grid = spGridFromLayout({ seats }, seatPlan.rows, seatPlan.cols);
    renderSeatGrid();
    toast(`KI-Anordnung übernommen (${seats.length} Plätze) – manuell nachbearbeitbar.`);
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; }
}
/* =================== /U18: Sitzplan =================== */

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
      try { await API.post("/todos/" + btn.dataset.delTodo + "/archive"); await refresh(); toast("To-Do archiviert."); }
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
  loadPlanNotes();
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

/* ---------- Archiv (U13): Klassen | Planungen | To-Dos | Notizen ---------- */
let archivTab = "klassen";

function setArchivTab(name) {
  archivTab = name;
  document.querySelectorAll(".archiv-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.archiv === name));
  ["klassen", "planungen", "todos", "notizen"].forEach((n) => {
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
  const panel = $("archiv" + name.charAt(0).toUpperCase() + name.slice(1));
  if (panel) panel.innerHTML = '<p class="muted small">Noch keine archivierten Einträge.</p>';
}

/* ---------- U16: Archiv „Planungen" – Plan auf neues Schuljahr übernehmen ---------- */
async function renderArchivPlanungen() {
  const wrap = $("archivPlanungen");
  if (!wrap) return;
  wrap.innerHTML = '<p class="muted small">Wird geladen …</p>';
  let plans = [];
  try { plans = await API.get("/stoff-plans"); }
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
      <span class="muted small">${esc(clsName(p.classId))} · ${esc(yearLbl(p.schoolYearId))} · ${esc(p.blockCount ?? 0)} Blöcke</span>
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

// Effektiver Bildungsgang für die Anzeige (Deutsch 'gemischt' ab Kl. 7 → RS).
function resolveTrack(subject, grade, track) {
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
      e.classId === cid && (e.entryType === "lu" || e.entryType === "exam") &&
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
}
function closeCalEntryPanel() { const p = $("calEntryPanel"); if (p) p.classList.add("hidden"); }

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
// U15: Kalender auf ein Datum springen lassen und den Tag kurz farblich hervorheben.
function jumpCalendarToDate(dStr) {
  const d = parseIso(dStr);
  if (!d) return;
  calCursor = d;
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
function entriesForDate(dStr) {
  const vis = visibleClassIds();
  // Klassenlose Termine (classId == null) sind immer sichtbar; mehrtägige Termine
  // erscheinen an jedem Tag zwischen entryDate und endDate (inklusive).
  return state.calendar.filter((e) => {
    const end = e.endDate || e.entryDate;
    const inRange = e.entryDate <= dStr && dStr <= end;
    return inRange && (e.classId == null || vis.includes(e.classId));
  });
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
  const makeCell = (d, other) => {
    const dStr = isoDate(d);
    const cell = document.createElement("div");
    cell.className = "cal-cell" + (other ? " otherMonth" : "") + (dStr === todayStr ? " today" : "");
    cell.dataset.date = dStr;
    const sd = schoolDateFor(dStr);
    if (sd) { cell.style.background = cssVar(sd.kind === "feiertag" ? "--cal-holiday" : "--cal-vacation", sd.kind === "feiertag" ? "#fde68a" : "#e5e7eb"); cell.title = sd.name; }
    const strips = planSegs.filter((s) => s.start <= dStr && dStr <= s.end);
    const stripHtml = strips.length
      ? `<div class="cal-plan-strips">` + strips.map((s) =>
          `<span class="cal-plan-strip" style="background:${s.color}" title="${s.tip}">${esc(s.code)}</span>`).join("") + `</div>`
      : "";
    cell.innerHTML = `<div class="cal-daynum">${d.getDate()}</div>` + stripHtml +
      entriesForDate(dStr).map((e) => {
        const cat = catById(e.categoryId);
        const style = cat ? ` style="border-left:4px solid ${esc(cat.color)}"` : "";
        const time = (!e.allDay && e.startTime) ? esc(e.startTime) + " " : "";
        return `<div class="cal-entry ${esc(e.entryType)}" data-lesson="${e.lessonId == null ? "" : e.lessonId}"${style}>${time}${esc(e.title)}</div>`;
      }).join("");
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
  // U22: Klick auf die freie Fläche eines Tages öffnet das Termin-Popover (vorbefülltes Datum).
  grid.querySelectorAll(".cal-cell").forEach((cell) => {
    cell.addEventListener("click", (ev) => {
      if (ev.target.closest(".cal-entry")) return;
      openCalEntryPanel(cell.dataset.date);
    });
  });
}

async function saveCalendarEntry() {
  const title = $("calEntryTitle").value.trim(), date = $("calEntryDate").value;
  if (!title || !date) { toast("Bitte Titel und Datum angeben.", false); return; }
  const endDate = $("calEntryEndDate").value || null;
  if (endDate && endDate < date) { toast("Enddatum darf nicht vor dem Startdatum liegen.", false); return; }
  const allDay = $("calEntryAllDay").checked;
  try {
    await API.post("/calendar", {
      title, entryDate: date, endDate,
      allDay,
      startTime: allDay ? null : ($("calEntryStartTime").value || null),
      endTime: allDay ? null : ($("calEntryEndTime").value || null),
      entryType: $("calEntryType").value,
      categoryId: $("calEntryCategory").value ? Number($("calEntryCategory").value) : null,
      classId: $("calEntryClass").value ? Number($("calEntryClass").value) : null,
      isFixed: $("calEntryFixed").checked,
    });
    $("calEntryTitle").value = ""; $("calEntryEndDate").value = "";
    $("calEntryStartTime").value = ""; $("calEntryEndTime").value = "";
    $("calEntryAllDay").checked = true; $("calEntryTimeRow").style.display = "none";
    $("calEntryFixed").checked = false;
    closeCalEntryPanel();
    await refresh(); toast("Termin gespeichert.");
  } catch (e) { toast(e.message, false); }
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
      try { await API.put("/calendar-categories/" + id, { name, color }); await refresh(); toast("Kategorie gespeichert."); }
      catch (e) { toast(e.message, false); }
    };
  });
  wrap.querySelectorAll("[data-cat-del]").forEach((b) => {
    b.onclick = async () => {
      try { await API.del("/calendar-categories/" + b.dataset.catDel); await refresh(); toast("Kategorie gelöscht."); }
      catch (e) { toast(e.message, false); }
    };
  });
}

async function addCategory() {
  const name = $("newCatName").value.trim(), color = $("newCatColor").value;
  if (!name) { toast("Bitte einen Namen angeben.", false); return; }
  try {
    await API.post("/calendar-categories", { name, color });
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
  const wrap = $("importResult");
  if (!wrap) return;
  if (!importSuggestions.length) {
    wrap.innerHTML = '<p class="muted small">Keine Termine erkannt.</p>';
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
  wrap.innerHTML =
    `<p class="small muted">${importSuggestions.length} Termin(e) erkannt – Auswahl prüfen und übernehmen.</p>` +
    rows +
    `<div style="margin-top:10px;"><button class="btn" id="importCommitBtn">Ausgewählte übernehmen</button></div>`;
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
  const wrap = $("importResult");
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
    importSuggestions = []; $("importFile").value = ""; $("importResult").innerHTML = "";
    await refresh(); toast(`${created.length} Termin(e) übernommen.`);
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
    // Vorschau für „Plan speichern" merken (U12).
    state.stoffPreview = res.blocks.map((x) => ({
      code: x.code, title: x.title, ustd: x.ustd,
      startDate: x.startDate, endDate: x.endDate,
      conflictNote: x.conflictWithFixed ? "Konflikt fixer Termin" : null,
    }));
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

/* ---------- Jahresplan-Ideen (Freitext, KI-relevant) ---------- */
let planNotesTimer = null;
let planNotesKey = "";     // classId|schoolYearId der aktuell geladenen Notiz

async function loadPlanNotes() {
  const ta = $("planNotes");
  if (!ta) return;
  if (planNotesTimer) { clearTimeout(planNotesTimer); planNotesTimer = null; }  // ausstehenden Save der alten Auswahl verwerfen (kein Cross-Klassen-Schreiben)
  const clsId = Number($("planClass").value), syId = Number($("planYear").value);
  const status = $("planNotesStatus");
  if (!clsId || !syId) { ta.value = ""; planNotesKey = ""; if (status) status.textContent = ""; return; }
  planNotesKey = clsId + "|" + syId;
  if (status) status.textContent = "";
  try {
    const res = await API.get(`/planning/notes?classId=${clsId}&schoolYearId=${syId}`);
    if (planNotesKey === clsId + "|" + syId) ta.value = res.text || "";
  } catch (e) { /* stumm – Notizen sind optional */ }
}

async function savePlanNotes(silent) {
  const ta = $("planNotes");
  if (!ta) return;
  const clsId = Number($("planClass").value), syId = Number($("planYear").value);
  if (!clsId || !syId) { if (!silent) toast("Bitte Schuljahr und Klasse wählen.", false); return; }
  const status = $("planNotesStatus");
  try {
    await API.put("/planning/notes", { classId: clsId, schoolYearId: syId, text: ta.value });
    if (status) status.textContent = "Gespeichert.";
    if (!silent) toast("Ideen gespeichert.");
  } catch (e) { if (status) status.textContent = ""; toast(e.message, false); }
}

function schedulePlanNotesSave() {
  const status = $("planNotesStatus");
  if (status) status.textContent = "…";
  if (planNotesTimer) clearTimeout(planNotesTimer);
  planNotesTimer = setTimeout(() => savePlanNotes(true), 900);
}

/* ---------- Stoffverteilungspläne speichern/laden (U12) ---------- */
function selectedText(id) {
  const sel = $(id), opt = sel && sel.options[sel.selectedIndex];
  return opt ? opt.textContent : "";
}

// Wandelt die interne Vorschau (state.stoffPreview) in API-Blöcke (camelCase, lbCode) um.
function previewToBlocks(preview) {
  return (preview || []).map((b) => ({
    lbCode: b.code || null, title: b.title || null, ustd: b.ustd ?? null,
    startDate: b.startDate || null, endDate: b.endDate || null,
    conflictNote: b.conflictNote || null,
  }));
}

async function saveStoffPlan() {
  const clsId = Number($("planClass").value), syId = Number($("planYear").value);
  if (!clsId) { toast("Bitte eine Klasse wählen.", false); return; }
  if (!state.stoffPreview.length) {
    toast("Kein Vorschlag vorhanden – erst „Jahresplan vorschlagen“ oder „KI-Vorschlag“.", false);
    return;
  }
  const def = `Stoffverteilungsplan ${selectedText("planClass")} ${selectedText("planYear")}`.trim();
  const title = window.prompt("Titel des Plans:", def);
  if (title === null) return;                       // Abbruch
  try {
    await API.post("/stoff-plans", {
      classId: clsId, schoolYearId: syId || null,
      title: title.trim() || def, status: "entwurf",
      blocks: previewToBlocks(state.stoffPreview),
    });
    toast("Stoffplan gespeichert.");
    await loadStoffPlans();
  } catch (e) { toast(e.message, false); }
}

async function loadStoffPlans() {
  const wrap = $("stoffPlansList");
  if (!wrap) return;
  const clsId = Number($("planClass").value);
  if (!clsId) { state.stoffPlans = []; renderStoffPlans(); return; }
  try {
    state.stoffPlans = await API.get(`/stoff-plans?classId=${clsId}`);
  } catch (e) { state.stoffPlans = []; }
  renderStoffPlans();
}

function renderStoffPlans() {
  const wrap = $("stoffPlansList");
  if (!wrap) return;
  if (!Number($("planClass").value)) {
    wrap.innerHTML = '<p class="muted small">Bitte eine Klasse wählen.</p>';
    return;
  }
  if (!state.stoffPlans.length) {
    wrap.innerHTML = '<p class="muted small">Noch keine gespeicherten Pläne für diese Klasse.</p>';
    return;
  }
  wrap.innerHTML = state.stoffPlans.map((p) => {
    const badge = p.status === "aktiv"
      ? '<span class="badge ok">aktiv</span>' : '<span class="badge warn">Entwurf</span>';
    const meta = `${esc(p.blockCount ?? 0)} Blöcke · zuletzt geändert ${esc((p.updatedAt || "").slice(0, 10))}`;
    const toggleLbl = p.status === "aktiv" ? "Auf Entwurf" : "Aktiv setzen";
    return `<div class="stoff-plan-row" data-plan="${p.id}">
      <div class="stoff-plan-head">
        <div><strong>${esc(p.title)}</strong> ${badge}<br><span class="small muted">${meta}</span></div>
        <div class="stoff-plan-actions">
          <button class="btn small" data-sp-load="${p.id}">Laden</button>
          <button class="btn small secondary" data-sp-edit="${p.id}">Bearbeiten</button>
          <button class="btn small secondary" data-sp-toggle="${p.id}">${toggleLbl}</button>
          <button class="btn small danger" data-sp-del="${p.id}">Löschen</button>
        </div>
      </div>
      <div class="stoff-plan-editor" data-editor="${p.id}"></div>
    </div>`;
  }).join("");
  wrap.querySelectorAll("[data-sp-load]").forEach((b) => b.onclick = () => loadStoffPlanIntoTable(Number(b.dataset.spLoad)));
  wrap.querySelectorAll("[data-sp-edit]").forEach((b) => b.onclick = () => toggleStoffPlanEditor(Number(b.dataset.spEdit)));
  wrap.querySelectorAll("[data-sp-toggle]").forEach((b) => b.onclick = () => toggleStoffPlanStatus(Number(b.dataset.spToggle)));
  wrap.querySelectorAll("[data-sp-del]").forEach((b) => b.onclick = () => deleteStoffPlan(Number(b.dataset.spDel)));
  if (editingStoffPlanId != null) renderStoffPlanEditor(editingStoffPlanId);
}

async function loadStoffPlanIntoTable(id) {
  try {
    const p = await API.get(`/stoff-plans/${id}`);
    state.stoffPreview = (p.blocks || []).map((b) => ({
      code: b.lbCode, title: b.title, ustd: b.ustd,
      startDate: b.startDate, endDate: b.endDate, conflictNote: b.conflictNote,
    }));
    $("planSummary").textContent = `Geladener Plan „${p.title}" · ${(p.blocks || []).length} Blöcke`;
    const body = document.querySelector("#planTable tbody");
    body.innerHTML = "";
    (p.blocks || []).forEach((b) => {
      const tr = document.createElement("tr");
      const zeit = (b.startDate || b.endDate) ? `${esc(b.startDate || "?")} – ${esc(b.endDate || "?")}` : "—";
      tr.innerHTML = `<td>${esc(b.lbCode || "")}</td><td>${esc(b.title || "")}</td><td>${esc(b.ustd ?? "")}</td>` +
        `<td>—</td><td>${zeit}</td><td>${esc(b.conflictNote || "—")}</td>`;
      body.appendChild(tr);
    });
    toast("Plan in die Tabelle geladen.");
  } catch (e) { toast(e.message, false); }
}

function toggleStoffPlanEditor(id) {
  editingStoffPlanId = (editingStoffPlanId === id) ? null : id;
  renderStoffPlans();
}

async function renderStoffPlanEditor(id) {
  const box = document.querySelector(`[data-editor="${id}"]`);
  if (!box) return;
  let p;
  try { p = await API.get(`/stoff-plans/${id}`); }
  catch (e) { toast(e.message, false); return; }
  const rows = (p.blocks || []).map((b, i) =>
    `<tr data-i="${i}">
      <td>${esc(b.lbCode || "")}</td>
      <td><input type="text" data-f="title" value="${esc(b.title || "")}" /></td>
      <td><input type="number" data-f="ustd" min="0" value="${esc(b.ustd ?? "")}" style="width:70px;" /></td>
      <td><input type="date" data-f="startDate" value="${esc(b.startDate || "")}" /></td>
      <td><input type="date" data-f="endDate" value="${esc(b.endDate || "")}" /></td>
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
        <button class="btn small" data-sp-save="${id}">Änderungen speichern</button>
        <button class="btn small secondary" data-sp-cancel="${id}">Schließen</button>
      </div>
    </div>`;
  box.querySelector(`[data-sp-save="${id}"]`).onclick = () => saveStoffPlanEdits(id);
  box.querySelector(`[data-sp-cancel="${id}"]`).onclick = () => { editingStoffPlanId = null; renderStoffPlans(); };
}

async function saveStoffPlanEdits(id) {
  const box = document.querySelector(`[data-editor="${id}"]`);
  if (!box) return;
  const title = box.querySelector("[data-edit-title]").value;
  const blocks = [...box.querySelectorAll("tbody tr[data-i]")].map((tr) => {
    const get = (f) => { const el = tr.querySelector(`[data-f="${f}"]`); return el ? el.value : ""; };
    return {
      lbCode: tr.children[0].textContent || null,
      title: get("title") || null,
      ustd: get("ustd") === "" ? null : Number(get("ustd")),
      startDate: get("startDate") || null,
      endDate: get("endDate") || null,
    };
  });
  try {
    await API.put(`/stoff-plans/${id}`, { title, blocks });
    toast("Plan aktualisiert.");
    editingStoffPlanId = null;
    await loadStoffPlans();
  } catch (e) { toast(e.message, false); }
}

async function toggleStoffPlanStatus(id) {
  const p = state.stoffPlans.find((x) => x.id === id);
  const next = (p && p.status === "aktiv") ? "entwurf" : "aktiv";
  try {
    await API.put(`/stoff-plans/${id}`, { status: next });
    toast(next === "aktiv" ? "Plan aktiv gesetzt." : "Plan auf Entwurf gesetzt.");
    await loadStoffPlans();
  } catch (e) { toast(e.message, false); }
}

async function deleteStoffPlan(id) {
  if (!window.confirm("Diesen Stoffplan wirklich löschen?")) return;
  try {
    await API.del(`/stoff-plans/${id}`);
    if (editingStoffPlanId === id) editingStoffPlanId = null;
    toast("Plan gelöscht.");
    await loadStoffPlans();
  } catch (e) { toast(e.message, false); }
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
         `${z.phaseSortOrder != null ? ` <span class="muted small">(${esc(phaseNames[z.phaseSortOrder] || "Phase")})</span>` : ""}</p>`).join(""))
    : '<p class="muted small">Noch keine Lernziele erfasst.</p>';
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
      <button class="btn small secondary" id="modalEditBtn" style="float:right; margin-right:10px;">Stunde bearbeiten</button>
      <h2>${esc(l.title)}</h2>
      <p class="muted small">${esc(l.subject)} – Klasse ${esc(l.grade || "?")} – ${esc(l.lessonType || "")} – ${esc(l.durationMinutes || 45)} Min. ${l.time ? "– " + esc(l.time) + " Uhr" : ""}</p>
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
  const body = {
    name, subject: $("classSubject").value, grade: Number($("classGrade").value),
    track: $("classTrack").value, weeklyHours: Number($("classHours").value) || 2,
    parallelGroup: $("classGroup").value.trim() || null,
  };
  try {
    if (editingClassId) {
      await API.put("/classes/" + editingClassId, body);
    } else {
      await API.post("/classes", body);
    }
    resetClassForm();
    await refresh(); toast("Klasse gespeichert.");
  } catch (e) { toast(e.message, false); }
}

async function saveLesson() {
  const title = $("lessonTitle").value.trim();
  if (!title) { toast("Bitte einen Titel angeben.", false); return; }
  const meyer = readMeyerGrid("meyerPlanGrid");
  const body = {
    title, subject: $("lessonSubject").value, grade: Number($("lessonGrade").value),
    lessonType: $("lessonType").value,
    durationMinutes: Number($("lessonDuration").value) || 45,
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
    lernziele: readLernziele(),
  };
  try {
    if (editingLessonId) {
      await API.put("/lessons/" + editingLessonId, body);
    } else {
      await API.post("/lessons", { ...body, time: null });
    }
    const updated = Boolean(editingLessonId);
    resetLessonEditState();
    clearLessonForm(); await refresh();
    toast(updated ? "Stunde aktualisiert." : "Stunde gespeichert.");
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
    // U21: Google-Kalender-Status übernehmen.
    state.google = { keySet: s.googleKeySet, calendarId: s.googleCalendarId, lastSync: s.googleLastSync };
    $("googleKeyWarn").classList.toggle("hidden", s.secretConfigured);
    $("saveGoogleKey").disabled = !s.secretConfigured;
    if (s.googleCalendarId && !$("googleCalendarIdInput").value) $("googleCalendarIdInput").value = s.googleCalendarId;
    applyGoogleStatus();
    state.aiActive = s.apiKeyStatus === "aktiv";
    applyAiGating(state.aiActive);
    applyAppearance(s.theme, s.darkMode, s.font);
    renderAiUsage();
    refreshLogoPreview();
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
  if (cBtn) cBtn.disabled = !g.keySet;
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
  ["aiPlanBtn", "stoffAiBtn", "asuvAiBtn", "aiLernzieleBtn", "asuvEinordnungBtn", "stundeEinordnungBtn", "spAiBtn"].forEach((id) => {
    const b = $(id);
    if (b) { b.disabled = !active; b.title = active ? "" : "Kein API-Key hinterlegt – in den Einstellungen eintragen"; }
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
    });
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
    // Vorschau für „Plan speichern" merken (U12) – KI liefert keine Zeiträume.
    state.stoffPreview = blocks.map((x) => ({
      code: x.code, title: x.title, ustd: x.ustd,
      startDate: null, endDate: null, conflictNote: x.note || null,
    }));
    toast(res.cached ? "KI-Stoffplan (aus Cache)." : "KI-Stoffplan-Vorschlag erzeugt.");
  } catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; btn.textContent = label; }
}

async function aiAsuvSuggest() {
  if (!asuvLessonId) { toast("Bitte eine Stunde wählen.", false); return; }
  const btn = $("asuvAiBtn"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "✨ Wird ausformuliert…";
  const startedFor = asuvLessonId; // Stunde merken – Nutzer kann während des Wartens wechseln
  try {
    // Asynchroner Job: sofort jobId, dann alle 3 s pollen (Cloudflare-Timeout-sicher).
    const { jobId } = await API.post(`/ai/asuv/${startedFor}`, {});
    const deadline = Date.now() + 5 * 60 * 1000;
    let job;
    do {
      if (Date.now() > deadline) {
        throw new Error("Zeitüberschreitung: Die KI-Antwort kam nicht innerhalb von 5 Minuten.");
      }
      await new Promise((r) => setTimeout(r, 3000));
      try {
        job = await API.get(`/ai/jobs/${jobId}`);
      } catch (e) {
        if (e.status !== undefined) throw e; // echter HTTP-Fehler (401/404/…) -> abbrechen
        job = { status: "pending" };         // Netzwerk-Aussetzer -> weiter pollen
      }
    } while (job.status === "pending");
    if (job.status === "error") throw new Error(job.error || "KI-Anfrage fehlgeschlagen.");
    if (asuvLessonId !== startedFor) {
      toast("Stunde wurde gewechselt – KI-Vorschlag verworfen. Bitte erneut ausformulieren.", false);
      return;
    }
    const res = job.result || {};
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
const praesent = { mode: "jahresplan", classId: "", lessonId: null, phaseIdx: 0 };
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
    lesSel.innerHTML = state.lessons.length
      ? state.lessons.map((l) => `<option value="${l.id}">${esc(lessonOptionLabel(l))}</option>`).join("")
      : '<option value="">Keine Stunden</option>';
    if (state.lessons.some((l) => String(l.id) === String(prev))) lesSel.value = String(prev);
    praesent.lessonId = lesSel.value ? Number(lesSel.value) : (state.lessons[0] ? state.lessons[0].id : null);
    if (praesent.lessonId != null) lesSel.value = String(praesent.lessonId);
  }
}

function renderPraesentation() {
  praesentToken++;   // laufende async-Renderings entwerten
  const clsSel = $("praesentClass"), lesSel = $("praesentLesson");
  const prevBtn = $("praesentPrevBtn"), nextBtn = $("praesentNextBtn");
  // Steuerungssichtbarkeit je Unteransicht
  if (clsSel) clsSel.style.display = praesent.mode === "jahresplan" ? "" : "none";
  if (lesSel) lesSel.style.display = (praesent.mode === "lernbereich" || praesent.mode === "ablauf") ? "" : "none";
  const showPhaseNav = praesent.mode === "ablauf";
  if (prevBtn) prevBtn.style.display = showPhaseNav ? "" : "none";
  if (nextBtn) nextBtn.style.display = showPhaseNav ? "" : "none";
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

function renderPraesentLernbereich() {
  const stage = $("praesentStage");
  if (!stage) return;
  if (!state.lessons.length) {
    stage.innerHTML = '<div class="praesent-empty">Noch keine Stunden geplant. Lege eine Stunde in der Unterrichtsplanung an.</div>';
    return;
  }
  const l = state.lessons.find((x) => String(x.id) === String(praesent.lessonId)) || state.lessons[0];
  praesent.lessonId = l.id;
  const ziele = l.lernziele || [];
  const grob = ziele.filter((z) => z.kind === "grob");
  const fein = ziele.filter((z) => z.kind === "fein");
  const bloom = (z) => z.bloomStufe ? `<span class="praesent-goal-bloom">${esc(z.bloomStufe)}</span>` : "";
  const phaseNote = (z) => z.phaseSortOrder != null
    ? `<span class="praesent-goal-phase">Phase: ${esc(phaseNames[z.phaseSortOrder] || "–")}</span>` : "";
  const goalHtml = (z, kind) =>
    `<div class="praesent-goal ${kind}"><span class="praesent-goal-kind">${kind === "grob" ? "Grobziel" : "Feinziel"}</span>` +
    `<span class="praesent-goal-text">${esc(z.text)}${bloom(z)}${phaseNote(z)}</span></div>`;
  const goals = grob.map((z) => goalHtml(z, "grob")).concat(fein.map((z) => goalHtml(z, "fein"))).join("");
  stage.innerHTML =
    `<h2 class="praesent-h">${esc(l.title)}</h2>` +
    `<div class="praesent-sub">${esc(l.subject)} · Klasse ${esc(l.grade || "?")}${l.lessonType ? " · " + esc(l.lessonType) : ""}</div>` +
    `<div class="praesent-goals">${goals || '<div class="praesent-empty">Für diese Stunde sind noch keine Lernziele hinterlegt.</div>'}</div>`;
}

function renderPraesentAblauf() {
  const stage = $("praesentStage");
  if (!stage) return;
  const l = state.lessons.find((x) => String(x.id) === String(praesent.lessonId));
  if (!l) {
    stage.innerHTML = '<div class="praesent-empty">Noch keine Stunden geplant. Lege eine Stunde in der Unterrichtsplanung an.</div>';
    return;
  }
  const phases = l.phases || [];
  const ziele = l.lernziele || [];
  const isToday = l.date === isoDate(new Date());
  const hint = isToday ? "" :
    '<div class="praesent-sub" style="color:var(--orange);">Diese Stunde ist nicht für heute geplant – frei gewählte Stunde.</div>';
  if (!phases.length) {
    stage.innerHTML = `<h2 class="praesent-h">${esc(l.title)}</h2>${hint}` +
      '<div class="praesent-empty">Für diese Stunde sind noch keine Phasen erfasst.</div>';
    return;
  }
  if (praesent.phaseIdx >= phases.length) praesent.phaseIdx = phases.length - 1;
  if (praesent.phaseIdx < 0) praesent.phaseIdx = 0;
  const steps = phases.map((p, i) => {
    const active = i === praesent.phaseIdx;
    const cls = "praesent-step" + (active ? " active" : "") + (i < praesent.phaseIdx ? " done" : "");
    const meta = [
      p.minutes != null ? `${esc(p.minutes)} Min.` : null,
      p.socialForm ? esc(p.socialForm) : null,
      p.method ? esc(p.method) : null,
    ].filter(Boolean).join(" · ");
    const stepZiele = ziele
      .filter((z) => z.kind === "fein" && z.phaseSortOrder != null && String(z.phaseSortOrder) === String(p.sortOrder))
      .map((z) => `<div class="praesent-step-goal">🎯 ${esc(z.text)}</div>`).join("");
    const here = active ? '<span class="praesent-here">📍 Wir sind hier</span>' : "";
    return `<div class="${cls}" data-phaseidx="${i}">` +
      `<div class="praesent-step-num">${i + 1}</div>` +
      `<div class="praesent-step-body"><div class="praesent-step-title">${esc(p.phaseName)}${here}</div>` +
      (meta ? `<div class="praesent-step-meta">${meta}</div>` : "") +
      (stepZiele ? `<div class="praesent-step-goals">${stepZiele}</div>` : "") +
      `</div></div>`;
  }).join("");
  stage.innerHTML = `<h2 class="praesent-h">${esc(l.title)}</h2>${hint}<div class="praesent-steps">${steps}</div>`;
  stage.querySelectorAll("[data-phaseidx]").forEach((el) => {
    el.onclick = () => { praesent.phaseIdx = Number(el.dataset.phaseidx); renderPraesentAblauf(); updatePraesentPhaseButtons(); };
  });
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
  if (mode === "ablauf") {
    // Standard: erste heutige Stunde, sonst aktuelle/erste
    const today = todayLessons();
    if (today.length && !today.some((l) => String(l.id) === String(praesent.lessonId))) {
      praesent.lessonId = today[0].id;
      const sel = $("praesentLesson");
      if (sel) sel.value = String(praesent.lessonId);
    }
    praesent.phaseIdx = 0;
  }
  renderPraesentation();
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
  kalender: ["Planungskalender", "Monat, Woche und Lernbereichs-Zeitleiste (folgt in M4)."],
  praesentation: ["Schüleransicht", "Präsentationsmodus für Beamer/Tafel – Jahresplan, Lernbereich, heutiger Ablauf."],
  stoff: ["Stoffverteilungsplan", "Lehrplanbasierte Jahresplanung (folgt in M4)."],
  stunde: ["Unterrichtsplanung", "Ideenfeld, Phasentabelle und abschließende Klafki-/Meyer-Reflexion."],
  reflexion: ["Reflexion", "Offene Reflexionen ansehen, überspringen oder erfassen."],
  notizen: ["Notizen", "Gedanken sammeln – allgemein oder je Klasse, mit Autosave."],
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
  // Verlässt man die Klassen-Ansicht mit offenem Bearbeiten-Modus, den Update-Modus
  // zurücksetzen – sonst würde ein späteres "Klasse speichern" versehentlich updaten.
  if (view !== "klassen" && editingClassId) resetClassForm();
  if (view === "settings") loadSettings();
  if (view === "kalender") { ensureGoogleStatus(); maybeAutoSyncOnOpen(); }  // U21/U24: Status + Auto-Sync (A)
  if (view === "asuv" && state.lessons.length) loadAsuv(asuvLessonId || state.lessons[0].id);
  if (view === "stoff") loadStoffPlans();
  if (view === "praesentation") renderPraesentation();
  if (view === "notizen") renderNotizen();
  if (view === "material") renderArchivPanel(archivTab);
  closeMobileNav();
}
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
  await refreshAiStatus();
  startGoogleAutoSync();  // U24: periodischer Auto-Sync (B), solange die App offen ist
}

function wireEvents() {
  buildMeyerGrid("meyerPlanGrid");
  buildMeyerGrid("meyerReflectGrid");
  buildPhases();
  renderLernziele();
  wireAppearance();

  document.querySelectorAll(".nav-btn").forEach((btn) => (btn.onclick = () => showView(btn.dataset.view)));
  document.querySelectorAll("[data-view-target]").forEach((el) => (el.onclick = () => showView(el.dataset.viewTarget)));

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
  $("cdStudentName").addEventListener("keydown", (e) => { if (e.key === "Enter") addStudent(); });
  $("cdStudentBulkBtn").onclick = addStudentsBulk;
  // U18: Sitzplan
  $("spBuildBtn").onclick = spBuildGrid;
  $("spSaveBtn").onclick = saveSeatPlan;
  $("spNewBtn").onclick = initSeatPlan;
  $("spAiBtn").onclick = aiArrangeSeats;
  $("saveLesson").onclick = saveLesson;
  $("cancelEditBtn").onclick = () => { resetLessonEditState(); clearLessonForm(); toast("Formular geleert – neue Stunde."); };
  $("saveReflect").onclick = saveReflect;

  // Kalender
  $("calPrevBtn").onclick = () => { calCursor.setDate(calCursor.getDate() - (calMode === "week" ? 7 : 30)); renderCalendar(); };
  $("calNextBtn").onclick = () => { calCursor.setDate(calCursor.getDate() + (calMode === "week" ? 7 : 30)); renderCalendar(); };
  $("calMonthBtn").onclick = () => { calMode = "month"; $("calMonthBtn").classList.add("active"); $("calWeekBtn").classList.remove("active"); renderCalendar(); };
  $("calWeekBtn").onclick = () => { calMode = "week"; $("calWeekBtn").classList.add("active"); $("calMonthBtn").classList.remove("active"); renderCalendar(); };
  $("calSaveEntryBtn").onclick = saveCalendarEntry;
  $("calEntryAllDay").onchange = () => {
    $("calEntryTimeRow").style.display = $("calEntryAllDay").checked ? "none" : "flex";
  };
  // U22: Termin-Popover öffnen/schließen; Werkzeug-Seitenleiste ein-/ausklappen.
  $("calNewEntryBtn").onclick = () => openCalEntryPanel(isoDate(new Date()));
  $("calEntryCancel").onclick = closeCalEntryPanel;
  $("calSideToggle").onclick = () => $("calLayout").classList.toggle("side-collapsed");
  $("addCatBtn").onclick = addCategory;
  $("importAnalyzeBtn").onclick = analyzeJahresplan;  // U20: Jahresplan-Import
  $("saveSchoolYear").onclick = saveSchoolYear;
  $("planPreviewBtn").onclick = runPlanning;
  $("stoffUpload").onclick = stoffUpload;
  $("planSaveBtn").onclick = saveStoffPlan;
  $("planClass").addEventListener("change", () => { loadPlanNotes(); editingStoffPlanId = null; loadStoffPlans(); });
  $("planYear").addEventListener("change", loadPlanNotes);
  $("planNotes").addEventListener("input", schedulePlanNotesSave);
  $("planNotesSave").onclick = () => savePlanNotes(false);

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
  $("addLernzielBtn").onclick = addLernziel;
  $("aiLernzieleBtn").onclick = aiLernzieleSuggest;
  $("asuvEinordnungBtn").onclick = asuvEinordnungSuggest;
  $("stundeEinordnungBtn").onclick = stundeEinordnungSuggest;
  $("lessonType").addEventListener("change", (e) =>
    $("lueHint").classList.toggle("hidden", e.target.value !== "Übungsstunde vor LUE"));

  // Schüleransicht / Präsentationsmodus (M12 U8)
  document.querySelectorAll(".praesent-tab").forEach((btn) =>
    (btn.onclick = () => setPraesentMode(btn.dataset.praesent)));
  $("praesentClass").addEventListener("change", (e) => { praesent.classId = e.target.value; renderPraesentation(); });
  $("praesentLesson").addEventListener("change", (e) => {
    praesent.lessonId = e.target.value ? Number(e.target.value) : null;
    praesent.phaseIdx = 0;
    renderPraesentation();
  });
  $("praesentPrevBtn").onclick = () => { if (praesent.phaseIdx > 0) { praesent.phaseIdx--; renderPraesentAblauf(); } };
  $("praesentNextBtn").onclick = () => { praesent.phaseIdx++; renderPraesentAblauf(); };
  $("praesentFullscreenBtn").onclick = praesentFullscreen;
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
  // U21: Google-Kalender-Sync
  $("saveGoogleKey").onclick = saveGoogleKey;
  $("removeGoogleKey").onclick = removeGoogleKey;
  $("calGoogleSyncBtn").onclick = syncGoogle;
  $("logoutBtn").onclick = async () => {
    try { await API.post("/auth/logout"); } catch (e) { /* egal */ }
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
   U17: Notizen ("Gedanken sammeln") – additiver Block.
   Unterreiter "Allgemein" + je aktiver Klasse einer; großes Textfeld mit
   Autosave (Debounce → PUT; erster Schreibvorgang POST). Archivieren pro Notiz;
   Archiv-Liste in der Materialbibliothek (renderArchivNotizen).
   ========================================================================= */
let notizenTab = "allgemein";   // "allgemein" oder String(class.id)
let notizenSaveId = null;       // id der aktuell bearbeiteten Notiz (null = noch keine)
let notizenTimer = null;
let notizenSaving = false;

function renderNotizen() {
  const tabsWrap = $("notizenTabs");
  if (!tabsWrap) return;
  const tabs = [{ key: "allgemein", label: "Allgemein" }];
  state.classes.forEach((c) => {
    const sy = state.schoolYears.find((s) => s.id === c.schoolYearId);
    const label = sy ? `${c.name} (${sy.label})` : c.name;
    tabs.push({ key: String(c.id), label });
  });
  if (!tabs.some((t) => t.key === notizenTab)) notizenTab = "allgemein";
  tabsWrap.innerHTML = tabs.map((t) =>
    `<button class="notizen-tab${t.key === notizenTab ? " active" : ""}" data-notiz-tab="${esc(t.key)}">${esc(t.label)}</button>`
  ).join("");
  tabsWrap.querySelectorAll("[data-notiz-tab]").forEach((b) => {
    b.onclick = async () => {
      await flushNotizenSave();     // ausstehende Eingabe des alten Reiters sichern
      notizenTab = b.dataset.notizTab;
      renderNotizen();
    };
  });
  renderNotizenPanel();
}

function renderNotizenPanel() {
  const panel = $("notizenPanel");
  if (!panel) return;
  if (notizenTimer) { clearTimeout(notizenTimer); notizenTimer = null; }
  const isAllg = notizenTab === "allgemein";
  const classId = isAllg ? null : Number(notizenTab);
  const note = state.notes.find((n) =>
    n.archivedAt == null &&
    (isAllg ? n.scope === "allgemein" : (n.scope === "klasse" && n.classId === classId)));
  notizenSaveId = note ? note.id : null;
  const hint = isAllg
    ? "Allgemeine Gedanken, klassenübergreifend."
    : "Gedanken zu dieser Klasse.";
  panel.innerHTML =
    `<p class="muted small">${esc(hint)}</p>` +
    `<textarea id="notizenText" class="notizen-text" placeholder="Gedanken sammeln …"></textarea>` +
    `<div class="notizen-foot">` +
    `<span class="small muted" id="notizenStatus"></span>` +
    `<button class="btn small secondary" id="notizenArchiveBtn"${note ? "" : " disabled"}>Notiz archivieren</button>` +
    `</div>`;
  const ta = $("notizenText");
  ta.value = note ? (note.bodyMd || "") : "";
  ta.oninput = scheduleNotizenSave;
  $("notizenArchiveBtn").onclick = archiveCurrentNote;
}

function scheduleNotizenSave() {
  const status = $("notizenStatus");
  if (status) status.textContent = "…";
  if (notizenTimer) clearTimeout(notizenTimer);
  notizenTimer = setTimeout(saveNotizen, 900);
}

async function flushNotizenSave() {
  if (notizenTimer) { clearTimeout(notizenTimer); notizenTimer = null; await saveNotizen(); }
}

async function saveNotizen() {
  const ta = $("notizenText");
  if (!ta) return;
  if (notizenSaving) { scheduleNotizenSave(); return; }  // Überlappung vermeiden (kein Doppel-POST)
  const status = $("notizenStatus");
  const body = ta.value;
  const isAllg = notizenTab === "allgemein";
  notizenSaving = true;
  try {
    if (notizenSaveId == null) {
      const created = await API.post("/notes", {
        scope: isAllg ? "allgemein" : "klasse",
        classId: isAllg ? null : Number(notizenTab),
        bodyMd: body,
      });
      notizenSaveId = created.id;
      state.notes.push(created);
      const ab = $("notizenArchiveBtn"); if (ab) ab.disabled = false;
    } else {
      const updated = await API.put(`/notes/${notizenSaveId}`, { bodyMd: body });
      const idx = state.notes.findIndex((n) => n.id === notizenSaveId);
      if (idx >= 0) state.notes[idx] = updated;
    }
    if (status) status.textContent = "Gespeichert.";
  } catch (e) {
    if (status) status.textContent = "";
    toast(e.message, false);
  } finally {
    notizenSaving = false;
  }
}

async function archiveCurrentNote() {
  if (notizenSaveId == null) return;
  if (!confirm("Diese Notiz archivieren? Sie wandert ins Archiv der Materialbibliothek.")) return;
  try {
    await flushNotizenSave();
    await API.post(`/notes/${notizenSaveId}/archive`);
    await refresh();
    renderNotizen();
    toast("Notiz archiviert.");
  } catch (e) { toast(e.message, false); }
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
  if (!banner) return;
  banner.classList.toggle("hidden", navigator.onLine !== false);
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
}
/* ===== Ende U23-Block =============================================================== */
