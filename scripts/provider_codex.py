"""Codex-specific protocol and sandbox configuration behind the AI boundary."""
import json
from types import SimpleNamespace
from ai_runtime import sources

class Session:
    def __init__(self, client_factory=None):
        self.client_factory = client_factory
        self.client = None
        self.thread_id = self.turn_id = None

    def run(self, request, callbacks):
        if request.mode == 'review':
            return self.review(request, callbacks)
        from openai_codex import Codex, CodexConfig, ApprovalMode, Sandbox
        from codex_runtime import chat_overrides, restricted_overrides
        from workspace_chat_provider import ask
        chat = request.mode == 'chat'
        with Codex(CodexConfig(cwd=request.cwd,
                              config_overrides=chat_overrides() if chat else restricted_overrides(),
                              client_name='pr_review_dashboard', client_title='PR review assistant')) as codex:
            options = dict(model=request.model or None, cwd=request.cwd,
                           sandbox=Sandbox.read_only,
                           approval_mode=ApprovalMode.auto_review if chat else ApprovalMode.deny_all)
            options['developer_instructions' if chat else 'base_instructions'] = request.instructions
            session = codex.thread_resume(request.session_id, **options) if request.session_id else codex.thread_start(ephemeral=not chat, **options)
            callbacks.session(session.id)
            if chat:
                return {'completed': True, **ask(session, request.prompt, request.effort,
                         lambda text: callbacks.emit('update', text), callbacks.tool, callbacks.draft)}
            from openai_codex import ExternalMessage
            result = session.run(ExternalMessage(tool_name='pr_context', content=request.prompt),
                                 output_schema=request.schema, effort=request.effort or None)
            return {'completed': True, 'structured': json.loads(result.final_response),
                    'usage': result.usage.model_dump(mode='json') if result.usage else {}}

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

    def interrupt(self):
        if self.client and self.thread_id and self.turn_id:
            self.client.turn_interrupt(self.thread_id, self.turn_id)

    def close(self):
        if self.client:
            self.client.close()
