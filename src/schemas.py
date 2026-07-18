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


class SettingsOut(Base):
    api_key_status: str            # "aktiv" | "kein Key"
    api_key_last4: Optional[str] = None
    api_key_set_at: Optional[str] = None
    secret_configured: bool        # ob APP_SECRET_KEY serverseitig gesetzt ist
    theme: str = "fruehling"       # fruehling | sommer | herbst | winter
    dark_mode: bool = False
    font: str = "verspielt"        # verspielt | standard


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
    phases: Optional[List[PhaseIn]] = None
    lernziele: Optional[List["LernzielIn"]] = None

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
    phases: List[PhaseOut] = Field(default_factory=list)
    lernziele: List["LernzielOut"] = Field(default_factory=list)
    created_at: str
    updated_at: str


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
    auto_generated: bool = False
    created_at: str


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
    lesson_id: int
    saved: bool
    bibox_empty: bool


# ---------- KI-Anfragen (Meilenstein 7) ----------
class LessonSuggestIn(Base):
    ideas: str = ""
    subject: Optional[str] = None
    grade: Optional[int] = None
    title: Optional[str] = None
    lesson_type: Optional[str] = None
    class_id: Optional[int] = None
    date: Optional[str] = None


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
    class_id: int
    school_year_id: int
    text: str = ""
    updated_at: Optional[str] = None


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
