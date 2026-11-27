"""Gate 5 runtime contention & fencing invariant check for M09 Transactions & Idempotency."""

import sqlite3
import tempfile
import threading
from pathlib import Path


def run_check(module_dir: Path) -> tuple[bool, str]:
    if not (module_dir / "drill_a_core.py").is_file():
        return False, "missing drill_a_core.py"

    try:
        import drill_a_core
    except Exception as exc:
        return False, f"failed to import drill_a_core: {exc}"

    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            db_path = Path(tmp_dir) / "gate5_ledger.db"

            # Warm initial WAL schema once, then hammer with 8 concurrent threads
            with drill_a_core.open_ledger(db_path):
                pass

            worker_count = 8
            barrier = threading.Barrier(worker_count)
            lock = threading.Lock()
            side_effect_runs: list[int] = []
            submissions: list[drill_a_core.StoredSubmission] = []
            worker_errors: list[BaseException] = []

            def compute_snapshot() -> dict[str, object]:
                with lock:
                    side_effect_runs.append(1)
                    return {"side_effect_seq": len(side_effect_runs), "ok": True}

            def hammer(worker_idx: int) -> None:
                payload: dict[str, object] = (
                    {"tenant": "acme", "amount": 250}
                    if worker_idx % 2 == 0
                    else {"amount": 250, "tenant": "acme"}
                )
                try:
                    barrier.wait()
                    with drill_a_core.open_ledger(db_path) as ledger:
                        sub = ledger.submit_idempotent(
                            "gate5-req-1",
                            "gate5-task-1",
                            payload,
                            compute_snapshot,
                        )
                    with lock:
                        submissions.append(sub)
                except BaseException as exc:
                    with lock:
                        worker_errors.append(exc)

            threads = [
                threading.Thread(target=hammer, args=(idx,))
                for idx in range(worker_count)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            if worker_errors:
                return False, f"concurrent submit_idempotent raised: {worker_errors[0]!r}"
            if len(submissions) != worker_count:
                return False, f"expected {worker_count} submissions, got {len(submissions)}"
            if len(side_effect_runs) != 1:
                return (
                    False,
                    f"expected side-effect callback to run once, ran {len(side_effect_runs)} times",
                )
            created_true = sum(1 for sub in submissions if sub.created_new)
            if created_true != 1:
                return False, f"expected exactly 1 created_new=True, got {created_true}"

            raw_conn = sqlite3.connect(db_path)
            try:
                sub_rows = int(
                    raw_conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
                )
                task_rows = int(
                    raw_conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
                )
            finally:
                raw_conn.close()

            if sub_rows != 1 or task_rows != 1:
                return (
                    False,
                    f"expected 1 submission & 1 task row, found submissions={sub_rows}, tasks={task_rows}",
                )

            # Verify lease fencing rejects stale fence_token
            with drill_a_core.open_ledger(db_path) as ledger:
                lease_1 = ledger.acquire_lease("gate5-task-1", "worker-1")
                lease_2 = ledger.acquire_lease("gate5-task-1", "worker-2")
                stale_rejected = False
                try:
                    ledger.record_outcome(
                        "gate5-task-1",
                        lease_1.fence_token,
                        '{"by":"stale-worker-1"}',
                    )
                except drill_a_core.StaleFenceError:
                    stale_rejected = True

                if not stale_rejected:
                    return False, "stale fence_token did not raise StaleFenceError"

                ledger.record_outcome(
                    "gate5-task-1",
                    lease_2.fence_token,
                    '{"by":"active-worker-2"}',
                )
                status, final_fence, outcome = ledger.get_task_outcome("gate5-task-1")
                if (status, final_fence, outcome) != (
                    "succeeded",
                    2,
                    '{"by":"active-worker-2"}',
                ):
                    return False, f"unexpected final task outcome: {(status, final_fence, outcome)!r}"

    except Exception as exc:
        return False, f"runtime verification failed: {exc}"

    return (
        True,
        "8 concurrent threads executed side-effect 1x (1 row), and stale fence_token raised StaleFenceError",
    )
