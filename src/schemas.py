"""Pydantic-Modelle. API spricht camelCase (Alias), DB/Python snake_case.

FastAPI serialisiert Responses standardmäßig per Alias (camelCase); durch
populate_by_name werden eingehend beide Schreibweisen akzeptiert.
Python 3.9: durchgängig typing.Optional/List statt PEP-604-'|'.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# ---------- Auth (Meilenstein 2) ----------
class RegisterIn(Base):
    email: str
    display_name: str
    password: str


class LoginIn(Base):
    email: str
    password: str


class ApiKeyIn(Base):
    api_key: str


class GoogleKeyIn(Base):
    """Service-Account-JSON-Schlüssel + Ziel-Kalender-ID (U21)."""
    key_json: str
    calendar_id: str


class SchulmanagerIcalIn(Base):
    """Persönlicher Schulmanager-ICS-Stundenplan-Link (M1a)."""
    url: str


class SettingsOut(Base):
    api_key_status: str            # "aktiv" | "kein Key"
    api_key_last4: Optional[str] = None
    api_key_set_at: Optional[str] = None
    secret_configured: bool        # ob APP_SECRET_KEY serverseitig gesetzt ist
    theme: str = "fruehling"       # fruehling | sommer | herbst | winter
    dark_mode: bool = False
    font: str = "verspielt"        # verspielt | standard
    # Google-Kalender-Sync (U21)
    google_key_set: bool = False
    google_calendar_id: Optional[str] = None
    google_last_sync: Optional[str] = None
    # Schulmanager-ICS-Sync (M1a)
    schulmanager_ical_set: bool = False
    schulmanager_last_sync: Optional[str] = None
    # Deploy-Info (aus Docker-Build-Args, siehe DEPLOY.md)
    deploy_commit: str = "unbekannt"
    deploy_time: str = "unbekannt"


# ---------- Nutzer (Profil) ----------
class UserCreate(Base):
    email: str
    display_name: str
    avatar_path: Optional[str] = None


class UserUpdate(Base):
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_path: Optional[str] = None


class UserOut(Base):
    id: int
    email: str
    display_name: str
    avatar_path: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- Schuljahre ----------
class SchoolYearCreate(Base):
    label: str
    start_date: str
    end_date: str


class SchoolYearUpdate(Base):
    label: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SchoolYearOut(Base):
    id: int
    label: str
    start_date: str
    end_date: str
    created_at: str
    updated_at: str


# ---------- Klassen ----------
class ClassCreate(Base):
    name: str
    subject: str
    grade: int
    track: Optional[str] = None
    weekly_hours: int = 2
    parallel_group: Optional[str] = None
    school_year_id: Optional[int] = None
    visible_in_calendar: bool = True


class ClassUpdate(Base):
    name: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[int] = None
    track: Optional[str] = None
    weekly_hours: Optional[int] = None
    parallel_group: Optional[str] = None
    school_year_id: Optional[int] = None
    visible_in_calendar: Optional[bool] = None


class ClassOut(Base):
    id: int
    name: str
    subject: str
    grade: int
    track: Optional[str] = None
    weekly_hours: int
    parallel_group: Optional[str] = None
    school_year_id: Optional[int] = None
    visible_in_calendar: bool
    archived_at: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- Lernbereiche (Referenz) ----------
class LernbereichCreate(Base):
    subject: str
    grade: int
    track: str
    code: str
    title: str
    richtwert_ustd: Optional[int] = None
    sort_order: int = 0
    source: Optional[str] = None


class LernbereichOut(Base):
    id: int
    subject: str
    grade: int
    track: str
    code: str
    title: str
    richtwert_ustd: Optional[int] = None
    sort_order: int
    source: Optional[str] = None


# ---------- Stunden ----------
class Klafki(Base):
    gegenwart: str = ""
    zukunft: str = ""
    exemplarisch: str = ""
    zugang: str = ""
    struktur: str = ""


class Bibox(Base):
    werk: str = ""
    seite: str = ""
    notiz: str = ""


class TafelbildBlock(Base):
    ueberschrift: str = ""
    punkte: List[str] = Field(default_factory=list)
    hervorgehoben: bool = False


class Tafelbild(Base):
    titel: str = ""
    bloecke: List[TafelbildBlock] = Field(default_factory=list)


class PhaseIn(Base):
    phase_name: str
    minutes: Optional[int] = None
    social_form: Optional[str] = None
    method: Optional[str] = None
    material: Optional[str] = None
    teacher_activity: Optional[str] = None
    student_activity: Optional[str] = None
    gme: Optional[str] = None


class PhaseOut(PhaseIn):
    id: int
    sort_order: int


class LessonCreate(Base):
    title: str
    subject: str
    grade: Optional[int] = None
    class_id: Optional[int] = None
    lernbereich_id: Optional[int] = None
    lesson_type: Optional[str] = None
    duration_minutes: int = 45
    time: Optional[str] = None
    date: Optional[str] = None
    klafki: Klafki = Field(default_factory=Klafki)
    meyer_plan: Optional[List[str]] = None
    diff: Optional[str] = None
    selbst_lernen: Optional[str] = None
    bibox: Bibox = Field(default_factory=Bibox)
    tafelbild_eingabe: Optional[str] = None
    tafelbild: Tafelbild = Field(default_factory=Tafelbild)
    tafelbild_notiz: Optional[str] = None
    phases: List[PhaseIn] = Field(default_factory=list)
    lernziele: List["LernzielIn"] = Field(default_factory=list)

    @field_validator("duration_minutes")
    @classmethod
    def _dur_45_or_90(cls, v: int) -> int:
        if v not in (45, 90):
            raise ValueError("Stundendauer muss 45 oder 90 Minuten sein.")
        return v


class LessonUpdate(Base):
    title: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[int] = None
    class_id: Optional[int] = None
    lernbereich_id: Optional[int] = None
    lesson_type: Optional[str] = None
    duration_minutes: Optional[int] = None
    time: Optional[str] = None
    date: Optional[str] = None
    klafki: Optional[Klafki] = None
    meyer_plan: Optional[List[str]] = None
    diff: Optional[str] = None
    selbst_lernen: Optional[str] = None
    bibox: Optional[Bibox] = None
    tafelbild_eingabe: Optional[str] = None
    tafelbild: Optional[Tafelbild] = None
    tafelbild_notiz: Optional[str] = None
    phases: Optional[List[PhaseIn]] = None
    lernziele: Optional[List["LernzielIn"]] = None
    reflection_skipped: Optional[bool] = None

    @field_validator("duration_minutes")
    @classmethod
    def _dur_45_or_90(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in (45, 90):
            raise ValueError("Stundendauer muss 45 oder 90 Minuten sein.")
        return v


class LessonOut(Base):
    id: int
    title: str
    subject: str
    grade: Optional[int] = None
    class_id: Optional[int] = None
    lernbereich_id: Optional[int] = None
    lesson_type: Optional[str] = None
    duration_minutes: int = 45
    time: Optional[str] = None
    date: Optional[str] = None
    klafki: Klafki
    meyer_plan: Optional[List[str]] = None
    diff: Optional[str] = None
    selbst_lernen: Optional[str] = None
    bibox: Bibox
    tafelbild_eingabe: Optional[str] = None
    tafelbild: Tafelbild = Field(default_factory=Tafelbild)
    tafelbild_notiz: Optional[str] = None
    phases: List[PhaseOut] = Field(default_factory=list)
    lernziele: List["LernzielOut"] = Field(default_factory=list)
    created_at: str
    updated_at: str


class LessonUpcomingSlotOut(Base):
    """Ein laut Stundenplan realer künftiger Unterrichtstermin der Klasse dieser Stunde –
    Auswahlliste für "Stunde verschieben" im Planungskalender (nur echte Slots, kein Freitext)."""
    date: str
    time: Optional[str] = None
    span_slots: Optional[int] = None


class LessonMoveSlotIn(Base):
    date: str
    time: Optional[str] = None
    with_calendar: bool = True   # auch nachfolgende, bereits terminierte Sequenzstunden nachrücken?


class LessonMoveSlotOut(Base):
    lesson: LessonOut
    # gesetzt, wenn die Stunde mit einer Sequenzstunde verknüpft war -- die neue, an den
    # Zielort verschobene Kopie (die Ursprungszeile bleibt mit moved_to_id darauf stehen).
    new_sequenz_stunde_id: Optional[int] = None
    over_budget: bool = False
    planned_count: Optional[int] = None
    richtwert_ustd: Optional[int] = None


# ---------- Kalender ----------
class CalendarCreate(Base):
    title: str
    entry_date: str
    end_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    all_day: bool = True
    entry_type: str = "normal"
    category_id: Optional[int] = None
    class_id: Optional[int] = None
    lesson_id: Optional[int] = None
    school_year_id: Optional[int] = None
    is_fixed: bool = False
    room: Optional[str] = None
    notes: Optional[str] = None
    class_ids: List[int] = []


class CalendarUpdate(Base):
    title: Optional[str] = None
    entry_date: Optional[str] = None
    end_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    all_day: Optional[bool] = None
    entry_type: Optional[str] = None
    category_id: Optional[int] = None
    class_id: Optional[int] = None
    lesson_id: Optional[int] = None
    school_year_id: Optional[int] = None
    is_fixed: Optional[bool] = None
    room: Optional[str] = None
    notes: Optional[str] = None
    class_ids: Optional[List[int]] = None


class CalendarOut(Base):
    id: int
    title: str
    entry_date: str
    end_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    all_day: bool = True
    entry_type: str
    category_id: Optional[int] = None
    class_id: Optional[int] = None
    lesson_id: Optional[int] = None
    school_year_id: Optional[int] = None
    is_fixed: bool
    room: Optional[str] = None
    notes: Optional[str] = None
    class_ids: List[int] = []
    auto_generated: bool = False
    archived_at: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None          # U26: Last-write-wins-Zeitstempel (Google-Sync)
    google_event_id: Optional[str] = None     # U26: gesetzt = mit Google-Kalender verknuepft


# ---------- Kalender-Kategorien (U11) ----------
class CalendarCategoryCreate(Base):
    name: str
    color: str
    sort_order: int = 0


class CalendarCategoryUpdate(Base):
    name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


class CalendarCategoryOut(Base):
    id: int
    name: str
    color: str
    sort_order: int
    created_at: str
    updated_at: str


# ---------- Jahresplan-Import (U20) ----------
class ImportSuggestion(Base):
    """Ein von der KI erkannter Terminvorschlag aus dem Jahresplan-PDF (nichts gespeichert)."""
    datum: str
    end_datum: Optional[str] = None
    titel: str
    kategorie_vorschlag: Optional[str] = None


class ImportEntry(Base):
    """Ein vom Nutzer bestätigter Termin, der übernommen werden soll."""
    datum: str
    end_datum: Optional[str] = None
    titel: str
    category_id: Optional[int] = None


class ImportCommitIn(Base):
    entries: List[ImportEntry]


# ---------- Materialien ----------
class MaterialCreate(Base):
    filename: str
    stored_path: Optional[str] = None
    mime_type: Optional[str] = None
    byte_size: Optional[int] = None
    sha256: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[int] = None
    school_year_id: Optional[int] = None
    lb_label: Optional[str] = None
    status: str = "neu"
    tag: Optional[str] = None
    external_link: Optional[str] = None


class MaterialUpdate(Base):
    filename: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[int] = None
    school_year_id: Optional[int] = None
    lb_label: Optional[str] = None
    status: Optional[str] = None
    tag: Optional[str] = None
    external_link: Optional[str] = None


class MaterialOut(Base):
    id: int
    filename: str
    stored_path: str
    mime_type: Optional[str] = None
    byte_size: Optional[int] = None
    sha256: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[int] = None
    school_year_id: Optional[int] = None
    lb_label: Optional[str] = None
    status: str
    tag: Optional[str] = None
    external_link: Optional[str] = None
    extracted: bool
    archived_at: Optional[str] = None
    created_at: str
    updated_at: str


class MaterialLink(Base):
    lesson_id: Optional[int] = None
    lernbereich_id: Optional[int] = None


class SearchHit(Base):
    material_id: int
    filename: str
    page_from: Optional[int] = None
    page_to: Optional[int] = None
    snippet: str


# ---------- ASUV (Meilenstein 6) ----------
class AsuvDraft(Base):
    bedingung_org: str = ""
    bedingung_lern: str = ""
    bedingung_einordnung: str = ""
    ziele: str = ""
    sachanalyse: str = ""
    quellen: str = ""
    didaktisch: str = ""
    reduktion: str = ""
    methodisch: str = ""
    anhang: str = ""
    schule: str = ""
    pruefer: str = ""
    deckblatt_datum: str = ""
    checks: Dict[str, bool] = Field(default_factory=dict)


class AsuvOut(AsuvDraft):
    id: int          # = lesson_id (lesson_id ist Primärschlüssel von asuv_drafts, kein eigenes id)
    lesson_id: int
    saved: bool
    bibox_empty: bool
    updated_at: Optional[str] = None   # None solange saved=False (noch keine Zeile gespeichert)


class AsuvSyncCreate(AsuvDraft):
    lesson_id: int


class AsuvSyncUpdate(AsuvDraft):
    pass


# U29: Übersicht aller gespeicherten ASUV-Entwürfe (für die Materialbibliothek).
class AsuvListItem(Base):
    lesson_id: int
    lesson_title: str
    subject: str
    grade: Optional[int] = None
    class_id: Optional[int] = None
    class_name: Optional[str] = None
    updated_at: str


# ---------- KI-Anfragen (Meilenstein 7) ----------
class LessonSuggestIn(Base):
    ideas: str = ""
    subject: Optional[str] = None
    grade: Optional[int] = None
    title: Optional[str] = None
    lesson_type: Optional[str] = None
    class_id: Optional[int] = None
    date: Optional[str] = None
    duration_minutes: Optional[int] = None


class TafelbildSuggestIn(Base):
    eingabe: str = ""
    subject: Optional[str] = None
    grade: Optional[int] = None
    title: Optional[str] = None


class StoffplanIn(Base):
    school_year_id: int
    class_id: int


class AsuvSuggestIn(Base):
    pass


# ---------- Reflexionen (Meilenstein 3) ----------
class ReflectionCreate(Base):
    lesson_id: int
    meyer_ist: Optional[List[str]] = None
    text: Optional[str] = None


class ReflectionOut(Base):
    id: int
    lesson_id: int
    lesson_title: Optional[str] = None
    meyer_ist: Optional[List[str]] = None
    ampel_summary: Optional[str] = None
    text: Optional[str] = None
    created_at: str
    updated_at: str


class OpenReflectionOut(Base):
    lesson_id: int
    title: str
    subject: str
    grade: Optional[int] = None


class SkipReflectionIn(Base):
    lesson_id: int


# ---------- To-dos (Meilenstein 3) ----------
class TodoCreate(Base):
    text: str
    source: str = "manuell"


class TodoUpdate(Base):
    text: Optional[str] = None
    done: Optional[bool] = None


class TodoOut(Base):
    id: int
    text: str
    source: str
    done: bool
    archived_at: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- Notizen (U17) ----------
class NoteCreate(Base):
    scope: str                          # 'allgemein' | 'klasse'
    class_id: Optional[int] = None      # Pflicht bei scope 'klasse'
    body_md: str = ""


class NoteUpdate(Base):
    body_md: str


class NoteOut(Base):
    id: int
    scope: str
    class_id: Optional[int] = None
    school_year_id: Optional[int] = None
    body_md: str
    archived_at: Optional[str] = None
    created_at: str
    updated_at: str


# ---------- Ferien/Feiertage & Jahresplanung (Meilenstein 4) ----------
class SchoolDateOut(Base):
    id: int
    kind: str            # "feiertag" | "ferien"
    name: str
    start_date: str
    end_date: str
    source: Optional[str] = None


class PlanningRequest(Base):
    school_year_id: int
    class_id: int


class PlanningBlock(Base):
    lernbereich_id: Optional[int] = None
    code: Optional[str] = None
    title: Optional[str] = None
    ustd: int
    weeks: int
    start_date: str
    end_date: str
    conflict_with_fixed: bool


class PlanningResult(Base):
    teaching_weeks: int
    planned: int
    unplaced: int
    blocks: List[PlanningBlock]


# ---------- Jahresplan-Notizen (Meilenstein 11) ----------
class PlanNoteIn(Base):
    class_id: int
    school_year_id: int
    text: str = ""


class PlanNoteOut(Base):
    id: Optional[int] = None  # None = für diese Klasse/dieses Schuljahr existiert noch keine Zeile
    class_id: int
    school_year_id: int
    text: str = ""
    updated_at: Optional[str] = None


# Offline-Sync (Rollout): eigene Create/Update-Schemas, da plan_notes über den natürlichen
# Schlüssel (class_id, school_year_id) statt eine für den Client sichtbare id adressiert wird —
# der generische Sync-Push braucht aber eine echte id (siehe planning.py _apply_create/_apply_update).
class PlanNoteSyncCreate(Base):
    class_id: int
    school_year_id: int
    text: str = ""


class PlanNoteSyncUpdate(Base):
    text: str = ""


# ---------- Lernziele (Meilenstein 11) — ans Dateiende (Konfliktvermeidung) ----------
class LernzielIn(Base):
    kind: str                                   # 'grob' | 'fein'
    text: str
    bloom_stufe: Optional[str] = None           # Erinnern|Verstehen|Anwenden|Analysieren|Bewerten|Erschaffen
    phase_sort_order: Optional[int] = None      # Zuordnung zu einer Phase (0..3) oder None
    sort_order: int = 0

    @field_validator("kind")
    @classmethod
    def _kind_grob_or_fein(cls, v: str) -> str:
        if v not in ("grob", "fein"):
            raise ValueError("Lernziel-Art muss 'grob' oder 'fein' sein.")
        return v


class LernzielOut(LernzielIn):
    id: int


# ---------- Schüler (U14) — Namensliste je Klasse ----------
class StudentCreate(Base):
    name: str


class StudentBulkCreate(Base):
    names: List[str]


class StudentUpdate(Base):
    name: Optional[str] = None
    sort_order: Optional[int] = None


class StudentOut(Base):
    id: int
    class_id: int
    name: str
    sort_order: int
    created_at: str
    updated_at: str


# Offline-Sync (Rollout): eigenes Create-Schema mit class_id im Body — der REST-Endpunkt
# nimmt die Klasse über den URL-Pfad (/classes/{cid}/students), der generische Sync-Push
# kennt aber nur ein payload-Objekt pro Mutation (siehe planning.py PlanNoteSyncCreate
# für dasselbe Muster).
class StudentSyncCreate(Base):
    class_id: int
    name: str


# ---------- Darstellung / Appearance (Meilenstein 12, U9) — ans Dateiende (Konfliktvermeidung) ----------
_THEMES = {"fruehling", "sommer", "herbst", "winter"}
_FONTS = {"verspielt", "standard"}


class AppearanceIn(Base):
    theme: str
    dark_mode: bool = False
    font: str = "verspielt"

    @field_validator("theme")
    @classmethod
    def _valid_theme(cls, v: str) -> str:
        if v not in _THEMES:
            raise ValueError("Ungültige Jahreszeit (fruehling|sommer|herbst|winter).")
        return v

    @field_validator("font")
    @classmethod
    def _valid_font(cls, v: str) -> str:
        if v not in _FONTS:
            raise ValueError("Ungültige Schriftart (verspielt|standard).")
        return v


# ---------- Stoffplan-Persistenz (U12) — ans Dateiende (Konfliktvermeidung) ----------
_STOFF_STATUS = {"entwurf", "aktiv"}


class StoffPlanBlockIn(Base):
    lb_code: Optional[str] = None
    title: Optional[str] = None
    ustd: Optional[int] = None
    start_date: Optional[str] = None            # ISO oder None
    end_date: Optional[str] = None              # ISO oder None
    sort_order: int = 0
    conflict_note: Optional[str] = None


class StoffPlanBlockOut(StoffPlanBlockIn):
    id: int
    weeks: Optional[int] = None          # berechnet (Ferien abgezogen), nicht gespeichert


class StoffPlanCreate(Base):
    class_id: int
    school_year_id: Optional[int] = None
    title: str
    status: str = "entwurf"
    blocks: List[StoffPlanBlockIn] = []

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in _STOFF_STATUS:
            raise ValueError("status muss 'entwurf' oder 'aktiv' sein.")
        return v


class StoffPlanUpdate(Base):
    title: Optional[str] = None
    status: Optional[str] = None
    blocks: Optional[List[StoffPlanBlockIn]] = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v):
        if v is not None and v not in _STOFF_STATUS:
            raise ValueError("status muss 'entwurf' oder 'aktiv' sein.")
        return v


class StoffPlanOut(Base):
    id: int
    class_id: int
    school_year_id: Optional[int] = None
    title: str
    status: str
    block_count: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class StoffPlanDetail(StoffPlanOut):
    blocks: List[StoffPlanBlockOut] = []


# ---------- Stoffplan-Wiederverwendung (U16) — Duplizieren/Übernehmen ----------
_STOFF_DUP_MODES = {"kopie", "deterministisch", "ki"}


class StoffPlanDuplicateIn(Base):
    target_class_id: int
    target_school_year_id: Optional[int] = None
    mode: str = "deterministisch"           # kopie | deterministisch | ki

    @field_validator("mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        if v not in _STOFF_DUP_MODES:
            raise ValueError("mode muss 'kopie', 'deterministisch' oder 'ki' sein.")
        return v


# Forward-Refs der Lesson-Modelle auf Lernziel-Modelle auflösen (Definition folgt erst hier).
LessonCreate.model_rebuild()
LessonUpdate.model_rebuild()


# ---------- Sequenzplan — Einzelstunden je Stoffplan-Block ----------
class SequenzStundeCreate(Base):
    block_id: int
    title: str
    grobziel: Optional[str] = None
    notes: Optional[str] = None
    is_lk: bool = False
    is_referat: bool = False
    is_komplexe_arbeit: bool = False
    is_klassenarbeit: bool = False
    weitere_notenart: Optional[str] = None
    sort_order: Optional[int] = None   # None = ans Ende anhängen
    date: Optional[str] = None         # voraussichtliches Datum, ISO; unabhängig von lesson_id


class SequenzStundeUpdate(Base):
    title: Optional[str] = None
    grobziel: Optional[str] = None
    notes: Optional[str] = None
    is_lk: Optional[bool] = None
    is_referat: Optional[bool] = None
    is_komplexe_arbeit: Optional[bool] = None
    is_klassenarbeit: Optional[bool] = None
    weitere_notenart: Optional[str] = None
    date: Optional[str] = None


class SequenzStundeOut(Base):
    id: int
    block_id: int
    sort_order: int
    title: str
    grobziel: Optional[str] = None
    notes: Optional[str] = None
    is_lk: bool
    is_referat: bool
    is_komplexe_arbeit: bool
    is_klassenarbeit: bool
    weitere_notenart: Optional[str] = None
    date: Optional[str] = None
    lesson_id: Optional[int] = None
    moved_to_id: Optional[int] = None   # gesetzt, wenn diese Karte per "Stunde verschieben" auf
                                          # eine neue Zeile (moved_to_id) umgezogen ist
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SequenzStundeReorderIn(Base):
    block_id: int
    ordered_ids: List[int]


class SequenzStundeLinkIn(Base):
    lesson_id: Optional[int] = None   # None = Verknüpfung lösen


class SequenzStundeShiftIn(Base):
    with_calendar: bool = False


class SequenzStundeShiftOut(Base):
    over_budget: bool
    planned_count: int
    richtwert_ustd: Optional[int] = None


_CALENDAR_ENTRY_TYPES = {"exam", "lu"}


class SequenzStundeCalendarEntryIn(Base):
    type: str

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in _CALENDAR_ENTRY_TYPES:
            raise ValueError("type muss 'exam' oder 'lu' sein.")
        return v


class SequenzplanIn(Base):
    block_id: int
    ideas: str = ""
    want_lk: bool = False
    want_referat: bool = False
    want_komplexe_arbeit: bool = False
    want_klassenarbeit: bool = False
LessonOut.model_rebuild()


# ---------- Sitzplan (U18) — ans Dateiende (Konfliktvermeidung mit Parallel-Units) ----------
class SeatIn(Base):
    row: int
    col: int
    student_id: Optional[int] = None
    name: Optional[str] = None


class SeatPlanLayout(Base):
    seats: List[SeatIn] = []


class SeatPlanCreate(Base):
    name: str
    rows: Optional[int] = None
    cols: Optional[int] = None
    layout_json: SeatPlanLayout


class SeatPlanSyncCreate(SeatPlanCreate):
    class_id: int


class SeatPlanUpdate(Base):
    name: Optional[str] = None
    rows: Optional[int] = None
    cols: Optional[int] = None
    layout_json: Optional[SeatPlanLayout] = None


class SeatPlanOut(Base):
    id: int
    class_id: int
    name: str
    rows: Optional[int] = None
    cols: Optional[int] = None
    layout_json: SeatPlanLayout
    created_at: str
    updated_at: str


class SeatPlanAiArrange(Base):
    class_id: Optional[int] = None   # via Body oder Pfad; Pfad hat Vorrang
    rows: int
    cols: int
    description: str


# ---------- Globale Volltextsuche (U25) — ans Dateiende (Konfliktvermeidung) ----------
class SearchFacet(Base):
    key: str
    count: int


class SearchFacets(Base):
    types: List[SearchFacet] = Field(default_factory=list)
    subjects: List[SearchFacet] = Field(default_factory=list)
    grades: List[SearchFacet] = Field(default_factory=list)


class SearchResult(Base):
    type: str                          # lesson|material|note|calendar|class|reflection|todo|asuv|stoffplan|lernbereich
    id: int                            # Ziel-ID fürs Frontend (asuv/reflection = lesson_id)
    title: str
    snippet: str = ""                  # Markierungen [[…]] → Frontend ersetzt durch <mark>
    subject: Optional[str] = None
    grade: Optional[int] = None
    date: Optional[str] = None         # nur calendar/lesson (Sprung zum Tag)
    page_from: Optional[int] = None    # nur material (PDF-Treffer)
    page_to: Optional[int] = None


class SearchResponse(Base):
    query: str
    total: int
    facets: SearchFacets
    results: List[SearchResult] = Field(default_factory=list)


# ---------- Mein Stundenplan (U27) ----------
# Zeit- und Datumsfelder als gemusterte Strings: so sind Vergleiche lexikographisch
# korrekt (feste Breite) und ungültige Werte ergeben schon im Schema 422.
from typing import Literal  # lokal am Dateiende (Konfliktvermeidung mit Parallel-Units)

_TIME_RE = r"^([01]\d|2[0-3]):[0-5]\d$"      # 00:00 … 23:59
_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"            # YYYY-MM-DD


# --- Typen (Unterricht/Aufsicht/…) ---
class TimetableKindCreate(Base):
    name: str
    color: str
    sort_order: int = 0


class TimetableKindUpdate(Base):
    # is_default fehlt bewusst: der Default-Typ ist per PUT NICHT umsetzbar.
    name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None


class TimetableKindOut(Base):
    id: int
    name: str
    color: str
    is_default: bool
    sort_order: int
    created_at: str
    updated_at: str


# --- Klingelraster-Slots ---
class TimetableSlotCreate(Base):
    position: int
    slot_type: Literal["lesson", "break"] = "lesson"
    label: str
    start_time: str = Field(pattern=_TIME_RE)
    end_time: str = Field(pattern=_TIME_RE)


class TimetableSlotUpdate(Base):
    position: Optional[int] = None
    slot_type: Optional[Literal["lesson", "break"]] = None
    label: Optional[str] = None
    start_time: Optional[str] = Field(default=None, pattern=_TIME_RE)
    end_time: Optional[str] = Field(default=None, pattern=_TIME_RE)


class TimetableSlotOut(Base):
    id: int
    position: int
    slot_type: str
    label: str
    start_time: str
    end_time: str
    created_at: str
    updated_at: str


# --- Pläne ---
class TimetablePlanCreate(Base):
    name: str = ""
    valid_from: str = Field(pattern=_DATE_RE)
    copy_from_plan_id: Optional[int] = None     # Einträge dieses Plans in den neuen kopieren


class TimetablePlanUpdate(Base):
    name: Optional[str] = None
    valid_from: Optional[str] = Field(default=None, pattern=_DATE_RE)


class TimetablePlanOut(Base):
    id: int
    name: str
    valid_from: str
    created_at: str
    updated_at: str


# --- Einträge ---
class TimetableEntryCreate(Base):
    plan_id: int
    slot_id: int
    kind_id: int
    class_id: Optional[int] = None
    weekday: int = Field(ge=0, le=4)
    week_type: Literal["both", "A", "B"] = "both"
    span_slots: int = Field(default=1, ge=1, le=12)
    label: Optional[str] = None
    room: Optional[str] = None
    color: Optional[str] = None


class TimetableEntryUpdate(Base):
    plan_id: Optional[int] = None
    slot_id: Optional[int] = None
    kind_id: Optional[int] = None
    class_id: Optional[int] = None
    weekday: Optional[int] = Field(default=None, ge=0, le=4)
    week_type: Optional[Literal["both", "A", "B"]] = None
    span_slots: Optional[int] = Field(default=None, ge=1, le=12)
    label: Optional[str] = None
    room: Optional[str] = None
    color: Optional[str] = None


class TimetableEntryOut(Base):
    id: int
    plan_id: int
    slot_id: int
    kind_id: int
    class_id: Optional[int] = None
    weekday: int
    week_type: str
    span_slots: int
    label: Optional[str] = None
    room: Optional[str] = None
    color: Optional[str] = None
    created_at: str
    updated_at: str


# --- Overrides (U30): einmalige, datumsgebundene Einträge (z. B. Vertretung) ---
class TimetableOverrideCreate(Base):
    date: str
    slot_id: int
    kind_id: int
    class_id: Optional[int] = None
    span_slots: int = Field(default=1, ge=1, le=12)
    label: Optional[str] = None
    room: Optional[str] = None
    color: Optional[str] = None


class TimetableOverrideOut(Base):
    id: int
    date: str
    slot_id: int
    kind_id: int
    class_id: Optional[int] = None
    span_slots: int
    label: Optional[str] = None
    room: Optional[str] = None
    color: Optional[str] = None
    created_at: str
    updated_at: str


# --- Einstellungen (A/B-Wochen-Parität) ---
class TimetableSettingsUpdate(Base):
    week_a_parity: Literal["odd", "even"]


class TimetableSettingsOut(Base):
    week_a_parity: str
    iso_week: int                # ISO-Kalenderwoche HEUTE (serverseitig)
    current_week_type: str       # 'A' | 'B' für HEUTE


# --- Aufgelöste Wochenansicht (A/B serverseitig aufgelöst) ---
class TimetableResolvedItem(Base):
    entry_id: int                # bei source="override": id in timetable_overrides
    slot_id: int
    slot_label: str
    time_range: str              # "07:30–09:10" (en-dash)
    title: str
    subtitle: str
    color: str
    kind_id: int
    kind_name: str
    class_id: Optional[int] = None
    week_type: str
    span_slots: int
    source: str                  # "plan" (wiederkehrend) | "override" (einmalig, z. B. Vertretung)


class TimetableResolvedDay(Base):
    date: str
    weekday: int
    is_tropentag: bool = False   # Tropenplan (verkürzter Unterricht) gilt an diesem Tag
    items: List[TimetableResolvedItem] = Field(default_factory=list)


class TimetableResolved(Base):
    week_start: str
    iso_week: int
    week_type: str               # 'A' | 'B'
    plan_id: int
    plan_name: str
    days: List[TimetableResolvedDay] = Field(default_factory=list)


# --- Tropenplan (U27d): eigenes Klingelraster + markierte Tropentage ---
class TropenSlotCreate(Base):
    position: int
    slot_type: Literal["lesson", "break"] = "lesson"
    label: str
    start_time: str = Field(pattern=_TIME_RE)
    end_time: str = Field(pattern=_TIME_RE)
    covers: int = Field(default=1, ge=1, le=4)


class TropenSlotUpdate(Base):
    position: Optional[int] = None
    slot_type: Optional[Literal["lesson", "break"]] = None
    label: Optional[str] = None
    start_time: Optional[str] = Field(default=None, pattern=_TIME_RE)
    end_time: Optional[str] = Field(default=None, pattern=_TIME_RE)
    covers: Optional[int] = Field(default=None, ge=1, le=4)


class TropenSlotOut(Base):
    id: int
    position: int
    slot_type: str
    label: str
    start_time: str
    end_time: str
    covers: int
    created_at: str
    updated_at: str


class TropentagUpdate(Base):
    active: bool


class TropentagOut(Base):
    date: str
    active: bool


# ---------- Kumulierte Ansicht: Stoffplan-Blöcke inkl. ihrer Sequenzstunden ----------
class StoffPlanBlockCombinedOut(StoffPlanBlockOut):
    stunden: List[SequenzStundeOut] = []


class StoffPlanCombinedOut(StoffPlanOut):
    blocks: List[StoffPlanBlockCombinedOut] = []


# ---------- Offline-Sync (Fundament) ----------
class SyncChangeOut(Base):
    seq: int
    entity_type: str
    entity_id: int
    op: str                          # 'upsert' | 'delete'
    entity: Optional[Dict] = None    # None bei op='delete' (bereits camelCase-serialisiert)


class SyncChangesOut(Base):
    changes: List[SyncChangeOut]
    next_cursor: int
    has_more: bool


class SyncMutationIn(Base):
    client_id: str                   # vom Client vergebene Korrelations-ID (i.d.R. localId)
    entity_type: str
    op: str                          # 'create' | 'update' | 'delete'
    entity_id: Optional[int] = None  # None bei 'create'
    base_updated_at: Optional[str] = None  # Basis für Optimistic-Concurrency bei 'update'/'delete'
    payload: Dict = Field(default_factory=dict)


class SyncPushIn(Base):
    mutations: List[SyncMutationIn]


class SyncMutationResult(Base):
    client_id: str
    status: str                      # 'applied' | 'conflict' | 'error'
    entity_id: Optional[int] = None
    entity: Optional[Dict] = None
    server_entity: Optional[Dict] = None
    detail: Optional[str] = None


class SyncPushOut(Base):
    results: List[SyncMutationResult]


# --- Schulmanager-Online-Abgleich (M1c) ---
class SchulmanagerEventRef(Base):
    title: Optional[str] = None
    room: Optional[str] = None
    uid: Optional[str] = None


class SchulmanagerChangeOut(Base):
    date: str
    start: str
    end: Optional[str] = None
    expected: Optional[SchulmanagerEventRef] = None
    actual: Optional[SchulmanagerEventRef] = None
    # Nur bei Unterricht (Vertretung/Ausfall) gesetzt – Frontend nutzt es, um "Ausarbeiten"
    # direkt in den Unterrichtsplanung-Editor zu leiten (wie die U27-Stundenplan-Ansicht).
    class_id: Optional[int] = None
    # Nur bei aufsicht_geaendert gesetzt – Frontend öffnet damit das bestehende Bearbeiten-Modal.
    entry_id: Optional[int] = None


class SchulmanagerChangesOut(Base):
    vertretung: List[SchulmanagerChangeOut] = Field(default_factory=list)
    ausfall: List[SchulmanagerChangeOut] = Field(default_factory=list)
    aufsicht_neu: List[SchulmanagerChangeOut] = Field(default_factory=list)
    aufsicht_geaendert: List[SchulmanagerChangeOut] = Field(default_factory=list)
