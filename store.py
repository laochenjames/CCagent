"""SQLite storage for sessions and evaluations."""

import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "agent2.db")


def utcnow_iso():
    """Return current UTC time in ISO 8601 format with microseconds and Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def generate_session_id():
    """Generate a session ID like s_YYYYMMDDHHMMSS_<token>."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = secrets.token_urlsafe(12)
    return f"s_{ts}_{rand}"


def generate_eval_id():
    """Generate an evaluation ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = secrets.token_hex(3)
    return f"e_{ts}_{rand}"


def get_db(db_path=None):
    """Open a SQLite connection with row_factory."""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(db_path=None):
    """Initialize database tables and migrate missing columns."""
    conn = get_db(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                fields_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                analysis_json TEXT,
                analysis_stale INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_eval_session_ver
                ON evaluations(session_id, version);
            """
        )
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(evaluations)").fetchall()}
        if "analysis_json" not in cols:
            conn.execute("ALTER TABLE evaluations ADD COLUMN analysis_json TEXT")
        if "analysis_stale" not in cols:
            conn.execute("ALTER TABLE evaluations ADD COLUMN analysis_stale INTEGER DEFAULT 0")
        s_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "owner_hash" not in s_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN owner_hash TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated ON sessions(owner_hash, updated_at)"
        )
        conn.commit()
    finally:
        conn.close()


def create_session(raw_text, title, fields_state, result_obj, db_path=None, owner_hash=None):
    """Create a new session and its version 1 evaluation."""
    sid = generate_session_id()
    eid = generate_eval_id()
    now = utcnow_iso()
    clean_title = (title or "").strip() or (raw_text.strip()[:20] if raw_text else "未命名评估")
    if len(clean_title) > 40:
        clean_title = clean_title[:40]

    conn = get_db(db_path)
    try:
        conn.execute(
            "INSERT INTO sessions (id, title, raw_text, created_at, updated_at, status, owner_hash) VALUES (?, ?, ?, ?, ?, 'active', ?)",
            (sid, clean_title, raw_text, now, now, owner_hash),
        )
        conn.execute(
            "INSERT INTO evaluations (id, session_id, version, fields_json, result_json, analysis_json, analysis_stale, created_at) VALUES (?, ?, 1, ?, ?, NULL, 0, ?)",
            (eid, sid, json.dumps(fields_state, ensure_ascii=False), json.dumps(result_obj, ensure_ascii=False), now),
        )
        conn.commit()
        return sid
    finally:
        conn.close()


def add_evaluation(session_id, version, fields_state, result_obj, title=None, raw_text=None, db_path=None):
    """Add a new evaluation version to an existing session."""
    eid = generate_eval_id()
    now = utcnow_iso()
    conn = get_db(db_path)
    try:
        conn.execute(
            "INSERT INTO evaluations (id, session_id, version, fields_json, result_json, analysis_json, analysis_stale, created_at) VALUES (?, ?, ?, ?, ?, NULL, 0, ?)",
            (eid, session_id, version, json.dumps(fields_state, ensure_ascii=False), json.dumps(result_obj, ensure_ascii=False), now),
        )
        if title and raw_text is not None:
            conn.execute("UPDATE sessions SET updated_at = ?, title = ?, raw_text = ? WHERE id = ?", (now, title[:40], raw_text, session_id))
        elif raw_text is not None:
            conn.execute("UPDATE sessions SET updated_at = ?, raw_text = ? WHERE id = ?", (now, raw_text, session_id))
        elif title:
            conn.execute("UPDATE sessions SET updated_at = ?, title = ? WHERE id = ?", (now, title[:40], session_id))
        else:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()
    finally:
        conn.close()


