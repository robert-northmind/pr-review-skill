"""Codex app-server adapter: SDK setup, prompt context, and public activity.

Only this module knows the Codex protocol. Raw commands, tool output and
reasoning events are intentionally excluded from dashboard activity.
"""
import pr_review_tracker as tracker


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
        'cwd': job.get('cwd') or str(tracker.tracker_root()),
        'sandbox': 'workspace-write',
        'approvalPolicy': 'on-request',
        'approvalsReviewer': 'auto_review',
    }
    if job.get('model'):
        params['model'] = job['model']
    return params



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
