from dataclasses import dataclass, field
import os
from pathlib import Path

from .errors import ConfigurationError


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: Path
    api_key: str = field(repr=False)


def load_settings(env_file=None, db_path=None):
    path = Path(env_file) if env_file else PACKAGE_ROOT / ".env"
    values = {}
    if path.is_file():
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                raise ConfigurationError(f"Invalid configuration line {number}; use NAME=value.")
            name, value = line.split("=", 1)
            name, value = name.strip(), value.strip()
            if name not in {"FIRMS_MAP_KEY", "FIRMS_DB_PATH"}:
                continue
            if name in values:
                raise ConfigurationError(f"Duplicate configuration variable {name}.")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ConfigurationError(f"Unclosed quote on configuration line {number}.")
                value = value[1:-1]
            else:
                value = value.split(" #", 1)[0].rstrip()
            values[name] = value

    key = os.environ.get("FIRMS_MAP_KEY", values.get("FIRMS_MAP_KEY", "")).strip()
    configured_db = os.environ.get("FIRMS_DB_PATH", values.get("FIRMS_DB_PATH", ""))
    if db_path is not None:
        database = Path(db_path).expanduser().resolve()
    elif configured_db:
        database = Path(configured_db).expanduser()
        if not database.is_absolute():
            database = path.resolve().parent / database
    else:
        database = PACKAGE_ROOT / "var" / "fires.sqlite3"
    return Settings(database.resolve(), key)
