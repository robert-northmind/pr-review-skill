# AI settings prototype

Open `index.html` in a browser, or serve this directory from the repository root:

```sh
python3 -m http.server 8878 --bind 127.0.0.1
```

Then open <http://127.0.0.1:8878/prototypes/ai-settings/>.

The prototype reuses the dashboard's CSS and demonstrates independent Triage,
AI review and Chat settings. Each feature remembers its model/reasoning choices
for each provider. `catalog.js` is the single prototype catalog. Haiku has no
reasoning override; unsupported reasoning resets to the model default.

Save/discard works, with settings persisted only under the browser storage key
`pr-review-ai-settings-prototype-v1`. The sample defaults deliberately mix
providers. Automatic triage and daily limits are editable UI only.

“Try the workflow” simulates estimates, cancellable reviews, report history and
chat. Runs snapshot saved settings. Conversations retain their original settings;
new conversations use the latest saved Chat choice. Run/chat history resets on
reload. `simulateRun` demonstrates a common event boundary, not a production
adapter. There are no network requests, SDK calls, authentication checks, provider
fallbacks, GitHub operations or live tracker writes.

Real SDK behavior, permission handling, recovery, billing/authentication and
terminal removal remain outside this prototype. Production scripts are untouched.
