"""Application state dataclass attached to FastAPI app.state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from py_experimenter_db.config import CredentialsConfig, ExperimenterConfig
from py_experimenter_db.dashboard.project_registry import ProjectRegistry
from py_experimenter_db.dashboard.settings import DashboardSettings
from py_experimenter_db.db.connection import DbBackend
from py_experimenter_db.db.schema import SchemaInfo
from py_experimenter_db.history.store import QueryHistoryStore


@dataclass
class AppState:
    project_registry: ProjectRegistry
    # These are None until a project is activated (either via CLI args or the Projects UI)
    db: DbBackend | None = None
    schema: SchemaInfo | None = None
    experimenter_config: ExperimenterConfig | None = None
    creds: CredentialsConfig | None = None
    history_store: QueryHistoryStore | None = None
    history_db_path: Path | None = None
    settings: DashboardSettings = field(default_factory=DashboardSettings)
    config_path: str = ""
    db_config_path: str = ""

    @property
    def is_active(self) -> bool:
        """True when a project is connected and the database backend is available."""
        return self.db is not None and self.schema is not None
