"""Copyable commands and prompts for continuing a finished review elsewhere.

Both agents keep review transcripts on disk. Continuing forks the session, so a
new conversation never writes into (or waits for) the original review thread.
"""
import json
import os
from pathlib import Path
import re
import shlex

import pr_review_tracker as tracker

SESSION_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
AGENTS = {'claude-code': 'Claude Code', 'codex': 'Codex'}
FINAL = frozenset({'completed', 'completed-with-gaps', 'failed', 'cancelled', 'blocked'})
RUN_FILES = ('review.md', 'verification.md', 'context.json', 'discussion.md')
CWD_SCAN_LINES = 50


def claude_transcript(session_id):
    home = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
    return next(iter(sorted((home / 'projects').glob(f'*/{session_id}.jsonl'))), None)


def codex_transcript(session_id):
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    return next((path for pattern in (f'sessions/*/*/*/rollout-*-{session_id}.jsonl',
                                      f'archived_sessions/rollout-*-{session_id}.jsonl')
                 for path in sorted(home.glob(pattern))), None)


def recorded_cwd(transcript):
    """Both formats record the session's working directory near the start."""
    try:
        with transcript.open(encoding='utf-8') as handle:
            for _, line in zip(range(CWD_SCAN_LINES), handle):
                entry = json.loads(line)
                cwd = entry.get('cwd') or (entry.get('payload') or {}).get('cwd')
                if isinstance(cwd, str) and os.path.isabs(cwd) and Path(cwd).is_dir():
                    return cwd
    except (OSError, ValueError, AttributeError):
        pass
    return ''


def handoff_prompt(run, label, session_id, transcript):
    directory = tracker.run_dir(run['run_id'])
    lines = [f"Pick up where an earlier {label} review of {run['pr_url']} left off.",
             f'Session ID: {session_id}',
             f'Transcript: {transcript} (large JSONL; search it instead of reading all of it)']
    present = [name for name in RUN_FILES if (directory / name).is_file()]
    if present:
        lines.append(f'Start with the review notes in {directory}: {", ".join(present)}.')
    return '\n'.join(lines)


def continuation(run, status):
    """Commands for a finished run's session, or None when none can be offered."""
    label = AGENTS.get(run.get('tool', ''))
    session_id = run.get('session_reference', '')
    if not label or status not in FINAL or not SESSION_ID.fullmatch(session_id):
        return None
    claude = run['tool'] == 'claude-code'
    transcript = (claude_transcript if claude else codex_transcript)(session_id)
    if not transcript:
        return {'agent': label, 'session_id': session_id,
                'unavailable': f'The {label} transcript for this review is no longer on disk.'}
    cwd = recorded_cwd(transcript) or str(tracker.tracker_root())
    # Claude finds sessions by working directory; Codex finds them anywhere.
    command = (f'cd {shlex.quote(cwd)} && claude --resume {session_id} --fork-session' if claude
               else f'codex fork -C {shlex.quote(cwd)} {session_id}')
    return {'agent': label, 'session_id': session_id, 'command': command, 'transcript': str(transcript),
            'prompt': handoff_prompt(run, label, session_id, transcript)}