def update_latest_evaluation(session_id, fields_state, result_obj, db_path=None):
    """Update latest evaluation in place (for instant field edits without new version)."""
    now = utcnow_iso()
    conn = get_db(db_path)
    try:
        row = conn.execute(
            "SELECT id, analysis_json FROM evaluations WHERE session_id = ? ORDER BY version DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            return False
        stale = 1 if row["analysis_json"] else 0
        conn.execute(
            "UPDATE evaluations SET fields_json = ?, result_json = ?, analysis_stale = ? WHERE id = ?",
            (json.dumps(fields_state, ensure_ascii=False), json.dumps(result_obj, ensure_ascii=False), stale, row["id"]),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()
        return bool(stale)
    finally:
        conn.close()


def save_analysis(session_id, analysis_obj, db_path=None):
    """Save analysis_json on the latest evaluation and clear analysis_stale."""
    now = utcnow_iso()
    conn = get_db(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM evaluations WHERE session_id = ? ORDER BY version DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE evaluations SET analysis_json = ?, analysis_stale = 0 WHERE id = ?",
            (json.dumps(analysis_obj, ensure_ascii=False), row["id"]),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()
        return True
    finally:
        conn.close()


def list_sessions(limit=50, db_path=None, owner_hash=None, hosted=False):
    """List recent sessions with latest label and confidence."""
    conn = get_db(db_path)
    try:
        if hosted:
            if not owner_hash:
                return []
            rows = conn.execute(
                """
                SELECT s.id, s.title, s.updated_at, e.version, e.result_json
                FROM sessions s
                LEFT JOIN evaluations e ON e.session_id = s.id
                    AND e.version = (SELECT MAX(e2.version) FROM evaluations e2 WHERE e2.session_id = s.id)
                WHERE s.owner_hash = ?
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (owner_hash, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT s.id, s.title, s.updated_at, e.version, e.result_json
                FROM sessions s
                LEFT JOIN evaluations e ON e.session_id = s.id
                    AND e.version = (SELECT MAX(e2.version) FROM evaluations e2 WHERE e2.session_id = s.id)
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for r in rows:
            label = "还看不出来"
            conf_pct = 0
            red_line = False
            if r["result_json"]:
                try:
                    res = json.loads(r["result_json"])
                    if "score" in res:
                        sc = res["score"]
                        label = sc.get("label", label)
                        conf_pct = sc.get("confidence_pct", 0)
                        if "red_line" in sc:
                            red_line = bool(sc["red_line"])
                        else:
                            red_line = sc.get("action") == "不建议投入"
                    else:
                        label = res.get("tier", {}).get("value", label)
                        conf_pct = round(res.get("completeness", {}).get("value", 0.0) * 100)
                except Exception:
                    pass
            items.append({
                "id": r["id"],
                "title": r["title"],
                "updated_at": r["updated_at"],
                "version": r["version"] or 1,
                "label": label,
                "confidence_pct": conf_pct,
                "red_line": red_line,
            })
        return items
    finally:
        conn.close()


def get_session(session_id, version=None, db_path=None, owner_hash=None, hosted=False):
    """Get session metadata and the requested (or latest) evaluation."""
    conn = get_db(db_path)
    try:
        s_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not s_row:
            return None
        if hosted and (not owner_hash or s_row["owner_hash"] != owner_hash):
            return None
        if version is not None:
            e_row = conn.execute(
                "SELECT * FROM evaluations WHERE session_id = ? AND version = ?",
                (session_id, int(version)),
            ).fetchone()
        else:
            e_row = conn.execute(
                "SELECT * FROM evaluations WHERE session_id = ? ORDER BY version DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        if not e_row:
            return None
        analysis = None
        if "analysis_json" in e_row.keys() and e_row["analysis_json"]:
            try:
                analysis = json.loads(e_row["analysis_json"])
            except Exception:
                analysis = None
        stale = bool(e_row["analysis_stale"]) if "analysis_stale" in e_row.keys() else False
        return {
            "session": dict(s_row),
            "version": e_row["version"],
            "fields": json.loads(e_row["fields_json"]),
            "result": json.loads(e_row["result_json"]),
            "analysis": analysis,
            "analysis_stale": stale,
        }
    finally:
        conn.close()


def delete_session(session_id, db_path=None, owner_hash=None, hosted=False):
    """Hard delete a session and all its evaluations."""
    conn = get_db(db_path)
    try:
        if hosted:
            if not owner_hash:
                return False
            row = conn.execute("SELECT owner_hash FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row or row["owner_hash"] != owner_hash:
                return False
        conn.execute("DELETE FROM evaluations WHERE session_id = ?", (session_id,))
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def cleanup_expired_sessions(retention_days=30, db_path=None, now=None):
    """Delete sessions whose updated_at is older than retention_days."""
    from datetime import timedelta
    dt = now if now is not None else datetime.now(timezone.utc)
    cutoff = (dt - timedelta(days=int(retention_days))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn = get_db(db_path)
    try:
        conn.execute(
            "DELETE FROM evaluations WHERE session_id IN (SELECT id FROM sessions WHERE updated_at < ?)",
            (cutoff,),
        )
        cur = conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
