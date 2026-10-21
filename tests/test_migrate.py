import pytest

from migrate import MIGRATIONS_DIR, migration_files


def test_repo_migrations_are_contiguous_and_start_with_initial_schema():
    files = migration_files()
    assert files[0][0] == 1 and files[0][1].name == "0001_initial.sql"


def test_gap_in_versions_is_rejected(tmp_path):
    (tmp_path / "0001_a.sql").write_text("")
    (tmp_path / "0003_c.sql").write_text("")
    with pytest.raises(ValueError, match="no gaps"):
        migration_files(tmp_path)


def test_bad_name_is_rejected(tmp_path):
    (tmp_path / "1_init.sql").write_text("")
    with pytest.raises(ValueError, match="bad migration file name"):
        migration_files(tmp_path)


def test_initial_migration_defines_core_tables():
    sql = (MIGRATIONS_DIR / "0001_initial.sql").read_text(encoding="utf-8")
    for table in ("stores", "cards", "listings", "variants", "price_history", "scrape_runs"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
