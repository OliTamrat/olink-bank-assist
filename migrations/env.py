from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from bankassist import models  # noqa: F401  (register mappings)
from bankassist.config import get_settings
from bankassist.db import Base

target_metadata = Base.metadata

# Apply the [loggers] config from alembic.ini. Without this call the whole
# section is dead configuration, alembic's INFO records fall to a root logger
# defaulting to WARNING, and `alembic upgrade head` runs completely silently —
# applying six migrations from an empty database prints nothing at all.
#
# That matters here because the deploy pipeline migrates the production
# database on every push. A schema change that leaves no trace in the deploy
# log is one you cannot confirm afterwards without opening a psql session.
if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
