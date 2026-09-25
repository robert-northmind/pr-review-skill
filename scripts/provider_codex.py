"""Codex-specific protocol and sandbox configuration behind the AI boundary."""
import json
from types import SimpleNamespace
from ai_runtime import sources
import github_read

# Chat commands run sandboxed without network, and nothing may escalate (see
# codex_runtime.chat_overrides). GitHub reads go through this fixed tool instead,
# which the dashboard runs itself.
GITHUB_READ = {'type': 'function', 'name': 'github_read', 'description': github_read.DESCRIPTION,
               'inputSchema': github_read.SCHEMA}
CHAT_TOOLS = ('\nUse git show BASE:path and git diff BASE HEAD in the shell for pinned revisions; use github_read '
              'for GitHub reads. If github_read is unavailable, this conversation predates it: say that '
              'GitHub reads need a new conversation.')

DECLINED = {'item/permissions/requestApproval': {'permissions': {}}, 'item/tool/requestUserInput': {'answers': {}},
            'mcpServer/elicitation/request': {'action': 'decline'}}


def chat_client(request, handler):
    from openai_codex.client import CodexClient, CodexConfig
    from codex_runtime import chat_overrides
    overrides = chat_overrides(request.cwd, request.context.get('readable') or ())
    return CodexClient(CodexConfig(cwd=request.cwd, config_overrides=overrides, client_name='pr_review_dashboard',
                                   client_title='PR review assistant'), approval_handler=handler)


class Session:
    def __init__(self, client_factory=None):
        self.client_factory = client_factory
        self.client = None
        self.thread_id = self.turn_id = None

    def run(self, request, callbacks):
        if request.mode == 'review':
            return self.review(request, callbacks)
        if request.mode == 'chat':
            return self.chat(request, callbacks)
        from openai_codex import Codex, CodexConfig, ApprovalMode, Sandbox
        from codex_runtime import restricted_overrides
        with Codex(CodexConfig(cwd=request.cwd, config_overrides=restricted_overrides(),
                              client_name='pr_review_dashboard', client_title='PR review assistant')) as codex:
            session = codex.thread_start(ephemeral=True, model=request.model or None, cwd=request.cwd,
                                         sandbox=Sandbox.read_only, approval_mode=ApprovalMode.deny_all,
                                         base_instructions=request.instructions)
            callbacks.session(session.id)
            from openai_codex import ExternalMessage
            result = session.run(ExternalMessage(tool_name='pr_context', content=request.prompt),
                                 output_schema=request.schema, effort=request.effort or None)
            return {'completed': True, 'structured': json.loads(result.final_response),
                    'usage': result.usage.model_dump(mode='json') if result.usage else {}}

    def chat(self, request, callbacks):
        from openai_codex import Thread
        from codex_runtime import CHAT_PROFILE
        from workspace_chat_provider import ask
        def server_request(method, params):
            if method == 'item/tool/call':
                if (params or {}).get('tool') != 'github_read' or (params or {}).get('namespace'):
                    ok, text = False, 'Unknown tool.'
                else:
                    ok, text = github_read.read(request.context, (params or {}).get('arguments'), request.cwd)
                return {'success': ok, 'contentItems': [{'type': 'inputText', 'text': text}]}
            # approvalPolicy "never" means no approvals should arrive; refuse any that do.
            return DECLINED.get(method, {'decision': 'decline'} if method.endswith('requestApproval') else {})
        self.client = (self.client_factory or chat_client)(request, server_request)
        self.client.start(); self.client.initialize()
        # Resumed threads restore their stored profile or sandbox unless this names one.
        params = {'cwd': request.cwd, 'permissions': CHAT_PROFILE, 'approvalPolicy': 'never',
                  'developerInstructions': request.instructions + CHAT_TOOLS, **({'model': request.model} if request.model else {})}
        # Tools are stored with the thread. Older chats resume without github_read.
        thread = (self.client.thread_resume(request.session_id, params) if request.session_id else
                  self.client.thread_start({**params, 'ephemeral': False, 'dynamicTools': [GITHUB_READ]})).thread.id
        callbacks.session(thread)
        return {'completed': True, **ask(Thread(self.client, thread), request.prompt, request.effort,
                 lambda text: callbacks.emit('update', text), callbacks.tool, callbacks.draft)}

    def review(self, request, callbacks):
        import codex_review
        def approval(method, params):
            callbacks.emit('attention', 'The agent needs permission or input. The request was declined; review may be blocked.')
            if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                return {'decision': 'decline'}
            return {'answers': {}} if method == 'item/tool/requestUserInput' else {}
        self.client = (self.client_factory or codex_review.create_client)(approval)
        self.client.start(); self.client.initialize()
        self.thread_id = self.client.thread_start(codex_review.thread_parameters({'model': request.model, 'cwd': request.cwd})).thread.id
        callbacks.session(self.thread_id)
        self.turn_id = self.client.turn_start(self.thread_id, request.prompt,
                         {'effort': request.effort} if request.effort else None).turn.id
        while True:
            notification = self.client.next_turn_notification(self.turn_id)
            payload = notification.payload.model_dump(mode='json', by_alias=True)
            codex_review.record_notification(SimpleNamespace(emit=callbacks.emit), notification.method, payload)
            if notification.method == 'turn/completed':
                return {'completed': payload.get('turn', {}).get('status') == 'completed'}

    def steer(self, text, wrap_up=False):
        # Codex folds steering input into the active review turn.
        if not (self.client and self.thread_id and self.turn_id):
            return False
        self.client.turn_steer(self.thread_id, self.turn_id, text)
        return True

    def interrupt(self):
        if self.client and self.thread_id and self.turn_id:
            self.client.turn_interrupt(self.thread_id, self.turn_id)

    def close(self):
        if self.client:
            self.client.close()
