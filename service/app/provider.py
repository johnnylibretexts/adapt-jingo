"""JsonPhoneticsProvider — jingo_engine.PhoneticsProvider backed by per-exercise
JSON records on a bind-mounted read-only directory.

Layout:
  {records_dir}/{language}/{exercise_id}.json   # one phonetics_for() record
  {records_dir}/tag_map/{language}.json          # {language, map: {phone: tag|None}, ...}

Records are built on the Mac (G2P, build-time only) and embedded in content
packs; the import command writes them here. espeak never runs in this service.
"""
import json
import re
from pathlib import Path
from typing import Dict, Optional

# language / exercise_id are attacker-influenceable (come from the request
# body). Restrict to a safe id charset -- this also rejects "." and ".."
# and anything containing "/" or "\" since those characters aren't in the
# allowed set.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_safe_id(value: str) -> bool:
    if not _SAFE_ID_RE.match(value):
        return False
    if value in (".", ".."):
        return False
    return True


class JsonPhoneticsProvider:
    def __init__(self, records_dir: str):
        self.records_dir = Path(records_dir)

    def get(self, language: str, exercise_id: str) -> Optional[dict]:
        if not (_is_safe_id(language) and _is_safe_id(exercise_id)):
            return None
        path = self.records_dir / language / f"{exercise_id}.json"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def tag_map(self, language: str) -> Dict[str, Optional[str]]:
        path = self.records_dir / "tag_map" / f"{language}.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f).get("map", {})