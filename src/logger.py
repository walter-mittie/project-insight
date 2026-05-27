"""
src/logger.py
-------------
F-15 · JSONL Logging Infrastructure

Project Insight: Agentic Conversational BI 

Public interface
----------------
    log_turn(result, session_id, resumed=False, resumed_at=None) -> bool
    load_past_sessions(log_path=LOG_PATH)  -> list[dict]
    read_turns_from_jsonl(session_id, log_path=LOG_PATH) -> list[dict]

Canonical JSONL field names (Sprint 5 benchmark reads these exactly):
    session_id, turn_id, timestamp, user_query, generated_sql,
    execution_time_ms, retry_count, row_count, success_flag,
    narrative_generated, history_truncated, error_stage,
    resumed, resumed_at

Notes
-----
- raw_nl2sql and raw_narrative are intentionally NOT logged (too large;
  Sprint 5 benchmark operates on structured fields only — ADR-041).
- Log write failures are non-fatal: this module raises LogWriteError so
  app.py can surface st.warning("Log write failed — turn not recorded.")
  without crashing the session.
- File opened in append mode ("a") — never overwrites existing log.
- logs/ directory is created automatically on first write.
- All reads return [] if the log file does not yet exist.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
LOG_PATH = "logs/interactions.jsonl"


class LogWriteError(Exception):
    """Raised when a JSONL write fails; caught by app.py to surface st.warning."""


# ── Public: write ──────────────────────────────────────────────────────────────


def log_turn(
    result: dict,
    session_id: str,
    rendered_chart_type: str = "auto",
    resumed: bool = False,
    resumed_at: Optional[str] = None,
) -> bool:
    """
    Append one turn to the JSONL interaction log.

    Parameters
    ----------
    result : dict
        Return dict from run_turn().  Handles both success and error shapes.
    session_id : str
        Session UUID from st.session_state.session_id.
    rendered_chart_type : str
        The chart type actually shown to the user after the full priority
        chain resolved (ADR-042). Set by app.py. Defaults to "auto".
    resumed : bool
        True for turns logged during session restoration (State 2 → State 3).
    resumed_at : str | None
        ISO timestamp string when restoration occurred; None for normal turns.

    Returns
    -------
    bool
        True on success.  Raises LogWriteError on any failure so the caller
        (app.py) can display a non-blocking warning without crashing.
    """
    try:
        _ensure_log_dir(LOG_PATH)

        status = result.get("status", "error")
        is_success = status == "success"
        turn_index = result.get("turn_index", 0)

        entry = {
            "session_id": session_id,
            "turn_id": turn_index + 1,  # 1-based (spec §16)
            "timestamp": _utc_now(),
            "user_query": result.get("user_question", ""),
            "generated_sql": result.get("sql") if is_success else None,
            "execution_time_ms": result.get("exec_time_ms") if is_success else None,
            "retry_count": result.get("retry_count", 0),
            "row_count": result.get("row_count") if is_success else None,
            "success_flag": is_success,
            "narrative_generated": bool(result.get("narrative"))
            if is_success
            else False,
            "history_truncated": result.get("history_truncated", False),
            "error_stage": result.get("error_stage") if not is_success else None,
            "suggested_chart_type": result.get(
                "suggested_chart_type", "auto"
            ),  # ADR-042
            "rendered_chart_type": rendered_chart_type,  # ADR-042
            "resumed": resumed,
            "resumed_at": resumed_at if resumed else None,
        }

        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

        log.debug(
            "log_turn | session=%s turn=%d success=%s",
            session_id[:8],
            turn_index + 1,
            is_success,
        )
        return True

    except Exception as exc:
        log.error("log_turn failed: %s", exc)
        raise LogWriteError(str(exc)) from exc


# ── Public: read ───────────────────────────────────────────────────────────────


def load_past_sessions(log_path: str = LOG_PATH) -> list[dict]:
    """
    Read the JSONL log and return a summary list for the sidebar, ordered
    most-recent first.

    Each item:
        {
            "id":      session_id str,
            "date":    "02 February 2026",
            "preview": first user_query str (up to 120 chars),
            "q_count": total non-resumed turn count,
        }

    Returns [] if the log file does not exist.
    """
    if not os.path.exists(log_path):
        return []

    sessions: dict[str, dict] = {}

    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                sid = entry.get("session_id", "")
                if not sid:
                    continue

                if sid not in sessions:
                    raw_ts = entry.get("timestamp", "")
                    sessions[sid] = {
                        "id": sid,
                        "date": _format_log_date(raw_ts),
                        "preview": entry.get("user_query", "")[:120],
                        "q_count": 0,
                        "_sort_ts": raw_ts,  # internal; removed before return
                    }

                # Count only original (non-resumed) successful turns
                if not entry.get("resumed", False) and entry.get("success_flag", False):
                    sessions[sid]["q_count"] += 1

    except OSError as exc:
        log.warning("load_past_sessions: could not read log: %s", exc)
        return []

    result = list(sessions.values())
    result.sort(key=lambda x: x.get("_sort_ts", ""), reverse=True)
    for item in result:
        item.pop("_sort_ts", None)
    return result


def read_turns_from_jsonl(
    session_id: str,
    log_path: str = LOG_PATH,
) -> list[dict]:
    """
    Return all log entries for a given session_id, sorted by turn_id ascending.

    Used by load_session() (State 1 — Pending) to populate turns_raw.
    Only successful non-resumed turns are returned — these are the original
    user queries that run_restore() will replay via run_turn().

    Returns [] if the log file does not exist or contains no matching entries.
    """
    if not os.path.exists(log_path):
        return []

    turns = []
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if (
                    entry.get("session_id") == session_id
                    and entry.get("success_flag", False)
                    and not entry.get("resumed", False)
                ):
                    turns.append(entry)

    except OSError as exc:
        log.warning("read_turns_from_jsonl: could not read log: %s", exc)
        return []

    turns.sort(key=lambda x: x.get("turn_id", 0))
    return turns


# ── Internal helpers ───────────────────────────────────────────────────────────


def _ensure_log_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _utc_now() -> str:
    """Return current UTC time as ISO-8601 string (e.g. '2026-02-02T09:09:00Z')."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_log_date(raw_ts: str) -> str:
    """
    Convert '2026-02-02T09:09:00Z' → '02 February 2026'.
    Returns raw_ts unchanged if parsing fails.
    """
    try:
        dt = datetime.strptime(raw_ts[:10], "%Y-%m-%d")
        return dt.strftime("%-d %b %Y")
    except Exception:
        return raw_ts[:10]
