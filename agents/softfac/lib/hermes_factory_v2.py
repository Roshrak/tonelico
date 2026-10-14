#!/usr/bin/env python3
# HoH Self-Improvement Engine
"""Hermes Software Factory v2.

Fail-closed orchestration for:
Hermes -> Astra planner -> AGY builder -> tests -> AGY repair ->
fresh Sol reviewer -> hash-checked Git commit.
"""

from __future__ import annotations

import argparse
import ast
import base64
import errno
import hashlib
import inspect
import json
import math
import os
import re
import shlex
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable
from xml.sax.saxutils import escape as xml_escape

from linux_agy_boundary import LinuxBoundaryError, linux_agy_command


DEFAULT_STATE_ROOT = Path.home() / ".hermes" / "software-factory" / "runs"
DEFAULT_PLANNER_MODEL = "gpt-6-astra"
DEFAULT_SOL_MODEL = "gpt-5.6-sol"
DEFAULT_REVIEWER_MODEL = DEFAULT_SOL_MODEL
DEFAULT_PLANNER_REASONING = "high"
DEFAULT_REVIEWER_REASONING = "high"
DEFAULT_BUILDER_MODEL = "gemini-3.8-flash-high"
RUN_CONFIG_VERSION = 2
BUILDER_CONTRACT_VERSION = 1
SCHEMA_VERSION = 3
WINDOWS_AGY_VERSION = "1.2.2"
WINDOWS_AGY_SHA256 = "80a029a8f22dccc123fd39453bd4d51c93d6384d4f365993a3d5accfa4af4b47"
LINUX_AGY_VERSION = "1.2.0"
LINUX_AGY_SHA256 = "787ebdb295c94b075ce459503686388b222db4349e74551439a962f1e5e7c01e"
if sys.platform.startswith("linux"):
    SUPPORTED_AGY_VERSION = LINUX_AGY_VERSION
    APPROVED_AGY_SHA256 = LINUX_AGY_SHA256
else:
    SUPPORTED_AGY_VERSION = WINDOWS_AGY_VERSION
    APPROVED_AGY_SHA256 = WINDOWS_AGY_SHA256
AGY_PREFLIGHT_PRINT_TIMEOUT_SECONDS = 90
AGY_REQUIRED_CAPABILITIES = (
    "--model",
    "--dangerously-skip-permissions",
    "--output-format",
    "--disable-slash-commands",
    "--print",
    "--print-timeout",
)
AGY_REQUIRED_OUTPUT_FORMAT = "stream-json"
AGY_REQUIRED_PERMISSION_MODE = "always-proceed"
AGY_SHELL_SHIMS = {".bat", ".cmd", ".ps1", ".vbs", ".wsf"}
BUILDER_OUTPUT_LIMIT_BYTES = 1024 * 1024
BUILDER_PIPE_READ_CHUNK_BYTES = 64 * 1024
BUILDER_SHUTDOWN_TIMEOUT_SECONDS = 5.0
BUILDER_WINDOWS_COMMAND_LINE_LIMIT_UNITS = 30_000
FINAL_STATES = {"committed", "complete", "failed", "blocked"}
AGY_NAVIGATION_RECOVERY_MODES = {"off", "observe", "adaptive"}
AGY_NAVIGATION_RECOVERY_DEFAULT = "adaptive"
CAPSULE_SCHEMA_VERSION = 1
CAPSULE_EDITABLE_FILE = "target.py"


def classify_objective(request: str) -> dict[str, Any]:
    """Classifies a user request into 'capability_growth' or 'repair' with checkable rationale.

    Deterministic Policy:
    1. Scan request for repair-oriented indicators (fix, bug, error, fail, regression, etc.).
    2. Scan request for capability-growth indicators (add, new, implement, feature, create, etc.).
    3. Pure repair: Only repair indicators present -> 'repair'.
    4. Pure growth: Only growth indicators present -> 'capability_growth'.
    5. Mixed: Both indicators present -> 'capability_growth' under the HoH principle that
       new capability delivery takes architectural precedence while repairs are subsumed into the iteration.
    6. Ambiguous / default: No explicit indicators -> 'capability_growth' as forward development progress.
    """
    req_lower = request.lower()
    repair_keywords = {
        "fix", "fixes", "fixed", "fixing", "repair", "repairs", "repaired", "repairing",
        "bug", "bugs", "bugfix", "error", "errors", "fail", "fails", "failed", "failing",
        "failure", "failures", "crash", "crashes", "crashed", "regression", "regressions",
        "broken", "defect", "defects", "resolve", "resolves", "resolved", "resolving",
        "sửa", "lỗi", "khắc phục", "vá",
    }
    growth_keywords = {
        "add", "adds", "added", "adding", "new", "feature", "features", "implement",
        "implements", "implemented", "implementing", "create", "creates", "created",
        "creating", "support", "supports", "supported", "supporting", "extend",
        "extends", "extended", "extending", "enhance", "enhances", "enhanced",
        "enhancing", "build", "builds", "built", "building", "introduce", "introduces",
        "introduced", "introducing", "capability", "capabilities",
        "thêm", "mới", "tạo", "phát triển", "tính năng",
    }

    tokens = set(re.findall(r"\b\w+\b", req_lower))
    found_repair = sorted(tokens & repair_keywords)
    found_growth = sorted(tokens & growth_keywords)

    if found_repair and not found_growth:
        classification = "repair"
        rationale = f"Request contains repair keywords ({found_repair}) without capability expansion keywords."
        policy = "pure_repair"
    elif found_growth and not found_repair:
        classification = "capability_growth"
        rationale = f"Request contains capability growth keywords ({found_growth}) without repair keywords."
        policy = "pure_growth"
    elif found_growth and found_repair:
        classification = "capability_growth"
        rationale = (
            f"Mixed request with growth keywords ({found_growth}) and repair keywords ({found_repair}). "
            "Under HoH policy, mixed tasks are classified as capability_growth to prioritize concrete capability delivery while subsuming fixes."
        )
        policy = "mixed_growth_precedence"
    else:
        classification = "capability_growth"
        rationale = "Request contains no explicit repair keywords; defaulting to capability_growth as forward development progress."
        policy = "default_forward_progress"

    return {
        "classification": classification,
        "rationale": rationale,
        "policy": policy,
        "growth_signals": found_growth,
        "repair_signals": found_repair,
    }


def get_priority_guidance(classification: str) -> str:
    """Returns priority balance guidance for Sol/Astra Planner based on objective classification."""
    if classification == "repair":
        return (
            "Objective is classified as REPAIR. Prioritize diagnosing and repairing the root cause "
            "of reported errors or regressions. Keep changes tightly focused on the fix and avoid unrelated feature additions."
        )
    return (
        "Objective is classified as CAPABILITY_GROWTH. Prioritize delivering the requested new capability "
        "in a bounded, testable increment while preserving previously verified behaviors and addressing any prior gaps."
    )


class MemoryLedger:
    """Manages versioned issue ledger and trajectory tracking under run_dir/ledger."""

    def __init__(self, run_dir: Path, run_id: str, repo: str, root_objective_class: str) -> None:
        self.run_dir = run_dir
        self.ledger_dir = run_dir / "ledger"
        self.ledger_path = self.ledger_dir / "issue_ledger.json"
        self.trajectory_path = self.ledger_dir / "trajectory.json"
        self.run_id = run_id
        self.repo = repo
        self.root_objective_class = root_objective_class
        self.sync_seq = 0
        self.events: list[dict[str, Any]] = []
        self.issues: dict[str, dict[str, Any]] = {}
        self._load_or_init()

    def _load_or_init(self) -> None:
        self.ledger_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.ledger_path.is_file() and self.trajectory_path.is_file():
            try:
                ledger_data = read_json(self.ledger_path)
                trajectory_data = read_json(self.trajectory_path)
                if isinstance(ledger_data, dict) and isinstance(trajectory_data, dict):
                    self.sync_seq = max(
                        ledger_data.get("sync_seq", 0), trajectory_data.get("sync_seq", 0)
                    )
                    self.events = trajectory_data.get("events", [])
                    for issue in ledger_data.get("issues", []):
                        fp = issue.get("fingerprint") or issue.get("id")
                        if fp:
                            self.issues[fp] = issue
                    return
            except Exception:
                pass
        self._flush()

    def _flush(self) -> None:
        self.sync_seq += 1
        issues_list = list(self.issues.values())
        total = len(issues_list)
        open_count = sum(1 for i in issues_list if i.get("status") in {"open", "regressed"})
        resolved_count = sum(1 for i in issues_list if i.get("status") == "resolved")
        regressed_count = sum(1 for i in issues_list if i.get("status") == "regressed")

        ledger_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "repo": self.repo,
            "root_objective_class": self.root_objective_class,
            "sync_seq": self.sync_seq,
            "updated_at": now_iso(),
            "issues": issues_list,
            "summary": {
                "total": total,
                "open": open_count,
                "resolved": resolved_count,
                "regressed": regressed_count,
            },
        }
        trajectory_payload = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "repo": self.repo,
            "root_objective_class": self.root_objective_class,
            "sync_seq": self.sync_seq,
            "updated_at": now_iso(),
            "events": self.events,
        }
        atomic_json(self.ledger_path, ledger_payload)
        atomic_json(self.trajectory_path, trajectory_payload)

    def record_event(
        self,
        *,
        phase: str,
        action: str,
        result: str,
        objective_class: str | None = None,
        details: dict[str, Any] | None = None,
        issue_links: list[str] | None = None,
        artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.events:
            last = self.events[-1]
            if (
                last.get("phase") == phase
                and last.get("action") == action
                and last.get("result") == result
                and last.get("details") == (details or {})
            ):
                return last

        event = {
            "seq": len(self.events) + 1,
            "timestamp": now_iso(),
            "phase": phase,
            "action": action,
            "result": result,
            "objective_class": objective_class or self.root_objective_class,
            "details": details or {},
            "issue_links": issue_links or [],
            "artifacts": artifacts or [],
        }
        self.events.append(event)
        self._flush()
        return event

    def record_or_update_issue(
        self,
        *,
        source: str,
        title: str,
        description: str,
        status: str = "open",
        severity: str = "error",
        cycle: int | str = 1,
        evidence: dict[str, Any] | None = None,
    ) -> str:
        normalized_key = f"{source.strip().lower()}:{title.strip().lower()}"
        fingerprint = hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()[:16]
        issue_id = f"ISSUE-{fingerprint[:8]}"

        if fingerprint in self.issues:
            existing = self.issues[fingerprint]
            if existing.get("status") == "resolved" and status == "open":
                existing["status"] = "regressed"
            elif status != "open":
                existing["status"] = status
            existing["cycle_updated"] = cycle
            existing["occurrences"] = existing.get("occurrences", 1) + 1
            if evidence:
                existing.setdefault("evidence_history", []).append(evidence)
                existing["latest_evidence"] = evidence
        else:
            self.issues[fingerprint] = {
                "id": issue_id,
                "fingerprint": fingerprint,
                "source": source,
                "title": title.strip(),
                "description": description.strip(),
                "status": status,
                "severity": severity,
                "cycle_created": cycle,
                "cycle_updated": cycle,
                "occurrences": 1,
                "evidence": evidence or {},
                "resolution_evidence": None,
            }
        self._flush()
        return issue_id

    def resolve_issues_by_source(
        self, source: str, resolution_evidence: dict[str, Any]
    ) -> list[str]:
        resolved_ids: list[str] = []
        changed = False
        for issue in self.issues.values():
            if issue.get("source") == source and issue.get("status") in {"open", "regressed"}:
                issue["status"] = "resolved"
                issue["resolution_evidence"] = resolution_evidence
                issue["resolved_at"] = now_iso()
                resolved_ids.append(issue["id"])
                changed = True
        if changed:
            self._flush()
        return resolved_ids

    @staticmethod
    def check_snapshot_consistency(ledger_dir: Path) -> tuple[bool, str]:
        ledger_path = ledger_dir / "issue_ledger.json"
        trajectory_path = ledger_dir / "trajectory.json"
        if not ledger_path.is_file() or not trajectory_path.is_file():
            return False, "missing ledger or trajectory file"
        try:
            l_data = read_json(ledger_path)
            t_data = read_json(trajectory_path)
        except Exception as exc:
            return False, f"corrupted json: {exc}"
        if not isinstance(l_data, dict) or not isinstance(t_data, dict):
            return False, "ledger or trajectory is not a JSON object"
        s_l = l_data.get("sync_seq", 0)
        s_t = t_data.get("sync_seq", 0)
        if s_l != s_t:
            return False, f"snapshot sequence mismatch: ledger sync_seq={s_l}, trajectory sync_seq={s_t}"
        if l_data.get("run_id") != t_data.get("run_id"):
            return False, f"run_id mismatch: {l_data.get('run_id')} vs {t_data.get('run_id')}"
        return True, "consistent"


def load_prior_run_context(
    state_root: Path,
    repo: Path,
    prior_run_id: str,
    *,
    max_issues: int = 10,
    max_total_chars: int = 3000,
) -> dict[str, Any]:
    """Safely loads and builds a progressive disclosure context from a prior run's issue ledger."""
    if not isinstance(prior_run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", prior_run_id.strip()):
        raise FactoryError(f"invalid prior run id: {prior_run_id!r}", "prior_run")

    prior_id = prior_run_id.strip()
    root_resolved = state_root.resolve()
    prior_dir = (state_root / prior_id).resolve()

    try:
        prior_dir.relative_to(root_resolved)
    except ValueError as exc:
        raise FactoryError(f"prior run escapes state_root: {prior_id}", "prior_run") from exc

    if not prior_dir.is_dir():
        raise FactoryError(f"prior run directory does not exist: {prior_id}", "prior_run")

    state_file = prior_dir / "run_state.json"
    if not state_file.is_file():
        raise FactoryError(f"prior run missing run_state.json: {prior_id}", "prior_run")

    try:
        prior_state = read_json(state_file)
    except Exception as exc:
        raise FactoryError(f"prior run has invalid run_state.json: {exc}", "prior_run") from exc

    if not isinstance(prior_state, dict):
        raise FactoryError("prior run state must be a JSON object", "prior_run")

    if prior_state.get("schema_version") not in {1, 2, SCHEMA_VERSION}:
        raise FactoryError(
            f"prior run schema_version mismatch: expected current or legacy state schema, got {prior_state.get('schema_version')}",
            "prior_run",
        )

    prior_cfg = prior_state.get("config", {})
    prior_repo_raw = prior_cfg.get("repo")
    if not prior_repo_raw:
        raise FactoryError("prior run state missing repository path", "prior_run")
    prior_repo_resolved = Path(prior_repo_raw).resolve()
    if prior_repo_resolved != repo.resolve():
        raise FactoryError(
            f"prior run repository mismatch: {prior_repo_resolved} != {repo.resolve()}",
            "prior_run",
        )

    ledger_dir = prior_dir / "ledger"
    consistent, reason = MemoryLedger.check_snapshot_consistency(ledger_dir)
    if not consistent:
        raise FactoryError(f"prior run ledger snapshot is not consistent: {reason}", "prior_run")

    ledger_path = ledger_dir / "issue_ledger.json"
    prior_ledger = read_json(ledger_path)

    raw_issues = prior_ledger.get("issues", [])
    if not isinstance(raw_issues, list):
        raw_issues = []

    def issue_priority(item: dict[str, Any]) -> tuple[int, str]:
        st = item.get("status", "")
        if st in {"open", "regressed"}:
            return (0, str(item.get("id", "")))
        return (1, str(item.get("id", "")))

    sorted_issues = sorted(raw_issues, key=issue_priority)
    selected_issues: list[dict[str, Any]] = []
    current_chars = 0
    truncated = False
    omitted_count = 0

    for iss in sorted_issues:
        if len(selected_issues) >= max_issues:
            truncated = True
            omitted_count = len(sorted_issues) - len(selected_issues)
            break

        compact_iss = {
            "id": iss.get("id"),
            "status": iss.get("status"),
            "source": iss.get("source"),
            "title": (iss.get("title") or "")[:150],
            "severity": iss.get("severity"),
            "occurrences": iss.get("occurrences", 1),
        }
        iss_json_len = len(json.dumps(compact_iss))
        if current_chars + iss_json_len > max_total_chars:
            truncated = True
            omitted_count = len(sorted_issues) - len(selected_issues)
            break
        selected_issues.append(compact_iss)
        current_chars += iss_json_len

    context = {
        "prior_run_id": prior_id,
        "prior_phase": prior_state.get("phase"),
        "prior_root_objective_class": prior_ledger.get("root_objective_class"),
        "ledger_summary": prior_ledger.get("summary", {}),
        "total_issues_recorded": len(raw_issues),
        "selected_issues": selected_issues,
        "truncated": truncated,
        "omitted_issues_count": omitted_count,
        "truncation_notice": (
            f"Truncated: {omitted_count} issue(s) omitted due to context length limits."
            if truncated
            else None
        ),
        "safety_boundary_note": (
            "Historical context only. Do not interpret prior issues as permission to expand allowed_files or redesign architecture."
        ),
    }
    return context


class FactoryError(RuntimeError):
    """Expected factory failure with a stable category."""

    def __init__(self, message: str, category: str = "failed") -> None:
        super().__init__(message)
        self.category = category


class ReplanRequested(FactoryError):
    """A verified strategic trigger that must return control to Astra."""

    def __init__(self, reason: dict[str, Any]) -> None:
        super().__init__(f"exceptional replan requested: {reason['code']}", "replan")
        self.reason = reason


REPLAN_REASON_CODES = {
    "ASSUMPTION_DISPROVED",
    "REQUIRED_GAP_UNCOVERED",
    "ARCHITECTURE_DEPENDENCY_CONFLICT",
    "PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE",
    "USER_OBJECTIVE_OR_SCOPE_CHANGE",
}
REPLAN_REASON_KINDS = {
    "ASSUMPTION_DISPROVED": "assumption",
    "REQUIRED_GAP_UNCOVERED": "gap",
    "ARCHITECTURE_DEPENDENCY_CONFLICT": "dependency_conflict",
    "PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE": "completion_gap",
    "USER_OBJECTIVE_OR_SCOPE_CHANGE": "user_change",
}


def _python_node_span(source: str, node: ast.AST) -> tuple[int, int]:
    """Return UTF-8 byte offsets for one AST node, including decorators."""
    if (
        not isinstance(getattr(node, "lineno", None), int)
        or not isinstance(getattr(node, "end_lineno", None), int)
        or not isinstance(getattr(node, "col_offset", None), int)
        or not isinstance(getattr(node, "end_col_offset", None), int)
    ):
        raise FactoryError("Python symbol has no complete source span", "navigation")
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    decorators = getattr(node, "decorator_list", []) or []
    start_line = min(
        [node.lineno, *[item.lineno for item in decorators if isinstance(item.lineno, int)]]
    )
    start_col = node.col_offset
    if decorators and start_line != node.lineno:
        start_col = min(item.col_offset for item in decorators)
    if start_line < 1 or node.end_lineno > len(lines):
        raise FactoryError("Python symbol source span is outside the file", "navigation")
    # Start at the physical line boundary so class-method indentation remains
    # part of the hash-bound block and can be reused without re-indenting code
    # or changing multiline string contents.
    start = offsets[start_line - 1]
    end = offsets[node.end_lineno - 1] + node.end_col_offset
    if end <= start:
        raise FactoryError("Python symbol source span is empty", "navigation")
    return start, end


def _python_symbol_entries(source: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise FactoryError(f"Python source cannot be localized: {exc}", "navigation") from exc
    entries: list[dict[str, Any]] = []

    def add(node: ast.AST, qualified: str, node_kind: str, parent_class: str | None) -> None:
        start, end = _python_node_span(source, node)
        entries.append(
            {
                "qualified_symbol": qualified,
                "symbol": qualified.rsplit(".", 1)[-1],
                "node_kind": node_kind,
                "parent_class": parent_class,
                "node_col_offset": node.col_offset,
                "start_line": min(
                    [node.lineno, *[item.lineno for item in getattr(node, "decorator_list", [])]]
                ),
                "end_line": node.end_lineno,
                "start_byte": start,
                "end_byte": end,
                "old_block": source.encode("utf-8")[start:end].decode("utf-8"),
            }
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(
                node,
                node.name,
                "AsyncFunctionDef" if isinstance(node, ast.AsyncFunctionDef) else "FunctionDef",
                None,
            )
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(
                        child,
                        f"{node.name}.{child.name}",
                        "AsyncFunctionDef" if isinstance(child, ast.AsyncFunctionDef) else "FunctionDef",
                        node.name,
                    )
    return entries


def locate_python_symbol(
    source: str,
    *,
    symbol: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    """Resolve exactly one supported Python symbol from deterministic hints."""
    if not isinstance(source, str) or "\x00" in source:
        raise FactoryError("Python localization source is invalid", "navigation")
    if symbol is not None:
        symbol = symbol.strip().strip("`").removesuffix("()")
        if symbol.startswith("def "):
            symbol = symbol[4:].strip()
    if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
        raise FactoryError("Python localization line is invalid", "navigation")
    entries = _python_symbol_entries(source)
    candidates = entries
    if symbol:
        exact_qualified = [item for item in candidates if item["qualified_symbol"] == symbol]
        exact_name = [item for item in candidates if item["symbol"] == symbol]
        candidates = exact_qualified or exact_name
    if line is not None:
        candidates = [
            item for item in candidates if item["start_line"] <= line <= item["end_line"]
        ]
    if len(candidates) != 1:
        hint = symbol or (f"line {line}" if line is not None else "no hint")
        raise FactoryError(
            f"Python symbol localization is not unique for {hint}: {len(candidates)} matches",
            "navigation",
        )
    return candidates[0]


def create_python_capsule(
    source: str,
    *,
    source_path: str,
    base_commit: str,
    candidate_baseline_sha256: str,
    task_id: str,
    attempt: int,
    symbol: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    located = locate_python_symbol(source, symbol=symbol, line=line)
    source_bytes = source.encode("utf-8")
    block = source_bytes[located["start_byte"] : located["end_byte"]].decode("utf-8")
    parent_class = located["parent_class"]
    capsule_source = (
        f"class {parent_class}:\n{block}\n" if parent_class else f"{block}\n"
    )
    capsule = {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "task_id": task_id,
        "attempt": attempt,
        "strategy": "python_symbol_capsule",
        "base_commit": base_commit,
        "candidate_baseline_sha256": candidate_baseline_sha256,
        "source_path": str(source_path).replace("\\", "/"),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "qualified_symbol": located["qualified_symbol"],
        "node_kind": located["node_kind"],
        "parent_class": parent_class,
        "node_col_offset": located["node_col_offset"],
        "start_byte": located["start_byte"],
        "end_byte": located["end_byte"],
        "old_block_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
        "editable_file": CAPSULE_EDITABLE_FILE,
        "capsule_source": capsule_source,
    }
    capsule["editable_input_sha256"] = hashlib.sha256(
        capsule_source.encode("utf-8")
    ).hexdigest()
    return capsule


def validate_python_capsule_output(capsule: dict[str, Any], output: str) -> str:
    """Validate one synthetic capsule and return its edited source block."""
    if not isinstance(capsule, dict) or not isinstance(output, str) or "\x00" in output:
        raise FactoryError("Python capsule output is invalid", "navigation")
    try:
        tree = ast.parse(output)
    except SyntaxError as exc:
        raise FactoryError(f"Python capsule output is not valid syntax: {exc}", "navigation") from exc
    parent_class = capsule.get("parent_class")
    expected_name = str(capsule.get("qualified_symbol", "")).rsplit(".", 1)[-1]
    expected_kind = capsule.get("node_kind")
    expected_col = capsule.get("node_col_offset")
    if parent_class:
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.ClassDef):
            raise FactoryError("Python capsule must contain exactly one wrapper class", "navigation")
        wrapper = tree.body[0]
        if wrapper.name != parent_class or len(wrapper.body) != 1:
            raise FactoryError("Python capsule wrapper identity is invalid", "navigation")
        node = wrapper.body[0]
    else:
        if len(tree.body) != 1 or not isinstance(
            tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            raise FactoryError("Python capsule must contain exactly one function", "navigation")
        node = tree.body[0]
    actual_kind = "AsyncFunctionDef" if isinstance(node, ast.AsyncFunctionDef) else "FunctionDef"
    if node.name != expected_name or actual_kind != expected_kind or node.col_offset != expected_col:
        raise FactoryError("Python capsule symbol identity changed", "navigation")
    start, end = _python_node_span(output, node)
    return output.encode("utf-8")[start:end].decode("utf-8")


def reintegrate_python_capsule(capsule: dict[str, Any], source: str, output: str) -> str:
    """Replace only the hash-bound source range in the real file."""
    source_bytes = source.encode("utf-8")
    if hashlib.sha256(source_bytes).hexdigest() != capsule.get("source_sha256"):
        raise FactoryError("Python capsule source hash is stale", "navigation")
    start = capsule.get("start_byte")
    end = capsule.get("end_byte")
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end <= start
        or end > len(source_bytes)
    ):
        raise FactoryError("Python capsule source range is invalid", "navigation")
    old_block = source_bytes[start:end]
    if hashlib.sha256(old_block).hexdigest() != capsule.get("old_block_sha256"):
        raise FactoryError("Python capsule old block hash is stale", "navigation")
    edited_block = validate_python_capsule_output(capsule, output)
    new_bytes = source_bytes[:start] + edited_block.encode("utf-8") + source_bytes[end:]
    try:
        return new_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FactoryError("Python capsule reintegration produced invalid UTF-8", "navigation") from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _run_state_lock(run_dir: Path) -> Iterable[None]:
    """Hold a non-blocking OS lock for one state-mutating run operation."""
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = run_dir / "run.lock"
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise FactoryError(f"run is already locked: {run_dir.name}", "state") from exc
        try:
            yield
        finally:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_run_state(run_dir: Path) -> dict[str, Any]:
    """Read a run snapshot without constructing executable configuration."""
    state_path = run_dir / "run_state.json"
    if not state_path.is_file():
        raise FactoryError(f"run missing run_state.json: {run_dir}", "input")
    try:
        state = read_json(state_path)
    except Exception as exc:
        raise FactoryError(f"run has invalid run_state.json: {exc}", "state") from exc
    if not isinstance(state, dict):
        raise FactoryError("run state must be a JSON object", "state")
    return state


def load_config_for_execution(state: dict[str, Any]) -> Config:
    """Load only a current, explicitly versioned execution configuration."""
    if not isinstance(state, dict):
        raise FactoryError("run state must be a JSON object", "state")
    state_schema = state.get("schema_version")
    if state_schema in {1, 2}:
        raise FactoryError(
            "legacy or unknown run configuration; create a new AGY run instead of resuming",
            "state",
        )
    if state_schema != SCHEMA_VERSION:
        raise FactoryError(
            f"unsupported run state schema_version; expected {SCHEMA_VERSION}, got {state_schema}",
            "state",
        )
    if state.get("run_config_version") != RUN_CONFIG_VERSION:
        raise FactoryError(
            "legacy or unknown run configuration; create a new AGY run instead of resuming",
            "state",
        )
    if state.get("builder_backend") != "agy":
        raise FactoryError("run is not an AGY backend state", "state")
    if state.get("builder_contract_version") != BUILDER_CONTRACT_VERSION:
        raise FactoryError("unsupported Builder contract version", "state")
    raw_config = state.get("config")
    if not isinstance(raw_config, dict):
        raise FactoryError("run state is missing executable config", "state")
    raw_config = dict(raw_config)
    # Runs created by the approved release predate navigation recovery and
    # retain their original behavior when resumed.
    raw_config.setdefault("agy_navigation_recovery", "off")
    config_fields = {item.name for item in fields(Config)}
    unknown = sorted(set(raw_config) - config_fields)
    if unknown:
        raise FactoryError(
            f"run config contains unknown active keys: {unknown}",
            "state",
        )
    try:
        return Config(**raw_config)
    except TypeError as exc:
        raise FactoryError(f"run config cannot be loaded: {exc}", "state") from exc


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)


def command(
    argv: list[str] | str,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    shell: bool = False,
    stdin: str | bytes | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        input_data = stdin
        if isinstance(input_data, bytes):
            input_data = input_data.decode("utf-8", errors="replace")
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            input=input_data,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            shell=shell,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FactoryError(f"command timed out after {timeout}s: {argv}") from exc
    except OSError as exc:
        raise FactoryError(f"could not execute {argv}: {exc}") from exc


class BuilderProcessError(FactoryError):
    """Fail-closed Builder process error with retained evidence locations."""

    def __init__(
        self,
        message: str,
        *,
        stdout_path: Path,
        stderr_path: Path,
        returncode: int | None = None,
        failure_code: str | None = None,
        secondary_failure_code: str | None = None,
        secondary_failure: str | None = None,
    ) -> None:
        super().__init__(message, "builder")
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self.returncode = returncode
        self.failure_code = failure_code
        self.secondary_failure_code = secondary_failure_code
        self.secondary_failure = secondary_failure


class BuilderFailure(FactoryError):
    """Structured, non-resumable AGY Builder failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        non_resumable: bool,
        evidence_path: str | None = None,
    ) -> None:
        super().__init__(message, "builder")
        self.code = code
        self.non_resumable = non_resumable
        self.evidence_path = evidence_path


class _BoundedByteCapture:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data = bytearray()
        self.overflow = False

    def append(self, chunk: bytes) -> None:
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])
        if len(chunk) > max(remaining, 0):
            self.overflow = True


def _builder_process_paths(stdout_path: Path, stderr_path: Path) -> tuple[Path, Path]:
    stdout_target = Path(stdout_path).expanduser()
    stderr_target = Path(stderr_path).expanduser()
    if stdout_target == stderr_target:
        raise FactoryError("Builder stdout and stderr evidence paths must differ", "builder")
    return stdout_target, stderr_target


def _validate_builder_process_inputs(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int | float,
    max_output_bytes: int,
    cancel_event: threading.Event | None,
) -> tuple[list[str], Path, dict[str, str], float, int]:
    if not isinstance(argv, list) or not argv:
        raise FactoryError("Builder argv must be a non-empty argument list", "builder")
    if any(not isinstance(item, str) for item in argv):
        raise FactoryError("Builder argv must contain only strings", "builder")
    if any("\x00" in item for item in argv):
        raise FactoryError("Builder argv contains a NUL byte", "builder")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise FactoryError("Builder timeout must be a positive finite number", "builder")
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise FactoryError("Builder output limit must be a positive integer", "builder")
    if cancel_event is not None and not hasattr(cancel_event, "is_set"):
        raise FactoryError("Builder cancellation object must expose is_set()", "builder")
    if not isinstance(env, dict):
        raise FactoryError("Builder environment must be a string mapping", "builder")
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or "\x00" in key
        or "\x00" in value
        for key, value in env.items()
    ):
        raise FactoryError("Builder environment contains an invalid string", "builder")
    try:
        cwd_target = Path(cwd).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FactoryError("Builder cwd is unavailable", "builder") from exc
    if not cwd_target.is_dir():
        raise FactoryError("Builder cwd is not a directory", "builder")

    argv_copy = list(argv)
    if os.name == "nt":
        try:
            serialized_units = len(subprocess.list2cmdline(argv_copy).encode("utf-16-le")) // 2
        except (OSError, UnicodeError) as exc:
            raise FactoryError("Builder command line cannot be serialized safely", "builder") from exc
        if serialized_units > BUILDER_WINDOWS_COMMAND_LINE_LIMIT_UNITS:
            raise FactoryError("Builder command line exceeds the conservative Windows limit", "builder")
    return argv_copy, cwd_target, dict(env), float(timeout), max_output_bytes


def _write_builder_evidence(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class _WindowsBuilderJob:
    """Windows Job Object assigned before the suspended process is resumed."""

    _KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _CREATE_SUSPENDED = 0x00000004

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        self._kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            wintypes.INT,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.QueryInformationJobObject.argtypes = [
            ctypes.c_void_p,
            wintypes.INT,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, wintypes.UINT]
        self._kernel32.TerminateJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        self._handle = handle
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
            self._handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "SetInformationJobObject failed")

        self._ntdll = ctypes.WinDLL("ntdll")
        self._ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
        self._ntdll.NtResumeProcess.restype = ctypes.c_long

        class BasicAccountingInformation(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._basic_accounting_information = BasicAccountingInformation

    def _handle_value(self, value: Any) -> Any:
        if isinstance(value, self._ctypes.c_void_p):
            return value
        return self._ctypes.c_void_p(int(value))

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        process_handle = getattr(process, "_handle", None)
        if process_handle is None or not self._kernel32.AssignProcessToJobObject(
            self._handle,
            self._handle_value(process_handle),
        ):
            raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def resume(self, process: subprocess.Popen[bytes]) -> None:
        process_handle = getattr(process, "_handle", None)
        if process_handle is None:
            raise OSError("suspended process handle is unavailable")
        status = self._ntdll.NtResumeProcess(self._handle_value(process_handle))
        if status != 0:
            raise OSError(f"NtResumeProcess failed with status {status:#x}")

    def terminate(self) -> None:
        if getattr(self, "_handle", None):
            self._kernel32.TerminateJobObject(self._handle, 1)

    def active_processes(self) -> int:
        handle = getattr(self, "_handle", None)
        if not handle:
            return 0
        info = self._basic_accounting_information()
        returned = self._ctypes.c_ulong(0)
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            1,
            self._ctypes.byref(info),
            self._ctypes.sizeof(info),
            self._ctypes.byref(returned),
        ):
            raise OSError(self._ctypes.get_last_error(), "QueryInformationJobObject failed")
        return int(info.ActiveProcesses)

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._kernel32.CloseHandle(handle)
            self._handle = None


def _terminate_builder_process(
    process: subprocess.Popen[bytes],
    job: _WindowsBuilderJob | None,
    timeout: float,
    *,
    process_group_id: int | None = None,
) -> bool:
    """Stop and prove quiescence of the owned process boundary."""

    def signal_boundary(force: bool) -> None:
        if job is not None:
            job.terminate()
            return
        if process_group_id is not None and os.name != "nt":
            os.killpg(process_group_id, signal.SIGKILL if force else signal.SIGTERM)
            return
        if os.name == "nt":
            (process.kill if force else process.terminate)()
            return
        (process.kill if force else process.terminate)()

    def group_exists() -> bool:
        if process_group_id is None or os.name == "nt":
            return False
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH
        return True

    def quiescent() -> bool:
        if process.poll() is None:
            return False
        if job is not None:
            try:
                return job.active_processes() == 0
            except OSError:
                return False
        return not group_exists()

    def wait_for_quiescence(wait_seconds: float) -> bool:
        deadline = time.monotonic() + max(wait_seconds, 0.1)
        while time.monotonic() < deadline:
            try:
                process.wait(timeout=min(0.1, max(deadline - time.monotonic(), 0.01)))
            except subprocess.TimeoutExpired:
                pass
            if quiescent():
                return True
            time.sleep(0.02)
        return quiescent()

    try:
        signal_boundary(False)
    except (OSError, ProcessLookupError):
        pass
    if wait_for_quiescence(timeout):
        return True
    try:
        signal_boundary(True)
    except (OSError, ProcessLookupError):
        pass
    return wait_for_quiescence(timeout)


def _builder_reader(
    stream: Any,
    capture: _BoundedByteCapture,
    errors: list[BaseException],
    signal_event: threading.Event,
) -> None:
    try:
        while True:
            chunk = stream.read(BUILDER_PIPE_READ_CHUNK_BYTES)
            if not chunk:
                break
            capture.append(chunk)
            if capture.overflow:
                signal_event.set()
    except BaseException as exc:
        errors.append(exc)
        signal_event.set()
    finally:
        try:
            stream.close()
        except OSError:
            pass


def run_builder_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    stdout_path: Path,
    stderr_path: Path,
    cancel_event: threading.Event | None = None,
    max_output_bytes: int = BUILDER_OUTPUT_LIMIT_BYTES,
    completion_probe: Callable[[], bool] | None = None,
    progress_probe: Callable[[], None] | None = None,
    external_cleanup: Callable[[int], None] | None = None,
    use_windows_job: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one Builder process with bounded, identity-preserving supervision.

    The returned stdout/stderr are strict UTF-8 decodes of the same bounded raw
    bytes written to the evidence paths. Timeout, cancellation, spawn failure,
    malformed UTF-8, output overflow, or writer non-quiescence raise
    ``BuilderProcessError`` after the process tree and pipe readers are stopped.
    ``timeout`` is the outer watchdog; callers must put the AGY CLI's own
    ``--print-timeout`` inside ``argv`` with a shutdown margin below this value.
    """
    stdout_target, stderr_target = _builder_process_paths(stdout_path, stderr_path)
    validated_argv, cwd_target, validated_env, timeout_value, output_limit = _validate_builder_process_inputs(
        argv,
        cwd=cwd,
        env=env,
        timeout=timeout,
        max_output_bytes=max_output_bytes,
        cancel_event=cancel_event,
    )
    if completion_probe is not None and not callable(completion_probe):
        raise FactoryError("Builder completion probe must be callable", "builder")
    if progress_probe is not None and not callable(progress_probe):
        raise FactoryError("Builder progress probe must be callable", "builder")
    if external_cleanup is not None and not callable(external_cleanup):
        raise FactoryError("Builder external cleanup callback must be callable", "builder")
    if not isinstance(use_windows_job, bool):
        raise FactoryError("Builder Windows job-boundary option must be boolean", "builder")
    if not isinstance(capture_output, bool):
        raise FactoryError("Builder output-capture option must be boolean", "builder")
    try:
        _write_builder_evidence(stdout_target, b"")
        _write_builder_evidence(stderr_target, b"")
    except OSError as exc:
        raise BuilderProcessError(
            "Builder process evidence files could not be initialized",
            stdout_path=stdout_target,
            stderr_path=stderr_target,
            failure_code="agy_runtime_error",
        ) from exc

    stdout_capture = _BoundedByteCapture(output_limit)
    stderr_capture = _BoundedByteCapture(output_limit)
    reader_errors: list[BaseException] = []
    reader_signal = threading.Event()
    process: subprocess.Popen[bytes] | None = None
    job: _WindowsBuilderJob | None = None
    job_assigned = False
    process_group_id: int | None = None
    readers: list[threading.Thread] = []
    failure: str | None = None
    failure_code: str | None = None
    secondary_failure_code: str | None = None
    secondary_failure: str | None = None

    def mark_boundary_failure(message: str) -> None:
        nonlocal failure, failure_code, secondary_failure_code, secondary_failure
        if failure_code and failure_code != "agy_isolation_failed":
            secondary_failure_code = failure_code
            secondary_failure = message
        failure = failure or message
        failure_code = "agy_isolation_failed"

    try:
        if os.name == "nt" and use_windows_job:
            try:
                job = _WindowsBuilderJob()
            except Exception as exc:
                failure = "could not create the Windows Builder process boundary"
                raise BuilderProcessError(
                    failure,
                    stdout_path=stdout_target,
                    stderr_path=stderr_target,
                    failure_code="agy_isolation_failed",
                ) from exc

        popen_kwargs: dict[str, Any] = {
            "cwd": str(cwd_target),
            "env": validated_env,
            "stdin": subprocess.DEVNULL if (external_cleanup is not None and not capture_output) else subprocess.PIPE,
            "stdout": subprocess.PIPE if capture_output else subprocess.DEVNULL,
            "stderr": subprocess.PIPE if capture_output else subprocess.DEVNULL,
            "shell": False,
            "text": False,
            "close_fds": True,
        }
        if os.name == "nt":
            if use_windows_job:
                popen_kwargs["creationflags"] = (
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                    | _WindowsBuilderJob._CREATE_SUSPENDED
                )
        else:
            popen_kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(validated_argv, **popen_kwargs)
        except Exception as exc:
            failure = "could not spawn the Builder process; empty evidence was retained"
            raise BuilderProcessError(
                failure,
                stdout_path=stdout_target,
                stderr_path=stderr_target,
                failure_code="agy_spawn_failed",
            ) from exc

        if os.name != "nt":
            try:
                process_group_id = os.getpgid(process.pid)
            except (OSError, ProcessLookupError) as exc:
                failure = "could not retain the Builder process-group boundary"
                raise BuilderProcessError(
                    failure,
                    stdout_path=stdout_target,
                    stderr_path=stderr_target,
                    failure_code="agy_isolation_failed",
                ) from exc

        if job is not None:
            try:
                job.assign(process)
                job_assigned = True
            except Exception as exc:
                failure = "could not assign the Builder process to its Windows boundary"
                raise BuilderProcessError(
                    failure,
                    stdout_path=stdout_target,
                    stderr_path=stderr_target,
                    failure_code="agy_isolation_failed",
                ) from exc

        if capture_output and (process.stdout is None or process.stderr is None):
            failure = "Builder process pipes were not created"
            raise BuilderProcessError(
                failure,
                stdout_path=stdout_target,
                stderr_path=stderr_target,
                failure_code="agy_output_incomplete",
            )
        readers = []
        if capture_output:
            readers = [
                threading.Thread(
                    target=_builder_reader,
                    args=(process.stdout, stdout_capture, reader_errors, reader_signal),
                    name="builder-stdout-drain",
                    daemon=True,
                ),
                threading.Thread(
                    target=_builder_reader,
                    args=(process.stderr, stderr_capture, reader_errors, reader_signal),
                    name="builder-stderr-drain",
                    daemon=True,
                ),
            ]
        for reader in readers:
            reader.start()
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if job is not None:
            try:
                job.resume(process)
            except Exception as exc:
                failure = "could not resume the supervised Builder process"
                raise BuilderProcessError(
                    failure,
                    stdout_path=stdout_target,
                    stderr_path=stderr_target,
                    failure_code="agy_isolation_failed",
                ) from exc

        deadline = time.monotonic() + timeout_value
        while process.poll() is None:
            if progress_probe is not None:
                try:
                    progress_probe()
                except Exception:
                    failure = "Builder progress evidence probe failed"
                    failure_code = "agy_output_incomplete"
                    break
            if completion_probe is not None:
                try:
                    if completion_probe():
                        break
                except Exception:
                    failure = "Builder completion evidence probe failed"
                    failure_code = "agy_output_incomplete"
                    break
            if cancel_event is not None and cancel_event.is_set():
                failure = "Builder process cancelled; partial evidence was retained"
                failure_code = "agy_canceled"
                break
            if stdout_capture.overflow or stderr_capture.overflow:
                failure = "Builder process output exceeded the bounded evidence limit"
                failure_code = "agy_output_incomplete"
                break
            if reader_errors:
                failure = "Builder process output reader failed; partial evidence was retained"
                failure_code = "agy_output_incomplete"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "Builder process timed out; partial evidence was retained"
                failure_code = "agy_timeout"
                break
            time.sleep(min(0.05, remaining))
    except BuilderProcessError as exc:
        failure_code = failure_code or exc.failure_code
        secondary_failure_code = secondary_failure_code or exc.secondary_failure_code
        secondary_failure = secondary_failure or exc.secondary_failure
    except Exception:
        failure = failure or "Builder process supervision failed; partial evidence was retained"
        failure_code = failure_code or "agy_runtime_error"
    finally:
        if process is not None:
            if external_cleanup is not None:
                try:
                    # Some Windows host wrappers (notably Windows Sandbox)
                    # create a client process that is not a Job Object child.
                    # Tear it down while the owning wrapper PID is still
                    # identifiable, then repeat after wrapper termination.
                    external_cleanup(process.pid)
                except Exception:
                    mark_boundary_failure("external Builder boundary cleanup failed")
            owned_job = job if job_assigned else None
            if not _terminate_builder_process(
                process,
                owned_job,
                BUILDER_SHUTDOWN_TIMEOUT_SECONDS,
                process_group_id=process_group_id,
            ):
                mark_boundary_failure("Builder process boundary did not become quiescent")

            for reader in readers:
                reader.join(timeout=BUILDER_SHUTDOWN_TIMEOUT_SECONDS)
            if any(reader.is_alive() for reader in readers):
                mark_boundary_failure("Builder output writer did not terminate")
                if not _terminate_builder_process(
                    process,
                    owned_job,
                    BUILDER_SHUTDOWN_TIMEOUT_SECONDS,
                    process_group_id=process_group_id,
                    ):
                        mark_boundary_failure("Builder output writer boundary did not become quiescent")
            if job is not None:
                try:
                    if job_assigned and job.active_processes() != 0:
                        mark_boundary_failure("Windows Builder Job Object still owns active processes")
                    job.close()
                except Exception:
                    mark_boundary_failure("Windows Builder boundary could not be closed")
            for reader in readers:
                reader.join(timeout=BUILDER_SHUTDOWN_TIMEOUT_SECONDS)
            if any(reader.is_alive() for reader in readers):
                mark_boundary_failure("Builder output writer remained active after shutdown")
            if external_cleanup is not None:
                try:
                    external_cleanup(process.pid)
                except Exception:
                    mark_boundary_failure("external Builder boundary cleanup failed")
        elif job is not None:
            try:
                job.close()
            except Exception:
                mark_boundary_failure("Windows Builder boundary could not be closed")

    if progress_probe is not None:
        try:
            progress_probe()
        except Exception:
            failure = failure or "Builder final progress evidence probe failed"
            failure_code = failure_code or "agy_output_incomplete"

    stdout_bytes = bytes(stdout_capture.data)
    stderr_bytes = bytes(stderr_capture.data)
    try:
        _write_builder_evidence(stdout_target, stdout_bytes)
        _write_builder_evidence(stderr_target, stderr_bytes)
    except OSError as exc:
        raise BuilderProcessError(
            "Builder partial evidence could not be persisted",
            stdout_path=stdout_target,
            stderr_path=stderr_target,
            returncode=process.returncode if process is not None else None,
            failure_code="agy_runtime_error",
        ) from exc

    if stdout_capture.overflow or stderr_capture.overflow:
        failure = failure or "Builder process output exceeded the bounded evidence limit"
        if failure_code == "agy_isolation_failed":
            secondary_failure_code = secondary_failure_code or "agy_output_incomplete"
            secondary_failure = secondary_failure or "Builder process output exceeded the bounded evidence limit"
        else:
            failure_code = failure_code or "agy_output_incomplete"
    if reader_errors:
        failure = failure or "Builder process output reader failed; partial evidence was retained"
        if failure_code == "agy_isolation_failed":
            secondary_failure_code = secondary_failure_code or "agy_output_incomplete"
            secondary_failure = secondary_failure or "Builder process output reader failed; partial evidence was retained"
        else:
            failure_code = failure_code or "agy_output_incomplete"
    if failure is not None:
        raise BuilderProcessError(
            failure,
            stdout_path=stdout_target,
            stderr_path=stderr_target,
            returncode=process.returncode if process is not None else None,
            failure_code=failure_code or "agy_runtime_error",
            secondary_failure_code=secondary_failure_code,
            secondary_failure=secondary_failure,
        )

    try:
        stdout_text = stdout_bytes.decode("utf-8")
        stderr_text = stderr_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BuilderProcessError(
            "Builder process emitted malformed UTF-8; raw evidence was retained",
            stdout_path=stdout_target,
            stderr_path=stderr_target,
            returncode=process.returncode if process is not None else None,
            failure_code="agy_output_incomplete",
        ) from exc
    return subprocess.CompletedProcess(
        validated_argv,
        process.returncode if process is not None else -1,
        stdout_text,
        stderr_text,
    )


AGY_EVENT_STREAM_MAX_BYTES = 8 * 1024 * 1024
AGY_EVENT_RECORD_MAX_BYTES = 512 * 1024


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _protocol_failure(message: str, code: str = "agy_protocol_error") -> BuilderFailure:
    return BuilderFailure(message, code=code, non_resumable=True)


def _normalized_agy_outcome(code: str) -> str:
    return {
        "agy_timeout": "TIMEOUT",
        "agy_token_budget_exhausted": "TOKEN_BUDGET_EXHAUSTED",
        "agy_rate_limit": "RATE_LIMIT",
        "agy_provider_quota": "PROVIDER_QUOTA",
        "agy_protocol_error": "PROTOCOL_ERROR",
        "agy_output_incomplete": "PROTOCOL_ERROR",
        "agy_canceled": "CANCELLED",
        "agy_spawn_failed": "PROCESS_ERROR",
        "agy_runtime_error": "PROCESS_ERROR",
        "agy_model_mismatch": "PROTOCOL_ERROR",
        "agy_identity_changed": "PROCESS_ERROR",
        "agy_isolation_failed": "PROCESS_ERROR",
    }.get(code, "PROCESS_ERROR")


def _agy_terminal_error(raw: bytes) -> str | None:
    """Extract only an explicit terminal error for diagnostic classification."""
    if not isinstance(raw, (bytes, bytearray)):
        return None
    for line in bytes(raw).splitlines():
        try:
            event = json.loads(
                line.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(event, dict) or event.get("event") != "result":
            continue
        result = event.get("result")
        if isinstance(result, dict) and isinstance(result.get("error"), str):
            return result["error"]
    return None


def _classify_agy_diagnostic(*evidence: Any) -> str | None:
    """Classify explicit AGY/provider failure evidence before generic fallback."""
    diagnostic = "\n".join(
        value for value in evidence if isinstance(value, str) and value.strip()
    ).casefold()
    if any(marker in diagnostic for marker in ("token budget", "context window", "turn limit")):
        return "agy_token_budget_exhausted"
    if re.search(r"\b429\b", diagnostic) or re.search(r"rate[\s_-]+limit", diagnostic):
        return "agy_rate_limit"
    if "resource_exhausted" in diagnostic and re.search(r"\b(?:rate|limit)\b", diagnostic):
        return "agy_rate_limit"
    if "quota" in diagnostic:
        return "agy_provider_quota"
    if re.search(r"timeout|timed out", diagnostic):
        return "agy_timeout"
    return None


def _agy_conversation_ids(raw: bytes) -> list[str]:
    """Extract every valid init identity seen before full protocol validation."""
    identities: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(
                line.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            break
        if isinstance(event, dict) and event.get("event") == "init":
            value = event.get("conversation_id")
            if isinstance(value, str) and value:
                identities.append(value)
    return identities


def parse_agy_event_stream(raw: bytes) -> dict[str, Any]:
    """Parse one bounded AGY stream-json response as an untrusted protocol."""
    if not isinstance(raw, (bytes, bytearray)):
        raise _protocol_failure("AGY event stream must be raw bytes")
    raw_bytes = bytes(raw)
    if not raw_bytes:
        raise _protocol_failure("AGY event stream is empty", "agy_output_incomplete")
    if len(raw_bytes) > AGY_EVENT_STREAM_MAX_BYTES:
        raise _protocol_failure("AGY event stream exceeds the bounded record budget", "agy_output_incomplete")
    if b"\x00" in raw_bytes:
        raise _protocol_failure("AGY event stream contains NUL", "agy_protocol_error")

    events: list[dict[str, Any]] = []
    for line in raw_bytes.splitlines():
        if not line.strip():
            raise _protocol_failure("AGY event stream contains a blank record", "agy_output_incomplete")
        if len(line) > AGY_EVENT_RECORD_MAX_BYTES:
            raise _protocol_failure("AGY event record exceeds the bounded size", "agy_output_incomplete")
        try:
            event = json.loads(
                line.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise _protocol_failure("AGY event stream contains malformed JSON", "agy_protocol_error") from exc
        if not isinstance(event, dict) or not isinstance(event.get("event"), str):
            raise _protocol_failure("AGY event record has an invalid shape")
        events.append(event)
    if not events:
        raise _protocol_failure("AGY event stream has no records", "agy_output_incomplete")

    init_events = [event for event in events if event.get("event") == "init"]
    result_events = [event for event in events if event.get("event") == "result"]
    if len(init_events) != 1:
        raise _protocol_failure("AGY event stream must contain exactly one init event")
    if len(result_events) != 1:
        raise _protocol_failure(
            "AGY event stream must contain exactly one terminal result",
            "agy_output_incomplete" if not result_events else "agy_protocol_error",
        )
    if events[0].get("event") != "init":
        raise _protocol_failure("AGY event stream must begin with init")
    if events[-1].get("event") != "result":
        raise _protocol_failure("AGY event stream result must be final", "agy_output_incomplete")
    if any(event.get("event") not in {"init", "step_update", "result"} for event in events):
        raise _protocol_failure("AGY event stream contains an unsupported event")
    if not any(event.get("event") == "step_update" for event in events[1:-1]):
        raise _protocol_failure("AGY event stream is missing a step update", "agy_output_incomplete")

    init_event = init_events[0]
    conversation_id = init_event.get("conversation_id")
    init = init_event.get("init")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise _protocol_failure("AGY init is missing a conversation identity")
    if not isinstance(init, dict):
        raise _protocol_failure("AGY init payload is missing")
    model = init.get("model")
    cwd = init.get("cwd")
    tools = init.get("tools")
    permission_mode = init.get("permission_mode")
    if not isinstance(model, str) or not model:
        raise _protocol_failure("AGY init has no model")
    if not isinstance(cwd, str) or not cwd:
        raise _protocol_failure("AGY init has no effective cwd")
    if (
        not isinstance(tools, list)
        or not tools
        or any(not isinstance(tool, str) or not tool for tool in tools)
    ):
        raise _protocol_failure("AGY init has invalid capability metadata")
    if permission_mode != AGY_REQUIRED_PERMISSION_MODE:
        raise _protocol_failure("AGY init has an unexpected permission mode")

    for event in events[1:-1]:
        update = event.get("step_update")
        if event.get("event") != "step_update" or not isinstance(update, dict):
            raise _protocol_failure("AGY event stream has an invalid intermediate record")
        if update.get("conversation_id") != conversation_id:
            raise _protocol_failure("AGY event stream has inconsistent conversation identity")
        step_index = update.get("step_index")
        if (
            isinstance(step_index, bool)
            or not isinstance(step_index, (int, float))
            or not math.isfinite(step_index)
            or not isinstance(update.get("state"), str)
            or not isinstance(update.get("step_type"), str)
        ):
            raise _protocol_failure("AGY step update has invalid typed fields")

    result = result_events[0].get("result")
    if not isinstance(result, dict):
        raise _protocol_failure("AGY result payload is missing", "agy_output_incomplete")
    required_result_keys = {
        "conversation_id",
        "status",
        "response",
        "duration_seconds",
        "num_turns",
        "usage",
    }
    if not required_result_keys.issubset(result):
        raise _protocol_failure("AGY result is missing required fields", "agy_output_incomplete")
    if result.get("conversation_id") != conversation_id:
        raise _protocol_failure("AGY result has stale conversation identity")
    status = result.get("status")
    if status not in {"SUCCESS", "ERROR"}:
        raise _protocol_failure("AGY result has an unsupported terminal status")
    if not isinstance(result.get("response"), str):
        raise _protocol_failure("AGY result response is not a string")
    duration_seconds = result.get("duration_seconds")
    num_turns = result.get("num_turns")
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or not math.isfinite(duration_seconds)
        or duration_seconds < 0
        or isinstance(num_turns, bool)
        or not isinstance(num_turns, (int, float))
        or not math.isfinite(num_turns)
        or num_turns <= 0
        or not isinstance(result.get("usage"), dict)
    ):
        raise _protocol_failure("AGY result has invalid completion metadata", "agy_output_incomplete")
    if status == "ERROR":
        if not isinstance(result.get("error"), str) or not result["error"].strip():
            raise _protocol_failure("AGY error result has no error description", "agy_runtime_error")
        raise _protocol_failure("AGY terminal result reported an error", "agy_runtime_error")
    elif result.get("error"):
        raise _protocol_failure("AGY success result contains a contradictory error", "agy_protocol_error")

    return {
        "event_count": len(events),
        "event_sequence": [event["event"] for event in events],
        "conversation_id": conversation_id,
        "model": model,
        "cwd": cwd,
        "permission_mode": permission_mode,
        "tool_count": len(tools),
        "init": init,
        "result": result,
    }


def _python_definition_entries(source: str) -> list[dict[str, Any]]:
    """Return supported top-level Python definitions, including classes."""
    entries = list(_python_symbol_entries(source))
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise FactoryError(f"Python source cannot be localized: {exc}", "navigation") from exc
    source_bytes = source.encode("utf-8")
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        start, end = _python_node_span(source, node)
        block = source_bytes[start:end].decode("utf-8")
        entries.append(
            {
                "qualified_symbol": node.name,
                "symbol": node.name,
                "node_kind": "ClassDef",
                "parent_class": None,
                "node_col_offset": node.col_offset,
                "start_line": min(
                    [node.lineno, *[item.lineno for item in getattr(node, "decorator_list", [])]]
                ),
                "end_line": node.end_lineno,
                "start_byte": start,
                "end_byte": end,
                "old_block": block,
            }
        )
    return sorted(entries, key=lambda item: (item["start_byte"], item["qualified_symbol"]))


def _definition_identifier_candidates(instruction: str) -> list[str]:
    """Extract code-like identifiers without treating prose as definitions."""
    if not isinstance(instruction, str) or "\x00" in instruction:
        return []
    qualified = list(
        re.finditer(
            r"(?<![A-Za-z0-9_])(?:[A-Za-z_][A-Za-z0-9_]*\.)+[A-Za-z_][A-Za-z0-9_]*\b",
            instruction,
        )
    )
    identifiers: list[str] = [
        match.group(0)
        for match in qualified
        if not match.group(0).lower().endswith(".py")
    ]
    simple_pattern = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*\b")
    camel_pattern = re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+$")
    for match in simple_pattern.finditer(instruction):
        if any(match.start() >= item.start() and match.end() <= item.end() for item in qualified):
            continue
        token = match.group(0)
        if "_" in token or camel_pattern.fullmatch(token):
            identifiers.append(token)
    return list(dict.fromkeys(identifiers))


def discover_exact_python_definition(
    worktree: Path,
    instruction: str,
    allowed_files: list[str],
) -> dict[str, Any]:
    """Find one exact supported Python definition inside the allowed surface."""
    identifiers = _definition_identifier_candidates(instruction)
    if not identifiers or not isinstance(allowed_files, list):
        return {"status": "NOT_FOUND", "candidate": None, "candidates": [], "identifiers": identifiers}

    try:
        normalized_allowed = normalized_paths(allowed_files)
    except FactoryError:
        return {"status": "NOT_FOUND", "candidate": None, "candidates": [], "identifiers": identifiers}
    hinted_paths = [
        relative
        for relative in normalized_allowed
        if relative in instruction or PurePosixPath(relative).name in instruction
    ]
    candidate_paths = list(dict.fromkeys(hinted_paths or normalized_allowed))
    candidate_paths = [path for path in candidate_paths if path.lower().endswith(".py")]
    try:
        ensure_paths_confined(worktree, candidate_paths)
    except FactoryError:
        return {"status": "NOT_FOUND", "candidate": None, "candidates": [], "identifiers": identifiers}

    parsed_files: list[tuple[str, str, list[dict[str, Any]]]] = []
    total_bytes = 0
    for relative in candidate_paths:
        source_path = worktree / Path(relative)
        if not source_path.is_file() or source_path.is_symlink():
            continue
        try:
            source = source_path.read_text(encoding="utf-8")
            needles = [
                part
                for identifier in identifiers
                for part in (identifier.split(".") if "." in identifier else [identifier])
            ]
            if not any(needle in source for needle in needles):
                continue
            entries = _python_definition_entries(source)
        except (OSError, UnicodeError, FactoryError):
            continue
        total_bytes += len(source.encode("utf-8"))
        parsed_files.append((relative, source, entries))

    resolved: dict[tuple[str, str, str], dict[str, Any]] = {}
    saw_ambiguous_identifier = False
    for identifier in identifiers:
        matches: list[dict[str, Any]] = []
        for relative, source, entries in parsed_files:
            for entry in entries:
                matched = entry["qualified_symbol"] == identifier
                if matched:
                    candidate = {**entry, "file_path": relative, "source": source}
                    key = (relative, entry["qualified_symbol"], entry["node_kind"])
                    if all(
                        (item["file_path"], item["qualified_symbol"], item["node_kind"]) != key
                        for item in matches
                    ):
                        matches.append(candidate)
                elif "." not in identifier and entry["symbol"] == identifier:
                    candidate = {**entry, "file_path": relative, "source": source}
                    key = (relative, entry["qualified_symbol"], entry["node_kind"])
                    if all(
                        (item["file_path"], item["qualified_symbol"], item["node_kind"]) != key
                        for item in matches
                    ):
                        matches.append(candidate)
        if len(matches) > 1:
            saw_ambiguous_identifier = True
        for candidate in matches:
            key = (candidate["file_path"], candidate["qualified_symbol"], candidate["node_kind"])
            resolved[key] = candidate
    if saw_ambiguous_identifier or len(resolved) > 1:
        return {
            "status": "AMBIGUOUS",
            "candidate": None,
            "candidates": list(resolved.values()),
            "identifiers": identifiers,
            "files_scanned": len(parsed_files),
            "bytes_scanned": total_bytes,
        }
    if len(resolved) == 1:
        candidate = next(iter(resolved.values()))
        return {
            "status": "UNIQUE",
            "candidate": candidate,
            "candidates": [candidate],
            "identifiers": identifiers,
            "files_scanned": len(parsed_files),
            "bytes_scanned": total_bytes,
        }
    return {
        "status": "NOT_FOUND",
        "candidate": None,
        "candidates": [],
        "identifiers": identifiers,
        "files_scanned": len(parsed_files),
        "bytes_scanned": total_bytes,
    }


def git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    result = command(["git", *args], cwd=repo, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise FactoryError(f"git {' '.join(args)} failed: {detail}")
    return result


def _candidate_index_path(worktree: Path) -> Path:
    index_path = git(worktree, "rev-parse", "--git-path", "index").stdout.strip()
    if not index_path:
        raise FactoryError("candidate Git index path is unavailable", "hash")
    path = Path(index_path)
    if not path.is_absolute():
        path = worktree / path
    return path.resolve(strict=True)


def _candidate_index_digest(worktree: Path) -> str:
    """Return the byte identity of the candidate's current Git index."""
    try:
        return hashlib.sha256(_candidate_index_path(worktree).read_bytes()).hexdigest()
    except (OSError, RuntimeError) as exc:
        raise FactoryError("candidate Git index could not be fingerprinted", "hash") from exc


@contextmanager
def _hold_candidate_index_lock(worktree: Path) -> Iterable[None]:
    """Reserve Git's standard index lock across the final commit transaction."""
    index_path = _candidate_index_path(worktree)
    try:
        lock_path = Path(str(index_path) + ".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise FactoryError("candidate Git index is already locked", "hash") from exc
    except OSError as exc:
        raise FactoryError("candidate Git index lock could not be acquired", "hash") from exc
    try:
        os.write(fd, f"softfac exact candidate commit pid={os.getpid()}\n".encode("ascii"))
        yield
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lock_path.unlink()
        except OSError:
            pass


def _commit_exact_candidate_tree(
    worktree: Path,
    *,
    candidate_id: str,
    base_commit: str,
    message: str,
) -> str:
    """Create and publish exactly one approved tree with an old-HEAD CAS.

    The commit object is formed from the recorded tree, never from the mutable
    worktree index.  The index is fingerprinted around object creation so an
    injected or concurrent candidate mutation fails before the branch ref is
    advanced.  ``update-ref <new> <old>`` supplies the final parent CAS.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", candidate_id) or not re.fullmatch(
        r"[0-9a-f]{40}", base_commit
    ):
        raise FactoryError("exact candidate commit has an invalid tree or base", "hash")
    current_head = git(worktree, "rev-parse", "HEAD").stdout.strip()
    if current_head != base_commit:
        raise FactoryError("candidate base changed before exact commit", "hash")
    if git(worktree, "write-tree").stdout.strip() != candidate_id:
        raise FactoryError("candidate tree changed before exact commit", "hash")
    index_before = _candidate_index_digest(worktree)
    head_ref = git(worktree, "symbolic-ref", "-q", "HEAD").stdout.strip()
    if not re.fullmatch(r"refs/heads/[A-Za-z0-9._/-]+", head_ref):
        raise FactoryError("candidate HEAD is not an authorized branch ref", "hash")

    created = command(
        ["git", "commit-tree", candidate_id, "-p", base_commit, "-m", message],
        cwd=worktree,
        timeout=120,
    )
    if created.returncode != 0:
        raise FactoryError(
            f"exact candidate commit creation failed: {(created.stderr or created.stdout).strip()}",
            "git",
        )
    commit_hash = (created.stdout or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit_hash):
        raise FactoryError("exact candidate commit returned an invalid object ID", "hash")

    with _hold_candidate_index_lock(worktree):
        if (
            _candidate_index_digest(worktree) != index_before
            or git(worktree, "rev-parse", "HEAD").stdout.strip() != base_commit
        ):
            raise FactoryError(
                "candidate index or base changed before exact commit ref advance",
                "hash",
            )
        updated = command(
            ["git", "update-ref", head_ref, commit_hash, base_commit],
            cwd=worktree,
            timeout=120,
        )
        if updated.returncode != 0:
            raise FactoryError(
                f"exact candidate ref update failed: {(updated.stderr or updated.stdout).strip()}",
                "git",
            )
        if (
            _candidate_index_digest(worktree) != index_before
            or git(worktree, "rev-parse", "HEAD").stdout.strip() != commit_hash
        ):
            raise FactoryError(
                "candidate index or ref changed during exact commit publication",
                "hash",
            )
    return commit_hash


def normalize_test_command(cmd: str) -> str:
    if sys.platform == "win32":
        if cmd.startswith("python3 "):
            return f'"{sys.executable}" ' + cmd[8:]
        elif cmd == "python3":
            return f'"{sys.executable}"'
    return cmd


def normalize_path(raw: str) -> str:
    if not isinstance(raw, str):
        raise FactoryError("file paths must be strings", "contract")
    value = raw.strip().replace("\\", "/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.parts[0] == ".git":
        raise FactoryError(f"unsafe repository-relative path: {raw!r}", "contract")
    normalized = path.as_posix()
    if normalized in {".", ".git"}:
        raise FactoryError(f"unsafe repository-relative path: {raw!r}", "contract")
    return normalized


def normalized_paths(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = normalize_path(value)
        if path not in seen:
            result.append(path)
            seen.add(path)
    if not result:
        raise FactoryError("at least one allowed file is required", "contract")
    return result


def ensure_paths_confined(repo: Path, paths: Iterable[str]) -> None:
    """Reject directories and symlink traversal outside the repository."""
    root = repo.resolve()
    for relative in paths:
        candidate = repo / relative
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise FactoryError(f"allowed path escapes repository through a symlink: {relative}", "scope") from exc
        if candidate.is_symlink():
            raise FactoryError(f"allowed path may not be a symlink: {relative}", "scope")
        if candidate.exists() and candidate.is_dir():
            raise FactoryError(f"allowed path is a directory, not a file: {relative}", "scope")


def ensure_head_paths_not_symlinks(repo: Path, paths: Iterable[str]) -> None:
    """Reject files that are symlinks in the committed source snapshot."""
    for relative in paths:
        entry = git(repo, "ls-tree", "HEAD", "--", relative).stdout.strip()
        if entry and entry.split(maxsplit=1)[0] == "120000":
            raise FactoryError(f"allowed path is a symlink in HEAD: {relative}", "scope")


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    # Match the complete fence contents. A non-greedy brace match truncates
    # valid nested objects such as Sol review criteria at their first `}`.
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.S | re.I)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        first, last = candidate.find("{"), candidate.rfind("}")
        if first >= 0 and last > first:
            candidate = candidate[first : last + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise FactoryError(f"model did not return valid JSON: {exc}", "contract") from exc
    if not isinstance(value, dict):
        raise FactoryError("model response must be a JSON object", "contract")
    return value


def require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(keys - value.keys())
    extra = sorted(value.keys() - keys)
    if missing or extra:
        raise FactoryError(
            f"{label} schema mismatch; missing={missing}, extra={extra}", "contract"
        )


def validate_replan_reason(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"code", "evidence"}:
        raise FactoryError(
            "exceptional replan reason must contain exactly code and evidence",
            "contract",
        )
    code = value.get("code")
    evidence = value.get("evidence")
    if code not in REPLAN_REASON_CODES:
        raise FactoryError("exceptional replan reason has an unsupported code", "contract")
    if not isinstance(evidence, dict) or not evidence:
        raise FactoryError("exceptional replan reason evidence must be a non-empty object", "contract")
    if (
        evidence.get("verified") is not True
        or evidence.get("kind") != REPLAN_REASON_KINDS[code]
        or not isinstance(evidence.get("artifact_ref"), str)
        or not evidence["artifact_ref"].strip()
    ):
        raise FactoryError(
            "exceptional replan reason evidence must identify a verified artifact",
            "contract",
        )
    return {"code": code, "evidence": evidence}


def string_list(value: Any, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise FactoryError(f"{field} must be a non-empty JSON array", "contract")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise FactoryError(f"{field} must contain only non-empty strings", "contract")
    return [item.strip() for item in value]


def normalize_acceptance_criteria(value: Any, task_id: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise FactoryError(f"task {task_id} acceptance_criteria must be a non-empty array", "contract")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value, start=1):
        if isinstance(item, str) and item.strip():
            criterion = {"id": f"{task_id}.AC{index}", "statement": item.strip()}
        elif isinstance(item, dict):
            require_keys(item, {"id", "statement"}, f"task {task_id} acceptance criterion")
            criterion_id = _validate_plan_identifier(item.get("id"), f"task {task_id} acceptance criterion id")
            statement = item.get("statement")
            if not isinstance(statement, str) or not statement.strip():
                raise FactoryError(f"task {task_id} acceptance criterion statement must be non-empty", "contract")
            criterion = {"id": criterion_id, "statement": statement.strip()}
        else:
            raise FactoryError(f"task {task_id} acceptance_criteria has an invalid entry", "contract")
        if criterion["id"] in seen:
            raise FactoryError(f"task {task_id} has duplicate acceptance criterion id", "contract")
        seen.add(criterion["id"])
        normalized.append(criterion)
    return normalized


def validate_plan(value: dict[str, Any], requested_files: list[str] | None) -> dict[str, Any]:
    require_keys(
        value,
        {
            "objective",
            "allowed_files",
            "implementation_steps",
            "acceptance_criteria",
            "recommended_tests",
            "risks",
        },
        "Sol plan",
    )
    if not isinstance(value["objective"], str) or not value["objective"].strip():
        raise FactoryError("Sol plan objective must be a non-empty string", "contract")
    value["allowed_files"] = normalized_paths(string_list(value["allowed_files"], "allowed_files"))
    for key in ("implementation_steps", "acceptance_criteria", "recommended_tests"):
        value[key] = string_list(value[key], key)
    value["risks"] = string_list(value["risks"], "risks", allow_empty=True)
    if requested_files is not None:
        outside = sorted(set(value["allowed_files"]) - set(requested_files))
        if outside:
            raise FactoryError(
                f"Sol expanded beyond user --files boundary: {outside}", "scope"
            )
    return value


def _validate_plan_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise FactoryError(f"{field} must be a safe non-empty identifier", "contract")
    return value


def validate_master_plan(value: dict[str, Any], requested_files: list[str] | None) -> dict[str, Any]:
    """Validate Astra's one-shot project plan without creating a plan subsystem."""
    require_keys(
        value,
        {
            "schema_version",
            "request_ref",
            "objective",
            "global_criteria",
            "architecture_invariants",
            "assumptions",
            "non_goals",
            "milestones",
        },
        "Astra master plan",
    )
    if value["schema_version"] != 1:
        raise FactoryError("Astra master plan schema_version must be 1", "contract")
    if not isinstance(value["request_ref"], str) or not value["request_ref"].strip():
        raise FactoryError("Astra master plan request_ref must be a non-empty string", "contract")
    if not isinstance(value["objective"], str) or not value["objective"].strip():
        raise FactoryError("Astra master plan objective must be a non-empty string", "contract")

    def named_entries(key: str, fields_for_entry: set[str]) -> tuple[list[dict[str, Any]], set[str]]:
        raw_entries = value[key]
        if not isinstance(raw_entries, list) or not raw_entries:
            raise FactoryError(f"Astra master plan {key} must be a non-empty array", "contract")
        entries: list[dict[str, Any]] = []
        ids: set[str] = set()
        for entry in raw_entries:
            if not isinstance(entry, dict):
                raise FactoryError(f"Astra master plan {key} entries must be objects", "contract")
            require_keys(entry, fields_for_entry, f"Astra master plan {key} entry")
            entry_id = _validate_plan_identifier(entry.get("id"), f"{key} id")
            if entry_id in ids:
                raise FactoryError(f"Astra master plan has duplicate {key} id: {entry_id}", "contract")
            statement = entry.get("statement")
            if not isinstance(statement, str) or not statement.strip():
                raise FactoryError(f"Astra master plan {key} statement must be non-empty", "contract")
            entry["id"] = entry_id
            entry["statement"] = statement.strip()
            ids.add(entry_id)
            entries.append(entry)
        return entries, ids

    global_criteria, global_criteria_ids = named_entries("global_criteria", {"id", "statement"})
    architecture_invariants, _ = named_entries("architecture_invariants", {"id", "statement"})
    assumptions, _ = named_entries("assumptions", {"id", "statement", "critical"})
    if any(not isinstance(entry["critical"], bool) for entry in assumptions):
        raise FactoryError("Astra master plan assumption critical must be boolean", "contract")
    value["global_criteria"] = global_criteria
    value["architecture_invariants"] = architecture_invariants
    value["assumptions"] = assumptions
    value["non_goals"] = string_list(value["non_goals"], "non_goals", allow_empty=True)
    milestones = value["milestones"]
    if not isinstance(milestones, list) or not milestones:
        raise FactoryError("Astra master plan milestones must be a non-empty array", "contract")

    seen_milestones: set[str] = set()
    seen_tasks: set[str] = set()
    task_order: list[str] = []
    for milestone in milestones:
        if not isinstance(milestone, dict):
            raise FactoryError("Astra master plan milestone must be an object", "contract")
        require_keys(milestone, {"id", "objective", "tasks"}, "Astra milestone")
        milestone_id = _validate_plan_identifier(milestone.get("id"), "milestone id")
        if milestone_id in seen_milestones:
            raise FactoryError(f"Astra master plan has duplicate milestone id: {milestone_id}", "contract")
        seen_milestones.add(milestone_id)
        if not isinstance(milestone.get("objective"), str) or not milestone["objective"].strip():
            raise FactoryError("Astra milestone objective must be a non-empty string", "contract")
        tasks = milestone.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise FactoryError(f"Astra milestone {milestone_id} must contain tasks", "contract")
        normalized_tasks: list[dict[str, Any]] = []
        for task in tasks:
            if not isinstance(task, dict):
                raise FactoryError("Astra task must be an object", "contract")
            require_keys(
                task,
                {
                    "id",
                    "objective",
                    "depends_on",
                    "editable_scope",
                    "acceptance_criteria",
                    "verification_commands",
                    "preservation_constraints",
                    "global_criteria",
                },
                "Astra task",
            )
            task_id = _validate_plan_identifier(task.get("id"), "task id")
            if task_id in seen_tasks:
                raise FactoryError(f"Astra master plan has duplicate task id: {task_id}", "contract")
            seen_tasks.add(task_id)
            task_order.append(task_id)
            if not isinstance(task.get("objective"), str) or not task["objective"].strip():
                raise FactoryError(f"Astra task {task_id} objective must be non-empty", "contract")
            depends = task.get("depends_on")
            if not isinstance(depends, list) or any(
                not isinstance(item, str) or not item.strip() for item in depends
            ):
                raise FactoryError(f"Astra task {task_id} depends_on must be a string array", "contract")
            if task_id in depends:
                raise FactoryError(f"Astra task {task_id} cannot depend on itself", "contract")
            raw_scope = string_list(task.get("editable_scope"), f"task {task_id} editable_scope")
            scope = normalized_paths(raw_scope)
            if len(raw_scope) != len(scope):
                raise FactoryError(f"Astra task {task_id} editable_scope contains duplicates", "contract")
            if requested_files is not None:
                outside = sorted(set(scope) - set(requested_files))
                if outside:
                    raise FactoryError(
                        f"Astra task {task_id} expanded beyond user --files boundary: {outside}", "scope"
                    )
            task["editable_scope"] = scope
            task["depends_on"] = list(depends)
            task["acceptance_criteria"] = normalize_acceptance_criteria(
                task.get("acceptance_criteria"), task_id
            )
            task["verification_commands"] = string_list(
                task.get("verification_commands"), f"task {task_id} verification_commands"
            )
            task["preservation_constraints"] = string_list(
                task.get("preservation_constraints"),
                f"task {task_id} preservation_constraints",
                allow_empty=True,
            )
            task_global_criteria = string_list(
                task.get("global_criteria"),
                f"task {task_id} global_criteria",
                allow_empty=True,
            )
            if len(task_global_criteria) != len(set(task_global_criteria)):
                raise FactoryError(
                    f"Astra task {task_id} has duplicate global criterion references",
                    "contract",
                )
            unknown_criteria = sorted(set(task_global_criteria) - global_criteria_ids)
            if unknown_criteria:
                raise FactoryError(
                    f"Astra task {task_id} references unknown global criteria: {unknown_criteria}",
                    "contract",
                )
            task["global_criteria"] = task_global_criteria
            normalized_tasks.append(task)
        milestone["tasks"] = normalized_tasks

    for milestone in milestones:
        for task in milestone["tasks"]:
            unknown = sorted(set(task["depends_on"]) - seen_tasks)
            if unknown:
                raise FactoryError(f"Astra task {task['id']} has unknown dependencies: {unknown}", "contract")

    dependencies = {
        task["id"]: set(task["depends_on"])
        for milestone in milestones
        for task in milestone["tasks"]
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise FactoryError("Astra master plan task dependencies contain a cycle", "contract")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in task_order:
        visit(task_id)
    all_plan_ids: list[str] = []
    all_plan_ids.extend(entry["id"] for entry in global_criteria)
    all_plan_ids.extend(entry["id"] for entry in architecture_invariants)
    all_plan_ids.extend(entry["id"] for entry in assumptions)
    all_plan_ids.extend(milestone["id"] for milestone in milestones)
    all_plan_ids.extend(task["id"] for milestone in milestones for task in milestone["tasks"])
    all_plan_ids.extend(
        criterion["id"]
        for milestone in milestones
        for task in milestone["tasks"]
        for criterion in task["acceptance_criteria"]
    )
    if len(all_plan_ids) != len(set(all_plan_ids)):
        raise FactoryError(
            "Astra master plan identifiers must be globally unique",
            "contract",
        )
    covered_criteria = {
        criterion_id
        for milestone in milestones
        for task in milestone["tasks"]
        for criterion_id in task["global_criteria"]
    }
    uncovered = sorted(global_criteria_ids - covered_criteria)
    if uncovered:
        raise FactoryError(
            f"Astra master plan has uncovered global criteria: {uncovered}",
            "contract",
        )
    return value


def master_plan_tasks(master_plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [task for milestone in master_plan["milestones"] for task in milestone["tasks"]]


def next_ready_master_task(
    master_plan: dict[str, Any], task_statuses: dict[str, str]
) -> dict[str, Any] | None:
    """Select the first pending task whose dependencies are committed."""
    for task in master_plan_tasks(master_plan):
        if task_statuses.get(task["id"], "PENDING") != "PENDING":
            continue
        if all(task_statuses.get(dependency) in {"PASS", "COMMITTED"} for dependency in task["depends_on"]):
            return task
    return None


def failure_signature(failure: dict[str, Any]) -> tuple[Any, ...]:
    """Return the small deterministic identity used by the stagnation rule."""
    return (
        failure.get("source"),
        failure.get("code") or failure.get("error_category"),
        tuple(sorted(str(item) for item in failure.get("criterion_ids", []))),
        failure.get("returncode"),
        failure.get("evidence_signature"),
    )


def is_stagnant(
    previous_candidate_id: str | None,
    current_candidate_id: str | None,
    previous_failure: dict[str, Any],
    current_failure: dict[str, Any],
) -> bool:
    return (
        previous_candidate_id is not None
        and previous_candidate_id == current_candidate_id
        and failure_signature(previous_failure) == failure_signature(current_failure)
    )


def validate_review(
    value: dict[str, Any],
    expected_hash: str,
    expected_base_commit: str,
    expected_candidate_id: str,
    expected_criteria_ids: Iterable[str] | None = None,
    expected_verification: dict[str, Any] | None = None,
    *,
    expected_review_mode: str | None = None,
    expected_predecessor_review_ref: str | None = None,
    expected_target_finding_ids: Iterable[str] | None = None,
    task_id: str | None = None,
    predecessor_review: dict[str, Any] | None = None,
    expected_repair_delta_sha256: str | None = None,
    expected_verification_ref: str | None = None,
) -> dict[str, Any]:
    required_review_keys = {
        "decision",
        "reviewed_diff_sha256",
        "base_commit",
        "candidate_id",
        "criteria",
        "findings",
        "required_changes",
        "route",
    }
    missing = sorted(required_review_keys - value.keys())
    extra = sorted(
        value.keys()
        - required_review_keys
        - {
            "replan_reason",
            "verification",
            "review_mode",
            "predecessor_review_ref",
            "target_finding_ids",
            "finding_records",
        }
    )
    if missing or extra:
        raise FactoryError(
            f"Sol review schema mismatch; missing={missing}, extra={extra}", "contract"
        )
    if "replan_reason" in value:
        validate_replan_reason(value["replan_reason"])
    decision = value["decision"]
    if decision not in {"APPROVE", "REJECT"}:
        raise FactoryError("Sol review decision must be APPROVE or REJECT", "contract")
    # This hash is diagnostic evidence that Sol saw the supplied patch. The
    # candidate authority remains expected_base_commit + expected_candidate_id
    # (the host-side git write-tree result), never this digest.
    if value["reviewed_diff_sha256"] != expected_hash:
        raise FactoryError("Sol reviewed hash does not match the staged candidate", "hash")
    if value["base_commit"] != expected_base_commit:
        raise FactoryError("Sol reviewed base does not match the candidate base", "hash")
    if value["candidate_id"] != expected_candidate_id:
        raise FactoryError("Sol reviewed candidate does not match the staged tree", "hash")
    if expected_verification is not None and value.get("verification") != expected_verification:
        raise FactoryError("Sol reviewed verification does not match the Runner evidence", "hash")
    if not isinstance(value["criteria"], list) or not all(isinstance(x, dict) for x in value["criteria"]):
        raise FactoryError("Sol review criteria must be an array of objects", "contract")
    criteria_ids: set[str] = set()
    for criterion in value["criteria"]:
        criterion_id = criterion.get("criterion")
        if not isinstance(criterion_id, str) or not criterion_id.strip() or not isinstance(criterion.get("passed"), bool):
            raise FactoryError("Sol review criteria require a string criterion and boolean passed", "contract")
        if criterion_id.strip() in criteria_ids:
            raise FactoryError("Sol review criteria contain duplicate identifiers", "contract")
        criteria_ids.add(criterion_id.strip())
    value["findings"] = string_list(value["findings"], "findings", allow_empty=True)
    value["required_changes"] = string_list(value["required_changes"], "required_changes", allow_empty=True)
    review_mode = value.setdefault("review_mode", expected_review_mode or "LARGE_STEP_REVIEW")
    if review_mode not in {"LARGE_STEP_REVIEW", "FINDING_ONLY_RECHECK"}:
        raise FactoryError("Sol review mode is invalid", "contract")
    predecessor = value.setdefault("predecessor_review_ref", None)
    target_ids = value.setdefault("target_finding_ids", [])
    if not isinstance(target_ids, list) or any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+-F[0-9]{3}", item)
        for item in target_ids
    ) or len(target_ids) != len(set(target_ids)):
        raise FactoryError("Sol review target finding IDs are invalid", "contract")
    if review_mode == "LARGE_STEP_REVIEW":
        if predecessor is not None or target_ids:
            raise FactoryError("large Sol review cannot target a predecessor finding", "contract")
    else:
        if not isinstance(predecessor, str) or not predecessor or not target_ids:
            raise FactoryError("finding-only Sol recheck lacks predecessor or target findings", "contract")
    if expected_review_mode is not None and review_mode != expected_review_mode:
        raise FactoryError("Sol review mode does not match the current review phase", "contract")
    if expected_predecessor_review_ref is not None and predecessor != expected_predecessor_review_ref:
        raise FactoryError("Sol review predecessor does not match the current review chain", "contract")
    if expected_target_finding_ids is not None and target_ids != list(expected_target_finding_ids):
        raise FactoryError("Sol review target findings do not match the current review chain", "contract")
    records = value.get("finding_records")
    if records is None:
        if review_mode == "FINDING_ONLY_RECHECK":
            raise FactoryError("finding-only Sol recheck must provide finding_records", "contract")
        raw_findings = value["findings"]
        record_ids = list(target_ids) if target_ids else [
            f"{task_id or 'TASK'}-F{index:03d}" for index in range(1, len(raw_findings) + 1)
        ]
        records = [
            {
                "finding_id": finding_id,
                "status": "OPEN" if value["decision"] == "REJECT" else "RESOLVED",
                "criterion_ids": [],
                "summary": raw_findings[index] if index < len(raw_findings) else "",
                "evidence": "",
                "required_correction": value["required_changes"][index]
                if index < len(value["required_changes"])
                else "",
            }
            for index, finding_id in enumerate(record_ids)
        ]
        value["finding_records"] = records
    if not isinstance(records, list):
        raise FactoryError("Sol finding_records must be an array", "contract")
    record_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "finding_id",
            "status",
            "criterion_ids",
            "summary",
            "evidence",
            "required_correction",
        }:
            raise FactoryError("Sol finding record schema is invalid", "contract")
        finding_id = record.get("finding_id")
        if not isinstance(finding_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+-F[0-9]{3}", finding_id
        ) or finding_id in record_ids:
            raise FactoryError("Sol finding IDs must be stable and unique", "contract")
        record_ids.add(finding_id)
        if record.get("status") not in {"OPEN", "RESOLVED", "REGRESSED"}:
            raise FactoryError("Sol finding status is invalid", "contract")
        if not isinstance(record.get("criterion_ids"), list) or any(
            not isinstance(item, str) or not item.strip() for item in record["criterion_ids"]
        ):
            raise FactoryError("Sol finding criterion_ids are invalid", "contract")
        for field in ("summary", "required_correction"):
            if not isinstance(record.get(field), str):
                raise FactoryError(f"Sol finding {field} must be a string", "contract")
        if not isinstance(record.get("evidence"), (str, dict)):
            raise FactoryError("Sol finding evidence must be text or a structured object", "contract")
        if record.get("status") in {"RESOLVED", "REGRESSED"}:
            evidence = record["evidence"]
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {"repair_delta_sha256", "verification_ref", "observation"}
                or not isinstance(evidence.get("repair_delta_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", evidence["repair_delta_sha256"])
                or not isinstance(evidence.get("verification_ref"), str)
                or not evidence["verification_ref"].strip()
                or not isinstance(evidence.get("observation"), str)
                or not evidence["observation"].strip()
            ):
                raise FactoryError("resolved/regressed finding requires structured repair evidence", "contract")
            if expected_repair_delta_sha256 is not None and evidence["repair_delta_sha256"] != expected_repair_delta_sha256:
                raise FactoryError("finding evidence is not bound to the current repair delta", "hash")
            if expected_verification_ref is not None and evidence["verification_ref"] != expected_verification_ref:
                raise FactoryError("finding evidence is not bound to the current verification", "hash")
    open_records = [
        record for record in records if record.get("status") in {"OPEN", "REGRESSED"}
    ]
    if review_mode == "FINDING_ONLY_RECHECK" and record_ids != set(target_ids):
        raise FactoryError("finding-only Sol recheck introduced an untargeted finding", "contract")
    if review_mode == "FINDING_ONLY_RECHECK":
        if not isinstance(predecessor_review, dict):
            raise FactoryError("finding-only Sol recheck lacks a predecessor artifact", "contract")
        predecessor_records = predecessor_review.get("finding_records")
        if not isinstance(predecessor_records, list):
            raise FactoryError("finding-only predecessor lacks finding_records", "contract")
        predecessor_by_id = {
            record.get("finding_id"): record
            for record in predecessor_records
            if isinstance(record, dict)
        }
        predecessor_open_ids = {
            finding_id
            for finding_id, record in predecessor_by_id.items()
            if record.get("status") in {"OPEN", "REGRESSED"}
        }
        if predecessor_open_ids != set(target_ids):
            raise FactoryError("finding-only Sol recheck targets stale or incomplete findings", "contract")
        for record in records:
            previous = predecessor_by_id.get(record["finding_id"])
            if not isinstance(previous, dict) or previous.get("status") not in {"OPEN", "REGRESSED"}:
                raise FactoryError("finding-only Sol recheck changed an unrelated finding", "contract")
            if record["status"] == "REGRESSED" and isinstance(record["evidence"], str) and not record["evidence"].strip():
                raise FactoryError("REGRESSED finding requires concrete repair evidence", "contract")
        for record in records:
            previous = predecessor_by_id[record["finding_id"]]
            if (
                record["criterion_ids"] != previous.get("criterion_ids", [])
                or record["summary"] != previous.get("summary", "")
                or record["required_correction"] != previous.get("required_correction", "")
            ):
                raise FactoryError("finding-only record changed predecessor evidence", "contract")
        open_corrections = {
            record["required_correction"]
            for record in records
            if record["status"] in {"OPEN", "REGRESSED"}
            and record["required_correction"].strip()
        }
        if decision == "REJECT" and set(value["required_changes"]) != open_corrections:
            raise FactoryError("finding-only required_changes are not bound to target findings", "contract")
        expected_findings = [record["summary"] for record in records if record["status"] in {"OPEN", "REGRESSED"}]
        if decision == "REJECT" and value["findings"] != expected_findings:
            raise FactoryError("finding-only findings are not bound to target records", "contract")
        if decision == "APPROVE" and any(record["status"] != "RESOLVED" for record in records):
            raise FactoryError("finding-only APPROVE must resolve every target finding", "contract")
        if expected_criteria_ids is not None and criteria_ids != set(expected_criteria_ids):
            raise FactoryError("finding-only criteria are not bound to target records", "contract")
        if decision == "APPROVE" and any(item["passed"] is not True for item in value["criteria"]):
            raise FactoryError("finding-only APPROVE requires targeted criteria to pass", "contract")
        if decision == "APPROVE" and value["findings"]:
            raise FactoryError("finding-only APPROVE cannot retain open findings", "contract")
    if value["route"] not in {"none", "builder"}:
        raise FactoryError("Sol review route must be none or builder in v1", "contract")
    if decision == "APPROVE" and (value["route"] != "none" or value["required_changes"] or open_records):
        raise FactoryError("APPROVE must use route=none with no required_changes", "contract")
    if decision == "APPROVE":
        required_ids = set(expected_criteria_ids or [])
        if review_mode == "LARGE_STEP_REVIEW" and required_ids and criteria_ids != required_ids:
            raise FactoryError("APPROVE does not cover every task acceptance criterion", "contract")
        if review_mode == "LARGE_STEP_REVIEW" and (
            not value["criteria"] or any(item["passed"] is not True for item in value["criteria"])
        ):
            raise FactoryError("APPROVE requires every supplied criterion to pass", "contract")
    if decision == "REJECT" and (value["route"] == "none" or not value["required_changes"] or not open_records):
        raise FactoryError("REJECT requires changes and the builder route in v1", "contract")
    return value


def open_review_finding_ids(review: dict[str, Any], task_id: str) -> list[str]:
    """Return stable open finding IDs from the latest review artifact."""
    records = review.get("finding_records")
    if isinstance(records, list):
        return [
            record["finding_id"]
            for record in records
            if isinstance(record, dict)
            and record.get("status") in {"OPEN", "REGRESSED"}
            and isinstance(record.get("finding_id"), str)
        ]
    findings = review.get("findings")
    if not isinstance(findings, list):
        return []
    return [f"{task_id}-F{index:03d}" for index in range(1, len(findings) + 1)]


def review_required_changes(review: dict[str, Any]) -> list[str]:
    """Return only corrections bound to open/reopened finding records."""
    records = review.get("finding_records")
    if isinstance(records, list):
        return [
            record["required_correction"]
            for record in records
            if isinstance(record, dict)
            and record.get("status") in {"OPEN", "REGRESSED"}
            and isinstance(record.get("required_correction"), str)
            and record["required_correction"].strip()
        ]
    changes = review.get("required_changes")
    return list(changes) if isinstance(changes, list) else []


def review_evidence_signature(review: dict[str, Any]) -> str:
    """Hash the effective finding evidence used by review stagnation."""
    payload = {
        "finding_records": review.get("finding_records", []),
        "findings": review.get("findings", []),
        "required_changes": review.get("required_changes", []),
        "target_finding_ids": review.get("target_finding_ids", []),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_file_tree_skeleton(repo: Path, max_depth: int = 6) -> str:
    """Build a compact directory tree skeleton of tracked files in HEAD for planner token reduction."""
    result = command(["git", "ls-tree", "-r", "-z", "--name-only", "HEAD"], cwd=repo, timeout=30)
    if result.returncode != 0:
        raise FactoryError(f"git ls-tree failed to build skeleton: {result.stderr}", "context")
    paths = [p for p in result.stdout.split("\0") if p]
    if not paths:
        return ""

    tree: dict[str, Any] = {}
    for path_str in sorted(paths):
        parts = PurePosixPath(path_str).parts
        if len(parts) > max_depth:
            parts = parts[:max_depth] + ("...",)
        current = tree
        for part in parts:
            current = current.setdefault(part, {})

    def render_tree(d: dict[str, Any], prefix: str = "") -> list[str]:
        out = []
        keys = sorted(d.keys())
        for i, key in enumerate(keys):
            is_last = (i == len(keys) - 1)
            connector = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "
            if d[key]:
                out.append(f"{prefix}{connector}{key}/")
                out.extend(render_tree(d[key], prefix + child_prefix))
            else:
                out.append(f"{prefix}{connector}{key}")
        return out

    return ".\n" + "\n".join(render_tree(tree))


def review_test_evidence_with_log_tail(tests: list[dict[str, Any]], run_dir: Path) -> list[dict[str, Any]]:
    """Give Sol bounded test output only when it matches Runner's recorded hash."""
    enriched: list[dict[str, Any]] = []
    trusted_root = run_dir.resolve()
    for item in tests:
        record = dict(item)
        raw_path = item.get("log")
        expected_sha256 = item.get("log_sha256")
        if isinstance(raw_path, str) and isinstance(expected_sha256, str):
            path = Path(raw_path)
            try:
                if path.is_symlink() or path.parent.resolve() != trusted_root or not path.is_file():
                    raise OSError("test log is outside the run directory")
                digest = hashlib.sha256()
                tail = b""
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(64 * 1024), b""):
                        digest.update(chunk)
                        tail = (tail + chunk)[-8192:]
                if digest.hexdigest() == expected_sha256:
                    excerpt = tail.decode("utf-8", errors="replace")
                    record["verified_log_tail"] = excerpt
                    match = re.search(r"\bRan ([0-9]+) tests?\b", excerpt)
                    if match:
                        record["observed_test_count"] = int(match.group(1))
            except (OSError, RuntimeError):
                pass
        enriched.append(record)
    return enriched


def make_review_evidence_packet(
    *,
    diff_text: str,
    digest: str,
    base_commit: str,
    candidate_id: str,
    changed: list[str],
    candidate_source_context: dict[str, Any],
    tests: list[dict[str, Any]],
    plan: dict[str, Any],
    sequence: int,
    review_mode: str = "LARGE_STEP_REVIEW",
    predecessor_review_ref: str | None = None,
    target_finding_ids: list[str] | None = None,
    repair_delta: str | None = None,
) -> dict[str, Any]:
    """Build a standardized HoH evidence packet for Sol Reviewer."""
    is_finding_recheck = review_mode == "FINDING_ONLY_RECHECK"
    affected_files = list(changed)
    if is_finding_recheck and repair_delta:
        parsed_paths = sorted(
            {
                match.group(1)
                for match in re.finditer(r"^\+\+\+ b/(.+)$", repair_delta, re.MULTILINE)
                if match.group(1) != "/dev/null"
            }
        )
        if parsed_paths:
            affected_files = parsed_paths
    packet_source_context = candidate_source_context
    if is_finding_recheck:
        source_files = candidate_source_context.get("files", {})
        packet_source_context = {
            **{
                key: candidate_source_context[key]
                for key in ("source", "base_commit", "candidate_id", "preferred_context_budget_chars", "context_chars", "soft_budget_exceeded")
                if key in candidate_source_context
            },
            "files": {
                path: source_files[path]
                for path in affected_files
                if isinstance(source_files, dict) and path in source_files
            },
        }
    return {
        "packet_type": "review_evidence",
        "review_cycle": sequence,
        "review_mode": review_mode,
        "predecessor_review_ref": predecessor_review_ref,
        "target_finding_ids": target_finding_ids or [],
        "affected_files": affected_files,
        "repair_delta": repair_delta,
        "candidate_diff": {
            "sha256": digest,
            "base_commit": base_commit,
            "candidate_id": candidate_id,
            "changed_files": changed,
            "patch": repair_delta if is_finding_recheck and repair_delta is not None else diff_text,
        },
        "candidate_authority": {
            "base_commit": base_commit,
            "candidate_id": candidate_id,
            "candidate_id_source": "host git write-tree",
            "reviewed_diff_sha256_role": "diagnostic evidence only",
        },
        "candidate_source_context": packet_source_context,
        "test_results": tests[-1:] if is_finding_recheck else tests,
        "scope_boundary": {
            "allowed_files": plan["allowed_files"],
            "changed_files": changed,
            "is_confined": set(changed).issubset(set(plan["allowed_files"])),
        },
        "acceptance_criteria": [] if is_finding_recheck else plan.get("acceptance_criteria", []),
        "global_criteria": [] if is_finding_recheck else plan.get("global_criteria", []),
    }


def make_debug_evidence_packet(
    *,
    diff_text: str,
    failure: str,
    plan: dict[str, Any],
    attempt: int | str,
    latest_test: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standardized HoH evidence packet for a repair attempt."""
    return {
        "packet_type": "debug_evidence",
        "attempt": attempt,
        "candidate_diff": diff_text,
        "failure_evidence": failure,
        "latest_test": latest_test or {},
        "allowed_files": plan["allowed_files"],
        "recommended_tests": plan.get("recommended_tests", []),
    }


@dataclass
class Config:
    repo: str
    request: str
    requested_files: list[str] | None
    test_command: str | None
    prior_run: str | None = None
    planner_provider: str = "openai-codex"
    planner_model: str = DEFAULT_PLANNER_MODEL
    planner_reasoning: str = DEFAULT_PLANNER_REASONING
    reviewer_provider: str = "openai-codex"
    reviewer_model: str = DEFAULT_REVIEWER_MODEL
    reviewer_reasoning: str = DEFAULT_REVIEWER_REASONING
    sol_provider: str = "openai-codex"
    sol_model: str = DEFAULT_SOL_MODEL
    builder_model: str = DEFAULT_BUILDER_MODEL
    agy_bin: str | None = None
    max_task_attempts: int = 12
    max_debug_attempts: int = 2
    max_review_cycles: int = 2
    role_timeout: int = 300
    builder_timeout: int = 900
    test_timeout: int = 900
    agy_navigation_recovery: str = AGY_NAVIGATION_RECOVERY_DEFAULT

    def __post_init__(self) -> None:
        integer_bounds = {
            "max_task_attempts": 1,
            "max_debug_attempts": 0,
            "max_review_cycles": 0,
            "role_timeout": 1,
            "builder_timeout": 1,
            "test_timeout": 1,
        }
        for name, minimum in integer_bounds.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise FactoryError(
                    f"{name} must be an integer >= {minimum}",
                    "config",
                )
        if not isinstance(self.builder_model, str) or not self.builder_model.strip():
            raise FactoryError("builder_model must be a non-empty string", "config")
        if self.builder_model.startswith("openai/"):
            raise FactoryError(
                "builder_model must use the bare AGY model slug; obsolete openai/ prefix is not allowed",
                "config",
            )
        if self.agy_bin is not None and (
            not isinstance(self.agy_bin, str) or not self.agy_bin.strip()
        ):
            raise FactoryError("agy_bin must be None or a non-empty string", "config")
        if self.agy_navigation_recovery not in AGY_NAVIGATION_RECOVERY_MODES:
            raise FactoryError(
                "agy_navigation_recovery must be off, observe, or adaptive",
                "config",
            )


class CodexRoleClient:
    """Invokes Codex CLI directly for Astra/Sol calls."""

    def __init__(self, codex_bin: str | None = None) -> None:
        self.codex_bin = codex_bin or shutil.which("codex") or "codex"

    def call(
        self,
        *,
        role: str,
        provider: str,
        model: str,
        prompt: str,
        usage_path: Path,
        output_path: Path,
        timeout: int,
        reasoning: str = "high",
    ) -> dict[str, Any]:
        argv = [
            self.codex_bin,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "-m",
            model,
            "-c",
            f"model_reasoning_effort={json.dumps(reasoning)}",
            "-",
        ]
        # Pipe prompt via stdin to avoid Windows 8191-char command line length limits
        result = command(argv, cwd=usage_path.parent, timeout=timeout, stdin=prompt)
        raw_output = result.stdout or ""
        write_text(output_path, raw_output + ("\nSTDERR:\n" + result.stderr if result.stderr else ""))

        # Attestation file for audit
        atomic_json(
            usage_path,
            {
                "role": role,
                "provider": provider,
                "model": model,
                "reasoning": reasoning,
                "completed": result.returncode == 0,
                "failed": result.returncode != 0,
            },
        )
        if result.returncode != 0:
            raise FactoryError(f"{role} invocation failed: {(result.stderr or result.stdout).strip()}", "provider")

        return parse_json_object(raw_output)


class HermesRoleClient:
    """Creates a completely fresh Hermes process for every Astra/Sol call."""

    def __init__(self, hermes_bin: str | None = None) -> None:
        self.hermes_bin = hermes_bin or shutil.which("hermes") or "hermes"

    def call(
        self,
        *,
        role: str,
        provider: str,
        model: str,
        prompt: str,
        usage_path: Path,
        output_path: Path,
        timeout: int,
        reasoning: str = "high",
    ) -> dict[str, Any]:
        if provider == "openai-codex":
            client = CodexRoleClient()
            return client.call(
                role=role,
                provider=provider,
                model=model,
                prompt=prompt,
                usage_path=usage_path,
                output_path=output_path,
                timeout=timeout,
                reasoning=reasoning,
            )
        argv = [
            self.hermes_bin,
            "--safe-mode",
            "--provider",
            provider,
            "--model",
            model,
            "--reasoning",
            reasoning,
            # Explicitly select a built-in empty toolset. This prevents the
            # role from inheriting configured terminal/file tools while still
            # using Hermes's normal provider and usage-attestation path.
            "--toolsets",
            "bot_room",
            "--usage-file",
            str(usage_path),
            "--oneshot",
            prompt,
        ]
        result = command(argv, cwd=usage_path.parent, timeout=timeout)
        write_text(output_path, (result.stdout or "") + ("\nSTDERR:\n" + result.stderr if result.stderr else ""))
        if not usage_path.is_file():
            raise FactoryError(f"{role} produced no usage attestation", "preflight")
        usage = read_json(usage_path)
        if result.returncode != 0 or usage.get("failed") or not usage.get("completed"):
            raise FactoryError(f"{role} invocation failed: {(result.stderr or result.stdout).strip()}", "provider")
        if usage.get("model") != model:
            raise FactoryError(
                f"{role} model mismatch: requested {model!r}, got {usage.get('model')!r}", "provider"
            )
        actual_provider = usage.get("provider")
        if actual_provider != provider and not (provider.startswith("custom:") and actual_provider == "custom"):
            raise FactoryError(
                f"{role} provider mismatch: requested {provider!r}, got {actual_provider!r}", "provider"
            )
        return parse_json_object(result.stdout)


def _validate_agy_executable(candidate: str | os.PathLike[str], source: str) -> Path:
    try:
        path = Path(candidate).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FactoryError(f"AGY executable from {source} is not a valid file: {candidate}", "preflight") from exc
    if not path.is_file():
        raise FactoryError(f"AGY executable from {source} is not a file: {path}", "preflight")
    if path.suffix.lower() in AGY_SHELL_SHIMS:
        raise FactoryError(f"AGY executable from {source} is an unsupported shell shim: {path}", "preflight")
    if os.name == "nt" and path.suffix.lower() != ".exe":
        raise FactoryError(f"AGY executable from {source} is not a native Windows executable: {path}", "preflight")
    if os.name != "nt" and not os.access(path, os.X_OK):
        raise FactoryError(f"AGY executable from {source} is not executable: {path}", "preflight")
    return path


def resolve_agy_executable(explicit: str | None) -> Path:
    """Resolve one native AGY executable without silently changing sources."""
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit.strip():
            raise FactoryError("explicit AGY executable path must be a non-empty string", "preflight")
        return _validate_agy_executable(explicit, "--agy-bin")

    discovered = shutil.which("agy")
    if discovered:
        return _validate_agy_executable(discovered, "PATH")

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise FactoryError(
                "AGY executable not found: LOCALAPPDATA is unavailable for the Windows fallback",
                "preflight",
            )
        local_root = Path(local_app_data)
        fallback = local_root / "agy" / "bin" / "agy.exe"
        return _validate_agy_executable(fallback, "%LOCALAPPDATA%/agy/bin/agy.exe")

    raise FactoryError("AGY executable not found on PATH or the Windows local-app fallback", "preflight")


def _parse_agy_model_catalog(raw: str) -> dict[str, str]:
    """Parse the observed tabular `agy models` output strictly."""
    catalog: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "Fetching available models...":
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*-[A-Za-z0-9][A-Za-z0-9._-]*)\s+(.+\S)", stripped)
        if not match:
            raise FactoryError(f"AGY model catalog contains a malformed entry: {line!r}", "preflight")
        model, description = match.groups()
        if model in catalog:
            raise FactoryError(f"AGY model catalog contains a duplicate entry: {model}", "preflight")
        catalog[model] = description
    if not catalog:
        raise FactoryError("AGY model catalog is empty", "preflight")
    return catalog


def _parse_agy_help_capabilities(raw: str) -> dict[str, str]:
    """Parse option declarations instead of accepting arbitrary substrings."""
    declarations: dict[str, str] = {}
    for line in raw.splitlines():
        match = re.match(r"^\s*(--[A-Za-z0-9][A-Za-z0-9-]*)(?=\s|$)(.*)$", line)
        if not match:
            continue
        option, description = match.groups()
        if option in declarations:
            raise FactoryError(f"AGY help contains a duplicate option declaration: {option}", "preflight")
        declarations[option] = description.strip()
    if not declarations:
        raise FactoryError("AGY help contains no parseable option declarations", "preflight")
    return declarations


def _snapshot_probe_tree(root: Path) -> dict[str, dict[str, Any]]:
    """Hash a private probe root so no-edit behavior is independently checked."""
    snapshot: dict[str, dict[str, Any]] = {}
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if item.is_symlink():
            snapshot[relative] = {
                "kind": "symlink",
                "target": os.readlink(item),
            }
        elif item.is_dir():
            snapshot[relative] = {"kind": "directory"}
        elif item.is_file():
            snapshot[relative] = {
                "kind": "file",
                "size": item.stat().st_size,
                "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
            }
        else:
            snapshot[relative] = {"kind": "other"}
    return snapshot


def _replace_candidate_file(
    source: Path,
    target: Path,
    *,
    race_safe: bool,
    expected_target: dict[str, Any] | None = None,
    target_fd: int | None = None,
) -> None:
    """Replace one candidate file with an OS operation compatible with its guard."""
    if expected_target is not None:
        if target_fd is not None:
            os.lseek(target_fd, 0, os.SEEK_SET)
            data = os.read(target_fd, max(1, os.fstat(target_fd).st_size))
            current_target = {
                "kind": "file",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        elif target.is_file():
            data = target.read_bytes()
            current_target = {
                "kind": "file",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        else:
            current_target = {"kind": "missing"}
        if current_target != expected_target:
            raise OSError("candidate target changed before atomic replacement")
    if (
        race_safe
        and os.name == "nt"
        and isinstance(expected_target, dict)
        and expected_target.get("kind") == "missing"
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # NTFS hard-link creation is atomic and fails if the destination
            # appeared after the CAS check; the staged source stays intact
            # until the link succeeds.
            os.link(source, target)
        except FileExistsError as exc:
            raise OSError("candidate target appeared before atomic creation") from exc
        source.unlink()
        return
    if not race_safe or os.name != "nt":
        os.replace(source, target)
        return
    import ctypes
    import ctypes.wintypes as wintypes

    replace_file = ctypes.windll.kernel32.ReplaceFileW
    replace_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    replace_file.restype = wintypes.BOOL
    if not replace_file(str(target), str(source), None, 0, None, None):
        raise OSError(ctypes.get_last_error(), "could not replace candidate target")


@contextmanager
def _probe_temp_root() -> Iterable[str]:
    root = tempfile.mkdtemp(prefix="agy-preflight-sandbox-")
    try:
        yield root
    finally:
        try:
            shutil.rmtree(root, ignore_errors=True)
        except OSError:
            pass


class AgyBuilder:
    """Direct AGY Builder adapter with a fail-closed result boundary."""

    def __init__(
        self,
        agy_bin: str | None = None,
        *,
        _probe_runner: Callable[[Path, Config, Path], dict[str, Any]] | None = None,
        _builder_runner: Callable[..., tuple[subprocess.CompletedProcess[str], str, dict[str, Any]]] | None = None,
    ) -> None:
        self._explicit_agy_bin = agy_bin
        self._probe_runner = _probe_runner
        self._builder_runner = _builder_runner
        self.agy_bin: Path | None = None
        self._pinned_sha256: str | None = None
        self._conversation_ids: set[str] = set()
        self.last_attempt_artifact: str | None = None
        self.last_attempt_label: str | None = None
        self.last_attempt_run_root: Path | None = None
        self.last_attempt_outcome: str | None = None
        self.last_attempt_telemetry: dict[str, Any] | None = None
        if agy_bin is not None:
            self.agy_bin = resolve_agy_executable(agy_bin)
            self._pinned_sha256 = hashlib.sha256(self.agy_bin.read_bytes()).hexdigest()

    def _pin_executable(self, config: Config) -> tuple[Path, str]:
        requested = self._explicit_agy_bin if self._explicit_agy_bin is not None else config.agy_bin
        resolved = resolve_agy_executable(requested)
        try:
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        except OSError as exc:
            raise FactoryError(f"could not hash pinned AGY executable: {resolved}", "preflight") from exc
        if self.agy_bin is not None and resolved != self.agy_bin:
            raise FactoryError(
                f"AGY executable path changed during the run: expected {self.agy_bin}, got {resolved}",
                "preflight",
            )
        if self._pinned_sha256 is not None and digest != self._pinned_sha256:
            raise FactoryError("AGY executable identity changed during the run", "preflight")
        self.agy_bin = resolved
        self._pinned_sha256 = digest
        return resolved, digest

    def _recheck_identity(self, path: Path, expected_sha256: str) -> None:
        try:
            current_path = path.resolve(strict=True)
            current_sha256 = hashlib.sha256(current_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise FactoryError(f"could not recheck AGY executable identity: {path}", "preflight") from exc
        if current_path != path or current_sha256 != expected_sha256:
            raise FactoryError("AGY executable identity changed during preflight", "preflight")

    @staticmethod
    def _persisted_identities(run_dir: Path) -> list[tuple[str, Path, str]]:
        identities: list[tuple[str, Path, str]] = []
        state_path = run_dir / "run_state.json"
        if state_path.is_file():
            try:
                state = read_json(state_path)
            except Exception as exc:
                raise FactoryError(f"run has invalid state while checking AGY identity: {exc}", "state") from exc
            if not isinstance(state, dict):
                raise FactoryError("run state must be a JSON object while checking AGY identity", "state")
            state_path_value = state.get("agy_executable_path")
            state_sha256 = state.get("agy_executable_sha256")
            if (state_path_value is None) != (state_sha256 is None):
                raise FactoryError("run state has an incomplete pinned AGY identity", "state")
            if state_path_value is not None:
                if not isinstance(state_path_value, str) or not isinstance(state_sha256, str):
                    raise FactoryError("run state has an invalid pinned AGY identity", "state")
                if not Path(state_path_value).expanduser().is_absolute():
                    raise FactoryError("run state AGY executable path must be absolute", "state")
                if not re.fullmatch(r"[0-9a-f]{64}", state_sha256):
                    raise FactoryError("run state has an invalid pinned AGY hash", "state")
                identities.append(("run_state.json", Path(state_path_value), state_sha256))

        evidence_path = run_dir / "preflight_builder.json"
        if evidence_path.is_file():
            try:
                evidence = read_json(evidence_path)
            except Exception as exc:
                raise FactoryError(f"preflight evidence is invalid while checking AGY identity: {exc}", "state") from exc
            if not isinstance(evidence, dict):
                raise FactoryError("preflight evidence must be a JSON object", "state")
            executable = evidence.get("executable")
            if not isinstance(executable, dict):
                if evidence.get("status") == "FAIL":
                    return identities
                raise FactoryError("preflight evidence is missing its pinned AGY identity", "state")
            evidence_path_value = executable.get("path")
            evidence_sha256 = executable.get("sha256")
            if not isinstance(evidence_path_value, str) or not isinstance(evidence_sha256, str):
                raise FactoryError("preflight evidence has an invalid pinned AGY identity", "state")
            if not Path(evidence_path_value).expanduser().is_absolute():
                raise FactoryError("preflight evidence AGY executable path must be absolute", "state")
            if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256):
                raise FactoryError("preflight evidence has an invalid pinned AGY hash", "state")
            identities.append(("preflight_builder.json", Path(evidence_path_value), evidence_sha256))
        return identities

    def _verify_persisted_identity(self, run_dir: Path, path: Path, sha256: str) -> None:
        for source, persisted_path, persisted_sha256 in self._persisted_identities(run_dir):
            try:
                persisted_path = persisted_path.expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise FactoryError(f"{source} points to an unavailable AGY executable", "state") from exc
            if persisted_path != path or persisted_sha256 != sha256:
                raise FactoryError(
                    f"AGY executable identity changed since {source} was recorded",
                    "preflight",
                )

    @staticmethod
    def _parse_probe(
        raw: str,
        probe_dir: Path,
        expected_model: str,
        expected_cwd: str | Path | None = None,
    ) -> dict[str, Any]:
        if "\x00" in raw:
            raise FactoryError("AGY capability probe output contains NUL", "preflight")

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        events: list[dict[str, Any]] = []
        try:
            for line in raw.splitlines():
                if not line.strip():
                    continue
                event = json.loads(line, object_pairs_hook=reject_duplicate_keys)
                if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                    raise ValueError("event must be a JSON object with an event string")
                events.append(event)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise FactoryError(f"AGY capability probe returned malformed stream JSON: {exc}", "preflight") from exc
        if not events:
            raise FactoryError("AGY capability probe returned no events", "preflight")

        init_events = [event for event in events if event.get("event") == "init"]
        result_events = [event for event in events if event.get("event") == "result"]
        if len(init_events) != 1:
            raise FactoryError("AGY capability probe must return exactly one init event", "preflight")
        if len(result_events) != 1:
            raise FactoryError("AGY capability probe must return exactly one terminal result", "preflight")
        if any(event.get("event") not in {"init", "step_update", "result"} for event in events):
            raise FactoryError("AGY capability probe returned an unsupported event", "preflight")
        if events[0].get("event") != "init":
            raise FactoryError("AGY capability probe must begin with init", "preflight")
        if events[-1].get("event") != "result":
            raise FactoryError("AGY capability probe result must be the final event", "preflight")
        if any(event.get("event") not in {"step_update"} for event in events[1:-1]):
            raise FactoryError("AGY capability probe has an event after initialization and before its terminal result", "preflight")

        init = init_events[0].get("init")
        if not isinstance(init, dict):
            raise FactoryError("AGY capability probe init payload is missing", "preflight")
        conversation_id = init_events[0].get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise FactoryError("AGY capability probe init has no conversation identity", "preflight")
        if not isinstance(init.get("model"), str) or init.get("model") != expected_model:
            raise FactoryError("AGY capability probe reported the wrong model", "preflight")
        init_cwd = init.get("cwd")
        if not isinstance(init_cwd, str) or not init_cwd:
            raise FactoryError("AGY capability probe init has no effective cwd", "preflight")
        if expected_cwd is None:
            try:
                effective_cwd = Path(init_cwd).expanduser().resolve()
            except (OSError, RuntimeError) as exc:
                raise FactoryError("AGY capability probe reported an invalid cwd", "preflight") from exc
            expected_cwd_text = str(probe_dir.resolve())
            effective_cwd_text = str(effective_cwd)
        else:
            expected_cwd_text = str(expected_cwd)
            effective_cwd_text = init_cwd
        if os.path.normcase(effective_cwd_text.rstrip("\\/")) != os.path.normcase(expected_cwd_text.rstrip("\\/")):
            raise FactoryError(
                f"AGY capability probe used the wrong cwd: expected {expected_cwd_text}, got {effective_cwd_text}",
                "preflight",
            )
        tools = init.get("tools")
        if (
            not isinstance(tools, list)
            or not tools
            or any(not isinstance(tool, str) or not tool for tool in tools)
        ):
            raise FactoryError("AGY capability probe init is missing audited capability metadata", "preflight")
        if init.get("permission_mode") != AGY_REQUIRED_PERMISSION_MODE:
            raise FactoryError("AGY capability probe reported an unexpected permission mode", "preflight")

        for event in events:
            if event.get("event") == "step_update":
                update = event.get("step_update")
                if (
                    not isinstance(update, dict)
                    or update.get("conversation_id") != conversation_id
                    or isinstance(update.get("step_index"), bool)
                    or not isinstance(update.get("step_index"), (int, float))
                    or not math.isfinite(update["step_index"])
                    or not isinstance(update.get("state"), str)
                    or not isinstance(update.get("step_type"), str)
                ):
                    raise FactoryError("AGY capability probe conversation identity is inconsistent", "preflight")

        result = result_events[0].get("result")
        if not isinstance(result, dict):
            raise FactoryError("AGY capability probe result payload is missing", "preflight")
        required_result_keys = {
            "conversation_id",
            "status",
            "response",
            "duration_seconds",
            "num_turns",
            "usage",
        }
        missing_result_keys = sorted(required_result_keys - set(result))
        if missing_result_keys:
            raise FactoryError(
                f"AGY capability probe result is missing required fields: {missing_result_keys}",
                "preflight",
            )
        if result.get("conversation_id") != conversation_id:
            raise FactoryError("AGY capability probe result has a stale conversation identity", "preflight")
        if result.get("status") != "SUCCESS":
            raise FactoryError("AGY capability probe did not complete successfully", "preflight")
        response = result.get("response")
        if not isinstance(response, str) or response.strip() != "AGY_PREFLIGHT_OK":
            raise FactoryError("AGY capability probe returned an unexpected response", "preflight")
        duration_seconds = result.get("duration_seconds")
        num_turns = result.get("num_turns")
        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds)
            or duration_seconds < 0
            or isinstance(num_turns, bool)
            or not isinstance(num_turns, (int, float))
            or not math.isfinite(num_turns)
            or num_turns <= 0
            or not isinstance(result.get("usage"), dict)
        ):
            raise FactoryError("AGY capability probe result has invalid completion metadata", "preflight")
        if result.get("error"):
            raise FactoryError("AGY capability probe reported a contradictory error", "preflight")

        return {
            "status": "SUCCESS",
            "event_count": len(events),
            "event_sequence": [event["event"] for event in events],
            "effective_model": init["model"],
            "effective_cwd": effective_cwd_text,
            "permission_mode": init["permission_mode"],
            "tool_count": len(init["tools"]),
            "conversation_id_sha256": hashlib.sha256(conversation_id.encode("utf-8")).hexdigest(),
            "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _powershell_single_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def _run_windows_sandbox_probe(
        self,
        path: Path,
        config: Config,
        expected_sha256: str,
    ) -> dict[str, Any]:
        """Run the no-edit probe through the audited Windows Sandbox boundary."""
        sandbox_exe = Path(r"C:\Windows\System32\WindowsSandbox.exe")
        if not sandbox_exe.is_file():
            raise FactoryError(
                "approved Windows Sandbox boundary is unavailable; refusing unrestricted AGY preflight",
                "preflight",
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", config.builder_model):
            raise FactoryError("builder_model is not safe for the sandbox argument contract", "preflight")

        prompt = "Reply with exactly AGY_PREFLIGHT_OK. Do not call tools and do not read or write any files."
        guest_prefix = r"C:\softfac-step5"
        guest_agy = guest_prefix + "\\agy\\" + path.name
        guest_cwd = guest_prefix + r"\cwd"
        guest_output = guest_prefix + r"\output"
        guest_script = guest_prefix + r"\guest\probe.ps1"
        guest_stdout = guest_output + r"\stdout.ndjson"
        guest_stderr = guest_output + r"\stderr.txt"
        guest_done = guest_output + r"\done.json"
        guest_auth = guest_prefix + r"\auth\oauth.json"
        guest_appdata = guest_prefix + r"\appdata"
        guest_temp = guest_prefix + r"\temp"
        ps_quote = self._powershell_single_quote
        arguments = (
            f'--model "{config.builder_model}" '
            "--dangerously-skip-permissions "
            "--output-format stream-json "
            "--disable-slash-commands "
            f"--print-timeout {AGY_PREFLIGHT_PRINT_TIMEOUT_SECONDS}s "
            f'--print "{prompt}"'
        )

        with _probe_temp_root() as raw_root:
            host_root = Path(raw_root).resolve()
            host_cwd = host_root / "cwd"
            host_output = host_root / "output"
            host_guest = host_root / "guest"
            for directory in (host_cwd, host_output, host_guest):
                directory.mkdir()
            try:
                host_auth_token = self._stage_windows_oauth_credential(host_root)
            except OSError as exc:
                raise FactoryError(
                    "approved AGY OAuth credential could not be staged for Windows Sandbox",
                    "preflight",
                ) from exc
            stdout_path = host_output / "stdout.ndjson"
            stderr_path = host_output / "stderr.txt"
            done_path = host_output / "done.json"
            sandbox_script = fr"""$ErrorActionPreference = "Stop"
$stdout = ""
$stderr = ""
$exitCode = 125
$errorText = $null
try {{
{self._guest_oauth_import_script(guest_auth)}
    $appData = {ps_quote(guest_appdata)}
    New-Item -ItemType Directory -Force -Path $appData | Out-Null
    $guestTemp = {ps_quote(guest_temp)}
    New-Item -ItemType Directory -Force -Path $guestTemp | Out-Null
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = {ps_quote(guest_agy)}
    $psi.WorkingDirectory = {ps_quote(guest_cwd)}
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.Arguments = {ps_quote(arguments)}
    $psi.Environment["HOME"] = "C:\Users\WDAGUtilityAccount"
    $psi.Environment["USERPROFILE"] = "C:\Users\WDAGUtilityAccount"
    $psi.Environment["APPDATA"] = "C:\Users\WDAGUtilityAccount\AppData\Roaming"
    $psi.Environment["LOCALAPPDATA"] = "C:\Users\WDAGUtilityAccount\AppData\Local"
    $psi.Environment["JETSKI_APP_DATA_DIR"] = $appData
    $psi.Environment["SystemDrive"] = "C:"
    $psi.Environment["SystemRoot"] = "C:\Windows"
    $psi.Environment["WINDIR"] = "C:\Windows"
    $psi.Environment["ProgramData"] = "C:\ProgramData"
    $psi.Environment["PROGRAMDATA"] = "C:\ProgramData"
    $psi.Environment["ALLUSERSPROFILE"] = "C:\ProgramData"
    $psi.Environment["Path"] = "C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0"
    $psi.Environment["PATH"] = $psi.Environment["Path"]
    $psi.Environment["TEMP"] = $guestTemp
    $psi.Environment["TMP"] = $guestTemp
    $psi.Environment["PYTHONDONTWRITEBYTECODE"] = "1"
    $psi.Environment["PYTHONUTF8"] = "1"
    $psi.Environment["PYTHONIOENCODING"] = "utf-8"
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $process.ExitCode
}} catch {{
    $errorText = $_.Exception.GetType().FullName
}} finally {{
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText({ps_quote(guest_stdout)}, $stdout, $utf8)
    [System.IO.File]::WriteAllText({ps_quote(guest_stderr)}, $stderr, $utf8)
    $done = [ordered]@{{
        schema_version = 1
        exit_code = $exitCode
        error = $errorText
    }}
    [System.IO.File]::WriteAllText({ps_quote(guest_done)}, ($done | ConvertTo-Json -Compress), $utf8)
}}
shutdown.exe /s /t 0 /f | Out-Null
"""
            write_text(host_guest / "probe.ps1", sandbox_script)

            def mapping(host_path: Path, guest_path: str, readonly: bool) -> str:
                readonly_text = "true" if readonly else "false"
                return (
                    "    <MappedFolder>"
                    f"<HostFolder>{xml_escape(str(host_path))}</HostFolder>"
                    f"<SandboxFolder>{xml_escape(guest_path)}</SandboxFolder>"
                    f"<ReadOnly>{readonly_text}</ReadOnly>"
                    "</MappedFolder>"
                )

            mappings = [
                mapping(path.parent, guest_prefix + r"\agy", True),
                mapping(host_cwd, guest_cwd, False),
                mapping(host_output, guest_output, False),
                mapping(host_guest, guest_prefix + r"\guest", True),
                mapping(host_auth_token.parent, guest_prefix + r"\auth", True),
            ]
            sandbox_config = host_root / "probe.wsb"
            config_text = (
                "<Configuration>\n"
                "  <VGpu>Disable</VGpu>\n"
                "  <Networking>Enable</Networking>\n"
                "  <MappedFolders>\n"
                + "\n".join(mappings)
                + "\n  </MappedFolders>\n"
                "  <LogonCommand>\n"
                f"    <Command>{xml_escape('powershell.exe -NoProfile -ExecutionPolicy Bypass -File ' + guest_script)}</Command>\n"
                "  </LogonCommand>\n"
                "</Configuration>\n"
            )
            write_text(sandbox_config, config_text)
            config_sha256 = hashlib.sha256(sandbox_config.read_bytes()).hexdigest()
            before_probe_tree = _snapshot_probe_tree(host_cwd)

            try:
                self._recheck_identity(path, expected_sha256)
                sandbox_process = subprocess.Popen(
                    [str(sandbox_exe), str(sandbox_config)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                raise FactoryError(f"could not start Windows Sandbox: {exc}", "preflight") from exc

            deadline = time.monotonic() + max(180, AGY_PREFLIGHT_PRINT_TIMEOUT_SECONDS + 60)
            while not done_path.is_file() and sandbox_process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.5)
            timed_out = not done_path.is_file()
            if sandbox_process.poll() is None:
                sandbox_process.terminate()
                try:
                    sandbox_process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    sandbox_process.kill()
                    sandbox_process.wait(timeout=15)
            else:
                sandbox_process.wait()
            sandbox_exit_code = sandbox_process.returncode
            if timed_out:
                raise FactoryError(
                    "Windows Sandbox AGY capability probe timed out before host attestation",
                    "preflight",
                )

            try:
                done_payload = json.loads(done_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FactoryError("Windows Sandbox probe produced invalid completion evidence", "preflight") from exc
            if not isinstance(done_payload, dict) or done_payload.get("schema_version") != 1:
                raise FactoryError("Windows Sandbox probe completion evidence has an invalid schema", "preflight")
            exit_code = done_payload.get("exit_code")
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                raise FactoryError("Windows Sandbox probe completion evidence has an invalid exit code", "preflight")
            try:
                stdout_bytes = stdout_path.read_bytes()
                stderr_bytes = stderr_path.read_bytes()
            except OSError as exc:
                raise FactoryError("Windows Sandbox probe did not produce host-attested output", "preflight") from exc
            if exit_code != 0:
                detail = done_payload.get("error")
                if not detail:
                    detail = stderr_bytes.decode("utf-8", errors="replace").strip()[:500]
                detail = detail or f"guest exit code {exit_code}"
                detail = re.sub(r"https?://\S+", "<redacted-url>", str(detail))
                raise FactoryError(f"AGY capability probe failed in Windows Sandbox: {detail}", "preflight")
            try:
                stdout = stdout_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise FactoryError("Windows Sandbox probe stdout is not valid UTF-8", "preflight") from exc
            probe_evidence = self._parse_probe(
                stdout,
                host_cwd,
                config.builder_model,
                expected_cwd=guest_cwd,
            )
            after_probe_tree = _snapshot_probe_tree(host_cwd)
            if before_probe_tree != after_probe_tree:
                raise FactoryError(
                    "AGY capability probe mutated its disposable boundary",
                    "preflight",
                )
            probe_evidence.update(
                {
                    "boundary": "Windows Sandbox",
                    "host_attested": True,
                    "sandbox_config_sha256": config_sha256,
                    "sandbox_process_exit_code": sandbox_exit_code,
                    "guest_cwd": guest_cwd,
                    "auth_state": "host OAuth credential staged read-only; guest imports it into disposable Credential Manager",
                    "disposable_files_created": [],
                    "stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
                    "stderr_empty": not bool(stderr_bytes),
                }
            )
            return probe_evidence

    def _run_linux_bubblewrap_probe(
        self, path: Path, config: Config, expected_sha256: str
    ) -> dict[str, Any]:
        """Authenticate and attest AGY in a disposable Linux namespace."""
        prompt = "Reply with exactly AGY_PREFLIGHT_OK. Do not call tools and do not read or write any files."
        with _probe_temp_root() as raw_root:
            root = Path(raw_root)
            probe_dir = root / "workspace"
            probe_dir.mkdir()
            before = _snapshot_probe_tree(probe_dir)
            stdout_path = root / "stdout.ndjson"
            stderr_path = root / "stderr.txt"
            args = [
                "--model", config.builder_model,
                "--dangerously-skip-permissions", "--output-format", AGY_REQUIRED_OUTPUT_FORMAT,
                "--disable-slash-commands", "--print-timeout",
                f"{AGY_PREFLIGHT_PRINT_TIMEOUT_SECONDS}s", "--print", prompt,
            ]
            try:
                with linux_agy_command(probe_dir, path, args) as (command_line, environment):
                    result = run_builder_process(
                        command_line, cwd=probe_dir, env=environment,
                        timeout=AGY_PREFLIGHT_PRINT_TIMEOUT_SECONDS + 30,
                        stdout_path=stdout_path, stderr_path=stderr_path,
                    )
            except (LinuxBoundaryError, BuilderProcessError) as exc:
                raise FactoryError(f"Linux AGY isolation probe failed: {exc}", "preflight") from exc
            if result.returncode != 0:
                raise FactoryError("Linux AGY isolation probe exited unsuccessfully", "preflight")
            evidence = self._parse_probe(result.stdout, probe_dir, config.builder_model, "/workspace")
            if before != _snapshot_probe_tree(probe_dir):
                raise FactoryError("Linux AGY isolation probe changed its disposable workspace", "preflight")
            self._recheck_identity(path, expected_sha256)
            evidence.update({
                "boundary": "Bubblewrap mount and PID namespace with private one-item Secret Service",
                "guest_cwd": "/workspace",
                "host_home_mapped": False,
                "host_session_bus_mapped": False,
                "credential_mode": "one AGY OAuth item in disposable keyring",
                "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
                "stderr_empty": not bool(result.stderr),
                "disposable_files_created": [],
            })
            return evidence

    @staticmethod
    def _preflight_error_code(value: str) -> str:
        lowered = value.lower()
        if "timed out" in lowered or "timeout" in lowered:
            return "command_timeout"
        if "authentication" in lowered or "login" in lowered:
            return "authentication_unavailable"
        if "identity" in lowered or "hash" in lowered:
            return "identity_mismatch"
        if "model" in lowered:
            return "model_capability_failed"
        if "catalog" in lowered:
            return "model_catalog_failed"
        if "sandbox" in lowered or "probe" in lowered:
            return "capability_probe_failed"
        return "preflight_failed"

    def _write_preflight_failure(self, run_dir: Path, error: str) -> None:
        target = run_dir / "preflight_builder.json"
        if target.is_file():
            try:
                existing = read_json(target)
            except Exception:
                existing = None
            if isinstance(existing, dict) and (
                existing.get("status") == "SUCCESS"
                or (
                    isinstance(existing.get("probe"), dict)
                    and existing["probe"].get("status") == "SUCCESS"
                )
            ):
                target = run_dir / "preflight_builder_failure.json"
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "builder_backend": "agy",
            "status": "FAIL",
            "stage": "capability_preflight",
            "error_category": "preflight",
            "error_code": self._preflight_error_code(error),
            "error": "preflight_failed",
            "failure_message_sha256": hashlib.sha256(error.encode("utf-8")).hexdigest(),
            "credential_mode": "AGY runtime authentication only; no API-key fallback",
        }
        if self.agy_bin is not None and self._pinned_sha256 is not None:
            evidence["executable"] = {
                "path": str(self.agy_bin),
                "sha256": self._pinned_sha256,
            }
        try:
            atomic_json(target, evidence)
        except Exception as exc:
            raise FactoryError(
                f"could not persist AGY preflight failure evidence: {exc}",
                "preflight",
            ) from exc

    def _preflight_command(
        self,
        argv: list[str],
        *,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return command(argv, timeout=timeout)
        except FactoryError as exc:
            raise FactoryError(str(exc), "preflight") from exc

    def preflight(self, config: Config, run_dir: Path) -> dict[str, Any]:
        try:
            return self._preflight(config, run_dir)
        except FactoryError as exc:
            self._write_preflight_failure(run_dir, str(exc))
            raise

    def _preflight(self, config: Config, run_dir: Path) -> dict[str, Any]:
        path, binary_sha256 = self._pin_executable(config)
        self._verify_persisted_identity(run_dir, path, binary_sha256)
        if binary_sha256 != APPROVED_AGY_SHA256:
            raise FactoryError(
                f"AGY executable hash is not an approved audited identity: {binary_sha256}",
                "preflight",
            )
        self._recheck_identity(path, binary_sha256)
        version_result = self._preflight_command([str(path), "--version"], timeout=30)
        if version_result.returncode != 0:
            raise FactoryError(f"AGY --version failed: {(version_result.stderr or version_result.stdout).strip()}", "preflight")
        version = (version_result.stdout or "").strip()
        if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
            raise FactoryError("AGY --version must be a bare semantic version", "preflight")
        if version != SUPPORTED_AGY_VERSION:
            raise FactoryError(f"unsupported AGY version: {version}", "preflight")

        self._recheck_identity(path, binary_sha256)
        help_result = self._preflight_command([str(path), "--help"], timeout=30)
        if help_result.returncode != 0:
            raise FactoryError(f"AGY --help failed: {(help_result.stderr or help_result.stdout).strip()}", "preflight")
        help_text = (help_result.stdout or "") + "\n" + (help_result.stderr or "")
        capability_declarations = _parse_agy_help_capabilities(help_text)
        missing_capabilities = [
            flag for flag in AGY_REQUIRED_CAPABILITIES if flag not in capability_declarations
        ]
        output_format_description = capability_declarations.get("--output-format", "")
        if (
                "--output-format" not in missing_capabilities
            and not re.search(
                rf"(?<![A-Za-z0-9_.-]){re.escape(AGY_REQUIRED_OUTPUT_FORMAT)}(?![A-Za-z0-9_.-])",
                output_format_description,
            )
        ):
            missing_capabilities.append("--output-format=stream-json")
        if missing_capabilities:
            raise FactoryError(f"AGY is missing required capabilities: {missing_capabilities}", "preflight")

        self._recheck_identity(path, binary_sha256)
        models_result = self._preflight_command([str(path), "models"], timeout=60)
        if models_result.returncode != 0:
            raise FactoryError(f"AGY model catalog failed: {(models_result.stderr or models_result.stdout).strip()}", "preflight")
        catalog = _parse_agy_model_catalog(models_result.stdout or "")
        if config.builder_model not in catalog:
            raise FactoryError(f"AGY model catalog does not contain {config.builder_model}", "preflight")

        prompt = "Reply with exactly AGY_PREFLIGHT_OK. Do not call tools and do not read or write any files."
        if len(prompt) > 4096 or "\x00" in prompt:
            raise FactoryError("AGY capability probe prompt is invalid", "preflight")
        if self._probe_runner is not None:
            with tempfile.TemporaryDirectory(prefix="agy-preflight-parent-") as raw_probe_parent:
                probe_parent = Path(raw_probe_parent).resolve()
                probe_root = probe_parent / "root"
                probe_root.mkdir()
                probe_dir = probe_root / "cwd"
                probe_dir.mkdir()
                before_probe_tree = _snapshot_probe_tree(probe_parent)
                self._recheck_identity(path, binary_sha256)
                probe_result = self._probe_runner(path, config, probe_dir)
                if not isinstance(probe_result, dict):
                    raise FactoryError("injected AGY probe runner returned invalid evidence", "preflight")
                return_code = probe_result.get("returncode")
                if isinstance(return_code, bool) or not isinstance(return_code, int):
                    raise FactoryError("injected AGY probe runner returned an invalid exit code", "preflight")
                if return_code != 0:
                    raise FactoryError(
                        f"AGY capability probe failed: {probe_result.get('stderr', '')}",
                        "preflight",
                    )
                raw_probe = probe_result.get("stdout", "")
                if not isinstance(raw_probe, str):
                    raise FactoryError("injected AGY probe runner returned invalid stdout", "preflight")
                probe_evidence = self._parse_probe(raw_probe, probe_dir, config.builder_model)
                after_probe_tree = _snapshot_probe_tree(probe_parent)
                if before_probe_tree != after_probe_tree:
                    raise FactoryError(
                        "AGY capability probe mutated its disposable boundary",
                        "preflight",
                    )
                probe_evidence["disposable_files_created"] = []
                probe_evidence["stdout_sha256"] = hashlib.sha256(raw_probe.encode("utf-8")).hexdigest()
                probe_evidence["stderr_empty"] = not bool(probe_result.get("stderr", ""))
        elif os.name == "nt":
            probe_evidence = self._run_windows_sandbox_probe(path, config, binary_sha256)
        elif sys.platform.startswith("linux"):
            probe_evidence = self._run_linux_bubblewrap_probe(path, config, binary_sha256)
        else:
            raise FactoryError("no approved AGY isolation boundary is available on this platform", "preflight")

        self._verify_persisted_identity(run_dir, path, binary_sha256)
        self._recheck_identity(path, binary_sha256)
        evidence = {
            "schema_version": 1,
            "builder_backend": "agy",
            "executable": {
                "path": str(path),
                "version": version,
                "sha256": binary_sha256,
            },
            "capabilities": {
                "required": list(AGY_REQUIRED_CAPABILITIES),
                "missing": missing_capabilities,
                "declarations": capability_declarations,
                "output_format": AGY_REQUIRED_OUTPUT_FORMAT,
            },
            "model_catalog": {
                "requested_model": config.builder_model,
                "exact_entry": catalog[config.builder_model],
                "models": catalog,
            },
            "probe": probe_evidence,
            "credential_mode": "AGY runtime authentication only; no API-key fallback",
        }
        atomic_json(run_dir / "preflight_builder.json", evidence)
        return evidence

    @staticmethod
    def _builder_label(label: str) -> str:
        if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", label):
            raise BuilderFailure(
                "AGY Builder label is invalid",
                code="agy_protocol_error",
                non_resumable=True,
            )
        return label

    @staticmethod
    def _canonical_builder_worktree(
        worktree: Path,
        config: Config,
        run_dir: Path,
    ) -> tuple[Path, Path, dict[str, Any]]:
        try:
            candidate = Path(worktree).expanduser().resolve(strict=True)
            run_root = Path(run_dir).expanduser().resolve(strict=True)
            source = Path(config.repo).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BuilderFailure(
                "AGY Builder candidate or artifact root is unavailable",
                code="agy_isolation_failed",
                non_resumable=True,
            ) from exc
        if not run_root.is_dir() or not candidate.is_dir() or candidate == source:
            raise BuilderFailure(
                "AGY Builder requires a distinct disposable candidate directory",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        expected_candidate = (run_root / "worktree").resolve(strict=True)
        if candidate != expected_candidate:
            raise BuilderFailure(
                "AGY Builder candidate is not the factory-created run worktree",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        state_path = run_root / "run_state.json"
        try:
            state = read_json(state_path)
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            raise BuilderFailure(
                "AGY Builder candidate provenance state is unavailable",
                code="agy_isolation_failed",
                non_resumable=True,
            ) from exc
        if not isinstance(state, dict):
            raise BuilderFailure(
                "AGY Builder candidate provenance state has an invalid shape",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        if any(
            state.get(key) != value
            for key, value in {
                "schema_version": SCHEMA_VERSION,
                "run_config_version": RUN_CONFIG_VERSION,
                "builder_backend": "agy",
                "builder_contract_version": BUILDER_CONTRACT_VERSION,
            }.items()
        ):
            raise BuilderFailure(
                "AGY Builder candidate provenance has an unapproved run-state schema",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        state_worktree = state.get("worktree")
        if (
            not isinstance(state_worktree, str)
            or Path(state_worktree).expanduser().resolve(strict=False) != candidate
            or state.get("run_id") != run_root.name
            or state.get("factory_worktree_authorized") is not True
        ):
            raise BuilderFailure(
                "AGY Builder candidate provenance does not match the active run",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        def git_common_dir(path: Path) -> str:
            result = command(["git", "rev-parse", "--git-common-dir"], cwd=path, timeout=30)
            if result.returncode != 0:
                raise BuilderFailure(
                    "AGY Builder could not resolve candidate Git common directory",
                    code="agy_isolation_failed",
                    non_resumable=True,
                )
            common = Path(result.stdout.strip())
            if not common.is_absolute():
                common = path / common
            return str(common.resolve(strict=True))

        candidate_common_dir = git_common_dir(candidate)
        source_common_dir = git_common_dir(source)
        expected_common_dir = state.get("candidate_git_common_dir")
        if not isinstance(expected_common_dir, str) or Path(expected_common_dir).resolve() != Path(candidate_common_dir):
            raise BuilderFailure(
                "AGY Builder candidate Git common directory does not match factory provenance",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        if state.get("boundary_test_fixture") is not True and candidate_common_dir != source_common_dir:
            raise BuilderFailure(
                "AGY Builder candidate is not registered with the source repository Git metadata",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        try:
            candidate_head = git(candidate, "rev-parse", "HEAD").stdout.strip()
        except FactoryError as exc:
            raise BuilderFailure(
                "AGY Builder candidate is not a valid Git worktree",
                code="agy_isolation_failed",
                non_resumable=True,
            ) from exc
        state_base = state.get("base_commit")
        if isinstance(state_base, str) and state_base and state_base != candidate_head:
            raise BuilderFailure(
                "AGY Builder candidate HEAD does not match the run baseline",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        def nested(left: Path, right: Path) -> bool:
            try:
                left.relative_to(right)
                return True
            except ValueError:
                return False

        if nested(source, run_root) or nested(run_root, source):
            raise BuilderFailure(
                "AGY Builder source and run roots are not disjoint",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        try:
            run_root.relative_to(candidate)
        except ValueError:
            pass
        else:
            raise BuilderFailure(
                "AGY Builder artifacts must be outside the candidate directory",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        return candidate, run_root, {
            "candidate_path": str(candidate),
            "run_root": str(run_root),
            "source_path": str(source),
            "run_id": state.get("run_id"),
            "branch": state.get("branch"),
            "baseline_head": candidate_head,
            "factory_worktree_authorized": True,
            "expected_baseline_identity": state.get("candidate_baseline_identity"),
            "candidate_git_common_dir": candidate_common_dir,
        }

    @staticmethod
    def _candidate_baseline_identity(candidate: Path) -> dict[str, Any]:
        status = command(
            [
                "git",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignored=matching",
            ],
            cwd=candidate,
            timeout=30,
        )
        if status.returncode != 0:
            raise FactoryError("could not capture the candidate baseline status", "isolation")
        staged = command(["git", "diff", "--cached", "--binary", "--no-ext-diff"], cwd=candidate, timeout=30)
        unstaged = command(["git", "diff", "--binary", "--no-ext-diff"], cwd=candidate, timeout=30)
        head = command(["git", "rev-parse", "HEAD"], cwd=candidate, timeout=30)
        tree = command(["git", "rev-parse", "HEAD^{tree}"], cwd=candidate, timeout=30)
        if any(result.returncode != 0 for result in (staged, unstaged, head, tree)):
            raise FactoryError("could not capture the complete candidate baseline", "isolation")
        status_text = status.stdout
        status_records = [record for record in status_text.split("\0") if record]
        status_files: dict[str, dict[str, Any]] = {}
        for record in status_records:
            if len(record) < 4 or record.startswith("##"):
                continue
            relative = record[3:].replace("\\", "/")
            if " -> " in relative:
                relative = relative.rsplit(" -> ", 1)[-1]
            if not relative:
                continue
            path = candidate / relative.rstrip("/")
            if path.is_symlink():
                status_files[relative] = {"kind": "symlink", "target": os.readlink(path)}
            elif path.is_file():
                data = path.read_bytes()
                status_files[relative] = {
                    "kind": "file",
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            elif path.is_dir():
                status_files[relative] = {"kind": "directory"}
            else:
                status_files[relative] = {"kind": "missing"}
        filesystem_snapshot: dict[str, dict[str, Any]] = {}
        for item in candidate.rglob("*"):
            relative_path = item.relative_to(candidate)
            if ".git" in relative_path.parts:
                continue
            relative = relative_path.as_posix()
            if item.is_symlink():
                filesystem_snapshot[relative] = {
                    "kind": "symlink",
                    "target": os.readlink(item),
                }
            elif item.is_file():
                data = item.read_bytes()
                filesystem_snapshot[relative] = {
                    "kind": "file",
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            elif item.is_dir():
                filesystem_snapshot[relative] = {"kind": "directory"}
        identity_material = {
            "head": head.stdout.strip(),
            "tree": tree.stdout.strip(),
            "status_sha256": hashlib.sha256(status_text.encode("utf-8")).hexdigest(),
            "status_records": status_records,
            "status_files": status_files,
            "filesystem_snapshot": filesystem_snapshot,
            "staged_diff_sha256": hashlib.sha256(staged.stdout.encode("utf-8")).hexdigest(),
            "unstaged_diff_sha256": hashlib.sha256(unstaged.stdout.encode("utf-8")).hexdigest(),
        }
        identity = hashlib.sha256(
            json.dumps(identity_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            **identity_material,
            "complete_identity_sha256": identity,
            "clean": not status_records and not staged.stdout and not unstaged.stdout,
        }

    @staticmethod
    def _builder_file_snapshot(worktree: Path, allowed_files: list[str]) -> dict[str, dict[str, Any]]:
        snapshot: dict[str, dict[str, Any]] = {}
        for relative in allowed_files:
            path = worktree / relative
            if path.is_symlink():
                snapshot[relative] = {"kind": "symlink", "target": os.readlink(path)}
            elif path.is_file():
                data = path.read_bytes()
                snapshot[relative] = {
                    "kind": "file",
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            elif path.exists():
                snapshot[relative] = {"kind": "other"}
            else:
                snapshot[relative] = {"kind": "missing"}
        return snapshot

    @staticmethod
    def _builder_attempt_path(run_root: Path, label: str) -> Path:
        attempts = run_root / "builder_attempts"
        attempts.mkdir(parents=True, exist_ok=True, mode=0o700)
        attempt = attempts / f"{label}-{uuid.uuid4().hex}"
        attempt.mkdir(mode=0o700)
        return attempt

    @staticmethod
    def _builder_process_failure_code(error: BuilderProcessError) -> str:
        code = getattr(error, "failure_code", None)
        if isinstance(code, str) and code:
            return code
        return "agy_runtime_error"

    @staticmethod
    def _builder_attempt_failure(
        attempt_path: Path,
        attempt: dict[str, Any],
        *,
        code: str,
        message: str,
    ) -> BuilderFailure:
        attempt["status"] = "FAILURE"
        attempt["failure_code"] = code
        attempt["termination_reason"] = _normalized_agy_outcome(code)
        attempt["failure_message"] = "builder_failed"
        evidence_file = attempt_path / "attempt.json"
        persisted = False
        try:
            atomic_json(evidence_file, attempt)
            persisted = evidence_file.is_file()
        except Exception:
            pass
        return BuilderFailure(
            message,
            code=code,
            non_resumable=True,
            evidence_path=str(evidence_file) if persisted else None,
        )

    @staticmethod
    def _persisted_conversation_hashes(run_root: Path) -> set[str]:
        hashes: set[str] = set()
        attempts = run_root / "builder_attempts"
        if not attempts.is_dir() or attempts.is_symlink():
            return hashes
        try:
            entries = list(attempts.iterdir())
        except OSError as exc:
            raise BuilderFailure(
                "AGY Builder reservation evidence directory is unreadable",
                code="agy_protocol_error",
                non_resumable=True,
            ) from exc
        for attempt_dir in entries:
            if attempt_dir.is_symlink() or not attempt_dir.is_dir():
                raise BuilderFailure(
                    "AGY Builder reservation evidence directory is ambiguous",
                    code="agy_protocol_error",
                    non_resumable=True,
                )
            evidence_path = attempt_dir / "attempt.json"
            if not evidence_path.is_file() or evidence_path.is_symlink():
                raise BuilderFailure(
                    "AGY Builder reservation evidence is incomplete",
                    code="agy_protocol_error",
                    non_resumable=True,
                )
            try:
                evidence = read_json(evidence_path)
            except (OSError, json.JSONDecodeError, UnicodeError) as exc:
                raise BuilderFailure(
                    "AGY Builder reservation evidence is invalid",
                    code="agy_protocol_error",
                    non_resumable=True,
                ) from exc
            if not isinstance(evidence, dict):
                raise BuilderFailure(
                    "AGY Builder reservation evidence has an invalid shape",
                    code="agy_protocol_error",
                    non_resumable=True,
                )
            values: list[Any] = []
            singular = evidence.get("conversation_id_sha256")
            plural = evidence.get("conversation_id_sha256s")
            if singular is not None:
                values.append(singular)
            if plural is not None:
                if not isinstance(plural, list):
                    raise BuilderFailure(
                        "AGY Builder reservation evidence has an invalid identity list",
                        code="agy_protocol_error",
                        non_resumable=True,
                    )
                values.extend(plural)
            for value in values:
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    raise BuilderFailure(
                        "AGY Builder reservation evidence has an invalid identity hash",
                        code="agy_protocol_error",
                        non_resumable=True,
                    )
                hashes.add(value)
        return hashes

    @staticmethod
    def _protected_host_snapshot(source: Path, run_root: Path) -> dict[str, Any]:
        try:
            source_head = git(source, "rev-parse", "HEAD").stdout.strip()
            source_status = git(
                source, "status", "--porcelain=v1", "--untracked-files=all"
            ).stdout
        except FactoryError as exc:
            raise BuilderFailure(
                "AGY Builder could not attest the protected source checkout",
                code="agy_isolation_failed",
                non_resumable=True,
            ) from exc
        state_path = run_root / "run_state.json"
        try:
            state_bytes = state_path.read_bytes()
        except OSError as exc:
            raise BuilderFailure(
                "AGY Builder could not attest protected run state",
                code="agy_isolation_failed",
                non_resumable=True,
            ) from exc
        return {
            "source_head": source_head,
            "source_status_sha256": hashlib.sha256(source_status.encode("utf-8")).hexdigest(),
            "source_status_clean": not source_status.strip(),
            "run_state_sha256": hashlib.sha256(state_bytes).hexdigest(),
        }

    @staticmethod
    def _sandbox_host_environment() -> dict[str, str]:
        # Windows environment names are case-insensitive.  Preserve the
        # inherited spelling while matching the minimal launcher allowlist in
        # a case-insensitive way; omitting SYSTEMROOT makes legacy
        # WindowsPowerShell fail before WindowsSandbox.exe is started.
        allowed = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
        return {
            key: value
            for key, value in os.environ.items()
            if key.upper() in allowed and isinstance(value, str) and "\x00" not in value
        }

    @staticmethod
    def _read_windows_oauth_credential() -> bytes:
        """Read the approved host OAuth credential without exposing its value."""
        if os.name != "nt":
            raise OSError("Windows Credential Manager is unavailable on this platform")
        import ctypes
        import ctypes.wintypes as wintypes

        class Credential(ctypes.Structure):
            pass

        credential_pointer = ctypes.POINTER(Credential)
        Credential._fields_ = [
            ("flags", wintypes.DWORD),
            ("type", wintypes.DWORD),
            ("target_name", wintypes.LPWSTR),
            ("comment", wintypes.LPWSTR),
            ("last_written", wintypes.FILETIME),
            ("credential_blob_size", wintypes.DWORD),
            ("credential_blob", ctypes.POINTER(ctypes.c_ubyte)),
            ("persist", wintypes.DWORD),
            ("attribute_count", wintypes.DWORD),
            ("attributes", ctypes.c_void_p),
            ("target_alias", wintypes.LPWSTR),
            ("user_name", wintypes.LPWSTR),
        ]
        read = ctypes.windll.advapi32.CredReadW
        read.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(credential_pointer)]
        read.restype = wintypes.BOOL
        free = ctypes.windll.advapi32.CredFree
        free.argtypes = [credential_pointer]
        credential = credential_pointer()
        if not read("gemini:antigravity", 1, 0, ctypes.byref(credential)):
            raise OSError(ctypes.get_last_error(), "approved host AGY OAuth credential is unavailable")
        try:
            size = int(credential.contents.credential_blob_size)
            if size <= 0 or size > 64 * 1024:
                raise OSError("approved host AGY OAuth credential has an invalid size")
            data = ctypes.string_at(credential.contents.credential_blob, size)
        finally:
            free(credential)
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OSError("approved host AGY OAuth credential is malformed") from exc
        token = payload.get("token") if isinstance(payload, dict) else None
        if (
            not isinstance(token, dict)
            or not isinstance(token.get("access_token"), str)
            or not token.get("access_token")
            or not isinstance(token.get("refresh_token"), str)
            or not token.get("refresh_token")
        ):
            raise OSError("approved host AGY OAuth credential has an invalid token payload")
        return data

    @classmethod
    def _stage_windows_oauth_credential(cls, host_root: Path) -> Path:
        """Stage one private, disposable OAuth handoff for the Sandbox guest."""
        data = cls._read_windows_oauth_credential()
        auth_root = host_root / "auth"
        auth_root.mkdir(mode=0o700)
        temporary = auth_root / "oauth.json.tmp"
        token_path = auth_root / "oauth.json"
        temporary.write_bytes(data)
        temporary.replace(token_path)
        return token_path

    @staticmethod
    def _guest_oauth_import_script(guest_token_path: str) -> str:
        """Return a guest-only Credential Manager import with no token literal."""
        return f'''$oauthToken = [System.IO.File]::ReadAllText({AgyBuilder._powershell_single_quote(guest_token_path)})
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class GuestOAuthCredential {{
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct CREDENTIAL {{
    public UInt32 Flags; public UInt32 Type; public string TargetName; public string Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten; public UInt32 CredentialBlobSize;
    public IntPtr CredentialBlob; public UInt32 Persist; public UInt32 AttributeCount;
    public IntPtr Attributes; public string TargetAlias; public string UserName;
  }}
  [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern bool CredWrite(ref CREDENTIAL credential, UInt32 flags);
  public static void Write(string value) {{
    byte[] bytes = Encoding.UTF8.GetBytes(value);
    IntPtr blob = Marshal.AllocHGlobal(bytes.Length);
    try {{
      Marshal.Copy(bytes, 0, blob, bytes.Length);
      CREDENTIAL credential = new CREDENTIAL();
      credential.Type = 1; credential.TargetName = "gemini:antigravity";
      credential.UserName = "antigravity"; credential.CredentialBlob = blob;
      credential.CredentialBlobSize = (UInt32)bytes.Length; credential.Persist = 2;
      if (!CredWrite(ref credential, 0))
        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    }} finally {{ Marshal.FreeHGlobal(blob); }}
  }}
}}
"@
[GuestOAuthCredential]::Write($oauthToken)
'''

    @staticmethod
    def _read_bounded_guest_file(path: Path, limit: int) -> tuple[bytes, bool]:
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                data = handle.read(limit)
        except OSError as exc:
            raise BuilderProcessError(
                "isolated AGY output evidence is unavailable",
                stdout_path=path,
                stderr_path=path,
                failure_code="agy_output_incomplete",
            ) from exc
        return data, size > limit

    @staticmethod
    def _copy_sandbox_candidate(
        source: Path, mirror: Path, visible_files: list[str] | None = None
    ) -> None:
        """Copy candidate content into a disposable guest-facing mirror."""
        mirror.mkdir(mode=0o700)

        def copy_entry(source_entry: Path, mirror_entry: Path) -> None:
            if source_entry.is_symlink():
                raise OSError(f"candidate mirror refuses symlink: {source_entry}")
            if source_entry.is_dir():
                mirror_entry.mkdir(mode=0o700)
                for child in sorted(source_entry.iterdir(), key=lambda item: item.name.casefold()):
                    if child.name == ".git":
                        continue
                    copy_entry(child, mirror_entry / child.name)
                return
            if source_entry.is_file():
                shutil.copy2(source_entry, mirror_entry)
                return
            raise OSError(f"candidate mirror refuses unsupported entry: {source_entry}")

        if visible_files is None:
            for entry in sorted(source.iterdir(), key=lambda item: item.name.casefold()):
                if entry.name == ".git":
                    continue
                copy_entry(entry, mirror / entry.name)
            return
        for relative in sorted(set(visible_files)):
            normalized = normalize_path(relative)
            entry = source / Path(normalized)
            if not entry.exists():
                continue
            if entry.is_dir() or entry.is_symlink():
                raise OSError(f"capsule mirror refuses non-file visible path: {normalized}")
            target = mirror / Path(normalized)
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_entry(entry, target)

    @staticmethod
    def _validate_capsule_surface_delta(
        before: dict[str, dict[str, Any]],
        after: dict[str, dict[str, Any]],
        *,
        stdout_path: Path,
        stderr_path: Path,
    ) -> None:
        """Reject every capsule filesystem change except the editable target."""
        changed = sorted(
            relative
            for relative in set(before) | set(after)
            if before.get(relative) != after.get(relative)
        )
        unexpected = [
            relative for relative in changed if relative != CAPSULE_EDITABLE_FILE
        ]
        target_before = before.get(CAPSULE_EDITABLE_FILE)
        target_after = after.get(CAPSULE_EDITABLE_FILE)
        if (
            unexpected
            or not isinstance(target_before, dict)
            or target_before.get("kind") != "file"
            or not isinstance(target_after, dict)
            or target_after.get("kind") != "file"
        ):
            raise BuilderProcessError(
                "isolated AGY capsule changed an unauthorized filesystem path",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                failure_code="agy_isolation_failed",
            )

    @staticmethod
    def _sync_sandbox_candidate(
        candidate: Path,
        mirror: Path,
        allowed_files: list[str],
        before: dict[str, dict[str, Any]],
        host_baseline_identity: dict[str, Any] | None = None,
        *,
        stdout_path: Path,
        stderr_path: Path,
    ) -> dict[str, Any]:
        """Copy only allowed guest edits back after classifying mirror changes."""
        if isinstance(host_baseline_identity, dict):
            current_identity = AgyBuilder._candidate_baseline_identity(candidate)
            if current_identity.get("complete_identity_sha256") != host_baseline_identity.get(
                "complete_identity_sha256"
            ):
                raise BuilderProcessError(
                    "host candidate changed while AGY mirror was running",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
        after = _snapshot_probe_tree(mirror)
        changed = sorted(
            relative
            for relative in set(before) | set(after)
            if before.get(relative) != after.get(relative)
        )
        allowed = {relative.replace("\\", "/") for relative in allowed_files}
        allowed_parent_dirs: set[str] = set()
        for relative in allowed:
            parent = PurePosixPath(relative).parent
            while str(parent) not in {"", "."}:
                allowed_parent_dirs.add(str(parent))
                parent = parent.parent
        unexpected = [
            relative
            for relative in changed
            if relative not in allowed and relative not in allowed_parent_dirs
        ]
        if unexpected:
            raise BuilderProcessError(
                "isolated AGY candidate mirror changed an out-of-scope path",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                failure_code="agy_isolation_failed",
            )

        sync_plan: list[tuple[str, Path, Path]] = []
        for relative in sorted(allowed & set(changed)):
            mirror_path = mirror / Path(relative)
            candidate_path = candidate / Path(relative)
            if mirror_path.is_symlink() or candidate_path.is_symlink():
                raise BuilderProcessError(
                    "isolated AGY candidate synchronization encountered a symlink",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            if mirror_path.is_file():
                if candidate_path.exists() and not candidate_path.is_file():
                    raise BuilderProcessError(
                        "isolated AGY candidate synchronization encountered an unsupported target",
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        failure_code="agy_isolation_failed",
                    )
                sync_plan.append((relative, mirror_path, candidate_path))
            elif mirror_path.exists():
                raise BuilderProcessError(
                    "isolated AGY candidate synchronization encountered an unsupported source",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            elif candidate_path.exists():
                if not candidate_path.is_file():
                    raise BuilderProcessError(
                        "isolated AGY candidate synchronization cannot remove a non-file target",
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        failure_code="agy_isolation_failed",
                    )
                sync_plan.append((relative, mirror_path, candidate_path))

        def is_allowed_path_or_parent(relative: str) -> bool:
            path = PurePosixPath(relative)
            return any(
                path == PurePosixPath(target) or path in PurePosixPath(target).parents
                for target in allowed
            )

        def current_host_identity() -> dict[str, Any] | None:
            if not isinstance(host_baseline_identity, dict):
                return None
            return AgyBuilder._candidate_baseline_identity(candidate)

        def assert_reserved_host_identity() -> dict[str, Any] | None:
            current_identity = current_host_identity()
            if current_identity is None:
                return None
            if current_identity.get("complete_identity_sha256") != host_baseline_identity.get(
                "complete_identity_sha256"
            ):
                raise BuilderProcessError(
                    "host candidate changed while AGY mirror was running",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            return current_identity

        assert_reserved_host_identity()
        transaction_root = Path(tempfile.mkdtemp(prefix=".softfac-candidate-sync-", dir=str(candidate.parent)))
        staged_root = transaction_root / "staged"
        backup_root = transaction_root / "backup"
        backups: list[tuple[Path, Path, bool]] = []
        applied: list[tuple[Path, Path, bool]] = []
        applied_targets: set[str] = set()
        desired_targets: dict[str, dict[str, Any]] = {}
        target_before: dict[str, dict[str, Any]] = {}

        @contextmanager
        def hold_target(target: Path) -> Iterable[int | None]:
            """Prevent a cooperating host writer from racing a target replacement."""
            if not isinstance(host_baseline_identity, dict) or os.name != "nt" or not target.is_file():
                yield None
                return
            import ctypes
            import ctypes.wintypes as wintypes
            import msvcrt

            kernel32 = ctypes.windll.kernel32
            create_file = kernel32.CreateFileW
            create_file.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            create_file.restype = wintypes.HANDLE
            handle = create_file(
                str(target),
                0xC0000000,  # GENERIC_READ | GENERIC_WRITE
                0x00000005,  # FILE_SHARE_READ | FILE_SHARE_DELETE; writers are excluded
                None,
                3,  # OPEN_EXISTING
                0x00000080,  # FILE_ATTRIBUTE_NORMAL
                None,
            )
            invalid_handle = ctypes.c_void_p(-1).value
            handle_value = handle.value if hasattr(handle, "value") else int(handle)
            if not handle_value or handle_value == invalid_handle:
                raise OSError(ctypes.get_last_error(), "could not reserve candidate target")
            try:
                fd = msvcrt.open_osfhandle(handle_value, os.O_RDWR | os.O_BINARY)
            except OSError:
                kernel32.CloseHandle(handle)
                raise
            lock_length = 0x7FFFFFFF
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, lock_length)
                try:
                    yield fd
                finally:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, lock_length)
            finally:
                os.close(fd)

        def target_matches_desired(relative: str, target_fd: int | None = None) -> bool:
            expected = desired_targets.get(relative)
            if expected is None:
                return False
            target = candidate / Path(relative)
            if expected["kind"] == "missing":
                return not target.exists() and not target.is_symlink()
            return target_snapshot(target, target_fd) == expected

        def target_snapshot(target: Path, target_fd: int | None = None) -> dict[str, Any]:
            if target_fd is not None:
                os.lseek(target_fd, 0, os.SEEK_SET)
                data = os.read(target_fd, max(1, os.fstat(target_fd).st_size))
            elif target.is_file():
                data = target.read_bytes()
            else:
                return {"kind": "missing"}
            return {
                "kind": "file",
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }

        for relative, _, candidate_path in sync_plan:
            if candidate_path.is_symlink():
                raise BuilderProcessError(
                    "isolated AGY candidate synchronization encountered a symlink",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            if candidate_path.is_file():
                target_before[relative] = {
                    "kind": "file",
                    "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                    "size": candidate_path.stat().st_size,
                }
            elif candidate_path.exists():
                target_before[relative] = {"kind": "other"}
            else:
                target_before[relative] = {"kind": "missing"}
        created_dirs: list[Path] = []
        try:
            for relative, mirror_path, candidate_path in sync_plan:
                if mirror_path.is_file():
                    staged_path = staged_root / Path(relative)
                    staged_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(mirror_path, staged_path)
                    staged_source = staged_path
                    data = mirror_path.read_bytes()
                    desired_targets[relative] = {
                        "kind": "file",
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                else:
                    staged_source = mirror_path
                    desired_targets[relative] = {"kind": "missing"}
                if candidate_path.is_symlink():
                    raise BuilderProcessError(
                        "isolated AGY candidate synchronization encountered a symlink",
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                        failure_code="agy_isolation_failed",
                    )
                existed = candidate_path.is_file()
                backup_path = backup_root / Path(relative)
                if existed:
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate_path, backup_path)
                backups.append((candidate_path, backup_path, existed))
                applied.append((candidate_path, staged_source, existed))

            for candidate_path, staged_source, existed in applied:
                relative = str(candidate_path.relative_to(candidate)).replace("\\", "/")
                with hold_target(candidate_path) as target_fd:
                    current_target = target_before.get(relative, {"kind": "missing"})
                    if current_target.get("kind") == "file" and target_snapshot(
                        candidate_path, target_fd
                    ) != current_target:
                        raise BuilderProcessError(
                            "host candidate target changed during AGY synchronization",
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                            failure_code="agy_isolation_failed",
                        )
                    if current_target.get("kind") == "missing" and candidate_path.exists():
                        raise BuilderProcessError(
                            "host candidate target appeared during AGY synchronization",
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                            failure_code="agy_isolation_failed",
                        )
                    if staged_source.is_file():
                        parent = candidate_path.parent
                        missing_parents: list[Path] = []
                        while not parent.exists() and parent != candidate:
                            missing_parents.append(parent)
                            parent = parent.parent
                        candidate_path.parent.mkdir(parents=True, exist_ok=True)
                        created_dirs.extend(reversed(missing_parents))
                        _replace_candidate_file(
                            staged_source,
                            candidate_path,
                            race_safe=isinstance(host_baseline_identity, dict),
                            expected_target=current_target,
                            target_fd=target_fd,
                        )
                        applied_targets.add(relative)
                    elif candidate_path.exists():
                        candidate_path.unlink()
                        applied_targets.add(relative)
            post_identity = current_host_identity()
            if post_identity is not None:
                for field in ("status_files", "filesystem_snapshot"):
                    before_entries = {
                        path: value
                        for path, value in host_baseline_identity.get(field, {}).items()
                        if not is_allowed_path_or_parent(path)
                    }
                    after_entries = {
                        path: value
                        for path, value in post_identity.get(field, {}).items()
                        if not is_allowed_path_or_parent(path)
                    }
                    if before_entries != after_entries:
                        raise BuilderProcessError(
                            "host candidate changed outside the allowed synchronization targets",
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                            failure_code="agy_isolation_failed",
                        )
                for relative in desired_targets:
                    if not target_matches_desired(relative):
                        raise BuilderProcessError(
                            "host candidate target changed during AGY synchronization",
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                            failure_code="agy_isolation_failed",
                        )
            return {
                "mode": "disposable_candidate_mirror",
                "transaction": "prepared-then-replace-with-rollback",
                "allowed_files_synchronized": [relative for relative, _, _ in sync_plan],
                "unexpected_guest_change_count": 0,
            }
        except (BuilderProcessError, OSError, RuntimeError) as exc:
            rollback_error: BaseException | None = None
            for candidate_path, backup_path, existed in reversed(backups):
                try:
                    relative = str(candidate_path.relative_to(candidate)).replace("\\", "/")
                    if relative not in applied_targets:
                        continue
                    if not target_matches_desired(relative):
                        continue
                    with hold_target(candidate_path) as target_fd:
                        if not target_matches_desired(relative, target_fd):
                            continue
                        if existed:
                            _replace_candidate_file(
                                backup_path,
                                candidate_path,
                                race_safe=isinstance(host_baseline_identity, dict),
                            )
                        elif candidate_path.exists() or candidate_path.is_symlink():
                            candidate_path.unlink()
                except (OSError, RuntimeError) as rollback_exc:
                    rollback_error = rollback_exc
                    break
            if rollback_error is not None:
                raise BuilderProcessError(
                    "isolated AGY candidate synchronization could not be rolled back",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from rollback_error
            if isinstance(exc, BuilderProcessError):
                raise
            raise BuilderProcessError(
                "isolated AGY candidate synchronization failed before commit",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                failure_code="agy_isolation_failed",
            ) from exc
        finally:
            for directory in sorted(created_dirs, key=lambda item: len(item.parts), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            shutil.rmtree(transaction_root, ignore_errors=True)

    def _run_windows_sandbox_builder(
        self,
        *,
        path: Path,
        config: Config,
        candidate: Path,
        instruction: str,
        stdout_path: Path,
        stderr_path: Path,
        allowed_files: list[str] | None = None,
        host_baseline_identity: dict[str, Any] | None = None,
        run_root: Path | None = None,
        pre_sync_acceptance: Callable[..., None] | None = None,
        surface: dict[str, Any] | None = None,
        capsule_reintegrator: Callable[[Path], dict[str, Any]] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str, dict[str, Any]]:
        """Run AGY in the approved disposable Windows Sandbox boundary."""
        sandbox_exe = Path(r"C:\Windows\System32\WindowsSandbox.exe")
        if not sandbox_exe.is_file():
            raise BuilderProcessError(
                "approved Windows Sandbox boundary is unavailable",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                failure_code="agy_isolation_failed",
            )
        guest_prefix = r"C:\softfac-step7"
        guest_candidate = guest_prefix + r"\candidate"
        guest_agy = guest_prefix + "\\agy\\" + path.name
        guest_output = guest_prefix + r"\output"
        guest_guest = guest_prefix + r"\guest"
        guest_stdout = guest_output + r"\stdout.txt"
        guest_stderr = guest_output + r"\stderr.txt"
        guest_done = guest_output + r"\done.json"
        guest_auth = guest_prefix + r"\auth\oauth.json"
        guest_runtime = guest_prefix + r"\runtime"
        guest_appdata = guest_runtime + r"\appdata"
        guest_temp = guest_runtime + r"\temp"
        ps_quote = self._powershell_single_quote
        inner_args = [
            "--model",
            config.builder_model,
            "--dangerously-skip-permissions",
            "--output-format",
            AGY_REQUIRED_OUTPUT_FORMAT,
            "--disable-slash-commands",
            "--print-timeout",
            f"{min(AGY_PREFLIGHT_PRINT_TIMEOUT_SECONDS, max(config.builder_timeout - 10, 1))}s",
            "--print",
            instruction,
        ]
        serialized_arguments = subprocess.list2cmdline(inner_args)
        guest_script = fr'''$ErrorActionPreference = "Stop"
$stdoutPath = {ps_quote(guest_stdout)}
$stderrPath = {ps_quote(guest_stderr)}
$donePath = {ps_quote(guest_done)}
$utf8 = New-Object System.Text.UTF8Encoding($false)
$exitCode = 125
$errorType = $null
$errorHash = $null
try {{
{self._guest_oauth_import_script(guest_auth)}
    $appData = {ps_quote(guest_appdata)}
    New-Item -ItemType Directory -Force -Path $appData | Out-Null
    $guestTemp = {ps_quote(guest_temp)}
    New-Item -ItemType Directory -Force -Path $guestTemp | Out-Null
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = {ps_quote(guest_agy)}
    $psi.WorkingDirectory = {ps_quote(guest_candidate)}
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.Arguments = {ps_quote(serialized_arguments)}
    $blocked = @("AGY_", "AIDER_", "OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_", "HTTP_PROXY", "HTTPS_PROXY")
    foreach ($key in @($psi.Environment.Keys)) {{
        if ($blocked | Where-Object {{ $key -eq $_ -or $key.StartsWith($_) }}) {{ $psi.Environment.Remove($key) }}
    }}
    $psi.Environment["HOME"] = "C:\Users\WDAGUtilityAccount"
    $psi.Environment["USERPROFILE"] = "C:\Users\WDAGUtilityAccount"
    $psi.Environment["APPDATA"] = "C:\Users\WDAGUtilityAccount\AppData\Roaming"
    $psi.Environment["LOCALAPPDATA"] = "C:\Users\WDAGUtilityAccount\AppData\Local"
    $psi.Environment["JETSKI_APP_DATA_DIR"] = $appData
    $psi.Environment["SystemDrive"] = "C:"
    $psi.Environment["SystemRoot"] = "C:\Windows"
    $psi.Environment["WINDIR"] = "C:\Windows"
    $psi.Environment["ProgramData"] = "C:\ProgramData"
    $psi.Environment["PROGRAMDATA"] = "C:\ProgramData"
    $psi.Environment["ALLUSERSPROFILE"] = "C:\ProgramData"
    $psi.Environment["Path"] = "C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0"
    $psi.Environment["PATH"] = $psi.Environment["Path"]
    $psi.Environment["TEMP"] = $guestTemp
    $psi.Environment["TMP"] = $guestTemp
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $process.StandardInput.Close()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    [System.IO.File]::WriteAllText($stdoutPath, $stdout, $utf8)
    [System.IO.File]::WriteAllText($stderrPath, $stderr, $utf8)
    $exitCode = $process.ExitCode
}} catch {{
    $errorType = $_.Exception.GetType().FullName
    $errorHash = [System.BitConverter]::ToString((New-Object System.Security.Cryptography.SHA256Managed).ComputeHash([System.Text.Encoding]::UTF8.GetBytes([string]$_.Exception.Message))).Replace("-", "").ToLowerInvariant()
}} finally {{
    $done = [ordered]@{{ schema_version = 1; exit_code = $exitCode; error_type = $errorType; error_sha256 = $errorHash }}
    [System.IO.File]::WriteAllText($donePath, ($done | ConvertTo-Json -Compress), $utf8)
    shutdown.exe /s /t 0 /f | Out-Null
}}
'''
        with _probe_temp_root() as raw_root:
            host_root = Path(raw_root).resolve()
            host_guest = host_root / "guest"
            host_output = host_root / "output"
            host_agy = host_root / "agybin"
            host_candidate = host_root / "candidate"
            host_runtime = host_root / "runtime"
            host_guest.mkdir()
            host_output.mkdir()
            host_agy.mkdir()
            surface_kind = surface.get("kind", "normal") if isinstance(surface, dict) else "normal"
            visible_files = surface.get("visible_files") if isinstance(surface, dict) else None
            if visible_files is not None and (
                not isinstance(visible_files, list)
                or any(not isinstance(item, str) for item in visible_files)
            ):
                raise BuilderProcessError(
                    "AGY surface has invalid visible-file metadata",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            try:
                if surface_kind == "python_capsule":
                    editable_file = surface.get("editable_file") if isinstance(surface, dict) else None
                    capsule_source = surface.get("capsule_source") if isinstance(surface, dict) else None
                    if editable_file != CAPSULE_EDITABLE_FILE or not isinstance(capsule_source, str):
                        raise OSError("invalid Python capsule surface")
                    host_candidate.mkdir(parents=True, exist_ok=True)
                    target = host_candidate / CAPSULE_EDITABLE_FILE
                    target.write_text(capsule_source, encoding="utf-8")
                else:
                    self._copy_sandbox_candidate(candidate, host_candidate, visible_files)
                mirror_before = _snapshot_probe_tree(host_candidate)
            except (OSError, RuntimeError) as exc:
                raise BuilderProcessError(
                    "candidate could not be copied into the disposable isolated mirror",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from exc
            host_runtime.mkdir()
            try:
                host_auth_token = self._stage_windows_oauth_credential(host_root)
            except OSError as exc:
                raise BuilderProcessError(
                    "approved AGY OAuth credential could not be staged for the isolated boundary",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from exc
            staged_binary = host_agy / path.name
            try:
                shutil.copyfile(path, staged_binary)
                if hashlib.sha256(staged_binary.read_bytes()).hexdigest() != self._pinned_sha256:
                    raise OSError("staged AGY identity mismatch")
            except OSError as exc:
                raise BuilderProcessError(
                    "pinned AGY executable could not be staged for the isolated boundary",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from exc
            write_text(host_guest / "run.ps1", guest_script)

            def mapping(host_path: Path, guest_path: str, readonly: bool) -> str:
                return (
                    "    <MappedFolder>"
                    f"<HostFolder>{xml_escape(str(host_path))}</HostFolder>"
                    f"<SandboxFolder>{xml_escape(guest_path)}</SandboxFolder>"
                    f"<ReadOnly>{'true' if readonly else 'false'}</ReadOnly>"
                    "</MappedFolder>"
                )

            mappings = [
                mapping(host_runtime, guest_runtime, False),
                mapping(host_candidate, guest_candidate, False),
                mapping(host_agy, guest_prefix + r"\agy", True),
                mapping(host_output, guest_output, False),
                mapping(host_guest, guest_guest, True),
                mapping(host_auth_token.parent, guest_prefix + r"\auth", True),
            ]
            sandbox_config = host_root / "builder.wsb"
            guest_script_path = guest_guest + "\\run.ps1"
            config_text = (
                "<Configuration>\n"
                "  <VGpu>Disable</VGpu>\n"
                "  <Networking>Enable</Networking>\n"
                "  <MappedFolders>\n"
                + "\n".join(mappings)
                + "\n  </MappedFolders>\n"
                "  <LogonCommand>\n"
                f"    <Command>{xml_escape('powershell.exe -NoProfile -ExecutionPolicy Bypass -File ' + guest_script_path)}</Command>\n"
                "  </LogonCommand>\n"
                "</Configuration>\n"
            )
            write_text(sandbox_config, config_text)
            config_sha256 = hashlib.sha256(sandbox_config.read_bytes()).hexdigest()
            powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
            if not powershell.is_file():
                raise BuilderProcessError(
                    "Windows PowerShell sandbox launcher is unavailable",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )

            def cleanup_sandbox_client(parent_pid: int) -> None:
                powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
                if not powershell.is_file():
                    raise OSError("Windows PowerShell cleanup executable is unavailable")
                cleanup_script = (
                    "$ErrorActionPreference='Stop'; "
                    f"$parent={int(parent_pid)}; "
                    "$children=@(Get-CimInstance Win32_Process | "
                    "Where-Object { $_.Name -eq 'WindowsSandboxClient.exe' -and $_.ParentProcessId -eq $parent }); "
                    "foreach ($child in $children) { Stop-Process -Id $child.ProcessId -Force -ErrorAction Stop }; "
                    "Start-Sleep -Milliseconds 250; "
                    "$remaining=@(Get-CimInstance Win32_Process | "
                    "Where-Object { $_.Name -eq 'WindowsSandboxClient.exe' -and $_.ParentProcessId -eq $parent }); "
                    "if ($remaining.Count -gt 0) { exit 1 }"
                )
                cleanup = subprocess.run(
                    [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cleanup_script],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if cleanup.returncode != 0:
                    raise OSError("Windows Sandbox client cleanup did not quiesce")

            progress_started = time.monotonic()
            progress_state: dict[str, Any] = {
                "first_host_write_ms": None,
                "last_host_change_ms": None,
                "changed_paths": [],
                "polls": 0,
            }
            progress_before = dict(mirror_before)
            progress_last_scan = 0.0

            def progress_probe() -> None:
                nonlocal progress_last_scan, progress_before
                now = time.monotonic()
                if now - progress_last_scan < 0.25:
                    return
                progress_last_scan = now
                progress_state["polls"] += 1
                current = _snapshot_probe_tree(host_candidate)
                changed = sorted(
                    path
                    for path in set(progress_before) | set(current)
                    if progress_before.get(path) != current.get(path)
                )
                if changed:
                    elapsed_ms = round((now - progress_started) * 1000, 3)
                    if progress_state["first_host_write_ms"] is None:
                        progress_state["first_host_write_ms"] = elapsed_ms
                    progress_state["last_host_change_ms"] = elapsed_ms
                    progress_state["changed_paths"] = sorted(
                        set(progress_state["changed_paths"]) | set(changed)
                    )
                progress_before = current

            try:
                outer = run_builder_process(
                    [
                        str(powershell),
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        fr"""$ErrorActionPreference = 'Stop'
$sandbox = Start-Process -FilePath {ps_quote(str(sandbox_exe))} -ArgumentList @({ps_quote(str(sandbox_config))}) -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds({max(config.builder_timeout - 5, 5)})
while (-not (Test-Path -LiteralPath {ps_quote(str(host_output / 'done.json'))}) -and [DateTime]::UtcNow -lt $deadline) {{ Start-Sleep -Milliseconds 250 }}
for ($attempt = 0; $attempt -lt 4; $attempt++) {{
    $clients = @(Get-CimInstance Win32_Process | Where-Object {{ $_.Name -eq 'WindowsSandboxClient.exe' -and $_.ParentProcessId -eq $sandbox.Id }})
    foreach ($client in $clients) {{ Stop-Process -Id $client.ProcessId -Force -ErrorAction SilentlyContinue }}
    if (-not $sandbox.HasExited) {{ Stop-Process -Id $sandbox.Id -Force -ErrorAction SilentlyContinue }}
    Start-Sleep -Milliseconds 250
}}
if (-not (Test-Path -LiteralPath {ps_quote(str(host_output / 'done.json'))})) {{ exit 124 }}
exit 0
""",
                    ],
                    cwd=host_root,
                    env=self._sandbox_host_environment(),
                    timeout=config.builder_timeout,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    max_output_bytes=64 * 1024,
                    completion_probe=lambda: (host_output / "done.json").is_file(),
                    progress_probe=progress_probe,
                    external_cleanup=cleanup_sandbox_client,
                    use_windows_job=False,
                    capture_output=True,
                )
            except BuilderProcessError:
                # Preserve any guest partial output in the attempt evidence
                # before the temporary untrusted mapping is removed.
                atomic_json(stdout_path.parent / "progress.json", progress_state)
                for guest_path, host_path in (
                    (host_output / "stdout.txt", stdout_path),
                    (host_output / "stderr.txt", stderr_path),
                ):
                    if guest_path.is_file():
                        data, _ = self._read_bounded_guest_file(guest_path, BUILDER_OUTPUT_LIMIT_BYTES)
                        _write_builder_evidence(host_path, data)
                raise
            done_path = host_output / "done.json"
            progress_probe()
            if not done_path.is_file():
                raise BuilderProcessError(
                    "isolated AGY guest did not produce completion evidence",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_output_incomplete",
                )
            try:
                done = json.loads(done_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise BuilderProcessError(
                    "isolated AGY completion evidence is malformed",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_output_incomplete",
                ) from exc
            if not isinstance(done, dict) or done.get("schema_version") != 1 or not isinstance(done.get("exit_code"), int):
                raise BuilderProcessError(
                    "isolated AGY completion evidence has an invalid schema",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_output_incomplete",
                )
            stdout_bytes, stdout_overflow = self._read_bounded_guest_file(host_output / "stdout.txt", BUILDER_OUTPUT_LIMIT_BYTES)
            stderr_bytes, stderr_overflow = self._read_bounded_guest_file(host_output / "stderr.txt", BUILDER_OUTPUT_LIMIT_BYTES)
            _write_builder_evidence(stdout_path, stdout_bytes)
            _write_builder_evidence(stderr_path, stderr_bytes)
            if stdout_overflow or stderr_overflow:
                raise BuilderProcessError(
                    "isolated AGY output exceeded the bounded evidence limit",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_output_incomplete",
                )
            try:
                stdout_text = stdout_bytes.decode("utf-8")
                stderr_text = stderr_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BuilderProcessError(
                    "isolated AGY output is not valid UTF-8",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_output_incomplete",
                ) from exc
            diagnostic_code = _classify_agy_diagnostic(
                _agy_terminal_error(stdout_bytes),
                stderr_text,
            )
            if outer.returncode != 0 or done["exit_code"] != 0:
                raise BuilderProcessError(
                    "isolated AGY process exited unsuccessfully",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    returncode=done["exit_code"],
                    failure_code=diagnostic_code or "agy_runtime_error",
                )
            if done.get("error_type") is not None:
                raise BuilderProcessError(
                    "isolated AGY completion evidence reports a process error",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code=diagnostic_code or "agy_runtime_error",
                )
            if diagnostic_code is not None:
                raise BuilderProcessError(
                    "isolated AGY process reported an explicit failure diagnostic",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code=diagnostic_code,
                )
            try:
                parsed = parse_agy_event_stream(stdout_bytes)
            except BuilderFailure as exc:
                raise BuilderProcessError(
                    "isolated AGY process returned an invalid event stream",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code=diagnostic_code or exc.code,
                ) from exc
            if parsed["model"] != config.builder_model:
                raise BuilderProcessError(
                    "isolated AGY process reported an unexpected model",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_model_mismatch",
                )
            if parsed["cwd"].rstrip("\\/").lower() != guest_candidate.rstrip("\\/").lower():
                raise BuilderProcessError(
                    "isolated AGY process reported an unexpected effective cwd",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            if parsed["result"].get("status") != "SUCCESS":
                raise BuilderProcessError(
                    "isolated AGY process returned an error result",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code=diagnostic_code or "agy_runtime_error",
                )
            observed_conversation_ids = _agy_conversation_ids(stdout_bytes)
            observed_hashes = {
                hashlib.sha256(value.encode("utf-8")).hexdigest()
                for value in observed_conversation_ids
            }
            try:
                persisted_hashes = self._persisted_conversation_hashes(
                    run_root or stdout_path.parent
                )
            except BuilderFailure as exc:
                raise BuilderProcessError(
                    "isolated AGY conversation reservation evidence is invalid",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code=exc.code,
                ) from exc
            if (
                len(set(observed_conversation_ids)) != len(observed_conversation_ids)
                or any(value in self._conversation_ids for value in observed_conversation_ids)
                or observed_hashes & persisted_hashes
            ):
                raise BuilderProcessError(
                    "isolated AGY process reused a conversation identity",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_protocol_error",
                )
            boundary_evidence: dict[str, Any] = {
                "boundary": "Windows Sandbox",
                "host_launcher": "Windows PowerShell Start-Process with explicit sandbox-client cleanup",
                "sandbox_config_sha256": config_sha256,
                "guest_cwd": guest_candidate,
                "host_output_untrusted": True,
                "candidate_transport": "disposable mirror; only allowed files synchronized after guest quiescence",
                "mappings": [
                    {"guest": guest_candidate, "access": "read_write", "role": "disposable candidate mirror"},
                    {"guest": guest_runtime, "access": "read_write_untrusted", "role": "sandbox runtime cache"},
                    {"guest": guest_prefix + r"\agy", "access": "read_only", "role": "pinned AGY executable"},
                    {"guest": guest_output, "access": "read_write_untrusted", "role": "guest output"},
                    {"guest": guest_guest, "access": "read_only", "role": "trusted helper"},
                    {"guest": guest_prefix + r"\auth", "access": "read_only", "role": "ephemeral OAuth handoff"},
                ],
                "protected_roots_mapped": False,
                "git_metadata_mapped": False,
                "environment_policy": "guest environment sanitized; host credential/API-key variables removed; OAuth handoff is disposable",
                "guest_exit_code": done["exit_code"],
                "guest_stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
                "guest_stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
                "staged_executable_sha256": hashlib.sha256(staged_binary.read_bytes()).hexdigest(),
            }
            if pre_sync_acceptance is not None:
                pre_sync_acceptance(
                    result=subprocess.CompletedProcess([guest_agy, *inner_args], 0, stdout_text, stderr_text),
                    parsed=parsed,
                    conversation_ids=observed_conversation_ids,
                    stdout_bytes=stdout_bytes,
                    stderr_bytes=stderr_bytes,
                    boundary_evidence=boundary_evidence,
                )
            try:
                if surface_kind == "python_capsule":
                    if capsule_reintegrator is None:
                        raise BuilderProcessError(
                            "Python capsule has no host reintegration callback",
                            stdout_path=stdout_path,
                            stderr_path=stderr_path,
                            failure_code="agy_isolation_failed",
                        )
                    self._validate_capsule_surface_delta(
                        mirror_before,
                        _snapshot_probe_tree(host_candidate),
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                    )
                    candidate_sync = capsule_reintegrator(host_candidate)
                else:
                    candidate_sync = self._sync_sandbox_candidate(
                        candidate,
                        host_candidate,
                        visible_files if visible_files is not None else (allowed_files or []),
                        mirror_before,
                        host_baseline_identity,
                        stdout_path=stdout_path,
                        stderr_path=stderr_path,
                    )
            except BuilderProcessError:
                raise
            except (OSError, RuntimeError) as exc:
                raise BuilderProcessError(
                    "isolated AGY candidate mirror could not be synchronized",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from exc
            boundary_evidence["progress"] = progress_state
            atomic_json(stdout_path.parent / "progress.json", progress_state)
            boundary_evidence["candidate_sync"] = candidate_sync
            boundary_evidence["progress"] = progress_state
            return (
                subprocess.CompletedProcess([guest_agy, *inner_args], 0, stdout_text, stderr_text),
                guest_candidate,
                boundary_evidence,
            )

    def _run_linux_bubblewrap_builder(
        self,
        *,
        path: Path,
        config: Config,
        candidate: Path,
        instruction: str,
        stdout_path: Path,
        stderr_path: Path,
        allowed_files: list[str] | None = None,
        host_baseline_identity: dict[str, Any] | None = None,
        run_root: Path | None = None,
        pre_sync_acceptance: Callable[..., None] | None = None,
        surface: dict[str, Any] | None = None,
        capsule_reintegrator: Callable[[Path], dict[str, Any]] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str, dict[str, Any]]:
        """Run AGY against a disposable mirror and synchronize scoped edits."""
        surface_kind = surface.get("kind", "normal") if isinstance(surface, dict) else "normal"
        visible_files = surface.get("visible_files") if isinstance(surface, dict) else None
        if visible_files is not None and (
            not isinstance(visible_files, list)
            or any(not isinstance(item, str) for item in visible_files)
        ):
            raise BuilderProcessError(
                "AGY surface has invalid visible-file metadata",
                stdout_path=stdout_path, stderr_path=stderr_path,
                failure_code="agy_isolation_failed",
            )
        with _probe_temp_root() as raw_root:
            mirror = Path(raw_root) / "workspace"
            try:
                if surface_kind == "python_capsule":
                    editable = surface.get("editable_file") if isinstance(surface, dict) else None
                    source = surface.get("capsule_source") if isinstance(surface, dict) else None
                    if editable != CAPSULE_EDITABLE_FILE or not isinstance(source, str):
                        raise OSError("invalid Python capsule surface")
                    mirror.mkdir(mode=0o700)
                    (mirror / CAPSULE_EDITABLE_FILE).write_text(source, encoding="utf-8")
                else:
                    self._copy_sandbox_candidate(candidate, mirror, visible_files)
                before = _snapshot_probe_tree(mirror)
            except (OSError, RuntimeError) as exc:
                raise BuilderProcessError(
                    "candidate could not be copied into the disposable Linux mirror",
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from exc

            args = [
                "--model", config.builder_model,
                "--dangerously-skip-permissions", "--output-format", AGY_REQUIRED_OUTPUT_FORMAT,
                "--disable-slash-commands", "--print-timeout",
                f"{min(AGY_PREFLIGHT_PRINT_TIMEOUT_SECONDS, max(config.builder_timeout - 10, 1))}s",
                "--print", instruction,
            ]
            started = time.monotonic()
            try:
                with linux_agy_command(mirror, path, args) as (command_line, environment):
                    result = run_builder_process(
                        command_line, cwd=mirror, env=environment,
                        timeout=config.builder_timeout,
                        stdout_path=stdout_path, stderr_path=stderr_path,
                    )
            except LinuxBoundaryError as exc:
                raise BuilderProcessError(
                    f"Linux AGY isolation boundary is unavailable: {exc}",
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from exc
            stdout_bytes = result.stdout.encode("utf-8")
            stderr_bytes = result.stderr.encode("utf-8")
            diagnostic_code = _classify_agy_diagnostic(_agy_terminal_error(stdout_bytes), result.stderr)
            if result.returncode != 0 or diagnostic_code:
                raise BuilderProcessError(
                    "isolated AGY process exited unsuccessfully",
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    returncode=result.returncode,
                    failure_code=diagnostic_code or "agy_runtime_error",
                )
            try:
                parsed = parse_agy_event_stream(stdout_bytes)
            except BuilderFailure as exc:
                raise BuilderProcessError(
                    "isolated AGY process returned an invalid event stream",
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    failure_code=exc.code,
                ) from exc
            if parsed["model"] != config.builder_model:
                raise BuilderProcessError(
                    "isolated AGY process reported an unexpected model",
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    failure_code="agy_model_mismatch",
                )
            if parsed["cwd"].rstrip("/") != "/workspace":
                raise BuilderProcessError(
                    "isolated AGY process reported an unexpected cwd",
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            if parsed["result"].get("status") != "SUCCESS":
                raise BuilderProcessError(
                    "isolated AGY process returned an error result",
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    failure_code="agy_runtime_error",
                )
            conversations = _agy_conversation_ids(stdout_bytes)
            observed_hashes = {hashlib.sha256(value.encode("utf-8")).hexdigest() for value in conversations}
            persisted_hashes = self._persisted_conversation_hashes(run_root or stdout_path.parent)
            if (
                len(conversations) != len(set(conversations))
                or any(value in self._conversation_ids for value in conversations)
                or observed_hashes & persisted_hashes
            ):
                raise BuilderProcessError(
                    "isolated AGY process reused a conversation identity",
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    failure_code="agy_protocol_error",
                )
            after = _snapshot_probe_tree(mirror)
            changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
            elapsed_ms = round((time.monotonic() - started) * 1000, 3)
            progress = {
                "first_host_write_ms": elapsed_ms if changed else None,
                "last_host_change_ms": elapsed_ms if changed else None,
                "changed_paths": changed,
                "polls": 1,
            }
            boundary_evidence: dict[str, Any] = {
                "boundary": "Bubblewrap mount and PID namespace",
                "guest_cwd": "/workspace",
                "host_output_untrusted": True,
                "candidate_transport": "disposable mirror; allowed delta synchronized after quiescence",
                "git_metadata_mapped": False,
                "protected_roots_mapped": False,
                "host_session_bus_mapped": False,
                "credential_mode": "private one-item Secret Service",
                "guest_exit_code": result.returncode,
                "guest_stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
                "guest_stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
                "staged_executable_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "progress": progress,
            }
            if pre_sync_acceptance is not None:
                pre_sync_acceptance(
                    result=result, parsed=parsed, conversation_ids=conversations,
                    stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes,
                    boundary_evidence=boundary_evidence,
                )
            if surface_kind == "python_capsule":
                if capsule_reintegrator is None:
                    raise BuilderProcessError(
                        "Python capsule has no host reintegration callback",
                        stdout_path=stdout_path, stderr_path=stderr_path,
                        failure_code="agy_isolation_failed",
                    )
                self._validate_capsule_surface_delta(
                    before, after, stdout_path=stdout_path, stderr_path=stderr_path
                )
                candidate_sync = capsule_reintegrator(mirror)
            else:
                candidate_sync = self._sync_sandbox_candidate(
                    candidate, mirror,
                    visible_files if visible_files is not None else (allowed_files or []),
                    before, host_baseline_identity,
                    stdout_path=stdout_path, stderr_path=stderr_path,
                )
            atomic_json(stdout_path.parent / "progress.json", progress)
            boundary_evidence["candidate_sync"] = candidate_sync
            return result, "/workspace", boundary_evidence

    def run(
        self,
        *,
        worktree: Path,
        instruction: str,
        allowed_files: list[str],
        config: Config,
        run_dir: Path,
        label: str,
        surface: dict[str, Any] | None = None,
    ) -> None:
        """Dispatch one fresh direct AGY editing turn and validate its stream."""
        self.last_attempt_artifact = None
        self.last_attempt_label = None
        self.last_attempt_run_root = None
        self.last_attempt_outcome = None
        self.last_attempt_telemetry = None
        label = self._builder_label(label)
        if not isinstance(instruction, str) or not instruction.strip() or "\x00" in instruction:
            raise BuilderFailure(
                "AGY Builder instruction is empty or contains NUL",
                code="agy_protocol_error",
                non_resumable=True,
            )
        if config.builder_model != DEFAULT_BUILDER_MODEL:
            raise BuilderFailure(
                "AGY Builder model does not match the audited model",
                code="agy_model_mismatch",
                non_resumable=True,
            )
        candidate, run_root, provenance = self._canonical_builder_worktree(worktree, config, run_dir)
        try:
            raw_allowed = list(allowed_files)
            normalized_allowed = normalized_paths(raw_allowed)
            if len(raw_allowed) != len(normalized_allowed):
                raise FactoryError("AGY Builder editable file list contains duplicates", "scope")
            ensure_paths_confined(candidate, normalized_allowed)
            ensure_head_paths_not_symlinks(candidate, normalized_allowed)
            path, binary_sha256 = self._pin_executable(config)
            self._verify_persisted_identity(run_root, path, binary_sha256)
            if binary_sha256 != APPROVED_AGY_SHA256:
                raise FactoryError("AGY Builder executable is not the audited identity", "preflight")
            self._recheck_identity(path, binary_sha256)
            baseline_head = git(candidate, "rev-parse", "HEAD").stdout.strip()
            baseline = self._candidate_baseline_identity(candidate)
            expected_baseline = provenance.get("expected_baseline_identity")
            if isinstance(expected_baseline, dict):
                if baseline.get("complete_identity_sha256") != expected_baseline.get("complete_identity_sha256"):
                    raise FactoryError(
                        "AGY Builder candidate baseline changed before dispatch",
                        "isolation",
                    )
            elif not baseline["clean"]:
                raise FactoryError(
                    "AGY Builder candidate baseline is dirty or ambiguous",
                    "isolation",
                )
            protected_before = self._protected_host_snapshot(Path(config.repo).expanduser().resolve(), run_root)
            if surface is None:
                surface = {"kind": "normal"}
            if not isinstance(surface, dict) or surface.get("kind") not in {
                "normal",
                "path_reduced",
                "python_capsule",
            }:
                raise FactoryError("AGY Builder surface is invalid", "isolation")
            visible_files = surface.get("visible_files")
            if visible_files is None and surface.get("kind") == "normal":
                visible_files = normalized_allowed
            if (
                not isinstance(visible_files, list)
                or any(not isinstance(item, str) for item in visible_files)
                or len(set(visible_files)) != len(visible_files)
                or not set(normalized_paths(visible_files)).issubset(set(normalized_allowed))
                and surface.get("kind") != "python_capsule"
            ):
                raise FactoryError("AGY Builder surface paths are outside the task scope", "isolation")
            if surface.get("kind") == "python_capsule":
                if (
                    surface.get("editable_file") != CAPSULE_EDITABLE_FILE
                    or not isinstance(surface.get("capsule"), dict)
                    or not isinstance(surface.get("capsule_source"), str)
                ):
                    raise FactoryError("AGY Builder Python capsule metadata is invalid", "isolation")
                capsule = surface["capsule"]
                canonical_capsule = json.dumps(
                    capsule, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                expected_ref = f"capsules/{hashlib.sha256(canonical_capsule).hexdigest()}.json"
                if surface.get("surface_ref") != expected_ref:
                    raise FactoryError("AGY Builder Python capsule reference is stale", "isolation")
                if capsule.get("editable_input_sha256") != hashlib.sha256(
                    surface["capsule_source"].encode("utf-8")
                ).hexdigest():
                    raise FactoryError("AGY Builder Python capsule input hash is stale", "isolation")
        except BuilderFailure:
            raise
        except FactoryError as exc:
            code = "agy_identity_changed" if exc.category in {"preflight", "state"} else "agy_isolation_failed"
            raise BuilderFailure(str(exc), code=code, non_resumable=True) from exc

        try:
            attempt_path = self._builder_attempt_path(run_root, label)
        except OSError as exc:
            raise BuilderFailure(
                "AGY Builder attempt directory could not be created",
                code="agy_runtime_error",
                non_resumable=True,
            ) from exc
        self.last_attempt_artifact = str(attempt_path / "attempt.json")
        self.last_attempt_label = label
        self.last_attempt_run_root = run_root
        stdout_path = attempt_path / "stdout.ndjson"
        stderr_path = attempt_path / "stderr.txt"
        surface_kind = str(surface.get("kind", "normal"))
        surface_files = surface.get("visible_files")
        if not isinstance(surface_files, list):
            surface_files = []
        if surface_kind == "python_capsule":
            inspectable_files = [CAPSULE_EDITABLE_FILE]
            inspectable_bytes = len(str(surface.get("capsule_source", "")).encode("utf-8"))
        elif surface_files:
            inspectable_files = list(surface_files)
            inspectable_bytes = sum(
                (candidate / Path(relative)).stat().st_size
                for relative in inspectable_files
                if (candidate / Path(relative)).is_file()
            )
        else:
            inspectable_files = []
            inspectable_bytes = 0
            for item in candidate.rglob("*"):
                if ".git" not in item.relative_to(candidate).parts and item.is_file():
                    inspectable_files.append(item.relative_to(candidate).as_posix())
                    inspectable_bytes += item.stat().st_size
        attempt: dict[str, Any] = {
            "schema_version": 1,
            "status": "DISPATCHED",
            "label": label,
            "worktree": str(candidate),
            "baseline_head": baseline_head,
            "baseline_files": self._builder_file_snapshot(candidate, normalized_allowed),
            "baseline_identity": baseline,
            "candidate_provenance": provenance,
            "protected_host_before": protected_before,
            "allowed_files": normalized_allowed,
            "instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
            "model": config.builder_model,
            "executable": {"path": str(path), "sha256": binary_sha256},
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "argv_shape": [
                str(path),
                "--model",
                config.builder_model,
                "--dangerously-skip-permissions",
                "--output-format",
                "stream-json",
                "--disable-slash-commands",
                "--print-timeout",
                "<bounded-duration>",
                "--print",
                "<instruction>",
            ],
            "navigation": {
                "strategy": surface.get("strategy", surface_kind),
                "surface_ref": surface.get("surface_ref"),
                "target_symbols": surface.get("target_symbols", []),
                "inspectable_files": sorted(inspectable_files),
                "inspectable_bytes": inspectable_bytes,
            },
        }
        attempt_started = time.monotonic()
        try:
            write_text(attempt_path / "instruction.txt", instruction)
            atomic_json(attempt_path / "attempt.json", attempt)
        except Exception as exc:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_runtime_error",
                message="AGY Builder attempt artifacts could not be created",
            ) from exc

        if config.builder_timeout <= int(BUILDER_SHUTDOWN_TIMEOUT_SECONDS) + 1:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_timeout",
                message="AGY Builder timeout leaves no shutdown margin",
            )
        cli_timeout = min(
            AGY_PREFLIGHT_PRINT_TIMEOUT_SECONDS,
            int(config.builder_timeout - BUILDER_SHUTDOWN_TIMEOUT_SECONDS - 1),
        )
        argv = [
            str(path),
            "--model",
            config.builder_model,
            "--dangerously-skip-permissions",
            "--output-format",
            AGY_REQUIRED_OUTPUT_FORMAT,
            "--disable-slash-commands",
            "--print-timeout",
            f"{cli_timeout}s",
            "--print",
            instruction,
        ]
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        expected_cwd = str(candidate)
        boundary_evidence: dict[str, Any] = {
            "boundary": "injected_builder_runner" if self._builder_runner is not None else "test_probe_runner",
            "protected_roots_mapped": None,
        }
        sandbox_prevalidated = False

        def reintegrate_capsule(mirror_root: Path) -> dict[str, Any]:
            if surface_kind != "python_capsule":
                raise BuilderProcessError(
                    "unexpected capsule reintegration request",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            capsule = surface.get("capsule")
            if not isinstance(capsule, dict):
                raise BuilderProcessError(
                    "Python capsule descriptor is unavailable",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            if capsule.get("candidate_baseline_sha256") != baseline.get("complete_identity_sha256"):
                raise BuilderProcessError(
                    "Python capsule candidate baseline is stale",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            source_relative = capsule.get("source_path")
            if not isinstance(source_relative, str) or source_relative not in normalized_allowed:
                raise BuilderProcessError(
                    "Python capsule source path is outside the task scope",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            output_path = mirror_root / CAPSULE_EDITABLE_FILE
            if not output_path.is_file() or output_path.is_symlink():
                raise BuilderProcessError(
                    "Python capsule output is missing or unsafe",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_protocol_error",
                )
            source_path = candidate / Path(source_relative)
            try:
                original_source = source_path.read_text(encoding="utf-8")
                edited_capsule = output_path.read_text(encoding="utf-8")
                reconstructed = reintegrate_python_capsule(
                    capsule,
                    original_source,
                    edited_capsule,
                )
            except (OSError, UnicodeError, FactoryError) as exc:
                raise BuilderProcessError(
                    "Python capsule output could not be safely reintegrated",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from exc
            reintegration_root = Path(
                tempfile.mkdtemp(prefix=".softfac-capsule-reintegration-", dir=str(candidate.parent))
            )
            try:
                reintegration_target = reintegration_root / Path(source_relative)
                reintegration_target.parent.mkdir(parents=True, exist_ok=True)
                reintegration_target.write_text(original_source, encoding="utf-8")
                reintegration_before = _snapshot_probe_tree(reintegration_root)
                reintegration_target.write_text(reconstructed, encoding="utf-8")
                return self._sync_sandbox_candidate(
                    candidate,
                    reintegration_root,
                    [source_relative],
                    reintegration_before,
                    baseline,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                ) | {
                    "mode": "python_symbol_capsule",
                    "source_path": source_relative,
                    "capsule_symbol": capsule.get("qualified_symbol"),
                }
            except (OSError, RuntimeError, BuilderProcessError) as exc:
                if isinstance(exc, BuilderProcessError):
                    raise
                raise BuilderProcessError(
                    "Python capsule reintegration synchronization failed",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                ) from exc
            finally:
                shutil.rmtree(reintegration_root, ignore_errors=True)

        def accept_sandbox_attempt_before_sync(
            *,
            result: subprocess.CompletedProcess[str],
            parsed: dict[str, Any],
            conversation_ids: list[str],
            stdout_bytes: bytes,
            stderr_bytes: bytes,
            boundary_evidence: dict[str, Any],
        ) -> None:
            nonlocal sandbox_prevalidated
            try:
                protected_after = self._protected_host_snapshot(
                    Path(config.repo).expanduser().resolve(), run_root
                )
            except BuilderFailure as exc:
                raise BuilderProcessError(
                    "AGY Builder protected-state attestation failed",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code=exc.code,
                ) from exc
            if protected_after != protected_before:
                raise BuilderProcessError(
                    "AGY Builder changed protected host state",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            try:
                self._recheck_identity(path, binary_sha256)
            except FactoryError as exc:
                raise BuilderProcessError(
                    "AGY Builder executable identity changed after the attempt",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_identity_changed",
                ) from exc
            observed_hashes = [
                hashlib.sha256(value.encode("utf-8")).hexdigest()
                for value in conversation_ids
            ]
            attempt["protected_host_after"] = protected_after
            attempt["boundary"] = boundary_evidence
            attempt["conversation_id_sha256s"] = observed_hashes
            if len(observed_hashes) == 1:
                attempt["conversation_id_sha256"] = observed_hashes[0]
            attempt["conversation_reservation"] = "RESERVED"
            attempt.update(
                {
                    "status": "SUCCESS",
                    "returncode": result.returncode,
                    "event_count": parsed["event_count"],
                    "event_sequence": parsed["event_sequence"],
                    "result_status": parsed["result"]["status"],
                    "response_sha256": hashlib.sha256(
                        parsed["result"]["response"].encode("utf-8")
                    ).hexdigest(),
                    "stdout_sha256": hashlib.sha256(stdout_bytes).hexdigest(),
                    "stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
                }
            )
            try:
                atomic_json(attempt_path / "attempt.json", attempt)
            except Exception as exc:
                raise BuilderProcessError(
                    "AGY Builder attempt completion evidence could not be persisted",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_runtime_error",
                ) from exc
            self._conversation_ids.update(conversation_ids)
            sandbox_prevalidated = True
        try:
            if self._builder_runner is not None:
                runner_kwargs: dict[str, Any] = {
                    "argv": argv,
                    "candidate": candidate,
                    "config": config,
                    "stdout_path": stdout_path,
                    "stderr_path": stderr_path,
                    "run_root": run_root,
                }
                if "surface" in inspect.signature(self._builder_runner).parameters:
                    runner_kwargs["surface"] = surface
                result, expected_cwd, boundary_evidence = self._builder_runner(**runner_kwargs)
            elif self._probe_runner is not None:
                result = run_builder_process(
                    argv,
                    cwd=candidate,
                    env=env,
                    timeout=config.builder_timeout,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                )
            elif os.name == "nt":
                result, expected_cwd, boundary_evidence = self._run_windows_sandbox_builder(
                    path=path,
                    config=config,
                    candidate=candidate,
                    instruction=instruction,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    allowed_files=normalized_allowed,
                    host_baseline_identity=baseline,
                    run_root=run_root,
                    pre_sync_acceptance=accept_sandbox_attempt_before_sync,
                    surface=surface,
                    capsule_reintegrator=reintegrate_capsule,
                )
            elif sys.platform.startswith("linux"):
                result, expected_cwd, boundary_evidence = self._run_linux_bubblewrap_builder(
                    path=path,
                    config=config,
                    candidate=candidate,
                    instruction=instruction,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    allowed_files=normalized_allowed,
                    host_baseline_identity=baseline,
                    run_root=run_root,
                    pre_sync_acceptance=accept_sandbox_attempt_before_sync,
                    surface=surface,
                    capsule_reintegrator=reintegrate_capsule,
                )
            else:
                raise BuilderProcessError(
                    "no approved AGY filesystem isolation boundary is available on this platform",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    failure_code="agy_isolation_failed",
                )
            if sandbox_prevalidated:
                synced = boundary_evidence.get("candidate_sync", {})
                changed = bool(
                    isinstance(synced, dict)
                    and synced.get("allowed_files_synchronized")
                )
                attempt["elapsed_ms"] = round((time.monotonic() - attempt_started) * 1000, 3)
                attempt["termination_reason"] = "SUCCESS" if changed else "NO_PATCH"
                attempt["navigation"]["progress"] = boundary_evidence.get("progress")
                self.last_attempt_outcome = attempt["termination_reason"]
                self.last_attempt_telemetry = dict(attempt["navigation"])
                atomic_json(attempt_path / "attempt.json", attempt)
                return
        except BuilderProcessError as exc:
            code = self._builder_process_failure_code(exc)
            attempt["process_failure_code"] = code
            progress_path = exc.stdout_path.parent / "progress.json"
            if progress_path.is_file():
                attempt["navigation"]["progress_ref"] = str(progress_path)
            if exc.secondary_failure_code:
                attempt["secondary_failure_code"] = exc.secondary_failure_code
            if exc.secondary_failure:
                attempt["secondary_failure"] = exc.secondary_failure
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code=code,
                message="AGY Builder process failed; inspect the retained attempt evidence",
            ) from exc

        try:
            protected_after = self._protected_host_snapshot(Path(config.repo).expanduser().resolve(), run_root)
        except BuilderFailure as exc:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code=exc.code,
                message="AGY Builder protected-state attestation failed",
            ) from exc
        if protected_after != protected_before:
            attempt["protected_host_after"] = protected_after
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_isolation_failed",
                message="AGY Builder changed protected host state",
            )
        attempt["protected_host_after"] = protected_after
        attempt["boundary"] = boundary_evidence
        try:
            atomic_json(attempt_path / "attempt.json", attempt)
        except Exception as exc:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_runtime_error",
                message="AGY Builder boundary evidence could not be persisted",
            ) from exc

        raw_stream_bytes = result.stdout.encode("utf-8")
        observed_conversation_ids = _agy_conversation_ids(raw_stream_bytes)
        reserved_here = False
        if observed_conversation_ids:
            observed_conversation_hashes = [
                hashlib.sha256(value.encode("utf-8")).hexdigest()
                for value in observed_conversation_ids
            ]
            try:
                persisted_hashes = self._persisted_conversation_hashes(run_root)
            except BuilderFailure as exc:
                raise self._builder_attempt_failure(
                    attempt_path,
                    attempt,
                    code=exc.code,
                    message="AGY Builder reservation evidence could not be validated",
                ) from exc
            already_reserved = (
                len(set(observed_conversation_ids)) != len(observed_conversation_ids)
                or any(value in self._conversation_ids for value in observed_conversation_ids)
                or any(value in persisted_hashes for value in observed_conversation_hashes)
            )
            attempt["conversation_id_sha256s"] = observed_conversation_hashes
            if len(observed_conversation_hashes) == 1:
                attempt["conversation_id_sha256"] = observed_conversation_hashes[0]
            attempt["conversation_reservation"] = "REUSED" if already_reserved else "RESERVED"
            if already_reserved:
                raise self._builder_attempt_failure(
                    attempt_path,
                    attempt,
                    code="agy_protocol_error",
                    message="AGY Builder reused a conversation identity",
                )
            self._conversation_ids.update(observed_conversation_ids)
            reserved_here = True
            try:
                atomic_json(attempt_path / "attempt.json", attempt)
            except Exception as exc:
                raise self._builder_attempt_failure(
                    attempt_path,
                    attempt,
                    code="agy_runtime_error",
                    message="AGY Builder conversation reservation could not be persisted",
                ) from exc

        diagnostic_code = _classify_agy_diagnostic(
            _agy_terminal_error(raw_stream_bytes),
            result.stderr,
        )
        if diagnostic_code is not None:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code=diagnostic_code,
                message="AGY Builder reported an explicit failure diagnostic",
            )
        if result.returncode != 0:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_runtime_error",
                message="AGY Builder exited unsuccessfully; inspect the retained attempt evidence",
            )
        if re.search(r"(?i)(?:print\s+)?timeout|timed out", result.stderr):
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_timeout",
                message="AGY Builder reported a CLI timeout; partial evidence was retained",
            )
        try:
            parsed = parse_agy_event_stream(raw_stream_bytes)
        except BuilderFailure as exc:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code=exc.code,
                message="AGY Builder returned an invalid event stream",
            ) from exc

        if parsed["model"] != config.builder_model:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_model_mismatch",
                message="AGY Builder reported an unexpected model",
            )
        if expected_cwd.startswith("C:\\") and boundary_evidence.get("boundary") == "Windows Sandbox":
            cwd_matches = os.path.normcase(parsed["cwd"].rstrip("\\/")) == os.path.normcase(expected_cwd.rstrip("\\/"))
        else:
            try:
                effective_cwd = Path(parsed["cwd"]).expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise self._builder_attempt_failure(
                    attempt_path,
                    attempt,
                    code="agy_isolation_failed",
                    message="AGY Builder reported an invalid effective cwd",
                ) from exc
            cwd_matches = effective_cwd == candidate
        if not cwd_matches:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_isolation_failed",
                message="AGY Builder reported an unexpected effective cwd",
            )
        conversation_id = parsed["conversation_id"]
        if conversation_id in self._conversation_ids and not reserved_here:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_protocol_error",
                message="AGY Builder reused a conversation identity",
            )
        if parsed["result"].get("status") != "SUCCESS":
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_runtime_error",
                message="AGY Builder returned an error result",
            )
        try:
            self._recheck_identity(path, binary_sha256)
        except FactoryError as exc:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_identity_changed",
                message="AGY Builder executable identity changed after the attempt",
            ) from exc
        if not observed_conversation_ids:
            self._conversation_ids.add(conversation_id)
        attempt.update(
            {
                "status": "SUCCESS",
                "returncode": result.returncode,
                "event_count": parsed["event_count"],
                "event_sequence": parsed["event_sequence"],
                "conversation_id_sha256": hashlib.sha256(conversation_id.encode("utf-8")).hexdigest(),
                "result_status": parsed["result"]["status"],
                "response_sha256": hashlib.sha256(parsed["result"]["response"].encode("utf-8")).hexdigest(),
                "stdout_sha256": hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest(),
                "elapsed_ms": round((time.monotonic() - attempt_started) * 1000, 3),
                "report_bytes": len(raw_stream_bytes),
                "usage": parsed["result"].get("usage"),
            }
        )
        final_identity = self._candidate_baseline_identity(candidate)
        changed = final_identity.get("complete_identity_sha256") != baseline.get(
            "complete_identity_sha256"
        )
        attempt["termination_reason"] = "SUCCESS" if changed else "NO_PATCH"
        self.last_attempt_outcome = attempt["termination_reason"]
        self.last_attempt_telemetry = dict(attempt["navigation"])
        try:
            atomic_json(attempt_path / "attempt.json", attempt)
        except Exception as exc:
            raise self._builder_attempt_failure(
                attempt_path,
                attempt,
                code="agy_runtime_error",
                message="AGY Builder attempt completion evidence could not be persisted",
            ) from exc


class FactoryEngine:
    def __init__(
        self,
        *,
        state_root: Path = DEFAULT_STATE_ROOT,
        role_client: Any | None = None,
        builder: Any | None = None,
    ) -> None:
        self.state_root = state_root.expanduser().resolve()
        self.role_client = role_client or CodexRoleClient()
        # Step 7 makes the direct AGY adapter the production Builder.  Tests
        # and callers may still inject a deterministic Builder explicitly.
        self.builder = builder or AgyBuilder()

    def _run_dir(self, identifier: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", identifier):
            raise FactoryError("invalid run id", "input")
        return self.state_root / identifier

    def _save(self, run_dir: Path, state: dict[str, Any], phase: str, **updates: Any) -> None:
        state.update(updates)
        state["phase"] = phase
        state["updated_at"] = now_iso()
        atomic_json(run_dir / "run_state.json", state)

    def _load(self, identifier: str) -> tuple[Path, dict[str, Any], Config]:
        run_dir = self._run_dir(identifier)
        try:
            state = read_run_state(run_dir)
        except FactoryError as exc:
            if exc.category == "input":
                raise FactoryError(f"unknown run id: {identifier}", "input") from exc
            raise
        return run_dir, state, load_config_for_execution(state)

    def _repo(self, raw: str) -> Path:
        repo = Path(raw).expanduser().resolve()
        probe = command(["git", "rev-parse", "--show-toplevel"], cwd=repo, timeout=30)
        if probe.returncode != 0 or Path(probe.stdout.strip()).resolve() != repo:
            raise FactoryError(f"repository must be its Git top-level directory: {repo}", "input")
        return repo

    def _source_status(self, repo: Path, paths: Iterable[str] | None = None) -> str:
        argv = ["status", "--porcelain=v1", "--untracked-files=all"]
        if paths is not None:
            argv.extend(["--", *paths])
        return git(repo, *argv).stdout

    def _assert_source_unchanged(
        self, repo: Path, state: dict[str, Any], run_dir: Path, label: str
    ) -> None:
        expected_head = state.get("source_head_before")
        guard_paths = state.get("source_guard_paths")
        expected_status = state.get("source_allowed_status_before")
        if expected_head is None or not isinstance(guard_paths, list) or expected_status is None:
            raise FactoryError("run is missing its source checkout guard baseline", "state")
        actual_head = git(repo, "rev-parse", "HEAD").stdout.strip()
        actual_status = self._source_status(repo, guard_paths)
        atomic_json(
            run_dir / f"source_status_{label}.json",
            {
                "label": label,
                "guard_paths": guard_paths,
                "expected_head": expected_head,
                "actual_head": actual_head,
                "expected_allowed_status": expected_status,
                "actual_allowed_status": actual_status,
            },
        )
        if actual_head != expected_head or actual_status != expected_status:
            raise FactoryError(
                "planned base or allowed source paths changed during isolated factory run; refusing to continue",
                "isolation",
            )

    def _candidate_files(self, repo: Path) -> list[str]:
        tracked = git(repo, "ls-files").stdout.splitlines()
        extensions = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".nix", ".json", ".yaml", ".yml", ".toml", ".md"}
        sensitive = re.compile(r"(^|/)(\.env|.*(?:secret|credential|private[_-]?key).*)($|\.)", re.I)
        candidates = [
            p
            for p in tracked
            if PurePosixPath(p).suffix.lower() in extensions
            and not p.startswith(".git/")
            and not sensitive.search(p)
        ]
        return candidates[:40]

    def _repo_context(self, repo: Path, files: list[str] | None) -> dict[str, Any]:
        selected = files or self._candidate_files(repo)
        tracked = set(git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout.splitlines())
        skeleton = build_file_tree_skeleton(repo)
        contents: dict[str, str] = {}
        remaining = 60_000 if files else 20_000
        for relative in selected:
            if relative not in tracked:
                continue
            shown = command(["git", "show", f"HEAD:{relative}"], cwd=repo, timeout=30)
            if shown.returncode != 0:
                continue
            raw = shown.stdout
            excerpt = raw[: min(remaining, 8_000)]
            contents[relative] = excerpt
            remaining -= len(excerpt)
            if remaining <= 0:
                break
        manifests = [
            p
            for p in ("AGENTS.md", "README.md", "pyproject.toml", "package.json", "Cargo.toml", "go.mod")
            if p in tracked
        ]
        return {
            "base_commit": git(repo, "rev-parse", "HEAD").stdout.strip(),
            "source": "committed HEAD tree",
            "candidate_files": selected,
            "manifests": manifests,
            "file_tree_skeleton": skeleton,
            "file_excerpts": contents,
        }

    def _role_call(
        self,
        *,
        run_dir: Path,
        role: str,
        provider: str,
        model: str,
        prompt: str,
        label: str,
        timeout: int,
        reasoning: str = "high",
    ) -> dict[str, Any]:
        call_kwargs = {
            "role": role,
            "provider": provider,
            "model": model,
            "prompt": prompt,
            "usage_path": run_dir / f"{label}.usage.json",
            "output_path": run_dir / f"{label}.output.txt",
            "timeout": timeout,
        }
        import inspect
        sig = inspect.signature(self.role_client.call)
        if "reasoning" in sig.parameters:
            call_kwargs["reasoning"] = reasoning
        return self.role_client.call(**call_kwargs)

    def _smoke_role(self, run_dir: Path, role: str, provider: str, model: str, timeout: int) -> None:
        if role == "Sol":
            prompt = 'Capability smoke test. Return ONLY this JSON object: {"capability":"planner-reviewer","schema_ok":true}'
            expected = {"capability": "planner-reviewer", "schema_ok": True}
        else:
            prompt = 'Capability smoke test. Return ONLY this JSON object: {"capability":"debugger","schema_ok":true}'
            expected = {"capability": "debugger", "schema_ok": True}
        actual = self._role_call(
            run_dir=run_dir,
            role=role,
            provider=provider,
            model=model,
            prompt=prompt,
            label=f"preflight_{role.lower()}",
            timeout=timeout,
        )
        if actual != expected:
            raise FactoryError(f"{role} failed the strict JSON capability smoke test", "preflight")

    def _perform_planning(
        self,
        run_dir: Path,
        state: dict[str, Any],
        config: Config,
        repo: Path,
        ledger: MemoryLedger | None = None,
        *,
        replan_reason: str | None = None,
        planning_repo: Path | None = None,
    ) -> None:
        classifier_info = state.get("objective_classification") or classify_objective(config.request)
        priority_guidance = get_priority_guidance(classifier_info["classification"])

        prior_context = None
        prior_context_path = run_dir / "prior_run_context.json"
        if prior_context_path.is_file():
            prior_context = read_json(prior_context_path)
        elif config.prior_run:
            prior_context = load_prior_run_context(self.state_root, repo, config.prior_run)
            atomic_json(prior_context_path, prior_context)

        context_repo = planning_repo or repo
        context = self._repo_context(context_repo, config.requested_files)
        atomic_json(run_dir / "repo_context.json", context)
        planner_input = {
            "original_request": config.request,
            "user_file_boundary": config.requested_files,
            "configured_test_command": normalize_test_command(config.test_command) if config.test_command else None,
            "objective_classification": classifier_info["classification"],
            "objective_rationale": classifier_info["rationale"],
            "priority_guidance": priority_guidance,
            "repository_context": context,
            "authoritative_request_ref": state.get("request_ref") or "request.json",
            "master_plan_contract": {
                "schema_version": 1,
                "request_ref": "request.json",
                "global_criteria": [{"id": "safe identifier", "statement": "string"}],
                "architecture_invariants": [{"id": "safe identifier", "statement": "string"}],
                "assumptions": [{"id": "safe identifier", "statement": "string", "critical": "boolean"}],
                "non_goals": "string array",
                "milestones": [
                    {
                        "id": "safe identifier",
                        "objective": "string",
                        "tasks": [
                            {
                                "id": "safe identifier",
                                "objective": "string",
                                "depends_on": "task id string array",
                                "editable_scope": "repository-relative file array",
                                "acceptance_criteria": [{"id": "safe criterion id", "statement": "string"}],
                                "verification_commands": "string array",
                                "preservation_constraints": "string array",
                                "global_criteria": "global criterion id string array",
                            }
                        ],
                    }
                ],
            },
        }
        if prior_context is not None:
            planner_input["prior_run_context"] = prior_context
        current_plan_ref = state.get("master_plan_ref")
        current_plan_path = (
            (run_dir / current_plan_ref).resolve()
            if isinstance(current_plan_ref, str) and current_plan_ref
            else run_dir / "master_plan.json"
        )
        existing_master_plan: dict[str, Any] | None = None
        if current_plan_path.is_file():
            current_value = read_json(current_plan_path)
            if isinstance(current_value, dict):
                existing_master_plan = current_value
            planner_input["current_master_plan"] = current_value
        if replan_reason:
            try:
                parsed_replan_reason = json.loads(replan_reason)
            except (TypeError, json.JSONDecodeError) as exc:
                raise FactoryError("replan reason is not structured evidence", "contract") from exc
            planner_input["replan_reason"] = validate_replan_reason(parsed_replan_reason)
            self._validate_replan_evidence(run_dir, planner_input["replan_reason"], state)
        planner_input["completed_commits"] = state.get("completed_commits", [])
        planner_input["criterion_evidence"] = state.get("criterion_evidence", {})

        prompt = (
            "You are Astra, the strategic project planner. You may inspect the supplied context but must not edit files "
            "or call tools. Produce one executable master plan for the whole objective. Return only strict JSON with "
            "exactly these top-level keys: schema_version, request_ref, objective, global_criteria, architecture_invariants, assumptions, non_goals, milestones. "
            "Each milestone must contain id, objective, tasks. Each task must contain exactly id, objective, depends_on, "
            "editable_scope, acceptance_criteria, verification_commands, preservation_constraints, global_criteria. Plan observable "
            "increments, keep implementation HOW open to AGY, preserve prior verified behavior, and do not invent "
            "services, managers, registries, or speculative future architecture. Every acceptance and global criterion "
            "must be decidable from the candidate diff, repository context, and the verification commands that this "
            "plan actually supplies. Do not require a baseline run, a second test command, or an extra manual probe "
            "unless it is explicitly requested and included in verification_commands. If configured_test_command "
            "is non-null, use that exact command in verification_commands and write any test criterion against that "
            "command; Runner will execute it, not substitute another command. If user_file_boundary is non-null, "
            "every editable_scope must be a subset. Input:\n"
            + json.dumps(planner_input, indent=2)
        )
        previous_astra_calls = state.get("astra_invocation_count", 0)
        if isinstance(previous_astra_calls, bool) or not isinstance(previous_astra_calls, int) or previous_astra_calls < 0:
            raise FactoryError("run has invalid Astra invocation count", "state")
        replan_dispatch_ref: str | None = None
        if replan_reason:
            dispatch_attempt = self._durable_replan_dispatch_count(run_dir) + 1
            if dispatch_attempt > 2:
                self._block_replan_exhaustion(
                    run_dir,
                    state,
                    attempts=dispatch_attempt - 1,
                    reason=planner_input["replan_reason"],
                )
            replan_dispatch_ref = f"replan_dispatch_{dispatch_attempt}.json"
            dispatch_path = run_dir / replan_dispatch_ref
            if dispatch_path.exists():
                raise FactoryError("replan dispatch history is ambiguous", "blocked")
            atomic_json(
                dispatch_path,
                {
                    "status": "RESERVED",
                    "attempt": dispatch_attempt,
                    "reason_ref": state.get("replan_reason_ref"),
                    "reason": planner_input["replan_reason"],
                },
            )
        self._save(
            run_dir,
            state,
            "planning",
            astra_invocation_count=previous_astra_calls + 1,
            replan_dispatch_ref=replan_dispatch_ref,
        )
        plan = self._role_call(
            run_dir=run_dir,
            role="Astra Planner",
            provider=config.planner_provider,
            model=config.planner_model,
            prompt=prompt,
            label="astra_master_plan",
            timeout=config.role_timeout,
            reasoning=config.planner_reasoning,
        )
        plan = validate_master_plan(plan, config.requested_files)
        authoritative_request_ref = state.get("request_ref") or "request.json"
        if plan.get("request_ref") != authoritative_request_ref:
            raise FactoryError(
                "Astra master plan request_ref does not match the authoritative request",
                "contract",
            )
        request_path = (run_dir / authoritative_request_ref).resolve()
        try:
            request_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("authoritative request reference escapes the run directory", "state") from exc
        if not request_path.is_file():
            raise FactoryError("authoritative request artifact is missing", "state")
        request_value = read_json(request_path)
        if (
            not isinstance(request_value, dict)
            or request_value.get("request") != config.request
            or request_value.get("requested_files") != config.requested_files
            or not re.fullmatch(r"requests/[0-9a-f]{64}\.json", authoritative_request_ref.replace("\\", "/"))
            or hashlib.sha256(request_path.read_bytes()).hexdigest() != authoritative_request_ref.replace("\\", "/").split("/")[-1][:-5]
            or request_value.get("run_id") != state.get("run_id")
            or request_value.get("artifact_type") not in {"request_v1", "user_request_change_v1"}
        ):
            raise FactoryError("authoritative request artifact does not match current config", "state")
        new_task_ids = {task["id"] for task in master_plan_tasks(plan)}
        completed_ids = {
            item.get("task_id")
            for item in state.get("completed_commits", [])
            if isinstance(item, dict) and isinstance(item.get("task_id"), str)
        }
        missing_completed = sorted(completed_ids - new_task_ids)
        if missing_completed:
            raise FactoryError(
                f"replan removed completed task identities: {missing_completed}",
                "state",
            )
        active_task_id = state.get("current_task_id")
        if active_task_id and active_task_id not in completed_ids and active_task_id not in new_task_ids:
            raise FactoryError(
                f"replan cannot preserve active task identity: {active_task_id}",
                "state",
            )
        if existing_master_plan is not None:
            old_global = {
                item["id"]: item
                for item in existing_master_plan.get("global_criteria", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            new_global = {
                item["id"]: item
                for item in plan.get("global_criteria", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            completed_commit_hashes = {
                item.get("commit")
                for item in state.get("completed_commits", [])
                if isinstance(item, dict) and isinstance(item.get("commit"), str)
            }
            bound_global_ids = {
                criterion_id
                for criterion_id, evidence in (state.get("criterion_evidence") or {}).items()
                if (
                    isinstance(evidence, dict)
                    and evidence.get("status") == "PASS"
                    and evidence.get("commit") in completed_commit_hashes
                    and isinstance(evidence.get("task_id"), str)
                )
            }
            protected_old_global = set(old_global) & bound_global_ids
            removed_global = sorted(protected_old_global - set(new_global))
            changed_global = sorted(
                criterion_id
                for criterion_id in protected_old_global & set(new_global)
                if json.dumps(old_global[criterion_id], sort_keys=True, separators=(",", ":"))
                != json.dumps(new_global[criterion_id], sort_keys=True, separators=(",", ":"))
            )
            old_tasks = {
                task["id"]: task
                for task in master_plan_tasks(existing_master_plan)
                if isinstance(task, dict) and isinstance(task.get("id"), str)
            }
            new_tasks = {task["id"]: task for task in master_plan_tasks(plan)}
            # Completed task contracts are immutable history.  The active
            # task keeps its stable identity, but its contract may be replaced
            # when the verified strategic assumption that justified it is
            # disproved; attempts remain in run_state and are not reset.
            preserved_ids = set(completed_ids)
            immutable_fields = (
                "id",
                "objective",
                "depends_on",
                "editable_scope",
                "acceptance_criteria",
                "verification_commands",
                "preservation_constraints",
                "global_criteria",
            )
            changed_tasks = sorted(
                task_id
                for task_id in preserved_ids
                if task_id not in old_tasks
                or task_id not in new_tasks
                or any(
                    json.dumps(old_tasks[task_id].get(field), sort_keys=True, separators=(",", ":"))
                    != json.dumps(new_tasks[task_id].get(field), sort_keys=True, separators=(",", ":"))
                    for field in immutable_fields
                )
            )
            if removed_global or changed_global or changed_tasks:
                reason = "replan attempted to rewrite immutable completed planning history"
                evidence = {
                    "reason": reason,
                    "removed_global_criteria": removed_global,
                    "changed_global_criteria": changed_global,
                    "changed_preserved_tasks": changed_tasks,
                    "completed_task_ids": sorted(completed_ids),
                }
                rejection_ref = f"replan_rejected_{uuid.uuid4().hex}.json"
                atomic_json(run_dir / rejection_ref, evidence)
                self._save(
                    run_dir,
                    state,
                    "blocked",
                    block_reason=reason,
                    error=reason,
                    error_category="blocked",
                    replan_block_evidence=rejection_ref,
                )
                raise FactoryError(reason, "blocked")
        all_allowed = sorted(
            {
                relative
                for task in master_plan_tasks(plan)
                for relative in task["editable_scope"]
            }
        )
        ensure_paths_confined(context_repo, all_allowed)
        ensure_head_paths_not_symlinks(context_repo, all_allowed)
        canonical_plan = json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        plan_digest = hashlib.sha256(canonical_plan.encode("utf-8")).hexdigest()
        plan_ref = f"plans/{plan_digest}.json"
        plan_path = run_dir / plan_ref
        if plan_path.is_file():
            existing_plan = read_json(plan_path)
            existing_canonical = json.dumps(
                existing_plan,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if hashlib.sha256(existing_canonical.encode("utf-8")).hexdigest() != plan_digest:
                raise FactoryError("content-addressed master plan artifact is inconsistent", "state")
        else:
            atomic_json(plan_path, plan)
        if replan_dispatch_ref is not None:
            dispatch_path = run_dir / replan_dispatch_ref
            atomic_json(
                dispatch_path,
                {
                    "status": "COMPLETED",
                    "attempt": int(re.search(r"([0-9]+)", replan_dispatch_ref).group(1)),
                    "reason_ref": state.get("replan_reason_ref"),
                    "plan_ref": plan_ref,
                },
            )
        current_base = state.get("base_commit") or context["base_commit"]
        source_head_before = state.get("source_head_before") or context["base_commit"]
        source_guard_paths = sorted(
            set(state.get("source_guard_paths", [])) | set(all_allowed)
        )
        source_status_before = state.get("source_allowed_status_before")
        if source_status_before is None or not state.get("source_guard_paths"):
            source_status_before = self._source_status(repo, source_guard_paths)
        if ledger:
            ledger.record_event(
                phase="planning", action="astra_master_plan", result="success", artifacts=[plan_ref]
            )
        preserved_task_id = state.get("current_task_id")
        preserved_attempts = state.get("current_task_attempts", 0)
        if preserved_attempts is None:
            preserved_attempts = 0
        if isinstance(preserved_attempts, bool) or not isinstance(preserved_attempts, int) or preserved_attempts < 0:
            raise FactoryError("run has invalid current task attempt count", "state")
        self._save(
            run_dir,
            state,
            "planned",
            base_commit=current_base,
            master_plan_ref=plan_ref,
            current_task_id=preserved_task_id,
            current_task_attempts=preserved_attempts,
            criterion_evidence=state.get("criterion_evidence", {}),
            allowed_files=all_allowed,
            source_head_before=source_head_before,
            source_guard_paths=source_guard_paths,
            source_allowed_status_before=source_status_before,
            error=None,
            error_category=None,
        )

    def _capability_preflight(
        self, run_dir: Path, state: dict[str, Any], config: Config
    ) -> None:
        """Prove every provider/tool capability before planning or execution."""
        self._save(run_dir, state, "preflight", error=None, error_category=None)
        builder_evidence = self.builder.preflight(config, run_dir)
        if isinstance(builder_evidence, dict):
            executable = builder_evidence.get("executable")
            if isinstance(executable, dict):
                pinned_path = executable.get("path")
                pinned_sha256 = executable.get("sha256")
                if isinstance(pinned_path, str) and isinstance(pinned_sha256, str):
                    previous_path = state.get("agy_executable_path")
                    previous_sha256 = state.get("agy_executable_sha256")
                    if (
                        (previous_path is not None and previous_path != pinned_path)
                        or (previous_sha256 is not None and previous_sha256 != pinned_sha256)
                    ):
                        raise FactoryError(
                            "run state AGY executable identity changed",
                            "preflight",
                        )
                    self._save(
                        run_dir,
                        state,
                        "preflight",
                        agy_executable_path=pinned_path,
                        agy_executable_sha256=pinned_sha256,
                    )
        self._smoke_role(run_dir, "Sol", config.reviewer_provider or config.sol_provider, config.reviewer_model or config.sol_model, config.role_timeout)

    def plan(self, config: Config) -> str:
        repo = self._repo(config.repo)
        config.repo = str(repo)
        source_status_before = self._source_status(repo)
        if config.requested_files is not None:
            config.requested_files = normalized_paths(config.requested_files)
            ensure_paths_confined(repo, config.requested_files)
            ensure_head_paths_not_symlinks(repo, config.requested_files)
        identifier = run_id()
        run_dir = self._run_dir(identifier)
        run_dir.mkdir(parents=True, mode=0o700)

        classifier_info = classify_objective(config.request)
        root_objective_class = classifier_info["classification"]

        state = {
            "schema_version": SCHEMA_VERSION,
            "run_config_version": RUN_CONFIG_VERSION,
            "builder_backend": "agy",
            "builder_contract_version": BUILDER_CONTRACT_VERSION,
            "run_id": identifier,
            "phase": "initializing",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "config": asdict(config),
            "request_ref": None,
            "master_plan_ref": None,
            "current_task_id": None,
            "current_task_attempts": 0,
            "active_attempt_ref": None,
            "candidate_baseline_identity": None,
            "builder_dispatch": None,
            "luna_invocation_count": 0,
            "candidate_id": None,
            "candidate_state_identity": None,
            "verification_ref": None,
            "verification_attestation_sha256": None,
            "review_ref": None,
            "pending_commit": None,
            "completed_commits": [],
            "criterion_evidence": {},
            "replan_reason_ref": None,
            "replan_history": [],
            "block_reason": None,
            "base_commit": git(repo, "rev-parse", "HEAD").stdout.strip(),
            "source_status_before": source_status_before,
            "objective_class": root_objective_class,
            "objective_classification": classifier_info,
            "astra_invocation_count": 0,
        }
        atomic_json(run_dir / "run_state.json", state)
        request_value = {
            "artifact_type": "request_v1",
            "run_id": identifier,
            "request": config.request,
            "requested_files": config.requested_files,
        }
        request_serialized = (
            json.dumps(request_value, indent=2, sort_keys=True).replace("\n", os.linesep) + os.linesep
        ).encode("utf-8")
        request_ref = f"requests/{hashlib.sha256(request_serialized).hexdigest()}.json"
        request_path = run_dir / request_ref
        atomic_json(request_path, request_value)
        state["request_ref"] = request_ref
        state["request_sha256"] = hashlib.sha256(request_path.read_bytes()).hexdigest()
        atomic_json(run_dir / "run_state.json", state)

        ledger = MemoryLedger(run_dir, identifier, config.repo, root_objective_class)
        try:
            if config.prior_run:
                prior_context = load_prior_run_context(self.state_root, repo, config.prior_run)
                atomic_json(run_dir / "prior_run_context.json", prior_context)
                ledger.record_event(
                    phase="prior_run_load",
                    action="load_prior_run_context",
                    result="success",
                    details={
                        "prior_run_id": config.prior_run,
                        "unresolved": prior_context["ledger_summary"].get("open", 0),
                    },
                    artifacts=["prior_run_context.json"],
                )
            self._capability_preflight(run_dir, state, config)
            ledger.record_event(phase="preflight", action="preflight_check", result="success")
            self._perform_planning(run_dir, state, config, repo, ledger=ledger)
            return identifier
        except FactoryError as exc:
            ledger.record_event(
                phase="blocked" if exc.category in {"preflight", "provider"} else "failed",
                action="planning_aborted",
                result=exc.category,
                details={"error": str(exc), "category": exc.category},
            )
            self._save(
                run_dir,
                state,
                "blocked" if exc.category in {"preflight", "provider"} else "failed",
                error=str(exc),
                error_category=exc.category,
            )
            raise

    def _create_worktree(self, run_dir: Path, state: dict[str, Any], config: Config) -> Path:
        repo = Path(config.repo)
        current = git(repo, "rev-parse", "HEAD").stdout.strip()
        source_base = state.get("source_head_before", state["base_commit"])
        if current != source_base:
            raise FactoryError(
                f"base moved since planning: expected {source_base}, found {current}", "base"
            )
        worktree = run_dir / "worktree"
        if worktree.is_dir():
            return worktree
        branch = f"hermes/task-{state['run_id']}"
        result = command(["git", "worktree", "add", "-b", branch, str(worktree), state["base_commit"]], cwd=repo, timeout=120)
        if result.returncode != 0:
            raise FactoryError(f"could not create isolated worktree: {(result.stderr or result.stdout).strip()}", "git")
        common_dir_raw = git(worktree, "rev-parse", "--git-common-dir").stdout.strip()
        common_dir = Path(common_dir_raw)
        if not common_dir.is_absolute():
            common_dir = (worktree / common_dir).resolve()
        else:
            common_dir = common_dir.resolve()
        self._save(
            run_dir,
            state,
            "worktree_ready",
            branch=branch,
            worktree=str(worktree),
            factory_worktree_authorized=True,
            candidate_git_common_dir=str(common_dir),
        )
        return worktree

    def _changed_files(self, worktree: Path) -> list[str]:
        tracked = git(worktree, "diff", "--name-only", "HEAD", "--").stdout.splitlines()
        untracked = git(worktree, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
        ignored = git(
            worktree,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
        ).stdout.splitlines()
        return sorted({normalize_path(p) for p in tracked + untracked + ignored if p.strip()})

    def _scope_check(self, worktree: Path, allowed: list[str], label: str, run_dir: Path) -> list[str]:
        # Revalidate after every builder/test boundary. A builder can replace a
        # previously safe file with a symlink before staging.
        ensure_paths_confined(worktree, allowed)
        changed = self._changed_files(worktree)
        outside = sorted(set(changed) - set(allowed))
        evidence = {"label": label, "changed_files": changed, "allowed_files": allowed, "outside_scope": outside}
        atomic_json(run_dir / f"scope_{label}.json", evidence)
        if outside:
            raise FactoryError(f"scope violation after {label}: {outside}", "scope")
        return changed

    def _artifact_sequence(self, sequence: int) -> int:
        return getattr(self, "_artifact_offset", 0) + sequence

    def _detect_test(self, worktree: Path) -> str | None:
        package = worktree / "package.json"
        if package.is_file():
            try:
                data = read_json(package)
                if isinstance(data.get("scripts", {}).get("test"), str):
                    return "npm test"
            except (OSError, json.JSONDecodeError, AttributeError):
                pass
        if (worktree / "pytest.ini").is_file() or (worktree / "pyproject.toml").is_file() or (worktree / "tests").is_dir():
            return "pytest"
        if (worktree / "Cargo.toml").is_file():
            return "cargo test"
        if (worktree / "go.mod").is_file():
            return "go test ./..."
        return None

    def _test(self, worktree: Path, config: Config, run_dir: Path, sequence: int) -> dict[str, Any]:
        artifact_sequence = self._artifact_sequence(sequence)
        test_command = config.test_command or self._detect_test(worktree)
        if not test_command:
            result = {
                "sequence": sequence,
                "artifact_sequence": artifact_sequence,
                "command": None,
                "returncode": None,
                "passed": False,
                "error": "no test command supplied or detected",
            }
            atomic_json(run_dir / f"test_{artifact_sequence}.json", result)
            raise FactoryError("no test command supplied or safely auto-detected", "test")
        test_command = normalize_test_command(test_command)
        test_env = os.environ.copy()
        # Test runners must not manufacture Git-visible Python bytecode outside
        # the approved file boundary. Other generated outputs remain subject to
        # the normal post-test scope gate and should be listed in .gitignore.
        test_env["PYTHONDONTWRITEBYTECODE"] = "1"
        lib_dir = worktree / "lib"
        if lib_dir.is_dir():
            current_pp = test_env.get("PYTHONPATH", "")
            test_env["PYTHONPATH"] = f"{str(lib_dir)}{os.pathsep}{current_pp}" if current_pp else str(lib_dir)
        executed = command(
            test_command,
            cwd=worktree,
            env=test_env,
            timeout=config.test_timeout,
            shell=True,
        )
        log_path = run_dir / f"test_{artifact_sequence}.log"
        log_text = (executed.stdout or "") + ("\n" + executed.stderr if executed.stderr else "")
        write_text(log_path, log_text)
        log_sha256 = hashlib.sha256(log_path.read_bytes()).hexdigest()
        result = {
            "sequence": sequence,
            "artifact_sequence": artifact_sequence,
            "command": test_command,
            "returncode": executed.returncode,
            "passed": executed.returncode == 0,
            "log": str(log_path),
            "log_sha256": log_sha256,
        }
        result_path = run_dir / f"test_{artifact_sequence}.json"
        atomic_json(result_path, result)
        # Keep the exact Runner result identity outside the mutable JSON fields.
        # The caller carries this returned snapshot through the review gate and
        # persists its digest in run state for safe resume.
        result["artifact_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
        return result

    def _builder_instruction(self, config: Config, plan: dict[str, Any]) -> str:
        return (
            "Goal:\nImplement the current task from Astra's immutable master plan.\n\n"
            f"Context:\nOriginal request: {config.request}\n"
            "Astra owns strategy and task contracts; Hermes owns execution and sequencing; Sol independently "
            "reviews the candidate. AGY is the direct Builder; apply the current task contract without inventing "
            "a second design. Luna is outside the v1 production path.\n\n"
            "Scope:\nAllowed files (hard boundary):\n"
            + "\n".join(f"- {p}" for p in plan["allowed_files"])
            + "\n\nConstraints:\n"
            "- Do not redesign the plan.\n- Do not add dependencies.\n- Do not edit files outside the boundary.\n"
            "- Do not commit; the factory owns Git.\n\n"
            "Implementation steps:\n"
            + "\n".join(f"{i + 1}. {step}" for i, step in enumerate(plan["implementation_steps"]))
            + "\n\nDone when:\n"
            + "\n".join(
                f"- {item['id']}: {item['statement']}"
                if isinstance(item, dict)
                else f"- {item}"
                for item in plan["acceptance_criteria"]
            )
            + "\n\nPreservation constraints:\n"
            + "\n".join(f"- {item}" for item in plan.get("risks", []))
        )

    @staticmethod
    def _shrink_builder_instruction(
        instruction: str,
        allowed_files: list[str] | None = None,
    ) -> str:
        """Compact redundant context while retaining the current task contract."""
        if len(instruction) <= 12_000:
            return instruction

        def compact(text: str, limit: int) -> str:
            if len(text) <= limit:
                return text
            head = limit // 2
            tail = limit - head
            retained_head = text[:head]
            retained_tail = text[-tail:]
            anchor_lines = [
                line.strip()
                for line in text.splitlines()
                if re.search(
                    r"(?i)(objective|task|scope|allow|editable|symbol|acceptance|"
                    r"criterion|invariant|constraint|failure|must|function|method|class|\.py(?:[: )]|$))",
                    line,
                )
            ]
            anchors = list(dict.fromkeys(anchor_lines))
            middle_anchors = "\n".join(
                line for line in anchors if line not in retained_head and line not in retained_tail
            )
            return (
                retained_head
                + "\n...[redundant context omitted]...\n"
                + middle_anchors
                + "\n"
                + retained_tail
            )

        heading_pattern = re.compile(
            r"(?m)^(Goal|Context|Scope|Constraints|Implementation steps|Done when|"
            r"Preservation constraints|Failure evidence):[ \t]*$"
        )
        headings = list(heading_pattern.finditer(instruction))
        if headings:
            parts: list[str] = []
            if headings[0].start():
                prefix = instruction[: headings[0].start()].strip()
                if prefix:
                    parts.append(compact(prefix, 4000))
            for index, match in enumerate(headings):
                end = headings[index + 1].start() if index + 1 < len(headings) else len(instruction)
                body = instruction[match.end() : end].strip()
                if match.group(1) in {"Context", "Failure evidence"}:
                    body = compact(body, 7000 if match.group(1) == "Failure evidence" else 5000)
                parts.append(f"{match.group(1)}:\n{body}")
            packet = "\n\n".join(parts)
        else:
            head = instruction[:6000]
            tail = instruction[-6000:]
            anchor_lines = [
                line.strip()
                for line in instruction.splitlines()
                if re.search(
                    r"(?i)(objective|task|scope|allow|editable|symbol|acceptance|"
                    r"criterion|invariant|constraint|failure|must|function|method|class|\.py(?:[: )]|$))",
                    line,
                )
            ]
            anchors = list(dict.fromkeys(anchor_lines))
            retained = head + "\n...[redundant context omitted]...\n"
            retained += "\n".join(line for line in anchors if line not in head and line not in tail)
            retained += "\n" + tail
            packet = retained

        if allowed_files:
            allowed_block = "Authoritative allowed files:\n" + "\n".join(
                f"- {path}" for path in allowed_files
            )
            if allowed_block not in packet:
                packet += "\n\n" + allowed_block
        return (
            "Recovery context is intentionally reduced to the current task and latest failure. "
            "Do not search unrelated files.\n\n" + packet
        )

    @staticmethod
    def _navigation_hints(instruction: str, allowed: list[str]) -> tuple[list[str], list[str]]:
        paths: list[str] = []
        for relative in allowed:
            basename = PurePosixPath(relative).name
            if relative in instruction or basename in instruction:
                paths.append(relative)
        symbols = re.findall(
            r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)`",
            instruction,
        )
        symbols.extend(
            re.findall(
                r"\b(?:function|method|class)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)",
                instruction,
                flags=re.IGNORECASE,
            )
        )
        return list(dict.fromkeys(paths)), list(dict.fromkeys(symbols))

    @staticmethod
    def _navigation_line_hint(instruction: str, relative: str) -> int | None:
        basename = PurePosixPath(relative).name
        for token in (relative, basename):
            escaped = re.escape(token)
            for pattern in (
                rf"(?<![A-Za-z0-9_./-]){escaped}\s*:\s*(\d+)\b",
                rf"(?<![A-Za-z0-9_./-]){escaped}\s+\(?\s*line\s+(\d+)\s*\)?\b",
            ):
                match = re.search(pattern, instruction, flags=re.IGNORECASE)
                if match:
                    value = int(match.group(1))
                    if value > 0:
                        return value
        return None

    def _select_builder_surface(
        self,
        *,
        worktree: Path,
        run_dir: Path,
        config: Config,
        plan: dict[str, Any],
        instruction: str,
        recovery_stage: int,
        attempt: int,
    ) -> dict[str, Any]:
        allowed = list(plan["allowed_files"])
        if (
            not isinstance(self.builder, AgyBuilder)
            or config.agy_navigation_recovery != "adaptive"
            or recovery_stage <= 0
        ):
            return {"kind": "normal", "strategy": "normal", "visible_files": None}
        hinted_paths, hinted_symbols = self._navigation_hints(instruction, allowed)
        python_paths = [path for path in hinted_paths if path.lower().endswith(".py")]
        localized: list[tuple[str, str, dict[str, Any]]] = []
        for relative in python_paths:
                source_path = worktree / Path(relative)
                if not source_path.is_file() or source_path.is_symlink():
                    continue
                source = source_path.read_text(encoding="utf-8")
                for symbol in hinted_symbols:
                    try:
                        located = locate_python_symbol(source, symbol=symbol)
                    except FactoryError:
                        continue
                    localized.append((relative, source, located))
                if not hinted_symbols:
                    line_hint = self._navigation_line_hint(instruction, relative)
                    if line_hint is not None:
                        try:
                            located = locate_python_symbol(source, line=line_hint)
                        except FactoryError:
                            located = None
                        if located is not None:
                            localized.append((relative, source, located))

        def capsule_surface(relative: str, source: str, located: dict[str, Any]) -> dict[str, Any] | None:
            source_path = worktree / Path(relative)
            if not source_path.is_file() or source_path.is_symlink():
                return None
            baseline = AgyBuilder._candidate_baseline_identity(worktree)
            capsule = create_python_capsule(
                source,
                source_path=relative,
                base_commit=git(worktree, "rev-parse", "HEAD").stdout.strip(),
                candidate_baseline_sha256=baseline["complete_identity_sha256"],
                task_id=str(plan.get("task_id", "unknown")),
                attempt=attempt,
                symbol=located["qualified_symbol"],
            )
            canonical = json.dumps(
                capsule, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            digest = hashlib.sha256(canonical).hexdigest()
            ref = f"capsules/{digest}.json"
            atomic_json(run_dir / ref, capsule)
            return {
                "kind": "python_capsule",
                "strategy": "python_symbol_capsule",
                "surface_ref": ref,
                "visible_files": [CAPSULE_EDITABLE_FILE],
                "editable_file": CAPSULE_EDITABLE_FILE,
                "capsule": capsule,
                "capsule_source": capsule["capsule_source"],
                "target_symbols": [capsule["qualified_symbol"]],
            }

        if len(localized) == 1 and recovery_stage < 2:
            relative, source, located = localized[0]
            surface = capsule_surface(relative, source, located)
            if surface is not None:
                return surface

        exact = discover_exact_python_definition(worktree, instruction, allowed)
        exact_candidate = exact.get("candidate") if exact.get("status") == "UNIQUE" else None
        if isinstance(exact_candidate, dict):
            if (
                recovery_stage < 2
                and exact_candidate.get("node_kind") in {"FunctionDef", "AsyncFunctionDef"}
            ):
                surface = capsule_surface(
                    str(exact_candidate["file_path"]),
                    str(exact_candidate["source"]),
                    exact_candidate,
                )
                if surface is not None:
                    return surface
            exact_path = exact_candidate.get("file_path")
            exact_symbol = exact_candidate.get("qualified_symbol")
        else:
            exact_path = None
            exact_symbol = None

        visible = (
            [exact_path]
            if isinstance(exact_path, str) and exact_path
            else hinted_paths or [path for path in allowed if path.lower().endswith(".py")]
        )
        if not visible:
            visible = allowed
        return {
            "kind": "path_reduced",
            "strategy": "path_reduced",
            "visible_files": list(dict.fromkeys(visible)),
            "target_symbols": (
                [exact_symbol]
                if isinstance(exact_symbol, str) and exact_symbol
                else hinted_symbols
            ),
        }

    def _run_builder_attempt(
        self,
        *,
        worktree: Path,
        instruction: str,
        allowed_files: list[str],
        config: Config,
        run_dir: Path,
        label: str,
        surface: dict[str, Any],
    ) -> None:
        """Shared Builder call boundary; injected test Builders keep their API."""
        kwargs: dict[str, Any] = {
            "worktree": worktree,
            "instruction": instruction,
            "allowed_files": allowed_files,
            "config": config,
            "run_dir": run_dir,
            "label": label,
        }
        if isinstance(self.builder, AgyBuilder) and "surface" in inspect.signature(self.builder.run).parameters:
            kwargs["surface"] = surface
        self.builder.run(**kwargs)

    @staticmethod
    def _surface_instruction(instruction: str, surface: dict[str, Any]) -> str:
        kind = surface.get("kind")
        if kind == "python_capsule":
            capsule = surface.get("capsule")
            if not isinstance(capsule, dict):
                raise FactoryError("Python capsule instruction metadata is invalid", "navigation")
            return (
                "Navigation recovery is active. The only visible and editable file is target.py, "
                "a synthetic wrapper containing the exact Python symbol below. Do not search for the "
                "original source path, inspect other files, create files, run project-wide searches, "
                "or edit capsule metadata. Make the smallest requested change inside the named symbol.\n\n"
                f"Original source path: {capsule.get('source_path')}\n"
                f"Qualified symbol: {capsule.get('qualified_symbol')}\n"
                f"Node kind: {capsule.get('node_kind')}\n\n"
                + instruction
            )
        if kind == "path_reduced":
            visible = surface.get("visible_files", [])
            return (
                "Navigation recovery is active. Inspect only these visible task files and do not search "
                "outside them:\n"
                + "\n".join(f"- {item}" for item in visible)
                + "\n\n"
                + instruction
            )
        return instruction

    def _builder_artifacts(self, run_dir: Path, label: str) -> list[str]:
        if not isinstance(self.builder, AgyBuilder):
            return []
        artifact = self.builder.last_attempt_artifact
        expected_root = run_dir.expanduser().resolve() / "builder_attempts"
        if (
            not isinstance(artifact, str)
            or not artifact
            or not Path(artifact).is_file()
            or self.builder.last_attempt_label != label
            or self.builder.last_attempt_run_root != run_dir.expanduser().resolve()
        ):
            raise BuilderFailure(
                "AGY Builder completed without a verified current attempt artifact",
                code="agy_output_incomplete",
                non_resumable=True,
            )
        artifact_path = Path(artifact).resolve()
        try:
            artifact_path.relative_to(expected_root)
        except ValueError as exc:
            raise BuilderFailure(
                "AGY Builder attempt artifact is outside the active run",
                code="agy_isolation_failed",
                non_resumable=True,
            ) from exc
        if (
            artifact_path.name != "attempt.json"
            or artifact_path.parent.parent != expected_root
            or not artifact_path.parent.name.startswith(f"{label}-")
        ):
            raise BuilderFailure(
                "AGY Builder attempt artifact is not bound to the active label",
                code="agy_isolation_failed",
                non_resumable=True,
            )
        return [str(artifact_path)]

    def _stage(
        self,
        worktree: Path,
        allowed: list[str],
        run_dir: Path,
        sequence: int,
    ) -> tuple[str, str, list[str], str]:
        artifact_sequence = self._artifact_sequence(sequence)
        git(worktree, "reset", "--quiet")
        changed = self._scope_check(worktree, allowed, f"prestage_{artifact_sequence}", run_dir)
        if not changed:
            raise FactoryError("builder produced no changes", "builder")
        git(worktree, "add", "--", *allowed)
        diff_text = git(worktree, "diff", "--cached", "--binary", "--no-ext-diff").stdout
        if not diff_text:
            raise FactoryError("staged candidate diff is empty", "git")
        digest = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
        candidate_id = git(worktree, "write-tree").stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", candidate_id):
            raise FactoryError("git write-tree returned an invalid candidate identity", "git")
        write_text(run_dir / f"candidate_{artifact_sequence}.diff", diff_text)
        atomic_json(
            run_dir / f"candidate_{artifact_sequence}.json",
            {
                "sha256": digest,
                "candidate_id": candidate_id,
                "base_commit": git(worktree, "rev-parse", "HEAD").stdout.strip(),
                "changed_files": changed,
            },
        )
        return diff_text, digest, changed, candidate_id

    def _candidate_source_context(
        self,
        worktree: Path,
        allowed: list[str],
        changed: list[str],
        candidate_id: str,
        run_dir: Path,
        sequence: int,
    ) -> dict[str, Any]:
        """Build a bounded, read-only source snapshot for Sol's review.

        The index is used instead of the working tree so the reviewer sees the
        exact candidate that will be hash-checked, including newly created or
        deleted files. Planner and repair transcripts are deliberately omitted.
        """
        artifact_sequence = self._artifact_sequence(sequence)
        preferred_budget = 24_000
        remaining = preferred_budget
        files: dict[str, Any] = {}
        omitted_paths: list[str] = []
        ordered_paths = list(dict.fromkeys(list(changed) + sorted(set(allowed) - set(changed))))
        for relative in ordered_paths:
            shown = command(["git", "show", f":{relative}"], cwd=worktree, timeout=30)
            if shown.returncode != 0:
                files[relative] = {"state": "deleted-or-absent"}
                continue
            raw = shown.stdout
            if "\x00" in raw:
                files[relative] = {"state": "binary-or-non-text", "included": False}
                continue
            if relative not in changed and remaining <= 0:
                files[relative] = {
                    "state": "present",
                    "included": False,
                    "omitted": True,
                    "reason": "preferred soft context budget exhausted",
                    "size": len(raw),
                }
                omitted_paths.append(relative)
                continue
            # The budget is a soft prompt-shaping preference, not an evidence
            # invariant. Always retain the complete text of a small affected
            # file; larger context is permitted when it is the useful evidence
            # for a finding. Unchanged files are progressively disclosed only
            # after affected files have been considered.
            if relative in changed:
                excerpt = raw
            else:
                excerpt = raw[: min(len(raw), max(remaining, 12_000))]
            files[relative] = {
                "state": "present",
                "content": excerpt,
                "truncated": len(excerpt) < len(raw),
            }
            remaining -= len(excerpt)
        context = {
            "source": "staged index exact candidate state",
            "base_commit": git(worktree, "rev-parse", "HEAD").stdout.strip(),
            "candidate_id": candidate_id,
            "files": files,
            "preferred_context_budget_chars": preferred_budget,
            "context_chars": sum(
                len(item.get("content", "")) for item in files.values() if isinstance(item, dict)
            ),
            "soft_budget_exceeded": remaining < 0,
            "omitted_paths": omitted_paths,
            "note": "Read-only context; affected files are prioritized, and every omitted path is explicitly disclosed.",
        }
        atomic_json(run_dir / f"candidate_source_context_{artifact_sequence}.json", context)
        return context

    def _review(
        self,
        *,
        run_dir: Path,
        config: Config,
        plan: dict[str, Any],
        diff_text: str,
        digest: str,
        base_commit: str,
        candidate_id: str,
        changed: list[str],
        candidate_source_context: dict[str, Any],
        tests: list[dict[str, Any]],
        sequence: int,
        review_mode: str = "LARGE_STEP_REVIEW",
        predecessor_review_ref: str | None = None,
        target_finding_ids: list[str] | None = None,
        predecessor_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact_sequence = self._artifact_sequence(sequence)
        review_state = read_json(run_dir / "run_state.json")
        verification_ref = review_state.get("verification_ref") if isinstance(review_state, dict) else None
        if not isinstance(verification_ref, str):
            raise FactoryError("Sol review has no verification artifact", "state")
        verification_contract = self._validate_verification_attestation(
            run_dir,
            verification_ref,
            attestation_sha256=review_state.get("verification_attestation_sha256"),
            expected_task_id=plan.get("task_id"),
            expected_base_commit=base_commit,
            expected_candidate_id=candidate_id,
            expected_command=normalize_test_command(config.test_command) if config.test_command else None,
        )
        if not isinstance(review_state, dict):
            raise FactoryError("Sol review has no execution identity", "state")
        repair_delta = None
        if isinstance(predecessor_review_ref, str):
            match = re.fullmatch(r"sol_review_([0-9]+)\.json", predecessor_review_ref)
            if match:
                prior_candidate_path = run_dir / f"candidate_{match.group(1)}.json"
                if prior_candidate_path.is_file():
                    prior_candidate = read_json(prior_candidate_path)
                    prior_candidate_id = prior_candidate.get("candidate_id") if isinstance(prior_candidate, dict) else None
                    if isinstance(prior_candidate_id, str):
                        compared = git(
                            Path(config.repo),
                            "diff",
                            prior_candidate_id,
                            candidate_id,
                            "--binary",
                            "--no-ext-diff",
                        )
                        if compared.returncode == 0:
                            repair_delta = compared.stdout
        if repair_delta is None:
            repair_delta = diff_text
        replan_identity = {
            "artifact_ref": f"sol_review_{artifact_sequence}.json",
            "producer": "Sol Reviewer",
            "run_id": review_state.get("run_id"),
            "master_plan_ref": review_state.get("master_plan_ref"),
            "request_ref": review_state.get("request_ref"),
            "request_sha256": review_state.get("request_sha256"),
            "task_id": review_state.get("current_task_id"),
            "base_commit": base_commit,
            "candidate_id": candidate_id,
            "candidate_ref": review_state.get("candidate_ref"),
            "verification_ref": verification_ref,
            "verification": verification_contract,
            "verification_attestation_sha256": verification_contract["attestation_sha256"],
            "sequence": artifact_sequence,
        }
        verified_test_evidence = review_test_evidence_with_log_tail(tests, run_dir)
        evidence_packet = make_review_evidence_packet(
            diff_text=diff_text,
            digest=digest,
            base_commit=base_commit,
            candidate_id=candidate_id,
            changed=changed,
            candidate_source_context=candidate_source_context,
            tests=verified_test_evidence,
            plan=plan,
            sequence=sequence,
            review_mode=review_mode,
            predecessor_review_ref=predecessor_review_ref,
            target_finding_ids=target_finding_ids,
            repair_delta=repair_delta,
        )
        atomic_json(run_dir / f"evidence_packet_review_{artifact_sequence}.json", evidence_packet)
        # Deliberately omit planner transcript/history. This is a fresh process and clean input.
        review_plan = plan
        if review_mode == "FINDING_ONLY_RECHECK":
            review_plan = {
                "task_id": plan.get("task_id"),
                "objective": plan.get("objective"),
                "allowed_files": plan.get("allowed_files", []),
                "preservation_constraints": plan.get("preservation_constraints", []),
            }
        payload = {
            "master_plan_task": review_plan,
            "evidence_packet": evidence_packet,
            "candidate_diff": {
                "sha256": digest,
                "base_commit": base_commit,
                "candidate_id": candidate_id,
                "changed_files": changed,
                "patch": repair_delta if review_mode == "FINDING_ONLY_RECHECK" else diff_text,
            },
            "candidate_authority": {
                "base_commit": base_commit,
                "candidate_id": candidate_id,
                "candidate_id_source": "host git write-tree",
                "reviewed_diff_sha256_role": "diagnostic evidence only",
            },
            "repair_delta": repair_delta,
            "candidate_source_context": evidence_packet["candidate_source_context"],
            "test_results": evidence_packet["test_results"],
            "verification": verification_contract,
            "review_mode": review_mode,
            "predecessor_review_ref": predecessor_review_ref,
            "target_finding_ids": target_finding_ids or [],
            "prior_review_findings": (
                [
                    record
                    for record in (predecessor_review or {}).get("finding_records", [])
                    if isinstance(record, dict)
                    and record.get("finding_id") in (target_finding_ids or [])
                ]
            ),
            "replan_reason_contract": {
                "allowed_codes": [
                    "ASSUMPTION_DISPROVED",
                    "REQUIRED_GAP_UNCOVERED",
                    "ARCHITECTURE_DEPENDENCY_CONFLICT",
                ],
                "evidence_identity": replan_identity,
            },
        }
        if review_mode == "LARGE_STEP_REVIEW":
            payload["original_request"] = config.request
        review_criteria_ids = self._task_review_criteria_ids(plan)
        if review_mode == "FINDING_ONLY_RECHECK" and isinstance(predecessor_review, dict):
            review_criteria_ids = sorted(
                {
                    criterion_id
                    for record in predecessor_review.get("finding_records", [])
                    if isinstance(record, dict)
                    and record.get("finding_id") in (target_finding_ids or [])
                    for criterion_id in record.get("criterion_ids", [])
                    if isinstance(criterion_id, str)
                }
            )
        review_phase = (
            f"Review phase:\n{review_mode}. "
            + (
                "This is the one large review for this task; inspect the complete task contract and candidate.\n"
                if review_mode == "LARGE_STEP_REVIEW"
                else "This is a finding-only recheck; inspect only target finding IDs, the exact repair delta, and affected evidence. Do not create a new generic review.\n"
            )
        )
        prompt = (
            "Goal:\nIndependently decide whether the exact candidate diff is safe and complete.\n\n"
            "Context:\nYou are Sol Reviewer in a completely fresh context. Review the request, plan, exact staged diff, "
            "the read-only source snapshot reconstructed from the staged candidate index, and test results. "
            "The source snapshot is bounded and may mark large/binary files as omitted.\n\n"
            + review_phase
            + "Constraints:\n- Do not edit files or call tools.\n- Do not rely on planner conversation history.\n"
            "- Check acceptance criteria, correctness, regressions, architecture, and security.\n"
            "- Treat {base_commit, candidate_id from host git write-tree} as the only candidate authority;\n"
            "  reviewed_diff_sha256 is diagnostic evidence that the patch was presented, not a second identity.\n"
            "- A verified_log_tail in test_results is bounded output from the test log after its SHA-256 matched Runner evidence.\n"
            "- Do not reveal hidden reasoning.\n\n"
            "Output:\nReturn only strict JSON with exactly: decision (APPROVE or REJECT), review_mode, "
            "predecessor_review_ref, target_finding_ids, reviewed_diff_sha256 (copy the supplied hash exactly), "
            "criteria (array of objects), findings (string array), finding_records (array of objects), "
            "base_commit (string), candidate_id (string), required_changes (string array), "
            "route (none or builder). "
            "Also copy the supplied verification object exactly. For a verified strategic invalidation only, "
            "an optional replan_reason object may be included.\n"
            "Each criteria entry must use exactly {\"criterion\": \"criterion_id\", \"passed\": true_or_false}; "
            "cover these exact criterion IDs: " + json.dumps(review_criteria_ids) + ". "
            "Do not use id/status fields in criteria. On APPROVE, finding_records must be []. "
            "On REJECT, each finding_records entry must have exactly finding_id (task-prefixed -F001 style), "
            "status (OPEN), criterion_ids (string array), summary (string), evidence (string), "
            "required_correction (string). Do not return partial finding records.\n\n"
            "Done when:\nAPPROVE means route=none and no required_changes. REJECT means concrete changes and route=builder.\n\n"
            "Input:\n" + json.dumps(payload, indent=2)
        )
        review = self._role_call(
            run_dir=run_dir,
            role="Sol Reviewer",
            provider=config.reviewer_provider or config.sol_provider,
            model=config.reviewer_model or config.sol_model,
            prompt=prompt,
            label=f"sol_review_{artifact_sequence}",
            timeout=config.role_timeout,
            reasoning=config.reviewer_reasoning,
        )
        # Legacy deterministic role fixtures may omit the protocol metadata;
        # Hermes supplies the already-resolved phase identity. A real Sol
        # response is still validated against these values below.
        review = validate_review(
            review,
            digest,
            base_commit,
            candidate_id,
            review_criteria_ids,
            verification_contract,
            expected_review_mode=review_mode,
            expected_predecessor_review_ref=predecessor_review_ref,
            expected_target_finding_ids=target_finding_ids or [],
            task_id=str(plan.get("task_id") or review_state.get("current_task_id") or "TASK"),
            predecessor_review=predecessor_review,
            expected_repair_delta_sha256=hashlib.sha256(repair_delta.encode("utf-8")).hexdigest(),
            expected_verification_ref=verification_contract["attestation_ref"],
        )
        review_path = run_dir / f"sol_review_{artifact_sequence}.json"
        if review_path.exists():
            raise FactoryError("Sol review artifact identity collision", "blocked")
        atomic_json(review_path, review)
        return review

    @staticmethod
    def _review_retry_context(
        run_dir: Path, review_ref: str | None, task_id: str
    ) -> tuple[str, str | None, list[str], dict[str, Any] | None]:
        if not isinstance(review_ref, str) or not review_ref:
            return "LARGE_STEP_REVIEW", None, [], None
        review_path = (run_dir / review_ref).resolve()
        try:
            review_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("prior Sol review reference escapes the run directory", "state") from exc
        if not review_path.is_file():
            raise FactoryError("prior Sol review artifact is missing", "state")
        prior_review = read_json(review_path)
        if not isinstance(prior_review, dict):
            raise FactoryError("prior Sol review artifact is not an object", "state")
        return "FINDING_ONLY_RECHECK", review_ref, open_review_finding_ids(prior_review, task_id), prior_review

    @staticmethod
    def _load_review_predecessor(
        run_dir: Path, review: dict[str, Any]
    ) -> dict[str, Any] | None:
        predecessor_ref = review.get("predecessor_review_ref")
        if predecessor_ref is None:
            return None
        if not isinstance(predecessor_ref, str) or not re.fullmatch(
            r"sol_review_[0-9]+\.json", predecessor_ref
        ):
            raise FactoryError("Sol review predecessor reference is invalid", "state")
        path = (run_dir / predecessor_ref).resolve()
        try:
            path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("Sol review predecessor escapes the run directory", "state") from exc
        if not path.is_file():
            raise FactoryError("Sol review predecessor artifact is missing", "state")
        value = read_json(path)
        if not isinstance(value, dict):
            raise FactoryError("Sol review predecessor artifact is invalid", "state")
        return value

    def _create_checkpoint(self, worktree: Path, run_dir: Path, label: str) -> dict[str, Any]:
        """Capture a safe checkpoint of the worktree state with durable refs and binary fidelity."""
        offset = getattr(self, "_artifact_offset", 0)
        artifact_label = label if not offset else f"{label}_{offset}"
        # 1. Capture stash commit if any changes exist
        stash_res = command(["git", "stash", "create"], cwd=worktree)
        if stash_res.returncode != 0:
            raise FactoryError(f"git stash create failed: {stash_res.stderr}", "checkpoint")
        stash_commit = stash_res.stdout.strip()
        stash_ref = None
        if stash_commit:
                stash_ref = f"refs/factory/checkpoints/{artifact_label}_{uuid.uuid4().hex[:8]}"
                ref_res = command(["git", "update-ref", stash_ref, stash_commit], cwd=worktree)
                if ref_res.returncode != 0:
                    raise FactoryError(f"git update-ref failed: {ref_res.stderr}", "checkpoint")

        # 2. Capture diffs with returncode validation
        unstaged_res = command(["git", "diff"], cwd=worktree)
        if unstaged_res.returncode != 0:
            raise FactoryError(f"git diff failed: {unstaged_res.stderr}", "checkpoint")
        staged_res = command(["git", "diff", "--cached"], cwd=worktree)
        if staged_res.returncode != 0:
            raise FactoryError(f"git diff --cached failed: {staged_res.stderr}", "checkpoint")

        # 3. Capture untracked files safely with NUL delimiter and base64 encoding
        untracked_res = command(["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=worktree)
        if untracked_res.returncode != 0:
            raise FactoryError(f"git ls-files failed: {untracked_res.stderr}", "checkpoint")

        raw_paths = untracked_res.stdout.split("\0")
        untracked_files: dict[str, dict[str, Any]] = {}
        for rel_p in raw_paths:
            if not rel_p:
                continue
            full_p = worktree / rel_p
            if full_p.is_symlink():
                untracked_files[rel_p] = {
                    "type": "symlink",
                    "target": os.readlink(full_p),
                }
            elif full_p.is_file():
                content_bytes = full_p.read_bytes()
                mode = full_p.stat().st_mode
                untracked_files[rel_p] = {
                    "type": "file",
                    "data": base64.b64encode(content_bytes).decode("ascii"),
                    "mode": oct(mode),
                }

        checkpoint = {
            "label": artifact_label,
            "created_at": now_iso(),
            "stash_commit": stash_commit,
            "stash_ref": stash_ref,
            "unstaged_diff": unstaged_res.stdout,
            "staged_diff": staged_res.stdout,
            "untracked_files": untracked_files,
        }
        atomic_json(run_dir / f"checkpoint_{artifact_label}.json", checkpoint)
        return checkpoint

    def _safe_rollback(self, worktree: Path, checkpoint: dict[str, Any], run_dir: Path) -> None:
        """Safely restore the worktree to the state recorded in checkpoint and verify exact restoration."""
        # 1. Reset and clean strictly
        reset_res = command(["git", "reset", "--hard", "HEAD"], cwd=worktree)
        if reset_res.returncode != 0:
            raise FactoryError(f"git reset --hard failed: {reset_res.stderr}", "rollback")
        clean_res = command(["git", "clean", "-fd", "-q"], cwd=worktree)
        if clean_res.returncode != 0:
            raise FactoryError(f"git clean failed: {clean_res.stderr}", "rollback")

        # 2. Restore tracked changes
        stash_commit = checkpoint.get("stash_commit")
        if stash_commit:
            apply_res = command(["git", "stash", "apply", "--index", "--quiet", stash_commit], cwd=worktree)
            if apply_res.returncode != 0:
                raise FactoryError(f"git stash apply --index failed: {apply_res.stderr}", "rollback")
        else:
            staged_diff = checkpoint.get("staged_diff") or ""
            if staged_diff:
                apply_staged = command(["git", "apply", "--index", "--whitespace=nowarn"], cwd=worktree, stdin=staged_diff)
                if apply_staged.returncode != 0:
                    raise FactoryError(f"git apply --index failed: {apply_staged.stderr}", "rollback")
            unstaged_diff = checkpoint.get("unstaged_diff") or ""
            if unstaged_diff:
                apply_unstaged = command(["git", "apply", "--whitespace=nowarn"], cwd=worktree, stdin=unstaged_diff)
                if apply_unstaged.returncode != 0:
                    raise FactoryError(f"git apply unstaged failed: {apply_unstaged.stderr}", "rollback")

        # 3. Restore untracked files byte-for-byte and symlinks
        untracked_files = checkpoint.get("untracked_files") or {}
        for rel_p, file_meta in untracked_files.items():
            target_path = worktree / rel_p
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if file_meta.get("type") == "symlink":
                target = file_meta.get("target")
                if target:
                    if target_path.is_symlink() or target_path.exists():
                        target_path.unlink()
                    os.symlink(target, target_path)
            elif file_meta.get("type") == "file":
                data_b64 = file_meta.get("data", "")
                content_bytes = base64.b64decode(data_b64)
                target_path.write_bytes(content_bytes)
                mode_str = file_meta.get("mode")
                if mode_str and os.name != "nt":
                    try:
                        os.chmod(target_path, int(mode_str, 8))
                    except Exception as e:
                        raise FactoryError(f"Failed to restore mode for {rel_p}: {e}", "rollback")

        # 4. Post-rollback verification: confirm worktree state matches checkpoint exactly
        post_unstaged = command(["git", "diff"], cwd=worktree)
        if post_unstaged.returncode != 0:
            raise FactoryError(f"git diff verification failed: {post_unstaged.stderr}", "rollback")
        post_staged = command(["git", "diff", "--cached"], cwd=worktree)
        if post_staged.returncode != 0:
            raise FactoryError(f"git diff --cached verification failed: {post_staged.stderr}", "rollback")
        if post_unstaged.stdout != checkpoint.get("unstaged_diff", ""):
            raise FactoryError("rollback verification failed: unstaged diff mismatch", "rollback")
        if post_staged.stdout != checkpoint.get("staged_diff", ""):
            raise FactoryError("rollback verification failed: staged diff mismatch", "rollback")

        # 5. Post-rollback verification for untracked files: exact path set and content match
        post_untracked_res = command(["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=worktree)
        if post_untracked_res.returncode != 0:
            raise FactoryError(f"git ls-files verification failed: {post_untracked_res.stderr}", "rollback")
        post_raw_paths = [p for p in post_untracked_res.stdout.split("\0") if p]
        checkpoint_untracked = checkpoint.get("untracked_files") or {}
        if set(post_raw_paths) != set(checkpoint_untracked.keys()):
            raise FactoryError(
                f"rollback verification failed: untracked path mismatch (expected {sorted(checkpoint_untracked.keys())}, got {sorted(post_raw_paths)})",
                "rollback",
            )
        for rel_p in post_raw_paths:
            expected_meta = checkpoint_untracked[rel_p]
            current_p = worktree / rel_p
            if expected_meta.get("type") == "symlink":
                if not current_p.is_symlink() or os.readlink(current_p) != expected_meta.get("target"):
                    raise FactoryError(f"rollback verification failed: symlink mismatch for {rel_p}", "rollback")
            elif expected_meta.get("type") == "file":
                if not current_p.is_file():
                    raise FactoryError(f"rollback verification failed: {rel_p} is not a regular file", "rollback")
                curr_bytes = current_p.read_bytes()
                curr_b64 = base64.b64encode(curr_bytes).decode("ascii")
                if curr_b64 != expected_meta.get("data"):
                    raise FactoryError(f"rollback verification failed: content mismatch for {rel_p}", "rollback")

        atomic_json(
            run_dir / "last_rollback.json",
            {"restored_to": checkpoint.get("label"), "timestamp": now_iso()},
        )

    def _pre_review_gate(
        self,
        worktree: Path,
        allowed: list[str],
        changed: list[str],
        diff_text: str,
        tests: list[dict[str, Any]],
        run_dir: Path,
        sequence: int,
    ) -> dict[str, Any]:
        """Deterministic pre-review gate prior to calling Sol Reviewer."""
        gate_checks: dict[str, bool] = {}

        # 1. Tests must have passed before Sol Reviewer is invoked
        tests_ok = bool(tests and tests[-1].get("passed", False))
        gate_checks["tests_passed"] = tests_ok
        if not tests_ok:
            failure_info = {
                "gate_passed": False,
                "reason": "latest test run did not pass",
                "checks": gate_checks,
            }
            atomic_json(run_dir / f"pre_review_gate_{sequence}.json", failure_info)
            raise FactoryError("deterministic pre-review gate failed: tests have not passed", "pre_review_gate")

        # 2. Diff must be non-empty and scope strictly confined
        diff_ok = bool(diff_text.strip())
        scope_ok = bool(changed and set(changed).issubset(set(allowed)))
        gate_checks["diff_non_empty"] = diff_ok
        gate_checks["scope_confined"] = scope_ok
        if not diff_ok or not scope_ok:
            failure_info = {
                "gate_passed": False,
                "reason": "empty diff or out-of-scope files",
                "checks": gate_checks,
            }
            atomic_json(run_dir / f"pre_review_gate_{sequence}.json", failure_info)
            raise FactoryError("deterministic pre-review gate failed: invalid diff or scope", "pre_review_gate")

        # 3. No git conflict markers in candidate diff
        conflict_pattern = re.compile(r"^\+(<<<<<<<|=======|>>>>>>>)", re.MULTILINE)
        has_conflicts = bool(conflict_pattern.search(diff_text))
        gate_checks["no_conflict_markers"] = not has_conflicts
        if has_conflicts:
            failure_info = {
                "gate_passed": False,
                "reason": "merge conflict markers found in candidate diff",
                "checks": gate_checks,
            }
            atomic_json(run_dir / f"pre_review_gate_{sequence}.json", failure_info)
            raise FactoryError("deterministic pre-review gate failed: merge conflict markers detected", "pre_review_gate")

        # 4. Check syntax for Python files
        for rel_path in changed:
            if rel_path.endswith(".py"):
                file_path = worktree / rel_path
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        compile(content, str(file_path), "exec")
                    except SyntaxError as exc:
                        gate_checks["syntax_valid"] = False
                        failure_info = {
                            "gate_passed": False,
                            "reason": f"syntax error in {rel_path}: {exc}",
                            "checks": gate_checks,
                        }
                        atomic_json(run_dir / f"pre_review_gate_{sequence}.json", failure_info)
                        raise FactoryError(f"deterministic pre-review gate failed: syntax error in {rel_path}: {exc}", "pre_review_gate")
        gate_checks["syntax_valid"] = True

        gate_record = {
            "gate_passed": True,
            "sequence": sequence,
            "checks": gate_checks,
            "checked_at": now_iso(),
        }
        atomic_json(run_dir / f"pre_review_gate_{sequence}.json", gate_record)
        return gate_record

    def _load_master_plan_for_execution(
        self,
        run_dir: Path,
        config: Config,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        plan_ref = state.get("master_plan_ref")
        if not isinstance(plan_ref, str) or not plan_ref:
            raise FactoryError("run has no master_plan_ref", "state")
        plan_path = (run_dir / plan_ref).resolve()
        try:
            plan_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("master_plan_ref escapes the run directory", "state") from exc
        if not plan_path.is_file():
            raise FactoryError("run master plan artifact is missing", "state")
        plan = read_json(plan_path)
        if not isinstance(plan, dict):
            raise FactoryError("run master plan must be a JSON object", "state")
        match = re.fullmatch(r"plans/([0-9a-f]{64})\.json", plan_ref.replace("\\", "/"))
        if not match:
            raise FactoryError("master_plan_ref is not a content-addressed plan reference", "state")
        canonical = json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != match.group(1):
            raise FactoryError("master plan content does not match master_plan_ref", "state")
        plan = validate_master_plan(plan, config.requested_files)
        request_ref = state.get("request_ref")
        if not isinstance(request_ref, str) or plan.get("request_ref") != request_ref:
            raise FactoryError("master plan request identity is stale", "state")
        request_path = (run_dir / request_ref).resolve()
        try:
            request_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("authoritative request reference escapes the run directory", "state") from exc
        if not request_path.is_file():
            raise FactoryError("authoritative request artifact is missing", "state")
        request_value = read_json(request_path)
        if (
            not isinstance(request_value, dict)
            or request_value.get("request") != config.request
            or request_value.get("requested_files") != config.requested_files
            or not re.fullmatch(r"requests/[0-9a-f]{64}\.json", request_ref.replace("\\", "/"))
            or hashlib.sha256(request_path.read_bytes()).hexdigest() != request_ref.replace("\\", "/").split("/")[-1][:-5]
            or request_value.get("run_id") != state.get("run_id")
            or request_value.get("artifact_type") not in {"request_v1", "user_request_change_v1"}
        ):
            raise FactoryError("authoritative request artifact does not match current config", "state")
        request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
        if state.get("request_sha256") != request_sha256:
            raise FactoryError("authoritative request artifact digest is stale", "hash")
        self._validate_replan_history(run_dir, state)
        return plan

    @staticmethod
    def _task_execution_plan(
        master_plan: dict[str, Any], task: dict[str, Any]
    ) -> dict[str, Any]:
        """Adapt one validated master-plan task to the existing Builder gate contract."""
        return {
            "objective": task["objective"],
            "allowed_files": task["editable_scope"],
            "implementation_steps": [task["objective"]],
            "acceptance_criteria": task["acceptance_criteria"],
            "recommended_tests": task["verification_commands"],
            "risks": task["preservation_constraints"],
            "global_criteria": master_plan["global_criteria"],
            "global_criteria_ids": task.get("global_criteria", []),
            "acceptance_criteria_ids": [item["id"] for item in task["acceptance_criteria"]],
            "task_id": task["id"],
        }

    @staticmethod
    def _task_review_criteria_ids(plan: dict[str, Any]) -> list[str]:
        return list(
            dict.fromkeys(
                list(plan.get("global_criteria_ids", []))
                + list(plan.get("acceptance_criteria_ids", []))
            )
        )

    def _record_committed_task_criteria(
        self,
        state: dict[str, Any],
        master_plan: dict[str, Any],
        task: dict[str, Any],
    ) -> None:
        evidence = state.get("criterion_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        state["criterion_evidence"] = evidence

    @staticmethod
    def _bind_criteria_to_commit(
        state: dict[str, Any], task_id: str, commit_hash: str
    ) -> None:
        evidence = state.get("criterion_evidence")
        if not isinstance(evidence, dict):
            return
        for item in evidence.values():
            if isinstance(item, dict) and item.get("task_id") == task_id:
                item["commit"] = commit_hash

    @staticmethod
    def _record_approved_criteria(
        state: dict[str, Any],
        plan: dict[str, Any],
        review: dict[str, Any],
        *,
        base_commit: str,
        candidate_id: str,
        review_ref: str,
        verification_ref: str | None,
        review_sha256: str,
        verification_sha256: str,
        verification_sequence: int,
        review_criteria_ids: list[str] | None = None,
    ) -> None:
        evidence = state.get("criterion_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        raw_owned = plan.get("global_criteria_ids", plan.get("global_criteria", []))
        owned = {
            item.get("id") if isinstance(item, dict) else item
            for item in raw_owned
            if isinstance(item, (dict, str))
        }
        passed = {
            item.get("criterion")
            for item in review.get("criteria", [])
            if isinstance(item, dict) and item.get("passed") is True
        }
        for criterion_id in sorted(owned & passed):
            evidence[criterion_id] = {
                "status": "PASS",
                "task_id": plan.get("task_id"),
                "base_commit": base_commit,
                "candidate_id": candidate_id,
                "review_ref": review_ref,
                "verification_ref": verification_ref,
                "review_sha256": review_sha256,
                "verification_sha256": verification_sha256,
                "verification_sequence": verification_sequence,
                "review_criteria_ids": review_criteria_ids
                or list(
                    dict.fromkeys(
                        list(plan.get("global_criteria_ids", []))
                        + list(plan.get("acceptance_criteria_ids", []))
                    )
                ),
                "task_scope": list(plan.get("allowed_files", [])),
            }
        state["criterion_evidence"] = evidence

    def _create_verification_attestation(
        self,
        run_dir: Path,
        result: dict[str, Any],
        *,
        task_id: str,
        base_commit: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        if not isinstance(result, dict) or not isinstance(result.get("artifact_sequence"), int):
            raise FactoryError("Runner result lacks attestation identity", "state")
        result_ref = f"test_{result['artifact_sequence']}.json"
        result_path = (run_dir / result_ref).resolve()
        log_path = Path(result.get("log", "")).expanduser().resolve()
        try:
            result_path.relative_to(run_dir.resolve())
            log_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("Runner result artifact escapes the run directory", "state") from exc
        if not result_path.is_file() or not log_path.is_file() or log_path.name != f"test_{result['artifact_sequence']}.log":
            raise FactoryError("Runner result artifact or log is missing", "state")
        expected_result_artifact_sha256 = result.get("artifact_sha256")
        actual_result_artifact_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
        if (
            not isinstance(expected_result_artifact_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_result_artifact_sha256)
            or expected_result_artifact_sha256 != actual_result_artifact_sha256
        ):
            raise FactoryError("Runner result artifact digest changed before attestation", "hash")
        result_value = read_json(result_path)
        if (
            not isinstance(result_value, dict)
            or set(result_value) != {
                "sequence", "artifact_sequence", "command", "returncode", "passed", "log", "log_sha256"
            }
            or any(result_value.get(field) != result.get(field) for field in result_value)
        ):
            raise FactoryError("Runner result artifact schema changed before attestation", "hash")
        attestation = {
            "schema_version": 1,
            "task_id": task_id,
            "base_commit": base_commit,
            "candidate_id": candidate_id,
            "sequence": result.get("sequence"),
            "artifact_sequence": result.get("artifact_sequence"),
            "passed": result.get("passed"),
            "returncode": result.get("returncode"),
            "command": result.get("command"),
            "result_artifact_ref": result_ref,
            "result_artifact_sha256": actual_result_artifact_sha256,
            "log_ref": str(log_path.relative_to(run_dir.resolve())).replace("\\", "/"),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        }
        serialized = (
            json.dumps(attestation, indent=2, sort_keys=True).replace("\n", os.linesep) + os.linesep
        ).encode("utf-8")
        digest = hashlib.sha256(serialized).hexdigest()
        attestation_ref = f"attestations/{digest}.json"
        attestation_path = run_dir / attestation_ref
        if attestation_path.is_file() and attestation_path.read_bytes() != serialized:
            raise FactoryError("verification attestation content collision", "state")
        if not attestation_path.is_file():
            atomic_json(attestation_path, attestation)
        return {"attestation_ref": attestation_ref, "attestation_sha256": digest, **attestation}

    @staticmethod
    def _validate_verification_attestation(
        run_dir: Path,
        attestation_ref: str,
        *,
        attestation_sha256: str | None = None,
        expected_task_id: str | None = None,
        expected_base_commit: str | None = None,
        expected_candidate_id: str | None = None,
        expected_command: str | None = None,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"attestations/[0-9a-f]{64}\.json", attestation_ref.replace("\\", "/")):
            raise FactoryError("verification attestation reference is not content-addressed", "state")
        path = (run_dir / attestation_ref).resolve()
        try:
            path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("verification attestation escapes the run directory", "state") from exc
        if not path.is_file():
            raise FactoryError("verification attestation is missing", "state")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        expected_digest = attestation_ref.replace("\\", "/").split("/")[-1][:-5]
        if digest != expected_digest or (attestation_sha256 is not None and digest != attestation_sha256):
            raise FactoryError("verification attestation digest is stale", "hash")
        value = read_json(path)
        required = {
            "schema_version", "task_id", "base_commit", "candidate_id", "sequence",
            "artifact_sequence", "passed", "returncode", "command", "result_artifact_ref",
            "result_artifact_sha256", "log_ref", "log_sha256",
        }
        if not isinstance(value, dict) or set(value) != required or value.get("schema_version") != 1:
            raise FactoryError("verification attestation schema is invalid", "state")
        if (
            not isinstance(value.get("task_id"), str)
            or not isinstance(value.get("base_commit"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", value["base_commit"])
            or not isinstance(value.get("candidate_id"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", value["candidate_id"])
            or isinstance(value.get("sequence"), bool)
            or not isinstance(value.get("sequence"), int)
            or isinstance(value.get("artifact_sequence"), bool)
            or not isinstance(value.get("artifact_sequence"), int)
            or value.get("passed") is not True
            or value.get("returncode") != 0
            or not isinstance(value.get("command"), str)
            or not re.fullmatch(r"test_[0-9]+\.json", value.get("result_artifact_ref", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", value.get("result_artifact_sha256", ""))
            or not re.fullmatch(r"test_[0-9]+\.log", value.get("log_ref", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", value.get("log_sha256", ""))
        ):
            raise FactoryError("verification attestation values are invalid", "state")
        if value["result_artifact_ref"] != f"test_{value['artifact_sequence']}.json":
            raise FactoryError("verification attestation result identity is stale", "state")
        if expected_task_id is not None and value["task_id"] != expected_task_id:
            raise FactoryError("verification attestation task identity is stale", "hash")
        if expected_base_commit is not None and value["base_commit"] != expected_base_commit:
            raise FactoryError("verification attestation base identity is stale", "hash")
        if expected_candidate_id is not None and value["candidate_id"] != expected_candidate_id:
            raise FactoryError("verification attestation candidate identity is stale", "hash")
        if expected_command is not None and value["command"] != expected_command:
            raise FactoryError("verification attestation command is stale", "hash")
        result_path = (run_dir / value["result_artifact_ref"]).resolve()
        log_path = (run_dir / value["log_ref"]).resolve()
        try:
            result_path.relative_to(run_dir.resolve())
            log_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("verification attestation artifact escapes the run directory", "state") from exc
        if not result_path.is_file() or hashlib.sha256(result_path.read_bytes()).hexdigest() != value["result_artifact_sha256"]:
            raise FactoryError("verification attestation result artifact is stale", "hash")
        result = read_json(result_path)
        if (
            not isinstance(result, dict)
            or any(result.get(field) != value[field] for field in ("sequence", "artifact_sequence", "passed", "returncode", "command"))
            or result.get("log") != str(log_path)
            or result.get("log_sha256") != value["log_sha256"]
        ):
            raise FactoryError("verification attestation result differs from Runner output", "hash")
        if not log_path.is_file() or hashlib.sha256(log_path.read_bytes()).hexdigest() != value["log_sha256"]:
            raise FactoryError("verification attestation log is stale", "hash")
        return {"attestation_ref": attestation_ref, "attestation_sha256": digest, **value}

    def _prepare_verification_attestation(
        self,
        run_dir: Path,
        tests: list[dict[str, Any]],
        *,
        task_id: str,
        base_commit: str,
        candidate_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        if not tests or not isinstance(tests[-1], dict):
            raise FactoryError("approved candidate has no verification result", "state")
        result = tests[-1]
        current_ref = state.get("verification_ref")
        current_value = None
        if isinstance(current_ref, str) and current_ref.startswith("attestations/"):
            try:
                current_value = self._validate_verification_attestation(
                    run_dir,
                    current_ref,
                    attestation_sha256=state.get("verification_attestation_sha256"),
                    expected_task_id=task_id,
                    expected_base_commit=base_commit,
                    expected_candidate_id=candidate_id,
                )
            except FactoryError:
                current_value = None
        if current_value is not None and current_value.get("artifact_sequence") == result.get("artifact_sequence"):
            state["verification_ref"] = current_value["attestation_ref"]
            state["verification_attestation_sha256"] = current_value["attestation_sha256"]
            return current_value
        value = self._create_verification_attestation(
            run_dir,
            result,
            task_id=task_id,
            base_commit=base_commit,
            candidate_id=candidate_id,
        )
        state["verification_ref"] = value["attestation_ref"]
        state["verification_attestation_sha256"] = value["attestation_sha256"]
        return value

    @staticmethod
    def _invalidate_affected_criteria(
        state: dict[str, Any], task: dict[str, Any]
    ) -> list[str]:
        evidence = state.get("criterion_evidence")
        if not isinstance(evidence, dict):
            return []
        task_id = task.get("id")
        task_criteria = set(task.get("global_criteria", []))
        task_scope = set(task.get("editable_scope", []))
        affected: list[str] = []
        for criterion_id, item in evidence.items():
            if not isinstance(item, dict):
                continue
            prior_scope = set(item.get("task_scope", [])) if isinstance(item.get("task_scope"), list) else set()
            if (
                criterion_id in task_criteria
                or item.get("task_id") == task_id
                or not task_criteria
                or not prior_scope
                or prior_scope & task_scope
            ):
                item["status"] = "UNVERIFIED"
                item.pop("commit", None)
                affected.append(criterion_id)
        return sorted(set(affected))

    @staticmethod
    def _remaining_master_plan_gaps(
        master_plan: dict[str, Any], state: dict[str, Any]
    ) -> list[str]:
        evidence = state.get("criterion_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        committed = {
            item.get("commit")
            for item in state.get("completed_commits", [])
            if isinstance(item, dict)
        }
        return [
            criterion["id"]
            for criterion in master_plan["global_criteria"]
            if not isinstance(evidence.get(criterion["id"]), dict)
            or evidence[criterion["id"]].get("status") != "PASS"
            or evidence[criterion["id"]].get("commit") not in committed
            or not isinstance(evidence[criterion["id"]].get("task_scope"), list)
            or not evidence[criterion["id"]].get("task_scope")
            or not isinstance(evidence[criterion["id"]].get("task_id"), str)
            or not isinstance(evidence[criterion["id"]].get("base_commit"), str)
            or not isinstance(evidence[criterion["id"]].get("candidate_id"), str)
            or not evidence[criterion["id"]].get("review_ref")
            or not evidence[criterion["id"]].get("verification_ref")
        ]

    @staticmethod
    def _durable_replan_attempt_count(run_dir: Path, state: dict[str, Any]) -> int:
        history = state.get("replan_history")
        if not isinstance(history, list):
            return 0
        values = [
            item.get("sequence")
            for item in history
            if isinstance(item, dict) and isinstance(item.get("sequence"), int)
        ]
        return max(values, default=0)

    @staticmethod
    def _durable_replan_dispatch_count(run_dir: Path) -> int:
        values = []
        for path in run_dir.glob("replan_dispatch_*.json"):
            match = re.fullmatch(r"replan_dispatch_([0-9]+)\.json", path.name)
            if match:
                values.append(int(match.group(1)))
        return max(values, default=0)

    @staticmethod
    def _review_replan_reason(
        review_ref: str, review: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        original = validate_replan_reason(review.get("replan_reason"))
        evidence = dict(original["evidence"])
        evidence["source_artifact_ref"] = evidence.get("artifact_ref")
        evidence["artifact_ref"] = review_ref
        evidence["review_ref"] = review_ref
        evidence["producer"] = "Sol Reviewer"
        evidence["run_id"] = state.get("run_id")
        evidence["master_plan_ref"] = state.get("master_plan_ref")
        evidence["request_ref"] = state.get("request_ref")
        evidence["request_sha256"] = state.get("request_sha256")
        evidence["task_id"] = state.get("current_task_id")
        evidence["base_commit"] = review.get("base_commit")
        evidence["candidate_id"] = review.get("candidate_id")
        evidence["candidate_ref"] = state.get("candidate_ref")
        evidence["verification_ref"] = state.get("verification_ref")
        evidence["verification"] = review.get("verification")
        evidence["verification_attestation_sha256"] = (
            review.get("verification", {}).get("attestation_sha256")
            if isinstance(review.get("verification"), dict)
            else None
        )
        match = re.fullmatch(r"sol_review_([0-9]+)\.json", review_ref)
        evidence["sequence"] = int(match.group(1)) if match else None
        return {"code": original["code"], "evidence": evidence}

    def _validate_replan_evidence(
        self,
        run_dir: Path,
        reason: dict[str, Any],
        state: dict[str, Any],
        *,
        historical: bool = False,
    ) -> str:
        evidence = reason["evidence"]
        artifact_ref = evidence.get("artifact_ref")
        if not isinstance(artifact_ref, str) or not re.fullmatch(
            r"(?:requests/[0-9a-f]{64}|sol_review_[0-9]+|replan_evidence_[0-9]+)\.json",
            artifact_ref,
        ):
            raise FactoryError("replan evidence is not a bounded host artifact", "blocked")
        artifact = (run_dir / artifact_ref).resolve()
        try:
            artifact.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("replan evidence reference escapes the run directory", "blocked") from exc
        if not artifact.is_file():
            raise FactoryError("replan evidence artifact is missing", "blocked")
        value = read_json(artifact)
        code = reason["code"]
        kind = REPLAN_REASON_KINDS[code]

        if code == "USER_OBJECTIVE_OR_SCOPE_CHANGE":
            config = state.get("config")
            request_ref = evidence.get("request_ref")
            request_path = (run_dir / request_ref).resolve() if isinstance(request_ref, str) else None
            request_digest_ok = (
                request_path is not None
                and request_path.is_file()
                and isinstance(evidence.get("request_sha256"), str)
                and hashlib.sha256(request_path.read_bytes()).hexdigest() == evidence["request_sha256"]
            )
            valid = (
                artifact_ref == request_ref
                and isinstance(request_ref, str)
                and re.fullmatch(r"requests/[0-9a-f]{64}\.json", request_ref.replace("\\", "/"))
                and (historical or request_ref == state.get("request_ref"))
                and request_digest_ok
                and evidence.get("request_sha256") == request_ref.replace("\\", "/").split("/")[-1][:-5]
                and isinstance(config, dict)
                and isinstance(value, dict)
                and set(value) == {"artifact_type", "run_id", "request", "requested_files", "reason"}
                and value.get("artifact_type") == "user_request_change_v1"
                and value.get("run_id") == state.get("run_id")
                and (historical or value.get("request") == config.get("request"))
                and (historical or value.get("requested_files") == config.get("requested_files"))
                and isinstance(value.get("requested_files"), list)
                and isinstance(value.get("reason"), dict)
                and value["reason"].get("code") == code
                and value["reason"].get("evidence", {}).get("artifact_ref") == "user_change_request"
                and value["reason"].get("evidence", {}).get("kind") == kind
                and value["reason"].get("evidence", {}).get("verified") is True
            )
            if not valid:
                raise FactoryError("replan evidence is not the current immutable user request artifact", "blocked")
        elif code in {
            "ASSUMPTION_DISPROVED",
            "REQUIRED_GAP_UNCOVERED",
            "ARCHITECTURE_DEPENDENCY_CONFLICT",
        } and re.fullmatch(r"sol_review_[0-9]+\.json", artifact_ref):
            identity_fields = (
                "run_id",
                "master_plan_ref",
                "request_ref",
                "request_sha256",
                "task_id",
                "base_commit",
                "candidate_id",
                "candidate_ref",
                "review_ref",
                "verification_ref",
                "verification",
                "verification_attestation_sha256",
                "sequence",
            )
            if any(field not in evidence for field in identity_fields):
                raise FactoryError("replan evidence Sol reason lacks complete identity", "blocked")
            request_ref = evidence["request_ref"]
            request_path = (run_dir / request_ref).resolve() if isinstance(request_ref, str) else None
            if (
                request_path is None
                or not request_path.is_file()
                or not re.fullmatch(r"requests/[0-9a-f]{64}\.json", request_ref.replace("\\", "/"))
                or not isinstance(evidence["request_sha256"], str)
                or hashlib.sha256(request_path.read_bytes()).hexdigest() != evidence["request_sha256"]
                or evidence["request_sha256"] != request_ref.replace("\\", "/").split("/")[-1][:-5]
            ):
                raise FactoryError("replan evidence request identity is stale", "blocked")
            candidate_ref = evidence["candidate_ref"]
            if not re.fullmatch(r"candidate_[0-9]+\.json", candidate_ref):
                raise FactoryError("replan evidence has no bounded candidate lineage", "blocked")
            candidate_path = (run_dir / candidate_ref).resolve()
            if not candidate_path.is_file():
                raise FactoryError("replan evidence candidate artifact is missing", "blocked")
            candidate = read_json(candidate_path)
            plan_ref = evidence["master_plan_ref"]
            plan_path = (run_dir / plan_ref).resolve() if isinstance(plan_ref, str) else None
            config = state.get("config")
            if plan_path is None or not re.fullmatch(r"plans/[0-9a-f]{64}\.json", plan_ref.replace("\\", "/")):
                raise FactoryError("replan evidence has no bounded master plan lineage", "blocked")
            if not plan_path.is_file():
                raise FactoryError("replan evidence master plan artifact is missing", "blocked")
            plan = read_json(plan_path)
            canonical_plan = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if hashlib.sha256(canonical_plan.encode("utf-8")).hexdigest() != plan_ref.split("/")[-1][:-5]:
                raise FactoryError("replan evidence master plan lineage is stale", "blocked")
            if plan.get("request_ref") != evidence.get("request_ref"):
                raise FactoryError("replan evidence plan/request pairing is stale", "blocked")
            if not isinstance(config, dict) or not isinstance(config.get("requested_files"), list):
                raise FactoryError("replan evidence has no current request scope", "blocked")
            plan = validate_master_plan(plan, None)
            task_id = evidence["task_id"]
            task = next((item for item in master_plan_tasks(plan) if item["id"] == task_id), None)
            if task is None:
                raise FactoryError("replan evidence task identity is stale", "blocked")
            if (
                not isinstance(candidate, dict)
                or not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get("sha256")))
                or not re.fullmatch(r"[0-9a-f]{40}", str(candidate.get("base_commit")))
                or not re.fullmatch(r"[0-9a-f]{40}", str(candidate.get("candidate_id")))
                or candidate.get("base_commit") != evidence.get("base_commit")
                or candidate.get("candidate_id") != evidence.get("candidate_id")
            ):
                raise FactoryError("replan evidence candidate lineage is invalid", "blocked")
            review = value
            required_review_keys = {
                "decision",
                "reviewed_diff_sha256",
                "base_commit",
                "candidate_id",
                "criteria",
                "findings",
                "required_changes",
                "route",
                "verification",
                "replan_reason",
            }
            optional_review_keys = {
                "review_mode",
                "predecessor_review_ref",
                "target_finding_ids",
                "finding_records",
            }
            if (
                not isinstance(review, dict)
                or not required_review_keys.issubset(set(review))
                or set(review) - required_review_keys - optional_review_keys
            ):
                raise FactoryError("replan evidence Sol review schema is invalid", "blocked")
            review_reason = validate_replan_reason(review["replan_reason"])
            trigger_evidence = review_reason["evidence"]
            common_identity = (
                "artifact_ref",
                "kind",
                "verified",
                "producer",
                "run_id",
                "master_plan_ref",
                "request_ref",
                "request_sha256",
                "task_id",
                "base_commit",
                "candidate_id",
                "candidate_ref",
                "verification_ref",
                "verification",
                "verification_attestation_sha256",
                "sequence",
            )
            if any(
                trigger_evidence.get(field) != evidence.get(field)
                for field in common_identity
            ):
                raise FactoryError("replan evidence Sol reason identity is inconsistent", "blocked")
            if code == "ASSUMPTION_DISPROVED":
                assumption_ids = {
                    item["id"] for item in plan.get("assumptions", []) if isinstance(item, dict)
                }
                trigger_valid = (
                    isinstance(trigger_evidence.get("assumption_id"), str)
                    and trigger_evidence["assumption_id"] in assumption_ids
                )
            elif code == "REQUIRED_GAP_UNCOVERED":
                criterion_ids = {
                    item["id"]
                    for item in plan.get("global_criteria", [])
                    if isinstance(item, dict)
                }
                criterion_ids.update(item["id"] for item in task.get("acceptance_criteria", []))
                trigger_valid = (
                    isinstance(trigger_evidence.get("criterion_id"), str)
                    and trigger_evidence["criterion_id"] in criterion_ids
                )
            else:
                valid_edges = {
                    f"{dependency}->{item['id']}"
                    for item in master_plan_tasks(plan)
                    for dependency in item.get("depends_on", [])
                }
                trigger_valid = trigger_evidence.get("dependency") in valid_edges
            verification_ref = evidence["verification_ref"]
            if not isinstance(verification_ref, str) or not re.fullmatch(
                r"attestations/[0-9a-f]{64}\.json", verification_ref
            ):
                raise FactoryError("replan evidence has no bounded verification lineage", "blocked")
            verification_contract = self._validate_verification_attestation(
                run_dir,
                verification_ref,
                attestation_sha256=evidence.get("verification_attestation_sha256"),
                expected_task_id=task_id,
                expected_base_commit=candidate["base_commit"],
                expected_candidate_id=candidate["candidate_id"],
            )
            if (
                review_reason["code"] != code
                or review_reason["evidence"].get("kind") != kind
                or review_reason["evidence"].get("verified") is not True
                or not trigger_valid
                or review.get("base_commit") != candidate["base_commit"]
                or review.get("candidate_id") != candidate["candidate_id"]
                or review.get("reviewed_diff_sha256") != candidate["sha256"]
                or evidence["run_id"] != state.get("run_id")
                or evidence["master_plan_ref"] != plan_ref
                or (not historical and evidence["request_ref"] != state.get("request_ref"))
                or evidence["task_id"] != task_id
                or evidence["base_commit"] != candidate["base_commit"]
                or evidence["candidate_id"] != candidate["candidate_id"]
                or evidence["candidate_ref"] != candidate_ref
                or evidence["review_ref"] != artifact_ref
                or evidence["sequence"] != int(re.fullmatch(r"sol_review_([0-9]+)\.json", artifact_ref).group(1))
                or not isinstance(review.get("verification"), dict)
                or review["verification"].get("attestation_ref") != verification_ref
                or evidence["verification"] != review.get("verification")
                or review.get("verification") != verification_contract
            ):
                raise FactoryError("replan evidence Sol review is not bound to the current candidate", "blocked")
            validate_review(
                review,
                candidate["sha256"],
                candidate["base_commit"],
                candidate["candidate_id"],
                self._task_review_criteria_ids(self._task_execution_plan(plan, task)),
                verification_contract,
                predecessor_review=self._load_review_predecessor(run_dir, review),
            )
        elif code in {"ARCHITECTURE_DEPENDENCY_CONFLICT", "PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE"} and re.fullmatch(
            r"replan_evidence_[0-9]+\.json", artifact_ref
        ):
            expected_plan_ref = state.get("master_plan_ref")
            plan_path = (run_dir / expected_plan_ref).resolve() if isinstance(expected_plan_ref, str) else None
            if plan_path is None or not plan_path.is_file():
                raise FactoryError("replan evidence has no current master plan", "blocked")
            plan = read_json(plan_path)
            expected_completed = sorted(
                item.get("task_id")
                for item in state.get("completed_commits", [])
                if isinstance(item, dict) and isinstance(item.get("task_id"), str)
            )
            expected_gaps = self._remaining_master_plan_gaps(plan, state)
            expected_pending = sorted(
                task["id"]
                for task in master_plan_tasks(plan)
                if task["id"] not in set(expected_completed)
            )
            expected_sequence = int(re.fullmatch(r"replan_evidence_([0-9]+)\.json", artifact_ref).group(1))
            required_keys = {
                "artifact_type",
                "replan_code",
                "kind",
                "verified",
                "producer",
                "run_id",
                "master_plan_ref",
                "request_ref",
                "request_sha256",
                "base_commit",
                "task_id",
                "candidate_id",
                "sequence",
                "remaining_gaps",
                "completed_task_ids",
                "blocked_task_ids",
            }
            if code == "ARCHITECTURE_DEPENDENCY_CONFLICT":
                required_keys.add("dependency")
            historical_plan_ref = value.get("master_plan_ref") if isinstance(value, dict) else None
            historical_plan_path = (
                (run_dir / historical_plan_ref).resolve()
                if isinstance(historical_plan_ref, str)
                else None
            )
            historical_plan = read_json(historical_plan_path) if historical_plan_path and historical_plan_path.is_file() else None
            historical_request_ref = value.get("request_ref") if isinstance(value, dict) else None
            historical_request_path = (
                (run_dir / historical_request_ref).resolve()
                if isinstance(historical_request_ref, str)
                else None
            )
            historical_request_ok = (
                historical_request_path is not None
                and historical_request_path.is_file()
                and isinstance(value.get("request_sha256"), str)
                and hashlib.sha256(historical_request_path.read_bytes()).hexdigest() == value["request_sha256"]
            )
            historical_valid = (
                historical
                and isinstance(value, dict)
                and set(value) == required_keys
                and value.get("artifact_type") == "hermes_replan_evidence_v1"
                and value.get("replan_code") == code
                and value.get("kind") == kind
                and value.get("verified") is True
                and value.get("producer") == "Hermes"
                and value.get("sequence") == expected_sequence
                and isinstance(historical_plan_ref, str)
                and re.fullmatch(r"plans/[0-9a-f]{64}\.json", historical_plan_ref.replace("\\", "/"))
                and historical_plan_path is not None
                and historical_plan_path.is_file()
                and isinstance(historical_plan, dict)
                and hashlib.sha256(
                    json.dumps(historical_plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest() == historical_plan_ref.split("/")[-1][:-5]
                and historical_plan.get("request_ref") == historical_request_ref
                and historical_request_ok
                and isinstance(value.get("run_id"), str)
                and value.get("run_id") == state.get("run_id")
                and isinstance(value.get("base_commit"), str)
                and re.fullmatch(r"[0-9a-f]{40}", value["base_commit"])
                and (value.get("task_id") is None or isinstance(value.get("task_id"), str))
                and (value.get("candidate_id") is None or re.fullmatch(r"[0-9a-f]{40}", str(value.get("candidate_id"))))
                and isinstance(value.get("completed_task_ids"), list)
                and len(value["completed_task_ids"]) == len(set(value["completed_task_ids"]))
                and isinstance(value.get("blocked_task_ids"), list)
                and len(value["blocked_task_ids"]) == len(set(value["blocked_task_ids"]))
                and all(item in {task["id"] for task in master_plan_tasks(historical_plan)} for item in value["completed_task_ids"])
                and all(item in {task["id"] for task in master_plan_tasks(historical_plan)} for item in value["blocked_task_ids"])
                and set(value["completed_task_ids"]) | set(value["blocked_task_ids"]) == {task["id"] for task in master_plan_tasks(historical_plan)}
                and isinstance(value.get("remaining_gaps"), list)
                and set(value["remaining_gaps"]).issubset({item["id"] for item in historical_plan.get("global_criteria", [])})
            )
            if historical_valid:
                if code == "PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE":
                    historical_valid = (
                        not value["blocked_task_ids"]
                        and set(value["completed_task_ids"]) == {task["id"] for task in master_plan_tasks(historical_plan)}
                        and bool(value["remaining_gaps"])
                    )
                else:
                    historical_valid = bool(value["blocked_task_ids"])
                if value.get("task_id") is not None:
                    historical_valid = historical_valid and value["task_id"] in {
                        task["id"] for task in master_plan_tasks(historical_plan)
                    }
                if code == "ARCHITECTURE_DEPENDENCY_CONFLICT":
                    historical_valid = historical_valid and value.get("dependency") in {
                        f"{dependency}->{item['id']}"
                        for item in master_plan_tasks(historical_plan)
                        for dependency in item.get("depends_on", [])
                    }
            if historical and not historical_valid:
                raise FactoryError("historical Hermes replan evidence is invalid", "blocked")
            repo_value = state.get("config", {}).get("repo") if isinstance(state.get("config"), dict) else None
            known_base_commits = {
                state.get("source_head_before"),
                *{
                    item.get("commit")
                    for item in state.get("completed_commits", [])
                    if isinstance(item, dict)
                },
            }
            base_identity = value.get("base_commit") if isinstance(value, dict) else None
            candidate_identity = value.get("candidate_id") if isinstance(value, dict) else None
            completed_identity = value.get("completed_task_ids") if isinstance(value, dict) else None
            task_identity = value.get("task_id") if isinstance(value, dict) else None
            completed_records = [
                item for item in state.get("completed_commits", []) if isinstance(item, dict)
            ]
            base_record_index = next(
                (index for index, item in enumerate(completed_records) if item.get("commit") == base_identity),
                None,
            )
            expected_completed_prefix = (
                sorted(item.get("task_id") for item in completed_records[: base_record_index + 1])
                if base_record_index is not None
                else []
            )
            if (
                not isinstance(repo_value, str)
                or base_identity not in known_base_commits
                or git(Path(repo_value), "cat-file", "-e", f"{base_identity}^{{commit}}").returncode != 0
                or candidate_identity is not None
                or completed_identity != expected_completed_prefix
                or (
                    expected_completed_prefix
                    and task_identity != expected_completed_prefix[-1]
                )
            ):
                raise FactoryError("Hermes replan base/candidate identity is not host-bound", "blocked")
            valid = (
                isinstance(value, dict)
                and set(value) == required_keys
                and value.get("artifact_type") == "hermes_replan_evidence_v1"
                and value.get("replan_code") == code
                and value.get("kind") == kind
                and value.get("verified") is True
                and value.get("producer") == "Hermes"
                and value.get("run_id") == state.get("run_id")
                and value.get("master_plan_ref") == expected_plan_ref
                and value.get("request_ref") == state.get("request_ref")
                and value.get("request_sha256") == state.get("request_sha256")
                and value.get("base_commit") == state.get("base_commit")
                and value.get("task_id") == state.get("current_task_id")
                and value.get("candidate_id") == state.get("candidate_id")
                and value.get("sequence") == expected_sequence
                and value.get("completed_task_ids") == expected_completed
                and value.get("remaining_gaps") == expected_gaps
                and value.get("blocked_task_ids") == expected_pending
            )
            if code == "ARCHITECTURE_DEPENDENCY_CONFLICT":
                valid = valid and value.get("dependency") in {
                    f"{dependency}->{item['id']}"
                    for item in master_plan_tasks(plan)
                    for dependency in item.get("depends_on", [])
                }
            if code == "PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE":
                valid = valid and bool(expected_gaps) and not expected_pending
            else:
                valid = valid and bool(expected_pending)
            if not historical and not valid:
                raise FactoryError("replan evidence is not the current Hermes planning artifact", "blocked")
        else:
            raise FactoryError("replan evidence is not code-appropriate verified evidence", "blocked")

        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        recorded = evidence.get("artifact_sha256")
        if recorded is not None and recorded != digest:
            raise FactoryError("replan evidence artifact changed after reservation", "blocked")
        return digest

    def _validate_replan_history(self, run_dir: Path, state: dict[str, Any]) -> None:
        history = state.get("replan_history")
        if not isinstance(history, list):
            if state.get("replan_reason_ref") is not None:
                raise FactoryError("replan reason history is missing", "blocked")
            return
        if state.get("replan_reason_ref") != (history[-1].get("record_ref") if history else None):
            raise FactoryError("replan reason history has an invalid current reference", "blocked")
        for expected_sequence, entry in enumerate(history, start=1):
            if (
                not isinstance(entry, dict)
                or set(entry) != {"sequence", "record_ref", "record_sha256", "code"}
                or entry.get("sequence") != expected_sequence
                or not isinstance(entry.get("record_ref"), str)
                or not re.fullmatch(r"replan_history/[0-9a-f]{64}\.json", entry["record_ref"])
                or entry.get("record_sha256") != entry["record_ref"].split("/")[-1][:-5]
                or entry.get("code") not in REPLAN_REASON_CODES
            ):
                raise FactoryError("replan reason history entry is malformed", "blocked")
            record_path = (run_dir / entry["record_ref"]).resolve()
            try:
                record_path.relative_to(run_dir.resolve())
            except ValueError as exc:
                raise FactoryError("replan reason history record escapes the run", "blocked") from exc
            if not record_path.is_file() or hashlib.sha256(record_path.read_bytes()).hexdigest() != entry["record_sha256"]:
                raise FactoryError("replan reason history record integrity is stale", "blocked")
            record = read_json(record_path)
            if (
                not isinstance(record, dict)
                or set(record) != {"schema_version", "sequence", "code", "evidence"}
                or record.get("schema_version") != 1
                or record.get("sequence") != expected_sequence
                or record.get("code") != entry["code"]
            ):
                raise FactoryError("replan reason history record schema is invalid", "blocked")
            reason = validate_replan_reason({"code": record["code"], "evidence": record["evidence"]})
            self._validate_replan_evidence(run_dir, reason, state, historical=True)

    def _block_replan_exhaustion(
        self, run_dir: Path, state: dict[str, Any], *, attempts: int, reason: dict[str, Any] | None = None
    ) -> None:
        block_reason = "exceptional replan budget exhausted; run is blocked"
        evidence = {
            "reason": block_reason,
            "replan_attempts": attempts,
            "last_reason": reason,
            "last_reason_ref": state.get("replan_reason_ref"),
        }
        atomic_json(run_dir / "replan_blocked.json", evidence)
        self._save(
            run_dir,
            state,
            "blocked",
            block_reason=block_reason,
            error=block_reason,
            error_category="blocked",
            replan_block_evidence="replan_blocked.json",
        )
        raise FactoryError(block_reason, "blocked")

    def _persist_replan_reason(
        self, run_dir: Path, state: dict[str, Any], reason: dict[str, Any]
    ) -> str:
        reason = validate_replan_reason(reason)
        artifact_ref = reason["evidence"]["artifact_ref"]
        artifact_path = (run_dir / artifact_ref).resolve()
        try:
            artifact_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("replan evidence reference escapes the run directory", "blocked") from exc
        if not artifact_path.is_file():
            raise FactoryError("replan evidence artifact is missing", "blocked")
        if reason["code"] == "USER_OBJECTIVE_OR_SCOPE_CHANGE":
            reason["evidence"]["request_ref"] = artifact_ref
            reason["evidence"]["request_sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        reason["evidence"].setdefault("base_commit", state.get("base_commit"))
        reason["evidence"].setdefault("task_id", state.get("current_task_id"))
        evidence_hash = self._validate_replan_evidence(run_dir, reason, state)
        reason["evidence"]["artifact_sha256"] = evidence_hash
        attempt = self._durable_replan_attempt_count(run_dir, state) + 1
        if self._durable_replan_dispatch_count(run_dir) >= 2:
            self._block_replan_exhaustion(
                run_dir,
                state,
                attempts=self._durable_replan_dispatch_count(run_dir),
                reason=reason,
            )
        record = {
            "schema_version": 1,
            "sequence": attempt,
            "code": reason["code"],
            "evidence": reason["evidence"],
        }
        serialized = (
            json.dumps(record, indent=2, sort_keys=True).replace("\n", os.linesep) + os.linesep
        ).encode("utf-8")
        record_sha256 = hashlib.sha256(serialized).hexdigest()
        reason_ref = f"replan_history/{record_sha256}.json"
        reason_path = run_dir / reason_ref
        if reason_path.is_file() and reason_path.read_bytes() != serialized:
            raise FactoryError("replan history content collision", "blocked")
        if not reason_path.is_file():
            atomic_json(reason_path, record)
        history = state.get("replan_history")
        if not isinstance(history, list):
            history = []
        history = list(history)
        history.append(
            {
                "sequence": attempt,
                "record_ref": reason_ref,
                "record_sha256": record_sha256,
                "code": reason["code"],
            }
        )
        self._save(
            run_dir,
            state,
            "planning",
            replan_reason_ref=reason_ref,
            replan_history=history,
        )
        return reason_ref

    def request_replan(
        self,
        identifier: str,
        reason: dict[str, Any],
        *,
        objective: str | None = None,
        requested_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Accept only a verified structured strategic trigger for an Astra replan."""
        normalized_reason = validate_replan_reason(reason)
        run_dir = self._run_dir(identifier)
        with _run_state_lock(run_dir):
            run_dir, state, config = self._load(identifier)
            if state["phase"] in {"committed", "complete"}:
                return self._validate_terminal_state(identifier, run_dir, state, config)
            if state.get("candidate_id") is not None or state.get("pending_commit") is not None:
                raise FactoryError("cannot replan with an ambiguous candidate or pending commit", "blocked")
            self._load_master_plan_for_execution(run_dir, config, state)
            if normalized_reason["code"] == "USER_OBJECTIVE_OR_SCOPE_CHANGE":
                if not isinstance(objective, str) or not objective.strip() or requested_files is None:
                    raise FactoryError(
                        "user objective/scope replan requires replacement objective and authorized files",
                        "input",
                    )
                replacement_files = normalized_paths(requested_files)
                repo = self._repo(config.repo)
                ensure_paths_confined(repo, replacement_files)
                ensure_head_paths_not_symlinks(repo, replacement_files)
                config = replace(config, request=objective.strip(), requested_files=replacement_files)
                state["config"] = asdict(config)
                user_reason = {
                    "code": normalized_reason["code"],
                    "evidence": {
                        "artifact_ref": "user_change_request",
                        "kind": "user_change",
                        "verified": True,
                    },
                }
                request_value = {
                    "artifact_type": "user_request_change_v1",
                    "run_id": identifier,
                    "request": config.request,
                    "requested_files": replacement_files,
                    "reason": user_reason,
                }
                request_serialized = (
                    json.dumps(request_value, indent=2, sort_keys=True).replace("\n", os.linesep) + os.linesep
                ).encode("utf-8")
                change_ref = f"requests/{hashlib.sha256(request_serialized).hexdigest()}.json"
                normalized_reason["evidence"] = dict(normalized_reason["evidence"])
                normalized_reason["evidence"]["artifact_ref"] = change_ref
                atomic_json(run_dir / change_ref, request_value)
                state["request_ref"] = change_ref
                state["request_sha256"] = hashlib.sha256((run_dir / change_ref).read_bytes()).hexdigest()
                self._save(run_dir, state, state["phase"], request_change_ref=change_ref)
            elif objective is not None or requested_files is not None:
                raise FactoryError(
                    "replacement objective/scope is allowed only for USER_OBJECTIVE_OR_SCOPE_CHANGE",
                    "input",
                )
            reason_ref = self._persist_replan_reason(run_dir, state, normalized_reason)
            ledger = MemoryLedger(
                run_dir,
                identifier,
                config.repo,
                state.get("objective_class", "capability_growth"),
            )
            self._perform_planning(
                run_dir,
                state,
                config,
                self._repo(config.repo),
                ledger=ledger,
                replan_reason=json.dumps(normalized_reason, sort_keys=True),
                planning_repo=(
                    Path(state["worktree"])
                    if isinstance(state.get("worktree"), str)
                    and Path(state["worktree"]).is_dir()
                    else None
                ),
            )
            state["replan_reason_ref"] = reason_ref
            atomic_json(run_dir / "run_state.json", state)
            return self._execute_locked(identifier)

    def _reconcile_pending_commit(
        self,
        identifier: str,
        run_dir: Path,
        state: dict[str, Any],
        config: Config,
        master_plan: dict[str, Any],
    ) -> dict[str, Any]:
        pending = state.get("pending_commit")
        if not isinstance(pending, dict) or not isinstance(pending.get("candidate_id"), str):
            raise FactoryError("committing state has no valid pending candidate", "blocked")
        expected_candidate = pending["candidate_id"]
        task_id = state.get("current_task_id")
        if not isinstance(task_id, str):
            raise FactoryError("committing state has no current task", "blocked")
        task = next((item for item in master_plan_tasks(master_plan) if item["id"] == task_id), None)
        if task is None:
            raise FactoryError("pending commit task is not present in the master plan", "blocked")
        worktree_raw = state.get("worktree")
        if not isinstance(worktree_raw, str) or not Path(worktree_raw).is_dir():
            raise FactoryError("pending commit worktree is missing", "blocked")
        worktree = Path(worktree_raw)
        base_commit = state.get("base_commit")
        if not isinstance(base_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", base_commit):
            raise FactoryError("pending commit has an invalid base commit", "blocked")
        review_ref = state.get("review_ref")
        if not isinstance(review_ref, str) or not review_ref:
            raise FactoryError("pending commit has no review reference", "blocked")
        review_path = (run_dir / review_ref).resolve()
        try:
            review_path.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise FactoryError("pending review reference escapes the run directory", "blocked") from exc
        if not review_path.is_file():
            raise FactoryError("pending review artifact is missing", "blocked")
        review = read_json(review_path)
        if state.get("candidate_id") != expected_candidate:
            raise FactoryError("pending commit candidate is not bound to run state", "blocked")
        pending_base = pending.get("base_commit")
        if pending_base != base_commit:
            raise FactoryError("pending commit base does not match the approved base", "blocked")
        pending_review_hash = pending.get("reviewed_diff_sha256")
        if pending_review_hash != review.get("reviewed_diff_sha256"):
            raise FactoryError("pending commit review hash is not bound to the approval", "blocked")
        if pending.get("review_ref") != review_ref:
            raise FactoryError("pending commit review reference is not bound to the approval", "blocked")
        pending_candidate_state = pending.get("candidate_state_identity")
        state_candidate_state = state.get("candidate_state_identity")
        if (
            not isinstance(pending_candidate_state, dict)
            or not isinstance(state_candidate_state, dict)
            or pending_candidate_state.get("complete_identity_sha256")
            != state_candidate_state.get("complete_identity_sha256")
        ):
            raise FactoryError("pending commit candidate state is not bound to the approval", "blocked")
        if pending.get("verification_ref") != state.get("verification_ref"):
            raise FactoryError("pending commit verification reference is not bound to the approval", "blocked")
        verification_ref = state.get("verification_ref")
        if not isinstance(verification_ref, str):
            raise FactoryError("pending commit has no verification provenance", "blocked")
        verification_contract = self._validate_verification_attestation(
            run_dir,
            verification_ref,
            attestation_sha256=state.get("verification_attestation_sha256"),
            expected_task_id=task_id,
            expected_base_commit=base_commit,
            expected_candidate_id=expected_candidate,
            expected_command=normalize_test_command(config.test_command) if config.test_command else None,
        )
        verification_sha256 = verification_contract["attestation_sha256"]
        if pending.get("verification_sha256") != verification_sha256:
            raise FactoryError("pending commit verification digest is not bound to the approval", "blocked")
        review_sha256 = hashlib.sha256(review_path.read_bytes()).hexdigest()
        if pending.get("review_sha256") != review_sha256:
            raise FactoryError("pending commit review artifact integrity is stale", "blocked")
        if review.get("verification") != verification_contract:
            raise FactoryError("pending commit verification is not bound to the approval", "blocked")

        head = git(worktree, "rev-parse", "HEAD").stdout.strip()
        if head != base_commit:
            parent = git(worktree, "rev-parse", "HEAD^").stdout.strip()
            tree = git(worktree, "rev-parse", "HEAD^{tree}").stdout.strip()
            if parent != base_commit or tree != expected_candidate:
                raise FactoryError("pending commit does not match the approved base/tree", "blocked")
            post_commit_state = AgyBuilder._candidate_baseline_identity(worktree)
            if (
                post_commit_state.get("head") != head
                or post_commit_state.get("tree") != expected_candidate
                or post_commit_state.get("status_records")
                or post_commit_state.get("staged_diff_sha256")
                != hashlib.sha256(b"").hexdigest()
                or post_commit_state.get("unstaged_diff_sha256")
                != hashlib.sha256(b"").hexdigest()
                or not post_commit_state["clean"]
            ):
                raise FactoryError(
                    "pending commit has post-approval candidate mutations",
                    "blocked",
                )
            committed_diff = git(
                worktree, "diff", f"{base_commit}..{head}", "--binary", "--no-ext-diff"
            ).stdout
            validate_review(
                review,
                hashlib.sha256(committed_diff.encode("utf-8")).hexdigest(),
                base_commit,
                expected_candidate,
                list(task.get("global_criteria", []))
                + [item["id"] for item in task.get("acceptance_criteria", [])],
                verification_contract,
                predecessor_review=self._load_review_predecessor(run_dir, review),
            )
            if review.get("decision") != "APPROVE":
                raise FactoryError("pending commit reconciliation requires Sol APPROVE", "blocked")
            commit_hash = head
        else:
            staged_diff = git(worktree, "diff", "--cached", "--binary", "--no-ext-diff").stdout
            current_hash = hashlib.sha256(staged_diff.encode("utf-8")).hexdigest()
            current_tree = git(worktree, "write-tree").stdout.strip()
            unstaged_diff = git(worktree, "diff", "--binary", "--no-ext-diff").stdout
            current_candidate_state = AgyBuilder._candidate_baseline_identity(worktree)
            reviewed_candidate_state = state.get("candidate_state_identity")
            validate_review(
                review,
                current_hash,
                base_commit,
                expected_candidate,
                list(task.get("global_criteria", []))
                + [item["id"] for item in task.get("acceptance_criteria", [])],
                verification_contract,
                predecessor_review=self._load_review_predecessor(run_dir, review),
            )
            if review.get("decision") != "APPROVE":
                raise FactoryError("pending commit reconciliation requires Sol APPROVE", "blocked")
            if current_tree != expected_candidate or unstaged_diff:
                raise FactoryError("pending candidate changed before commit reconciliation", "blocked")
            if (
                not isinstance(reviewed_candidate_state, dict)
                or current_candidate_state.get("complete_identity_sha256")
                != reviewed_candidate_state.get("complete_identity_sha256")
            ):
                raise FactoryError("pending candidate state changed before commit reconciliation", "blocked")
            message = (
                f"hermes: {task['objective'].strip()[:68]}\n\n"
                f"Factory-Run: {identifier}\n"
                f"Sol-Model: {config.sol_model}\n"
                f"Builder-Model: {config.builder_model}\n"
                f"Reviewed-Diff-SHA256: {current_hash}\n"
                f"Candidate-Tree: {expected_candidate}"
            )
            commit_hash = _commit_exact_candidate_tree(
                worktree,
                candidate_id=expected_candidate,
                base_commit=base_commit,
                message=message,
            )
            if git(worktree, "rev-parse", "HEAD^{tree}").stdout.strip() != expected_candidate:
                raise FactoryError("reconciled commit tree does not match the pending candidate", "blocked")

        completed_commits = state.get("completed_commits")
        if not isinstance(completed_commits, list):
            raise FactoryError("run completed_commits state is invalid", "state")
        completed_commits = list(completed_commits)
        existing = next(
            (item for item in completed_commits if isinstance(item, dict) and item.get("task_id") == task_id),
            None,
        )
        completed_record = {
            "task_id": task_id,
            "commit": commit_hash,
            "candidate_id": expected_candidate,
            "base_commit": base_commit,
        }
        if existing is None:
            completed_commits.append(completed_record)
        elif existing.get("commit") != commit_hash or existing.get("candidate_id") != expected_candidate:
            raise FactoryError("completed task history conflicts with pending commit", "blocked")
        state["completed_commits"] = completed_commits
        state["base_commit"] = commit_hash
        state["candidate_id"] = None
        state["pending_commit"] = None
        state["active_attempt_ref"] = None
        task_evidence = next(
            (
                item
                for item in (state.get("criterion_evidence") or {}).values()
                if isinstance(item, dict) and item.get("task_id") == task_id
            ),
            None,
        )
        if (
            not isinstance(task_evidence, dict)
            or not isinstance(task_evidence.get("review_sha256"), str)
            or not isinstance(task_evidence.get("verification_sha256"), str)
            or not isinstance(task_evidence.get("verification_sequence"), int)
        ):
            raise FactoryError("pending commit lacks bound verification provenance", "blocked")
        self._record_approved_criteria(
            state,
            task,
            review,
            base_commit=base_commit,
            candidate_id=expected_candidate,
            review_ref=str(state.get("review_ref")),
            verification_ref=state.get("verification_ref"),
            review_sha256=task_evidence["review_sha256"],
            verification_sha256=task_evidence["verification_sha256"],
            verification_sequence=task_evidence["verification_sequence"],
            review_criteria_ids=task_evidence.get("review_criteria_ids"),
        )
        self._record_committed_task_criteria(state, master_plan, task)
        self._bind_criteria_to_commit(state, task_id, commit_hash)
        self._save(
            run_dir,
            state,
            "planned",
            commit=commit_hash,
            current_task_id=task_id,
            completed_commits=completed_commits,
            criterion_evidence=state["criterion_evidence"],
            pending_commit=None,
            candidate_id=None,
            candidate_state_identity=None,
            active_attempt_ref=None,
        )
        return state

    def _validate_terminal_state(
        self,
        identifier: str,
        run_dir: Path,
        state: dict[str, Any],
        config: Config,
    ) -> dict[str, Any]:
        """Revalidate a terminal snapshot before trusting its fast path."""
        def invalid(reason: str) -> None:
            self._save(
                run_dir,
                state,
                "blocked",
                block_reason=reason,
                error=reason,
                error_category="blocked",
            )
            raise FactoryError(reason, "blocked")

        try:
            plan = self._load_master_plan_for_execution(run_dir, config, state)
            tasks = master_plan_tasks(plan)
            completed = state.get("completed_commits")
            if not isinstance(completed, list) or not completed:
                invalid("terminal state has no completed commit history")
            task_ids: set[str] = set()
            plan_ids = {task["id"] for task in tasks}
            for record in completed:
                if not isinstance(record, dict):
                    invalid("terminal state has an invalid completed commit record")
                task_id = record.get("task_id")
                commit = record.get("commit")
                candidate_id = record.get("candidate_id")
                base_commit = record.get("base_commit")
                if (
                    not isinstance(task_id, str)
                    or task_id in task_ids
                    or not isinstance(commit, str)
                    or not re.fullmatch(r"[0-9a-f]{40}", commit)
                    or not isinstance(candidate_id, str)
                    or not re.fullmatch(r"[0-9a-f]{40}", candidate_id)
                    or not isinstance(base_commit, str)
                    or not re.fullmatch(r"[0-9a-f]{40}", base_commit)
                ):
                    invalid("terminal state has an invalid or duplicate completed commit record")
                if task_id not in plan_ids:
                    invalid("terminal state references a task absent from the master plan")
                task_ids.add(task_id)
                if git(Path(config.repo), "rev-parse", f"{commit}^").stdout.strip() != base_commit:
                    invalid("terminal state commit parent does not match its recorded base")
                if git(Path(config.repo), "rev-parse", f"{commit}^{{tree}}").stdout.strip() != candidate_id:
                    invalid("terminal state commit tree does not match its recorded candidate")
            if task_ids != plan_ids:
                invalid("terminal state is missing a committed master-plan task")
            if state.get("commit") != completed[-1].get("commit"):
                invalid("terminal state latest commit is not bound to completed history")
            if state.get("current_task_id") is not None:
                invalid("terminal state retains a current task")
            if any(state.get(key) is not None for key in ("candidate_id", "pending_commit", "active_attempt_ref")):
                invalid("terminal state retains an ambiguous candidate or attempt")
            if state.get("test_results") not in (None, []):
                invalid("terminal state retains duplicate mutable Runner result state")
            gaps = self._remaining_master_plan_gaps(plan, state)
            if gaps:
                invalid(f"terminal state has incomplete global criterion evidence: {gaps}")
            evidence = state.get("criterion_evidence")
            if not isinstance(evidence, dict):
                invalid("terminal state criterion evidence is missing")
            completed_by_commit = {
                item["commit"]: item
                for item in completed
                if isinstance(item, dict) and isinstance(item.get("commit"), str)
            }
            task_by_id = {task["id"]: task for task in tasks}
            validated_reviews: set[str] = set()
            for criterion_id, item in evidence.items():
                if not isinstance(item, dict) or item.get("status") != "PASS":
                    continue
                commit_record = completed_by_commit.get(item.get("commit"))
                if commit_record is None or item.get("candidate_id") != commit_record.get("candidate_id"):
                    invalid(f"terminal state criterion {criterion_id} has stale commit lineage")
                task = task_by_id.get(item.get("task_id"))
                if task is None:
                    invalid(f"terminal state criterion {criterion_id} has an unknown task")
                review_ref = item.get("review_ref")
                verification_ref = item.get("verification_ref")
                if not isinstance(review_ref, str) or not review_ref:
                    invalid(f"terminal state criterion {criterion_id} has no review_ref")
                if not isinstance(verification_ref, str) or not verification_ref:
                    invalid(f"terminal state criterion {criterion_id} has no verification_ref")
                verification_contract = self._validate_verification_attestation(
                    run_dir,
                    verification_ref,
                    attestation_sha256=item.get("verification_sha256"),
                    expected_task_id=item.get("task_id"),
                    expected_base_commit=item.get("base_commit"),
                    expected_candidate_id=item.get("candidate_id"),
                    expected_command=normalize_test_command(config.test_command) if config.test_command else None,
                )
                if verification_contract.get("sequence") != item.get("verification_sequence"):
                    invalid(f"terminal state criterion {criterion_id} verification sequence is stale")
                review_path = (run_dir / review_ref).resolve()
                if not review_path.is_file():
                    invalid(f"terminal state criterion {criterion_id} references missing review_ref")
                review_value = read_json(review_path)
                review_hash = item.get("review_sha256")
                if (
                    not isinstance(review_hash, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", review_hash)
                    or hashlib.sha256(review_path.read_bytes()).hexdigest() != review_hash
                ):
                    invalid(f"terminal state criterion {criterion_id} review_ref integrity is stale")
                if review_value.get("decision") != "APPROVE":
                    invalid(f"terminal state criterion {criterion_id} references a non-approval review")
                if review_value.get("verification") != verification_contract:
                    invalid(f"terminal state criterion {criterion_id} review verification is stale")
                if review_ref not in validated_reviews:
                    commit = commit_record["commit"]
                    committed_diff = git(
                        Path(config.repo),
                        "diff",
                        f"{item['base_commit']}..{commit}",
                        "--binary",
                        "--no-ext-diff",
                    ).stdout
                    validate_review(
                        review_value,
                        hashlib.sha256(committed_diff.encode("utf-8")).hexdigest(),
                        item["base_commit"],
                        item["candidate_id"],
                        item.get("review_criteria_ids")
                        if isinstance(item.get("review_criteria_ids"), list)
                        else self._task_review_criteria_ids(self._task_execution_plan(plan, task)),
                        verification_contract,
                        predecessor_review=self._load_review_predecessor(run_dir, review_value),
                    )
                    validated_reviews.add(review_ref)
            ledger = MemoryLedger(
                run_dir,
                identifier,
                config.repo,
                state.get("objective_class", "capability_growth"),
            )
            if any(item.get("status") in {"open", "regressed"} for item in ledger.issues.values()):
                invalid("terminal state has unresolved ledger findings")
        except FactoryError as exc:
            if state.get("phase") != "blocked":
                invalid(f"terminal state validation failed: {exc}")
            raise
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            invalid(f"terminal state evidence is invalid: {exc}")
        return state

    def _commit_approved_candidate(
        self,
        *,
        identifier: str,
        run_dir: Path,
        state: dict[str, Any],
        config: Config,
        plan: dict[str, Any],
        task_id: str,
        worktree: Path,
        diff_text: str,
        digest: str,
        changed: list[str],
        candidate_id: str,
        review: dict[str, Any],
        tests: list[dict[str, Any]],
        checkpoints: list[str],
        ledger: MemoryLedger,
        review_sequence: int,
        finalize_run: bool,
    ) -> dict[str, Any]:
        self._assert_source_unchanged(
            Path(config.repo), state, run_dir, f"commit_gate_{self._artifact_sequence(review_sequence)}"
        )
        self._scope_check(
            worktree,
            allowed := plan["allowed_files"],
            f"commit_gate_{self._artifact_sequence(review_sequence)}",
            run_dir,
        )
        current_diff = git(worktree, "diff", "--cached", "--binary", "--no-ext-diff").stdout
        current_hash = hashlib.sha256(current_diff.encode("utf-8")).hexdigest()
        current_base_commit = git(worktree, "rev-parse", "HEAD").stdout.strip()
        current_candidate_id = git(worktree, "write-tree").stdout.strip()
        current_candidate_state = AgyBuilder._candidate_baseline_identity(worktree)
        reviewed_candidate_state = state.get("candidate_state_identity")
        unstaged_diff = git(worktree, "diff", "--binary", "--no-ext-diff").stdout
        # Diff hashes corroborate what Sol was shown. Candidate authority is
        # the host's current base plus git write-tree result below; the digest
        # never supplies or replaces the candidate identity.
        if (
            current_hash != digest
            or review.get("decision") != "APPROVE"
            or review["reviewed_diff_sha256"] != current_hash
            or review["base_commit"] != current_base_commit
            or state.get("base_commit") != current_base_commit
            or review["candidate_id"] != current_candidate_id
            or current_candidate_id != candidate_id
            or unstaged_diff
            or not isinstance(reviewed_candidate_state, dict)
            or current_candidate_state.get("complete_identity_sha256")
            != reviewed_candidate_state.get("complete_identity_sha256")
        ):
            raise FactoryError("candidate changed after Sol approval; approval invalidated", "hash")
        review_ref = str(state.get("review_ref") or f"sol_review_{self._artifact_sequence(review_sequence)}.json")
        verification_ref = state.get("verification_ref")
        if not isinstance(verification_ref, str):
            raise FactoryError("approved candidate has no verification artifact", "state")
        verification_contract = self._validate_verification_attestation(
            run_dir,
            verification_ref,
            attestation_sha256=state.get("verification_attestation_sha256"),
            expected_task_id=task_id,
            expected_base_commit=current_base_commit,
            expected_candidate_id=current_candidate_id,
            expected_command=normalize_test_command(config.test_command) if config.test_command else None,
        )
        verification_sha256 = verification_contract["attestation_sha256"]
        if review.get("verification") != verification_contract:
            raise FactoryError("Sol reviewed verification does not match the Runner evidence", "hash")
        review_path = (run_dir / review_ref).resolve()
        if not review_path.is_file():
            raise FactoryError("approved review artifact is missing", "state")
        review_sha256 = hashlib.sha256(review_path.read_bytes()).hexdigest()
        self._record_approved_criteria(
            state,
            plan,
            review,
            base_commit=current_base_commit,
            candidate_id=current_candidate_id,
            review_ref=review_ref,
            verification_ref=verification_ref,
            review_sha256=review_sha256,
            verification_sha256=verification_sha256,
            verification_sequence=verification_contract["sequence"],
        )
        message = (
            f"hermes: {plan['objective'].strip()[:68]}\n\n"
            f"Factory-Run: {identifier}\n"
            f"Sol-Model: {config.sol_model}\n"
            f"Builder-Model: {config.builder_model}\n"
            f"Reviewed-Diff-SHA256: {current_hash}\n"
            f"Candidate-Tree: {current_candidate_id}"
        )
        self._save(
            run_dir,
            state,
            "committing",
            candidate_id=current_candidate_id,
            candidate_state_identity=reviewed_candidate_state,
            reviewed_diff_sha256=current_hash,
            review_ref=review_ref,
            verification_ref=verification_ref,
            pending_commit={
                "base_commit": current_base_commit,
                "candidate_id": current_candidate_id,
                "reviewed_diff_sha256": current_hash,
                "review_ref": review_ref,
                "verification_ref": verification_ref,
                "review_sha256": review_sha256,
                "verification_sha256": verification_sha256,
                "candidate_state_identity": reviewed_candidate_state,
            },
        )
        commit_hash = _commit_exact_candidate_tree(
            worktree,
            candidate_id=current_candidate_id,
            base_commit=current_base_commit,
            message=message,
        )
        committed_parent = git(worktree, "rev-parse", "HEAD^").stdout.strip()
        committed_tree = git(worktree, "rev-parse", "HEAD^{tree}").stdout.strip()
        if committed_parent != current_base_commit or committed_tree != current_candidate_id:
            raise FactoryError("committed parent or tree does not match the approved candidate", "blocked")
        ledger.resolve_issues_by_source(
            "Sol Reviewer",
            resolution_evidence={"reviewed_diff_sha256": current_hash, "decision": "APPROVE"},
        )
        ledger.record_event(
            phase="review",
            action=f"sol_review_{self._artifact_sequence(review_sequence)}",
            result="approved",
            details={"decision": "APPROVE", "reviewed_diff_sha256": current_hash},
            artifacts=[review_ref],
        )
        ledger.record_event(
            phase="commit",
            action="git_commit",
            result="success",
            details={
                "commit": commit_hash,
                "reviewed_diff_sha256": current_hash,
                "candidate_id": current_candidate_id,
            },
        )
        completed_commits = state.get("completed_commits")
        if not isinstance(completed_commits, list):
            raise FactoryError("run completed_commits state is invalid", "state")
        completed_commits = list(completed_commits)
        completed_commits.append(
            {
                "task_id": task_id,
                "commit": commit_hash,
                "candidate_id": current_candidate_id,
                "base_commit": current_base_commit,
            }
        )
        self._bind_criteria_to_commit(state, task_id, commit_hash)
        next_state = self._save(
            run_dir,
            state,
            "planned" if not finalize_run else "committed",
            commit=commit_hash,
            base_commit=commit_hash,
            current_task_id=task_id,
            candidate_id=None,
            candidate_state_identity=None,
            completed_commits=completed_commits,
            reviewed_diff_sha256=current_hash,
            changed_files=changed,
            test_results=tests,
            review_cycles=state.get("review_cycles", 0) + review_sequence,
            checkpoints=checkpoints,
            active_attempt_ref=None,
            pending_commit=None,
        )
        if finalize_run:
            removed = command(["git", "worktree", "remove", str(worktree)], cwd=Path(config.repo), timeout=120)
            if removed.returncode == 0:
                state["worktree_removed"] = True
                atomic_json(run_dir / "run_state.json", state)
        return state

    def _resume_existing_task_phase(
        self,
        identifier: str,
        run_dir: Path,
        state: dict[str, Any],
        config: Config,
        master_plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Continue a durable verification/review phase without replaying AGY."""
        task_id = state.get("current_task_id")
        if not isinstance(task_id, str):
            reason = "resumable phase has no current task"
            self._save(run_dir, state, "blocked", block_reason=reason, error_category="blocked")
            raise FactoryError(reason, "blocked")
        task = next((item for item in master_plan_tasks(master_plan) if item["id"] == task_id), None)
        if task is None:
            raise FactoryError("resumable phase task is absent from the master plan", "blocked")
        worktree_raw = state.get("worktree")
        if not isinstance(worktree_raw, str) or not Path(worktree_raw).is_dir():
            raise FactoryError("resumable phase worktree is missing", "blocked")
        worktree = Path(worktree_raw)
        base_commit = state.get("base_commit")
        expected_candidate = state.get("candidate_id")
        if not isinstance(base_commit, str):
            raise FactoryError("resumable phase lacks candidate identity", "blocked")
        if state["phase"] == "reviewing" and not isinstance(expected_candidate, str):
            raise FactoryError("resumable phase lacks candidate identity", "blocked")
        if git(worktree, "rev-parse", "HEAD").stdout.strip() != base_commit:
            raise FactoryError("resumable phase base commit changed", "blocked")
        completed_offset = len(state.get("completed_commits", [])) * 1000
        existing_artifact_numbers = [
            int(match.group(1))
            for path in run_dir.iterdir()
            if (match := re.search(r"_(\d+)(?:\.[^.]+)$", path.name))
        ]
        self._artifact_offset = max([completed_offset, *existing_artifact_numbers], default=0) + 500
        task_plan = self._task_execution_plan(master_plan, task)
        ledger = MemoryLedger(
            run_dir,
            identifier,
            config.repo,
            state.get("objective_class", "capability_growth"),
        )
        tests = state.get("test_results")
        if not isinstance(tests, list):
            tests = []
        tests = list(tests)

        def block_resume(reason: str) -> None:
            self._save(
                run_dir,
                state,
                "blocked",
                block_reason=reason,
                error_category="blocked",
                error=reason,
                test_results=tests,
            )
            raise FactoryError(reason, "blocked")

        def resume_repair(instruction: str, label: str) -> tuple[str, str, list[str], str]:
            previous_candidate: str | None = None
            previous_failure: dict[str, Any] | None = None
            repair_index = 0
            while True:
                attempts = state.get("current_task_attempts", 0)
                if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
                    block_resume("resumed task has an invalid attempt count")
                if attempts >= config.max_task_attempts:
                    block_resume("resumed task attempt budget exhausted")
                repair_index += 1
                actual_label = label if repair_index == 1 else f"{label}_{repair_index}"
                surface = self._select_builder_surface(
                    worktree=worktree,
                    run_dir=run_dir,
                    config=config,
                    plan=task_plan,
                    instruction=instruction,
                    recovery_stage=1,
                    attempt=attempts + 1,
                )
                baseline = (
                    AgyBuilder._candidate_baseline_identity(worktree)
                    if isinstance(self.builder, AgyBuilder)
                    else None
                )
                self._save(
                    run_dir,
                    state,
                    "building",
                    current_task_attempts=attempts + 1,
                    active_attempt_ref=actual_label,
                    candidate_baseline_identity=baseline,
                    builder_dispatch={
                        "state": "reserved",
                        "label": actual_label,
                        "strategy": surface.get("strategy", surface.get("kind", "normal")),
                        "surface_ref": surface.get("surface_ref"),
                        "target_symbols": surface.get("target_symbols", []),
                        "baseline_identity": baseline.get("complete_identity_sha256") if baseline else None,
                    },
                )
                self._run_builder_attempt(
                    worktree=worktree,
                    instruction=self._surface_instruction(instruction, surface),
                    allowed_files=task_plan["allowed_files"],
                    config=config,
                    run_dir=run_dir,
                    label=actual_label,
                    surface=surface,
                )
                self._assert_source_unchanged(Path(config.repo), state, run_dir, f"after_{actual_label}")
                self._scope_check(worktree, task_plan["allowed_files"], f"after_{actual_label}", run_dir)
                self._save(
                    run_dir,
                    state,
                    "verifying",
                    active_attempt_ref=None,
                    builder_dispatch={
                        "state": "completed",
                        "label": actual_label,
                        "strategy": surface.get("strategy", surface.get("kind", "normal")),
                        "surface_ref": surface.get("surface_ref"),
                        "target_symbols": surface.get("target_symbols", []),
                    },
                )
                next_sequence = max(
                    [item.get("sequence", 0) for item in tests if isinstance(item, dict)] + [0]
                ) + 1
                result = self._test(worktree, config, run_dir, next_sequence)
                tests.append(result)
                self._assert_source_unchanged(Path(config.repo), state, run_dir, f"after_test_{next_sequence}")
                changed = self._scope_check(
                    worktree,
                    task_plan["allowed_files"],
                    f"after_test_{next_sequence}",
                    run_dir,
                )
                self._save(
                    run_dir,
                    state,
                    "verifying",
                    active_attempt_ref=None,
                    builder_dispatch={
                        "state": "completed",
                        "label": actual_label,
                        "strategy": surface.get("strategy", surface.get("kind", "normal")),
                        "surface_ref": surface.get("surface_ref"),
                        "target_symbols": surface.get("target_symbols", []),
                    },
                    test_results=tests,
                )
                if result.get("passed"):
                    try:
                        diff_text, digest, changed, candidate_id = self._stage(
                            worktree,
                            task_plan["allowed_files"],
                            run_dir,
                            next_sequence,
                        )
                        self._prepare_verification_attestation(
                            run_dir,
                            tests,
                            task_id=task_id,
                            base_commit=base_commit,
                            candidate_id=candidate_id,
                            state=state,
                        )
                    except FactoryError as exc:
                        block_resume(f"resumed AGY repair could not produce a candidate: {exc}")
                    self._save(
                        run_dir,
                        state,
                        "reviewing",
                        candidate_id=candidate_id,
                        candidate_state_identity=AgyBuilder._candidate_baseline_identity(worktree),
                        candidate_ref=f"candidate_{self._artifact_sequence(next_sequence)}.json",
                        test_results=tests,
                    )
                    return diff_text, digest, changed, candidate_id

                failure = {
                    "source": "Test Runner",
                    "code": "resumed_test_failure",
                    "criterion_ids": [],
                    "returncode": result.get("returncode"),
                }
                candidate_fingerprint = hashlib.sha256(
                    git(worktree, "diff", "--binary", "--no-ext-diff", "HEAD", "--", *task_plan["allowed_files"]).stdout.encode("utf-8")
                ).hexdigest()
                repair_history = state.get("repair_evidence")
                if not isinstance(repair_history, list):
                    repair_history = []
                repair_history = list(repair_history)
                repair_history.append(
                    {
                        "stage": actual_label,
                        "sequence": next_sequence,
                        "candidate_fingerprint": candidate_fingerprint,
                        "failure_signature": failure_signature(failure),
                        "log": result.get("log"),
                        "strategy": surface.get("strategy", surface.get("kind", "normal")),
                        "surface_ref": surface.get("surface_ref"),
                    }
                )
                state["repair_evidence"] = repair_history
                atomic_json(
                    run_dir / "repair_evidence.json",
                    {"luna_invocation_count": 0, "attempts": repair_history},
                )
                if is_stagnant(
                    previous_candidate,
                    candidate_fingerprint,
                    previous_failure or {},
                    failure,
                ):
                    block_resume("repeated resumed test failure made no progress; run is blocked")
                previous_candidate = candidate_fingerprint
                previous_failure = failure
                if state.get("current_task_attempts", 0) >= config.max_task_attempts:
                    block_resume("resumed AGY repair exhausted the task attempt budget")
                instruction = (
                    "The resumed AGY repair still failed deterministic verification. Apply the smallest additional "
                    "repair within the existing task scope. Do not redesign the plan, edit outside the allowed files, "
                    "or commit.\n\nFailure evidence:\n" + str(result)
                )
                git(worktree, "reset", "--quiet")

        if state["phase"] == "verifying":
            next_sequence = max(
                [item.get("sequence", 0) for item in tests if isinstance(item, dict)] + [0]
            ) + 1
            test_result = self._test(worktree, config, run_dir, next_sequence)
            tests.append(test_result)
            self._assert_source_unchanged(Path(config.repo), state, run_dir, "resume_after_test")
            changed = self._scope_check(worktree, task_plan["allowed_files"], "resume_after_test", run_dir)
            self._save(
                run_dir,
                state,
                "verifying",
                active_attempt_ref=None,
                test_results=tests,
            )
            if not test_result.get("passed"):
                diff_text, digest, changed, expected_candidate = resume_repair(
                    "The resumed Runner verification failed. Apply the smallest AGY repair within the current task scope.\n\n"
                    + str(test_result),
                    f"builder_resume_verify_repair_{self._artifact_sequence(next_sequence)}",
                )
                candidate_id = expected_candidate
                self._save(
                    run_dir,
                    state,
                    "reviewing",
                    candidate_id=candidate_id,
                    candidate_state_identity=AgyBuilder._candidate_baseline_identity(worktree),
                    test_results=tests,
                )
            else:
                try:
                    _, _, changed, expected_candidate = self._stage(
                        worktree,
                        task_plan["allowed_files"],
                        run_dir,
                        next_sequence,
                    )
                    verification_contract = self._prepare_verification_attestation(
                        run_dir,
                        tests,
                        task_id=task_id,
                        base_commit=base_commit,
                        candidate_id=expected_candidate,
                        state=state,
                    )
                except FactoryError as exc:
                    block_resume(f"resumed verification could not produce a candidate: {exc}")
                self._save(
                    run_dir,
                    state,
                    "reviewing",
                    test_results=tests,
                    candidate_id=expected_candidate,
                    candidate_state_identity=AgyBuilder._candidate_baseline_identity(worktree),
                    candidate_ref=f"candidate_{self._artifact_sequence(next_sequence)}.json",
                )
        else:
            changed = self._changed_files(worktree)
            self._scope_check(worktree, task_plan["allowed_files"], "resume_review_scope", run_dir)
            if not tests or not isinstance(tests[-1], dict) or not tests[-1].get("passed"):
                block_resume("resumable review has no passing verification evidence")

        def load_orphan_review(
            digest: str, candidate_id: str, verification_contract: dict[str, Any]
        ) -> tuple[str, dict[str, Any]] | None:
            review_paths = sorted(
                (
                    path
                    for path in run_dir.glob("sol_review_*.json")
                    if re.fullmatch(r"sol_review_[0-9]+\.json", path.name)
                ),
                key=lambda path: int(re.search(r"([0-9]+)", path.stem).group(1)),
                reverse=True,
            )
            for review_path in review_paths:
                try:
                    candidate_review = read_json(review_path)
                except (OSError, json.JSONDecodeError, UnicodeError) as exc:
                    raise FactoryError(
                        "resumable review artifact is unreadable", "blocked"
                    ) from exc
                if not isinstance(candidate_review, dict):
                    continue
                if (
                    candidate_review.get("base_commit") != base_commit
                    or candidate_review.get("candidate_id") != candidate_id
                    or candidate_review.get("reviewed_diff_sha256") != digest
                ):
                    continue
                try:
                    validate_review(
                        candidate_review,
                        digest,
                        base_commit,
                        candidate_id,
                        self._task_review_criteria_ids(task_plan),
                        verification_contract,
                        predecessor_review=self._load_review_predecessor(run_dir, candidate_review),
                    )
                except FactoryError as exc:
                    raise FactoryError(
                        "resumable review artifact does not validate for the current candidate",
                        "blocked",
                    ) from exc
                return review_path.name, candidate_review
            return None

        review_sequence = 1
        previous_review_candidate_id: str | None = None
        previous_review_failure: dict[str, Any] | None = None
        while True:
            diff_text = git(worktree, "diff", "--cached", "--binary", "--no-ext-diff").stdout
            if not diff_text:
                block_resume("resumable review has no staged candidate")
            digest = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
            candidate_id = git(worktree, "write-tree").stdout.strip()
            if expected_candidate is not None and candidate_id != expected_candidate:
                block_resume("resumable review candidate tree changed")
            current_candidate_state = AgyBuilder._candidate_baseline_identity(worktree)
            reviewed_candidate_state = state.get("candidate_state_identity")
            if (
                not isinstance(reviewed_candidate_state, dict)
                or current_candidate_state.get("complete_identity_sha256")
                != reviewed_candidate_state.get("complete_identity_sha256")
            ):
                block_resume("resumable review candidate state changed")
            verification_contract = self._prepare_verification_attestation(
                run_dir,
                tests,
                task_id=task_id,
                base_commit=base_commit,
                candidate_id=candidate_id,
                state=state,
            )
            artifact_sequence = self._artifact_sequence(review_sequence)
            source_context = self._candidate_source_context(
                worktree,
                task_plan["allowed_files"],
                changed,
                candidate_id,
                run_dir,
                review_sequence,
            )
            orphan_review = load_orphan_review(digest, candidate_id, verification_contract)
            if orphan_review is None:
                review_mode, predecessor_review_ref, target_finding_ids, predecessor_review = self._review_retry_context(
                    run_dir,
                    state.get("review_ref"),
                    task_id,
                )
                review = self._review(
                    run_dir=run_dir,
                    config=config,
                    plan=task_plan,
                    diff_text=diff_text,
                    digest=digest,
                    base_commit=base_commit,
                    candidate_id=candidate_id,
                    changed=changed,
                    candidate_source_context=source_context,
                    tests=tests,
                    sequence=review_sequence,
                    review_mode=review_mode,
                    predecessor_review_ref=predecessor_review_ref,
                    target_finding_ids=target_finding_ids,
                    predecessor_review=predecessor_review,
                )
                review_ref = f"sol_review_{artifact_sequence}.json"
            else:
                review_ref, review = orphan_review
            if review.get("replan_reason") is not None:
                state["review_ref"] = review_ref
                self._save(run_dir, state, "reviewing", review_ref=review_ref)
                reason = self._review_replan_reason(review_ref, review, state)
                git(worktree, "reset", "--quiet")
                raise ReplanRequested(reason)
            candidate_ref = state.get("candidate_ref")
            if not isinstance(candidate_ref, str) or not re.fullmatch(
                r"candidate_[0-9]+\.json", candidate_ref
            ):
                candidate_ref = f"candidate_{artifact_sequence}.json"
            candidate_artifact_path = run_dir / candidate_ref
            if candidate_artifact_path.is_file():
                candidate_artifact = read_json(candidate_artifact_path)
                if (
                    not isinstance(candidate_artifact, dict)
                    or candidate_artifact.get("sha256") != digest
                    or candidate_artifact.get("candidate_id") != candidate_id
                    or candidate_artifact.get("base_commit") != base_commit
                ):
                    block_resume("resumable review candidate artifact does not match the staged tree")
            else:
                atomic_json(
                    candidate_artifact_path,
                    {
                        "sha256": digest,
                        "candidate_id": candidate_id,
                        "base_commit": base_commit,
                        "changed_files": changed,
                    },
                )
            self._save(
                run_dir,
                state,
                "reviewing",
                candidate_id=candidate_id,
                candidate_state_identity=current_candidate_state,
                candidate_ref=candidate_ref,
                review_ref=review_ref,
                test_results=tests,
            )
            if review.get("decision") == "APPROVE":
                return self._commit_approved_candidate(
                    identifier=identifier,
                    run_dir=run_dir,
                    state=state,
                    config=config,
                    plan=task_plan,
                    task_id=task_id,
                    worktree=worktree,
                    diff_text=diff_text,
                    digest=digest,
                    changed=changed,
                    candidate_id=candidate_id,
                    review=review,
                    tests=tests,
                    checkpoints=list(state.get("checkpoints", [])) if isinstance(state.get("checkpoints"), list) else [],
                    ledger=ledger,
                    review_sequence=review_sequence,
                    finalize_run=False,
                )

            review_failure = {
                "source": "Sol Reviewer",
                "code": "review_rejection",
                "criterion_ids": open_review_finding_ids(review, task_id),
                "returncode": None,
                "candidate_id": candidate_id,
                "evidence_signature": review_evidence_signature(review),
            }
            if is_stagnant(
                previous_review_candidate_id,
                candidate_id,
                previous_review_failure or {},
                review_failure,
            ):
                block_resume("repeated Sol rejection made no progress; run is blocked")
            previous_review_candidate_id = candidate_id
            previous_review_failure = review_failure
            repair_history = state.get("repair_evidence")
            if not isinstance(repair_history, list):
                repair_history = []
            repair_history = list(repair_history)
            repair_history.append(
                {
                    "stage": "resume_review_rejection",
                    "sequence": review_sequence,
                    "candidate_id": candidate_id,
                    "failure_signature": failure_signature(review_failure),
                    "review_ref": review_ref,
                }
            )
            state["repair_evidence"] = repair_history
            atomic_json(run_dir / "repair_evidence.json", {"luna_invocation_count": 0, "attempts": repair_history})
            required = "\n".join(f"- {item}" for item in review_required_changes(review))
            git(worktree, "reset", "--quiet")
            diff_text, digest, changed, expected_candidate = resume_repair(
                "Sol rejected the resumed candidate. Apply only these required changes:\n" + required,
                f"builder_review_rework_resume_{review_sequence}",
            )
            review_sequence += 1

    def _execute_one_task(
        self,
        identifier: str,
        plan: dict[str, Any],
        task_id: str | None,
        *,
        perform_preflight: bool,
        finalize_run: bool,
    ) -> dict[str, Any]:
        run_dir, state, config = self._load(identifier)
        if finalize_run and state["phase"] in {"committed", "complete"}:
            return self._validate_terminal_state(identifier, run_dir, state, config)
        state.setdefault("luna_invocation_count", 0)
        completed_for_offset = state.get("completed_commits")
        completed_offset = len(completed_for_offset) * 1000 if isinstance(completed_for_offset, list) else 0
        existing_artifact_numbers = [
            int(match.group(1))
            for path in run_dir.iterdir()
            if (match := re.search(r"_(\d+)(?:\.[^.]+)$", path.name))
        ]
        maximum_existing = max(existing_artifact_numbers, default=-1)
        self._artifact_offset = max(completed_offset, maximum_existing + 1)
        allowed = plan["allowed_files"]
        ensure_paths_confined(Path(config.repo), allowed)
        previous_tests = state.get("test_results")
        tests: list[dict[str, Any]] = list(previous_tests) if isinstance(previous_tests, list) else []
        previous_checkpoints = state.get("checkpoints")
        checkpoints: list[str] = (
            list(previous_checkpoints) if isinstance(previous_checkpoints, list) else []
        )
        previous_review_cycles = state.get("review_cycles", 0)
        if isinstance(previous_review_cycles, bool) or not isinstance(previous_review_cycles, int) or previous_review_cycles < 0:
            raise FactoryError("run has invalid review cycle count", "state")

        root_obj_class = state.get("objective_class") or classify_objective(config.request)["classification"]
        ledger = MemoryLedger(run_dir, identifier, config.repo, root_obj_class)

        try:
            self._save(run_dir, state, "preflight_execution", error=None, error_category=None)
            # All three capabilities are proven before creating or changing the task worktree.
            if perform_preflight:
                self._capability_preflight(run_dir, state, config)
                ledger.record_event(phase="preflight_execution", action="capability_preflight", result="success")
            self._assert_source_unchanged(Path(config.repo), state, run_dir, "before_worktree")
            worktree = self._create_worktree(run_dir, state, config)
            ledger.record_event(
                phase="worktree",
                action="create_worktree",
                result="success",
                details={"branch": state.get("branch")},
            )
            ensure_paths_confined(worktree, allowed)
            self._scope_check(worktree, allowed, "before_builder", run_dir)
            cp_initial = self._create_checkpoint(worktree, run_dir, "initial")
            checkpoints.append("initial")
            ledger.record_event(phase="checkpoint", action="checkpoint_initial", result="success")

            repair_history: list[dict[str, Any]] = []

            def capture_repair_failure(
                result: dict[str, Any], stage: str
            ) -> tuple[str, dict[str, Any]]:
                diff = git(
                    worktree,
                    "diff",
                    "--binary",
                    "--no-ext-diff",
                    "HEAD",
                    "--",
                    *allowed,
                ).stdout
                candidate_fingerprint = hashlib.sha256(diff.encode("utf-8")).hexdigest()
                failure = {
                    "source": "Test Runner",
                    "code": "ambiguous_test_failure",
                    "criterion_ids": [],
                    "returncode": result.get("returncode"),
                    "log": result.get("log"),
                }
                repair_history.append(
                    {
                        "stage": stage,
                        "sequence": result.get("sequence"),
                        "candidate_fingerprint": candidate_fingerprint,
                        "failure_signature": failure_signature(failure),
                        "log": result.get("log"),
                    }
                )
                state["luna_invocation_count"] = 0
                state["repair_evidence"] = repair_history
                atomic_json(
                    run_dir / "repair_evidence.json",
                    {
                        "luna_invocation_count": 0,
                        "attempts": repair_history,
                    },
                )
                return candidate_fingerprint, failure

            def block_repair(reason: str, last_failure: dict[str, Any]) -> None:
                evidence = {
                    "reason": reason,
                    "luna_invocation_count": 0,
                    "max_debug_attempts": config.max_debug_attempts,
                    "attempts": repair_history,
                    "last_failure": last_failure,
                }
                atomic_json(
                    run_dir / "repair_evidence.json",
                    {
                        "luna_invocation_count": 0,
                        "attempts": repair_history,
                    },
                )
                atomic_json(run_dir / "repair_blocked.json", evidence)
                ledger.record_event(
                    phase="repair",
                    action="repair_blocked",
                    result="blocked",
                    details=evidence,
                    artifacts=["repair_evidence.json", "repair_blocked.json"],
                )
                self._save(
                    run_dir,
                    state,
                    "blocked",
                    block_reason=reason,
                    repair_evidence=repair_history,
                    repair_block_evidence="repair_blocked.json",
                    luna_invocation_count=0,
                    test_results=tests,
                )
                raise FactoryError(reason, "blocked")

            def reserve_builder_attempt(label: str, surface: dict[str, Any]) -> None:
                current_attempts = state.get("current_task_attempts", 0)
                if isinstance(current_attempts, bool) or not isinstance(current_attempts, int) or current_attempts < 0:
                    raise FactoryError("run has invalid current task attempt count", "state")
                if current_attempts >= config.max_task_attempts:
                    block_repair(
                        "task attempt budget exhausted; run is blocked",
                        {
                            "source": "Hermes",
                            "code": "task_attempt_budget_exhausted",
                            "criterion_ids": [],
                            "returncode": None,
                            "attempts": current_attempts,
                        },
                    )
                baseline = (
                    AgyBuilder._candidate_baseline_identity(worktree)
                    if isinstance(self.builder, AgyBuilder)
                    else None
                )
                self._save(
                    run_dir,
                    state,
                    "building",
                    checkpoints=checkpoints,
                    current_task_attempts=current_attempts + 1,
                    active_attempt_ref=label,
                    candidate_baseline_identity=baseline,
                    builder_dispatch={
                        "state": "reserved",
                        "label": label,
                        "strategy": surface.get("strategy", surface.get("kind", "normal")),
                        "surface_ref": surface.get("surface_ref"),
                        "target_symbols": surface.get("target_symbols", []),
                        "baseline_identity": baseline.get("complete_identity_sha256") if baseline else None,
                    },
                )

            def dispatch_builder(label: str, instruction: str, recovery_stage: int = 0) -> dict[str, Any]:
                current_instruction = instruction
                stage = recovery_stage
                seen_surfaces: set[str] = set()
                while True:
                    surface = self._select_builder_surface(
                        worktree=worktree,
                        run_dir=run_dir,
                        config=config,
                        plan=plan,
                        instruction=current_instruction,
                        recovery_stage=stage,
                        attempt=int(state.get("current_task_attempts", 0)) + 1,
                    )
                    surface_key = json.dumps(
                        {
                            "kind": surface.get("kind"),
                            "surface_ref": surface.get("surface_ref"),
                            "visible_files": surface.get("visible_files"),
                            "target_symbols": surface.get("target_symbols"),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if surface_key in seen_surfaces:
                        raise FactoryError(
                            "AGY navigation recovery repeated the same surface without progress",
                            "blocked",
                        )
                    seen_surfaces.add(surface_key)
                    dispatch_instruction = self._surface_instruction(current_instruction, surface)
                    reserve_builder_attempt(label, surface)
                    try:
                        self._run_builder_attempt(
                            worktree=worktree,
                            instruction=dispatch_instruction,
                            allowed_files=allowed,
                            config=config,
                            run_dir=run_dir,
                            label=label,
                            surface=surface,
                        )
                    except BuilderFailure as exc:
                        recoverable = exc.code in {"agy_timeout", "agy_token_budget_exhausted"}
                        if (
                            config.agy_navigation_recovery == "adaptive"
                            and stage < 2
                            and recoverable
                            and state.get("current_task_attempts", 0) < config.max_task_attempts
                        ):
                            stage += 1
                            current_instruction = self._shrink_builder_instruction(
                                current_instruction,
                                allowed_files=allowed,
                            )
                            self._save(
                                run_dir,
                                state,
                                "building",
                                active_attempt_ref=None,
                                builder_dispatch={
                                    "state": "completed",
                                    "label": label,
                                    "strategy": surface.get("strategy", surface.get("kind")),
                                    "outcome": exc.code,
                                },
                            )
                            continue
                        raise
                    if (
                        config.agy_navigation_recovery == "adaptive"
                        and stage < 2
                        and isinstance(self.builder, AgyBuilder)
                        and self.builder.last_attempt_outcome == "NO_PATCH"
                        and state.get("current_task_attempts", 0) < config.max_task_attempts
                    ):
                        stage += 1
                        current_instruction = self._shrink_builder_instruction(
                            current_instruction,
                            allowed_files=allowed,
                        )
                        self._save(
                            run_dir,
                            state,
                            "building",
                            active_attempt_ref=None,
                            builder_dispatch={
                                "state": "completed",
                                "label": label,
                                "strategy": surface.get("strategy", surface.get("kind")),
                                "outcome": "NO_PATCH",
                            },
                        )
                        continue
                    if (
                        config.agy_navigation_recovery == "adaptive"
                        and stage >= 2
                        and self.builder.last_attempt_outcome == "NO_PATCH"
                    ):
                        raise FactoryError(
                            "AGY navigation recovery exhausted without a patch",
                            "blocked",
                        )
                    return surface

            initial_surface = dispatch_builder(
                "builder_initial",
                self._builder_instruction(config, plan),
            )
            ledger.record_event(
                phase="build",
                action="builder_initial",
                result="success",
                objective_class=root_obj_class,
                artifacts=self._builder_artifacts(run_dir, "builder_initial"),
            )
            self._assert_source_unchanged(Path(config.repo), state, run_dir, "after_builder_initial")
            self._scope_check(worktree, allowed, "after_builder", run_dir)
            self._save(
                run_dir,
                state,
                "verifying",
                active_attempt_ref=None,
                builder_dispatch={
                    "state": "completed",
                    "label": "builder_initial",
                    "strategy": initial_surface.get("strategy", initial_surface.get("kind", "normal")),
                    "surface_ref": initial_surface.get("surface_ref"),
                    "target_symbols": initial_surface.get("target_symbols", []),
                },
            )

            test_sequence = 1
            test_result = self._test(worktree, config, run_dir, test_sequence)
            tests.append(test_result)
            self._assert_source_unchanged(Path(config.repo), state, run_dir, "after_test_1")
            self._scope_check(worktree, allowed, f"after_test_{test_sequence}", run_dir)
            previous_candidate_fingerprint: str | None = None
            previous_failure: dict[str, Any] | None = None
            if test_result["passed"]:
                self._create_checkpoint(worktree, run_dir, f"test_pass_{self._artifact_sequence(test_sequence)}")
                checkpoints.append(f"test_pass_{self._artifact_sequence(test_sequence)}")
                ledger.resolve_issues_by_source(
                    "Test Runner",
                    resolution_evidence={"test_sequence": test_sequence, "passed": True},
                )
                ledger.record_event(
                    phase="test",
                    action=f"test_{test_sequence}",
                    result="success",
                    details=test_result,
                    artifacts=[Path(test_result["log"]).name],
                )
            else:
                previous_candidate_fingerprint, previous_failure = capture_repair_failure(
                    test_result, "initial_test"
                )
                failure_log = Path(test_result["log"]).read_text(encoding="utf-8")[-12_000:]
                test_issue = ledger.record_or_update_issue(
                    source="Test Runner",
                    title=f"Test sequence {test_sequence} failed",
                    description=failure_log[-500:],
                    status="open",
                    cycle=test_sequence,
                    evidence={"returncode": test_result["returncode"], "log": test_result["log"]},
                )
                ledger.record_event(
                    phase="test",
                    action=f"test_{test_sequence}",
                    result="failed",
                    details=test_result,
                    issue_links=[test_issue],
                        artifacts=[Path(test_result["log"]).name],
                )

            debug_attempt = 0
            # The task attempt budget is the sole AGY dispatch budget. Sol
            # finding-only rechecks do not consume it; stagnation remains the
            # deterministic early stop for repeated non-progress.
            while not test_result["passed"] and state.get("current_task_attempts", 0) < config.max_task_attempts:
                debug_attempt += 1
                failure_log = Path(test_result["log"]).read_text(encoding="utf-8")[-12_000:]
                instruction = (
                    "Runner reported a failed verification. Apply the smallest repair that addresses this evidence "
                    "within the existing task scope. Do not redesign the plan, edit outside the allowed files, or commit.\n\n"
                    "Failure evidence:\n"
                    + failure_log
                )
                debug_surface = dispatch_builder(
                    f"builder_debug_{debug_attempt}",
                    instruction,
                    recovery_stage=1,
                )
                ledger.record_event(
                    phase="build",
                    action=f"builder_debug_{debug_attempt}",
                    result="success",
                    objective_class="repair",
                    artifacts=self._builder_artifacts(run_dir, f"builder_debug_{debug_attempt}"),
                )
                self._assert_source_unchanged(
                    Path(config.repo), state, run_dir, f"after_builder_debug_{debug_attempt}"
                )
                self._scope_check(worktree, allowed, f"after_debug_{debug_attempt}", run_dir)
                self._save(
                    run_dir,
                    state,
                    "verifying",
                    active_attempt_ref=None,
                    builder_dispatch={
                        "state": "completed",
                        "label": f"builder_debug_{debug_attempt}",
                        "strategy": debug_surface.get("strategy", debug_surface.get("kind", "normal")),
                        "surface_ref": debug_surface.get("surface_ref"),
                        "target_symbols": debug_surface.get("target_symbols", []),
                    },
                )
                test_sequence += 1
                test_result = self._test(worktree, config, run_dir, test_sequence)
                tests.append(test_result)
                self._assert_source_unchanged(
                    Path(config.repo), state, run_dir, f"after_test_{test_sequence}"
                )
                self._scope_check(worktree, allowed, f"after_test_{test_sequence}", run_dir)
                if test_result["passed"]:
                    self._create_checkpoint(worktree, run_dir, f"test_pass_{self._artifact_sequence(test_sequence)}")
                    checkpoints.append(f"test_pass_{self._artifact_sequence(test_sequence)}")
                    ledger.resolve_issues_by_source(
                        "Test Runner",
                        resolution_evidence={"test_sequence": test_sequence, "passed": True},
                    )
                    ledger.record_event(
                        phase="test",
                        action=f"test_{test_sequence}",
                        result="success",
                        details=test_result,
                        artifacts=[Path(test_result["log"]).name],
                    )
                else:
                    current_candidate_fingerprint, current_failure = capture_repair_failure(
                        test_result, f"builder_debug_{debug_attempt}"
                    )
                    if is_stagnant(
                        previous_candidate_fingerprint,
                        current_candidate_fingerprint,
                        previous_failure or {},
                        current_failure,
                    ):
                        block_repair(
                            "repeated ambiguous test failure made no progress; run is blocked",
                            current_failure,
                        )
                    previous_candidate_fingerprint = current_candidate_fingerprint
                    previous_failure = current_failure
                    failure_log = Path(test_result["log"]).read_text(encoding="utf-8")[-12_000:]
                    test_issue = ledger.record_or_update_issue(
                        source="Test Runner",
                        title=f"Test sequence {test_sequence} failed",
                        description=failure_log[-500:],
                        status="open",
                        cycle=test_sequence,
                        evidence={"returncode": test_result["returncode"], "log": test_result["log"]},
                    )
                    ledger.record_event(
                        phase="test",
                        action=f"test_{test_sequence}",
                        result="failed",
                        details=test_result,
                        issue_links=[test_issue],
                        artifacts=[Path(test_result["log"]).name],
                    )

            if not test_result["passed"]:
                block_repair(
                    "tests still fail after AGY repair budget; run is blocked",
                    previous_failure or {},
                )

            review_sequence = 1
            previous_review_candidate_id: str | None = None
            previous_review_failure: dict[str, Any] | None = None
            while True:
                diff_text, digest, changed, candidate_id = self._stage(
                    worktree, allowed, run_dir, review_sequence
                )
                if not isinstance(task_id, str):
                    raise FactoryError("master-plan task has no task identity for verification binding", "state")
                verification_contract = self._prepare_verification_attestation(
                    run_dir,
                    tests,
                    task_id=task_id,
                    base_commit=git(worktree, "rev-parse", "HEAD").stdout.strip(),
                    candidate_id=candidate_id,
                    state=state,
                )
                artifact_sequence = self._artifact_sequence(review_sequence)
                # Deterministic Pre-Review Gate before calling Sol Reviewer
                gate_record = self._pre_review_gate(
                    worktree, allowed, changed, diff_text, tests, run_dir, artifact_sequence
                )
                ledger.record_event(
                    phase="gate",
                    action=f"pre_review_gate_{artifact_sequence}",
                    result="success",
                    details=gate_record.get("checks"),
                    artifacts=[f"pre_review_gate_{artifact_sequence}.json"],
                )

                candidate_source_context = self._candidate_source_context(
                    worktree, allowed, changed, candidate_id, run_dir, review_sequence
                )
                self._assert_source_unchanged(
                    Path(config.repo), state, run_dir, f"before_review_{artifact_sequence}"
                )
                review_mode, predecessor_review_ref, target_finding_ids, predecessor_review = self._review_retry_context(
                    run_dir,
                    state.get("review_ref") if review_sequence > 1 else None,
                    task_id,
                )
                self._save(
                    run_dir,
                    state,
                    "reviewing",
                    candidate_id=candidate_id,
                    candidate_state_identity=AgyBuilder._candidate_baseline_identity(worktree),
                    candidate_ref=f"candidate_{artifact_sequence}.json",
                    verification_ref=verification_contract["attestation_ref"],
                    # Preserve the predecessor during the small crash window
                    # before the next finding-only Sol call.
                    review_ref=predecessor_review_ref,
                    test_results=tests,
                    pending_commit=None,
                )
                review = self._review(
                    run_dir=run_dir,
                    config=config,
                    plan=plan,
                    diff_text=diff_text,
                    digest=digest,
                    base_commit=candidate_source_context["base_commit"],
                    candidate_id=candidate_id,
                    changed=changed,
                    candidate_source_context=candidate_source_context,
                    tests=tests,
                    sequence=review_sequence,
                    review_mode=review_mode,
                    predecessor_review_ref=predecessor_review_ref,
                    target_finding_ids=target_finding_ids,
                    predecessor_review=predecessor_review,
                )
                state["review_ref"] = f"sol_review_{artifact_sequence}.json"
                if review.get("replan_reason") is not None:
                    reason = self._review_replan_reason(state["review_ref"], review, state)
                    self._safe_rollback(worktree, cp_initial, run_dir)
                    raise ReplanRequested(reason)
                if review["decision"] == "APPROVE":
                    return self._commit_approved_candidate(
                        identifier=identifier,
                        run_dir=run_dir,
                        state=state,
                        config=config,
                        plan=plan,
                        task_id=task_id,
                        worktree=worktree,
                        diff_text=diff_text,
                        digest=digest,
                        changed=changed,
                        candidate_id=candidate_id,
                        review=review,
                        tests=tests,
                        checkpoints=checkpoints,
                        ledger=ledger,
                        review_sequence=review_sequence,
                        finalize_run=finalize_run,
                    )

                review_failure = {
                    "source": "Sol Reviewer",
                    "code": "review_rejection",
                    "criterion_ids": open_review_finding_ids(review, task_id),
                    "returncode": None,
                    "candidate_id": candidate_id,
                    "evidence_signature": review_evidence_signature(review),
                }
                if is_stagnant(
                    previous_review_candidate_id,
                    candidate_id,
                    previous_review_failure or {},
                    review_failure,
                ):
                    block_repair(
                        "repeated Sol rejection made no progress; run is blocked",
                        review_failure,
                    )
                previous_review_candidate_id = candidate_id
                previous_review_failure = review_failure

                # Record checkpoint before rework and reset staged changes
                cp_rework = self._create_checkpoint(worktree, run_dir, f"rejection_{artifact_sequence}")
                checkpoints.append(f"rejection_{artifact_sequence}")
                git(worktree, "reset", "--quiet")
                rev_issue_ids: list[str] = []
                for f_idx, finding in enumerate(review.get("findings", [])):
                    iss_id = ledger.record_or_update_issue(
                        source="Sol Reviewer",
                        title=f"Sol review {review_sequence} finding: {finding[:100]}",
                        description=finding,
                        status="open",
                        severity="rejection",
                        cycle=review_sequence,
                        evidence={"required_changes": review.get("required_changes", [])},
                    )
                    rev_issue_ids.append(iss_id)
                ledger.record_event(
                    phase="review",
                    action=f"sol_review_{artifact_sequence}",
                    result="rejected",
                    details={
                        "decision": "REJECT",
                        "findings": review.get("findings", []),
                        "route": review.get("route"),
                    },
                    issue_links=rev_issue_ids,
                    artifacts=[f"sol_review_{artifact_sequence}.json"],
                )
                required = "\n".join(f"- {item}" for item in review_required_changes(review))
                # validate_review accepts only route=builder for REJECT in v1.
                rework = "Sol rejected the candidate. Apply only these required changes:\n" + required
                review_surface = dispatch_builder(
                    f"builder_review_rework_{review_sequence}",
                    rework,
                    recovery_stage=1,
                )
                ledger.record_event(
                    phase="build",
                    action=f"builder_review_rework_{review_sequence}",
                    result="success",
                    objective_class="repair",
                    issue_links=rev_issue_ids,
                    artifacts=self._builder_artifacts(run_dir, f"builder_review_rework_{review_sequence}"),
                )
                self._assert_source_unchanged(
                    Path(config.repo), state, run_dir, f"after_builder_review_rework_{review_sequence}"
                )
                self._scope_check(worktree, allowed, f"after_review_rework_{review_sequence}", run_dir)
                self._save(
                    run_dir,
                    state,
                    "verifying",
                    active_attempt_ref=None,
                    builder_dispatch={
                        "state": "completed",
                        "label": f"builder_review_rework_{review_sequence}",
                        "strategy": review_surface.get("strategy", review_surface.get("kind", "normal")),
                        "surface_ref": review_surface.get("surface_ref"),
                        "target_symbols": review_surface.get("target_symbols", []),
                    },
                )
                previous_candidate_fingerprint = None
                previous_failure = None
                test_sequence += 1
                test_result = self._test(worktree, config, run_dir, test_sequence)
                tests.append(test_result)
                self._assert_source_unchanged(
                    Path(config.repo), state, run_dir, f"after_test_{test_sequence}"
                )
                self._scope_check(worktree, allowed, f"after_test_{test_sequence}", run_dir)
                # The post-review verification has a distinct artifact namespace.
                if test_result["passed"]:
                    self._create_checkpoint(worktree, run_dir, f"test_pass_{self._artifact_sequence(test_sequence)}")
                    checkpoints.append(f"test_pass_{self._artifact_sequence(test_sequence)}")
                    ledger.resolve_issues_by_source(
                        "Test Runner",
                        resolution_evidence={"test_sequence": test_sequence, "passed": True},
                    )
                    ledger.record_event(
                        phase="test",
                        action=f"test_{test_sequence}",
                        result="success",
                        details=test_result,
                        artifacts=[Path(test_result["log"]).name],
                    )
                else:
                    previous_candidate_fingerprint, previous_failure = capture_repair_failure(
                        test_result, f"review_rework_{review_sequence}"
                    )
                    failure_log = Path(test_result["log"]).read_text(encoding="utf-8")[-12_000:]
                    test_issue = ledger.record_or_update_issue(
                        source="Test Runner",
                        title=f"Test sequence {test_sequence} failed",
                        description=failure_log[-500:],
                        status="open",
                        cycle=test_sequence,
                        evidence={"returncode": test_result["returncode"], "log": test_result["log"]},
                    )
                    ledger.record_event(
                        phase="test",
                        action=f"test_{test_sequence}",
                        result="failed",
                        details=test_result,
                        issue_links=[test_issue],
                        artifacts=[Path(test_result["log"]).name],
                    )

                while not test_result["passed"] and state.get("current_task_attempts", 0) < config.max_task_attempts:
                    debug_attempt += 1
                    failure_log = Path(test_result["log"]).read_text(encoding="utf-8")[-12_000:]
                    review_debug_surface = dispatch_builder(
                        f"builder_review_debug_{review_sequence}_{debug_attempt}",
                        (
                            "The reviewer-requested rework failed verification. Apply the smallest repair that addresses "
                            "this evidence within the unchanged task scope. Do not redesign the plan, edit outside the "
                            "allowed files, or commit.\n\nFailure evidence:\n"
                            + failure_log
                        ),
                        recovery_stage=1,
                    )
                    ledger.record_event(
                        phase="build",
                        action=f"builder_review_debug_{review_sequence}_{debug_attempt}",
                        result="success",
                        objective_class="repair",
                        artifacts=self._builder_artifacts(run_dir, f"builder_review_debug_{review_sequence}_{debug_attempt}"),
                    )
                    self._assert_source_unchanged(
                        Path(config.repo),
                        state,
                        run_dir,
                        f"after_builder_review_debug_{review_sequence}_{debug_attempt}",
                    )
                    self._scope_check(
                        worktree,
                        allowed,
                        f"after_review_debug_{review_sequence}_{debug_attempt}",
                        run_dir,
                    )
                    self._save(
                        run_dir,
                        state,
                        "verifying",
                        active_attempt_ref=None,
                        builder_dispatch={
                            "state": "completed",
                            "label": f"builder_review_debug_{review_sequence}_{debug_attempt}",
                            "strategy": review_debug_surface.get("strategy", review_debug_surface.get("kind", "normal")),
                            "surface_ref": review_debug_surface.get("surface_ref"),
                            "target_symbols": review_debug_surface.get("target_symbols", []),
                        },
                    )
                    test_sequence += 1
                    test_result = self._test(worktree, config, run_dir, test_sequence)
                    tests.append(test_result)
                    self._assert_source_unchanged(
                        Path(config.repo), state, run_dir, f"after_test_{test_sequence}"
                    )
                    self._scope_check(worktree, allowed, f"after_test_{test_sequence}", run_dir)
                    if test_result["passed"]:
                        self._create_checkpoint(worktree, run_dir, f"test_pass_{self._artifact_sequence(test_sequence)}")
                        checkpoints.append(f"test_pass_{self._artifact_sequence(test_sequence)}")
                        ledger.resolve_issues_by_source(
                            "Test Runner",
                            resolution_evidence={"test_sequence": test_sequence, "passed": True},
                        )
                        ledger.record_event(
                            phase="test",
                            action=f"test_{test_sequence}",
                            result="success",
                            details=test_result,
                        artifacts=[Path(test_result["log"]).name],
                        )
                    else:
                        current_candidate_fingerprint, current_failure = capture_repair_failure(
                            test_result,
                            f"builder_review_debug_{review_sequence}_{debug_attempt}",
                        )
                        if is_stagnant(
                            previous_candidate_fingerprint,
                            current_candidate_fingerprint,
                            previous_failure or {},
                            current_failure,
                        ):
                            block_repair(
                                "repeated ambiguous test failure made no progress; run is blocked",
                                current_failure,
                            )
                        previous_candidate_fingerprint = current_candidate_fingerprint
                        previous_failure = current_failure
                        failure_log = Path(test_result["log"]).read_text(encoding="utf-8")[-12_000:]
                        test_issue = ledger.record_or_update_issue(
                            source="Test Runner",
                            title=f"Test sequence {test_sequence} failed",
                            description=failure_log[-500:],
                            status="open",
                            cycle=test_sequence,
                            evidence={"returncode": test_result["returncode"], "log": test_result["log"]},
                        )
                        ledger.record_event(
                            phase="test",
                            action=f"test_{test_sequence}",
                            result="failed",
                            details=test_result,
                            issue_links=[test_issue],
                        artifacts=[Path(test_result["log"]).name],
                        )
                if not test_result["passed"]:
                    raise FactoryError("tests failed after reviewer rework and AGY repair budget", "blocked")
                review_sequence += 1
            raise FactoryError("review loop ended without approval", "review")
        except ReplanRequested as exc:
            ledger.record_event(
                phase="planning",
                action="exceptional_replan_requested",
                result=exc.reason["code"],
                details=exc.reason,
            )
            self._save(
                run_dir,
                state,
                "planning",
                error=str(exc),
                error_category="replan",
                replan_request=exc.reason,
                active_attempt_ref=None,
                candidate_id=None,
                pending_commit=None,
            )
            raise
        except FactoryError as exc:
            phase = "blocked" if exc.category in {"preflight", "provider", "base", "blocked"} else "failed"
            ledger.record_event(
                phase=phase,
                action="execution_aborted",
                result=exc.category,
                details={"error": str(exc), "category": exc.category},
            )
            self._save(run_dir, state, phase, error=str(exc), error_category=exc.category, test_results=tests)
            raise

    def execute(self, identifier: str) -> dict[str, Any]:
        run_dir = self._run_dir(identifier)
        with _run_state_lock(run_dir):
            return self._execute_locked(identifier)

    def _execute_locked(self, identifier: str) -> dict[str, Any]:
        """Run the validated master plan without routine planner calls."""
        run_dir, state, config = self._load(identifier)
        if state["phase"] in {"committed", "complete"}:
            return self._validate_terminal_state(identifier, run_dir, state, config)
        if state["phase"] == "blocked":
            raise FactoryError(
                "blocked run requires a resolved condition or explicit authority before resume",
                "blocked",
            )
        plan = self._load_master_plan_for_execution(run_dir, config, state)
        while True:
            run_dir, state, config = self._load(identifier)
            if state["phase"] in {"committed", "complete"}:
                return self._validate_terminal_state(identifier, run_dir, state, config)
            plan = self._load_master_plan_for_execution(run_dir, config, state)
            if state["phase"] == "committing" or state.get("pending_commit") is not None:
                try:
                    self._reconcile_pending_commit(identifier, run_dir, state, config, plan)
                except FactoryError as exc:
                    self._save(
                        run_dir,
                        state,
                        "blocked",
                        block_reason=str(exc),
                        error=str(exc),
                        error_category="blocked",
                    )
                    raise
                continue
            if state["phase"] in {"verifying", "reviewing"}:
                try:
                    self._resume_existing_task_phase(identifier, run_dir, state, config, plan)
                except ReplanRequested as exc:
                    run_dir, state, config = self._load(identifier)
                    reason_ref = self._persist_replan_reason(run_dir, state, exc.reason)
                    ledger = MemoryLedger(
                        run_dir,
                        identifier,
                        config.repo,
                        state.get("objective_class", "capability_growth"),
                    )
                    self._perform_planning(
                        run_dir,
                        state,
                        config,
                        self._repo(config.repo),
                        ledger=ledger,
                        replan_reason=json.dumps(exc.reason, sort_keys=True),
                        planning_repo=(
                            Path(state["worktree"])
                            if isinstance(state.get("worktree"), str)
                            and Path(state["worktree"]).is_dir()
                            else None
                        ),
                    )
                    continue
                except FactoryError as exc:
                    if state.get("phase") != "blocked":
                        self._save(
                            run_dir,
                            state,
                            "blocked",
                            block_reason=str(exc),
                            error=str(exc),
                            error_category="blocked",
                        )
                    raise
                continue
            if state["phase"] == "planning" and state.get("replan_reason_ref"):
                reason_ref = state["replan_reason_ref"]
                if not isinstance(reason_ref, str) or not re.fullmatch(
                    r"replan_history/[0-9a-f]{64}\.json", reason_ref
                ):
                    raise FactoryError("planning state has an invalid replan reason reference", "blocked")
                reason_path = (run_dir / reason_ref).resolve()
                try:
                    reason_path.relative_to(run_dir.resolve())
                except ValueError as exc:
                    raise FactoryError("planning state replan reason escapes the run directory", "blocked") from exc
                if not reason_path.is_file():
                    raise FactoryError("planning state replan reason artifact is missing", "blocked")
                record = read_json(reason_path)
                if (
                    not isinstance(record, dict)
                    or set(record) != {"schema_version", "sequence", "code", "evidence"}
                    or hashlib.sha256(reason_path.read_bytes()).hexdigest() != reason_ref.split("/")[-1][:-5]
                ):
                    raise FactoryError("planning state replan history record is invalid", "blocked")
                reason = validate_replan_reason({"code": record["code"], "evidence": record["evidence"]})
                self._validate_replan_history(run_dir, state)
                ledger = MemoryLedger(
                    run_dir,
                    identifier,
                    config.repo,
                    state.get("objective_class", "capability_growth"),
                )
                self._perform_planning(
                    run_dir,
                    state,
                    config,
                    self._repo(config.repo),
                    ledger=ledger,
                    replan_reason=json.dumps(reason, sort_keys=True),
                    planning_repo=(
                        Path(state["worktree"])
                        if isinstance(state.get("worktree"), str)
                        and Path(state["worktree"]).is_dir()
                        else None
                    ),
                )
                continue

            completed_commits = state.get("completed_commits")
            if not isinstance(completed_commits, list):
                raise FactoryError("run completed_commits state is invalid", "state")
            completed_ids = {
                item.get("task_id")
                for item in completed_commits
                if isinstance(item, dict) and isinstance(item.get("task_id"), str)
            }
            task_statuses = {
                task["id"]: ("COMMITTED" if task["id"] in completed_ids else "PENDING")
                for task in master_plan_tasks(plan)
            }
            task = next_ready_master_task(plan, task_statuses)

            if task is None:
                all_committed = bool(task_statuses) and all(
                    status == "COMMITTED" for status in task_statuses.values()
                )
                gaps = self._remaining_master_plan_gaps(plan, state)
                if (
                    all_committed
                    and not gaps
                    and state.get("candidate_id") is None
                    and state.get("pending_commit") is None
                    and state.get("active_attempt_ref") is None
                ):
                    ledger = MemoryLedger(
                        run_dir,
                        identifier,
                        config.repo,
                        state.get("objective_class", "capability_growth"),
                    )
                    unresolved = [
                        issue.get("id")
                        for issue in ledger.issues.values()
                        if issue.get("status") in {"open", "regressed"}
                    ]
                    if state.get("block_reason") or unresolved:
                        raise FactoryError(
                            "completion blocked by unresolved evidence",
                            "blocked",
                        )
                    worktree_raw = state.get("worktree")
                    if isinstance(worktree_raw, str) and Path(worktree_raw).is_dir():
                        removed = command(
                            ["git", "worktree", "remove", worktree_raw],
                            cwd=Path(config.repo),
                            timeout=120,
                        )
                        if removed.returncode == 0:
                            state["worktree_removed"] = True
                    self._save(
                        run_dir,
                        state,
                        "complete",
                        current_task_id=None,
                        candidate_id=None,
                        verification_ref=state.get("verification_ref"),
                        verification_attestation_sha256=state.get("verification_attestation_sha256"),
                        review_ref=state.get("review_ref"),
                        test_results=[],
                        pending_commit=None,
                    )
                    return self._validate_terminal_state(identifier, run_dir, state, config)

                reason_code = (
                    "PLAN_EXHAUSTED_OBJECTIVE_INCOMPLETE" if all_committed else "ARCHITECTURE_DEPENDENCY_CONFLICT"
                )
                replan_count = self._durable_replan_attempt_count(run_dir, state)
                next_replan = replan_count + 1
                if next_replan > 2:
                    reason = f"exceptional replan budget exhausted; master plan cannot produce a ready task after {replan_count} replans"
                    evidence = {
                        "reason": reason,
                        "replan_attempts": replan_count,
                        "last_reason_ref": state.get("replan_reason_ref"),
                        "completed_task_ids": sorted(completed_ids),
                        "remaining_gaps": gaps,
                    }
                    atomic_json(run_dir / "replan_blocked.json", evidence)
                    self._save(
                        run_dir,
                        state,
                        "blocked",
                        block_reason=reason,
                        error=reason,
                        error_category="blocked",
                        replan_block_evidence="replan_blocked.json",
                    )
                    raise FactoryError(reason, "blocked")
                reason = {
                    "code": reason_code,
                    "evidence": {
                        "kind": REPLAN_REASON_KINDS[reason_code],
                        "artifact_ref": f"replan_evidence_{next_replan}.json",
                        "verified": True,
                    },
                }
                dependency_identity = next(
                    (
                        f"{dependency}->{item['id']}"
                        for item in master_plan_tasks(plan)
                        for dependency in item.get("depends_on", [])
                    ),
                    None,
                )
                atomic_json(
                    run_dir / reason["evidence"]["artifact_ref"],
                    {
                        "artifact_type": "hermes_replan_evidence_v1",
                        "replan_code": reason_code,
                        "kind": REPLAN_REASON_KINDS[reason_code],
                        "verified": True,
                        "producer": "Hermes",
                        "run_id": identifier,
                        "master_plan_ref": state.get("master_plan_ref"),
                        "request_ref": state.get("request_ref"),
                        "request_sha256": state.get("request_sha256"),
                        "base_commit": state.get("base_commit"),
                        "task_id": state.get("current_task_id"),
                        "candidate_id": state.get("candidate_id"),
                        "sequence": next_replan,
                        "remaining_gaps": gaps,
                        "completed_task_ids": sorted(completed_ids),
                        "blocked_task_ids": sorted(
                            task["id"]
                            for task in master_plan_tasks(plan)
                            if task["id"] not in completed_ids
                        ),
                        **(
                            {"dependency": dependency_identity}
                            if reason_code == "ARCHITECTURE_DEPENDENCY_CONFLICT"
                            else {}
                        ),
                    },
                )
                reason_ref = self._persist_replan_reason(run_dir, state, reason)
                ledger = MemoryLedger(run_dir, identifier, config.repo, state.get("objective_class", "capability_growth"))
                self._perform_planning(
                    run_dir,
                    state,
                    config,
                    self._repo(config.repo),
                    ledger=ledger,
                    replan_reason=json.dumps(reason, sort_keys=True),
                    planning_repo=(
                        Path(state["worktree"])
                        if isinstance(state.get("worktree"), str)
                        and Path(state["worktree"]).is_dir()
                        else None
                    ),
                )
                continue

            previous_task_id = state.get("current_task_id")
            attempts = state.get("current_task_attempts", 0)
            affected_criteria: list[str] = []
            if previous_task_id != task["id"]:
                attempts = 0
                affected_criteria = self._invalidate_affected_criteria(state, task)
            task_plan = self._task_execution_plan(plan, task)
            if affected_criteria:
                task_plan["global_criteria_ids"] = sorted(
                    set(task_plan.get("global_criteria_ids", [])) | set(affected_criteria)
                )
            if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
                raise FactoryError("run has invalid current task attempt count", "state")
            self._save(
                run_dir,
                state,
                "planned",
                current_task_id=task["id"],
                current_task_attempts=attempts,
            )
            try:
                state = self._execute_one_task(
                    identifier,
                    task_plan,
                    task["id"],
                    perform_preflight=False,
                    finalize_run=False,
                )
            except ReplanRequested as exc:
                run_dir, state, config = self._load(identifier)
                reason_ref = self._persist_replan_reason(run_dir, state, exc.reason)
                ledger = MemoryLedger(
                    run_dir,
                    identifier,
                    config.repo,
                    state.get("objective_class", "capability_growth"),
                )
                self._perform_planning(
                    run_dir,
                    state,
                    config,
                    self._repo(config.repo),
                    ledger=ledger,
                    replan_reason=json.dumps(exc.reason, sort_keys=True),
                    planning_repo=(
                        Path(state["worktree"])
                        if isinstance(state.get("worktree"), str)
                        and Path(state["worktree"]).is_dir()
                        else None
                    ),
                )
                continue
            self._record_committed_task_criteria(state, plan, task)
            self._save(
                run_dir,
                state,
                "planned",
                current_task_id=task["id"],
                criterion_evidence=state["criterion_evidence"],
            )

    def status(self, identifier: str) -> dict[str, Any]:
        run_dir = self._run_dir(identifier)
        state = read_run_state(run_dir)
        if state["phase"] in {"committed", "complete"}:
            config = load_config_for_execution(state)
            return self._validate_terminal_state(identifier, run_dir, state, config)
        return state

    def resume(self, identifier: str) -> dict[str, Any]:
        run_dir = self._run_dir(identifier)
        with _run_state_lock(run_dir):
            return self._resume_locked(identifier)

    def _resume_locked(self, identifier: str) -> dict[str, Any]:
        run_dir, state, config = self._load(identifier)
        if state["phase"] in {"committed", "complete"}:
            return self._validate_terminal_state(identifier, run_dir, state, config)
        if state["phase"] == "blocked" and state.get("error_category") == "blocked":
            raise FactoryError(
                "blocked run requires a resolved condition or explicit authority before resume",
                "blocked",
            )
        if state["phase"] == "committing" or state.get("pending_commit") is not None:
            plan = self._load_master_plan_for_execution(run_dir, config, state)
            try:
                self._reconcile_pending_commit(identifier, run_dir, state, config, plan)
            except FactoryError as exc:
                self._save(
                    run_dir,
                    state,
                    "blocked",
                    block_reason=str(exc),
                    error=str(exc),
                    error_category="blocked",
                )
                raise
            return self._execute_locked(identifier)
        dispatch = state.get("builder_dispatch")
        if isinstance(dispatch, dict) and dispatch.get("state") == "dispatched":
            raise FactoryError(
                "run has an ambiguous Builder dispatch and cannot be resumed safely",
                "state",
            )
        if state.get("active_attempt_ref") is not None:
            raise FactoryError(
                "run has an incomplete Builder attempt and cannot be resumed safely",
                "state",
            )
        if state["phase"] not in {
            "planned",
            "blocked",
            "failed",
            "worktree_ready",
            "preflight_execution",
            "building",
            "verifying",
            "reviewing",
        }:
            raise FactoryError(f"run cannot be resumed safely from phase {state['phase']!r}", "state")
        if state["phase"] == "building":
            reason = "run cannot be resumed safely: persisted execution phase cannot safely replay the Builder"
            self._save(run_dir, state, "blocked", block_reason=reason, error_category="blocked")
            raise FactoryError(reason, "blocked")
        if not state.get("master_plan_ref"):
            astra_calls = state.get("astra_invocation_count", 0)
            if astra_calls:
                raise FactoryError(
                    "run has an incomplete Astra planning dispatch and cannot be resumed safely",
                    "state",
                )
            repo = self._repo(config.repo)
            ledger = MemoryLedger(
                run_dir,
                identifier,
                config.repo,
                state.get("objective_class") or "capability_growth",
            )
            self._capability_preflight(run_dir, state, config)
            self._perform_planning(run_dir, state, config, repo, ledger=ledger)
        else:
            self._load_master_plan_for_execution(run_dir, config, state)
        state["warm_start"] = True
        atomic_json(
            run_dir / "warm_start.json",
            {"warm_start": True, "resumed_from": state.get("phase"), "timestamp": now_iso()},
        )
        atomic_json(run_dir / "run_state.json", state)
        return self._execute_locked(identifier)


def split_files(raw_values: list[str] | None) -> list[str] | None:
    if not raw_values:
        return None
    values: list[str] = []
    for raw in raw_values:
        values.extend(item.strip() for item in raw.split(",") if item.strip())
    return normalized_paths(values)


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repo", help="Git repository top-level path")
    parser.add_argument("request", help="Implementation request")
    parser.add_argument("--files", action="append", help="Hard file boundary; repeat or comma-separate")
    parser.add_argument("--test-cmd", default=None, help="Explicit test command")
    parser.add_argument("--prior-run", default=None, help="Prior run ID for progressive disclosure context")
    parser.add_argument("--planner-provider", default="openai-codex")
    parser.add_argument("--planner-model", default=DEFAULT_PLANNER_MODEL)
    parser.add_argument("--planner-reasoning", default=DEFAULT_PLANNER_REASONING)
    parser.add_argument("--reviewer-provider", default="openai-codex")
    parser.add_argument("--reviewer-model", default=DEFAULT_REVIEWER_MODEL)
    parser.add_argument("--reviewer-reasoning", default=DEFAULT_REVIEWER_REASONING)
    parser.add_argument("--sol-provider", default="openai-codex")
    parser.add_argument("--sol-model", default=DEFAULT_SOL_MODEL)
    parser.add_argument("--builder-model", default=DEFAULT_BUILDER_MODEL)
    parser.add_argument("--agy-bin", default=None)
    parser.add_argument(
        "--agy-navigation-recovery",
        choices=sorted(AGY_NAVIGATION_RECOVERY_MODES),
        default=AGY_NAVIGATION_RECOVERY_DEFAULT,
        help="AGY navigation recovery mode: off, observe, or adaptive",
    )
    parser.add_argument("--max-task-attempts", type=int, default=12)
    parser.add_argument("--max-debug-attempts", type=int, default=2)
    parser.add_argument("--max-review-cycles", type=int, default=2)
    parser.add_argument("--role-timeout", type=int, default=300)
    parser.add_argument("--builder-timeout", type=int, default=900)
    parser.add_argument("--test-timeout", type=int, default=900)


def config_from_args(args: argparse.Namespace) -> Config:
    return Config(
        repo=args.repo,
        request=args.request,
        requested_files=split_files(args.files),
        test_command=args.test_cmd,
        prior_run=getattr(args, "prior_run", None),
        planner_provider=args.planner_provider,
        planner_model=args.planner_model,
        planner_reasoning=args.planner_reasoning,
        reviewer_provider=args.reviewer_provider,
        reviewer_model=args.reviewer_model,
        reviewer_reasoning=args.reviewer_reasoning,
        sol_provider=args.sol_provider,
        sol_model=args.sol_model,
        builder_model=args.builder_model,
        agy_bin=getattr(args, "agy_bin", None),
        agy_navigation_recovery=args.agy_navigation_recovery,
        max_task_attempts=args.max_task_attempts,
        max_debug_attempts=args.max_debug_attempts,
        max_review_cycles=args.max_review_cycles,
        role_timeout=args.role_timeout,
        builder_timeout=args.builder_timeout,
        test_timeout=args.test_timeout,
    )


def print_result(state: dict[str, Any]) -> None:
    print(json.dumps(state, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Software Factory v2")
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT), help="Run artifact root")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="plan and execute a complete task")
    add_common(run_parser)
    plan_parser = sub.add_parser("plan", help="create and validate an Astra master plan only")
    add_common(plan_parser)
    for name in ("execute", "resume", "status"):
        child = sub.add_parser(name)
        child.add_argument("run_id")
    sub.choices["status"].add_argument("--json", action="store_true", help="print full JSON")

    args = parser.parse_args(argv)
    engine = FactoryEngine(state_root=Path(args.state_root))
    try:
        if args.command == "plan":
            identifier = engine.plan(config_from_args(args))
            print(identifier)
        elif args.command == "run":
            identifier = engine.plan(config_from_args(args))
            print(f"Run: {identifier}", file=sys.stderr)
            print_result(engine.execute(identifier))
        elif args.command == "execute":
            print_result(engine.execute(args.run_id))
        elif args.command == "resume":
            print_result(engine.resume(args.run_id))
        else:
            state = engine.status(args.run_id)
            if args.json:
                print_result(state)
            else:
                summary = {key: state.get(key) for key in ("run_id", "phase", "branch", "commit", "error") if state.get(key) is not None}
                print_result(summary)
        return 0
    except FactoryError as exc:
        print(f"Factory {exc.category}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
