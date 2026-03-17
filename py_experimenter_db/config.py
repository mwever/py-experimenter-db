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


@dataclass
class CredentialsConfig:
    user: str
    password: str
    server: str
    port: int
    database: str  # injected from ExperimenterConfig


def load_config(config_path: str | Path, db_config_path: str | Path) -> tuple[ExperimenterConfig, CredentialsConfig]:
    """Parse both YAML config files and return validated config objects."""
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

    # Parse logtables
    logtables: dict[str, dict[str, str]] = {}
    for lt_name, lt_fields in table_section.get("logtables", {}).items():
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
    exp_cfg = ExperimenterConfig(database=database_name, table=table_cfg)

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
