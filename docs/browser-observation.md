# Browser Observation

Browser observation is optional. Install it with:

```bash
pip install -e '.[browser]'
playwright install chromium
```

Configure pages explicitly in `devsim.yaml`:

```yaml
runtime:
  adapters: [{type: http}, {type: command}, {type: browser}]
observation:
  browser:
    pages:
      dashboard: {path: /dashboard}
```

Scenarios can then use `browser.open`, `browser.expect`, `browser.click`, and
`browser.screenshot`. Screenshots are stored under
`.devsim/runs/<run_id>/screenshots/` and returned as run artifact metadata.

Observation URLs must resolve to localhost, private addresses, or local Docker
service names. Missing Playwright or Chromium produces
`BROWSER_ADAPTER_UNAVAILABLE`; it does not silently claim a UI pass.
