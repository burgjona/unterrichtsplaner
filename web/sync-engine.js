/* Offline-Sync (Fundament, F4): Pull/Push-Loop über OfflineDB (offline-db.js). Setzt auf
   API (api.js) auf, ersetzt sie nicht. Klassisches <script> wie api.js/offline-db.js, da
   Hintergrund-Sync ab App-Start laufen muss, nicht erst pro View.

   Nur Entitäten in ENTITIES sind sync-fähig. Jede Rollout-Einheit ergänzt hier einen Eintrag
   (kein weiterer Code nötig, sofern die Entität wie "notes" nur direkte, unverschachtelte
   Felder hat) und in offline-db.js einen Store-Eintrag in ENTITY_STORES.

   Identität: state.notes[i].id ist der Server-`id` (Zahl), SOBALD einer bekannt ist — das
   erhält bestehenden Code (Zahlen-Vergleiche, Sprung aus der Suche per numerischer id) exakt
   wie vor der Offline-Umstellung. Nur für einen offline neu angelegten, noch nicht
   synchronisierten Datensatz ist `id` übergangsweise die lokale `localId` (String). Sobald
   der Push die echte id liefert, wird das per onChange-idRemap kommuniziert, damit UI-Code,
   der die alte id in einer Auswahl-Variable hält, sie nachziehen kann. */

