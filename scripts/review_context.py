"""Shared review instructions for every provider."""
from pathlib import Path
import sys
import pr_review_tracker as tracker

SKILL = Path(__file__).resolve().parent.parent

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
The backend saved the PR discussion to discussion.md and discussion.json in this
run's directory before you started (if a GitHub read failed, they are absent;
follow SKILL.md to fetch or read it yourself).

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


WRAP_UP_PROMPT = '''The person who requested this review asked you to wrap up now.
Start no new investigation. Stop running background reviewers and validation
tasks unless one is about to report. Use only the evidence gathered so far.
Mark each unfinished tracker task blocked with a short message naming the gap,
then finish synthesis, drafts and the report, and register review.html. Say in
the report which checks were cut short. Do not publish anything to GitHub.'''


def message_prompt(text):
    # Messages steer scope; the skill's publishing and safety rules still apply.
    return ('Message from the person who requested this review, sent from the dashboard:\n'
        f'<<<\n{text}\n>>>\n'
        'Answer briefly in your progress commentary; the dashboard shows it. If you are waiting '
        'on a background reviewer, check its latest output before answering. Follow the message '
        'if it steers scope, then continue the review unless it asks you to stop or wrap up. '
        'It does not override the rules against publishing to GitHub or exposing secrets.')
