---
name: MergeAtlas
description: "MergeAtlas: Know what you're approving for real. The review screened like dailies off a film scanner."
colors:
  go-green: "#2fd07f"
  film: "#000000"
  film-ink: "#f2efe7"
  film-muted: "#a7a399"
  film-line: "#262624"
  light-table: "#f3f3ef"
  table-ink: "#0b0b0a"
  table-muted: "#55534d"
  strip: "#0b0b0a"
  screening-room: "#000000"
  room-ink: "#f2efe7"
  room-muted: "#a7a399"
  strip-dark: "#262624"
  shot-green: "#0f7a48"
typography:
  display:
    fontFamily: "Archivo, Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "clamp(42px, 5.6vw, 88px)"
    fontWeight: 820
    lineHeight: 0.96
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 118"
  headline:
    fontFamily: "Archivo, Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "clamp(32px, 3.6vw, 54px)"
    fontWeight: 820
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontVariation: "'wdth' 115"
  narration:
    fontFamily: "Archivo, Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "clamp(29px, 2.9vw, 38px)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.02em"
    fontVariation: "'wdth' 112"
  title:
    fontFamily: "Archivo, Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 750
    lineHeight: 1.2
    letterSpacing: "-0.01em"
    fontVariation: "'wdth' 108"
  brand:
    fontFamily: "Archivo, Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 750
    lineHeight: 1
    letterSpacing: "-0.01em"
    fontVariation: "'wdth' 112"
  lead:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "clamp(18px, 1.5vw, 20px)"
    fontWeight: 400
    lineHeight: 1.55
  body:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 700
    lineHeight: 1.4
  small:
    fontFamily: "Atkinson Hyperlegible Next, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  code:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, Menlo, monospace"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  counter:
    fontFamily: "Atkinson Hyperlegible Mono, ui-monospace, Menlo, monospace"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.4
    fontFeature: "tnum"
rounded:
  frame: "3px"
  inset: "2px"
  group: "4px"
spacing:
  gutter: "16px"
  step-gap: "32px"
  bridge: "40px"
  pair-gap: "64px"
  close: "48px"
  section: "clamp(64px, 8vw, 112px)"
  strip-after: "clamp(56px, 7vw, 104px)"
components:
  button-go:
    backgroundColor: "{colors.go-green}"
    textColor: "{colors.film}"
    typography: "{typography.label}"
    rounded: "{rounded.frame}"
    padding: "9px 18px"
  button-go-large:
    backgroundColor: "{colors.go-green}"
    textColor: "{colors.film}"
    rounded: "{rounded.frame}"
    padding: "14px 26px"
  button-star:
    backgroundColor: "{colors.go-green}"
    textColor: "{colors.film}"
    rounded: "{rounded.frame}"
    padding: "18px 32px 18px 28px"
  button-outline:
    textColor: "{colors.film-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.frame}"
    padding: "8px 14px"
  theme-switch:
    textColor: "{colors.film-muted}"
    rounded: "{rounded.group}"
    padding: "3px"
  command-line:
    backgroundColor: "{colors.film}"
    textColor: "{colors.film-ink}"
    typography: "{typography.code}"
    rounded: "{rounded.frame}"
    padding: "12px 14px"
  copy-button:
    textColor: "{colors.film-muted}"
    rounded: "{rounded.inset}"
    padding: "2px 10px"
  step-counter:
    backgroundColor: "{colors.table-ink}"
    textColor: "{colors.light-table}"
    typography: "{typography.counter}"
    padding: "1px 6px"
---

# Design System: MergeAtlas

## Overview

**Creative North Star: "Dailies off a Film Scanner"**

The page screens the review like rushes off a telecine: one frame at a time, each carrying its burn-in data. Every frame after the opening is black film in both themes: the review game's stage, the live map's band, the narration column, the install end card and its commands. Around the frames sits the room: a scanner's warm light table in the light theme, screening-room black in the dark one. The opening is screened on the room itself, so it follows the theme. The page never paints a later frame in the room's colour, and the room never takes a card, a tint or a shadow.

