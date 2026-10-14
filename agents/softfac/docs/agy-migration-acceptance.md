# SoftFac v2 M3 Acceptance Evidence

Status: **M3 implementation evidence; independent Sol review is still
required.** This record covers the active AGY runtime pin and deterministic
release gates. It does not authorize deployment or installation changes.

## Active runtime identity

The host-local executable used for M3 preflight was:

| Item | Observed value |
|---|---|
| Path | `C:/Users/HH18/AppData/Local/agy/bin/agy.exe` |
| Version | `1.2.2` |
| SHA-256 | `80a029a8f22dccc123fd39453bd4d51c93d6384d4f365993a3d5accfa4af4b47` |
| Model | `gemini-3.8-flash-high` |
| Boundary | Windows Sandbox |

The live preflight compared the executable version and hash to the active
source pin, verified the required CLI capabilities and model catalog, and
completed the no-edit capability probe inside Windows Sandbox. The retained
`tests/fixtures/agy/1.2.0/` files remain historical evidence and were not
rewritten.

## Deterministic gates

| Gate | Command | Result |
|---|---|---|
| Focused runtime tests | `uv run pytest tests/test_factory_preflight.py tests/test_factory_config.py tests/test_factory_agy_builder.py -q` | `67 passed, 41 subtests passed` |
| F001/F002 affected suite | `uv run pytest tests/test_factory_v2.py tests/test_factory_resume_contract.py -q` | `91 passed, 32 subtests passed` |
| Full suite | `uv run pytest tests -q` | `180 passed, 73 subtests passed` |
| Launcher surface | `python -B bin/hermes-code-factory-v2 run --help`; `python -B bin/hermes-code-factory-v2 plan --help` | both exit `0` |
| Diff whitespace | `git diff --cached --check` | pass |
| Tracked bytecode | `git ls-files` check for `.pyc`/`__pycache__` | empty |
| Filesystem bytecode | recursive `.pyc`/`__pycache__` check | empty |

All Python gates were run with `PYTHONDONTWRITEBYTECODE=1` and
`PYTHONUTF8=1`. The release checksum manifest is updated only after the final
source and documentation contents stabilize.
