---
target: MergeAtlas viewer
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/Users/ismayilkarimli/Developer/SaaS/MergeAtlas/skills/mergeatlas/assets/viewer.html"
target_fingerprint: "sha256:6af8e4f4d20cf4d9fa85db45b0171842aaeecfca42a8305cae3a3b004557f16b"
target_path: /Users/ismayilkarimli/Developer/SaaS/MergeAtlas/skills/mergeatlas/assets/viewer.html
timestamp: 2026-11-04T19-10-37Z
slug: skills-mergeatlas-assets-viewer-html
---
Method: dual-agent (A: design review sub-agent, B: detector + browser sub-agent)

## Design Health Score
| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | Progress bar, frame counts, live region good; R swaps card with no visible confirmation |
| 2 | Match System / Real World | 3 | "NOT CHANGED · AFFECTED", "affect 0 of 32 … 32 unaffected" read as tool-speak |
| 3 | User Control and Freedom | 3 | Esc, undo, Collapse fine; Esc after a ⌘K jump drops focus to body |
| 4 | Consistency and Standards | 2 | Arrow modals lack Prev/Next/review; intent modal "4 changes" vs pager "1 of 3"; frame "0 of 4" around 2 cards |
| 5 | Error Prevention | 3 | Marks scoped per file@intent with "Changed since you reviewed"; R toggles silently |
| 6 | Recognition Rather Than Recall | 2 | Legend at the bottom of the sidebar; R and ←/→ only in aria-keyshortcuts |
| 7 | Flexibility and Efficiency | 3 | ⌘K fuzzy, R, ←/→, Tree keys, Compact; palette shows no review state or reading order |
| 8 | Aesthetic and Minimalist Design | 2 | At 76% paths ~8.7px, pills ~9px; at Fit frame titles truncate; trivial intent gets a full frame |
| 9 | Error Recovery | 2 | No empty, loading or failed-map state |
| 10 | Help and Documentation | 2 | One hint line, no on-canvas legend, no shortcut sheet |
| Total | | 25/40 | Acceptable |

Baseline (2026-11-04T16-12-36Z): 25/40. Same total, different distribution: Flexibility 2→3 (modal keys), Consistency stays 2 for new reasons, Aesthetic 3→2 (legibility at default zoom measured this time). All five priority issues from the first run are fixed; this run found deeper ones.

## Design Specificity Verdict
LLM: structure is authored for this product — intent frames, relationship-coloured arrows with clickable pills, affected-file stacks, the Problem → Change → Key lines → Why it fixes modal, semantic atlas zoom. The visual surface is more generic (rounded white cards, top accent stripe, dotted canvas, segmented toggles). Missed chances: progress never shows spatially at atlas scale; arrow-colour meaning lives only in a buried legend.

Deterministic: CLI 1 finding, border-accent-on-rounded on #modal (deliberate intent stripe, false positive). Browser overlay: 12–13 findings — border-accent-on-rounded ×11 on canvas cards (same intent-colour system, deliberate), flat-type-hierarchy (sidebar h1 16px below card h3 19px; 1.23:1 step), and on mobile body-text-viewport-edge (first fit clips cards at the right; partly expected on a pannable canvas).

Verified false positive from A: "focus lands off-screen without panning" — re-tested with real Tab presses one at a time; every canvas element pans fully into view.

## What's Working
1. The modal is a reading instrument: Problem / What changes / Key lines / Why this fixes it with deep links, plus Mark-and-next, R and ←/→, makes a linear review loop over a non-linear map.
2. Relationships are first-class: labelled clickable pills, "Why they're linked" with code, hover/focus dimming of everything outside the neighbourhood.
3. Semantic zoom and accessibility basics: atlas blocks with progress, inert cards in atlas, proper dialog with labelled heading, focus trap and return, full dark theme.

## Priority Issues
- [P1] Default zoom is unreadable. At 76% paths ~8.7px, tags ~8.4px, pills ~9px and ~17px tall; at Fit frame titles truncate and 20–45% is a dead zone. Fix: open at a zoom where card text is ≥12px effective (fit the first intent), counter-scale pills to a minimum size and 24px hit area, bring atlas titles in sooner. Command: /impeccable typeset then /impeccable layout.
- [P1] Frame counts disagree with what the frame shows. "Let a manual export choice outlast theme changes" says "0 of 4 files reviewed" around 2 cards (App.tsx and the test sit in other frames); intent modal says 4 changes, pages 1 of 3. Conflicts with the agreed rule that a shared file sits in its first frame with no marker — needs a product decision. Command: /impeccable clarify.
- [P2] Mobile is a squeezed desktop: first fit clips cards, floating controls and the zoom label sit over card text. Fix: start phones on Tree, dock controls into one solid bottom bar. Command: /impeccable adapt.
- [P2] Legend and shortcuts are undiscoverable: arrow colours explained only at the bottom of the sidebar; R and ←/→ invisible (user chose to keep the R hint hidden). Fix: compact on-canvas legend chip; optional ? shortcut sheet. Command: /impeccable onboard.
- [P3] Tab order and focus edges: canvas comes before the sidebar and toolbar with no skip link; Esc after a ⌘K jump drops focus to body; story links are href="#" anchors that open modals. Command: /impeccable harden.

## Persona Red Flags
- Alex (power user): ⌘K shows no review state and is not in reading order; no next-unreviewed; two pagers inside the App.tsx modal (←/→ cards vs mouse-only "1 of 4" changes).
- Sam (keyboard/a11y): no skip link past the canvas; focus lost after palette + Esc; pills ~17px; relationship meaning by colour and dash only.
- Jordan (first-timer): nothing on the canvas says where to begin; "affect 0 of 32 … 32 unaffected" needs decoding; frame count vs cards makes them doubt their reading.

## Minor Observations
- Key-lines code clips horizontally in the modal with no scroll cue.
- "Also reaches" with 0 of 32 still renders; hide it at zero.
- Compact overlaps the "Checks the manual override" pill onto the affected stack.
- No completion moment at 100% reviewed.
- At atlas zoom the one-file frame's title is too small to read.

## Questions to Consider
- Should the canvas show the reading order (numbering, a Start review button) instead of keeping it inside the modal?
- Does a one-file, no-behaviour-change intent deserve a full frame and a cross-map arrow?
- What should 100% reviewed feel like?
