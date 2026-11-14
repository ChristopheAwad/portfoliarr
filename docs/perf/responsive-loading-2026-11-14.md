# Responsive loading verification

Roadmap #64. Baseline code: `c784bfd`. Checked code: `523707c`.

These measurements use disposable synthetic portfolios and controlled providers
on the audit host. They do not measure the deployed server, LAN, live Yahoo, or
an Android device. Four OpenAI Terra Max implementation agents worked on
separate files. The lead ran the combined verification.

## Interaction results

| Check | Before | After |
|---|---:|---:|
| Cached 1Y chart render, normal CPU | about 1046 ms | 21.6 ms |
| New history requests for that cached switch | 0 | 0 |
| 5,000 collapsed transactions, ledger descendants | 115,200 | 200 |
| Same fixture qty sort, 4x CPU | 1786.8 ms | 15.4 ms |
| Same fixture value sort, 4x CPU | 2095.0 ms | 14.4 ms |
| Same fixture ticker sort, 4x CPU | 1924.5 ms | 9.2 ms |
| Two concurrent cold Volume Leaders reads | 66 info calls | 33 info calls |
| Following warm Volume Leaders read | no extra calls | no extra calls |
| Eight same-key history reads plus one warm read | 1 provider call | 1 provider call |

The chart measurement records `afterRender` only when the plotted data matches
the successfully preloaded 1Y reply. A subsequent frame checks the active
period. It is not a physical screen-presentation measurement.

Sort durations cover the synchronous real sort/render handler. Separate
next-frame opportunity timings are in the raw report. The eight-group fixture
has exactly 5,000 CAD BUY transactions using `.TO` symbols. Its 4x-CPU
next-frame opportunities were 34.8-39.7 ms after the change.

A separate 1,000-row/200-group BUY/SELL fixture had 200 sales. At 4x CPU its
synchronous sorts took 45.7-50.9 ms, while next-frame opportunities took
189.6-219.8 ms. Many visible summary cards still have layout/paint cost. This
stress fixture has no invented 100 ms display-time requirement.

All 52 focused acceptance checks passed, including zero collapsed transaction
and sale detail rows, exact expanded counts, removal on collapse, correct
cached data, and zero additional cached-switch requests.

## All-screen browser run

The standard harness used a fixed 150 ms delay per market function, 1,002
verified synthetic transactions, two visits per screen, and both 1280x800 and
390x844 viewports. Dashboard and Stock drew real charts; Ledger and Preferences
loaded no Chart library. Both viewport runs recorded zero uncaught page errors,
zero console errors, and zero external browser requests.

The standard stub replaces app-level market functions and bypasses their real
caches. This run checks request/render plumbing, not live cache effectiveness.
Its setup already warms some work, so visit one is not a cold process start.
The corrected chart marks also wait longer than the old premature marks;
their raw before/after navigation values are not a fair chart-draw comparison.

Production fonts and chart libraries are served locally. A separate real-browser
test holds font responses while the dark theme, visible page shell and portfolio
request proceed. It then loads all five font subsets, including extended Latin
and Vietnamese samples. Source URLs, pinned versions, hashes and licenses live
beside the production files in `static/fonts/` and `static/vendor/`.

## Automated verification

- Full suite: **1614 passed in 114.97 seconds**, no skips on the audit host.
- The full run used the main checkout venv, a redirected disposable DB and a
  network namespace with loopback only. Browser smoke tests use local assets.
- New behavior checks run actual JS in Node and actual pages in Chromium.
- All changed JavaScript files pass `node --check`; `git diff --check` passes.
- No frontend build/lint/type command exists in this repository.
- Docker is unavailable locally. The existing main workflow must build,
  smoke-test and publish the verified merged image.
- Final GUI screenshots, independent PR review and release results are recorded
  in `feature.md` and the PR. They were pending when this evidence file was made.

The standard CI requirements do not install Playwright. Browser-only checks can
skip there; their local execution above is required evidence, not a CI claim.

## Reproduction

Standard desktop command:

```bash
/usr/bin/python3 scripts/measure_perf.py --python /home/Chris/Documents/code/portfoliarr/.venv/bin/python --stub-ms 150 --runs 2 --settle 0.3 --ledger-rows 1000 --offline-assets --out /tmp/opencode/portfoliarr-audit-20261113/after-desktop
```

For phone width, add `--viewport 390x844` and use a separate output base.

Exact-fixture interaction command on the audit host:

```bash
/usr/bin/python3 /tmp/opencode/portfoliarr-audit-20261113/verify_first_pass.py --out /tmp/opencode/portfoliarr-audit-20261113/after-focused.json
```

The lead's temporary driver creates and verifies its own disposable rows and
uses CDP CPU throttling. `--baseline` records only known pre-fix failures;
unexpected failures still fail the process. The standard import harness's
`--ledger-rows 5000` creates 5,002 rows/10 tickers and must not be substituted
for this exact eight-group fixture. The approved procedure is in `feature.md`.

Raw reports and scripts on the audit host are under
`/tmp/opencode/portfoliarr-audit-20261113/`, including `before-focused.json`,
`before-chart-final.json`, `after-focused.json`, `after-cache-probe.json`,
`after-desktop.{md,json}`, and `after-phone.{md,json}`. All data is synthetic.
