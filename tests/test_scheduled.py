import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("scheduled", ROOT / "scripts" / "scheduled.py")
scheduled = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduled)

URL = os.environ.get("TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not URL.rsplit("/", 1)[-1].endswith("_test"),
                              reason="TEST_DATABASE_URL (a *_test database) not set")


def test_env_file_does_not_override_real_environment(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comment\nTCG_A=from_file\nTCG_B= spaced \nnot a line\n", encoding="utf-8")
    monkeypatch.setenv("TCG_A", "from_env")
    monkeypatch.delenv("TCG_B", raising=False)
    scheduled.load_env(f)
    assert os.environ["TCG_A"] == "from_env" and os.environ["TCG_B"] == "spaced"


def test_db_params_keep_password_out_of_arguments(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://tcg:s3cret@localhost/tcg")
    assert scheduled.db_params() == {"user": "tcg", "password": "s3cret", "host": "localhost", "port": "5432",
                                     "dbname": "tcg"}
    monkeypatch.setenv("DATABASE_URL", "not a url")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        scheduled.db_params()


def test_freshness_alerts_on_stale_and_never_crawled_stores(monkeypatch):
    sent = []
    monkeypatch.setattr(scheduled, "ensure_postgres", lambda: None)
    monkeypatch.setattr(scheduled, "alert", sent.append)
    monkeypatch.setenv("FRESHNESS_MAX_HOURS", "26")
    monkeypatch.setattr(scheduled, "newest_ok_run_age_hours", lambda: {"trinity": 5.0})
    assert scheduled.job_check_freshness() == 0 and sent == []
    monkeypatch.setattr(scheduled, "newest_ok_run_age_hours", lambda: {"trinity": 30.2, "other": None})
    assert scheduled.job_check_freshness() == 1
    assert "trinity (30 h ago)" in sent[0] and "other (never)" in sent[0]


def test_crawl_job_alerts_when_the_database_cannot_start(monkeypatch):
    sent = []

    def broken():
        raise RuntimeError("pg_ctl start failed")

    monkeypatch.setattr(scheduled, "ensure_postgres", broken)
    monkeypatch.setattr(scheduled, "alert", sent.append)
    assert scheduled.job_crawl(no_crawl=True) == 2 and "could not start" in sent[0]


def test_task_scheduler_xml_is_well_formed_and_catches_up_missed_runs():
    import xml.etree.ElementTree as ET

    spec2 = importlib.util.spec_from_file_location("register_tasks", ROOT / "scripts" / "register_tasks.py")
    reg = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(reg)
    xml = reg.task_xml("crawl", ["07:15", "19:15"], "Crawl & back up", "kiung")
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.fromstring(xml.split("?>", 1)[1])
    starts = [e.text for e in root.findall(".//t:CalendarTrigger/t:StartBoundary", ns)]
    assert starts == ["2026-01-01T07:15:00", "2026-01-01T19:15:00"]
    assert root.find(".//t:StartWhenAvailable", ns).text == "true"
    assert root.find(".//t:LogonType", ns).text == "InteractiveToken"
    assert root.find(".//t:Arguments", ns).text.endswith('scheduled.py" crawl')
    assert root.find(".//t:Command", ns).text.endswith("pythonw.exe")


@needs_db
@pytest.mark.skipif(not (scheduled.PG_BIN / "pg_dump.exe").exists(), reason="local conda-forge pg_dump not installed")
def test_backup_is_written_verified_and_rotated(tmp_path, monkeypatch):
    import psycopg

    from migrate import migrate

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        migrate(conn)
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("BACKUP_KEEP", "2")
    for i in range(3):
        (tmp_path / f"tcg-2026010{i}-000000.dump").write_bytes(b"old")
    path = scheduled.backup()
    assert path.exists() and path.stat().st_size > 1000
    assert sorted(p.name for p in tmp_path.glob("tcg-*.dump")) == ["tcg-20260102-000000.dump", path.name]
