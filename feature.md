# Feature: Allocation Carousel Pagination

## Status
IMPLEMENTED — focused tests and the full 567-test suite pass. Browser GUI
approved by the user; ready for the approved PR workflow. Roadmap entry: #15.

## Goal
Make the dashboard's six allocation donut views read as a carousel. Keep the
existing previous/next arrows, touch swipe, saved position, and single Chart.js
canvas, while adding clickable pagination dots, an explicit current/total count
(`1 / 6`), and a subtle crossfade when the user changes views.

## User decisions
1. Show clickable dots plus an explicit current/total count.
2. Use a quick crossfade rather than rebuilding the card as a sliding track.
3. Keep the existing arrows and mobile swipe navigation.

## Test plan (write first; must fail before implementation)

### `tests/test_allocation_ui.py`
1. The rendered donut card contains a labelled pagination host and a live
   current/total counter whose initial text is `1 / 6`.
2. JavaScript creates one dot per `ALLOCATION_VIEWS` entry instead of
   hardcoding a second slide count.
3. Every dot is a real button with a dimension/position accessible label and
   clicking it calls the same `switchAllocView` path as arrows and swipe.
4. One synchronization function updates the dimension label, counter, active
   dot class, and `aria-current` state whenever the index changes.
5. Previous/next wraparound remains modulo `ALLOCATION_VIEWS.length`; direct
   dot navigation accepts the first and last boundaries.
6. An invalid or out-of-range saved index still falls back to zero; a valid
   saved non-ticker index synchronizes pagination and loads its data on startup.
7. Empty and failed allocation responses still paint the existing empty state
   without removing or disabling carousel pagination.
8. A navigation paint triggers the crossfade, while ordinary polling updates
   continue to use Chart.js `update("none")` and do not animate.
9. Async allocation replies are painted only if their dimension is still
   active, preventing a slow prior request from replacing a newer slide.
10. CSS contains active, hover, and keyboard focus-visible dot states; the
    crossfade is disabled under `prefers-reduced-motion: reduce`.

No backend tests or API shape changes are needed. Frontend behavior uses the
project's established source/meta-test approach and the final browser GUI gate.

## Implementation

### `templates/index.html`
- Add a pagination row below `.donut-box` and above the exclusion note.
- Include an empty dot host populated from `ALLOCATION_VIEWS` and an
  `aria-live="polite"` counter initialized to `1 / 6`.
- Improve arrow button labels while preserving their IDs and behavior.

### `static/js/main.js`
- Build dot buttons once from `ALLOCATION_VIEWS`; each dot routes through
  `switchAllocView(index)`.
- Centralize label, counter, active class, and `aria-current` updates in
  `syncAllocCarousel()`.
- Synchronize the initial saved index and immediately fetch a restored
  non-ticker view, fixing the current blank-until-poll reload behavior.
- Mark only user navigation for a one-shot crossfade when its data paints.
  Poll refreshes remain animation-free.
- Before painting an async dimension response or failure, confirm its key is
  still the active view so rapid navigation cannot paint stale data.
- Keep pagination visible when a slide has no data or its request fails.

### `static/style.css`
- Add a compact centered pagination row, dot buttons, active state, numeric
  counter, and visible keyboard focus treatment.
- Add a short opacity crossfade class and disable it for reduced motion.
- Keep the controls usable in the existing narrow sidebar and mobile layout.

## Verification and gates
1. Run `python -m pytest tests/test_allocation_ui.py` and confirm the new tests
   fail before implementation.
2. Implement the smallest frontend-only change.
3. Run the focused test file, then full `python -m pytest`.
4. Wait for browser GUI approval: arrows, swipe, and dots navigate; dots/count
   stay synchronized; saved non-ticker view loads; empty view remains navigable;
   crossfade is subtle in desktop/mobile and absent with reduced motion.
5. Ask before any commit or push.
