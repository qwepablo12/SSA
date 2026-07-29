"""Declarative base, constraint naming convention, and type mapping.

This is the most consequential file in the database layer, for two reasons that
are both easy to underestimate.

**The naming convention must exist before migration 001.** Without it,
PostgreSQL assigns constraint names, Alembic autogenerate invents different ones
per environment, and a later ``DROP CONSTRAINT`` fails on one machine and
succeeds on another. Retrofitting means hand-editing every migration in every
environment (ADR-003, 06 §1.2).

**The type map makes the timezone rule structural.** ``Mapped[datetime]``
resolves to ``TIMESTAMP(timezone=True)`` — so a naive ``TIMESTAMP`` column
cannot be created by accident. It has to be asked for explicitly, and there is
nowhere in this schema that should.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, ClassVar, Final

from sqlalchemy import BigInteger, Date, MetaData, Numeric, Text, Uuid
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import DeclarativeBase

__all__ = ["NAMING_CONVENTION", "Base", "metadata"]


NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Base for every ORM model.

    Note that these are *persistence* models, not domain entities. The domain
    keeps its own classes and the two are joined by explicit mappers
    (ADR-004) — which is what allows the domain to be free of SQLAlchemy and
    the layering contract to be enforceable rather than aspirational.
    """

    metadata = metadata

    # How Python annotations become PostgreSQL types.
    #
    # ``str`` maps to ``TEXT`` rather than ``VARCHAR(n)``: PostgreSQL stores
    # both identically, a length limit in the type means a migration to change
    # it, and length rules are expressed as CHECK constraints in this schema
    # where they can carry a name and be altered in one statement.
    #
    # ``ClassVar`` (rather than a ``Mapped``-free annotation) tells the
    # declarative class scanner this is configuration, not a column definition.
    type_annotation_map: ClassVar[dict[type, Any]] = {
        dt.datetime: TIMESTAMP(timezone=True),
        dt.date: Date,
        str: Text,
        int: BigInteger,
        uuid.UUID: Uuid(as_uuid=True),
        Decimal: Numeric,
    }

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


# ``int`` maps to BIGINT above because it cannot mean two things at once.
# Columns that should be SMALLINT — scores, day counts, weekdays — say so
# explicitly through the aliases in ``types.py``.
