"""Reproduce migration target selection in disposable state, including the original env.

No user database is opened. --baseline loads the tracked Git baseline's Alembic env only;
the identical cached-settings trigger is replayed against current env without that option.
"""

from argparse import ArgumentParser
from hashlib import sha256
from json import dumps
from os import environ
from pathlib import Path
from shutil import copytree
from sqlite3 import connect
from subprocess import run
from tempfile import mkdtemp

from alembic import command
from alembic.config import Config
from xxx_api.config import get_settings


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lab = root / ".local/workflow"
    lab.mkdir(parents=True, exist_ok=True)
    scratch = Path(mkdtemp(prefix="migration-target-", dir=lab))
    migrations = scratch / "migrations"
    copytree(root / "services/api/migrations", migrations)
    if args.baseline:
        original = run(["git", "show", "HEAD:services/api/migrations/env.py"],
                       cwd=root, check=True, capture_output=True).stdout
        (migrations / "env.py").write_bytes(original)
    else:
        original = (migrations / "env.py").read_bytes()
    intended = scratch / "intended.db"
    cached = scratch / "cached.db"
    previous = environ.get("XXX_DATABASE_URL")
    try:
        get_settings.cache_clear()
        environ["XXX_DATABASE_URL"] = f"sqlite+aiosqlite:///{cached}"
        get_settings()
        environ["XXX_DATABASE_URL"] = f"sqlite+aiosqlite:///{intended}"
        config = Config(str(root / "services/api/alembic.ini"))
        config.set_main_option("script_location", str(migrations))
        command.upgrade(config, "head")
        tables = []
        if intended.exists():
            with connect(intended) as connection:
                tables = [row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        report = {"trigger": "Cache another disposable URL, change XXX_DATABASE_URL, upgrade head",
            "environmentSource": "original tracked Git baseline" if args.baseline else "current repaired env",
            "environmentSha256": sha256(original).hexdigest(),
            "intendedDatabaseCreated": intended.exists(), "wrongCachedDatabaseCreated": cached.exists(),
            "intendedTables": tables, "userDatabaseOpened": False}
        path = lab / ("migration-before.json" if args.baseline else "migration-after.json")
        path.write_text(dumps(report, indent=2))
        print(path)
    finally:
        if previous is None:
            environ.pop("XXX_DATABASE_URL", None)
        else:
            environ["XXX_DATABASE_URL"] = previous
        get_settings.cache_clear()


if __name__ == "__main__":
    main()
