"""Consume Codex turn events without publishing private reasoning or raw JSON."""
import json


def collect_response(events, progress):
    final = fallback = None
    completed = False
    for event in events:
        method = event.method
        payload = event.payload.model_dump(mode='json', by_alias=True)
        if method == 'turn/started':
            progress('Analyzing selected code and PR diff…')
        elif method.startswith('item/reasoning/'):
            progress('Analyzing code…')
        elif method == 'item/agentMessage/delta':
            progress('Receiving response…')
        elif method == 'item/completed':
            item = payload.get('item', {})
            if item.get('type') == 'agentMessage':
                if item.get('phase') == 'final_answer':
                    final = item.get('text')
                elif item.get('phase') is None:
                    fallback = item.get('text')
        elif method == 'turn/completed':
            if payload.get('turn', {}).get('status') != 'completed':
                raise ValueError('The AI stopped before completing its response. Retry the question.')
            completed = True
    if not completed or not (final or fallback):
        raise ValueError('The AI response was interrupted. Retry the question.')
    return json.loads(final or fallback)


def ask(session, content, schema, effort, progress):
    from openai_codex import ExternalMessage
    turn = session.turn(ExternalMessage(tool_name='review_context', content=content),
                        output_schema=schema, effort=effort or None)
    events = turn.stream()
    try:
        return collect_response(events, progress)
    finally:
        events.close()
