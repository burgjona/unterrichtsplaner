/* Sequenzplanung-View (Einzelstunden je Stoffplan-Block), als ES-Modul ausgelagert
   (app.js-Splitting, vierter Kandidat nach sitzplan.js/notizen.js/stoffplan.js).
   Wird von app.js per dynamischem import() erst beim ersten Öffnen der
   Sequenzplanung-Ansicht nachgeladen.

   restoreSequenzStunden bleibt in app.js (schon für stoffplan.js als geteilte
   Abhängigkeit injiziert – die "Kumulierte Ansicht" dort und dieses Modul nutzen
   dieselbe Funktion) und wird hier nur über ctx gelesen.

   Der frühere, unabhängige Block zum Verknüpfen von Sequenzstunden MIT einer
   Stunde (updateLessonSeqOptions/renderLessonSeqList/... im Stunden-Modal, Zeilen
   ~100-620 in app.js) gehört NICHT zu diesem Modul – geprüft, keine Überschneidung. */

export function createSequenzplanModule(ctx) {
  const { $, esc, API, toast, state, setUndo, resetLocalUndo, restoreSequenzStunden } = ctx;

  // Karte = { id: number|null, title, grobziel, isLk, isReferat, isKomplexeArbeit,
  //           isKlassenarbeit, weitereNotenart }. id=null → noch nicht gespeichert (neu/KI).
  let seqCards = [];

  function seqNotenartenToFlags(notenarten) {
    const set = new Set(notenarten || []);
    return {
      isLk: set.has("lk"), isReferat: set.has("referat"),
      isKomplexeArbeit: set.has("komplexeArbeit"), isKlassenarbeit: set.has("klassenarbeit"),
    };
  }

  function renderSeqClassSelect() {
    const sel = $("seqClass");
    if (!sel) return;
    const prev = sel.value;
    // Sequenzplanung baut auf dem aktiven Stoffverteilungsplan der Klasse auf – "kein Fach"-
    // Klassen haben keinen solchen Plan, daher hier ebenfalls ausgeblendet (s. renderClassSelects).
    const eligible = state.classes.filter((c) => c.subject !== "kein Fach");
    sel.innerHTML = eligible.map((c) => `<option value="${c.id}">${esc(c.name)} (${esc(c.subject)})</option>`).join("");
    if (eligible.some((c) => String(c.id) === String(prev))) sel.value = prev;
  }

  function renderSeqBlockSelect() {
    const sel = $("seqBlock"), warn = $("seqNoActivePlan");
    if (!sel) return;
    const clsId = Number($("seqClass").value);
    const ap = clsId ? state.activePlans[clsId] : null;
    if (warn) warn.style.display = clsId && !ap ? "" : "none";
    const blocks = ap ? ap.blocks : [];
    sel.innerHTML = blocks
      .map((b) => `<option value="${b.id}">${esc(b.lbCode || "")} ${esc(b.title || "")}</option>`).join("");
  }

  async function loadSeqCardsFromServer() {
    const blockId = Number($("seqBlock").value);
    seqCards = [];
    if (!blockId) { renderSeqCards(); return; }
    try {
      const rows = await API.get(`/sequenz-stunden?blockId=${blockId}`);
      seqCards = rows.map((r) => ({
        id: r.id, title: r.title, grobziel: r.grobziel || "",
        isLk: r.isLk, isReferat: r.isReferat, isKomplexeArbeit: r.isKomplexeArbeit,
        isKlassenarbeit: r.isKlassenarbeit, weitereNotenart: r.weitereNotenart || "",
        date: r.date || "",
      }));
    } catch (e) { toast(e.message, false); }
    renderSeqCards();
  }

  function seqCardHtml(card, idx) {
    const chk = (field, label) =>
      `<label class="small"><input type="checkbox" data-seq-f="${field}" data-seq-i="${idx}" ${card[field] ? "checked" : ""}> ${label}</label>`;
    return `<div class="seq-card" data-seq-card="${idx}" data-local-undo-block="seq-${idx}">
      <div class="seq-card-head">
        <span class="seq-card-num">${idx + 1}.</span>
        <input type="text" class="seq-card-title" data-seq-f="title" data-seq-i="${idx}" value="${esc(card.title)}" placeholder="Titel der Stunde" />
        <button class="btn tiny secondary" data-seq-up="${idx}" ${idx === 0 ? "disabled" : ""} title="Nach vorn">↑</button>
        <button class="btn tiny secondary" data-seq-down="${idx}" ${idx === seqCards.length - 1 ? "disabled" : ""} title="Nach hinten (Position)">↓</button>
        <button class="btn tiny secondary" data-seq-shift="${idx}" ${card.id == null ? "disabled" : ""} title="Diese Stunde hat nicht gereicht – ganze Sequenz ab hier eine Position nach hinten schieben">Nicht gereicht</button>
        <button class="btn tiny secondary" data-local-undo-btn disabled title="Letzte ungespeicherte Änderung an dieser Karte rückgängig machen">Rückgängig</button>
        <button class="btn tiny danger" data-seq-del="${idx}" title="Stunde entfernen">✕</button>
      </div>
      <textarea class="seq-card-grobziel" data-seq-f="grobziel" data-seq-i="${idx}" rows="2" placeholder="Grobziel">${esc(card.grobziel)}</textarea>
      <div class="seq-card-date">
        <label class="small">voraussichtliches Datum
          <input type="date" class="seq-card-date-input" data-seq-f="date" data-seq-i="${idx}" value="${esc(card.date || "")}" />
        </label>
        ${card.date ? `<button class="btn tiny secondary" data-seq-clear-date="${idx}" title="Datum entfernen">✕ Datum</button>` : ""}
      </div>
      <div class="seq-card-notenarten">
        ${chk("isLk", "LK")} ${chk("isReferat", "Referat")} ${chk("isKomplexeArbeit", "Komplexe Arbeit")} ${chk("isKlassenarbeit", "Klassenarbeit")}
        <input type="text" class="seq-card-weitere" data-seq-f="weitereNotenart" data-seq-i="${idx}" value="${esc(card.weitereNotenart)}" placeholder="weitere Notenart (Freitext)" />
      </div>
    </div>`;
  }

  function renderSeqCards() {
    const wrap = $("seqCards"), summary = $("seqSummary");
    if (!wrap) return;
    resetLocalUndo("seq-");   // Karten-Indizes verschieben sich hier ggf. – alte Snapshots wären falsch zugeordnet.
    const blockId = Number($("seqBlock").value);
    if (!blockId) {
      wrap.innerHTML = '<p class="muted small">Bitte Klasse und Block wählen.</p>';
      if (summary) summary.textContent = "";
      return;
    }
    wrap.innerHTML = seqCards.length
      ? seqCards.map((c, i) => seqCardHtml(c, i)).join("")
      : '<p class="muted small">Noch keine Stunden – „✨ Vorschlag generieren" oder „+ Stunde hinzufügen".</p>';
    if (summary) summary.textContent = seqCards.length ? `${seqCards.length} Stunden` : "";

    wrap.querySelectorAll("[data-seq-f]").forEach((el) => {
      const evt = el.tagName === "INPUT" && el.type === "checkbox" ? "change" : "input";
      el.addEventListener(evt, () => {
        const i = Number(el.dataset.seqI), f = el.dataset.seqF;
        seqCards[i][f] = el.type === "checkbox" ? el.checked : el.value;
        if (summary) summary.textContent = `${seqCards.length} Stunden`;   // Karten-Zahl unverändert, nur Refresh vermeiden
      });
    });
    wrap.querySelectorAll("[data-seq-del]").forEach((b) => b.onclick = () => {
      seqCards.splice(Number(b.dataset.seqDel), 1);
      renderSeqCards();
    });
    wrap.querySelectorAll("[data-seq-clear-date]").forEach((b) => b.onclick = () => {
      seqCards[Number(b.dataset.seqClearDate)].date = "";
      renderSeqCards();
    });
    wrap.querySelectorAll("[data-seq-up]").forEach((b) => b.onclick = () => seqMoveCard(Number(b.dataset.seqUp), -1));
    wrap.querySelectorAll("[data-seq-down]").forEach((b) => b.onclick = () => seqMoveCard(Number(b.dataset.seqDown), 1));
    wrap.querySelectorAll("[data-seq-shift]").forEach((b) => b.onclick = () => seqShiftCard(Number(b.dataset.seqShift)));
  }

  function seqMoveCard(idx, dir) {
    const other = idx + dir;
    if (other < 0 || other >= seqCards.length) return;
    [seqCards[idx], seqCards[other]] = [seqCards[other], seqCards[idx]];
    renderSeqCards();
  }

  async function seqShiftCard(idx) {
    const card = seqCards[idx];
    if (!card || card.id == null) return;
    const withCalendar = window.confirm(
      "Auch bereits terminierte, verknüpfte Kalendertermine dieser und nachfolgender Stunden automatisch nachrücken?"
    );
    try {
      const res = await API.post(`/sequenz-stunden/${card.id}/shift`, { withCalendar });
      if (res.overBudget) {
        toast(`Achtung: ${res.plannedCount} Stunden geplant, Richtwert ${res.richtwertUstd ?? "?"} Ustd. – hier oder in einem anderen Lernbereich kürzen.`, false);
      } else {
        toast("Verschoben.");
      }
      await loadSeqCardsFromServer();
    } catch (e) { toast(e.message, false); }
  }

  async function seqAddCard() {
    const blockId = Number($("seqBlock").value);
    if (!blockId) { toast("Bitte zuerst einen Block wählen.", false); return; }
    let date = "";
    try { date = (await API.get(`/sequenz-stunden/suggest-date?blockId=${blockId}`)).date || ""; }
    catch (e) { /* best effort – ohne Stundenplan/Blockstart bleibt das Datum leer */ }
    seqCards.push({
      id: null, title: "", grobziel: "", isLk: false, isReferat: false,
      isKomplexeArbeit: false, isKlassenarbeit: false, weitereNotenart: "", date,
    });
    renderSeqCards();
  }

  async function fillSeqDatesFromSuggestions(blockId, cards) {
    // Karten sind noch ungespeichert (id=null) und tauchen daher server-seitig nicht als
    // "letzte terminierte Stunde" auf – deshalb hier je Karte einzeln nachfragen und den
    // zuletzt vorgeschlagenen Termin als Ausgangspunkt für die nächste Karte weiterreichen.
    // Ist der vorgeschlagene Tag laut Stundenplan eine echte Doppelstunde (spanSlots > 1),
    // bekommt die direkt folgende Karte dasselbe Datum statt eines eigenen Vorschlags –
    // so folgt die Terminierung dem tatsächlichen Einzel-/Doppelstunden-Rhythmus der Klasse.
    let after = null;
    let i = 0;
    while (i < cards.length) {
      let res;
      try {
        const url = after
          ? `/sequenz-stunden/suggest-date?blockId=${blockId}&after=${after}`
          : `/sequenz-stunden/suggest-date?blockId=${blockId}`;
        res = await API.get(url);
      } catch (e) { break; /* best effort – ohne Stundenplan/Blockstart bleiben restliche Daten leer */ }
      if (!res.date) break; /* gleiche Anfrage würde bei unverändertem "after" wieder leer bleiben */
      cards[i].date = res.date;
      after = res.date;
      i++;
      if (res.spanSlots > 1 && i < cards.length) {
        cards[i].date = res.date;
        i++;
      }
    }
  }

  async function aiSequenzplan() {
    const blockId = Number($("seqBlock").value);
    if (!blockId) { toast("Bitte Klasse und Block wählen.", false); return; }
    const btn = $("seqAiBtn"), label = btn.textContent;
    btn.disabled = true; btn.textContent = "✨ generiere …";
    try {
      // Hintergrund-Job mit Polling (Cloudflare-Timeout-sicher) – ein kompletter Block kann
      // mehrere Minuten dauern, deshalb Wartezeit im Button anzeigen.
      const res = await API.aiJob("/ai/sequenzplan", {
        blockId, ideas: $("seqIdeas").value,
        wantLk: $("seqWantLk").checked, wantReferat: $("seqWantReferat").checked,
        wantKomplexeArbeit: $("seqWantKomplexeArbeit").checked, wantKlassenarbeit: $("seqWantKlassenarbeit").checked,
      }, (sec) => { btn.textContent = `✨ generiere … ${sec} s`; });
      const stunden = (res.suggestion && res.suggestion.stunden) || [];
      seqCards = stunden.map((s) => ({
        id: null, title: s.title, grobziel: s.grobziel || "", weitereNotenart: "", date: "",
        ...seqNotenartenToFlags(s.notenarten),
      }));
      await fillSeqDatesFromSuggestions(blockId, seqCards);
      renderSeqCards();
      toast(`Vorschlag mit ${stunden.length} Stunden erzeugt${res.cached ? " (aus Cache)" : ""} – bitte prüfen und speichern.`);
    } catch (e) { toast(e.message, false); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  async function saveSequenzplan() {
    const blockId = Number($("seqBlock").value);
    if (!blockId) { toast("Bitte Klasse und Block wählen.", false); return; }
    if (seqCards.some((c) => !c.title.trim())) { toast("Jede Stunde braucht einen Titel.", false); return; }
    let original = [];
    try { original = await API.get(`/sequenz-stunden?blockId=${blockId}`); } catch (e) { /* best effort */ }
    const keepIds = new Set(seqCards.filter((c) => c.id != null).map((c) => c.id));
    try {
      for (const o of original) {
        if (!keepIds.has(o.id)) await API.del(`/sequenz-stunden/${o.id}`);
      }
      for (const c of seqCards) {
        const body = {
          blockId, title: c.title.trim(), grobziel: c.grobziel || null,
          isLk: c.isLk, isReferat: c.isReferat, isKomplexeArbeit: c.isKomplexeArbeit,
          isKlassenarbeit: c.isKlassenarbeit, weitereNotenart: c.weitereNotenart || null,
          date: c.date || null,
        };
        if (c.id == null) {
          const created = await API.post("/sequenz-stunden", body);
          c.id = created.id;
        } else {
          await API.put(`/sequenz-stunden/${c.id}`, body);
        }
      }
      await API.post("/sequenz-stunden/reorder", { blockId, orderedIds: seqCards.map((c) => c.id) });
      toast("Sequenzplan gespeichert.");
      await loadSeqCardsFromServer();
      setUndo("Sequenzplan gespeichert.", async () => {
        await restoreSequenzStunden(blockId, original.map((r) => ({
          title: r.title, grobziel: r.grobziel, isLk: r.isLk, isReferat: r.isReferat,
          isKomplexeArbeit: r.isKomplexeArbeit, isKlassenarbeit: r.isKlassenarbeit,
          weitereNotenart: r.weitereNotenart, date: r.date,
        })));
        await loadSeqCardsFromServer();
      });
    } catch (e) { toast(e.message, false); }
  }

  return {
    renderSeqClassSelect, renderSeqBlockSelect, loadSeqCardsFromServer,
    seqAddCard, aiSequenzplan, saveSequenzplan,
  };
}
