# gui/

The local web app: pages and the JSON API behind them. Routes stay thin; the work is in the other folders.

| | |
|---|---|
| Page | all of them: Chat, Energize, Tests, Devices, Lint, Help, Settings |
| Command line | `python app.py` |
| In | the browser, on 127.0.0.1 only |
| Out | pages, JSON, downloads |
| May import | every product folder, and Flask (the only folder that may) |
| Docs | [docs/GUIDE.md](../docs/GUIDE.md) |
| Tests | `tests/test_app.py`, `test_energize.py`, `test_devices_page.py`, `test_security.py` |

## Rules

- One Python module per page or feature (`energize.py`, `project.py`, `spec.py`, `udts.py` ...). A page's script and
  template have the page's name (`lint.html`, `lint.js`).
- No CDN, no web fonts: the app works offline. Icons are inline SVG (see `THIRD_PARTY_NOTICES.md`).
- Work that outlives a page (a requirements run, the loaded Energize program) stays on the server, so
  leaving a page never stops it.
