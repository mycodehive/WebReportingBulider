# Frontend interaction checks

Run from the repository root with Node.js 24.15+ and uv installed:

```sh
uv sync --group dev
npm ci
npm test
```

Node and jsdom are optional test tools. The service itself uses local vanilla
JavaScript and CSS and requires neither npm nor a frontend build.

The runner renders the actual Django designer template without creating a user,
database, or network service. It supplies the real Excel connector's schema to a
stub HTTP transport and exercises the designer DOM: dataset creation, field drag,
fixed/flow conversion, filters, parameters, sorting, explicit conversion mapping,
footer sum, page copy/delete, undo/redo, revision-aware saves, preview sandbox and
publication parameters. Captured report definitions are then validated by Python,
bound to a temporary Excel workbook, queried and rendered by the real engines.

This verifies interactions and contracts. jsdom has no browser layout engine and
does **not** verify visual appearance, pointer hit-testing, PDF output or physical
drag coordinates. Those need a separate browser check when Chromium is available.
