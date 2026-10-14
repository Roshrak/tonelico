from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(r"E:\Downloads\hermes-software-factory-v2-hoh\migration-worktree-recovered2")
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "tests"))

from hermes_factory_v2 import FactoryEngine, atomic_json, master_plan_tasks  # noqa: E402
from test_factory_v2 import (  # noqa: E402
    FactoryIntegrationTests,
    HermesThenUserRoles,
    ScopeChangingBuilder,
)


case = FactoryIntegrationTests("test_json_parser_accepts_fenced_nested_objects")
case.setUp()
try:
    roles = HermesThenUserRoles()
    builder = ScopeChangingBuilder()
    engine = FactoryEngine(state_root=case.state_root, role_client=roles, builder=builder)
    config = case.config()
    config.requested_files = ["calc.py", "test_calc.py", "new.py"]
    config.test_command = f'"{sys.executable}" -c "pass"'
    (case.repo / "new.py").write_text("replacement = 0\n", encoding="utf-8")
    subprocess.run(["git", "add", "new.py"], cwd=case.repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add replacement fixture"], cwd=case.repo, check=True)
    identifier = engine.plan(config)
    original_execute_one = engine._execute_one_task
    pause_target = {"completed": 1}

    def pause_after_commit(*args, **kwargs):
        state = original_execute_one(*args, **kwargs)
        if len(state.get("completed_commits", [])) == pause_target["completed"]:
            pause_target["completed"] = 2
            raise KeyboardInterrupt("pause")
        return state

    with patch.object(engine, "_execute_one_task", side_effect=pause_after_commit):
        try:
            engine.execute(identifier)
        except KeyboardInterrupt:
            pass
    paused = engine.status(identifier)
    plan = json.loads((case.state_root / identifier / paused["master_plan_ref"]).read_text(encoding="utf-8"))
    completed_ids = sorted(item["task_id"] for item in paused["completed_commits"])
    pending_ids = sorted(task["id"] for task in master_plan_tasks(plan) if task["id"] not in completed_ids)
    evidence_ref = "replan_evidence_1.json"
    atomic_json(
        case.state_root / identifier / evidence_ref,
        {
            "artifact_type": "hermes_replan_evidence_v1",
            "replan_code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
            "kind": "dependency_conflict",
            "verified": True,
            "producer": "Hermes",
            "run_id": identifier,
            "master_plan_ref": paused["master_plan_ref"],
            "request_ref": paused["request_ref"],
            "request_sha256": paused["request_sha256"],
            "base_commit": paused["base_commit"],
            "task_id": paused["current_task_id"],
            "candidate_id": paused["candidate_id"],
            "sequence": 1,
            "remaining_gaps": [],
            "completed_task_ids": completed_ids,
            "blocked_task_ids": pending_ids,
            "dependency": next(
                f"{dependency}->{item['id']}"
                for item in master_plan_tasks(plan)
                for dependency in item.get("depends_on", [])
            ),
        },
    )
    reason = {
        "code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
        "evidence": {"artifact_ref": evidence_ref, "kind": "dependency_conflict", "verified": True},
    }
    with patch.object(engine, "_execute_one_task", side_effect=pause_after_commit):
        try:
            engine.request_replan(identifier, reason)
        except KeyboardInterrupt:
            pass
    pause_target["completed"] = 99
    completed = engine.request_replan(
        identifier,
        {
            "code": "USER_OBJECTIVE_OR_SCOPE_CHANGE",
            "evidence": {"artifact_ref": "user-supplied.json", "kind": "user_change", "verified": True},
        },
        objective="Implement the replacement user objective",
        requested_files=["calc.py", "test_calc.py", "new.py"],
    )

    first_entry = completed["replan_history"][0]
    record_path = case.state_root / identifier / first_entry["record_ref"]
    record = json.loads(record_path.read_text(encoding="utf-8"))
    evidence_path = case.state_root / identifier / record["evidence"]["artifact_ref"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    original_base = evidence["base_commit"]
    forged_records = completed["completed_commits"][:2]
    forged_completed_ids = sorted(item["task_id"] for item in forged_records)
    forged_base = forged_records[-1]["commit"]
    historical_plan = json.loads(
        (case.state_root / identifier / evidence["master_plan_ref"]).read_text(encoding="utf-8")
    )
    evidence["base_commit"] = forged_base
    evidence["candidate_id"] = None
    evidence["completed_task_ids"] = forged_completed_ids
    evidence["blocked_task_ids"] = sorted(
        task["id"] for task in master_plan_tasks(historical_plan) if task["id"] not in forged_completed_ids
    )
    evidence["task_id"] = forged_completed_ids[-1]
    atomic_json(evidence_path, evidence)
    record["evidence"]["artifact_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    temporary_record = case.state_root / identifier / "forged-record.json"
    atomic_json(temporary_record, record)
    forged_record_sha = hashlib.sha256(temporary_record.read_bytes()).hexdigest()
    forged_record_ref = f"replan_history/{forged_record_sha}.json"
    temporary_record.replace(case.state_root / identifier / forged_record_ref)
    state_path = case.state_root / identifier / "run_state.json"
    durable_state = json.loads(state_path.read_text(encoding="utf-8"))
    durable_state["replan_history"][0] = {
        "sequence": 1,
        "record_ref": forged_record_ref,
        "record_sha256": forged_record_sha,
        "code": "ARCHITECTURE_DEPENDENCY_CONFLICT",
    }
    atomic_json(state_path, durable_state)
    accepted = engine.status(identifier)
    print(json.dumps({
        "accepted_phase": accepted["phase"],
        "original_base": original_base,
        "forged_base": forged_base,
        "forged_completed_task_ids": forged_completed_ids,
        "astra_invocation_count": roles.astra_invocation_count,
        "luna_invocation_count": roles.luna_invocation_count,
    }, sort_keys=True))
finally:
    case.tearDown()
