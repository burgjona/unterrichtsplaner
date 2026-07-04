from src.lib.storage_path import build_storage_path

# Konvention: {root}/{fach}/{klasse}/{schuljahr}/{datei}


def test_basic_layout():
    p = build_storage_path("2025-2026", "Deutsch", "Klasse-8", "Arbeitsblatt.pdf")
    assert p == "/storage/Deutsch/Klasse-8/2025-2026/Arbeitsblatt.pdf"


def test_umlauts_preserved():
    p = build_storage_path("2025-2026", "Deutsch", "Klasse-8", "Fabeln_Übung_groß.pdf")
    assert p.endswith("/Fabeln_Übung_groß.pdf")


def test_path_traversal_blocked():
    p = build_storage_path("2025", "Deutsch", "..", "../../etc/passwd")
    assert ".." not in p
    assert p == "/storage/Deutsch/-/2025/passwd"


def test_separators_and_dirs_stripped():
    p = build_storage_path("2025", "WTH", "9/b", "sub/dir/datei.docx")
    assert p == "/storage/WTH/9-b/2025/datei.docx"


def test_empty_components_get_fallbacks():
    p = build_storage_path("", "", "", "")
    assert p == "/storage/unbekanntes-fach/unbekannte-klasse/unbekanntes-schuljahr/datei"


def test_custom_root():
    p = build_storage_path("2025", "Deutsch", "Klasse-7", "x.pdf", root="/mnt/nas/storage")
    assert p.startswith("/mnt/nas/storage/Deutsch/Klasse-7/2025/")
