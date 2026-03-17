"""Application state dataclass attached to FastAPI app.state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiomysql

from py_experimenter_db.config import CredentialsConfig, ExperimenterConfig
from py_experimenter_db.dashboard.project_registry import ProjectRegistry
from py_experimenter_db.dashboard.settings import DashboardSettings
from py_experimenter_db.db.schema import SchemaInfo
from py_experimenter_db.history.store import QueryHistoryStore


@dataclass
class AppState:
    pool: aiomysql.Pool
    schema: SchemaInfo
    experimenter_config: ExperimenterConfig
    creds: CredentialsConfig
    history_store: QueryHistoryStore
    history_db_path: Path
    settings: DashboardSettings
    project_registry: ProjectRegistry
    config_path: str = ""
    db_config_path: str = ""
