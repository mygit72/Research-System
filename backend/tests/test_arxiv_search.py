"""arXiv search: multi-entry parsing, `since` filtering, LOCAL_ONLY refusal."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services import arxiv

MULTI_ENTRY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <published>2024-01-02T00:00:00Z</published>
    <title>Newest Paper</title>
    <summary>About retrieval augmented generation.</summary>
    <author><name>Author Two</name></author>
    <arxiv:doi>10.48550/arXiv.2401.00002</arxiv:doi>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <published>2024-01-01T00:00:00Z</published>
    <title>Older Paper</title>
    <summary>Also about retrieval.</summary>
    <author><name>Author One</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/hep-th/9901001v1</id>
    <published>2023-12-01T00:00:00Z</published>
    <title>Old-style Id Paper</title>
    <summary>A classic.</summary>
    <author><name>Author Three</name></author>
  </entry>
</feed>"""

WITH_ERROR_ENTRY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/api/errors#incorrect_id_format</id>
    <title>Error</title>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00003v1</id>
    <published>2024-01-03T00:00:00Z</published>
    <title>Good Paper</title>
    <summary>Fine.</summary>
  </entry>
</feed>"""


def test_parse_atom_entries_extracts_every_entry_and_its_arxiv_id() -> None:
    result = arxiv.parse_atom_entries(MULTI_ENTRY.encode())
    assert [c.arxiv_id for c in result] == ["2401.00002", "2401.00001", "hep-th/9901001"]
    assert result[0].title == "Newest Paper"
    assert result[0].doi == "10.48550/arXiv.2401.00002"
    assert result[0].authors == [{"name": "Author Two", "affiliation": None}]
    assert result[1].doi is None
    assert result[2].published == "2023-12-01"


def test_parse_atom_entries_skips_error_and_titleless_entries() -> None:
    result = arxiv.parse_atom_entries(WITH_ERROR_ENTRY.encode())
    assert [c.arxiv_id for c in result] == ["2401.00003"]


def test_parse_atom_still_takes_only_the_first_entry() -> None:
    # Regression check for the parse_atom -> _parse_entry refactor: fetch()'s single-entry
    # lookup must behave exactly as before, even when the feed happens to hold more than one.
    meta = arxiv.parse_atom(MULTI_ENTRY.encode())
    assert meta["title"] == "Newest Paper"
    assert meta["year"] == 2024


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=MULTI_ENTRY)

    monkeypatch.setattr(
        arxiv, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return seen


async def test_search_builds_the_expected_query(settings: Settings, serve: list[str]) -> None:
    results = await arxiv.search(settings, "retrieval augmented generation")
    assert [c.arxiv_id for c in results] == ["2401.00002", "2401.00001", "hep-th/9901001"]
    assert len(serve) == 1
    url = serve[0]
    assert url.startswith("https://export.arxiv.org/api/query?")
    assert "search_query=all%3Aretrieval" in url
    assert "sortBy=submittedDate" in url
    assert "sortOrder=descending" in url


async def test_search_filters_by_since(settings: Settings, serve: list[str]) -> None:
    since = datetime(2024, 1, 1)
    results = await arxiv.search(settings, "retrieval", since=since)
    assert [c.arxiv_id for c in results] == ["2401.00002", "2401.00001"]


async def test_search_refuses_under_local_only(
    settings: Settings, serve: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "local_only", True)
    with pytest.raises(AppError, match="turned off"):
        await arxiv.search(settings, "retrieval")
    assert serve == []
