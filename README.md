# Python 3.14 & Software Engineering Fundamentals Lab (AI Era)

A complete **12-module hands-on workshop** (`M01`–`M12`, 60–90 minutes per block) for polishing the Python 3.14 and Software Engineering fundamentals that matter *most* when working with coding agents.

Every module combines:
1. **10m Mental Model & ROI Map** — what to write cold vs. what to delegate to AI, plus the classic AI failure mode.
2. **35m Drill A: Cold-Turkey Core (AI OFF)** — implement core invariants from a blank docstring contract (`drill_a_core.py`) and write adversarial tests (`test_learner_a.py`).
3. **25m Drill B: Spec-First AI Pair** — write strict `Protocol`/type contracts and regression tests first, then remediate a flawed AI-generated component (`drill_b_ai_adapter.py`).
4. **15m 5-Stage Automated Evaluation Gate** — `ruff check`, `pyright --strict`, frozen `pytest` oracle, **100% seeded-bug mutation kill rate**, and module-specific runtime invariant checks.

---

## Workshop Guides

- **[`WORKSHOP.md`](./WORKSHOP.md)** — Full 12-module curriculum, 80/20 Human-vs-AI Time-ROI matrix, dependency learning graph, drill briefs, and step-by-step evaluation guides.
- **[`docs/WORKSHOP.html`](./docs/WORKSHOP.html)** — Self-contained interactive HTML workshop handbook.

---

## Quickstart

