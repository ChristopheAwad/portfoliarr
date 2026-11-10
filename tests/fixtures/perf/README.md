# Pinned browser assets for the offline performance smoke test

These files are test-only copies, served by `scripts/measure_perf.py` when
`--offline-assets` is set. The application still loads the production CDN
URLs in normal use; only the test browser's requests for those exact URLs
are fulfilled from here, so a real chart renders without network access.

| File | Upstream | Version | License |
|---|---|---|---|
| `chart.umd.4.6.1.js` | `https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.js` | 4.6.1 | MIT (`chart.js.LICENSE.md`) |
| `chartjs-plugin-annotation.3.1.0.min.js` | `https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js` | 3.1.0 | MIT (`chartjs-plugin-annotation.LICENSE.md`) |

Fetched 2026-11-10. `base.html` requests `chart.js@4` and
`chartjs-plugin-annotation@3`; on that date those URLs resolved to the
versions above. Re-pin these files (and this table) when the unversioned
production tags move.
