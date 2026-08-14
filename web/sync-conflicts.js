/* Offline-Sync (Fundament, F5): generische Konfliktauflösung-UI, lazy-geladen wie notizen.js
   (dynamischer import() erst wenn der Nutzer den Sidebar-Badge "Sync-Konflikte" öffnet).

   Rendert in #modalRoot (dasselbe generische Modal-Root, das app.js für Termin-/Stunden-
   Bearbeitungs-Modals nutzt), nicht in ein eigenes View-Fragment — Konflikte können jederzeit
   auftreten, unabhängig davon, welche View gerade sichtbar ist.

   Bewusst kein Drei-Wege-Feld-Merge: pro Konflikt stehen nur zwei Ganzzeilen-Optionen zur
   Wahl ("meine Version behalten" / "Server-Version übernehmen") — ein Feld-Diff wäre bei
   verschachtelten Entitäten (Lektion+Phasen, Stoffplan+Blöcke) unverhältnismäßig aufwendig
   für den Fundament-Beweis. ENTITY_RENDERERS wird pro Rollout-Entität um einen Eintrag
   ergänzt (Titel/Vorschau aus vorhandenen Formatierungs-Helfern); ohne Eintrag greift ein
   generischer Key-Value-Fallback. */

export function createSyncConflictsModule(ctx) {
  const { $, esc, toast, SyncEngine, entityRenderers } = ctx;

  function renderEntitySummary(entityType, data) {
    const renderer = entityRenderers && entityRenderers[entityType];
    if (renderer) {
      const { title, preview } = renderer(data);
      return `<div class="conflict-entity-title">${esc(title || "(ohne Titel)")}</div>` +
        (preview ? `<div class="conflict-entity-preview">${esc(preview)}</div>` : "");
    }
    // Fallback: generischer Key-Value-Dump, ohne interne Felder (localId/serverId/_syncStatus).
    const rows = Object.entries(data || {})
      .filter(([k]) => !["localId", "serverId", "_syncStatus", "id"].includes(k))
      .map(([k, v]) => `<div><b>${esc(k)}:</b> ${esc(String(v))}</div>`).join("");
    return `<div class="conflict-entity-fallback">${rows}</div>`;
  }

  async function renderConflictList() {
    const conflicts = await SyncEngine.getConflicts();
    if (!conflicts.length) {
      return { html: '<p class="muted small">Keine offenen Sync-Konflikte mehr.</p>', conflicts };
    }
    const items = conflicts.map((c) => {
      const gone = !c.serverEntity;
      return `<div class="conflict-item" data-queue-id="${c.queueId}">
        <div class="conflict-item-head">
          <span class="badge bad">${esc(c.entityType)}</span>
          <span class="muted small">gleichzeitig auf einem anderen Gerät geändert</span>
        </div>
        <div class="conflict-versions">
          <div class="conflict-version">
            <div class="conflict-version-label">Deine Version (offline geändert)</div>
            ${renderEntitySummary(c.entityType, c.payload)}
          </div>
          <div class="conflict-version">
            <div class="conflict-version-label">${gone ? "Server-Stand" : "Version auf dem anderen Gerät"}</div>
            ${gone
              ? '<p class="muted small">Wurde dort inzwischen endgültig gelöscht.</p>'
              : renderEntitySummary(c.entityType, c.serverEntity)}
          </div>
        </div>
        <div class="conflict-actions">
          ${gone ? "" : `<button class="btn small" data-resolve="local" data-queue-id="${c.queueId}">Meine Version behalten</button>`}
          <button class="btn small secondary" data-resolve="server" data-queue-id="${c.queueId}">
            ${gone ? "Verwerfen (bereits gelöscht)" : "Server-Version übernehmen"}
          </button>
        </div>
      </div>`;
    }).join("");
    return { html: items, conflicts };
  }

  async function openOverlay() {
    const { html } = await renderConflictList();
    $("modalRoot").innerHTML =
      `<div class="modal-overlay" id="modalOverlay"><div class="modal-box" style="max-width:640px;">
        <button class="modal-close" id="modalCloseBtn">Schließen</button>
        <h2>Sync-Konflikte</h2>
        <p class="muted small">Diese Datensätze wurden offline geändert, während sie auf einem
          anderen Gerät bereits eine neuere Version bekommen haben. Wähle je Eintrag, welche
          Version gelten soll.</p>
        <div class="modal-section" id="syncConflictList">${html}</div>
      </div></div>`;
    $("modalCloseBtn").onclick = () => { $("modalRoot").innerHTML = ""; };
    wireResolveButtons();
  }

  function wireResolveButtons() {
    const list = $("syncConflictList");
    if (!list) return;
    list.querySelectorAll("[data-resolve]").forEach((btn) => {
      btn.onclick = async () => {
        const queueId = Number(btn.dataset.queueId);
        btn.disabled = true;
        try {
          if (btn.dataset.resolve === "local") await SyncEngine.resolveKeepLocal(queueId);
          else await SyncEngine.resolveKeepServer(queueId);
          toast("Konflikt aufgelöst.");
          await refreshList();
        } catch (e) {
          toast(e.message, false);
          btn.disabled = false;
        }
      };
    });
  }

  async function refreshList() {
    const list = $("syncConflictList");
    if (!list) return; // Overlay wurde inzwischen geschlossen
    const { html, conflicts } = await renderConflictList();
    list.innerHTML = html;
    wireResolveButtons();
    if (!conflicts.length) {
      // Letzter Konflikt aufgelöst — Overlay nach kurzer Pause automatisch schließen.
      setTimeout(() => { const m = $("modalRoot"); if (m && $("syncConflictList")) m.innerHTML = ""; }, 900);
    }
  }

  return { openOverlay };
}
