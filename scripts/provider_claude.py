"""T3-style Claude integration: JS Agent SDK for sessions, tool-free CLI triage.

Use the installed executable and normal environment/login. Never copy credentials
or call Anthropic HTTP endpoints with subscription tokens.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from ai_runtime import ProviderError, sources

class Session:
    def __init__(self):
        self.process = None
        self.input_lock = threading.Lock()  # Steering and interrupts write from other threads.

    def run(self, request, callbacks):
        binary = os.environ.get('PR_REVIEW_CLAUDE') or shutil.which('claude')
        if not binary:
            raise ProviderError('Claude Code is not installed. Install it and run claude auth login.')
        if request.mode == 'triage':
            return self.classify(binary, request)
        node = os.environ.get('PR_REVIEW_NODE') or shutil.which('node')
        bridge = Path(__file__).with_name('claude-runtime')/'bridge.mjs'
        if not node or not (bridge.parent/'node_modules/@anthropic-ai/claude-agent-sdk/package.json').exists():
            raise ProviderError('Claude runtime is missing. Install Node.js and run npm ci --prefix scripts/claude-runtime.')
        self.process = subprocess.Popen([node, str(bridge)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, cwd=request.cwd)
        self.process.stdin.write(json.dumps({**asdict(request), 'binary': binary})+'\n')
        self.process.stdin.flush()
        result = None
        last_draft = 0
        for line in self.process.stdout:
            event = json.loads(line)
            kind = event.get('type')
            if kind == 'session': callbacks.session(event['id'])
            elif kind in ('update', 'tool', 'attention'): callbacks.emit(kind, event.get('text', ''))
            elif kind == 'read': callbacks.tool(event['details'])
            elif kind == 'draft' and time.monotonic() - last_draft >= .3:
                callbacks.draft(event['text']); last_draft = time.monotonic()
            elif kind == 'result': result = event
            elif kind == 'error':
                raise ProviderError('Claude Code could not finish. Check its local login, model availability and runtime installation.')
        if self.process.wait() or not result:
            raise ProviderError('Claude Code stopped before completing its response. Check its login and retry.')
        answer = result.get('answer', '')
        return {**result, 'sources': sources(answer)}

    def classify(self, binary, request):
        # Same tool-disabled CLI path as T3's ClaudeTextGeneration adapter.
        argv = [binary, '-p', '--output-format', 'json', '--json-schema', json.dumps(request.schema),
                '--tools', '', '--disable-slash-commands', '--strict-mcp-config',
                '--mcp-config', '{"mcpServers":{}}', '--permission-mode', 'dontAsk',
                '--setting-sources', '', '--settings', '{"disableAllHooks":true}',
                '--no-session-persistence', '--system-prompt', request.instructions]
        if request.model: argv += ['--model', request.model]
        if request.effort: argv += ['--effort', request.effort]
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, cwd=request.cwd)
        output, _ = self.process.communicate(request.prompt)
        try:
            value = json.loads(output)
            # User config can enable verbose output, producing a JSON message array.
            if isinstance(value, list): value = next(item for item in reversed(value) if item.get('type') == 'result')
            structured = value['structured_output']
        except (ValueError, KeyError, StopIteration, TypeError):
            raise ProviderError('Claude returned no structured estimate. Check local login and model availability.') from None
        if self.process.returncode or value.get('is_error'):
            raise ProviderError('Claude could not complete the estimate. Check local login and model availability.')
        return {'completed': True, 'structured': structured, 'usage': value.get('usage', {})}

    def steer(self, text, wrap_up=False):
        """Queue a user message into the running session; False until it can take one."""
        if not self.process or self.process.poll() is not None or not self.process.stdin or self.process.stdin.closed:
            return False
        with self.input_lock:
            self.process.stdin.write(json.dumps({'type': 'message', 'text': text, 'wrap_up': wrap_up})+'\n')
            self.process.stdin.flush()
        return True

    def interrupt(self):
        if self.process and self.process.poll() is None and self.process.stdin and not self.process.stdin.closed:
            with self.input_lock:
                self.process.stdin.write('{"type":"interrupt"}\n'); self.process.stdin.flush()

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try: self.process.wait(timeout=5)
                except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe and not pipe.closed: pipe.close()
