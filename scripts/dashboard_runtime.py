"""Local dashboard state, artifact history, and durable launches."""
from __future__ import annotations
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import threading
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import dashboard_queue as queue
import dashboard_reviews as codex

ARTIFACT_NAMES = ('review-html', 'explanation-html', 'review-markdown')
TERMINAL = {'completed', 'completed-with-gaps', 'failed', 'blocked', 'cancelled'}


def artifact_allowed(path):
    try:
        path = Path(path).resolve(strict=True)
        return path.is_file() and any(path.is_relative_to(root) for root in (
            tracker.tracker_root().resolve(), dashboard.explainer_output_root()))
    except (OSError, ValueError):
        return False


def artifact_version(artifact):
    # Legacy registrations have no version ID. Keep a stable identity until
    # they are registered again, including replacements at the same path.
    return artifact.get('version') or hashlib.sha256(
        json.dumps(artifact, sort_keys=True).encode()).hexdigest()


def mark_artifact_opened(run_id, name, version):
    if name not in ARTIFACT_NAMES or not isinstance(version, str) or not version:
        raise dashboard.DashboardError('Unknown artifact version.')
    with dashboard.state_lock():
        directory = tracker.run_dir(run_id)
        tracker.read_json(directory / 'run.json')
        artifact = tracker.read_json(directory / 'artifacts' / f'{name}.json', required=False)
        if not artifact or artifact_version(artifact) != version or not artifact_allowed(artifact.get('path', '')):
            # An old tab must never acknowledge a replacement it did not open.
            return {'opened': False}
        path = directory / 'artifact-views.json'
        views = tracker.read_json(path, required=False)
        views[name] = version
        tracker.atomic_write(path, views)
    return {'opened': True}


def collect_artifacts(runs, checked_sha=''):
    """Prefer completed artifacts, even while other tasks are still running."""
    candidates = []
    ordered = sorted(runs, key=lambda r:r.get('created_at', ''), reverse=True)
    for run in ordered:
        views = tracker.read_json(tracker.run_dir(run['run_id']) / 'artifact-views.json', required=False)
        tasks = {task['task']: task['status'] for task in run.get('tasks', [])}
        for artifact in run.get('artifacts', []):
            name, path = artifact.get('name'), artifact.get('path', '')
            if name not in ARTIFACT_NAMES or not artifact_allowed(path):
                continue
            task = {'review-html':'report', 'explanation-html':'explainer', 'review-markdown':'drafts'}[name]
            ready = run.get('status') == 'completed' or tasks.get(task) == 'completed'
            head = artifact.get('head_sha', run.get('head_sha', ''))
            version = artifact_version(artifact)
            candidates.append((ready, {'name': name, 'path': path, 'run_id': run['run_id'],
                'version': version, 'unread': views.get(name) != version,
                'freshness': 'unknown' if not head or not checked_sha else ('current' if head == checked_sha else 'older'),
                'created_at': artifact.get('updated_at') or run.get('created_at', ''), 'head_sha': head,
                'status': 'completed' if ready else run.get('status'), 'tool': run.get('tool', '')}))
    chosen = {}
    # Partial results only fill missing artifact types. A new unfinished
    # explainer must not hide the previous finished explanation.
    for _, artifact in sorted(candidates, key=lambda item: not item[0]):
        chosen.setdefault(artifact['name'], artifact)
    if 'review-html' in chosen:
        combined = chosen['review-html']
        if combined['status'] == 'completed' or not any(a['status'] == 'completed' for name, a in chosen.items() if name != 'review-html'):
            return {'review-html': combined}
        del chosen['review-html']
    return chosen


def launch_path(run_id):
    return tracker.run_dir(run_id) / 'dashboard-launch.json'


def age_seconds(stamp):
    try:
        return (datetime.now(timezone.utc) - tracker.parse_time(stamp)).total_seconds()
    except (ValueError, TypeError):
        return 0