Requires **Python 3.14** (compatible `>=3.12` for tooling, tested on CPython 3.14) and **[`uv`](https://docs.astral.sh/uv/)**. Zero external servers, cloud keys, or Docker required.

```powershell
# 1. Install dev/lab toolchain (.venv: pytest, hypothesis, ruff, pyright)
uv sync

# 2. Verify environment, non-vacuous starter gates, and all 12 reference solutions
.\go.ps1 -Check

# 3. Evaluate your working code on any module (m01 .. m12)
.\go.ps1 -Module m01

# Cross-platform Python CLI equivalents:
uv run python scripts/eval_module.py m01
uv run python scripts/eval_module.py all --use-solutions
uv run python scripts/verify_all.py
```

---

## Curriculum & Module Index (`taskledger` Spine)

All 12 modules share the **`taskledger`** domain (a zero-framework local durable task and tool execution engine), with decoupled entry contracts so modules work sequentially (`M01 -> M12`) or standalone:

| Module | Topic & Core Primitives | Lab Directory |
|---|---|---|
| **M01** | Object Model, Mutability, Aliasing, Identity, Hashing & Copy Semantics | [`labs/m01_object_model`](./labs/m01_object_model/README.md) |
| **M02** | Collections, Algorithmic Complexity (`deque`/`heapq`/`bisect`) & `slots=True` | [`labs/m02_collections_complexity`](./labs/m02_collections_complexity/README.md) |
| **M03** | Domain Modeling, Invariants, State Machines & Parse-Don't-Validate | [`labs/m03_domain_invariants`](./labs/m03_domain_invariants/README.md) |
| **M04** | Python 3.14 Static Typing: PEP 695 Generics, `Protocol`, Unions & `TypeIs` | [`labs/m04_static_typing`](./labs/m04_static_typing/README.md) |
| **M05** | Lazy Generators (`yield`), `ExitStack` Lifecycles & `ExceptionGroup` / `except*` | [`labs/m05_lifecycles_generators`](./labs/m05_lifecycles_generators/README.md) |
| **M06** | Modular Architecture: Deep Modules & Functional Core / Imperative Shell | [`labs/m06_modular_architecture`](./labs/m06_modular_architecture/README.md) |
| **M07** | Executable Verification: Contract Fakes, Golden Masters & `Hypothesis` | [`labs/m07_verification_harnesses`](./labs/m07_verification_harnesses/README.md) |
| **M08** | Structured Concurrency: `asyncio.TaskGroup`, Cancellation & Backpressure | [`labs/m08_structured_concurrency`](./labs/m08_structured_concurrency/README.md) |
| **M09** | State, ACID Transactions (`sqlite3` WAL / `BEGIN IMMEDIATE`), Idempotency & Fencing | [`labs/m09_transactions_idempotency`](./labs/m09_transactions_idempotency/README.md) |
| **M10** | Packaging (`uv`), Profiling (`tracemalloc`) & `contextvars` Span Telemetry | [`labs/m10_packaging_profiling_otel`](./labs/m10_packaging_profiling_otel/README.md) |
| **M11** | Security & Trust Boundaries: `Path.resolve`, `argv`, SQL & Untrusted Output Gates | [`labs/m11_security_boundaries`](./labs/m11_security_boundaries/README.md) |
| **M12** | Scientific Debugging, Trace-Driven RCA & End-to-End `TaskLedger` Audit Capstone | [`labs/m12_debugging_capstone`](./labs/m12_debugging_capstone/README.md) |

---

## Repository Layout

```text
python-se-fundamentals-lab/
├── WORKSHOP.md                 # Full 12-module workshop guide & evaluation rubrics
├── docs/WORKSHOP.html          # Self-contained HTML workshop guide
├── pyproject.toml              # uv config + strict pyright, ruff, pytest, hypothesis
├── go.ps1                      # PowerShell runner (-Check, -Module <id>, -VerifySolutions)
├── scripts/
│   ├── eval_module.py          # 5-stage isolated module evaluator (--use-solutions supported)
│   └── verify_all.py           # Proves starters fail non-vacuously + 12/12 solutions pass 100%
├── labs/                       # Learner workspaces (m01_object_model .. m12_debugging_capstone)
│   └── mXX_<slug>/
│       ├── README.md           # Module entry contract, signatures, and eval command
│       ├── drill_a_core.py     # Cold-Turkey Core surface (AI OFF)
│       ├── test_learner_a.py   # Learner test suite (must kill 100% of seeded_bugs_a.py)
│       ├── seeded_bugs_a.py    # Realistic subtle mutants swapped in during Gate 4
│       ├── drill_b_ai_adapter.py # Plausible flawed AI-generated component to harden
│       ├── test_acceptance_a.py  # Frozen acceptance suite for Drill A
│       ├── test_acceptance_b.py  # Frozen acceptance suite for Drill B
│       └── runtime_check.py    # Gate 5 non-functional & AST/memory/concurrency invariant check
└── solutions/                  # Verified reference implementations (spoiler-isolated)
    └── mXX_<slug>/
        ├── drill_a_core.py
        ├── test_learner_a.py
        └── drill_b_ai_adapter.py
```

---

## The 5-Stage Evaluation Gate

Every `uv run python scripts/eval_module.py mXX` run copies the module into an isolated temporary directory and enforces all five stages:

1. **Gate 1 — `ruff check`**: Zero lint errors, unused bindings, mutable defaults, or style defects.
2. **Gate 2 — `pyright --strict`**: Full strict static type checking across Python 3.14 syntax.
3. **Gate 3 — Frozen Oracle (`pytest`)**: Passes all hidden/frozen boundary tests in `test_acceptance_a.py` and `test_acceptance_b.py`.
4. **Gate 4 — Seeded-Bug Mutation Kill Rate (`100%`)**: Your `test_learner_a.py` passes on your code *and* fails on **every** subtle mutant in `seeded_bugs_a.py`.
5. **Gate 5 — Runtime Invariant (`runtime_check.py`)**: Enforces module-specific non-functional guarantees (`slots=True`, `tracemalloc` ceilings, AST bans on `Any`/`cast`/`shell=True`, zero leaked `asyncio` tasks, multi-thread SQLite `BEGIN IMMEDIATE` contention safety, and `contextvars` trace isolation).

---

## Honesty Notes

- Passing all 12 modules proves strong **single-process / single-node** Python 3.14 and software engineering fundamentals (immutability, algorithmic complexity, domain invariants, strict typing, resource lifecycles, functional core architecture, property-based testing, structured concurrency, SQLite `BEGIN IMMEDIATE` idempotency/fencing, profiling/context propagation, trust boundaries, and root-cause debugging).
- It intentionally uses stdlib + local SQLite rather than external distributed brokers, Kubernetes, or network services — distributed consensus, cross-node clock skew, and multi-service network partitions require dedicated distributed-systems testing beyond a single-node lab.