The opening is a single frame between letterbox bars in the room's colour (above 900px the picture is a true 2.39 frame, the bars splitting the rest of the viewport). The shot behind the title card is the real #8613 diff, set in Mono, three lines to a row so it fills the frame, tilted, defocused and rolling upward, in Go Green on screening-room black and Shot Green on the light table; a bottom-up shade in the room's colour sits behind the title card, and film grain over it, inverted on the light table. On load the aperture opens from a horizontal slit and the headline pulls focus. After the screening, the page is set type on the room's own ground, each section cut from the next by a strip of perforated film, the only divider the system has. Right after the game the page asks for a star: one large drawn star beside a display-size headline, lit Go Green while its button is in hand. The close is an end title card: install, the open-source note and a second star sit on a full-bleed black frame.

Archivo, wide and heavy, sets the title cards; Atkinson Hyperlegible Next carries running text; Atkinson Hyperlegible Mono is kept for burn-in data, code and counters. Green is the one saturated note on the page and it means the action in front of you. Light and dark both ship; the system decides until the visitor picks the sun or the moon.

**Key Characteristics:**
- Frames after the opening are always black film; the opening and the room around the frames are the light table or screening-room black.
- Square corners: 3px on frames and buttons, 2px on controls nested inside a frame.
- One saturated colour, Go Green, on actions, focus, selection and link underlines.
- Archivo expanded for title cards only; Atkinson Next for prose; Atkinson Mono for burn-in data and code.
- Perforated film strip as the only section divider; no cards, bands or rules elsewhere.
- No shadows or glows on the page; depth comes from black frames against the room, the title shade and grain.

## Colors

Monochrome film and room with a single phosphor green; the page carries its own tokens and the game inside the stage keeps its own.

