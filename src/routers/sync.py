"""Offline-Sync (Fundament): generischer Pull (Änderungen seit Cursor) und Push (gepufferte
Mutationen mit Optimistic-Concurrency-Konflikterkennung).

Nur in ENTITY_REGISTRY eingetragene Entitäten sind sync-fähig. Jede Rollout-Einheit ergänzt
hier einen Eintrag (Handler-Dict mit fetch/create/update/delete aus dem jeweiligen Router)
sowie in einer eigenen Migration die drei sync_log-Trigger für ihre Tabelle
(vgl. migrations/031_sync_log.sql).

Cursor = sync_log.seq (strikt monoton, kollisionsfrei über alle Tabellen hinweg — anders als
ein Timestamp, der bei mehreren Änderungen im selben Sekundenfenster mehrdeutig wäre).
Eine op='delete'-Zeile in sync_log ist gleichzeitig der Tombstone.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id
from ..schemas import (
    SyncChangeOut, SyncChangesOut, SyncMutationIn, SyncMutationResult, SyncPushIn, SyncPushOut,
)
from . import calendar_categories as calendar_categories_router
from . import classes as classes_router
from . import lessons as lessons_router
from . import notes as notes_router
from . import planning as planning_router
from . import school_years as school_years_router
from . import stoffplan as stoffplan_router
from . import students as students_router
from . import stundenplan as stundenplan_router
from . import todos as todos_router

router = APIRouter(prefix="/sync", tags=["sync"])

ENTITY_REGISTRY = {
    "notes": notes_router.SYNC_HANDLER,
    "todos": todos_router.SYNC_HANDLER,
    "calendar_categories": calendar_categories_router.SYNC_HANDLER,
    "school_years": school_years_router.SYNC_HANDLER,
    "classes": classes_router.SYNC_HANDLER,
    "students": students_router.SYNC_HANDLER,
    "lessons": lessons_router.SYNC_HANDLER,
    "stoff_plans": stoffplan_router.SYNC_HANDLER,
    "plan_notes": planning_router.SYNC_HANDLER,
    "timetable_kinds": stundenplan_router.SYNC_HANDLER_TIMETABLE_KINDS,
    "timetable_slots": stundenplan_router.SYNC_HANDLER_TIMETABLE_SLOTS,
    "timetable_plans": stundenplan_router.SYNC_HANDLER_TIMETABLE_PLANS,
    "timetable_entries": stundenplan_router.SYNC_HANDLER_TIMETABLE_ENTRIES,
    "tropenplan_slots": stundenplan_router.SYNC_HANDLER_TROPENPLAN_SLOTS,
}

PAGE_SIZE = 500


@router.get("/changes", response_model=SyncChangesOut)
def changes(
    since: int = Query(0),
    entities: Optional[str] = Query(None, alias="entities"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    wanted = set(ENTITY_REGISTRY) if not entities else set(entities.split(",")) & set(ENTITY_REGISTRY)
    if not wanted:
        return SyncChangesOut(changes=[], next_cursor=since, has_more=False)

    placeholders = ",".join("?" for _ in wanted)
    rows = conn.execute(
        f"SELECT seq, entity_type, entity_id, op FROM sync_log "
        f"WHERE user_id = ? AND seq > ? AND entity_type IN ({placeholders}) "
        f"ORDER BY seq LIMIT ?",
        (user_id, since, *wanted, PAGE_SIZE + 1),
    ).fetchall()

    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    out = []
    for row in rows:
        handler = ENTITY_REGISTRY[row["entity_type"]]
        op = row["op"]
        entity_payload = None
        if op == "upsert":
            entity = handler["fetch"](conn, user_id, row["entity_id"])
            if entity is None:
                # Zwischenzeitlich (nach dem Log-Eintrag) doch gelöscht — als Delete
                # ausliefern, statt dem Client einen nicht existierenden Datensatz zu zeigen.
                op = "delete"
            else:
                entity_payload = entity.model_dump(by_alias=True)
        out.append(SyncChangeOut(
            seq=row["seq"], entity_type=row["entity_type"], entity_id=row["entity_id"],
            op=op, entity=entity_payload,
        ))

    next_cursor = rows[-1]["seq"] if rows else since
    return SyncChangesOut(changes=out, next_cursor=next_cursor, has_more=has_more)


@router.post("/push", response_model=SyncPushOut)
def push(body: SyncPushIn, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return SyncPushOut(results=[_apply_one(conn, user_id, m) for m in body.mutations])


def _apply_one(conn, user_id, mutation: SyncMutationIn) -> SyncMutationResult:
    handler = ENTITY_REGISTRY.get(mutation.entity_type)
    if handler is None:
        return SyncMutationResult(
            client_id=mutation.client_id, status="error",
            detail=f"Unbekannter Entitätstyp '{mutation.entity_type}'.",
        )
    try:
        if mutation.op == "create":
            entity = handler["create"](conn, user_id, mutation.payload)
            conn.commit()
            return SyncMutationResult(
                client_id=mutation.client_id, status="applied",
                entity_id=entity.id, entity=entity.model_dump(by_alias=True),
            )

        if mutation.entity_id is None:
            return SyncMutationResult(
                client_id=mutation.client_id, status="error",
                detail="entityId erforderlich für 'update'/'delete'.",
            )

        current = handler["fetch"](conn, user_id, mutation.entity_id)
        if current is None:
            # Server-seitig bereits (endgültig) gelöscht — Client kann nicht mehr
            # gewinnen, muss lokal aufräumen statt erneut zu versuchen.
            return SyncMutationResult(
                client_id=mutation.client_id, status="conflict",
                entity_id=mutation.entity_id, server_entity=None,
            )
        if current.updated_at != mutation.base_updated_at:
            return SyncMutationResult(
                client_id=mutation.client_id, status="conflict",
                entity_id=mutation.entity_id,
                server_entity=current.model_dump(by_alias=True),
            )

        if mutation.op == "update":
            entity = handler["update"](conn, user_id, mutation.entity_id, mutation.payload)
            conn.commit()
            return SyncMutationResult(
                client_id=mutation.client_id, status="applied",
                entity_id=entity.id, entity=entity.model_dump(by_alias=True),
            )
        if mutation.op == "delete":
            handler["delete"](conn, user_id, mutation.entity_id)
            conn.commit()
            return SyncMutationResult(
                client_id=mutation.client_id, status="applied", entity_id=mutation.entity_id,
            )
        return SyncMutationResult(
            client_id=mutation.client_id, status="error",
            detail=f"Unbekannte Operation '{mutation.op}'.",
        )
    except HTTPException as exc:
        conn.rollback()
        return SyncMutationResult(client_id=mutation.client_id, status="error", detail=str(exc.detail))