def summarize_run(run, checked_sha=''):
    launch = tracker.read_json(launch_path(run['run_id']), required=False)
    status = run['status']
    if launch.get('exit_code') is not None and status not in TERMINAL:
        status = 'failed'
    elif status == 'queued':
        status = 'starting' if age_seconds(run['created_at']) < 180 else 'no-activity'
    elif status == 'potentially-stale':
        status = 'no-activity'
    job = codex.job_state(run['run_id']) if launch.get('transport') == 'codex-sdk' else {}
    if job:
        status = job['status']
    return {'run_id': run['run_id'], 'status': status, 'tool': run.get('tool', ''),
        'created_at': run.get('created_at', ''), 'updated_at': run.get('updated_at', ''),
        'head_sha': run.get('head_sha', ''), 'session_reference': run.get('session_reference', ''),
        'kind': launch.get('kind', 'review'), 'transport': launch.get('transport', 'terminal'),
        'progress': codex.progress(run, status) if job else None,
        'message': job.get('message', '') or launch.get('message', '') or run.get('control', {}).get('message', ''),
        'tasks': [{'name': t['task'], 'status': t['status'], 'message': t.get('message', '')} for t in run.get('tasks', [])],
        'artifacts': collect_artifacts([run], checked_sha)}


def snapshot():
    with dashboard.state_lock():
        data = dashboard.load_dashboard()
        config = dashboard.load_config()
        personal = queue.load()
        entries = queue.merged_entries(data['prs'], personal)
    import dashboard_triage
    triage = dashboard_triage.snapshot(entries)
    runs, errors = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
    grouped = {}
    for run in runs:
        grouped.setdefault(run['pr_url'], []).append(run)
    prs = []
    for url, entry in entries.items():
        history = grouped.get(url, [])
        checked_sha = entry.get('head_sha', '')
        artifacts = collect_artifacts(history, checked_sha)
        reasons = entry.get('reasons', [])
        group = 'mine' if 'author' in reasons else ('requested' if any(r in reasons for r in ('review-requested', 'assignee')) else 'watching')
        state = entry.get('my_review_state', '')
        participation = {'APPROVED':'Approved', 'CHANGES_REQUESTED':'Changes requested',
            'COMMENTED':'Commented in review', 'DISMISSED':'Review dismissed'}.get(state, '')
        if not participation:
            participation = 'Commented' if entry.get('my_comment_at') else (
                'Previous activity · refresh to classify' if entry.get('reviewed_by_me_at') and 'my_review_state' not in entry else 'Not reviewed')
        freshness = 'unknown'
        if artifacts and checked_sha:
            heads = [a['head_sha'] for a in artifacts.values()]
            if any(head and head != checked_sha for head in heads):
                freshness = 'older'
            elif all(heads):
                freshness = 'current'
        mixed = len({a['run_id'] for a in artifacts.values()}) > 1
        login = dashboard.normalize_author_login(entry.get('author_login', ''))
        profile = data.get('author_profiles', {}).get(login, {})
        prs.append({**entry, 'author_login': login, 'author_name': profile.get('author_name', ''),
                    'author_avatar_url': profile.get('author_avatar_url', ''), 'url': url, 'group':group, 'participation':participation,
            'triage':triage['prs'].get(url, {}), 'artifacts':artifacts, 'artifact_freshness':freshness, 'mixed_artifacts':mixed,
            'run':summarize_run(history[0], checked_sha) if history else None,
            'history':[summarize_run(r, checked_sha) for r in history],
            'history_total':len(history)})
    return {'prs':prs, 'config':config, 'triage': {k: v for k, v in triage.items() if k != 'prs'}, 'queue_refresh':queue.status(),
        'last_github_refresh_at':data.get('last_github_refresh_at', ''),
        'last_refresh_attempt_at':data.get('last_refresh_attempt_at', ''),
        'warnings':data.get('refresh_warnings', []) + errors,
        'refresh':tracker.read_json(tracker.tracker_root()/'dashboard-refresh.json',required=False),
        'models':{'claude':dashboard.discover_claude_options()[0], 'codex':dashboard.CODEX_MODELS},
        'efforts':{'claude':dashboard.discover_claude_options()[1], 'codex':dashboard.CODEX_EFFORTS},
        'model_efforts': {'codex': dashboard.CODEX_MODEL_EFFORTS}}


