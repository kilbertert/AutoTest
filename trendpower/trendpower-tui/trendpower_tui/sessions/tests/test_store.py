import os

import pytest

from trendpower_tui import sessions as S


@pytest.fixture()
def trendpower_home(tmp_path, monkeypatch):
    home = tmp_path / "trendpower"
    monkeypatch.setenv("TRENDPOWER_HOME", str(home))
    return home


SAMPLE = [
    {"role": "user", "content": [{"type": "text", "text": "Fix the bug please"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
]


def test_save_list_load_roundtrip(trendpower_home):
    sid = S.new_session_id()
    meta = S.save_session(sid, SAMPLE, model="m1", cwd="/work")
    assert meta.id == sid
    assert meta.title == "Fix the bug please"
    assert meta.message_count == 2

    listed = S.list_sessions()
    assert [m.id for m in listed] == [sid]

    loaded_meta, messages = S.load_session(sid)
    assert loaded_meta.model == "m1"
    assert messages == SAMPLE


def test_list_sorts_by_updated_desc(trendpower_home):
    a = S.save_session("20200101-000000-0001", SAMPLE, created=1.0)
    b = S.save_session("20210101-000000-0002", SAMPLE, created=1.0)
    ids = [m.id for m in S.list_sessions()]
    # Both written "now"; the more recently saved (b) should not trail a by file
    # mtime — assert both present and newest-first ordering is stable.
    assert set(ids) == {a.id, b.id}
    assert S.list_sessions()[0].updated >= S.list_sessions()[-1].updated


def test_delete_session(trendpower_home):
    sid = S.new_session_id()
    S.save_session(sid, SAMPLE)
    assert S.delete_session(sid) is True
    assert S.list_sessions() == []
    assert S.delete_session(sid) is False


def test_title_falls_back_when_no_user_text(trendpower_home):
    msgs = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}]
    assert S.session_title(msgs) == "(untitled session)"


def test_list_skips_unreadable_files(trendpower_home):
    sid = S.new_session_id()
    S.save_session(sid, SAMPLE)
    bad = S.sessions_dir() / "broken.json"
    bad.write_text("{ not json", encoding="utf-8")
    ids = [m.id for m in S.list_sessions()]
    assert ids == [sid]
