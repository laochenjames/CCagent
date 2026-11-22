import datetime
import sqlite3

import store

SGT = datetime.timezone(datetime.timedelta(hours=8))


def sgt_today(now=None):
    """Return YYYY-MM-DD in Singapore Time (UTC+8)."""
    dt = now if now is not None else datetime.datetime.now(SGT)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(SGT).strftime("%Y-%m-%d")


def next_sgt_midnight_iso(now=None):
    """Return ISO-8601 string for next 00:00 SGT."""
    dt = now if now is not None else datetime.datetime.now(SGT)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    sgt_dt = dt.astimezone(SGT)
    nxt = (sgt_dt + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.isoformat()


def init_usage_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage (
            day TEXT NOT NULL,
            subject TEXT NOT NULL,
            n INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (day, subject)
        )
        """
    )


def _get_count(conn, day, subject):
    row = conn.execute("SELECT n FROM usage WHERE day = ? AND subject = ?", (day, subject)).fetchone()
    return int(row["n"]) if row else 0


def reserve(owner_hash, ip_hash, db_path=None, limits=None, now=None):
    """Atomically check owner/ip/global limits and increment by 1.

    Returns (ok, exhausted_kind, status_dict).
    exhausted_kind is None when ok=True, else one of 'owner', 'ip', 'global'.
    """
    lim = limits or {}
    lim_owner = int(lim.get("owner", 10))
    lim_ip = int(lim.get("ip", 30))
    lim_global = int(lim.get("global", 300))

    day = sgt_today(now)
    resets_at = next_sgt_midnight_iso(now)
    subj_owner = f"o:{owner_hash}"
    subj_ip = f"i:{ip_hash}"
    subj_global = "g:all"

    conn = store.get_db(db_path)
    try:
        init_usage_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        c_owner = _get_count(conn, day, subj_owner)
        c_ip = _get_count(conn, day, subj_ip)
        c_global = _get_count(conn, day, subj_global)

        exhausted = None
        if c_owner >= lim_owner:
            exhausted = "owner"
        elif c_ip >= lim_ip:
            exhausted = "ip"
        elif c_global >= lim_global:
            exhausted = "global"

        if exhausted is not None:
            conn.rollback()
            return False, exhausted, {
                "limit": lim_owner,
                "used": c_owner,
                "remaining": max(0, lim_owner - c_owner),
                "resets_at": resets_at,
            }

        for subj in (subj_owner, subj_ip, subj_global):
            conn.execute(
                """
                INSERT INTO usage(day, subject, n) VALUES(?, ?, 1)
                ON CONFLICT(day, subject) DO UPDATE SET n = n + 1
                """,
                (day, subj),
            )
        conn.commit()
        new_used = c_owner + 1
        return True, None, {
            "limit": lim_owner,
            "used": new_used,
            "remaining": max(0, lim_owner - new_used),
            "resets_at": resets_at,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def refund(owner_hash, ip_hash, db_path=None, now=None):
    """Decrement usage by 1 (floor at 0) when a model call fails."""
    day = sgt_today(now)
    conn = store.get_db(db_path)
    try:
        init_usage_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        for subj in (f"o:{owner_hash}", f"i:{ip_hash}", "g:all"):
            conn.execute(
                "UPDATE usage SET n = MAX(0, n - 1) WHERE day = ? AND subject = ?",
                (day, subj),
            )
        conn.commit()
    finally:
        conn.close()


def get_quota_status(owner_hash, ip_hash=None, db_path=None, limits=None, now=None):
    """Return {limit, used, remaining, resets_at} for owner."""
    lim = limits or {}
    lim_owner = int(lim.get("owner", 10))
    day = sgt_today(now)
    resets_at = next_sgt_midnight_iso(now)
    conn = store.get_db(db_path)
    try:
        init_usage_table(conn)
        used = _get_count(conn, day, f"o:{owner_hash}")
        return {
            "limit": lim_owner,
            "used": used,
            "remaining": max(0, lim_owner - used),
            "resets_at": resets_at,
        }
    finally:
        conn.close()


def cleanup_old_usage(days=30, db_path=None, now=None):
    """Delete usage rows older than `days`."""
    dt = now if now is not None else datetime.datetime.now(SGT)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    cutoff = (dt.astimezone(SGT) - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    conn = store.get_db(db_path)
    try:
        init_usage_table(conn)
        conn.execute("DELETE FROM usage WHERE day < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()