### Primary
- **Go Green** (`go-green`, same in both themes): the fill of every page action (Play a review, Star on GitHub, the game's narration actions), the 2px focus ring, the text caret, selection at 35% mix, the lit progress segments above the stage, the 2px underline of page links, the star mark in the star ask while its button is hovered or focused, and the colour of the defocused diff wall in the dark opening. Labels on it are Film black, weight 700.
- **Shot Green** (`shot-green`, light theme only): the defocused diff wall on the light table, a darker green so the wall reads on the pale room. In the dark theme the wall takes Go Green.

### Neutral
- **Film** (`film`): the material of every frame after the opening, in both themes: the stage, the map band, the narration column, the install end card, the command lines. Inside the opening, `--film` and its inks point at the room's tokens, so the opening and its shade follow the theme.
- **Film Ink** (`film-ink`): projector-white text on film: narration headline, command text, install prose; in the opening, the room's ink sets the title card, subhead and nav.
- **Film Muted** (`film-muted`): secondary text on film: narration body, copy-button label, unpressed theme icons.
- **Film Line** (`film-line`): 1px hairlines on film: the theme switch frame, command-line and copy-button borders, the stage frame and its progress-bar rule.
- **Light Table** (`light-table`) / **Screening Room** (`screening-room`): the room behind the after-screening sections, light and dark.
- **Table Ink** (`table-ink`) / **Room Ink** (`room-ink`): headlines and prose on the room, the star mark at rest, and the opening's title card.
- **Table Muted** (`table-muted`) / **Room Muted** (`room-muted`): secondary text in the opening and on the room.
- **Strip** (`strip`) / **Strip Dark** (`strip-dark`): the perforated film divider. In the dark theme it lifts to a dark grey so the strip still reads against screening-room black.

### The game's internal palette
The fake OS inside the stage (desktop, windows, GitHob, Slick, Codix, terminal, flood screen) keeps the older tokens it was built with: `--bg`, `--dot`, `--card`, `--code-bg`, `--ink`, `--muted`, `--line`, `--core`, `--cleanup`, `--add`, `--del`, `--add-bg`, `--del-bg`, `--shadow`, `--flood`, `--flood-ink`, `--cream`, each with its own dark value. Inside the game, green/red/blue/orange keep their diff meanings (added, removed, link, cleanup), windows round at 10px and lift with shadows. Their values live in the sidecar's `gamePalette`. They are the fiction's materials, not the page's; the live map canvas also sits on the game's `--bg` because it is the real viewer.

### Named Rules
**The Black Film Rule.** Every frame after the opening is black film (`film`) in both themes. Only the room, and the opening screened on it, change with the theme.

**The One Note Rule.** Go Green is the only saturated colour the page draws from its own tokens, and it marks the action in front of you, focus and link underlines; the star mark takes it only while its button is in hand. Never a background band, a heading colour or decoration.

**The Two Palettes Rule.** Page surfaces draw only from the page tokens (`--pg*`, `--film*`, `--strip`, `--go`); the game draws only from its own. Neither borrows from the other.

## Typography

**Display Font:** Archivo, variable width 62 to 125 and weight 100 to 900 (with Atkinson Hyperlegible Next, system-ui)
**Body Font:** Atkinson Hyperlegible Next, 400 to 700 (with system-ui, sans-serif)
**Label/Mono Font:** Atkinson Hyperlegible Mono, 400 and 600 (with ui-monospace, Menlo)

**Character:** Title cards are Archivo pushed wide (108 to 118% width) and heavy (750 to 820), tightly tracked, like a film's opening card; everything people read at length stays in Atkinson for legibility. Mono is data, never voice.

### Hierarchy
- **Display** (Archivo 820, clamp 42 to 88px, 0.96, -0.035em, width 118%, balanced): the single title card in the opening, lower left.
- **Headline** (Archivo 820, clamp 32 to 54px, 1, -0.03em, width 115%, balanced): one per after-screening section. The star ask sets its headline at display scale instead (clamp 36 to 84px, 0.96, -0.035em, width 118%, 18ch).
- **Narration** (Archivo 800, clamp 29 to 38px above 900px, clamp 22 to 27px below, 1.08, width 112%): the narration column's step title beside the game.
- **Title** (Archivo 750, 20px, 1.2, width 108%): install step names.
- **Brand** (Archivo 750, 26px, width 112%) beside a 44px logo: the wordmark in the nav. At 480px and below the logo (32px) stands alone and the name is kept only for screen readers, since the headline below opens with it.
- **Lead** (Atkinson 400, clamp 18 to 20px, 1.55, pretty wrap): section prose capped at 62ch (60ch for the map bridge, 52ch for the install intro). The hero subhead is clamp 19 to 23px/1.5 at 40ch; narration body 22px/1.5 above 900px, 16px/1.4 below, capped at 68ch. The game's own text runs 4px larger above 900px.
- **Body** (Atkinson 400, 17px, 1.55): base size of the page and install notes.
- **Label** (Atkinson 700, 16px, 1.4): button text. Play a review and Skip to install run clamp 18 to 20px, narration actions 20px above 900px, the star ask's button 20px, the closing Star 18px, nav Install 17px (15px at 480px), Open the map 14px.
- **Small** (Atkinson 400, 14px): the credit line.
- **Code** (Mono 400, 14px, 1.6): install commands.
- **Counter** (Mono 600, 13px, tabular figures): install step numerals.

### Named Rules
**The Title Card Rule.** Archivo sets title cards only: the display, section headlines, narration titles, step titles, the wordmark. Never a paragraph, button or label.

**The Burn-in Rule.** Mono on the page is data the frame carries: commands, step numerals. It never sets prose or headings.

## Layout

A centred column, max 1240px, with a 16px gutter that grows to the safe-area inset. Frames break out of the column to full bleed: the opening fills the first viewport (min-height 100svh) with the nav bar over the picture; above 900px it takes three rows, 1fr / auto / 1fr, with the nav centred in the top bar, a 2.39 picture (aspect-ratio) and an empty bottom bar, below it the picture fills the rest of the viewport, with the title card bottom-aligned in a 1.5fr / 1fr grid (56px column gap), subhead and calls to action on the right. Above 900px the review stage takes the full viewport height with no border or radius, game left and a clamp(360px, 33.6vw, 480px) narration column right. The map band is a full-bleed black frame whose content aligns to the 1240px column.

After the screening, every section opens with a full-bleed perforated strip followed by clamp(56px, 7vw, 104px) of room, on top of the section's own clamp(64px, 8vw, 112px) top padding. Two passages pair into equal columns with a 64px gap above 900px, the second dropped by clamp(80px, 10vw, 160px) so they read as two cuts, not a table. The star ask follows them: the star mark (clamp 140 to 260px) left, headline and button right, centred on each other with a clamp(32px, 5vw, 72px) gap; at 600px and below it stacks with an 88px mark. Then the live map, then the install end card: the open-source note, the steps 40px below in auto-fit columns (min 320px, 32px gap), and the closing Star 48px below them. The page ends on that card.

Breakpoints: at 900px and below, the title card stacks (16px gap, 96px top padding) and the picture loses its min-height; the stage stacks narration above the game; controls in the nav, copy buttons and Open the map gain a 44px minimum touch height and the theme buttons grow to 40 by 38px. At 700px and below the live map is replaced by its static plate. At 480px the brand drops to its 32px logo alone, Install to 15px, and the theme buttons and the GitHub link to 36px wide, so the nav fits a 320px screen.

**The Full Bleed Rule.** Frames run edge to edge; set type stays in the 1240px column. Text never sits in a full-bleed band of its own.

## Elevation & Depth

The page is flat. Depth is contrast between black film and the room, plus the camera's own artefacts inside the opening: a bottom-up shade over the shot (the room's colour to transparent at 78%), the shot tilted in perspective (rotateX 24deg, rotateZ -4deg) set at 20px Mono, 70% opacity and blurred 3px, and a fractal-noise grain at 16% opacity (inverted at 10% on the light table) that jitters in four steps every half second. No page surface carries a shadow or a glow. Shadows exist only inside the game, as part of its fake OS.

