"""Actual process-crash recovery and core-only performance; no UI/backend runs.

Every session and event below is an explicitly synthetic persistence fixture.
Native agent processes, dependencies, credentials and existing repos are untouched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from acw.core import WorkspaceCore


class NoBackendCalls:
    """A fail-on-use guard, not a model or transport simulation."""
    state = "Disconnected"
    cwd = ""

    def __init__(self):
        self.calls = []

    def _reject(self, operation):
        self.calls.append(operation)
        raise AssertionError("Recovery attempted forbidden backend call: " + operation)

    def connect(self):
        return self._reject("connect")

    def send_message(self, *args, **kwargs):
        return self._reject("send_message")

    def resume_session(self, *args, **kwargs):
        return self._reject("resume_session")

    def create_session(self):
        return self._reject("create_session")


def crash_fixture(root):
    """Child process: commit fixture state, then exit without cleanup/checkpoint."""
    root = Path(root)
    project_dir = root / "isolated-project"
    project_dir.mkdir()
    core = WorkspaceCore(root / "data")
    # Explicit branch fixture: this test does not inspect any Git repository.
    core.git_snapshot = lambda project_id=None: {"branch": "synthetic-recovery"}
    project = core.create_project("Synthetic process recovery", project_dir)
    core.select_project(project["id"], sync=False)
    task = core.create_task("Synthetic recovery task")
    core.set_setting("logs.max_size", 1024)
    mappings = {agent: "synthetic-session-" + agent for agent in ("claude", "dot", "codex")}
    for agent, session_id in mappings.items():
        core.ingest_event(agent, "session", session_id=session_id)
    completed = core.ingest_event("claude", "message_end", content="Complete synthetic response A")
    preview = core.prepare_handoff(completed["message_id"], "codex", "Synthetic note; never transmitted")
    core.store.update("handoffs", {"id": preview["id"]}, {"status": "sending"})
    core.ingest_event("codex", "message_start")
    core.ingest_event("codex", "message_delta", content="Committed safe partial line\nUnfinished memory-only tail")
    held_references = []
    for index in range(24):
        event = core.ingest_event("codex", "event", summary="rotation-fixture-%02d " % index + "x" * 90)
        held_references.append({"id": event["id"], "raw_ref": event["raw_ref"]})
    manifest = {
        "project_id": project["id"], "task_id": task["id"], "mappings": mappings,
        "complete_message_id": completed["message_id"], "handoff_id": preview["id"],
        "held_references": held_references,
        "event_count": len(core.events(limit=100000)),
        "message_count": len(core.messages()),
        "prompt_sent_count": len([e for e in core.events(limit=100000) if e["type"] == "prompt_sent"]),
    }
    with (root / "expected.json").open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    # Deliberately skip core.close(), Python finally blocks and SQLite checkpoint.
    # This exits only this dedicated test process; no backend process exists.
    os._exit(91)


def run_crash_recovery(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--crash-fixture", str(root)],
        cwd=str(SOURCE_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=40, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode != 91:
        raise AssertionError("Crash child did not reach intentional exit 91: " + process.stderr)
    manifest = json.loads((root / "expected.json").read_text(encoding="utf-8"))
    guards = {agent: NoBackendCalls() for agent in ("claude", "dot", "codex")}
    start = time.perf_counter()
    core = WorkspaceCore(root / "data", guards)
    recovery_ms = (time.perf_counter() - start) * 1000
    try:
        assert core.current_project_id == manifest["project_id"]
        assert core.current_task_id == manifest["task_id"]
        for agent, session_id in manifest["mappings"].items():
            assert core.current_task[agent + "_session"] == session_id
            assert core.sessions(agent)[0]["id"] == session_id
        messages = core.messages()
        assert len(messages) == manifest["message_count"]
        complete = next(message for message in messages if message["id"] == manifest["complete_message_id"])
        assert complete["content"] == "Complete synthetic response A" and complete["status"] == "complete"
        partial = next(message for message in messages if message["agent"] == "codex")
        assert partial["status"] == "interrupted"
        assert partial["content"] == "Committed safe partial line\n"
        events = core.events(limit=100000)
        assert len(events) >= manifest["event_count"]
        assert any(event["type"] == "recovery" for event in events)
        assert len([event for event in events if event["type"] == "prompt_sent"]) == manifest["prompt_sent_count"]
        assert core.handoffs()[0]["id"] == manifest["handoff_id"]
        assert core.handoffs()[0]["status"] == "delivery_unknown"
        assert all(not guard.calls and guard.state == "Disconnected" for guard in guards.values())
        for reference in manifest["held_references"]:
            assert core.read_raw(reference["raw_ref"])["id"] == reference["id"]
        references = {row["raw_ref"] for row in events + messages if row.get("raw_ref")}
        for reference in references:
            assert isinstance(core.read_raw(reference), dict)
        segments = list(core.store.raw_dir.glob("codex*.jsonl*"))
        assert len(segments) > 1
        integrity = core.store.db.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok"
        return {
            "status": "PASS", "scope": "Actual subprocess os._exit(91); synthetic persistence fixture; no backend or GUI",
            "child_exit_code": process.returncode, "recovery_ms": round(recovery_ms, 3),
            "sqlite_integrity": integrity, "project_restored": True, "task_restored": True,
            "all_three_session_mappings_restored": True, "message_count": len(messages),
            "event_count": len(events), "raw_references_verified": len(references),
            "held_pre_rotation_references_verified": len(manifest["held_references"]),
            "codex_raw_segments": len(segments),
            "compressed_codex_segments": sum(path.suffix == ".gz" for path in segments),
            "partial_message_marked_interrupted": True,
            "complete_lines_recovered": True, "unfinished_line_omitted_by_security_policy": True,
            "inflight_handoff_marked_delivery_unknown": True,
            "adapter_calls": {agent: guard.calls for agent, guard in guards.items()},
            "automatic_connects": 0, "automatic_prompt_resends": 0,
        }
    finally:
        core.close()


def performance_fixture(root):
    """Fresh core-only child: one-second idle then three synthetic event workers."""
    core = WorkspaceCore(Path(root) / "data")
    try:
        cpu_start, wall_start = time.process_time(), time.perf_counter()
        time.sleep(1.0)
        idle_wall = time.perf_counter() - wall_start
        idle_cpu = time.process_time() - cpu_start
        counts = {"claude": 334, "dot": 333, "codex": 333}
        def worker(agent, count):
            for index in range(count):
                core.ingest_event(agent, "event", summary=f"Synthetic load event {agent}:{index}", status="fixture")
            return count
        wall_start, cpu_start = time.perf_counter(), time.process_time()
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(worker, agent, count) for agent, count in counts.items()]
            submitted = sum(job.result() for job in jobs)
        elapsed = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
        events = core.events(limit=2000)
        queued = core.drain_events(limit=2000)
        actual = {agent: sum(event["agent"] == agent for event in events) for agent in counts}
        assert submitted == len(events) == len(queued) == 1000
        assert actual == counts
        assert len({event["id"] for event in events}) == 1000
        assert idle_cpu < 0.25, "Core-only idle consumed unexpectedly high CPU"
        return {
            "status": "PASS", "scope": "Core-only fresh Python process; no GUI, Qt import, native agent or real stream",
            "idle_observation_seconds": round(idle_wall, 6), "idle_process_cpu_seconds": round(idle_cpu, 6),
            "idle_one_core_cpu_percent": round(100 * idle_cpu / idle_wall, 4),
            "workers": 3, "events_submitted": submitted, "events_persisted": len(events),
            "events_queued": len(queued), "per_agent_fixture_event_count": actual,
            "ingestion_wall_seconds": round(elapsed, 6), "ingestion_cpu_seconds": round(cpu, 6),
            "events_per_second": round(submitted / elapsed, 2),
            "gui_responsiveness": "NOT TESTED; this measurement does not satisfy UI streaming acceptance",
        }
    finally:
        core.close()


def run_performance(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--performance-fixture", str(root)],
        cwd=str(SOURCE_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode:
        raise AssertionError("Performance fixture failed: " + process.stderr)
    return json.loads(process.stdout)


class ProcessRecoveryTests(unittest.TestCase):
    def test_unclean_exit_restores_state_and_immutable_rotated_raw_references(self):
        with tempfile.TemporaryDirectory(prefix="acw-process-crash-") as root:
            result = run_crash_recovery(root)
            self.assertEqual("PASS", result["status"])
            self.assertEqual(91, result["child_exit_code"])

    def test_core_only_idle_and_three_worker_ingestion(self):
        with tempfile.TemporaryDirectory(prefix="acw-core-performance-") as root:
            result = run_performance(root)
            self.assertEqual("PASS", result["status"])
            self.assertEqual(1000, result["events_persisted"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--crash-fixture":
        crash_fixture(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "--performance-fixture":
        print(json.dumps(performance_fixture(sys.argv[2])))
    elif len(sys.argv) == 3 and sys.argv[1] == "--evidence":
        with tempfile.TemporaryDirectory(prefix="acw-recovery-evidence-") as root:
            report = {
                "observed_utc": datetime.now(timezone.utc).isoformat(), "python": sys.executable,
                "isolation": "Fresh temporary directories; no production repo, UI, credentials or backend process",
                "crash_recovery": run_crash_recovery(Path(root) / "recovery"),
                "performance": run_performance(Path(root) / "performance"),
            }
        target = Path(sys.argv[2])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    else:
        unittest.main()
