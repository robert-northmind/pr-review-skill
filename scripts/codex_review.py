"""Codex app-server adapter: SDK setup, prompt context, and public activity.

Only this module knows the Codex protocol. Raw commands, tool output and
reasoning events are intentionally excluded from dashboard activity.
"""
from pathlib import Path
import sys
import pr_review_tracker as tracker

SKILL = Path(__file__).resolve().parent.parent


def create_client(approval_handler):
    # Optional dependency: the dashboard still starts without the Codex SDK.
    from openai_codex.client import CodexClient, CodexConfig
    return CodexClient(CodexConfig(
        cwd=str(tracker.tracker_root()),
        client_name='pr_review_dashboard',
        client_title='PR review',
        config_overrides=('features.multi_agent=true',),
    ), approval_handler=approval_handler)


def thread_parameters(job):
    params = {
        'cwd': str(tracker.tracker_root()),
        'sandbox': 'workspace-write',
        'approvalPolicy': 'on-request',
        'approvalsReviewer': 'auto_review',
    }
    if job.get('model'):
        params['model'] = job['model']
    return params


def review_prompt(run_id, prompt):
    import shlex
    cli = shlex.join([sys.executable, str(SKILL / 'scripts/pr_review_tracker.py')])
    root = tracker.tracker_root()
    return f'''{prompt}

Dashboard execution context:
Read and follow {SKILL}/SKILL.md and its references, including reviewer allocation.
Use THIS skill checkout and its scripts, not another installed pr-review version.
PR_REVIEW_TRACKER_HOME={root} is the registry for this review. All run artifacts and
checkouts go beneath that root, even if a reference shows the default root.
Run ID: {run_id}. Do not create another run. The backend records your session ID.

Progress is part of the review deliverable. Give brief commentary when a stage
starts, when a meaningful checkpoint finishes, or a blocker appears. During long
work, aim for an update about every 30–60 seconds when there is new information.
Do not interrupt useful work merely to emit a timer update.
Give each reviewer its tracker task and ask it to update its own task directly
at checkpoints and before returning. The lead keeps explanation, synthesis,
drafts and report current. Reconcile reviewer updates in your own commentary.
After inventorying a task, report real completed/total file groups or checks:
{cli} set-task --run-id {run_id} --task correctness-review --status running --completed-units 2 --total-units 8 --unit 'file groups' --message 'Checked request parsing; tracing error handling next'
The numbers above are an example, not actual progress. Use your actual inventory.
Use the same flags for other tasks. Mark each completed/skipped/blocked honestly;
when skipping validation, explain the gap. Do not estimate elapsed time, invent
percentages, count tool calls as completed work, or mark the report done early.
Progress messages must be short and nonsensitive, without source excerpts,
credentials, raw command output or speculative defect claims.
The existing review.html remains the final deliverable. Register it and finish
all task states. Do not publish anything to GitHub.
'''


def record_notification(activity, method, payload):
    if method in ('item/started', 'item/completed'):
        item = payload.get('item', {})
        kind = item.get('type', '')
        done = method.endswith('completed')
        if kind == 'agentMessage' and done:
            activity.emit('update', item.get('text', ''))
        elif kind == 'commandExecution':
            activity.emit('tool', 'Command finished' if done else 'Running a command')
        elif kind in ('mcpToolCall', 'webSearch', 'collabAgentToolCall'):
            activity.emit('tool', {'mcpToolCall': 'Tool call', 'webSearch': 'Web search',
                'collabAgentToolCall': 'Reviewer activity'}[kind] + (' finished' if done else ' started'))
    elif method == 'turn/plan/updated':
        activity.emit('plan', '\n'.join(f"{p.get('status', '')}: {p.get('step', '')}" for p in payload.get('plan', [])))
