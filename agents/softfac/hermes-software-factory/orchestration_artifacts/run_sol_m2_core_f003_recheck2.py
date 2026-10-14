"""Run one final M2-S8-F003 finding-only recheck."""

from pathlib import Path


SOURCE = Path(r"C:\Users\HH18\run_sol_m2_core_finding_recheck.py")


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    replacements = {
        'PREVIOUS_TREE = "1bd19cfa43afdefa25032dba2c62f320e9335188"':
            'PREVIOUS_TREE = "eb383522afb0f663ff2ed4a814f40d8a24d9ee93"',
        'PRIOR = Path(r"C:\\Users\\HH18\\sol_m2_core_verdict.json")':
            'PRIOR = Path(r"C:\\Users\\HH18\\sol_m2_core_finding_recheck_verdict.json")',
        'prior.get("review_type") != "LARGE_STEP_REVIEW"':
            'prior.get("review_type") != "FINDING_ONLY_RECHECK"',
        'M2-S8-F001", "M2-S8-F002", "M2-S8-F003': 'M2-S8-F003',
        '"sol_m2_core_finding_recheck': '"sol_m2_core_f003_recheck2',
        'target_findings = M2-S8-F001, M2-S8-F002, M2-S8-F003':
            'target_findings = M2-S8-F003',
        'The M2-Core LARGE_STEP_REVIEW already happened exactly once. Recheck only those three predecessor findings, this exact repair delta, and affected deterministic evidence. Do not perform another large review. Step 7 and all other resolved findings are frozen.':
            'The M2-Core LARGE_STEP_REVIEW and prior F001/F002 recheck are complete. Recheck only M2-S8-F003, this exact repair delta, and affected deterministic evidence. Do not perform another large review. Step 7 and all other resolved findings are frozen.',
        '"target_findings": ["M2-S8-F001", "M2-S8-F002", "M2-S8-F003"]':
            '"target_findings": ["M2-S8-F003"]',
        '"target_findings": ["M2-S8-F001", "M2-S8-F002", "M2-S8-F003"],':
            '"target_findings": ["M2-S8-F003"],',
    }
    for old, new in replacements.items():
        source = source.replace(old, new)
    namespace = {"__name__": "m2_f003_recheck2_launcher"}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
