# Pinned chart library reference fixtures

These fixtures pin the chart libraries. The application and performance
harness load identical production copies from `static/vendor/`; the tests
verify that the served bytes match these files. `--offline-assets` blocks
external browser requests instead of replacing production assets with mocks.

| File | Upstream | Version | License |
|---|---|---|---|
| `chart.umd.4.6.1.js` | `https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.js` | 4.6.1 | MIT (`chart.js.LICENSE.md`) |
| `chartjs-plugin-annotation.3.1.0.min.js` | `https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js` | 3.1.0 | MIT (`chartjs-plugin-annotation.LICENSE.md`) |

Fetched 2026-11-10. The previously unversioned CDN tags resolved to these
versions at that time. Source and hash records for the shipped copies live in
`static/vendor/README.md`.
