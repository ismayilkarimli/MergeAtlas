---
target: MergeAtlas viewer
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "file:/Users/ismayilkarimli/Developer/SaaS/MergeAtlas/skills/mergeatlas/assets/viewer.html"
target_fingerprint: "sha256:2f6d45f1b6df45ad781b649763027e215d70a74b5fbdcc210f4eb175fbbdfcd4"
target_path: /Users/ismayilkarimli/Developer/SaaS/MergeAtlas/skills/mergeatlas/assets/viewer.html
timestamp: 2026-11-04T16-12-36Z
slug: skills-mergeatlas-assets-viewer-html
---
Method: dual-agent (A: design review sub-agent, B: detector + browser sub-agent)

## Design Health Score
| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | "N% reviewed" + per-frame counts good; #hint covers #zoomlabel at 1000px |
| 2 | Match System / Real World | 3 | "affect 0 of 4 files / 4 unaffected" inverted; view=list vs Tree label |
| 3 | User Control and Freedom | 3 | Esc, undo mark, Fit; no reset for dragged layout |
| 4 | Consistency and Standards | 2 | Two identical segmented controls on different axes; lowercase "hide"; h2->h4 skip |
| 5 | Error Prevention | 3 | Mark-and-advance gives no sign of what was marked |
| 6 | Recognition Rather Than Recall | 2 | Fit at 20-36% leaves Detailed text ~5px |
| 7 | Flexibility and Efficiency | 2 | No modal keys for prev/next/mark; no next-unreviewed |
| 8 | Aesthetic and Minimalist Design | 3 | Calm modal; busy canvas at mid zoom |
| 9 | Error Recovery | 2 | No empty or failed-load state |
| 10 | Help and Documentation | 2 | Single clipped hint line, hidden on phones |
| Total | | 25/40 | Acceptable |

## Design Specificity Verdict
Structure authored (intent frames, verb-led pills, affected-file stacks, atlas zoom, modal teaching order); visual shell generic (system font stack, soft-shadow rounded cards, full-colour emoji icons 🌍🌲📖🏷️🎯, cream #f4f1ea background = common AI default). New slate git-graph logo is more distinctive than the app.
Detector: CLI 1 (border-accent-on-rounded, #modal lines 129-130, deliberate kind stripe). Browser: canvas clean; modals 3 (border-accent-on-rounded; low-contrast .lineno 2.9:1 line 232; skipped-heading h2->h4 via section()).

## Priority Issues
- [P0] Canvas and modal not keyboard/screen-reader accessible: cards are divs tabIndex -1, arrows pointer-only, modal no aria-labelledby/focus move/trap/restore, focus-visible only on .review/.nav. Fix: focusable cards/pills with labels, modal focus management, focus ring, heading levels. /impeccable harden
- [P1] First view unreadable, chrome collides: fit lands 20-36% (A reports fit ignores #panel), #hint overlaps panel and controls, mobile #zout under density switch. Fix: fit beside panel, compact below ~50% zoom, hint in free area or dismissible, wrap controls on mobile. /impeccable layout, adapt
- [P1] Emoji icons break visual language (lines 331-336, 1199). Fix: monochrome currentColor line icons matching new logo. /impeccable polish
- [P2] No keyboard review loop in modal. Fix: ←/→ prev/next, R mark-and-advance, kbd hints in footer. /impeccable harden
- [P2] Canvas hierarchy and type: pills as loud as card titles, weak frame titles, underline under indentation, .lineno contrast. Fix: quieter pills, tinted heavier frame titles, underline code only, darken line numbers, one authored typeface. /impeccable quieter, typeset

## Persona Red Flags
Alex: no modal keys, no next-unreviewed, ⌘K unfiltered, no layout reset, no density shortcut.
Sam: unfocusable cards/arrows, unlabelled modal, no aria-live on progress, 11px muted text, no color-scheme so light scrollbars in dark.
Jordan: no "start here", clipped hint, Map/Tree vs Detailed/Compact confusion, legend below fold, affected-file stack not distinct.

## Minor Observations
Zero "Also reaches" wording; key lines marked by weight only; atlas title minimum size; panel toggle should be labelled icon button; dark atlas loses tint; no 100% closing moment (unverified).

## Questions to Consider
Closing beat at 100% that hands back the model? Story-first entry revealing the map intent by intent? One icon set and typeface drawn from the new logo?
