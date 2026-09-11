/* Noten-Ansicht (Notenmodul, Meilenstein 2), als ES-Modul ausgelagert wie notizen.js /
   sitzplan.js. Wird von app.js per dynamischem import() erst beim ersten Öffnen nachgeladen.

   Bewusst ohne Zugriff auf globale Variablen aus app.js: app.js ist ein klassisches
   <script> ohne type="module", dessen Top-Level-Bindings für ein Modul unsichtbar sind —
   alles Nötige kommt über ctx herein.

   Zwei Ebenen wie im Backend (docs/konzept_noten.md): eine Leistung ist eine Spalte der
   Matrix, die Noten der Schüler sind die Zellen. Das Anlegen einer Leistung und das
   Eintragen der Noten sind deshalb getrennte Schritte.

   Die Durchschnitte rechnet ausschließlich der Server (src/lib/noten.py). Nach jeder
   gespeicherten Note werden nur die Ø-Spalten nachgeladen und ersetzt — die Eingabefelder
   bleiben dabei stehen, sonst verlöre die Zelle beim Tippen den Fokus. */

export function createNotenModule(ctx) {
  const { $, esc, API, toast, state, deDate } = ctx;

  const KINDS = [
    "Leistungskontrolle", "Komplexe Leistung", "Klassenarbeit", "Referat",
    "Präsentation", "mündliche Leistung", "Hausaufgabe", "Stundenleistung",
  ];
  const TERM_LABEL = { HJ1: "1. Halbjahr", HJ2: "2. Halbjahr" };

  let classId = null;
  let term = "HJ1";
  let data = null;          // letzte Antwort von GET /classes/{id}/noten
  let editingItemId = null; // Leistung im Bearbeiten-Modus, sonst null

  /* ---------- Hilfen ---------- */

  // Klassen mit Schülern sind für Noten interessant; "kein Fach"-Klassen (z. B.
  // stellvertretende Klassenleitung) bleiben drin – auch dort kann es Noten geben.
  function classOptions() {
    return state.classes.map((c) =>
      `<option value="${c.id}">${esc(c.name)}${c.subject === "kein Fach" ? "" : " (" + esc(c.subject) + ")"}</option>`
    ).join("");
  }

  function currentItems() { return (data && data.items) || []; }

  function gradeMap() {
    const map = {};
    ((data && data.grades) || []).forEach((g) => { map[g.itemId + ":" + g.studentId] = g; });
    return map;
  }

  function summaryFor(studentId) {
    return ((data && data.summaries) || []).find((s) => s.studentId === studentId) || {};
  }

  // Durchschnitt als deutsche Dezimalzahl; leer, solange nichts bewertet ist.
  function avg(v) { return v == null ? "–" : String(v.toFixed(2)).replace(".", ","); }

  function sizeBadge(size) {
    return size === "gross"
      ? '<span class="noten-badge gross" title="Große Note">groß</span>'
      : '<span class="noten-badge klein" title="Kleine Note">klein</span>';
  }

  /* ---------- Laden ---------- */

  async function load() {
    if (!classId) { data = null; render(); return; }
    try {
      data = await API.get(`/classes/${classId}/noten?term=${term}`);
    } catch (e) {
      data = null;
      toast(e.message, false);
    }
    render();
  }

  // Nur die Ø-Spalten und die Zeugnisnoten-Vorschläge auffrischen, ohne die Eingabefelder
  // neu zu bauen (der Fokus soll beim Tippen in der Zelle bleiben).
  async function refreshAverages() {
    if (!classId) return;
    let fresh;
    try { fresh = await API.get(`/classes/${classId}/noten?term=${term}`); }
    catch (_) { return; }
    if (!data) { data = fresh; render(); return; }
    data.grades = fresh.grades;
    data.summaries = fresh.summaries;
    fresh.summaries.forEach((s) => {
      const row = document.querySelector(`.noten-matrix tr[data-student="${s.studentId}"]`);
      if (!row) return;
      const cells = row.querySelectorAll("td.noten-avg");
      if (cells[0]) cells[0].textContent = avg(s.avgGross);
      if (cells[1]) cells[1].textContent = avg(s.avgKlein);
      if (cells[2]) cells[2].textContent = avg(s.avgGesamt);
    });
  }

  /* ---------- Notenmatrix ---------- */

  function render() {
    renderMatrix();
    renderQuickSelect();
    renderSheetSelect();
    renderTermList();
    const anteil = $("notenAnteil");
    if (anteil && data) anteil.value = data.grossAnteil;
    const hint = $("notenAnteilHint");
    if (hint && data) {
      hint.textContent =
        `Große Noten ${data.grossAnteil} %, kleine Noten ${100 - data.grossAnteil} %.`;
    }
  }

  function renderMatrix() {
    const wrap = $("notenMatrixWrap");
    if (!wrap) return;
    if (!classId) {
      wrap.innerHTML = '<p class="muted small">Bitte oben eine Klasse wählen.</p>';
      return;
    }
    const students = (data && data.students) || [];
    const items = currentItems();
    if (!students.length) {
      wrap.innerHTML = '<p class="muted small">Diese Klasse hat noch keine Schülerliste. ' +
        'Die Namen legst du in den Klassendetails an.</p>';
      return;
    }
    if (!items.length) {
      wrap.innerHTML = `<p class="muted small">Im ${esc(TERM_LABEL[term])} gibt es noch keine ` +
        'Leistung. Lege oben rechts eine an – danach erscheint hier die Notenmatrix.</p>';
      return;
    }

    const map = gradeMap();
    const head = items.map((it) => `
      <th class="noten-col" data-item="${it.id}">
        <div class="noten-col-title">${esc(it.title)}</div>
        <div class="noten-col-meta">${esc(deDate(it.date))} · ${esc(it.kind)} ${sizeBadge(it.size)}</div>
        <div class="noten-col-actions">
          <button type="button" class="noten-icon" data-edit-item="${it.id}" title="Leistung bearbeiten" aria-label="Leistung „${esc(it.title)}“ bearbeiten">✎</button>
          <button type="button" class="noten-icon" data-export-item="${it.id}" title="Auswertung als Word-Datei" aria-label="Auswertung von „${esc(it.title)}“ als Word-Datei">⤓</button>
          <button type="button" class="noten-icon bad" data-del-item="${it.id}" title="Leistung löschen" aria-label="Leistung „${esc(it.title)}“ löschen">✕</button>
        </div>
      </th>`).join("");

    const body = students.map((s) => {
      const sum = summaryFor(s.id);
      const cells = items.map((it) => {
        const g = map[it.id + ":" + s.id];
        const title = g && g.comment ? ` title="${esc(g.comment)}"` : "";
        return `<td class="noten-cell-td${g && g.comment ? " has-comment" : ""}">
          <input class="noten-cell" inputmode="text" autocomplete="off"
                 data-item="${it.id}" data-student="${s.id}"
                 value="${esc(g ? g.label : "")}"${title}
                 aria-label="Note ${esc(s.name)}, ${esc(it.title)}" /></td>`;
      }).join("");
      return `<tr data-student="${s.id}">
        <th scope="row" class="noten-name"><button type="button" class="noten-namebtn" data-sheet="${s.id}" title="Schülerblatt von ${esc(s.name)} anzeigen">${esc(s.name)}</button></th>
        ${cells}
        <td class="noten-avg">${avg(sum.avgGross)}</td>
        <td class="noten-avg">${avg(sum.avgKlein)}</td>
        <td class="noten-avg gesamt">${avg(sum.avgGesamt)}</td>
      </tr>`;
    }).join("");

    wrap.innerHTML = `<table class="noten-matrix">
      <thead><tr><th class="noten-name">Schüler</th>${head}
        <th class="noten-avg">Ø groß</th><th class="noten-avg">Ø klein</th>
        <th class="noten-avg gesamt">Ø gesamt</th></tr></thead>
      <tbody>${body}</tbody></table>`;

    wrap.querySelectorAll(".noten-cell").forEach((inp) => {
      inp.onchange = () => saveCell(inp);
      inp.onkeydown = (e) => onCellKey(e, inp);
    });
    wrap.querySelectorAll("[data-edit-item]").forEach((b) => {
      b.onclick = () => startEditItem(Number(b.dataset.editItem));
    });
    wrap.querySelectorAll("[data-sheet]").forEach((b) => {
      b.onclick = () => showSheet(Number(b.dataset.sheet), true);
    });
    wrap.querySelectorAll("[data-export-item]").forEach((b) => {
      b.onclick = () => download(`/api/grade-items/${b.dataset.exportItem}/export`);
    });
    wrap.querySelectorAll("[data-del-item]").forEach((b) => {
      b.onclick = () => deleteItem(Number(b.dataset.delItem));
    });
  }

  // Tastaturnavigation: Enter und Pfeil hoch/runter wechseln den Schüler in derselben
  // Spalte. Tab bleibt dem Browser überlassen (springt zeilenweise weiter).
  function onCellKey(e, inp) {
    if (e.key !== "Enter" && e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const cells = Array.from(
      document.querySelectorAll(`.noten-cell[data-item="${inp.dataset.item}"]`));
    const idx = cells.indexOf(inp);
    const next = cells[idx + (e.key === "ArrowUp" ? -1 : 1)];
    if (next) { next.focus(); next.select(); } else inp.blur();
  }

  async function saveCell(inp) {
    const raw = inp.value.trim();
    inp.classList.remove("invalid");
    try {
      const saved = await API.put(
        `/grade-items/${inp.dataset.item}/students/${inp.dataset.student}/grade`,
        { value: raw === "" ? null : raw });
      // Serverform übernehmen ("2.25" → "2-"), damit die Zelle zeigt, was gespeichert ist.
      inp.value = saved ? saved.label : "";
      await refreshAverages();
    } catch (e) {
      inp.classList.add("invalid");
      inp.focus();
      toast(e.message, false);
    }
  }

  /* ---------- Leistungen anlegen und bearbeiten ---------- */

  function resetItemForm() {
    editingItemId = null;
    $("notenItemTitle").value = "";
    $("notenItemDate").value = "";
    $("notenItemKind").value = KINDS[0];
    $("notenItemSize").value = "klein";
    $("notenItemTerm").value = "";
    $("notenItemNote").value = "";
    $("notenItemSave").textContent = "Leistung anlegen";
    $("notenItemCancel").classList.add("hidden");
  }

  function startEditItem(id) {
    const it = currentItems().find((x) => x.id === id);
    if (!it) return;
    editingItemId = id;
    $("notenItemTitle").value = it.title;
    $("notenItemDate").value = it.date;
    $("notenItemKind").value = it.kind;
    $("notenItemSize").value = it.size;
    $("notenItemTerm").value = it.term;
    $("notenItemNote").value = it.note || "";
    $("notenItemSave").textContent = "Änderungen speichern";
    $("notenItemCancel").classList.remove("hidden");
    $("notenItemTitle").focus();
    $("notenItemTitle").closest(".card").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function saveItem() {
    if (!classId) { toast("Bitte zuerst eine Klasse wählen.", false); return; }
    const title = $("notenItemTitle").value.trim();
    const date = $("notenItemDate").value;
    if (!title) { toast("Die Leistung braucht eine Bezeichnung.", false); return; }
    if (!date) { toast("Die Leistung braucht ein Datum.", false); return; }
    const body = {
      title, date,
      kind: $("notenItemKind").value,
      size: $("notenItemSize").value,
      note: $("notenItemNote").value.trim() || null,
    };
    const chosenTerm = $("notenItemTerm").value;
    if (chosenTerm) body.term = chosenTerm;

    try {
      const saved = editingItemId
        ? await API.put(`/grade-items/${editingItemId}`, body)
        : await API.post(`/classes/${classId}/grade-items`, body);
      resetItemForm();
      // Landet die Leistung im anderen Halbjahr, dorthin mitwechseln – sonst wäre sie
      // nach dem Speichern scheinbar verschwunden.
      if (saved.term !== term) {
        term = saved.term;
        $("notenTerm").value = term;
        toast(`Gespeichert – die Leistung liegt im ${TERM_LABEL[term]}.`);
      } else {
        toast("Leistung gespeichert.");
      }
      await load();
    } catch (e) { toast(e.message, false); }
  }

  async function deleteItem(id) {
    const it = currentItems().find((x) => x.id === id);
    if (!it) return;
    const count = ((data && data.grades) || []).filter((g) => g.itemId === id).length;
    const warn = count
      ? `\n\nDabei ${count === 1 ? "wird 1 bereits eingetragene Note" : `werden ${count} bereits eingetragene Noten`} gelöscht.`
      : "";
    if (!confirm(`Leistung „${it.title}“ wirklich löschen?${warn}`)) return;
    try {
      await API.del(`/grade-items/${id}`);
      if (editingItemId === id) resetItemForm();
      toast("Leistung gelöscht.");
      await load();
    } catch (e) { toast(e.message, false); }
  }

  /* ---------- Schnellerfassung ---------- */

  function renderQuickSelect() {
    const sel = $("notenQuickItem");
    if (!sel) return;
    const items = currentItems();
    const prev = sel.value;
    sel.innerHTML = items.length
      ? items.map((it) =>
          `<option value="${it.id}">${esc(deDate(it.date))} · ${esc(it.title)}</option>`).join("")
      : '<option value="">– noch keine Leistung –</option>';
    if (prev && items.some((it) => String(it.id) === prev)) sel.value = prev;
    renderQuickList();
  }

  function renderQuickList() {
    const box = $("notenQuickList");
    if (!box) return;
    const itemId = Number($("notenQuickItem").value);
    const students = (data && data.students) || [];
    if (!itemId || !students.length) {
      box.innerHTML = '<p class="muted small">Sobald eine Leistung und eine Schülerliste ' +
        'vorhanden sind, kannst du hier die ganze Klasse am Stück eintragen.</p>';
      return;
    }
    const map = gradeMap();
    box.innerHTML = students.map((s) => {
      const g = map[itemId + ":" + s.id];
      return `<div class="noten-quick-row">
        <span class="noten-quick-name">${esc(s.name)}</span>
        <input class="noten-quick-input" data-student="${s.id}" inputmode="text"
               autocomplete="off" value="${esc(g ? g.label : "")}"
               aria-label="Note ${esc(s.name)}" />
        <input class="noten-quick-comment" data-comment="${s.id}"
               placeholder="Hinweis (optional)" value="${esc(g && g.comment ? g.comment : "")}"
               aria-label="Hinweis zu ${esc(s.name)}" />
      </div>`;
    }).join("");

    // Enter springt zum nächsten Schüler – der eigentliche Zweck der Schnellerfassung.
    const inputs = Array.from(box.querySelectorAll(".noten-quick-input"));
    inputs.forEach((inp, i) => {
      inp.onkeydown = (e) => {
        if (e.key !== "Enter" && e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        const next = inputs[i + (e.key === "ArrowUp" ? -1 : 1)];
        if (next) { next.focus(); next.select(); } else inp.blur();
      };
    });
  }

  async function saveQuick() {
    const itemId = Number($("notenQuickItem").value);
    if (!itemId) return;
    const box = $("notenQuickList");
    const rows = Array.from(box.querySelectorAll(".noten-quick-input")).map((inp) => {
      const sid = Number(inp.dataset.student);
      const comment = box.querySelector(`.noten-quick-comment[data-comment="${sid}"]`);
      const raw = inp.value.trim();
      return { studentId: sid, value: raw === "" ? null : raw,
               comment: comment && comment.value.trim() ? comment.value.trim() : null };
    });
    const status = $("notenQuickStatus");
    status.textContent = "Wird gespeichert …";
    try {
      await API.put(`/grade-items/${itemId}/grades`, { grades: rows });
      await load();
      $("notenQuickItem").value = String(itemId);
      renderQuickList();
      status.textContent = "Gespeichert.";
      toast("Noten gespeichert.");
    } catch (e) {
      status.textContent = "";
      toast(e.message, false);
    }
  }

  /* ---------- Gewichtung ---------- */

  async function saveAnteil() {
    if (!classId) return;
    const value = Number($("notenAnteil").value);
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      toast("Der Anteil muss zwischen 0 und 100 liegen.", false);
      return;
    }
    try {
      await API.put(`/classes/${classId}/noten-gewichtung`, { grossAnteil: value });
      toast("Gewichtung gespeichert.");
      await load();
    } catch (e) { toast(e.message, false); }
  }

  /* ---------- Schülerblatt ---------- */

  function renderSheetSelect() {
    const sel = $("notenSheetStudent");
    if (!sel) return;
    const students = (data && data.students) || [];
    const prev = sel.value;
    sel.innerHTML = students.length
      ? students.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")
      : '<option value="">– keine Schülerliste –</option>';
    if (prev && students.some((s) => String(s.id) === prev)) sel.value = prev;
    renderSheet();
  }

  // scroll=true nur beim Klick aus der Matrix – beim normalen Rendern soll die Seite
  // nicht ungefragt springen.
  function showSheet(studentId, scroll) {
    const sel = $("notenSheetStudent");
    if (!sel) return;
    sel.value = String(studentId);
    renderSheet();
    if (scroll) sel.closest(".card").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderSheet() {
    const box = $("notenSheet");
    if (!box) return;
    const studentId = Number($("notenSheetStudent").value);
    const student = ((data && data.students) || []).find((s) => s.id === studentId);
    if (!student) {
      box.innerHTML = '<p class="muted small">Für diese Klasse ist noch keine Schülerliste angelegt.</p>';
      return;
    }
    const map = gradeMap();
    const rows = currentItems()
      .filter((it) => map[it.id + ":" + studentId])
      .map((it) => {
        const g = map[it.id + ":" + studentId];
        return `<tr>
          <td>${esc(deDate(it.date))}</td>
          <td>${esc(it.title)}</td>
          <td>${esc(it.kind)} ${sizeBadge(it.size)}</td>
          <td class="noten-sheet-note">${esc(g.label)}</td>
          <td class="muted small">${esc(g.comment || "")}</td>
        </tr>`;
      }).join("");

    const sum = summaryFor(studentId);
    const abweichung = isDeviation(sum);
    const zeugnis = sum.termGrade != null
      ? `Zeugnisnote <strong>${esc(noteLabel(sum.termGrade))}</strong>` +
        (abweichung ? ` <span class="muted">(Vorschlag ${esc(suggestionLabel(sum))})</span>` : "")
      : `Vorschlag für die Zeugnisnote: <strong>${esc(suggestionLabel(sum))}</strong>`
        + (sum.termGradeBorderline
            ? ' <span class="noten-grenz">Grenzfall – bitte entscheiden</span>' : "");

    box.innerHTML = (rows
      ? `<div class="table-scroll-wide"><table class="noten-sheet">
           <thead><tr><th>Datum</th><th>Leistung</th><th>Anlass</th><th>Note</th><th>Hinweise</th></tr></thead>
           <tbody>${rows}</tbody></table></div>`
      : '<p class="muted small">In diesem Halbjahr liegt noch keine Note vor.</p>')
      + `<p class="noten-sheet-sum">Ø groß ${avg(sum.avgGross)} · Ø klein ${avg(sum.avgKlein)} · `
      + `<strong>Ø gesamt ${avg(sum.avgGesamt)}</strong> · ${zeugnis}</p>`;
  }

  // Anzeigeform eines Notenwerts – dieselbe Regel wie format_note() in src/lib/noten.py.
  // Der Server liefert das Label nur zu gespeicherten Zellen mit; Vorschläge und
  // Zeugnisnoten kommen als reine Zahl und werden hier formatiert. Ein einfaches Runden
  // täte es nicht: eine von Hand als "2-" gesetzte Zeugnisnote (2,25) stünde sonst als "2"
  // da und behauptete etwas anderes, als gespeichert ist.
  // Zeugnisnoten-Vorschlag. Bei einem Grenzfall (Ø genau x,50) stehen beide Möglichkeiten
  // da statt einer Zahl: dort ist die Entscheidung deine, nicht die der Rundungsregel.
  function suggestionLabel(sum) {
    if (sum.suggestedTermGrade == null) return "–";
    if (sum.termGradeBorderline) {
      return `${Math.round(sum.suggestedTermGrade) - 1} oder ${Math.round(sum.suggestedTermGrade)}`;
    }
    return noteLabel(sum.suggestedTermGrade);
  }

  // Weicht die gesetzte Zeugnisnote wirklich vom Vorschlag ab? Bei einem Grenzfall standen
  // zwei Noten zur Wahl – wer eine davon nimmt, weicht von nichts ab, sondern hat genau die
  // Entscheidung getroffen, um die er gebeten wurde.
  function isDeviation(sum) {
    if (sum.termGrade == null || sum.suggestedTermGrade == null) return false;
    if (sum.termGrade === sum.suggestedTermGrade) return false;
    if (sum.termGradeBorderline && sum.termGrade === sum.suggestedTermGrade - 1) return false;
    return true;
  }

  function noteLabel(value) {
    if (value == null) return "–";
    const ganz = Math.round(value);
    const rest = value - ganz;
    if (ganz >= 1 && ganz <= 6) {
      if (Math.abs(rest) < 1e-6) return String(ganz);
      if (Math.abs(rest + 0.25) < 1e-6) return ganz + "+";
      if (Math.abs(rest - 0.25) < 1e-6) return ganz + "-";
    }
    return String(Number(value.toFixed(2))).replace(".", ",");
  }

  /* ---------- Zeugnisnoten ---------- */

  function renderTermList() {
    const box = $("notenTermList");
    if (!box) return;
    const students = (data && data.students) || [];
    if (!students.length) {
      box.innerHTML = '<p class="muted small">Für diese Klasse ist noch keine Schülerliste angelegt.</p>';
      return;
    }
    box.innerHTML = `<div class="noten-term-row noten-term-head">
        <span>Schüler/in</span><span>Ø gesamt</span><span>Vorschlag</span>
        <span>Zeugnisnote</span><span>Bemerkung</span>
      </div>` + students.map((s) => {
      const sum = summaryFor(s.id);
      const abweichung = isDeviation(sum);
      // Grenzfall nur so lange hervorheben, wie noch keine Note gesetzt ist – danach ist
      // die Entscheidung gefallen und die Zeile soll nicht weiter nach Aufmerksamkeit rufen.
      const grenzfall = sum.termGradeBorderline && sum.termGrade == null;
      return `<div class="noten-term-row${abweichung ? " abweichend" : ""}${grenzfall ? " grenzfall" : ""}" data-term-row="${s.id}">
        <span class="noten-term-name">${esc(s.name)}${grenzfall ? ' <span class="noten-grenz">Grenzfall</span>' : ""}</span>
        <span class="noten-term-avg" data-label="Ø">${avg(sum.avgGesamt)}</span>
        <span class="noten-term-avg" data-label="Vorschlag">${esc(suggestionLabel(sum))}</span>
        <input class="noten-term-input" data-term-value="${s.id}" inputmode="text" autocomplete="off"
               value="${esc(sum.termGrade != null ? noteLabel(sum.termGrade) : "")}"
               aria-label="Zeugnisnote ${esc(s.name)}" />
        <input class="noten-term-comment" data-term-comment="${s.id}"
               placeholder="Begründung (optional)" value="${esc(sum.termGradeComment || "")}"
               aria-label="Begründung zur Zeugnisnote ${esc(s.name)}" />
      </div>`;
    }).join("");

    box.querySelectorAll("[data-term-value],[data-term-comment]").forEach((inp) => {
      inp.onchange = () => saveTermGrade(
        Number(inp.dataset.termValue || inp.dataset.termComment), inp);
    });
  }

  async function saveTermGrade(studentId, inp) {
    const box = $("notenTermList");
    const value = box.querySelector(`[data-term-value="${studentId}"]`).value.trim();
    const comment = box.querySelector(`[data-term-comment="${studentId}"]`).value.trim();
    inp.classList.remove("invalid");
    try {
      await API.put(`/classes/${classId}/students/${studentId}/term-grade?term=${term}`,
                    { value: value === "" ? null : value, comment: comment || null });
      await load();
    } catch (e) {
      inp.classList.add("invalid");
      inp.focus();
      toast(e.message, false);
    }
  }

  /* ---------- Word-Export ---------- */

  // U29: Die Exporte sind mit dem Sicherungspasswort verschlüsselt (Einstellungen →
  // Datensicherung). Ohne Passwort antwortet der Server mit 409 – der Link unten würde
  // dann statt einer Datei die JSON-Fehlermeldung öffnen, deshalb vorher nachsehen.
  // Ein "festgelegt" bleibt gemerkt; ein "fehlt" wird beim nächsten Klick neu geprüft.
  let exportPwSet = false;
  async function exportPasswordReady() {
    if (exportPwSet) return true;
    try {
      exportPwSet = Boolean((await API.get("/settings")).backupPasswordSet);
    } catch (e) {
      toast(e.message, false);
      return false;
    }
    if (!exportPwSet) {
      toast("Bitte zuerst unter Einstellungen → Datensicherung ein Sicherungspasswort festlegen – die Noten-Exporte werden damit verschlüsselt.", false);
    }
    return exportPwSet;
  }

  // Wie downloadStoffPlanPdf in app.js: der Browser holt die Datei selbst, Session-Cookie
  // inklusive. Kein fetch+Blob nötig, und der Dateiname aus dem Content-Disposition-Header
  // (RFC 5987, mit Umlauten) bleibt dabei erhalten.
  async function download(url) {
    if (!(await exportPasswordReady())) return;
    const a = document.createElement("a");
    a.href = url;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function exportClassDoc(kind) {
    if (!classId) { toast("Bitte zuerst eine Klasse wählen.", false); return; }
    download(`/api/classes/${classId}/noten/export/${kind}?term=${term}`);
  }

  /* ---------- Einstieg ---------- */

  let wired = false;

  function wire() {
    if (wired) return;
    wired = true;
    $("notenItemKind").innerHTML =
      KINDS.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join("");
    $("notenClass").onchange = () => {
      classId = Number($("notenClass").value) || null;
      load();
    };
    $("notenTerm").onchange = () => { term = $("notenTerm").value; load(); };
    $("notenItemSave").onclick = saveItem;
    $("notenItemCancel").onclick = resetItemForm;
    $("notenQuickItem").onchange = renderQuickList;
    $("notenQuickSave").onclick = saveQuick;
    $("notenAnteilSave").onclick = saveAnteil;
    $("notenExportMatrix").onclick = () => exportClassDoc("matrix");
    $("notenExportSchueler").onclick = () => exportClassDoc("schueler");
    $("notenExportZeugnis").onclick = () => exportClassDoc("zeugnis");
    $("notenSheetStudent").onchange = renderSheet;
  }

  // Wird bei jedem Öffnen der Ansicht gerufen (showView in app.js).
  async function renderNoten() {
    wire();
    if (!fillClassSelect()) return;
    $("notenTerm").value = term;
    await load();
  }

  // Füllt die Klassenauswahl und hält die bisherige Wahl. Rückgabe false = es gibt keine
  // Klasse, dann steht in der Matrix der Hinweis statt einer leeren Tabelle.
  function fillClassSelect() {
    const sel = $("notenClass");
    if (!sel) return false;
    const prev = classId;
    sel.innerHTML = classOptions();
    if (!state.classes.length) {
      classId = null;
      $("notenMatrixWrap").innerHTML =
        '<p class="muted small">Es gibt noch keine Klasse. Lege zuerst unter „Klassen“ eine an.</p>';
      return false;
    }
    classId = state.classes.some((c) => c.id === prev) ? prev : state.classes[0].id;
    sel.value = String(classId);
    return true;
  }

  // Aus app.js nach jedem Datenrefresh: die Klassenliste kommt asynchron (Sync-Engine) und
  // kann NACH dem ersten Öffnen der Ansicht eintreffen — ohne diesen Haken bliebe die
  // Auswahl dann dauerhaft leer. Es wird nur nachgeladen, wenn wirklich noch nichts steht;
  // sonst würde jeder Hintergrund-Refresh die gerade getippte Zelle neu aufbauen.
  async function onDataRefresh() {
    if (!$("notenClass")) return;
    const had = classId;
    if (!fillClassSelect()) return;
    if (!had) await load();
  }

  // Aus dem Klassendetail: Klasse vorwählen, bevor showView("noten") die Ansicht aufbaut.
  function setClass(cid) {
    classId = Number(cid) || null;
  }

  return { renderNoten, onDataRefresh, setClass };
}
