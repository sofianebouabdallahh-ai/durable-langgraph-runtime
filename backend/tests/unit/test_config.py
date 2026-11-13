import pytest
from pydantic import ValidationError

from agent_runtime.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from whatever the developer's shell exports."""
    for name in ("POSTGRES_PASSWORD", "POSTGRES_HOST", "LEASE_TTL_S", "HEARTBEAT_S"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_spec() -> None:
    s = Settings(postgres_password="pw")  # type: ignore[arg-type]
    assert s.lease_ttl_s == 30
    assert s.heartbeat_s == 10
    assert s.reaper_interval_s == 5
    assert s.max_reclaims == 3
    assert s.run_timeout_s == 1200
    assert s.run_max_steps == 200
    assert s.run_max_children == 6


def test_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-env")
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    s = Settings()  # type: ignore[call-arg]
    assert s.postgres_host == "postgres"
    assert s.postgres_password.get_secret_value() == "from-env"


def test_password_is_required() -> None:
    with pytest.raises(ValidationError, match="postgres_password"):
        Settings()  # type: ignore[call-arg]


def test_password_is_not_leaked_in_repr() -> None:
    s = Settings(postgres_password="hunter2")  # type: ignore[arg-type]
    assert "hunter2" not in repr(s)
    assert "hunter2" not in str(s.model_dump())


def test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_DB"):  # the defaults, not a dev env
        monkeypatch.delenv(name, raising=False)
    s = Settings(postgres_password="pw", postgres_host="db")  # type: ignore[arg-type]
    assert s.database_url() == "postgresql+psycopg://agent:pw@db:5432/agent_runtime"


def test_heartbeat_must_fit_three_times_in_lease() -> None:
    with pytest.raises(ValidationError, match="heartbeat_s"):
        Settings(postgres_password="pw", lease_ttl_s=30, heartbeat_s=11)  # type: ignore[arg-type]


def test_run_max_depth_cannot_exceed_the_budget_roll_up() -> None:
    """H10: usage is charged to the run, its parent and its root (three rows), so a
    tree deeper than 2 would skip an ancestor's budget."""
    with pytest.raises(ValidationError, match="run_max_depth"):
        Settings(postgres_password="pw", run_max_depth=3)  # type: ignore[arg-type]
    assert Settings(postgres_password="pw", run_max_depth=2).run_max_depth == 2  # type: ignore[arg-type]