const SyncEngine = (() => {
  const ENTITIES = {
    notes: { apiPath: "/notes" },
    todos: { apiPath: "/todos" },
    calendar_categories: { apiPath: "/calendar-categories" },
    school_years: { apiPath: "/school-years" },
    plan_notes: { apiPath: "/planning/notes" },
    timetable_kinds: { apiPath: "/stundenplan/kinds" },
    timetable_slots: { apiPath: "/stundenplan/slots" },
    tropenplan_slots: { apiPath: "/stundenplan/tropenslots" },
    classes: { apiPath: "/classes" },
    students: { apiPath: "/students" },
  };

  const listeners = new Set();
  let pushChain = Promise.resolve();

  function onChange(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function notify(entityType, info) {
    listeners.forEach((fn) => {
      try { fn(entityType, info || {}); } catch (_) { /* ein fehlerhafter Listener stoppt nicht die anderen */ }
    });
  }

  function isOnline() {
    return typeof navigator === "undefined" || navigator.onLine !== false;
  }

  function newLocalId() {
    return "loc_" + (crypto.randomUUID ? crypto.randomUUID() : (Date.now() + "_" + Math.random().toString(36).slice(2)));
  }

  function idOf(record) {
    return record.serverId != null ? record.serverId : record.localId;
  }

  // Zeitstempel im selben Format wie das Backend (strftime('%Y-%m-%d %H:%M:%f','now'), UTC,
  // Leerzeichen statt "T", ohne "Z") statt Date#toISOString() — sonst parsen bestehende
  // Anzeige-Helfer wie noteDateLabel() (app.js) das Datum falsch (erwarten das SQLite-Format).
  function nowTimestamp() {
    return new Date().toISOString().replace("T", " ").replace("Z", "");
  }

  // $localId-Platzhalter in Payload-Feldern auflösen (Cross-Entity-Referenzen auf noch nicht
  // synchronisierte Datensätze anderer Entitäten). notes hat aktuell kein solches Feld —
  // erst mit weiteren Rollout-Entitäten (z. B. classId → classes) wird das wirklich geprüft;
  // die Funktion ist bereits jetzt Teil des Fundaments, weil sie generisch am Payload arbeitet.
  function resolvePlaceholders(payload, localToServerId) {
    const out = {};
    for (const [key, value] of Object.entries(payload)) {
      if (value && typeof value === "object" && typeof value.$localId === "string") {
        out[key] = localToServerId.get(value.$localId) ?? null;
      } else {
        out[key] = value;
      }
    }
    return out;
  }

  // ---------- Materialisierung: gepullte Basiszeilen + noch unbestätigte Mutationen ----------

  async function materialize(entityType) {
    const base = await OfflineDB.getAll(entityType);
    const byLocalId = new Map(base.map((r) => [r.localId, { ...r, id: idOf(r) }]));
    const queue = (await OfflineDB.getMutationsByStatus())
      .filter((m) => m.entityType === entityType)
      .sort((a, b) => a.queueId - b.queueId);
    for (const m of queue) {
      if (m.op === "create") {
        const existing = byLocalId.get(m.localId) || { localId: m.localId, serverId: null };
        const merged = { ...existing, ...m.payload, localId: m.localId, updatedAt: m.clientTimestamp, _syncStatus: m.status };
        byLocalId.set(m.localId, { ...merged, id: idOf(merged) });
      } else if (m.op === "update") {
        const existing = byLocalId.get(m.localId);
        if (existing) {
          const merged = { ...existing, ...m.payload, updatedAt: m.clientTimestamp, _syncStatus: m.status };
          byLocalId.set(m.localId, { ...merged, id: idOf(merged) });
        }
      } else if (m.op === "delete") {
        byLocalId.delete(m.localId);
      }
    }
    return Array.from(byLocalId.values());
  }

  // ---------- Lokale Schreiboperationen: sofort optimistisch in OfflineDB + Mutation-Queue ----------

  async function create(entityType, payload) {
    const localId = newLocalId();
    const clientTimestamp = nowTimestamp();
    await OfflineDB.put(entityType, { localId, serverId: null, ...payload, updatedAt: clientTimestamp });
    await OfflineDB.enqueueMutation({
      entityType, op: "create", localId, entityId: null, baseUpdatedAt: null,
      payload, clientTimestamp,
    });
    notify(entityType, {});
    schedulePush();
    return { ...payload, id: localId, localId, serverId: null, updatedAt: clientTimestamp };
  }

  async function update(entityType, id, payload) {
    const record = await findByAnyId(entityType, id);
    if (!record) throw new Error("Datensatz nicht (mehr) vorhanden.");
    const updatedAt = nowTimestamp();
    const merged = { ...record, ...payload, updatedAt };
    await OfflineDB.put(entityType, merged);
    await OfflineDB.enqueueMutation({
      entityType, op: "update", localId: record.localId,
      entityId: record.serverId ?? null, baseUpdatedAt: record.updatedAt,
      payload, clientTimestamp: updatedAt,
    });
    notify(entityType, {});
    schedulePush();
    return { ...merged, id: idOf(merged) };
  }

  async function remove(entityType, id) {
    const record = await findByAnyId(entityType, id);
    if (!record) return;
    await OfflineDB.enqueueMutation({
      entityType, op: "delete", localId: record.localId,
      entityId: record.serverId ?? null, baseUpdatedAt: record.updatedAt,
      payload: {}, clientTimestamp: nowTimestamp(),
    });
    await OfflineDB.delete(entityType, record.localId);
    notify(entityType, {});
    schedulePush();
  }

  async function findByAnyId(entityType, id) {
    // id ist entweder eine serverId (Zahl) oder eine localId (String "loc_..."). Aufrufer
    // reichen teils rohe dataset-Strings durch (z. B. "5" statt 5) — IndexedDB-Index-Lookups
    // sind typsensitiv, also robust auf Number normalisieren, sofern es keine localId ist.
    if (typeof id === "string" && id.startsWith("loc_")) return OfflineDB.get(entityType, id);
    const hit = await OfflineDB.getByIndex(entityType, "serverId", Number(id));
    return hit || null;
  }

  // ---------- Pull: Änderungen seit Cursor holen, lokale Basiszeilen nachziehen ----------

  let pullChain = Promise.resolve();

  // Läufe serialisieren wie beim Push (pushChain) — mehrere gleichzeitige Aufrufer
  // (SyncEngine.init() beim Start, loadAll() bei jedem Reload, ein View-eigener Pull wie
  // in stundenplan.js) haben sonst denselben Cursor-Race: zwei parallele Läufe lesen
  // "syncCursor" auf demselben (alten) Stand, verarbeiten überlappende Änderungsfenster und
  // überschreiben sich gegenseitig beim Schreiben nach IndexedDB — konkret beobachtet: von
  // 7 gleichzeitig geseedeten Stundenplan-Typen kamen nur die letzten 2 im lokalen Store an.
  function pull() {
    pullChain = pullChain.then(() => pullOnce()).catch(() => {});
    return pullChain;
  }

  async function pullOnce() {
    if (!isOnline()) return;
    let cursor = await OfflineDB.getMeta("syncCursor", 0);
    const entityParam = Object.keys(ENTITIES).join(",");
    const touched = new Set();
    try {
      let hasMore = true;
      while (hasMore) {
        const res = await API.get(`/sync/changes?since=${cursor}&entities=${entityParam}`);
        for (const change of res.changes) {
          touched.add(change.entityType);
          if (change.op === "delete") {
            const existing = await OfflineDB.getByIndex(change.entityType, "serverId", change.entityId);
            if (existing) await OfflineDB.delete(change.entityType, existing.localId);
          } else {
            const existing = await OfflineDB.getByIndex(change.entityType, "serverId", change.entityId);
            const localId = existing ? existing.localId : ("loc_srv_" + change.entityId);
            await OfflineDB.put(change.entityType, { ...change.entity, localId, serverId: change.entityId });
          }
        }
        cursor = res.nextCursor;
        hasMore = res.hasMore;
        await OfflineDB.setMeta("syncCursor", cursor);
      }
      await OfflineDB.setMeta("lastSuccessfulContact", new Date().toISOString());
    } catch (_) {
      // Netzwerkfehler mitten im Pull: abbrechen, nächster Trigger (online-Event/Intervall/App-Start) versucht erneut.
      return;
    }
    touched.forEach((t) => notify(t, {}));
  }

  // ---------- Push: Mutation-Queue FIFO abarbeiten, Konflikte erkennen ----------

  function schedulePush() {
    // Läufe serialisieren (keine zwei parallelen Push-Durchläufe), aber nie eine
    // Anfrage "verlieren" — jeder Aufruf hängt sich ans Ende der Kette.
    pushChain = pushChain.then(() => push()).catch(() => {});
    return pushChain;
  }

  async function push() {
    if (!isOnline()) return;
    const queue = (await OfflineDB.getMutationsByStatus("pending")).sort((a, b) => a.queueId - b.queueId);
    if (!queue.length) return;
    const resolvedServerIds = new Map();
    const idRemapsByEntity = new Map();
    const touched = new Set();

    for (const mutation of queue) {
      if (!isOnline()) break;
      let entityId = mutation.entityId;
      if (entityId == null && mutation.op !== "create") {
        entityId = resolvedServerIds.get(mutation.localId);
        if (entityId == null) {
          const rec = await OfflineDB.get(mutation.entityType, mutation.localId);
          entityId = rec ? rec.serverId : null;
        }
        if (entityId == null) {
          await OfflineDB.updateMutation(mutation.queueId, { status: "blocked" });
          continue;
        }
      }
      const payload = resolvePlaceholders(mutation.payload, resolvedServerIds);

      let apiResult;
      try {
        const res = await API.post("/sync/push", {
          mutations: [{
            clientId: String(mutation.queueId), entityType: mutation.entityType, op: mutation.op,
            entityId, baseUpdatedAt: mutation.baseUpdatedAt, payload,
          }],
        });
        apiResult = res.results[0];
      } catch (_) {
        break; // Netzwerkfehler mitten im Push — Rest der Runde abbrechen, Mutation bleibt pending.
      }

      touched.add(mutation.entityType);
      if (apiResult.status === "applied") {
        if (mutation.op === "delete") {
          await OfflineDB.delete(mutation.entityType, mutation.localId);
        } else {
          await OfflineDB.put(mutation.entityType, {
            ...apiResult.entity, localId: mutation.localId, serverId: apiResult.entityId,
          });
          if (mutation.op === "create") {
            resolvedServerIds.set(mutation.localId, apiResult.entityId);
            const remaps = idRemapsByEntity.get(mutation.entityType) || [];
            remaps.push({ oldId: mutation.localId, newId: apiResult.entityId });
            idRemapsByEntity.set(mutation.entityType, remaps);
          }
        }
        await OfflineDB.deleteMutation(mutation.queueId);
      } else if (apiResult.status === "conflict") {
        await OfflineDB.updateMutation(mutation.queueId, {
          status: "conflict", serverEntity: apiResult.serverEntity,
        });
      } else {
        await OfflineDB.updateMutation(mutation.queueId, {
          status: "failed", lastError: apiResult.detail, attempts: (mutation.attempts || 0) + 1,
        });
      }
    }

    await OfflineDB.setMeta("lastSuccessfulContact", new Date().toISOString());
    touched.forEach((t) => notify(t, { idRemaps: idRemapsByEntity.get(t) || [] }));
  }

  // ---------- Start ----------

  function init() {
    window.addEventListener("online", () => { pull().then(() => schedulePush()); });
    if (isOnline()) pull().then(() => schedulePush());
  }

  // ---------- Konfliktauflösung (F5): Nutzer entscheidet, kein automatisches Last-Write-Wins ----------

  function getConflicts() {
    return OfflineDB.getMutationsByStatus("conflict");
  }

  // "Meine Version behalten": Mutation erneut auf "pending" setzen, aber mit dem inzwischen
  // aktuellen Server-Stand als neue Basis — der nächste Push überschreibt den Server damit
  // bewusst (erzwungenes Update), statt erneut in denselben Konflikt zu laufen.
  async function resolveKeepLocal(queueId) {
    const mutation = await OfflineDB.get("_mutationQueue", queueId);
    if (!mutation || mutation.status !== "conflict") return;
    if (!mutation.serverEntity) {
      // Zielzeile existiert serverseitig nicht mehr (endgültig gelöscht) — "meine Version
      // behalten" ist hier nicht sinnvoll anwendbar (es gibt kein "Update" auf nichts mehr).
      throw new Error("Diese Notiz wurde auf einem anderen Gerät bereits endgültig gelöscht.");
    }
    await OfflineDB.updateMutation(queueId, {
      status: "pending", baseUpdatedAt: mutation.serverEntity.updatedAt, serverEntity: null,
    });
    notify(mutation.entityType, {});
    await push();
  }

  // "Server-Version übernehmen": lokale Basiszeile durch die Server-Version ersetzen (oder
  // löschen, falls der Server die Zeile nicht mehr hat), gepufferte Mutation verwerfen.
  async function resolveKeepServer(queueId) {
    const mutation = await OfflineDB.get("_mutationQueue", queueId);
    if (!mutation || mutation.status !== "conflict") return;
    if (mutation.serverEntity) {
      await OfflineDB.put(mutation.entityType, {
        ...mutation.serverEntity, localId: mutation.localId, serverId: mutation.serverEntity.id,
      });
    } else {
      await OfflineDB.delete(mutation.entityType, mutation.localId);
    }
    await OfflineDB.deleteMutation(queueId);
    notify(mutation.entityType, {});
  }

  return {
    init, pull, push: schedulePush, materialize, create, update, remove, onChange,
    getConflicts, resolveKeepLocal, resolveKeepServer,
  };
})();
