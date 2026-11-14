# Local chart libraries

The production files are byte-for-byte copies of the pinned offline fixtures
in `tests/fixtures/perf/`. The tests directory is excluded from the Docker
image, so the app serves these copies from `static/vendor/`.

| File | Upstream | License | SHA-256 |
|---|---|---|---|
| `chart.umd.4.6.1.js` | <https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.js> | MIT, `chart.js.LICENSE.md` | `338399fb5bafe598d21cfc471b0590b61ceb321a985fade4f68499b151f67fbf` |
| `chartjs-plugin-annotation.3.1.0.min.js` | <https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0/dist/chartjs-plugin-annotation.min.js> | MIT, `chartjs-plugin-annotation.LICENSE.md` | `ff03786a60f6c93ccacfe0fbb6c2e3c671d7930856a3689f2f393113d8d655ec` |