def start_launch(url, kind, retry=False):
    canonical, *_ = tracker.canonical_pr_url(url)
    if kind not in ('review', 'explainer'):
        raise dashboard.DashboardError('Unknown review action.')
    # Old open tabs may still send the retired action; perform a full review.
    kind = 'review'
    with dashboard.state_lock():
        entry = queue.merged_entries(dashboard.load_dashboard()['prs']).get(canonical)
        if entry is None:
            raise dashboard.DashboardError('This PR is no longer in the inbox. Refresh the page.')
        runs, errors = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
        active = [r for r in runs if r['pr_url'] == canonical and
                  (summarize_run(r)['status'] not in TERMINAL or
                   (codex.read_job(r['run_id']) and codex.worker_alive(r['run_id'])))]
        if active and not retry:
            return {'run_id': active[0]['run_id'], 'existing': True,
                    'transport': summarize_run(active[0])['transport']}
        if active and retry:
            for run in active:
                if codex.read_job(run['run_id']):
                    raise dashboard.DashboardError('Stop the active Codex review and wait for it to finish before retrying.')
                tracker.command_cancel(Namespace(run_id=run['run_id'], message='Tracking released for an explicit retry; terminal is not terminated.'))
        config = dashboard.load_config()
        run_id = tracker.command_start(Namespace(pr_url=canonical,
            tool='codex' if config['agent']=='codex' else 'claude-code',
            title=entry.get('title',''), working_directory=str(tracker.tracker_root()),
            session_reference='', base_sha='', head_sha=''), emit=False)
        transport = 'codex-sdk' if config['agent'] == 'codex' else 'terminal'
        meta = {'kind':kind, 'agent':config['agent'], 'transport':transport, 'created_at':tracker.utc_now(), 'message':''}
        tracker.atomic_write(launch_path(run_id), meta)
        prompt = dashboard.full_review_prompt(canonical)
        prompt += ('\n\nThe dashboard has already registered this exact run. '
            f'Use run ID {run_id} for every tracker command; do not create another run. '
            'Read the installed skill instructions before proceeding. '
            'Update checkout, explanation, review, and report tasks as you work. '
            'Record a session reference when available; otherwise leave it blank without asking. '
            'This request authorizes the complete local review workflow and its local artifacts, '
            'not posting anything to GitHub.')
        try:
            if transport == 'codex-sdk':
                codex.start(run_id, prompt, config)
            else:
                dashboard.open_interactive_terminal(prompt, run_id=run_id)
        except (OSError, dashboard.DashboardError) as error:
            _record_exit(run_id, 1, str(error))
            raise dashboard.DashboardError(str(error)) from error
    if kind == 'review' and not entry.get('workflow'):
        queue.mutate(canonical, 'enqueue')
    return {'run_id':run_id, 'existing':False, 'transport':transport}


def _record_exit(run_id, code, message=''):
    run = tracker.load_run(tracker.run_dir(run_id), dashboard.STALE_RUN_HOURS)
    meta = tracker.read_json(launch_path(run_id),required=False)
    if not meta:
        raise dashboard.DashboardError('This run was not launched by the dashboard.')
    meta.update(exit_code=code, exited_at=tracker.utc_now())
    if run['status'] not in TERMINAL:
        meta['message'] = message or f'Terminal session ended (exit {code}) before the run completed. Close any remaining session before retrying.'
        for task in run['tasks']:
            if task['status'] in ('queued','running'):
                tracker.command_set_task(Namespace(run_id=run_id, task=task['task'], status='failed',message=meta['message']))
    tracker.atomic_write(launch_path(run_id),meta)


def record_launch_exit(run_id, code):
    with dashboard.state_lock():
        _record_exit(run_id, code)


_refresh_guard = threading.Lock()


def start_refresh():
    if not _refresh_guard.acquire(blocking=False):
        return False
    status_path = tracker.tracker_root()/'dashboard-refresh.json'
    tracker.atomic_write(status_path, {'status':'running','started_at':tracker.utc_now()})
    def worker():
        try:
            dashboard.command_refresh(Namespace())
            tracker.atomic_write(status_path, {'status':'completed','finished_at':tracker.utc_now()})
        except Exception as error:
            tracker.atomic_write(status_path, {'status':'failed','finished_at':tracker.utc_now(),'message':str(error)})
        finally:
            _refresh_guard.release()
    threading.Thread(target=worker,daemon=True).start()
    return True
