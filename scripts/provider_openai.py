"""Existing API-key classifier; not a review/chat agent."""
import json
import os
from ai_runtime import ProviderError

class Session:
    def run(self, request, callbacks):
        if request.mode != 'triage':
            raise ValueError('OpenAI API is only available for triage.')
        from openai import OpenAI
        if not os.environ.get('OPENAI_API_KEY'):
            raise ProviderError('OpenAI API key is not configured in the server environment.')
        with OpenAI(timeout=90, max_retries=0) as client:
            result = client.responses.create(model=request.model, instructions=request.instructions,
                input=request.prompt, store=False, max_output_tokens=1800,
                **({'reasoning': {'effort': request.effort}} if request.effort else {}),
                text={'format': {'type': 'json_schema', 'name': 'pr_effort', 'strict': True, 'schema': request.schema}})
            return {'completed': True, 'structured': json.loads(result.output_text),
                    'usage': result.usage.model_dump(mode='json') if result.usage else {}}
    def interrupt(self): pass
    def close(self): pass
