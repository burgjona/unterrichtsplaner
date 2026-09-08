"""Cache-Button: leert den HTTP-Cache, aber niemals den lokalen Speicher.

Hintergrund: "storage" im Clear-Site-Data-Header loescht auch IndexedDB - dort liegt die
_mutationQueue der Offline-Sync-Engine. Ein Klick nach einer Offline-Phase hätte damit
noch nicht gesendete Änderungen vernichtet. Regressionstest, damit "storage" nicht
versehentlich zurueckkommt.
"""


def test_clear_cache_requires_login(client):
    assert client.post("/api/settings/clear-cache").status_code == 401


def test_clear_cache_sets_only_cache_directive(client, auth):
    r = client.post("/api/settings/clear-cache")
    assert r.status_code == 204
    assert r.headers["Clear-Site-Data"] == '"cache"'


def test_clear_cache_never_wipes_local_storage(client, auth):
    """Kern der Zusage: kein "storage" - sonst wäre die Offline-Warteschlange weg."""
    directive = client.post("/api/settings/clear-cache").headers["Clear-Site-Data"]
    assert "storage" not in directive
    assert "cookies" not in directive        # wuerde zusätzlich die Anmeldung wegwerfen
