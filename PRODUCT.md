# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Skilled engineers asked to review a pull request whose change reaches further than its diff: several files, some of them affected only indirectly. Most know the repository they review; the struggle is missing context for the change, not unfamiliarity with the code. Their job: "When I'm asked to review a change that reaches further than its diff, help me quickly build the mental model I'm missing, so I can give a real review without having to reconstruct the change and hold it all in my head."

Emotional side of the job: not being the one who approved the incident. Social side: not being the bottleneck while a colleague waits.

## Product Purpose

MergeAtlas is an agent skill that turns a pull request into an interactive map on localhost. The story of the change comes first (background, problem, what the pull request does about it), then a card per changed file, framed by the outcome it serves, with cause-and-effect arrows and the unchanged files the change affects. Success is a reviewer who approves with confidence because they know what they are approving.

The promise ends at comprehension. It never finds bugs, gives verdicts, or tells the reviewer what to do; judgement stays with the reviewer.

## Positioning

A companion to GitHub's Files changed tab, never a replacement. The diff is the anchor: every claim links to its lines in Files changed, so the reviewer can always check against the code itself. The current hire leaves reviewers with workarounds: author walkthrough calls, asking to split the pull request, reading commit by commit, "viewed" checkboxes as memory, pasting the diff into an AI chat, or skimming and approving.

## Operating Context

The reviewer gets a review request (often in chat), opens the pull request, and works through Files changed. With MergeAtlas they ask their agent (for example Claude Code with `/mergeatlas`) to map the pull request, read the map in the browser, and click through to the diff for any line. Needs an agent that runs skills, Python 3, git, and the GitHub CLI signed in. Maps stay on the reviewer's machine.

## Capabilities and Constraints

- Real features: story with links to the cards that did each part; cards framed by intent; arrows; affected unchanged files; key lines with surrounding context; code links into Files changed; review marks and progress; Compact and Detailed cards; tree view; jump to a file; light and dark themes following the system.
- Fit is blast radius, not size: medium to large reach. A config tweak doesn't need a map.
- Habit (a MergeAtlas check on every pull request, regenerated per commit) is post-MVP and not shown until it exists.
- The repository is private until the MVP ships; the star link 404s until then.

## Brand Commitments

- Name: MergeAtlas. Logo: slate folded map with a git graph and green M / red A glyph (`skills/mergeatlas/assets/logo.svg`, `logo-3d.png`, `logo-glyph.svg`).
- Landing page voice: put the visitor in a reviewer's shoes instead of telling. Second person, present tense, plain; an unnamed narrator, never "we" or "I". "Your colleague", never a name; Sam exists only inside the fake OS.
- Copy speaks to the job and the limits of the current hire, never to MergeAtlas features. The name opens the headline as "MergeAtlas:" and never appears in the subhead or nav button; "map" names features only inside the game.
- Questions are the reviewer's own questions at the moment they arise, never quizzes or questions about tools. Show, don't tell. The villain is missing context, never the colleague.
- Hero: "MergeAtlas: Know what you're approving for real"
- The final call to action is starring the repository.

## Evidence on Hand

- Story pull request: the real excalidraw/excalidraw#8613 "feat: image cropping", credited by name and link; its map is the act-two demo.
- Proof section uses the same pull request.
- Install steps and the open-source repository (MIT).
- No testimonials, customers, usage numbers or measured time savings. Never claim numbers, time savings, or every/always/never unless literally true. No "built by an engineer who…" line.

## Product Principles

1. The job is the north star: every message shows a limit of the current hire or the job getting done.
2. Show the limit lived, then the progress; never sell the product.
3. Claim only what the product really does.
4. Stay beside the diff: the reviewer can always check the code itself.
5. End at comprehension; the judgement stays with the reviewer.
