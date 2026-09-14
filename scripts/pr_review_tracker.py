#!/usr/bin/env python3
"""Local, cross-agent registry for pull-request review runs."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit


DEFAULT_TASKS = (
    "checkout",
    "explainer",
    "correctness-review",
    "contracts-review",
    "security-review",
    "runtime-verification",
    "synthesis",
    "drafts",
)
TASK_STATUSES = (
    "queued",
    "running",
    "completed",
    "failed",
    "blocked",
    "skipped",
    "cancelled",
)
CONTROL_STATUSES = ("active", "cancelled")
PR_STATES = ("unknown", "open", "closed", "merged")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PR_PATH = re.compile(
    r"^/([A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"([A-Za-z0-9][A-Za-z0-9._-]*)/pull/([1-9][0-9]*)/?$"
)


class TrackerError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TrackerError(f"Invalid registry timestamp: {value}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def tracker_root() -> Path:
    configured = os.environ.get("PR_REVIEW_TRACKER_HOME")
    root = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "share" / "pr-review-tracker"
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    (root / "runs").mkdir(mode=0o700, exist_ok=True)
    (root / "checkouts").mkdir(mode=0o700, exist_ok=True)
    return root


def validate_name(value: str, label: str) -> str:
    if not SAFE_NAME.fullmatch(value):
        raise TrackerError(f"Invalid {label}: {value!r}")
    return value


def canonical_pr_url(value: str) -> tuple[str, str, str, int]:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.port
    ):
        raise TrackerError(
            "PR URL must be https://github.com/<owner>/<repository>/pull/<number>"
        )
    match = PR_PATH.fullmatch(parsed.path)
    if not match:
        raise TrackerError(
            "PR URL must be https://github.com/<owner>/<repository>/pull/<number>"
        )
    owner, repository, number_text = match.groups()
    repository = repository.removesuffix(".git")
    number = int(number_text)
    path = f"/{quote(owner)}/{quote(repository)}/pull/{number}"
    canonical = urlunsplit(("https", "github.com", path, "", ""))
    return canonical, owner, repository, number


def run_dir(run_id: str) -> Path:
    validate_name(run_id, "run ID")
    path = tracker_root() / "runs" / run_id
    if not path.is_dir():
        raise TrackerError(f"Unknown review run: {run_id}")
    return path


def read_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise TrackerError(f"Missing registry file: {path}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrackerError(f"Malformed registry file {path}: {error}") from error
    if not isinstance(value, dict):
        raise TrackerError(f"Registry file must contain an object: {path}")
    return value


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def make_run_id(owner: str, repository: str, number: int, tool: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_tool = re.sub(r"[^A-Za-z0-9._-]+", "-", tool).strip("-") or "agent"
    safe_tool = safe_tool[:24]
    suffix = secrets.token_hex(3)
    return (
        f"{owner[:24]}-{repository[:32]}-pr{number}-"
        f"{stamp}-{safe_tool}-{suffix}"
    )


def command_start(args: argparse.Namespace, *, emit: bool = True) -> str:
    canonical, owner, repository, number = canonical_pr_url(args.pr_url)
    tool = args.tool.strip()
    if not tool:
        raise TrackerError("Tool name cannot be empty")
    created = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    run_id = make_run_id(owner, repository, number, tool)
    directory = tracker_root() / "runs" / run_id
    directory.mkdir(mode=0o700)

    atomic_write(
        directory / "run.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "pr_url": canonical,
            "owner": owner,
            "repository": repository,
            "pr_number": number,
            "tool": tool,
            "working_directory": str(
                Path(args.working_directory or os.getcwd())
                .expanduser()
                .resolve(strict=False)
            ),
            "created_at": created,
        },
    )
    atomic_write(
        directory / "context.json",
        {
            "title": args.title,
            "base_sha": args.base_sha,
            "head_sha": args.head_sha,
            "updated_at": created,
        },
    )
    atomic_write(
        directory / "session.json",
        {"reference": args.session_reference, "updated_at": created},
    )
    atomic_write(
        directory / "control.json",
        {"status": "active", "message": "", "updated_at": created},
    )
    atomic_write(
        directory / "github.json",
        {
            "state": "unknown",
            "closed_at": "",
            "merged_at": "",
            "archived_at": "",
            "last_checked_at": "",
            "last_attempted_at": "",
            "last_error": "",
            "updated_at": created,
        },
    )
    for task in DEFAULT_TASKS:
        atomic_write(
            directory / "tasks" / f"{task}.json",
            {
                "task": task,
                "status": "queued",
                "message": "",
                "updated_at": created,
            },
        )
    if emit:
        print(run_id)
    return run_id


def command_set_context(args: argparse.Namespace) -> None:
    directory = run_dir(args.run_id)
    current = read_json(directory / "context.json", required=False)
    for field in ("title", "base_sha", "head_sha"):
        value = getattr(args, field)
        if value is not None:
            current[field] = value
    current["updated_at"] = utc_now()
    atomic_write(directory / "context.json", current)


def command_set_session(args: argparse.Namespace) -> None:
    directory = run_dir(args.run_id)
    atomic_write(
        directory / "session.json",
        {"reference": args.reference, "updated_at": utc_now()},
    )


def command_set_task(args: argparse.Namespace) -> None:
    directory = run_dir(args.run_id)
    task = validate_name(args.task, "task name")
    atomic_write(
        directory / "tasks" / f"{task}.json",
        {
            "task": task,
            "status": args.status,
            "message": args.message,
            "updated_at": utc_now(),
        },
    )


def command_add_artifact(args: argparse.Namespace) -> None:
    directory = run_dir(args.run_id)
    name = validate_name(args.name, "artifact name")
    artifact_path = Path(args.path).expanduser().resolve(strict=False)
    context = read_json(directory / "context.json", required=False)
    atomic_write(
        directory / "artifacts" / f"{name}.json",
        {
            "name": name,
            "kind": args.kind,
            "path": str(artifact_path),
            "exists": artifact_path.exists(),
            "managed": args.managed,
            "version": secrets.token_hex(16),
            "base_sha": context.get("base_sha", ""),
            "head_sha": context.get("head_sha", ""),
            "updated_at": utc_now(),
        },
    )


def command_cancel(args: argparse.Namespace) -> None:
    directory = run_dir(args.run_id)
    atomic_write(
        directory / "control.json",
        {
            "status": "cancelled",
            "message": args.message,
            "updated_at": utc_now(),
        },
    )


def command_set_checkout(args: argparse.Namespace) -> None:
    directory = run_dir(args.run_id)
    root = tracker_root().resolve()
    checkout_path = Path(args.path).expanduser().resolve(strict=False)
    expected_path = (
        root / "checkouts" / args.run_id / "source"
    ).resolve(strict=False)
    if checkout_path != expected_path:
        raise TrackerError(
            f"Managed checkout must be exactly {expected_path}"
        )
    existing = read_json(directory / "checkout.json", required=False)
    if existing.get("status") == "active":
        existing_path = Path(existing.get("path", "")).resolve(strict=False)
        existing_source = existing.get("source_repository") or ""
        requested_source = (
            str(Path(args.source_repository).expanduser().resolve(strict=False))
            if args.source_repository
            else ""
        )
        if (
            existing_path != checkout_path
            or existing.get("kind") != args.kind
            or existing_source != requested_source
        ):
            raise TrackerError("Cannot replace an active managed checkout")
    source_repository = ""
    if args.source_repository:
        source_repository = str(
            Path(args.source_repository).expanduser().resolve(strict=False)
        )
    if args.kind == "worktree" and not source_repository:
        raise TrackerError("A worktree requires --source-repository")
    now = utc_now()
    atomic_write(
        directory / "checkout.json",
        {
            "kind": args.kind,
            "path": str(checkout_path),
            "source_repository": source_repository,
            "status": "active",
            "cleanup_attempted_at": "",
            "cleanup_error": "",
            "updated_at": now,
        },
    )


def command_release_checkout(args: argparse.Namespace) -> None:
    directory = run_dir(args.run_id)
    checkout = read_json(directory / "checkout.json")
    now = utc_now()
    atomic_write(
        directory / "checkout.json",
        {
            **checkout,
            "status": "released",
            "cleanup_attempted_at": now,
            "cleanup_error": "",
            "updated_at": now,
        },
    )


def load_named_files(directory: Path, child: str) -> list[dict[str, Any]]:
    child_directory = directory / child
    if not child_directory.exists():
        return []
    return [read_json(path) for path in sorted(child_directory.glob("*.json"))]


def derive_status(
    control: dict[str, Any],
    tasks: list[dict[str, Any]],
    latest_update: datetime,
    stale_after: timedelta,
) -> tuple[str, str | None]:
    if control.get("status") == "cancelled":
        return "cancelled", None

    states = [task.get("status", "queued") for task in tasks]
    if any(state == "blocked" for state in states):
        status = "blocked"
    elif any(state == "running" for state in states):
        status = "running"
    elif any(state == "failed" for state in states):
        status = "failed"
    elif states and all(
        state in {"completed", "skipped", "cancelled"} for state in states
    ):
        status = "completed"
    elif states and all(state == "queued" for state in states):
        status = "queued"
    else:
        status = "running"

    stale = datetime.now(timezone.utc) - latest_update > stale_after
    if stale and status == "running":
        return "potentially-stale", status
    return status, None


def load_run(directory: Path, stale_hours: float) -> dict[str, Any]:
    run = read_json(directory / "run.json")
    context = read_json(directory / "context.json", required=False)
    session = read_json(directory / "session.json", required=False)
    control = read_json(directory / "control.json", required=False)
    github = read_json(directory / "github.json", required=False)
    checkout = read_json(directory / "checkout.json", required=False)
    tasks = load_named_files(directory, "tasks")
    artifacts = load_named_files(directory, "artifacts")

    activity_timestamps = [
        value.get("updated_at") or value.get("created_at")
        for value in [run, context, session, control, checkout, *tasks, *artifacts]
        if value.get("updated_at") or value.get("created_at")
    ]
    latest_activity = max(
        (parse_time(value) for value in activity_timestamps),
        default=datetime.min.replace(tzinfo=timezone.utc),
    )
    status, underlying = derive_status(
        control, tasks, latest_activity, timedelta(hours=stale_hours)
    )
    return {
        **run,
        **context,
        "session_reference": session.get("reference", ""),
        "pr_state": github.get("state", "unknown"),
        "pr_last_checked_at": github.get("last_checked_at", ""),
        "pr_refresh_error": github.get("last_error", ""),
        "archived_at": github.get("archived_at", ""),
        "checkout": checkout,
        "control": control,
        "tasks": tasks,
        "artifacts": artifacts,
        "status": status,
        "underlying_status": underlying,
        "updated_at": latest_activity.isoformat(timespec="seconds"),
    }


def path_link(value: str) -> str:
    path = Path(value)
    try:
        return path.as_uri()
    except ValueError:
        return value


def display_text(value: Any) -> str:
    return "".join(
        character if character.isprintable() else "\N{REPLACEMENT CHARACTER}"
        for character in str(value)
    )


def format_run(run: dict[str, Any], *, detailed: bool) -> str:
    title = display_text(run.get("title") or "(title not recorded)")
    lines = [
        f"{run['owner']}/{run['repository']} PR #{run['pr_number']}: {title}",
        f"  Status: {run['status']}  Tool: {display_text(run['tool'])}",
        f"  PR state: {run['pr_state']}"
        + (
            f"  Checked: {run['pr_last_checked_at']}"
            if run.get("pr_last_checked_at")
            else "  Checked: never"
        ),
        f"  PR: {run['pr_url']}",
        f"  Run: {run['run_id']}",
        f"  Updated: {run['updated_at']}",
    ]
    if run.get("working_directory"):
        lines.append(
            f"  Working directory: {display_text(run['working_directory'])}"
        )
    if run.get("base_sha") or run.get("head_sha"):
        lines.append(
            f"  SHAs: {display_text(run.get('base_sha') or '?')} -> "
            f"{display_text(run.get('head_sha') or '?')}"
        )
    if run.get("session_reference"):
        lines.append(f"  Session: {display_text(run['session_reference'])}")
    if run.get("checkout") and (
        detailed
        or run["checkout"].get("status") == "active"
        or run["checkout"].get("cleanup_error")
    ):
        checkout = run["checkout"]
        lines.append(
            f"  Checkout: {checkout.get('status', 'unknown')} "
            f"{display_text(checkout.get('kind', 'unknown'))} "
            f"{display_text(checkout.get('path', ''))}"
        )
        if checkout.get("cleanup_error"):
            lines.append(
                f"  Checkout cleanup warning: "
                f"{display_text(checkout['cleanup_error'])}"
            )
    if run.get("pr_refresh_error"):
        lines.append(f"  PR refresh warning: {display_text(run['pr_refresh_error'])}")
    if run["artifacts"]:
        lines.append("  Artifacts:")
        for artifact in run["artifacts"]:
            exists_note = "" if artifact.get("exists") else " (missing when recorded)"
            lines.append(
                f"    - {display_text(artifact['name'])}: "
                f"{display_text(path_link(artifact['path']))}{exists_note}"
            )
    if detailed:
        lines.append("  Tasks:")
        for task in run["tasks"]:
            message = (
                f" - {display_text(task.get('message'))}"
                if task.get("message")
                else ""
            )
            lines.append(f"    - {task['task']}: {task['status']}{message}")
        control_message = run.get("control", {}).get("message")
        if control_message:
            lines.append(f"  Note: {display_text(control_message)}")
    return "\n".join(lines)


def load_all_runs(stale_hours: float) -> tuple[list[dict[str, Any]], list[str]]:
    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    for directory in (tracker_root() / "runs").iterdir():
        if not directory.is_dir():
            continue
        try:
            runs.append(load_run(directory, stale_hours))
        except TrackerError as error:
            errors.append(str(error))
    runs.sort(key=lambda item: item["created_at"], reverse=True)
    return runs, errors


def github_status(pr_url: str) -> dict[str, str]:
    executable = os.environ.get("PR_REVIEW_TRACKER_GH", "gh")
    try:
        result = subprocess.run(
            [
                executable,
                "pr",
                "view",
                pr_url,
                "--json",
                "state,closedAt,mergedAt",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise TrackerError("GitHub CLI is not available") from error
    except subprocess.TimeoutExpired as error:
        raise TrackerError(f"GitHub status check timed out for {pr_url}") from error
    except OSError as error:
        raise TrackerError(f"Could not run GitHub CLI: {error}") from error
    if result.returncode != 0:
        detail = display_text(result.stderr.strip() or result.stdout.strip())
        raise TrackerError(f"GitHub status check failed for {pr_url}: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise TrackerError(f"GitHub returned invalid status data for {pr_url}") from error
    if not isinstance(payload, dict):
        raise TrackerError(f"GitHub returned invalid status data for {pr_url}")

    merged_at = payload.get("mergedAt") or ""
    closed_at = payload.get("closedAt") or ""
    raw_state = str(payload.get("state") or "").lower()
    state = "merged" if merged_at else raw_state
    if state not in PR_STATES or state == "unknown":
        raise TrackerError(f"GitHub returned an unknown PR state for {pr_url}")
    return {
        "state": state,
        "closed_at": str(closed_at),
        "merged_at": str(merged_at),
    }


def refresh_github_states(
    refresh_after_hours: float, *, force: bool
) -> tuple[list[str], list[str]]:
    if refresh_after_hours < 0:
        raise TrackerError("Refresh threshold cannot be negative")

    now = datetime.now(timezone.utc)
    grouped: dict[str, list[Path]] = {}
    errors: list[str] = []
    for directory in (tracker_root() / "runs").iterdir():
        if not directory.is_dir():
            continue
        try:
            run = read_json(directory / "run.json")
            github = read_json(directory / "github.json", required=False)
            if github.get("state") == "merged":
                continue
            last_attempted = github.get("last_attempted_at") or github.get(
                "last_checked_at"
            )
            fresh = bool(
                last_attempted
                and now - parse_time(last_attempted)
                <= timedelta(hours=refresh_after_hours)
            )
            if force or not fresh:
                grouped.setdefault(run["pr_url"], []).append(directory)
        except (KeyError, TrackerError) as error:
            errors.append(str(error))

    updates: list[str] = []
    if not grouped:
        return updates, errors

    max_workers = min(4, len(grouped))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(github_status, pr_url): pr_url for pr_url in grouped
        }
        for future in concurrent.futures.as_completed(futures):
            pr_url = futures[future]
            try:
                result = future.result()
            except TrackerError as error:
                errors.append(str(error))
                attempted = utc_now()
                for directory in grouped[pr_url]:
                    previous = read_json(directory / "github.json", required=False)
                    atomic_write(
                        directory / "github.json",
                        {
                            **previous,
                            "last_attempted_at": attempted,
                            "last_error": "The last GitHub status refresh failed.",
                            "updated_at": attempted,
                        },
                    )
                continue

            checked = utc_now()
            for directory in grouped[pr_url]:
                previous = read_json(directory / "github.json", required=False)
                previous_state = previous.get("state", "unknown")
                archived_at = previous.get("archived_at", "")
                if result["state"] in {"closed", "merged"}:
                    archived_at = archived_at or checked
                elif result["state"] == "open":
                    archived_at = ""
                atomic_write(
                    directory / "github.json",
                    {
                        **result,
                        "archived_at": archived_at,
                        "last_checked_at": checked,
                        "last_attempted_at": checked,
                        "last_error": "",
                        "updated_at": checked,
                    },
                )
                if previous_state != result["state"]:
                    run = read_json(directory / "run.json")
                    updates.append(
                        f"{run['run_id']}: {previous_state} -> {result['state']}"
                    )
    return updates, errors


def print_warnings(errors: list[str]) -> None:
    if errors:
        print("\nWarnings:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def save_checkout_state(
    directory: Path,
    checkout: dict[str, Any],
    *,
    status: str,
    error: str,
) -> None:
    now = utc_now()
    atomic_write(
        directory / "checkout.json",
        {
            **checkout,
            "status": status,
            "cleanup_attempted_at": now,
            "cleanup_error": error,
            "updated_at": now,
        },
    )


def remove_managed_checkout(directory: Path) -> str | None:
    checkout = read_json(directory / "checkout.json", required=False)
    if not checkout or checkout.get("status") != "active":
        return None

    run = read_json(directory / "run.json")
    expected_root = (
        tracker_root().resolve() / "checkouts" / run["run_id"]
    ).resolve(strict=False)
    recorded_path = Path(
        os.path.abspath(Path(checkout.get("path", "")).expanduser())
    )
    resolved_path = recorded_path.resolve(strict=False)
    if (
        not checkout.get("path")
        or recorded_path.is_symlink()
        or not is_within(recorded_path, expected_root)
        or not is_within(resolved_path, expected_root)
    ):
        error = "Refused cleanup because the checkout path is not safely owned."
        save_checkout_state(directory, checkout, status="active", error=error)
        return error

    kind = checkout.get("kind")
    if kind == "clone":
        try:
            if recorded_path.exists():
                if not recorded_path.is_dir():
                    raise TrackerError("Managed clone path is not a directory")
                shutil.rmtree(recorded_path)
        except (OSError, TrackerError) as error:
            message = f"Could not remove managed clone: {display_text(error)}"
            save_checkout_state(directory, checkout, status="active", error=message)
            return message
        try:
            expected_root.rmdir()
        except OSError:
            pass
        save_checkout_state(directory, checkout, status="released", error="")
        return None

    if kind != "worktree":
        error = f"Refused cleanup for unknown checkout kind: {display_text(kind)}"
        save_checkout_state(directory, checkout, status="active", error=error)
        return error

    source_text = checkout.get("source_repository")
    if not source_text:
        error = "Refused worktree cleanup without a source repository."
        save_checkout_state(directory, checkout, status="active", error=error)
        return error
    source_repository = Path(source_text).expanduser().resolve(strict=False)
    executable = os.environ.get("PR_REVIEW_TRACKER_GIT", "git")
    try:
        listing = subprocess.run(
            [executable, "-C", str(source_repository), "worktree", "list", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        message = f"Could not inspect managed worktree: {display_text(error)}"
        save_checkout_state(directory, checkout, status="active", error=message)
        return message
    if listing.returncode != 0:
        detail = display_text(listing.stderr.strip() or "git worktree list failed")
        message = f"Could not inspect managed worktree: {detail}"
        save_checkout_state(directory, checkout, status="active", error=message)
        return message

    listed_paths = {
        Path(line.removeprefix("worktree ")).resolve(strict=False)
        for line in listing.stdout.splitlines()
        if line.startswith("worktree ")
    }
    if resolved_path not in listed_paths:
        if not recorded_path.exists():
            save_checkout_state(directory, checkout, status="released", error="")
            return None
        error = "Refused cleanup because Git does not recognize the managed worktree."
        save_checkout_state(directory, checkout, status="active", error=error)
        return error

    try:
        removal = subprocess.run(
            [
                executable,
                "-C",
                str(source_repository),
                "worktree",
                "remove",
                str(recorded_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        message = f"Could not remove managed worktree: {display_text(error)}"
        save_checkout_state(directory, checkout, status="active", error=message)
        return message
    if removal.returncode != 0:
        detail = display_text(removal.stderr.strip() or "git worktree remove failed")
        message = f"Could not remove managed worktree without force: {detail}"
        save_checkout_state(directory, checkout, status="active", error=message)
        return message

    try:
        expected_root.rmdir()
    except OSError:
        pass
    save_checkout_state(directory, checkout, status="released", error="")
    return None


def cleanup_archived_checkouts(*, force: bool) -> tuple[list[str], list[str]]:
    now = datetime.now(timezone.utc)
    released: list[str] = []
    errors: list[str] = []
    for directory in (tracker_root() / "runs").iterdir():
        if not directory.is_dir():
            continue
        try:
            run = read_json(directory / "run.json")
            github = read_json(directory / "github.json", required=False)
            checkout = read_json(directory / "checkout.json", required=False)
            if not github.get("archived_at") or checkout.get("status") != "active":
                continue
            last_attempt = checkout.get("cleanup_attempted_at")
            if (
                not force
                and last_attempt
                and now - parse_time(last_attempt) <= timedelta(hours=1)
            ):
                if checkout.get("cleanup_error"):
                    errors.append(
                        f"{run['run_id']}: {checkout['cleanup_error']}"
                    )
                continue
            error = remove_managed_checkout(directory)
            if error:
                errors.append(f"{run['run_id']}: {error}")
            else:
                released.append(run["run_id"])
        except (KeyError, TrackerError) as error:
            errors.append(f"Could not inspect checkout {directory.name}: {error}")
    return released, errors


def purge_archived(
    retention_days: float, *, dry_run: bool
) -> tuple[list[str], list[str]]:
    if retention_days < 0:
        raise TrackerError("Retention period cannot be negative")

    root = tracker_root().resolve()
    runs_root = root / "runs"
    allowed_artifact_roots = (
        root,
        (Path.home() / ".local" / "share" / "explain-diff").resolve(),
    )
    now = datetime.now(timezone.utc)
    directories = [path for path in runs_root.iterdir() if path.is_dir()]
    errors: list[str] = []
    records: list[
        tuple[Path, dict[str, Any], dict[str, Any], list[dict[str, Any]]]
    ] = []

    for directory in directories:
        try:
            records.append(
                (
                    directory,
                    read_json(directory / "run.json"),
                    read_json(directory / "github.json", required=False),
                    load_named_files(directory, "artifacts"),
                )
            )
        except (KeyError, TrackerError) as error:
            errors.append(str(error))

    if errors:
        errors.append(
            "Retention cleanup was skipped because the registry could not be "
            "fully inspected."
        )
        return [], errors

    eligible: list[
        tuple[Path, dict[str, Any], dict[str, Any], list[dict[str, Any]]]
    ] = []
    for record in records:
        directory, _, github, _ = record
        try:
            archived_at = github.get("archived_at")
            expired = (
                github.get("state") in {"closed", "merged"}
                and archived_at
                and now - parse_time(archived_at)
                >= timedelta(days=retention_days)
            )
            if not expired:
                continue
            checkout = read_json(directory / "checkout.json", required=False)
            if checkout.get("status") == "active":
                errors.append(
                    f"Retained {directory.name} because checkout cleanup is pending."
                )
                continue
            eligible.append(record)
        except TrackerError as error:
            errors.append(f"Could not evaluate {directory.name}: {error}")

    eligible_directories = {record[0] for record in eligible}
    surviving_references: set[Path] = set()
    for directory, _, _, artifacts in records:
        if directory in eligible_directories:
            continue
        for artifact in artifacts:
            try:
                artifact_path = Path(
                    os.path.abspath(Path(artifact["path"]).expanduser())
                ).resolve(strict=False)
                surviving_references.add(artifact_path)
            except KeyError as error:
                errors.append(f"Malformed artifact in {directory.name}: {error}")

    purged: list[str] = []
    for directory, run, _, artifacts in eligible:
        try:
            for artifact in artifacts:
                if not artifact.get("managed"):
                    continue
                recorded_path = Path(
                    os.path.abspath(Path(artifact["path"]).expanduser())
                )
                artifact_path = recorded_path.resolve(strict=False)
                if is_within(recorded_path, directory.resolve()):
                    continue
                allowed = any(
                    is_within(recorded_path, allowed_root)
                    and is_within(artifact_path, allowed_root)
                    for allowed_root in allowed_artifact_roots
                )
                shared = artifact_path in surviving_references
                if recorded_path.is_symlink():
                    errors.append(
                        f"Refused to delete managed artifact through symlink: "
                        f"{recorded_path}"
                    )
                elif allowed and not shared and recorded_path.is_file():
                    if not dry_run:
                        recorded_path.unlink()
                elif recorded_path.exists() and not allowed:
                    errors.append(
                        f"Refused to delete managed artifact outside approved roots: "
                        f"{recorded_path}"
                    )

            purged.append(run["run_id"])
            if not dry_run:
                shutil.rmtree(directory)
        except (KeyError, OSError, TrackerError) as error:
            errors.append(f"Could not purge {directory.name}: {error}")
    return purged, errors


def command_refresh(args: argparse.Namespace) -> None:
    updates, errors = refresh_github_states(0, force=True)
    released, checkout_errors = cleanup_archived_checkouts(force=True)
    purged, purge_errors = purge_archived(30, dry_run=False)
    if updates:
        print("\n".join(updates))
    else:
        print("No PR state changes detected.")
    if purged:
        print("Purged expired runs: " + ", ".join(purged))
    if released:
        print("Removed archived checkouts: " + ", ".join(released))
    print_warnings([*errors, *checkout_errors, *purge_errors])


def command_purge(args: argparse.Namespace) -> None:
    checkout_errors: list[str] = []
    if not args.dry_run:
        _, checkout_errors = cleanup_archived_checkouts(force=True)
    purged, errors = purge_archived(args.retention_days, dry_run=args.dry_run)
    verb = "Would purge" if args.dry_run else "Purged"
    if purged:
        print(f"{verb}: " + ", ".join(purged))
    else:
        print("No expired archived runs.")
    print_warnings([*checkout_errors, *errors])


def command_list(args: argparse.Namespace) -> None:
    if args.stale_after_hours < 0:
        raise TrackerError("Stale threshold cannot be negative")
    refresh_errors: list[str] = []
    if not args.no_refresh:
        _, refresh_errors = refresh_github_states(
            args.refresh_after_hours, force=False
        )
    _, checkout_errors = cleanup_archived_checkouts(force=False)
    _, purge_errors = purge_archived(30, dry_run=False)
    runs, errors = load_all_runs(args.stale_after_hours)
    cached_refresh_errors = sorted(
        {
            f"{run['pr_url']}: {run['pr_refresh_error']}"
            for run in runs
            if run.get("pr_refresh_error")
        }
    )
    if args.status == "open":
        runs = [
            run
            for run in runs
            if run["status"] != "cancelled" and not run.get("archived_at")
        ]
    elif args.status != "all":
        runs = [run for run in runs if run["status"] == args.status]

    all_errors = [
        *refresh_errors,
        *cached_refresh_errors,
        *checkout_errors,
        *purge_errors,
        *errors,
    ]
    if args.json:
        print(json.dumps({"runs": runs, "errors": all_errors}, indent=2))
        return
    if not runs:
        print("No matching PR review runs.")
    else:
        print("\n\n".join(format_run(run, detailed=False) for run in runs))
    print_warnings(all_errors)


def command_show(args: argparse.Namespace) -> None:
    if args.stale_after_hours < 0:
        raise TrackerError("Stale threshold cannot be negative")
    run = load_run(run_dir(args.run_id), args.stale_after_hours)
    if args.json:
        print(json.dumps(run, indent=2))
    else:
        print(format_run(run, detailed=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="Register a review run")
    start.add_argument("--pr-url", required=True)
    start.add_argument("--tool", required=True)
    start.add_argument("--session-reference", default="")
    start.add_argument("--working-directory")
    start.add_argument("--title", default="")
    start.add_argument("--base-sha", default="")
    start.add_argument("--head-sha", default="")
    start.set_defaults(handler=command_start)

    context = commands.add_parser("set-context", help="Update verified PR context")
    context.add_argument("--run-id", required=True)
    context.add_argument("--title")
    context.add_argument("--base-sha")
    context.add_argument("--head-sha")
    context.set_defaults(handler=command_set_context)

    session = commands.add_parser("set-session", help="Record a session link or ID")
    session.add_argument("--run-id", required=True)
    session.add_argument("--reference", required=True)
    session.set_defaults(handler=command_set_session)

    task = commands.add_parser("set-task", help="Update one review task")
    task.add_argument("--run-id", required=True)
    task.add_argument("--task", required=True)
    task.add_argument("--status", choices=TASK_STATUSES, required=True)
    task.add_argument("--message", default="")
    task.set_defaults(handler=command_set_task)

    artifact = commands.add_parser("add-artifact", help="Attach a local artifact")
    artifact.add_argument("--run-id", required=True)
    artifact.add_argument("--name", required=True)
    artifact.add_argument("--kind", default="file")
    artifact.add_argument("--path", required=True)
    artifact.add_argument(
        "--managed",
        action="store_true",
        help="Allow retention cleanup to delete this generated artifact",
    )
    artifact.set_defaults(handler=command_add_artifact)

    cancel = commands.add_parser("cancel", help="Mark a run cancelled")
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--message", default="")
    cancel.set_defaults(handler=command_cancel)

    checkout = commands.add_parser(
        "set-checkout", help="Record a workflow-owned checkout"
    )
    checkout.add_argument("--run-id", required=True)
    checkout.add_argument("--kind", choices=("worktree", "clone"), required=True)
    checkout.add_argument("--path", required=True)
    checkout.add_argument("--source-repository")
    checkout.set_defaults(handler=command_set_checkout)

    release_checkout = commands.add_parser(
        "release-checkout", help="Mark a checkout as already removed"
    )
    release_checkout.add_argument("--run-id", required=True)
    release_checkout.set_defaults(handler=command_release_checkout)

    refresh = commands.add_parser("refresh", help="Force-refresh GitHub PR states")
    refresh.set_defaults(handler=command_refresh)

    purge = commands.add_parser("purge", help="Purge expired archived runs")
    purge.add_argument("--retention-days", type=float, default=30.0)
    purge.add_argument("--dry-run", action="store_true")
    purge.set_defaults(handler=command_purge)

    list_command = commands.add_parser("list", help="List review runs")
    list_command.add_argument(
        "--status",
        default="open",
        choices=(
            "open",
            "all",
            "queued",
            "running",
            "potentially-stale",
            "blocked",
            "failed",
            "completed",
            "cancelled",
        ),
    )
    list_command.add_argument("--stale-after-hours", type=float, default=6.0)
    list_command.add_argument("--refresh-after-hours", type=float, default=1.0)
    list_command.add_argument("--no-refresh", action="store_true")
    list_command.add_argument("--json", action="store_true")
    list_command.set_defaults(handler=command_list)

    show = commands.add_parser("show", help="Show one review run")
    show.add_argument("--run-id", required=True)
    show.add_argument("--stale-after-hours", type=float, default=6.0)
    show.add_argument("--json", action="store_true")
    show.set_defaults(handler=command_show)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except TrackerError as error:
        parser.exit(2, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
