#!/usr/bin/env python3
"""Proofrail: a tiny, model-independent evidence gate for agent work.

It verifies declared success signals in saved evidence; it does not judge
whether the goal itself was wise or whether evidence is authentic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = 1


def _load(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"plan not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan JSON is corrupt: {exc}") from exc
    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA or not isinstance(obj.get("checks"), list):
        raise ValueError("unsupported or malformed plan")
    return obj


def plan_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def initialize(path: Path, goal: str) -> dict[str, Any]:
    goal = goal.strip()
    if not goal:
        raise ValueError("goal must not be empty")
    if path.exists():
        raise ValueError(f"refusing to overwrite existing plan: {path}")
    obj = {"schema": SCHEMA, "goal": goal, "created_utc": datetime.now(timezone.utc).isoformat(), "checks": []}
    _save(path, obj)
    return obj


def add_check(path: Path, name: str, evidence_file: str, must_contain: str) -> dict[str, Any]:
    name, evidence_file = name.strip(), evidence_file.strip()
    if not name or not evidence_file or not must_contain.strip():
        raise ValueError("check name, evidence file, and required signal must all be nonempty")
    obj = _load(path)
    if any(check.get("name", "").casefold() == name.casefold() for check in obj["checks"]):
        raise ValueError(f"duplicate check name: {name}")
    check = {"kind": "text", "name": name, "evidence_file": evidence_file, "must_contain": must_contain}
    obj["checks"].append(check)
    _save(path, obj)
    return check


def add_command_check(path: Path, name: str, argv: list[str], cwd: str = ".", timeout_seconds: float = 60) -> dict[str, Any]:
    name, cwd = name.strip(), cwd.strip()
    if not name or not cwd or not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
        raise ValueError("check name, working directory, and a nonempty argv list of strings are required")
    if not isinstance(argv, list):
        raise ValueError("command must be an argument list, not a shell string")
    if not 0.1 <= timeout_seconds <= 300:
        raise ValueError("timeout must be between 0.1 and 300 seconds")
    obj = _load(path)
    if any(check.get("name", "").casefold() == name.casefold() for check in obj["checks"]):
        raise ValueError(f"duplicate check name: {name}")
    check = {"kind": "command", "name": name, "argv": argv, "cwd": cwd, "timeout_seconds": timeout_seconds}
    obj["checks"].append(check)
    _save(path, obj)
    return check


def _run_file(path: Path, index: int) -> Path:
    return path.parent / ".proofrail" / f"command-{index}.json"


def run_commands(path: Path, approved_hash: str) -> list[dict[str, Any]]:
    current_hash = plan_digest(path)
    if not approved_hash or current_hash.casefold() != approved_hash.casefold():
        raise ValueError(f"plan hash does not match approval; inspect `show {path}` and approve the current SHA-256")
    obj = _load(path)
    runs = []
    for index, check in enumerate(obj["checks"], start=1):
        if check.get("kind") != "command":
            continue
        if plan_digest(path).casefold() != approved_hash.casefold():
            raise ValueError("plan changed during execution; remaining commands were not started")
        run_cwd = Path(check["cwd"])
        if not run_cwd.is_absolute():
            run_cwd = path.parent / run_cwd
        started = datetime.now(timezone.utc).isoformat()
        result: dict[str, Any] = {"name": check["name"], "argv": check["argv"], "cwd": str(run_cwd), "timeout_seconds": check["timeout_seconds"], "plan_sha256": approved_hash, "started_utc": started, "timed_out": False, "launch_error": ""}
        try:
            proc = subprocess.run(check["argv"], cwd=run_cwd, shell=False, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=check["timeout_seconds"], check=False)
            result.update({"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        except subprocess.TimeoutExpired as exc:
            result.update({"returncode": None, "timed_out": True, "stdout": (exc.stdout or "").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""), "stderr": (exc.stderr or "").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")})
        except OSError as exc:
            result.update({"returncode": None, "launch_error": str(exc), "stdout": "", "stderr": ""})
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        result["plan_sha256_after"] = plan_digest(path)
        result["output_sha256"] = hashlib.sha256((result["stdout"] + "\0" + result["stderr"]).encode("utf-8")).hexdigest()
        dest = _run_file(path, index)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(dest)
        result["record_file"] = str(dest)
        runs.append(result)
    if not runs:
        raise ValueError("plan has no command checks to run")
    return runs


def verify(path: Path) -> dict[str, Any]:
    obj = _load(path)
    current_plan_hash = plan_digest(path)
    checks: list[dict[str, str]] = []
    for index, check in enumerate(obj["checks"], start=1):
        name = check["name"]
        if check.get("kind") == "command":
            record_path = _run_file(path, index)
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                checks.append({"name": name, "status": "NOT_RUN", "evidence_file": str(record_path)})
                continue
            except (OSError, json.JSONDecodeError):
                checks.append({"name": name, "status": "INVALID_RECORD", "evidence_file": str(record_path)})
                continue
            if (not isinstance(record, dict) or not isinstance(record.get("stdout"), str) or
                    not isinstance(record.get("stderr"), str) or not isinstance(record.get("output_sha256"), str) or
                    not isinstance(record.get("plan_sha256"), str) or not isinstance(record.get("plan_sha256_after"), str)):
                checks.append({"name": name, "status": "INVALID_RECORD", "evidence_file": str(record_path)})
                continue
            output = record.get("stdout", "") + "\0" + record.get("stderr", "")
            digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
            expected_cwd = Path(check["cwd"])
            if not expected_cwd.is_absolute():
                expected_cwd = path.parent / expected_cwd
            if (record.get("plan_sha256") != current_plan_hash or
                    record.get("plan_sha256_after") != current_plan_hash):
                status = "PLAN_CHANGED"
            elif (record.get("argv") != check.get("argv") or record.get("name") != name or
                    record.get("cwd") != str(expected_cwd) or record.get("timeout_seconds") != check.get("timeout_seconds")):
                status = "RUN_MISMATCH"
            elif digest != record.get("output_sha256"):
                status = "OUTPUT_CHANGED"
            elif record.get("timed_out"):
                status = "TIMEOUT"
            elif record.get("launch_error"):
                status = "LAUNCH_ERROR"
            elif record.get("returncode") != 0:
                status = "COMMAND_FAILED"
            else:
                status = "PASS"
            checks.append({"name": name, "status": status, "evidence_file": str(record_path), "sha256": digest, "returncode": record.get("returncode"), "argv": record.get("argv")})
            continue
        evidence_path = Path(check["evidence_file"])
        if not evidence_path.is_absolute():
            evidence_path = path.parent / evidence_path
        try:
            raw = evidence_path.read_bytes()
        except OSError:
            checks.append({"name": name, "status": "MISSING", "evidence_file": str(evidence_path)})
            continue
        digest = hashlib.sha256(raw).hexdigest()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            checks.append({"name": name, "status": "NOT_TEXT", "evidence_file": str(evidence_path), "sha256": digest})
            continue
        if check["must_contain"] not in text:
            checks.append({"name": name, "status": "SIGNAL_MISSING", "evidence_file": str(evidence_path), "sha256": digest, "required_signal": check["must_contain"]})
        else:
            checks.append({"name": name, "status": "PASS", "evidence_file": str(evidence_path), "sha256": digest, "required_signal": check["must_contain"]})
    if not checks:
        reason = "NO_CHECKS"
    else:
        reason = "ALL_CHECKS_PASSED" if all(c["status"] == "PASS" for c in checks) else "EVIDENCE_INCOMPLETE"
    return {"goal": obj["goal"], "passed": reason == "ALL_CHECKS_PASSED", "reason": reason, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate an agent's completion claim on saved evidence.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="create a task evidence plan")
    p_init.add_argument("plan", type=Path)
    p_init.add_argument("--goal", required=True)
    p_req = sub.add_parser("require", help="declare a required evidence signal")
    p_req.add_argument("plan", type=Path)
    p_req.add_argument("--name", required=True)
    p_req.add_argument("--file", required=True, help="evidence text file; relative paths use plan directory")
    p_req.add_argument("--contains", required=True, help="exact success signal required in evidence")
    p_cmd = sub.add_parser("require-command", help="declare a command to run as an explicit validator")
    p_cmd.add_argument("plan", type=Path)
    p_cmd.add_argument("--name", required=True)
    p_cmd.add_argument("--argv-json", required=True, help='JSON array, e.g. ["python", "-m", "unittest"]')
    p_cmd.add_argument("--cwd", default=".", help="working directory, relative to plan directory")
    p_cmd.add_argument("--timeout", type=float, default=60)
    p_run = sub.add_parser("run", help="run configured validators only for the approved plan hash")
    p_run.add_argument("plan", type=Path)
    p_run.add_argument("--approve-hash", required=True, help="SHA-256 copied after inspecting `show` output")
    p_show = sub.add_parser("show", help="print the plan and its approval hash")
    p_show.add_argument("plan", type=Path)
    p_ver = sub.add_parser("verify", help="check all declared evidence; exit 0 only if every check passes")
    p_ver.add_argument("plan", type=Path)
    p_ver.add_argument("--json", action="store_true", help="machine-readable result")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(args.plan, args.goal)
            print(f"Plan created: {args.plan} — {result['goal']}")
            return 0
        if args.command == "require":
            check = add_check(args.plan, args.name, args.file, args.contains)
            print(f"Requirement added: {check['name']}")
            return 0
        if args.command == "require-command":
            command = json.loads(args.argv_json)
            check = add_command_check(args.plan, args.name, command, args.cwd, args.timeout)
            print(f"Command requirement added: {check['name']} — {json.dumps(check['argv'], ensure_ascii=False)}")
            return 0
        if args.command == "show":
            obj = _load(args.plan)
            print(json.dumps(obj, indent=2, ensure_ascii=False))
            print(f"Approval SHA-256: {plan_digest(args.plan)}")
            return 0
        if args.command == "run":
            runs = run_commands(args.plan, args.approve_hash)
            for run in runs:
                print(f"{'TIMEOUT' if run['timed_out'] else 'EXIT '+str(run['returncode'])}: {run['name']} — {run['record_file']}")
            return 0 if all(not r["timed_out"] and not r["launch_error"] and r["returncode"] == 0 for r in runs) else 1
        result = verify(args.plan)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"Goal: {result['goal']}\nResult: {'PASS' if result['passed'] else 'BLOCKED'} ({result['reason']})")
            for check in result["checks"]:
                print(f"- {check['status']}: {check['name']} | {check['evidence_file']}" + (f" | sha256 {check['sha256']}" if 'sha256' in check else ""))
        return 0 if result["passed"] else 1
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
