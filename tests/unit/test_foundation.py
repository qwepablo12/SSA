"""Foundation tests. No database, no event loop — these must stay fast.

They assert the properties Step 0 exists to guarantee, because each one is
invisible until a migration or a production incident reveals it.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Date, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP

from ssa.domain.common.errors import ConflictError, SSAError, ValidationError
from ssa.domain.common.protocols import Clock
from ssa.infrastructure.clock import SystemClock
from ssa.infrastructure.database.base import NAMING_CONVENTION, Base
from ssa.shared.settings import DatabaseSettings, Environment, Settings


class TestNamingConvention:
    def test_metadata_carries_the_convention(self) -> None:
        """Migration 001 must not be generated without this in place."""
        assert Base.metadata.naming_convention == NAMING_CONVENTION

    @pytest.mark.parametrize("key", ["ix", "uq", "ck", "fk", "pk"])
    def test_every_constraint_kind_is_named(self, key: str) -> None:
        assert key in NAMING_CONVENTION


class TestTypeMapping:
    def test_datetime_is_always_timezone_aware(self) -> None:
        """The rule that makes TIMESTAMPTZ structural rather than a habit."""
        mapped = Base.type_annotation_map[dt.datetime]
        assert isinstance(mapped, TIMESTAMP)
        assert mapped.timezone is True

    def test_str_maps_to_text_not_varchar(self) -> None:
        assert Base.type_annotation_map[str] is Text

    def test_date_maps_to_date(self) -> None:
        assert Base.type_annotation_map[dt.date] is Date


class TestSystemClock:
    def test_satisfies_the_clock_port(self) -> None:
        assert isinstance(SystemClock(), Clock)

    def test_now_is_aware_and_utc(self) -> None:
        now = SystemClock().now()
        assert now.tzinfo is not None
        assert now.utcoffset() == dt.timedelta(0)

    def test_today_in_respects_the_users_timezone(self) -> None:
        """A user in Auckland and one in Los Angeles are rarely on the same date."""
        clock = SystemClock()
        auckland = clock.today_in(ZoneInfo("Pacific/Auckland"))
        los_angeles = clock.today_in(ZoneInfo("America/Los_Angeles"))
        assert (auckland - los_angeles).days in (0, 1)


class TestErrors:
    def test_all_errors_share_one_base(self) -> None:
        assert issubclass(ValidationError, SSAError)
        assert issubclass(ConflictError, SSAError)

    def test_details_are_structured_not_interpolated(self) -> None:
        err = ConflictError("already running", constraint="uq_study_sessions_one_active")
        assert err.message == "already running"
        assert err.details == {"constraint": "uq_study_sessions_one_active"}


class TestSettings:
    def test_url_escapes_special_characters_in_passwords(self) -> None:
        """Hand-built DSNs break on exactly this and the failure looks like a network error."""
        db = DatabaseSettings(user="ssa", password="p@ss:w/ord", host="db", port=5432, name="ssa")
        assert db.url.password == "p@ss:w/ord"
        assert db.url.drivername == "postgresql+asyncpg"

    def test_str_never_leaks_the_password(self) -> None:
        db = DatabaseSettings(password="hunter2")
        assert "hunter2" not in str(db)

    def test_environment_flag(self) -> None:
        assert Environment.PRODUCTION.is_production
        assert not Environment.LOCAL.is_production

    def test_unknown_prefixed_variable_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A typo in an env var should fail at boot, not default silently."""
        monkeypatch.setenv("SSA_NOT_A_REAL_SETTING", "1")
        with pytest.raises(Exception, match="extra_forbidden|Extra inputs"):
            Settings(_env_file=None)  # type: ignore[call-arg]
