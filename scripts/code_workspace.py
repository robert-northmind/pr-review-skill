"""Workspace application service shared by HTTP handlers and tests."""
import dashboard_runtime as runtime
import pr_dashboard as dashboard
import pr_review_tracker as tracker
import workspace_github as github
import workspace_store as store
import workspace_chat as chat
import ai_settings
import review_continuation


def review(url, head):
    runs, _ = tracker.load_all_runs(dashboard.STALE_RUN_HOURS)
    runs = [r for r in runs if r['pr_url'] == url]
    artifacts = runtime.collect_artifacts(runs, head)
    artifact = artifacts.get('review-html') or artifacts.get('review-markdown')
    latest = max(runs, key=lambda r: r.get('created_at', ''), default=None)
    # Continue the session that wrote the shown report, not a newer failed run.
    source = next((r for r in runs if artifact and r['run_id'] == artifact['run_id']), None)
    return {'artifact': artifact, 'run': runtime.summarize_run(latest, head) if latest else None,
            'continuation': review_continuation.continuation(
                source, runtime.summarize_run(source)['status']) if source else None}


def load(url, rev=None):
    comparison = github.cached(url, rev) if rev else github.manifest(url)
    private = store.read(url) if rev else store.reconcile(url, comparison)
    return {**comparison, 'chat_config': ai_settings.selected('chat'), 'saved': {**private, 'viewed': [f['path'] for f in comparison['files'] if private['viewed'].get(f['path']) == f['fingerprint']], 'threads': chat.conversations(url)},
            'review': review(comparison['url'], comparison['head'])}


def save(url, request):
    comparison = github.cached(url, request.get('revision'))
    state = store.save(url, comparison, request)
    return {'version': state['version']}
