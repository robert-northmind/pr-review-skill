# Screenshot provenance

Captured September 15, 2026 from this repository's dashboard assets and bundled
review renderer, using headless Chrome at 1440 CSS pixels wide, with viewport heights chosen to show each section.

- `inbox-light.jpg`: current combined Open notes action, snooze controls, and
  Add to Up next / My reviews actions.
- `review-overview-light.jpg`: the opening of the combined report, with a
  before/after explanation for a deliberately flawed toy integer parser.
- `review-findings-light.jpg`: the same report with one finding collapsed and
  another expanded, showing its example, impact, fix direction, and draft comment.
- `my-reviews-light.jpg`: saved reviews with fictional update reasons and notes.
- `reporting-dark.jpg`: synthetic weekly review and merge activity.

The dashboard API responses were intercepted in an isolated browser context.
Every displayed PR, repository, author, activity event, and private note was
invented for this demo. Avatar requests were fulfilled with generated initials;
no GitHub profile images or live tracker data were used. No dashboard request
was forwarded to GitHub or the local running server.

The report uses a temporary, synthetic Git repository containing only a toy
`parser.py`. Its examples were source-traced and are labeled as such; the report
does not claim runtime testing. The images are browser captures of the actual
UI, with no replacement controls or composited text.

When refreshing these images, use current assets and renderer output in an
isolated demo, populate all data synthetically, and inspect each capture before
committing. Do not capture the live inbox and redact it afterward. Keep demo
tracker state and generated review artifacts outside the Git repository.
