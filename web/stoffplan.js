/* Stoffplan-View (U12, inkl. "Kumulierte Ansicht" von U16/U19), als ES-Modul
   ausgelagert (app.js-Splitting, dritter Kandidat nach sitzplan.js/notizen.js).
   Wird von app.js per dynamischem import() erst beim ersten Öffnen der
   Stoffverteilungsplan-Ansicht nachgeladen.

   Deutlich mehr geteilte Abhängigkeiten als bei den ersten beiden Modulen:
   Datums-Helfer (deDate/nextMonday/parseIso/isoDate/openDatePicker), das
   generische "Rückgängig auf Feldebene"-System (resetLocalUndo — die Klick-
   Delegation selbst bleibt in app.js und funktioniert allein über DOM-Attribute,
   braucht also keine Modul-Anbindung), restoreSequenzStunden (auch von der
   Sequenzplanung-View genutzt) sowie getLernbereiche/resolveTrack. Alle bleiben
   in app.js und werden über ctx injiziert statt verschoben.

   Die parallele Klassen-Detail-Version (renderClassDetailStoffPlans u.a. in
   app.js) bleibt unangetastet — eigenständige, nicht verschränkte Implementierung. */

export function createStoffplanModule(ctx) {
  const {
    $, esc, API, toast, state, refresh, setUndo, SyncEngine,
    deDate, nextMonday, parseIso, isoDate, openDatePicker,
    resetLocalUndo, restoreSequenzStunden, getLernbereiche, resolveTrack,
    downloadStoffPlanPdf, cascadeStoffPlanDates,
  } = ctx;

  let editingStoffPlanId = null;   // gerade im Inline-Editor geöffneter Plan
  // Kein durchgängiges Tastendruck-Autosave für den Block-Editor: ein Block-Bulk-Save vergibt
  // serverseitig neue Block-ids und würde daran hängende Sequenzstunden kaskadierend löschen
  // (s. Kommentar bei toggleKumulierteAnsicht unten) – das bei jedem Tastendruck zu wiederholen
  // wäre riskanter als der Status quo. Stattdessen nur "Speichern beim Verlassen" der Ansicht.
  let stoffEditDirty = false;
  let kumuliertPlanId = null;
  let kumuliertBlocks = [];
  let planNotesTimer = null;
  let planNotesKey = "";           // classId|schoolYearId der aktuell geladenen Notiz
  let planNotesId = null;          // id der geladenen plan_notes-Zeile, oder null (noch keine angelegt)

  // Hintergrund-Sync kann die id einer offline angelegten plan_notes-Zeile jederzeit von
  // localId auf die echte serverId umstellen (siehe Identitäts-Kommentar in sync-engine.js) —
  // sonst würde savePlanNotes() nach einem erfolgreichen Hintergrund-Push mit einer veralteten
  // id weiterarbeiten.
  SyncEngine.onChange((entityType, info) => {
    if (entityType !== "plan_notes" || !info.idRemaps) return;
    const remap = info.idRemaps.find((r) => r.oldId === planNotesId);
    if (remap) planNotesId = remap.newId;
  });

  /* ---------- Jahresplan-Ideen (Freitext, KI-relevant) ----------
     Offline-Sync (Rollout): plan_notes wird über den natürlichen Schlüssel (Klasse+Schuljahr)
     gesucht statt über eine dem Nutzer bekannte id — die id wird erst beim Laden ermittelt und
     lokal gemerkt, damit savePlanNotes() weiß, ob SyncEngine.create oder .update zu rufen ist. */
  async function loadPlanNotes() {
    const ta = $("planNotes");
    if (!ta) return;
    if (planNotesTimer) { clearTimeout(planNotesTimer); planNotesTimer = null; }  // ausstehenden Save der alten Auswahl verwerfen (kein Cross-Klassen-Schreiben)
    const clsId = Number($("planClass").value), syId = Number($("planYear").value);
    const status = $("planNotesStatus");
    if (!clsId || !syId) { ta.value = ""; planNotesKey = ""; planNotesId = null; if (status) status.textContent = ""; return; }
    planNotesKey = clsId + "|" + syId;
    if (status) status.textContent = "";
    try {
      const all = await SyncEngine.materialize("plan_notes");
      const match = all.find((n) => n.classId === clsId && n.schoolYearId === syId);
      if (planNotesKey === clsId + "|" + syId) {
        ta.value = match ? (match.text || "") : "";
        planNotesId = match ? match.id : null;
      }
    } catch (e) { /* stumm – Notizen sind optional */ }
  }

  async function savePlanNotes(silent) {
    const ta = $("planNotes");
    if (!ta) return;
    const clsId = Number($("planClass").value), syId = Number($("planYear").value);
    if (!clsId || !syId) { if (!silent) toast("Bitte Schuljahr und Klasse wählen.", false); return; }
    const status = $("planNotesStatus");
    try {
      if (planNotesId == null) {
        const created = await SyncEngine.create("plan_notes", { classId: clsId, schoolYearId: syId, text: ta.value });
        planNotesId = created.id;
      } else {
        await SyncEngine.update("plan_notes", planNotesId, { text: ta.value });
      }
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

  /* ---------- Material zu einem Lernbereich hochladen ---------- */
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
      toast("Kein Vorschlag vorhanden – erst „✨ KI-Vorschlag“ erzeugen.", false);
      return;
    }
    const def = `Stoffverteilungsplan ${selectedText("planClass")} ${selectedText("planYear")}`.trim();
    const title = window.prompt("Titel des Plans:", def);
    if (title === null) return;                       // Abbruch
    try {
      await SyncEngine.create("stoff_plans", {
        classId: clsId, schoolYearId: syId || null,
        title: title.trim() || def, status: "entwurf",
        blocks: previewToBlocks(state.stoffPreview),
      });
      toast("Stoffplan gespeichert.");
      await loadStoffPlans();
    } catch (e) { toast(e.message, false); }
  }

  // Offline-Sync (Rollout): materialize() liefert bereits das volle StoffPlanDetail (inkl.
  // blocks — der Fetch-Handler in sync.py liefert _detail(), nicht nur die Listen-Zeile),
  // daher genügt ein einziger Pull/Materialize-Zyklus statt separater Detail-REST-Calls
  // in loadStoffPlanIntoTable/renderStoffPlanEditor/saveStoffPlanEdits unten.
  async function loadStoffPlans() {
    const wrap = $("stoffPlansList");
    if (!wrap) return;
    const clsId = Number($("planClass").value);
    if (!clsId) { state.stoffPlans = []; renderStoffPlans(); return; }
    try {
      const all = await SyncEngine.materialize("stoff_plans");
      state.stoffPlans = all.filter((p) => p.classId === clsId)
        .sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")) || String(b.id).localeCompare(String(a.id)));
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
      const meta = `${esc((p.blocks || []).length)} Blöcke · zuletzt geändert ${esc((p.updatedAt || "").slice(0, 10))}`;
      const toggleLbl = p.status === "aktiv" ? "Auf Entwurf" : "Aktiv setzen";
      return `<div class="stoff-plan-row" data-plan="${p.id}">
        <div class="stoff-plan-head">
          <div><strong>${esc(p.title)}</strong> ${badge}<br><span class="small muted">${meta}</span></div>
          <div class="stoff-plan-actions">
            <button class="btn small" data-sp-load="${p.id}">Laden</button>
            <button class="btn small secondary" data-sp-edit="${p.id}">Bearbeiten</button>
            <button class="btn small secondary" data-sp-toggle="${p.id}">${toggleLbl}</button>
            <button class="btn small secondary" data-sp-pdf="${p.id}">Als PDF</button>
            <button class="btn small secondary" data-sp-kumuliert="${p.id}">Kumulierte Ansicht</button>
            <button class="btn small danger" data-sp-del="${p.id}">Löschen</button>
          </div>
        </div>
        <div class="stoff-plan-editor" data-editor="${p.id}"></div>
        <div class="stoff-plan-kumuliert" data-kumuliert="${p.id}"></div>
      </div>`;
    }).join("");
    // Nicht Number()-erzwingen: ein noch nicht synchronisierter Plan hat eine lokale
    // "loc_..."-id, die dabei zu NaN würde (siehe Kommentar in sync-engine.js:findByAnyId).
    wrap.querySelectorAll("[data-sp-load]").forEach((b) => b.onclick = () => loadStoffPlanIntoTable(b.dataset.spLoad));
    wrap.querySelectorAll("[data-sp-edit]").forEach((b) => b.onclick = () => toggleStoffPlanEditor(b.dataset.spEdit));
    wrap.querySelectorAll("[data-sp-toggle]").forEach((b) => b.onclick = () => toggleStoffPlanStatus(b.dataset.spToggle));
    wrap.querySelectorAll("[data-sp-pdf]").forEach((b) => b.onclick = () => downloadStoffPlanPdf(b.dataset.spPdf));
    wrap.querySelectorAll("[data-sp-kumuliert]").forEach((b) => b.onclick = () => toggleKumulierteAnsicht(b.dataset.spKumuliert));
    wrap.querySelectorAll("[data-sp-del]").forEach((b) => b.onclick = () => deleteStoffPlan(b.dataset.spDel));
    if (editingStoffPlanId != null) renderStoffPlanEditor(editingStoffPlanId);
    if (kumuliertPlanId != null) renderKumulierteAnsicht(kumuliertPlanId);
  }

  async function loadStoffPlanIntoTable(id) {
    try {
      const p = state.stoffPlans.find((x) => String(x.id) === String(id));
      if (!p) { toast("Plan nicht gefunden.", false); return; }
      state.stoffPreview = (p.blocks || []).map((b) => ({
        code: b.lbCode, title: b.title, ustd: b.ustd,
        startDate: b.startDate, endDate: b.endDate, conflictNote: b.conflictNote,
      }));
      $("planSummary").textContent = `Geladener Plan „${p.title}" · ${(p.blocks || []).length} Blöcke`;
      const body = document.querySelector("#planTable tbody");
      body.innerHTML = "";
      (p.blocks || []).forEach((b) => {
        const tr = document.createElement("tr");
        const zeit = (b.startDate || b.endDate) ? `${esc(deDate(b.startDate) || "?")} – ${esc(deDate(b.endDate) || "?")}` : "—";
        tr.innerHTML = `<td>${esc(b.lbCode || "")}</td><td>${esc(b.title || "")}</td><td>${esc(b.ustd ?? "")}</td>` +
          `<td>${esc(b.weeks ?? "—")}</td><td>${zeit}</td>`;
        body.appendChild(tr);
        if (b.conflictNote) {
          const noteTr = document.createElement("tr");
          noteTr.className = "stoff-note-row";
          noteTr.innerHTML = `<td colspan="5" class="stoff-note-cell"><span class="stoff-note-label">Hinweis:</span> ${esc(b.conflictNote)}</td>`;
          body.appendChild(noteTr);
        }
      });
      toast("Plan in die Tabelle geladen.");
    } catch (e) { toast(e.message, false); }
  }

  function toggleStoffPlanEditor(id) {
    editingStoffPlanId = (editingStoffPlanId === id) ? null : id;
    renderStoffPlans();
  }

  // Manuell hinzugefügte Blöcke bekommen bewusst keinen lbCode (kein Lehrplan-Bezug) –
  // lbCode wird ohnehin nur angezeigt (Text, keine Eingabe), siehe saveStoffPlanEdits.
  function stoffEditorRowHtml(b, i) {
    return `<tbody data-local-undo-block="stoffblock-${i}">
      <tr data-i="${i}">
        <td>${esc(b.lbCode || "")}</td>
        <td><input type="text" data-f="title" value="${esc(b.title || "")}" /></td>
        <td><input type="number" data-f="ustd" min="0" value="${esc(b.ustd ?? "")}" style="width:70px;" /></td>
        <td><input type="text" readonly class="date-picker-input" data-f="startDate" value="${esc(b.startDate || "")}" placeholder="jjjj-mm-tt" /></td>
        <td><input type="text" readonly class="date-picker-input" data-f="endDate" value="${esc(b.endDate || "")}" placeholder="jjjj-mm-tt" /></td>
        <td><button class="btn tiny danger" data-sp-block-del title="Block entfernen">✕</button></td>
      </tr>
      <tr class="stoff-note-row">
        <td colspan="6" class="stoff-note-cell">
          <div class="stoff-note-head">
            <label class="small stoff-note-label">Hinweis</label>
            <button class="btn tiny secondary" data-local-undo-btn disabled title="Letzte ungespeicherte Änderung an diesem Block rückgängig machen">Rückgängig</button>
          </div>
          <textarea class="stoff-note-textarea" data-note-i="${i}" data-f="conflictNote" rows="2">${esc(b.conflictNote || "")}</textarea>
        </td>
      </tr>
      </tbody>`;
  }

  // Verkabelt Datepicker/Kaskade/Löschen-Button für genau eine Block-Zeile (initial für
  // alle vorhandenen Zeilen, sonst gezielt nur für eine neu eingefügte – vermeidet doppelt
  // gebundene Listener bei „Block hinzufügen".
  function wireStoffEditorRow(tbody, box) {
    tbody.querySelectorAll(".date-picker-input").forEach((inp) => inp.addEventListener("click", () => openDatePicker(inp)));
    // Endet ein Block, wird für den nächsten Block „nächster Montag danach" vorgeschlagen und die Kette bei Bedarf nachgezogen.
    tbody.querySelectorAll('[data-f="endDate"]').forEach((inp) => inp.addEventListener("change", (e) => {
      const tr = e.target.closest("tr[data-i]");
      if (tr) cascadeStoffPlanDates(box, Number(tr.dataset.i));
    }));
    const delBtn = tbody.querySelector("[data-sp-block-del]");
    if (delBtn) delBtn.onclick = () => {
      tbody.remove();
      const table = box.querySelector(".stoff-edit-table");
      if (table && !table.querySelector("tr[data-i]")) {
        table.querySelectorAll("tbody").forEach((tb) => tb.remove());
        table.insertAdjacentHTML("beforeend", '<tbody><tr><td colspan="6" class="muted small">Keine Blöcke.</td></tr></tbody>');
      }
    };
  }

  function addStoffEditorBlock(box) {
    const table = box.querySelector(".stoff-edit-table");
    if (!table) return;
    table.querySelectorAll("tbody").forEach((tb) => { if (!tb.querySelector("tr[data-i]")) tb.remove(); });
    const i = Number(box.dataset.nextIdx || "0");
    box.dataset.nextIdx = String(i + 1);
    table.insertAdjacentHTML("beforeend", stoffEditorRowHtml({}, i));
    const newTbody = table.lastElementChild;
    wireStoffEditorRow(newTbody, box);
    const titleInput = newTbody.querySelector('[data-f="title"]');
    if (titleInput) titleInput.focus();
  }

  async function renderStoffPlanEditor(id) {
    const box = document.querySelector(`[data-editor="${id}"]`);
    if (!box) return;
    const p = state.stoffPlans.find((x) => String(x.id) === String(id));
    if (!p) { toast("Plan nicht gefunden.", false); return; }
    const rows = (p.blocks || []).map((b, i) => stoffEditorRowHtml(b, i)).join("");
    box.innerHTML = `
      <div class="stoff-plan-edit-inner">
        <label class="small">Titel</label>
        <input type="text" data-edit-title value="${esc(p.title)}" style="width:100%; margin-bottom:8px;" />
        <div class="table-scroll"><table class="stoff-edit-table">
          <thead><tr><th>LB</th><th>Thema</th><th>Ustd.</th><th>Beginn</th><th>Ende</th><th></th></tr></thead>
          ${rows || '<tbody><tr><td colspan="6" class="muted small">Keine Blöcke.</td></tr></tbody>'}
        </table></div>
        <button class="btn tiny secondary" data-sp-block-add style="margin-top:6px;">+ Block hinzufügen</button>
        <div style="margin-top:10px;">
          <button class="btn small" data-sp-save="${id}">Änderungen speichern</button>
          <button class="btn small secondary" data-sp-cancel="${id}">Schließen</button>
        </div>
      </div>`;
    box.dataset.nextIdx = String((p.blocks || []).length);
    stoffEditDirty = false;
    box.addEventListener("input", () => { stoffEditDirty = true; });
    box.addEventListener("change", () => { stoffEditDirty = true; });
    box.querySelector(`[data-sp-save="${id}"]`).onclick = () => saveStoffPlanEdits(id);
    box.querySelector(`[data-sp-cancel="${id}"]`).onclick = () => { editingStoffPlanId = null; stoffEditDirty = false; renderStoffPlans(); };
    box.querySelector("[data-sp-block-add]").onclick = () => { stoffEditDirty = true; addStoffEditorBlock(box); };
    box.querySelectorAll("tbody").forEach((tb) => { if (tb.querySelector("tr[data-i]")) wireStoffEditorRow(tb, box); });
  }

  // silent=true (Autosave beim Verlassen der Ansicht): kein Erfolgs-Toast, Fehler wird trotzdem
  // gemeldet (der Nutzer verlässt die Seite sonst im Glauben, es sei alles gesichert).
  async function saveStoffPlanEdits(id, silent) {
    const box = document.querySelector(`[data-editor="${id}"]`);
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
    const before = state.stoffPlans.find((x) => String(x.id) === String(id)) || null;
    try {
      await SyncEngine.update("stoff_plans", id, { title, blocks });
      stoffEditDirty = false;
      if (!silent) toast("Plan aktualisiert.");
      editingStoffPlanId = null;
      await loadStoffPlans();
      if (before) {
        setUndo(`Stoffplan „${before.title}“ bearbeitet.`, async () => {
          await SyncEngine.update("stoff_plans", id, {
            title: before.title,
            blocks: (before.blocks || []).map((b) => ({
              lbCode: b.lbCode, title: b.title, ustd: b.ustd,
              startDate: b.startDate, endDate: b.endDate, conflictNote: b.conflictNote,
            })),
          });
          await loadStoffPlans();
        });
      }
    } catch (e) { toast(e.message, false); }
  }

  // Vor View-Wechsel aufrufen: sichert einen offenen, bearbeiteten Block-Editor still ab.
  async function flushStoffplanAutosave() {
    if (editingStoffPlanId == null || !stoffEditDirty) return;
    await saveStoffPlanEdits(editingStoffPlanId, true);
  }

  async function toggleStoffPlanStatus(id) {
    const p = state.stoffPlans.find((x) => String(x.id) === String(id));
    const next = (p && p.status === "aktiv") ? "entwurf" : "aktiv";
    try {
      await SyncEngine.update("stoff_plans", id, { status: next });
      toast(next === "aktiv" ? "Plan aktiv gesetzt." : "Plan auf Entwurf gesetzt.");
      await loadStoffPlans();
    } catch (e) { toast(e.message, false); }
  }

  async function deleteStoffPlan(id) {
    if (!window.confirm("Diesen Stoffplan wirklich löschen?")) return;
    // /combined ist ein reiner REST-Lesezugriff (joint mit sequenz_stunden, Tranche 4, noch
    // nicht sync-fähig) — Undo für den Löschvorgang bleibt deshalb best-effort online-only,
    // wie schon vor dem Rollout (guard "if (snapshot)" unten).
    let snapshot = null;
    try { snapshot = await API.get(`/stoff-plans/${id}/combined`); } catch (e) { /* best effort, Undo entfällt dann */ }
    try {
      await SyncEngine.remove("stoff_plans", id);
      if (String(editingStoffPlanId) === String(id)) editingStoffPlanId = null;
      toast("Plan gelöscht.");
      await loadStoffPlans();
      if (snapshot) {
        setUndo(`Stoffplan „${snapshot.title}“ gelöscht.`, async () => {
          // createAndSync statt create: die Sequenzstunden-Wiederherstellung unten braucht
          // sofort die echte Server-id jedes neuen Blocks (eigene REST-Calls, kein Sync-
          // Payload) — analog saveLesson() in app.js (siehe dortiger Kommentar).
          const created = await SyncEngine.createAndSync("stoff_plans", {
            classId: snapshot.classId, schoolYearId: snapshot.schoolYearId,
            title: snapshot.title, status: snapshot.status,
            blocks: (snapshot.blocks || []).map((b) => ({
              lbCode: b.lbCode, title: b.title, ustd: b.ustd,
              startDate: b.startDate, endDate: b.endDate, conflictNote: b.conflictNote,
            })),
          });
          for (let i = 0; i < (snapshot.blocks || []).length; i++) {
            const stunden = snapshot.blocks[i].stunden || [];
            const newBlockId = created.blocks[i].id;
            for (const s of stunden) {
              await API.post("/sequenz-stunden", {
                blockId: newBlockId, title: s.title, grobziel: s.grobziel || null,
                isLk: s.isLk, isReferat: s.isReferat, isKomplexeArbeit: s.isKomplexeArbeit,
                isKlassenarbeit: s.isKlassenarbeit, weitereNotenart: s.weitereNotenart || null,
                date: s.date || null,
              });
            }
          }
          await loadStoffPlans();
        });
      }
    } catch (e) { toast(e.message, false); }
  }

  /* ---------- Kumulierte Ansicht: Stoffplan-Blöcke + ihre Sequenzstunden in einer Seite ---------- */
  // kumuliertBlocks = [{ id, lbCode, title, ustd, startDate, endDate, weeks,
  //                       cards: [{ id, title, grobziel, isLk, isReferat, isKomplexeArbeit,
  //                                 isKlassenarbeit, weitereNotenart, date }] }]
  // Block-Kopfdaten (Titel/Zeitraum/Ustd) sind hier nur Anzeige – ihr Speichern läuft weiter über
  // „Bearbeiten" oben, da ein Blöcke-Bulk-Save dort intern alle Block-IDs neu vergibt (Cascade
  // löscht dann verknüpfte Sequenzstunden). Editierbar sind hier nur die Sequenzstunden je Block.
  function toggleKumulierteAnsicht(id) {
    kumuliertPlanId = (kumuliertPlanId === id) ? null : id;
    renderStoffPlans();
  }

  async function renderKumulierteAnsicht(id) {
    const box = document.querySelector(`[data-kumuliert="${id}"]`);
    if (!box) return;
    let p;
    try { p = await API.get(`/stoff-plans/${id}/combined`); }
    catch (e) { toast(e.message, false); return; }
    kumuliertBlocks = (p.blocks || []).map((b) => ({
      id: b.id, lbCode: b.lbCode, title: b.title, ustd: b.ustd,
      startDate: b.startDate, endDate: b.endDate, weeks: b.weeks,
      cards: (b.stunden || []).map((s) => ({
        id: s.id, title: s.title, grobziel: s.grobziel || "",
        isLk: s.isLk, isReferat: s.isReferat, isKomplexeArbeit: s.isKomplexeArbeit,
        isKlassenarbeit: s.isKlassenarbeit, weitereNotenart: s.weitereNotenart || "",
        date: s.date || "",
      })),
    }));
    box.innerHTML = `<div class="stoff-plan-edit-inner">
      <div class="ka-blocks"></div>
      <div style="margin-top:10px;">
        <button class="btn small" data-ka-save="${id}">Sequenzstunden speichern</button>
        <button class="btn small secondary" data-ka-pdf="${id}">Als PDF</button>
        <button class="btn small secondary" data-ka-close="${id}">Schließen</button>
      </div>
    </div>`;
    renderKumulierteAnsichtFromState(box);
    const saveBtn = box.querySelector(`[data-ka-save="${id}"]`);
    if (saveBtn) saveBtn.onclick = () => saveKumulierteAnsicht(id);
    const pdfBtn = box.querySelector(`[data-ka-pdf="${id}"]`);
    if (pdfBtn) pdfBtn.onclick = () => downloadKumulierteAnsichtPdf(id);
    const closeBtn = box.querySelector(`[data-ka-close="${id}"]`);
    if (closeBtn) closeBtn.onclick = () => { kumuliertPlanId = null; renderStoffPlans(); };
  }

  function kumuliertBlockHtml(b, bi) {
    const zeit = (b.startDate || b.endDate) ? `${esc(deDate(b.startDate) || "?")} – ${esc(deDate(b.endDate) || "?")}` : "—";
    const collapsed = !!b.collapsed;
    const toggleBtn = `<button class="btn tiny secondary" data-ka-block-toggle="${bi}" title="${collapsed ? "Ausklappen" : "Einklappen"}">${collapsed ? "▸" : "▾"}</button>`;
    return `<div class="kumuliert-block${collapsed ? " kumuliert-block-collapsed" : ""}">
      <div class="kumuliert-block-head">
        <span class="kumuliert-block-title">${toggleBtn}<strong>${esc(b.lbCode || "")} ${esc(b.title || "")}</strong></span>
        <span class="small muted">${esc(b.ustd ?? "—")} Ustd. · ${zeit}${b.weeks != null ? ` · ${esc(b.weeks)} Wochen` : ""}${collapsed ? ` · ${b.cards.length} Stunde(n)` : ""}</span>
      </div>
      ${collapsed ? "" : `
      <div class="seq-cards" data-ka-cards="${bi}">
        ${b.cards.map((c, ci) => kumuliertCardHtml(c, bi, ci)).join("")
          || '<p class="muted small">Noch keine Stunden.</p>'}
      </div>
      <button class="btn tiny secondary" data-ka-add="${bi}">+ Stunde hinzufügen</button>`}
    </div>`;
  }

  function kumuliertCardHtml(card, bi, ci) {
    const chk = (field, label) =>
      `<label class="small"><input type="checkbox" data-ka-f="${field}" data-ka-bi="${bi}" data-ka-ci="${ci}" ${card[field] ? "checked" : ""}> ${label}</label>`;
    const collapsed = !!card.collapsed;
    const toggleBtn = `<button class="btn tiny secondary" data-ka-toggle="${bi}-${ci}" title="${collapsed ? "Ausklappen" : "Einklappen"}">${collapsed ? "▸" : "▾"}</button>`;
    if (collapsed) {
      return `<div class="seq-card seq-card-collapsed" data-ka-card="${bi}-${ci}">
        <div class="seq-card-head">
          ${toggleBtn}
          <span class="seq-card-num">${ci + 1}.</span>
          <span class="seq-card-collapsed-title">${esc(card.title) || '<span class="muted">Titel der Stunde</span>'}</span>
          <span class="muted small">${card.date ? deDate(card.date) : "kein Datum"}</span>
          <button class="btn tiny danger" data-ka-del="${bi}-${ci}" title="Stunde entfernen">✕</button>
        </div>
      </div>`;
    }
    return `<div class="seq-card" data-ka-card="${bi}-${ci}" data-local-undo-block="ka-${bi}-${ci}">
      <div class="seq-card-head">
        ${toggleBtn}
        <span class="seq-card-num">${ci + 1}.</span>
        <input type="text" class="seq-card-title" data-ka-f="title" data-ka-bi="${bi}" data-ka-ci="${ci}" value="${esc(card.title)}" placeholder="Titel der Stunde" />
        <button class="btn tiny secondary" data-local-undo-btn disabled title="Letzte ungespeicherte Änderung an dieser Karte rückgängig machen">Rückgängig</button>
        <button class="btn tiny danger" data-ka-del="${bi}-${ci}" title="Stunde entfernen">✕</button>
      </div>
      <textarea class="seq-card-grobziel" data-ka-f="grobziel" data-ka-bi="${bi}" data-ka-ci="${ci}" rows="2" placeholder="Grobziel">${esc(card.grobziel)}</textarea>
      <div class="seq-card-date">
        <label class="small">voraussichtliches Datum
          <input type="date" class="seq-card-date-input" data-ka-f="date" data-ka-bi="${bi}" data-ka-ci="${ci}" value="${esc(card.date || "")}" />
        </label>
        ${card.date ? `<button class="btn tiny secondary" data-ka-clear-date="${bi}-${ci}" title="Datum entfernen">✕ Datum</button>` : ""}
      </div>
      <div class="seq-card-notenarten">
        ${chk("isLk", "LK")} ${chk("isReferat", "Referat")} ${chk("isKomplexeArbeit", "Komplexe Arbeit")} ${chk("isKlassenarbeit", "Klassenarbeit")}
        <input type="text" class="seq-card-weitere" data-ka-f="weitereNotenart" data-ka-bi="${bi}" data-ka-ci="${ci}" value="${esc(card.weitereNotenart)}" placeholder="weitere Notenart (Freitext)" />
      </div>
    </div>`;
  }

  function wireKumulierteAnsichtBlocks(box) {
    box.querySelectorAll("[data-ka-f]").forEach((el) => {
      const evt = el.tagName === "INPUT" && el.type === "checkbox" ? "change" : "input";
      el.addEventListener(evt, () => {
        const bi = Number(el.dataset.kaBi), ci = Number(el.dataset.kaCi), f = el.dataset.kaF;
        kumuliertBlocks[bi].cards[ci][f] = el.type === "checkbox" ? el.checked : el.value;
      });
    });
    box.querySelectorAll("[data-ka-toggle]").forEach((b) => b.onclick = () => {
      const [bi, ci] = b.dataset.kaToggle.split("-").map(Number);
      kumuliertBlocks[bi].cards[ci].collapsed = !kumuliertBlocks[bi].cards[ci].collapsed;
      renderKumulierteAnsichtFromState(box);
    });
    box.querySelectorAll("[data-ka-block-toggle]").forEach((b) => b.onclick = () => {
      const bi = Number(b.dataset.kaBlockToggle);
      kumuliertBlocks[bi].collapsed = !kumuliertBlocks[bi].collapsed;
      renderKumulierteAnsichtFromState(box);
    });
    box.querySelectorAll("[data-ka-clear-date]").forEach((b) => b.onclick = () => {
      const [bi, ci] = b.dataset.kaClearDate.split("-").map(Number);
      kumuliertBlocks[bi].cards[ci].date = "";
      renderKumulierteAnsichtFromState(box);
    });
    box.querySelectorAll("[data-ka-del]").forEach((b) => b.onclick = () => {
      const [bi, ci] = b.dataset.kaDel.split("-").map(Number);
      kumuliertBlocks[bi].cards.splice(ci, 1);
      renderKumulierteAnsichtFromState(box);
    });
    box.querySelectorAll("[data-ka-add]").forEach((b) => b.onclick = async () => {
      const bi = Number(b.dataset.kaAdd);
      let date = "";
      try { date = (await API.get(`/sequenz-stunden/suggest-date?blockId=${kumuliertBlocks[bi].id}`)).date || ""; }
      catch (e) { /* best effort */ }
      kumuliertBlocks[bi].cards.push({
        id: null, title: "", grobziel: "", isLk: false, isReferat: false,
        isKomplexeArbeit: false, isKlassenarbeit: false, weitereNotenart: "", date,
      });
      renderKumulierteAnsichtFromState(box);
    });
  }

  function renderKumulierteAnsichtFromState(box) {
    resetLocalUndo("ka-");   // Block-/Karten-Indizes verschieben sich hier ggf. – alte Snapshots wären falsch zugeordnet.
    box.querySelector(".ka-blocks").innerHTML =
      kumuliertBlocks.map((b, bi) => kumuliertBlockHtml(b, bi)).join("")
      || '<p class="muted small">Keine Blöcke erfasst.</p>';
    wireKumulierteAnsichtBlocks(box);
  }

  async function saveKumulierteAnsicht(id) {
    try {
      for (const b of kumuliertBlocks) {
        if (b.cards.some((c) => !c.title.trim())) {
          toast("Jede Stunde braucht einen Titel.", false);
          return;
        }
      }
      const snapshots = [];   // { blockId, rows } je Block, für Rückgängig
      for (const b of kumuliertBlocks) {
        let original = [];
        try { original = await SyncEngine.materialize("sequenz_stunden").then((all) => all.filter((r) => r.blockId === b.id)); }
        catch (e) { /* best effort */ }
        snapshots.push({ blockId: b.id, rows: original });
        const keepIds = new Set(b.cards.filter((c) => c.id != null).map((c) => c.id));
        for (const o of original) {
          if (!keepIds.has(o.id)) await SyncEngine.remove("sequenz_stunden", o.id);
        }
        for (const c of b.cards) {
          const body = {
            blockId: b.id, title: c.title.trim(), grobziel: c.grobziel || null,
            isLk: c.isLk, isReferat: c.isReferat, isKomplexeArbeit: c.isKomplexeArbeit,
            isKlassenarbeit: c.isKlassenarbeit, weitereNotenart: c.weitereNotenart || null,
            date: c.date || null,
          };
          if (c.id == null) {
            // reorder unten braucht zwingend die echte Server-id (eigener REST-Call, kein
            // Sync-Payload) — createAndSync statt create, analog saveLesson()/deleteStoffPlan().
            const created = await SyncEngine.createAndSync("sequenz_stunden", body);
            c.id = created.id;
          } else {
            await SyncEngine.update("sequenz_stunden", c.id, body);
          }
        }
        if (b.cards.length) {
          await API.post("/sequenz-stunden/reorder", { blockId: b.id, orderedIds: b.cards.map((c) => c.id) });
          // reorder ist ein eigener REST-Call (kein Sync-Payload) und kann updatedAt serverseitig
          // weiter bumpen (echte Umsortierung) — ohne pull() bliebe der lokale Cache dieser
          // Karten hinter dem Server zurück und die nächste Bearbeitung liefe in einen falschen
          // Konflikt (bereits beobachtet, siehe Backend-Fix in _apply_one/reorder).
          await SyncEngine.pull();
        }
      }
      toast("Sequenzstunden gespeichert.");
      await renderKumulierteAnsicht(id);
      setUndo("Sequenzstunden (kumulierte Ansicht) gespeichert.", async () => {
        for (const s of snapshots) {
          await restoreSequenzStunden(s.blockId, s.rows.map((r) => ({
            title: r.title, grobziel: r.grobziel, isLk: r.isLk, isReferat: r.isReferat,
            isKomplexeArbeit: r.isKomplexeArbeit, isKlassenarbeit: r.isKlassenarbeit,
            weitereNotenart: r.weitereNotenart, date: r.date,
          })));
        }
        await renderKumulierteAnsicht(id);
      });
    } catch (e) { toast(e.message, false); }
  }

  function downloadKumulierteAnsichtPdf(id) {
    const a = document.createElement("a");
    a.href = `/api/stoff-plans/${id}/export-combined?format=pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  /* ---------- KI-Vorschlag (Jahres-Verplanung) ---------- */
  async function aiStoffplan() {
    const syId = Number($("planYear").value), clsId = Number($("planClass").value);
    if (!syId || !clsId) { toast("Bitte Schuljahr und Klasse wählen.", false); return; }
    const btn = $("stoffAiBtn"), label = btn.textContent;
    btn.disabled = true; btn.textContent = "✨ generiere …";
    try {
      // Hintergrund-Job mit Polling (Cloudflare-Timeout-sicher).
      const res = await API.aiJob("/ai/stoffplan", { schoolYearId: syId, classId: clsId },
        (sec) => { btn.textContent = `✨ generiere … ${sec} s`; });
      const blocks = (res.suggestion && res.suggestion.blocks) || [];
      $("planSummary").textContent = `KI-Vorschlag: ${blocks.length} Lernbereiche` + (res.cached ? " (aus Cache)" : "");
      const b = document.querySelector("#planTable tbody");
      b.innerHTML = "";
      blocks.forEach((x) => {
        const tr = document.createElement("tr");
        const zeit = (x.startDate || x.endDate) ? `${esc(deDate(x.startDate) || "?")} – ${esc(deDate(x.endDate) || "?")}` : "—";
        tr.innerHTML = `<td>${esc(x.code)}</td><td>${esc(x.title)}</td><td>${esc(x.ustd)}</td>` +
          `<td>${esc(x.weeks)}</td><td>${zeit}</td>`;
        b.appendChild(tr);
        if (x.note) {
          const noteTr = document.createElement("tr");
          noteTr.className = "stoff-note-row";
          noteTr.innerHTML = `<td colspan="5" class="stoff-note-cell"><span class="stoff-note-label">Hinweis:</span> ${esc(x.note)}</td>`;
          b.appendChild(noteTr);
        }
      });
      // Vorschau für „Plan speichern" merken (U12) – Zeitraum wird serverseitig aus den
      // KI-Wochen + Ferienkalender berechnet (assign_dates_from_weeks).
      state.stoffPreview = blocks.map((x) => ({
        code: x.code, title: x.title, ustd: x.ustd,
        startDate: x.startDate || null, endDate: x.endDate || null, conflictNote: x.note || null,
      }));
      // Direkt-Upload zu einem Lernbereich freischalten (vormals nur nach "Jahresplan vorschlagen" verfügbar).
      // Die KI-Antwort liefert nur den Code, keine lernbereichId – daher gegen die geladenen Lernbereiche der Klasse auflösen.
      const cls = state.classes.find((c) => c.id === clsId);
      const lbList = cls
        ? await getLernbereiche({ subject: cls.subject, grade: cls.grade, track: resolveTrack(cls.subject, cls.grade, cls.track) })
        : [];
      const card = $("stoffUploadCard");
      $("stoffLb").innerHTML = blocks
        .map((x) => ({ x, lb: lbList.find((l) => l.code === x.code) }))
        .filter((p) => p.lb)
        .map((p) => `<option value="${p.lb.id}">${esc(p.x.code)} ${esc(p.x.title)}</option>`).join("");
      card.dataset.syId = syId;
      card.dataset.clsId = clsId;
      card.style.display = $("stoffLb").innerHTML ? "block" : "none";
      toast(res.cached ? "KI-Stoffplan (aus Cache)." : "KI-Stoffplan-Vorschlag erzeugt.");
    } catch (e) { toast(e.message, false); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  // Klassenwechsel (vormals inline im planClass-Change-Handler in app.js): Notizen neu laden,
  // offenen Inline-Editor schließen (gehörte zur alten Klasse), gespeicherte Pläne neu laden.
  function onClassChanged() {
    loadPlanNotes();
    editingStoffPlanId = null;
    loadStoffPlans();
  }

  return {
    loadPlanNotes, savePlanNotes, schedulePlanNotesSave, stoffUpload,
    saveStoffPlan, loadStoffPlans, aiStoffplan, onClassChanged, flushStoffplanAutosave,
  };
}
