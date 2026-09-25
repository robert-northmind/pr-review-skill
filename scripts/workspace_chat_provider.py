"""Consume Codex turn events without publishing private reasoning or raw JSON."""
import re
import time


def web_request(item):
    action = item.get('action') or {}
    kind = action.get('type', 'search')
    query = action.get('query') or ' · '.join(action.get('queries') or []) or item.get('query', '')
    if kind in ('openPage', 'open_page'):
        return {'kind': 'open_page', 'url': action.get('url', '')}
    if kind in ('findInPage', 'find_in_page'):
        return {'kind': 'find_in_page', 'url': action.get('url', ''), 'query': action.get('pattern', '')}
    return {'kind': 'web_search', 'query': query[:1000]}


def collect_response(events, progress, on_tool=lambda _: None, on_draft=lambda _: None):
    final = fallback = None
    completed = False
    drafts = {}
    last_update = 0
    for event in events:
        method = event.method
        payload = event.payload.model_dump(mode='json', by_alias=True)
        if method == 'turn/started':
            progress('Investigating the question…')
        elif method.startswith('item/reasoning/'):
            progress('Analyzing code…')
        elif method == 'item/agentMessage/delta':
            item_id = payload.get('itemId', '')
            drafts[item_id] = drafts.get(item_id, '') + payload.get('delta', '')
            if time.monotonic() - last_update > .3:
                on_draft(drafts[item_id])
                last_update = time.monotonic()
        elif method in ('item/started', 'item/completed'):
            item = payload.get('item', {})
            kind = item.get('type')
            if kind == 'webSearch':
                request = web_request(item)
                label = {'web_search': 'Searching web', 'open_page': 'Opening web page', 'find_in_page': 'Searching web page'}[request['kind']]
                progress(f'{label} · {request.get("url") or request.get("query") or "External documentation"}')
                if method == 'item/completed':
                    on_tool(request)
            elif kind in ('commandExecution', 'dynamicToolCall'):
                github = kind == 'dynamicToolCall' and item.get('tool') == 'github_read'
                progress('Reading GitHub context…' if github else 'Exploring repository source…')
                if method == 'item/completed':
                    on_tool({'kind': 'github_read' if github else 'repository_read'})
            elif kind == 'agentMessage' and method == 'item/completed':
                if item.get('phase') == 'final_answer':
                    final = item.get('text')
                    on_draft(final or '')
                elif item.get('phase') is None:
                    fallback = item.get('text')
                else:
                    progress((item.get('text') or '')[:500])
                    on_draft('')
        elif method == 'turn/completed':
            if payload.get('turn', {}).get('status') != 'completed':
                raise ValueError('The AI stopped before completing its response. Retry the question.')
            completed = True
    answer = final or fallback
    if not completed or not answer:
        raise ValueError('The AI response was interrupted. Retry the question.')
    sources = []
    for title, url in re.findall(r'\[([^]\n]+)\]\((https?://[^\s)]+)\)', answer):
        if url not in {s['url'] for s in sources}:
            sources.append({'title': title, 'url': url})
    return {'answer': answer, 'sources': sources[:12]}


def ask(session, content, effort, progress, on_tool=lambda _: None, on_draft=lambda _: None):
    from openai_codex import ExternalMessage
    turn = session.turn(ExternalMessage(tool_name='review_context', content=content),
                        effort=effort or None)
    events = turn.stream()
    try:
        return collect_response(events, progress, on_tool, on_draft)
    finally:
        events.close()