### Named Rules
**The No Lift Rule.** Nothing on the page is raised. A thing that needs separating is either a black frame or set apart by a perforated strip.

## Shapes

Square. Frames, buttons and command lines take a 3px radius; controls nested inside a frame (the copy button, the pressed theme button) take 2px; the theme switch's outer frame 4px; progress segments 1px. Borders are 1px hairlines; the primary button carries a 1.5px border in its own fill so it matches the outline button's box. The recurring silhouette is the film strip: a 24px band with a 26px repeat of rounded-rect sprocket holes (8 by 10px, 2px radius), cut by a mask so the room shows through.

## Components

### Buttons
- **Shape:** square (3px), label Atkinson 700.
- **Go:** Go Green fill and border, Film black label, 9px 18px. Play a review is 12px 24px; the closing Star on GitHub is the large variant (14px 26px, 18px label); Open the map is compact (6px 14px, 14px).
- **Star:** both Star on GitHub buttons lead with a stroked star glyph at 1.15em that fills on hover and focus.
- **Hover / Focus:** brightness 1.08 over 0.15s; focus is the global 2px Go Green outline at 3px offset.
- **Outline:** transparent fill, label in the surrounding ink, 1px border of 40% current colour that hovers to full current colour. Used for Install in the nav (10px 18px, 17px) and Open the map.
- **Text action:** Skip to install is a link in the opening's ink, weight 500, with a 2px Go Green underline, beside the Go button.
- **Install glide:** Install in the nav and Skip to install glide smoothly to the install end card (an instant jump under reduced motion).

