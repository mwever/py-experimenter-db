"""Configuration loading for PyExperimenter config.yml and db_config.yml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class KeyfieldConfig:
    type: str
    values: list[Any] | None = None


@dataclass
class TableConfig:
    name: str
    keyfields: dict[str, KeyfieldConfig]
    resultfields: dict[str, str]  # name -> SQL type string
    logtables: dict[str, dict[str, str]] = field(default_factory=dict)
    result_timestamps: bool = False


@dataclass
class ExperimenterConfig:
    database: str
    table: TableConfig
    provider: str = "mysql"          # "mysql" or "sqlite"
    sqlite_path: str | None = None   # absolute path to .db file (sqlite only)


@dataclass
class CredentialsConfig:
    user: str
    password: str
    server: str
    port: int
    database: str  # injected from ExperimenterConfig


def load_config(
    config_path: str | Path,
    db_config_path: str | Path | None = None,
) -> tuple[ExperimenterConfig, CredentialsConfig | None]:
    """Parse both YAML config files and return validated config objects."""
    config_path = Path(config_path)
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    py_exp = raw["PY_EXPERIMENTER"]
    db_section = py_exp["Database"]
    table_section = db_section["table"]

    # Parse keyfields
    keyfields: dict[str, KeyfieldConfig] = {}
    for name, spec in table_section.get("keyfields", {}).items():
        if isinstance(spec, dict):
            keyfields[name] = KeyfieldConfig(
                type=spec.get("type", "VARCHAR(255)"),
                values=spec.get("values"),
            )
        else:
            keyfields[name] = KeyfieldConfig(type=str(spec))

    # Parse resultfields (can be dict of name: type or list)
    resultfields: dict[str, str] = {}
    raw_rf = table_section.get("resultfields", {})
    if isinstance(raw_rf, dict):
        for name, typ in raw_rf.items():
            resultfields[name] = str(typ) if typ else "TEXT"
    elif isinstance(raw_rf, list):
        for item in raw_rf:
            if isinstance(item, dict):
                resultfields.update({k: str(v) for k, v in item.items()})
            else:
                resultfields[str(item)] = "TEXT"

    # Parse logtables — can live under Database.table or directly under Database
    logtables: dict[str, dict[str, str]] = {}
    raw_lt = table_section.get("logtables") or db_section.get("logtables") or {}
    for lt_name, lt_fields in raw_lt.items():
        if isinstance(lt_fields, dict):
            logtables[lt_name] = {k: str(v) for k, v in lt_fields.items()}
        else:
            logtables[lt_name] = {}

    table_cfg = TableConfig(
        name=table_section["name"],
        keyfields=keyfields,
        resultfields=resultfields,
        logtables=logtables,
        result_timestamps=bool(table_section.get("result_timestamps", False)),
    )

    database_name = db_section.get("database", "")
    provider = db_section.get("provider", "mysql").lower()

    exp_cfg = ExperimenterConfig(database=database_name, table=table_cfg, provider=provider)

    if provider == "sqlite":
        raw_path = db_section.get("database", db_section.get("path", ""))
        resolved_path = (config_path.parent / raw_path).resolve()
        exp_cfg.sqlite_path = str(resolved_path)
        return exp_cfg, None

    # MySQL path — db_config_path required
    if db_config_path is None:
        raise ValueError("db_config_path is required for MySQL provider")

    # Parse db_config
    with open(db_config_path) as f:
        db_raw = yaml.safe_load(f)

    creds = db_raw.get("CREDENTIALS", {})
    db_creds = creds.get("Database", {})
    conn_creds = creds.get("Connection", {}).get("Standard", {})

    creds_cfg = CredentialsConfig(
        user=db_creds.get("user", "root"),
        password=db_creds.get("password", "") or "",
        server=conn_creds.get("server", "127.0.0.1"),
        port=int(conn_creds.get("port", 3306)),
        database=database_name,
    )

    return exp_cfg, creds_cfg
