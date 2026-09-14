# Feature: Privacy toggle keeps % returns visible

## What

The dashboard privacy toggle currently hides the entire change pill (e.g.
`+123.45 (+0.52%) Today` becomes `****`). The user wants only the dollar
values hidden — the percentage returns should stay visible so relative
performance is always glanceable.

**Before:** `+123.45 (+0.52%) Today` → `****`
**After:** `+123.45 (+0.52%) Today` → `(+0.52%) Today`

Cost basis and total value stay `****` (pure dollar amounts, no % to show).

## Files to touch

| File | Change |
|---|---|
| `static/js/common.js` | Add optional `hideValue` param to `paintChange` |
| `static/js/main.js` | Update `applyPortfolioPrivacy` + remove blanket refresh guard |

## Test plan

Manual GUI check (no new pytest — this is a presentation-only change with no
backend logic). Verify in browser:

1. Toggle privacy ON → portfolio value and cost basis show `****`
2. Day change pill shows `(+X.XX%) Today` (no dollar amount, correct color)
3. Total return pill shows `(+X.XX%) Total` (no dollar amount, correct color)
4. Toggle privacy OFF → all four spans restore to full values
5. Let the 30s refresh cycle run while masked → percentages stay updated
6. Ledger privacy toggle unaffected (already hides $ only, shows %)

## Status

- [x] Plan approved
- [ ] Implementation
- [ ] GUI gate
- [ ] Commit gate
