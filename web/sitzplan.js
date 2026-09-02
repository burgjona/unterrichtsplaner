/* U18 Sitzplan, als ES-Modul ausgelagert (Machbarkeitsprobe app.js-Splitting).
   Wird von app.js per dynamischem import() erst beim ersten Öffnen einer
   Klassen-Detailseite nachgeladen — vorher lädt der Browser diese Datei nicht.

   Bewusst ohne Zugriff auf globale Variablen aus app.js (state, $, esc, API, toast,
   detailClassId, detailStudents): app.js bleibt ein klassisches <script> ohne
   type="module", dessen Top-Level-let/const-Bindings für ein Modul unsichtbar sind.
   Stattdessen bekommt createSeatPlanModule() alles explizit übergeben (ctx). */

export function createSeatPlanModule(ctx) {
  const { $, esc, API, toast, SyncEngine, getDetailClassId, getDetailStudents, cdSetTile } = ctx;

  // state: aktuell im Editor bearbeiteter Sitzplan (grid = Matrix[row][col] -> {studentId,name}|null)
  const seatPlan = { editId: null, rows: 4, cols: 5, grid: [] };
  let seatPlansCache = [];   // zuletzt materialisierte Liste der aktuellen Klasse (für Laden/Löschen ohne erneuten Fetch)

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
    const detailStudents = getDetailStudents();
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
    const cid = getDetailClassId();
    let plans = [];
    try {
      const all = await SyncEngine.materialize("seat_plans");
      plans = all.filter((p) => String(p.classId) === String(cid))
        .sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")) || String(b.id).localeCompare(String(a.id)));
    } catch (e) { toast(e.message, false); return; }
    seatPlansCache = plans;
    if (cdSetTile) cdSetTile("sitzplan", String(plans.length));
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
    // Nicht Number()-erzwingen: eine noch nicht synchronisierte "loc_..."-id würde zu NaN.
    wrap.querySelectorAll("[data-sp-load]").forEach((b) => (b.onclick = () => loadSeatPlan(b.dataset.spLoad)));
    wrap.querySelectorAll("[data-sp-pdf]").forEach((b) => (b.onclick = () => exportSeatPlan(b.dataset.spPdf)));
    wrap.querySelectorAll("[data-sp-del]").forEach((b) => (b.onclick = () => deleteSeatPlan(b.dataset.spDel)));
  }

  async function loadSeatPlan(pid) {
    try {
      const p = seatPlansCache.find((x) => String(x.id) === String(pid));
      if (!p) { toast("Sitzplan nicht gefunden.", false); return; }
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
      if (seatPlan.editId) {
        saved = await SyncEngine.update("seat_plans", seatPlan.editId, body);
      } else {
        saved = await SyncEngine.create("seat_plans", { ...body, classId: getDetailClassId() });
      }
      seatPlan.editId = saved.id;
      $("spExportBtn").disabled = false;
      $("spExportBtn").onclick = () => exportSeatPlan(saved.id);
      await renderSeatPlanList();
      toast("Sitzplan gespeichert.");
    } catch (e) { toast(e.message, false); }
  }

  async function deleteSeatPlan(pid) {
    try {
      await SyncEngine.remove("seat_plans", pid);
      if (String(seatPlan.editId) === String(pid)) { seatPlan.editId = null; $("spExportBtn").disabled = true; }
      await renderSeatPlanList();
      toast("Sitzplan gelöscht.");
    } catch (e) { toast(e.message, false); }
  }

  function exportSeatPlan(pid) {
    // Export ist ein reiner Online-REST-Download (PDF-Rendering) — ein noch nicht
    // synchronisierter Sitzplan ("loc_..."-id) existiert serverseitig noch nicht.
    if (String(pid).startsWith("loc_")) {
      toast("Dieser Sitzplan ist noch nicht synchronisiert – bitte online abwarten.", false);
      return;
    }
    const a = document.createElement("a");
    a.href = `/api/seat-plans/${pid}/export?format=pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function aiArrangeSeats() {
    const detailStudents = getDetailStudents();
    const description = $("spAiDesc").value.trim();
    if (!detailStudents.length) { toast("Diese Klasse hat noch keine Schüler.", false); return; }
    const btn = $("spAiBtn");
    btn.disabled = true;
    try {
      const res = await API.post(`/classes/${getDetailClassId()}/seat-plans/ai-arrange`, {
        rows: seatPlan.rows, cols: seatPlan.cols, description,
      });
      const seats = res.suggestion && res.suggestion.seats ? res.suggestion.seats : [];
      seatPlan.grid = spGridFromLayout({ seats }, seatPlan.rows, seatPlan.cols);
      renderSeatGrid();
      toast(`KI-Anordnung übernommen (${seats.length} Plätze) – manuell nachbearbeitbar.`);
    } catch (e) { toast(e.message, false); }
    finally { btn.disabled = false; }
  }

  return {
    initSeatPlan, spBuildGrid, renderSeatGrid, renderSeatPlanList,
    loadSeatPlan, saveSeatPlan, deleteSeatPlan, exportSeatPlan, aiArrangeSeats,
    hasGrid: () => seatPlan.grid.length > 0,
  };
}