### Theme Switch
- Two 40 by 36px icon buttons (sun, moon; 20px stroked SVG) in a 4px frame with a 40% current-colour border and 3px padding. The pressed one fills the ink with a glyph in the ground colour; unpressed glyphs are Film Muted, turning Film Ink on hover. The system decides until a pick is made; the pick is remembered and passed to the embedded map.

### GitHub Link
- The last item in the nav, after the theme switch: GitHub's mark as a 26px filled SVG in a 44px square (36px wide at 480px and below), in the muted ink, turning to the full ink on hover. It opens the MergeAtlas repository and is labelled "MergeAtlas on GitHub" for screen readers.

### Opening Frame (signature)
- Letterboxed frame on the room. On load the aperture opens from a horizontal slit (clip-path inset 50% to 0, 1.4s, cubic-bezier(.16, 1, .3, 1)) and the title pulls focus (blur 14px and 15% opacity to sharp, 1.6s after a 0.35s delay). The shot rolls upward over 90s; grain jitters at 0.5s. Reduced motion stops roll and grain.

### Perforated Strip
- The only divider: full bleed, 40px of 35mm stock in the Strip colour, two rows of sprocket holes cut through it. Every after-screening section opens with one.

### Command Line
- A small black frame (3px, Film Line border, 12px 14px) holding one Mono 14px command wrapping anywhere so the whole command shows, with a Copy button: transparent, Film Line border, 2px radius, Atkinson 600 12px in Film Muted, hovering to Film Ink with a Film Muted border.

### Star Ask
- A section on the room, right after the game: a large drawn star (the glyph's outline, 1.1 stroke in the room's ink, no fill) beside a display-size headline and the star button (Go, 18px 32px 18px 28px, 20px label). While the button is hovered or focused, the star fills and strokes Go Green and turns -8deg over 0.5s on the camera ease; under reduced motion it changes without the transition. The light comes only from the button: nothing glows.

### Install Steps
- The open-source note in Lead, then an ordered grid without markers; each step is a Title preceded by a step counter (a solid Film Ink block holding a Mono 13px numeral in black, 1px 6px), then a Command Line or a Film Muted note. The whole install section is the end title card, a full-bleed black frame below its strip, closing on the large Star button.

### Review Stage (fixed artifact)
- The game's frame: black film, a progress row drawn as a strip of film (sprocket rows above and below, one 14px frame per beat: exposed in 30% Film Ink once played, Go Green for the beat on screen) over a Film Line rule, the game screen, and the narration column on film with Narration headline, Film Muted body and Go buttons; each beat's headline pulls focus (0.8s) when it changes, and the column's rule is Film Line. Inside the screen everything is the game's own world. Above 900px a fast wheel scroll down from the opening stops once at the stage's top and holds 400ms, so the game can't be skipped by accident; after that the page scrolls freely.

### Live Map Band
- A full-bleed black frame holding the real viewer in a 640px canvas (592px at 900px and below) with Open the map above it; at 700px and below the iframe is never loaded and a static plate links to the full map.

## Do's and Don'ts

### Do:
- **Do** make every frame after the opening black film (`film`) in both themes and let only the room and the opening change.
- **Do** cut after-screening sections with the perforated strip and nothing else.
- **Do** keep Go Green for the action in front of you, focus, selection and link underlines, with a Film black label at weight 700.
- **Do** set title cards in Archivo at 108 to 118% width and everything read at length in Atkinson Hyperlegible Next.
- **Do** keep corners square: 3px on frames and buttons, 2px nested.
- **Do** stop roll and grain under reduced motion.

### Don't:
- **Don't** put shadows, glows, cards or tinted bands on the page; depth is film against the room.
- **Don't** add a second saturated colour to the page or use Go Green as a fill behind text that is not an action.
- **Don't** use game tokens (`--bg`, `--ink`, `--card`, `--line`, `--add`, ...) on page surfaces, or page tokens inside the game.
- **Don't** set prose or headings in Mono; it is burn-in data.
- **Don't** use Archivo for paragraphs, buttons or labels.
