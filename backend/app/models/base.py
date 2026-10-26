"""Shared SQLAlchemy Core metadata; table definitions live in domain modules."""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, MetaData, Table, Text

metadata = MetaData()


def col(name, type_=Text, default=None, nullable=False, fk=None):
    args = [ForeignKey(fk, ondelete="CASCADE")] if fk else []
    return Column(name, type_, *args, nullable=nullable, default=default)


def table(name, *columns, timestamps=True, constraints=()):
    extra = [col("created_at", DateTime(timezone=True), lambda: now())]
    if timestamps:
        extra.append(col("updated_at", DateTime(timezone=True), lambda: now()))
    return Table(name, metadata, Column("id", BigInteger, primary_key=True), *columns, *extra, *constraints)


def now():
    return datetime.now(timezone.utc)
