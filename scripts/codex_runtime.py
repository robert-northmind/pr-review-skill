"""Codex configuration shared by bounded classifiers and review chat."""
import os
import re
from pathlib import Path


def restricted_overrides(*, web_search=False):
    # Applied when the app-server launches, before any MCP servers or hooks start.
    search_mode = "live" if web_search else "disabled"
    overrides = [f'web_search="{search_mode}"', 'project_doc_max_bytes=0', 'history.persistence="none"']
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


def chat_overrides():
    overrides = restricted_overrides(web_search=True)
    replaced = ('features.shell_tool=', 'features.unified_exec=', 'history.persistence=')
    return tuple(value for value in overrides if not value.startswith(replaced)) + (
        'features.shell_tool=true', 'features.unified_exec=true', 'history.persistence="save-all"',
    )
