import json
import sqlite3
from pathlib import Path
from typing import Any, Dict

DEFAULT_DB_PATH = "ergovision_sessions.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_ts REAL NOT NULL,
  end_ts REAL NOT NULL,
  mode TEXT NOT NULL,
  duration_sec REAL NOT NULL,

  posture_good_sec REAL NOT NULL,
  posture_regular_sec REAL NOT NULL,
  posture_bad_sec REAL NOT NULL,
  posture_none_sec REAL NOT NULL,
  posture_alerts_count INTEGER NOT NULL,
  posture_bad_streak_max_sec REAL NOT NULL,
  posture_score_0_100 REAL,

  light_good_sec REAL NOT NULL,
  light_regular_sec REAL NOT NULL,
  light_bad_sec REAL NOT NULL,
  light_none_sec REAL NOT NULL,
  light_alerts_count INTEGER NOT NULL,
  light_bad_streak_max_sec REAL NOT NULL,
  light_score_0_100 REAL,

  drink_events_count INTEGER NOT NULL,
  hydration_reminders_sent_count INTEGER NOT NULL,
  avg_minutes_between_drinks REAL,

  metrics_json TEXT NOT NULL
);
"""

def ensure_db(db_path: str = DEFAULT_DB_PATH) -> str:
    """Ensure the sqlite DB and schema exist. Returns resolved db path."""
    p = Path(db_path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(p))
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute(SCHEMA_SQL)
        con.commit()
    finally:
        con.close()

    return str(p)

def _to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def save_session(session: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> int:
    """
    Save one session dict to DB. Returns inserted row id.
    """
    db_path = ensure_db(db_path)

    # solo guardar métricas extendidas aquí
    metrics_json = _to_json(session.get("metrics", {}))

    cols = [
        "start_ts","end_ts","mode","duration_sec",
        "posture_good_sec","posture_regular_sec","posture_bad_sec","posture_none_sec",
        "posture_alerts_count","posture_bad_streak_max_sec","posture_score_0_100",
        "light_good_sec","light_regular_sec","light_bad_sec","light_none_sec",
        "light_alerts_count","light_bad_streak_max_sec","light_score_0_100",
        "drink_events_count","hydration_reminders_sent_count","avg_minutes_between_drinks",
        "metrics_json",
    ]

    vals = [session.get(c) for c in cols[:-1]] + [metrics_json]

    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            f"INSERT INTO sessions ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
            vals
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()

def fetch_sessions(limit: int = 200, db_path: str = DEFAULT_DB_PATH):
    """Return list of rows as dicts (newest first)."""
    db_path = ensure_db(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT * FROM sessions ORDER BY end_ts DESC LIMIT ?",
            (int(limit),)
        )
        rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["metrics"] = json.loads(d.get("metrics_json") or "{}")
            except Exception:
                d["metrics"] = {}
            out.append(d)
        return out
    finally:
        con.close()
