"""Migrations use the data-service configuration, never an embedded URL."""

from alembic import context
from sqlalchemy import create_engine, pool

from incidentpilot.services.data.models import Base
from incidentpilot.shared.config import DataSettings

url = DataSettings().database_url.get_secret_value()

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool, connect_args={"connect_timeout": 3})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
