import json
import uuid
from datetime import datetime, timezone

from .sessions import SessionRepository


def now():
    return datetime.now(timezone.utc).isoformat()


class ExecutionConflict(ValueError):
    pass


class ExecutionRepository(SessionRepository):
    def __init__(self, directory):
        super().__init__(directory)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_runs (id TEXT PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id), status TEXT NOT NULL, created_at TEXT NOT NULL, task TEXT, team_state TEXT, result TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS execution_events (run_id TEXT NOT NULL REFERENCES execution_runs(id), seq INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,seq))"
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS execution_active_session ON execution_runs(session_id) WHERE status IN ('created','active','awaiting_input')"
            )

    def create_run(self, session_id):
        import sqlite3

        identifier = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT id FROM sessions WHERE id=? AND archived=0", (session_id,)
            ).fetchone():
                raise LookupError("Session not found")
            try:
                db.execute(
                    "INSERT INTO execution_runs(id,session_id,status,created_at) VALUES (?,?,?,?)",
                    (identifier, session_id, "created", now()),
                )
            except sqlite3.IntegrityError:
                raise ExecutionConflict("A run already owns this session") from None
        return {"run_id": identifier, "session_id": session_id, "status": "created"}

    def get_run(self, identifier):
        with self.connect() as db:
            row = db.execute(
                "SELECT r.*,s.team_snapshot FROM execution_runs r JOIN sessions s ON s.id=r.session_id WHERE r.id=? AND s.archived=0",
                (identifier,),
            ).fetchone()
        if row is None:
            raise LookupError("Run not found")
        return dict(row)

    def claim(self, identifier, task):
        with self.connect() as db:
            if (
                db.execute(
                    "UPDATE execution_runs SET status='active',task=? WHERE id=? AND status='created'",
                    (task, identifier),
                ).rowcount
                != 1
            ):
                raise ExecutionConflict("Run was already started or stopped")

    def event(self, identifier, payload, status=None):
        payload = {**payload, "timestamp": now()}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM execution_runs WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise LookupError("Run not found")
            if row["status"] not in ("created", "active", "awaiting_input"):
                raise ExecutionConflict("Run is already terminal")
            seq = db.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM execution_events WHERE run_id=?",
                (identifier,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO execution_events VALUES (?,?,?)",
                (identifier, seq, json.dumps(payload, ensure_ascii=False)),
            )
            if status:
                db.execute(
                    "UPDATE execution_runs SET status=? WHERE id=?",
                    (status, identifier),
                )

    def events(self, identifier, after=0):
        run = self.get_run(identifier)
        with self.connect() as db:
            rows = db.execute(
                "SELECT seq,payload FROM execution_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 501",
                (identifier, after),
            ).fetchall()
        return {
            "run_id": identifier,
            "session_id": run["session_id"],
            "status": run["status"],
            "has_more": len(rows) > 500,
            "events": [
                {**json.loads(row["payload"]), "seq": row["seq"]} for row in rows[:500]
            ],
        }

    def previous_state(self, run):
        with self.connect() as db:
            row = db.execute(
                "SELECT team_state FROM execution_runs WHERE session_id=? AND status='complete' AND team_state IS NOT NULL ORDER BY created_at DESC LIMIT 1",
                (run["session_id"],),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def finish(self, identifier, status, result, state=None, terminal_event=None):
        if status not in ("complete", "stopped", "error"):
            raise ValueError("Invalid terminal status")
        run = self.get_run(identifier)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "UPDATE execution_runs SET status=?,result=?,team_state=? WHERE id=? AND status IN ('created','active','awaiting_input')",
                    (
                        status,
                        json.dumps(result),
                        json.dumps(state) if state is not None else None,
                        identifier,
                    ),
                ).rowcount
                != 1
            ):
                return
            if terminal_event is not None:
                seq = db.execute(
                    "SELECT COALESCE(MAX(seq),0)+1 FROM execution_events WHERE run_id=?",
                    (identifier,),
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO execution_events VALUES (?,?,?)",
                    (
                        identifier,
                        seq,
                        json.dumps(
                            {**terminal_event, "timestamp": now()}, ensure_ascii=False
                        ),
                    ),
                )
            rows = db.execute(
                "SELECT payload FROM execution_events WHERE run_id=? ORDER BY seq",
                (identifier,),
            ).fetchall()
            events = [json.loads(row[0]) for row in rows]
            payload = {
                "id": identifier,
                "run_id": identifier,
                "created_at": run["created_at"],
                "status": status,
                "task": [{"source": "user", "content": run["task"] or ""}],
                "team_result": result,
                "messages": [
                    {
                        "config": event["data"],
                        "created_at": event["timestamp"],
                        "session_id": run["session_id"],
                        "run_id": identifier,
                    }
                    for event in events
                    if event["type"] == "message"
                ],
            }
            db.execute(
                "INSERT INTO runs(session_id,payload) VALUES (?,?)",
                (run["session_id"], json.dumps(payload, ensure_ascii=False)),
            )

    def recover_interrupted(self):
        with self.connect() as db:
            identifiers = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM execution_runs WHERE status IN ('created','active','awaiting_input')"
                )
            ]
        for identifier in identifiers:
            reason = "Previous executor exited before this run completed; start a new run to continue"
            self.finish(
                identifier,
                "error",
                {"task_result": {"messages": [], "stop_reason": reason}},
                terminal_event={"type": "error", "status": "error", "error": reason},
            )
