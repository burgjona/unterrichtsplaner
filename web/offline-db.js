/* Offline-Sync (Fundament, F3): dünner IndexedDB-Wrapper als lokale Datenhaltung für die
   Sync-Engine (sync-engine.js, F4). Bewusst kein ES-Modul, sondern klassisches <script> wie
   api.js — die Sync-Engine muss ab App-Start aktiv sein (Hintergrund-Sync für ALLE Views),
   nicht erst beim Öffnen einer bestimmten View wie die lazy-geladenen View-Module.

   Objekt-Stores:
   - Ein Store pro synchronisierter Backend-Entität (aktuell nur "notes", Beweis-Entität der
     Fundament-Phase). keyPath "localId" (client-generiert), NICHT die Server-id — ein offline
     neu angelegter Datensatz hat noch keine. "serverId" wird als eigenes Feld ergänzt, sobald
     der Server eine id zurückgegeben hat (Index unique, überspringt Datensätze ohne das Feld).
   - "_mutationQueue": FIFO-Warteschlange gepufferter Schreibvorgänge (keyPath "queueId"
     autoIncrement — Einfügereihenfolge = Ausführungsreihenfolge).
   - "_meta": Key/Value-Ablage für Sync-Cursor, letzten erfolgreichen Kontakt etc.

   Jede künftige Rollout-Einheit (weitere Entität) bumpt DB_VERSION um 1 und ergänzt ihren
   Store in ENTITY_STORES — onupgradeneeded legt beim Öffnen alle noch fehlenden Stores an
   (idempotent), das ist der natürliche Anknüpfungspunkt pro Meilenstein. */

const OfflineDB = (() => {
  const DB_NAME = "ldb_offline";
  const DB_VERSION = 14;

  // Entitäts-Stores: ein Eintrag pro synchronisierter Backend-Tabelle.
  const ENTITY_STORES = [
    "notes", "todos", "calendar_categories", "school_years", "plan_notes",
    "timetable_kinds", "timetable_slots", "tropenplan_slots", "classes", "students",
    "timetable_plans", "lessons", "stoff_plans", "timetable_entries", "timetable_overrides",
  ];

  let dbPromise = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        for (const name of ENTITY_STORES) {
          if (db.objectStoreNames.contains(name)) continue;
          const store = db.createObjectStore(name, { keyPath: "localId" });
          store.createIndex("serverId", "serverId", { unique: true });
          store.createIndex("updatedAt", "updatedAt", { unique: false });
        }
        if (!db.objectStoreNames.contains("_mutationQueue")) {
          const q = db.createObjectStore("_mutationQueue", {
            keyPath: "queueId", autoIncrement: true,
          });
          q.createIndex("status", "status", { unique: false });
        }
        if (!db.objectStoreNames.contains("_meta")) {
          db.createObjectStore("_meta", { keyPath: "key" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
      req.onblocked = () => reject(new Error("IndexedDB-Upgrade blockiert (anderer Tab offen?)."));
    });
    return dbPromise;
  }

  function promisify(req) {
    return new Promise((resolve, reject) => {
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function withStore(storeName, mode, fn) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, mode);
      const store = tx.objectStore(storeName);
      let result;
      Promise.resolve(fn(store))
        .then((r) => { result = r; })
        .catch(reject);
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error("IndexedDB-Transaktion abgebrochen."));
    });
  }

  // ---------- Generische Store-Operationen (für Entitäts-Stores und _meta/_mutationQueue) ----------

  function get(storeName, key) {
    return withStore(storeName, "readonly", (store) => promisify(store.get(key)));
  }

  function getByIndex(storeName, indexName, value) {
    return withStore(storeName, "readonly", (store) => promisify(store.index(indexName).get(value)));
  }

  function getAll(storeName) {
    return withStore(storeName, "readonly", (store) => promisify(store.getAll()));
  }

  function put(storeName, value) {
    return withStore(storeName, "readwrite", (store) => promisify(store.put(value)));
  }

  function del(storeName, key) {
    return withStore(storeName, "readwrite", (store) => promisify(store.delete(key)));
  }

  function clear(storeName) {
    return withStore(storeName, "readwrite", (store) => promisify(store.clear()));
  }

  // ---------- _meta: Key/Value-Ablage ----------

  async function getMeta(key, fallback = null) {
    const row = await get("_meta", key);
    return row ? row.value : fallback;
  }

  function setMeta(key, value) {
    return put("_meta", { key, value });
  }

  // ---------- _mutationQueue: FIFO, gefiltert nach status ----------

  function enqueueMutation(entry) {
    // queueId wird von IndexedDB vergeben (autoIncrement) — bestimmt die Ausführungsreihenfolge.
    return withStore("_mutationQueue", "readwrite", (store) =>
      promisify(store.add({ status: "pending", attempts: 0, lastError: null, ...entry }))
    );
  }

  async function getMutationsByStatus(status) {
    const all = await getAll("_mutationQueue");
    return status ? all.filter((m) => m.status === status) : all;
  }

  async function updateMutation(queueId, patch) {
    return withStore("_mutationQueue", "readwrite", async (store) => {
      const current = await promisify(store.get(queueId));
      if (!current) return null;
      const updated = { ...current, ...patch };
      await promisify(store.put(updated));
      return updated;
    });
  }

  function deleteMutation(queueId) {
    return del("_mutationQueue", queueId);
  }

  return {
    ENTITY_STORES,
    open: openDb,
    get, getByIndex, getAll, put, delete: del, clear,
    getMeta, setMeta,
    enqueueMutation, getMutationsByStatus, updateMutation, deleteMutation,
  };
})();
