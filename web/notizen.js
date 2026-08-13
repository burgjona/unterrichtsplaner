/* Notizen-View ("Gedanken sammeln", U17), als ES-Modul ausgelagert (app.js-Splitting,
   zweiter Kandidat nach sitzplan.js). Wird von app.js per dynamischem import() erst
   beim ersten Öffnen der Notizen-Ansicht nachgeladen.

   Bewusst ohne Zugriff auf globale Variablen aus app.js: app.js bleibt ein klassisches
   <script> ohne type="module", dessen Top-Level-let/const-Bindings für ein Modul
   unsichtbar sind. Stattdessen bekommt createNotizenModule() alles explizit übergeben (ctx).

   Die parallele Mini-Notizen-Ansicht in der Klassen-Detailseite (cdNote*-Funktionen in
   app.js) bleibt unangetastet — sie ist eine eigenständige, nicht mit diesem Modul
   verschränkte Implementierung, die lediglich dieselben winzigen Formatierungs-Helfer
   (noteTitle, noteDateLabel, activeNotesSorted) mitbenutzt; die bleiben deshalb in
   app.js und werden hier nur über ctx gelesen, nicht verschoben. */

export function createNotizenModule(ctx) {
  const { $, esc, API, toast, state, refresh, noteTitle, notePreviewText, noteScopeLabel,
          noteDateLabel, activeNotesSorted } = ctx;

  let notizSelectedId = null;      // id der im Editor offenen Notiz, oder null
  let notizIsDraft = false;        // true = Editor zeigt eine neue, noch ungespeicherte Notiz
  let notizDraftScope = "allgemein";
  let notizDraftClassId = null;
  let notizTimer = null;
  let notizSaving = false;
  let notizSearchQuery = "";
  let notizPendingOpenId = null;   // von der Suche gesetzt: nach dem Rendern diese Notiz öffnen

  function renderNotizen() {
    if (notizPendingOpenId != null) {
      notizSelectedId = notizPendingOpenId;
      notizPendingOpenId = null;
      notizIsDraft = false;
    }
    renderNotizList();
    renderNotizMain();
  }

  function renderNotizList() {
    const wrap = $("notizList");
    if (!wrap) return;
    const q = notizSearchQuery.trim().toLowerCase();
    let notes = activeNotesSorted();
    if (q) notes = notes.filter((n) => (noteTitle(n) + " " + (n.bodyMd || "")).toLowerCase().includes(q));
    if (!notes.length) {
      wrap.innerHTML = `<p class="notiz-ws-empty-list">${q ? "Keine Treffer." : 'Noch keine Notizen – „+ Neu" anlegen.'}</p>`;
      return;
    }
    wrap.innerHTML = notes.map((n) => `
      <div class="notiz-item${n.id === notizSelectedId && !notizIsDraft ? " active" : ""}" data-note-id="${n.id}">
        <span class="notiz-item-title">${esc(noteTitle(n))}</span>
        <span class="notiz-item-meta">${esc(noteScopeLabel(n))} · ${esc(noteDateLabel(n.updatedAt))}</span>
        ${notePreviewText(n) ? `<span class="notiz-item-preview">${esc(notePreviewText(n))}</span>` : ""}
      </div>`).join("");
    wrap.querySelectorAll("[data-note-id]").forEach((el) => {
      el.onclick = async () => {
        await flushNotizSave();
        notizSelectedId = Number(el.dataset.noteId);
        notizIsDraft = false;
        renderNotizList();
        renderNotizMain();
      };
    });
  }

  function renderNotizMain() {
    const main = $("notizMain");
    if (!main) return;
    if (notizTimer) { clearTimeout(notizTimer); notizTimer = null; }
    const ws = $("notizWs");

    if (notizIsDraft) {
      const classOpts = state.classes.filter((c) => !c.archivedAt)
        .map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.subject)})</option>`).join("");
      main.innerHTML =
        `<div class="notiz-main-head">` +
        `<button class="btn small secondary notiz-back-btn" id="notizBackBtn">← Notizen</button>` +
        `<div class="notiz-main-head-info"><label class="small muted" for="notizDraftScope">Zuordnung</label>` +
        `<select id="notizDraftScope" class="notiz-main-scope-select">` +
        `<option value="allgemein">Allgemein</option>` +
        (classOpts ? `<optgroup label="Klasse">${classOpts}</optgroup>` : "") +
        `</select></div>` +
        `<button class="btn small secondary" id="notizDraftCancelBtn">Verwerfen</button>` +
        `</div>` +
        `<textarea id="notizenText" class="notizen-text" placeholder="Gedanken sammeln …"></textarea>` +
        `<div class="notizen-foot"><span class="small muted" id="notizenStatus"></span></div>`;
      if (ws) ws.classList.add("notiz-detail-open");
      const sel = $("notizDraftScope");
      sel.value = notizDraftScope === "klasse" && notizDraftClassId ? String(notizDraftClassId) : "allgemein";
      sel.onchange = () => {
        if (sel.value === "allgemein") { notizDraftScope = "allgemein"; notizDraftClassId = null; }
        else { notizDraftScope = "klasse"; notizDraftClassId = Number(sel.value); }
      };
      const ta = $("notizenText");
      ta.value = "";
      ta.oninput = scheduleNotizSave;
      ta.focus();
      $("notizDraftCancelBtn").onclick = () => { notizIsDraft = false; renderNotizen(); };
      bindNotizBackBtn();
      return;
    }

    const note = state.notes.find((n) => n.id === notizSelectedId && n.archivedAt == null);
    if (!note) {
      notizSelectedId = null;
      main.innerHTML = '<div class="notiz-ws-placeholder">Notiz auswählen oder „+ Neu" anlegen.</div>';
      if (ws) ws.classList.remove("notiz-detail-open");
      return;
    }
    if (ws) ws.classList.add("notiz-detail-open");
    main.innerHTML =
      `<div class="notiz-main-head">` +
      `<button class="btn small secondary notiz-back-btn" id="notizBackBtn">← Notizen</button>` +
      `<div class="notiz-main-head-info"><span>${esc(noteScopeLabel(note))} · zuletzt bearbeitet ${esc(noteDateLabel(note.updatedAt))}</span></div>` +
      `<button class="btn small secondary" id="notizArchiveBtn">Notiz archivieren</button>` +
      `</div>` +
      `<textarea id="notizenText" class="notizen-text" placeholder="Gedanken sammeln …"></textarea>` +
      `<div class="notizen-foot"><span class="small muted" id="notizenStatus"></span></div>`;
    const ta = $("notizenText");
    ta.value = note.bodyMd || "";
    ta.oninput = scheduleNotizSave;
    $("notizArchiveBtn").onclick = archiveCurrentNote;
    bindNotizBackBtn();
  }

  // Mobil: „← Notizen" blendet nur die Editor-Spalte wieder aus, ohne die Auswahl zu verwerfen.
  function bindNotizBackBtn() {
    const back = $("notizBackBtn");
    if (back) back.onclick = () => { const ws = $("notizWs"); if (ws) ws.classList.remove("notiz-detail-open"); };
  }

  // Ersetzt nur die Kopfzeile (Entwurf → gespeicherte Notiz), damit Fokus/Cursor im Textfeld erhalten bleiben.
  function promoteNotizDraftHead(note) {
    const head = document.querySelector("#notizMain .notiz-main-head");
    if (!head) return;
    head.innerHTML =
      `<button class="btn small secondary notiz-back-btn" id="notizBackBtn">← Notizen</button>` +
      `<div class="notiz-main-head-info"><span>${esc(noteScopeLabel(note))} · zuletzt bearbeitet ${esc(noteDateLabel(note.updatedAt))}</span></div>` +
      `<button class="btn small secondary" id="notizArchiveBtn">Notiz archivieren</button>`;
    $("notizArchiveBtn").onclick = archiveCurrentNote;
    bindNotizBackBtn();
  }

  function scheduleNotizSave() {
    const status = $("notizenStatus");
    if (status) status.textContent = "…";
    if (notizTimer) clearTimeout(notizTimer);
    notizTimer = setTimeout(saveNotiz, 900);
  }

  async function flushNotizSave() {
    if (notizTimer) { clearTimeout(notizTimer); notizTimer = null; await saveNotiz(); }
  }

  async function saveNotiz() {
    const ta = $("notizenText");
    if (!ta) return;
    if (notizSaving) { scheduleNotizSave(); return; }  // Überlappung vermeiden (kein Doppel-POST)
    const body = ta.value;
    notizSaving = true;
    try {
      if (notizIsDraft) {
        if (!body.trim()) { notizSaving = false; return; }   // leere Entwürfe nicht anlegen
        const created = await API.post("/notes", {
          scope: notizDraftScope,
          classId: notizDraftScope === "klasse" ? notizDraftClassId : null,
          bodyMd: body,
        });
        state.notes.push(created);
        notizIsDraft = false;
        notizSelectedId = created.id;
        renderNotizList();
        promoteNotizDraftHead(created);
      } else if (notizSelectedId != null) {
        const updated = await API.put(`/notes/${notizSelectedId}`, { bodyMd: body });
        const idx = state.notes.findIndex((n) => n.id === notizSelectedId);
        if (idx >= 0) state.notes[idx] = updated;
        renderNotizList();
      }
      const st = $("notizenStatus"); if (st) st.textContent = "Gespeichert.";
    } catch (e) {
      const st = $("notizenStatus"); if (st) st.textContent = "";
      toast(e.message, false);
    } finally {
      notizSaving = false;
    }
  }

  async function archiveCurrentNote() {
    if (notizIsDraft || notizSelectedId == null) return;
    if (!confirm("Diese Notiz archivieren? Sie wandert ins Archiv der Materialbibliothek.")) return;
    try {
      await flushNotizSave();
      await API.post(`/notes/${notizSelectedId}/archive`);
      notizSelectedId = null;
      await refresh();
      renderNotizen();
      toast("Notiz archiviert.");
    } catch (e) { toast(e.message, false); }
  }

  // Startet einen neuen Entwurf (vormals inline im notizNewBtn-Click-Handler in app.js).
  async function startNewDraft() {
    await flushNotizSave();
    notizIsDraft = true;
    notizSelectedId = null;
    notizDraftScope = "allgemein";
    notizDraftClassId = null;
    renderNotizen();
  }

  // Setzt die Suchanfrage und rendert die Liste neu (vormals inline im notizSearch-Input-Handler).
  function setSearchQuery(q) {
    notizSearchQuery = q;
    renderNotizList();
  }

  // Von der globalen Suche gesetzt: die nächste renderNotizen()-Ausführung öffnet diese Notiz.
  function setPendingOpenId(id) {
    notizPendingOpenId = id;
  }

  return {
    renderNotizen, renderNotizList, flushNotizSave, startNewDraft, setSearchQuery, setPendingOpenId,
  };
}
