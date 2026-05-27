from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path("~/.vntrader/backups/").expanduser()
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _backup_stem(db_path: Path) -> str:
    return db_path.stem


def backup_agent_db(db_path: Path, keep: int = 3) -> Path | None:
    """Create an atomic, consistent backup of a SQLite database file.

    Uses SQLite's native ``connection.backup()`` API to produce a safe copy
    that can be used even while the source database is being written to.

    Parameters
    ----------
    db_path : Path
        Path to the source SQLite database file.
    keep : int
        Maximum number of backup files to retain (default 3).
        Oldest backups are purged first.

    Returns
    -------
    Path | None
        Path to the newly created backup file, or ``None`` if the source
        database file does not exist.
    """
    if not db_path.exists():
        return None

    stem = _backup_stem(db_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"agent_news_{stem}_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_filename

    backup_path.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(backup_path))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    _cleanup_old_backups(db_path, keep)
    return backup_path


def _cleanup_old_backups(db_path: Path, keep: int) -> None:
    backups = list_backups(db_path)
    while len(backups) > keep:
        oldest = backups.pop(0)
        oldest.unlink(missing_ok=True)


def list_backups(db_path: Path) -> list[Path]:
    """Return sorted list of existing backup paths for *db_path*.

    Backups are discovered by matching the naming convention produced by
    :func:`backup_agent_db` inside `~/.vntrader/backups/`.
    """
    stem = _backup_stem(db_path)
    pattern = f"agent_news_{stem}_????????_??????.db"
    paths = sorted(BACKUP_DIR.glob(pattern))
    return paths


def restore_latest_backup(db_path: Path) -> bool:
    """Restore the latest backup to *db_path*, overwriting the original.

    Requires user confirmation via a ``input()`` prompt.

    Returns
    -------
    bool
        ``True`` if a backup was restored, ``False`` if no backups exist
        or the user declined.
    """
    backups = list_backups(db_path)
    if not backups:
        return False

    latest = backups[-1]

    response = input(
        f"Restore backup {latest} → {db_path}? This will overwrite the "
        f"current database. [y/N] "
    )
    if response.strip().lower() not in ("y", "yes"):
        return False

    shutil.copy2(str(latest), str(db_path))
    return True
