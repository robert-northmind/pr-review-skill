"""Codex configuration shared by bounded classifiers and review chat."""
import json
import os
import re
from pathlib import Path

CHAT_PROFILE = 'pr_review_chat'
SAFE_PATH = re.compile(r'/[^\x00-\x1f()*?\[\]{}]*')


def restricted_overrides(*, web_search='disabled'):
    # Applied when the app-server launches, before any MCP servers or hooks start.
    overrides = [f'web_search="{web_search}"', 'project_doc_max_bytes=0', 'history.persistence="none"']
    disabled = ('shell_tool', 'unified_exec', 'shell_snapshot', 'apps', 'connectors', 'plugins',
                'hooks', 'codex_hooks', 'multi_agent', 'collab', 'js_repl', 'computer_use',
                'browser_use', 'browser_use_external', 'in_app_browser', 'image_generation',
                'view_image', 'memories', 'memory_tool', 'goals', 'workspace_dependencies')
    overrides += [f'features.{key}=false' for key in disabled]
    overrides += ['features.skip_host_skill_discovery=true']
    # Config maps merge: an empty mcp_servers map would NOT disable inherited servers.
    import tomllib
    path = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))) / 'config.toml'
    config = tomllib.loads(path.read_text()) if path.exists() else {}
    names = config.get('mcp_servers', {})
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in names):
        raise ValueError('An MCP server name cannot be safely disabled for this Codex profile.')
    overrides += [f'mcp_servers.{name}.enabled=false' for name in names]
    return tuple(overrides)


def read_scope(cwd, readable=()):
    """Filesystem rules for chat commands: the checkout plus the named review files.

    Reads elsewhere are denied, as for the Claude chat. Any deny rule also keeps
    commands matched by the user's exec-policy allow rules (for example `gh api`)
    inside the sandbox; without one, Codex runs them unsandboxed.
    """
    rules = {':minimal': 'read', ':slash_tmp': 'deny'}
    for path in (cwd, *readable):
        path = path.rstrip('/') if isinstance(path, str) else ''
        if SAFE_PATH.fullmatch(path) and '..' not in path.split('/'):
            rules[path] = 'read'
    return rules


def chat_overrides(cwd, readable=()):
    # Live web search, as in the Claude chat. It is a hosted tool outside the
    # sandbox; the read scope below limits what a query or URL could carry.
    overrides = restricted_overrides(web_search='live')
    replaced = ('features.shell_tool=', 'features.unified_exec=', 'history.persistence=')
    table = ', '.join(f'{json.dumps(path)}={json.dumps(access)}' for path, access in read_scope(cwd, readable).items())
    return tuple(value for value in overrides if not value.startswith(replaced)) + (
        'features.shell_tool=true', 'features.unified_exec=true', 'history.persistence="save-all"',
        f'default_permissions="{CHAT_PROFILE}"', f'permissions.{CHAT_PROFILE}.filesystem={{{table}}}',
        f'permissions.{CHAT_PROFILE}.network.enabled=false',
        # Commands see only core variables, never tokens; git skips the unreadable user config.
        'shell_environment_policy.inherit="core"', 'shell_environment_policy.ignore_default_excludes=false',
        'shell_environment_policy.set.GIT_CONFIG_GLOBAL="/dev/null"', 'shell_environment_policy.set.GIT_CONFIG_NOSYSTEM="1"',
    )
