from dataclasses import dataclass
import os
from pathlib import Path


IDENTIFIER_PATTERN = r"[0-9a-f]{32}"
SQLITE_INTEGER_MAX = 2**63 - 1
MAX_CLAIM_TTL_SECONDS = 31_536_000


@dataclass(frozen=True)
class Config:
    db_path: Path
    is_root: Path = Path("runtime/data/is")
    oos_root: Path = Path("/data/oos")

    @classmethod
    def from_env(cls):
        return cls(Path(os.environ.get("SHARPESHOOTER_DB", "runtime/state/sharpeshooter.sqlite3")),
                   Path(os.environ.get("SHARPESHOOTER_IS_ROOT", "runtime/data/is")),
                   Path(os.environ.get("SHARPESHOOTER_OOS_ROOT", "/data/oos")))
