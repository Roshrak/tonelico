---
name: minecraft-skin-pixel-art-editor
description: "Edit, recolor, and preview 64x64 Minecraft player skins."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, skin, pixel-art, uv-map, texture, gaming]
    category: gaming
---

# Minecraft Skin Pixel-Art Editor (64x64 UV)

Procedure for inspecting, recoloring, reshaping garments/emblems, and visually verifying 64x64 RGBA Minecraft player skins (classic 4px-arm and slim 3px-arm layouts).

## When to Use

- User asks to edit, recolor, or customize a Minecraft player skin PNG (`64x64` or `64x32` UV texture).
- User wants to change a skin's outfit geometry (e.g., cloak/robe to tunic, armor, jacket, boots) or back/chest emblem (e.g., moon to stars, guild crest).
- User wants to preview how a flat Minecraft UV texture looks assembled across Front, Back, Right, and Left views with 3D outer overlays applied.

## Workflow

### 1. Backup & Inspect UV Islands in `execute_code`
Run `PIL.Image` inside `execute_code` (Pillow is available in the Hermes kernel).
1. Back up the source skin to `<name>_original_backup.png` before modifying in-place or writing named outputs.
2. Extract unique RGBA colors, compute luminance (`0.299*R + 0.587*G + 0.114*B`), assign each color a single-character ASCII symbol (`.` for `alpha == 0`), and print all 6 faces (`TOP`, `BOTTOM`, `RIGHT`, `FRONT`, `LEFT`, `BACK`) of all 12 UV islands.

Standard 64x64 box UV generator for any part at `(x0, y0)` with `(w, d, h)`:
- `TOP`: `(x0+d, y0, w, d)`
- `BOTTOM`: `(x0+d+w, y0, w, d)`
- `RIGHT`: `(x0, y0+d, d, h)`
- `FRONT`: `(x0+d, y0+d, w, h)`
- `LEFT`: `(x0+d+w, y0+d, d, h)`
- `BACK`: `(x0+2*d+w, y0+d, w, h)`

Part origins `(x0, y0, w, d, h)` (Classic 4px arms):
- Head Base: `(0, 0, 8, 8, 8)` | Hat Overlay: `(32, 0, 8, 8, 8)`
- Torso Base: `(16, 16, 8, 4, 12)` | Jacket Overlay: `(16, 32, 8, 4, 12)`
- Right Leg Base: `(0, 16, 4, 4, 12)` | Right Leg Overlay: `(0, 32, 4, 4, 12)`
- Left Leg Base: `(16, 48, 4, 4, 12)` | Left Leg Overlay: `(0, 48, 4, 4, 12)`
- Right Arm Base: `(40, 16, 4, 4, 12)` | Right Arm Overlay: `(40, 32, 4, 4, 12)`
- Left Arm Base: `(32, 48, 4, 4, 12)` | Left Arm Overlay: `(48, 48, 4, 4, 12)`

### 2. Build Multi-Shade Hue-Shifted Color Ramps
- Map source accent shades by luminance rank to a multi-shade gradient (8–19 shades) rather than flat or neon colors.
- For gold/yellow palettes, avoid pure neon yellow (`R > 235, G > 210`); anchor highlights in warm antique gold (`#e0b946` / `#ddbd46`), midtones in goldenrod/ochre (`#caa030`, `#be9328`, `#a4791d`), and shadows in bronze/umber (`#825c15`, `#684711`, `#573a0e`, `#3f290a`).
- Neutralize cool-tinted dark fabric (`B > R + 6`) when switching from cool (purple/blue) to warm (gold/yellow) accents so the black/charcoal base (`#000000` to `#26262a`) harmonizes with warm trim.

### 3. Apply Structural Garment & Emblem Edits
- **Cloak/Robe to Tunic conversion**:
  - Replace the full-length center-front black void gap (`x=23..24`) with a V-neck collar (`y=20..22`) converging into a central tunic placket/seam (`y=23..27`) over shaded chest fabric.
  - Add a 2-pixel horizontal waist belt (`y=28..29` on Torso Base and `y=44..45` on Jacket Overlay) wrapping all 4 torso faces, with a 2x2 center buckle at `x=23..24`.
  - Terminate the tunic skirt on the upper thighs (`y=23` on Right Leg, `y=55` on Left Leg, plus matching 3D overlays at `y=36..39` and `y=52..55`) with a 1-pixel inner-thigh center split (`x=7` on Right Leg Front, `x=20` on Left Leg Front).
  - Clear lower leg overlays (`y=40..47` and `y=56..63`) to transparent `(0, 0, 0, 0)` and paint shaded trousers (`rows 4..7` of legs) above boots (`rows 8..11` of legs).
- **Back Emblems (`x=32..39, y=20..27`)**:
  - Within the 8x8 upper-back canvas above the belt, use odd-dimensioned (`5x5` and `3x3`) 4-point cross/diamond stars with bright centers, mid-gold cardinal arms, and dark bronze tips.

### 4. Render Composite Orthographic Preview & Verify with `vision_analyze`
Run `scripts/render_skin_preview.py` (or call its functions in `execute_code`) to generate a 10x nearest-neighbor comparison sheet showing assembled `Front`, `Back`, `Right`, and `Left` views (with 3D overlays alpha-composited onto base layers) alongside the unwrapped 64x64 UV map. Always inspect the rendered preview with `vision_analyze` before finishing.

## Pitfalls

- **Diagonal star/emblem fusion on 8-wide torso backs**: Leave at least a 1–2 pixel dark background gap both orthogonally and diagonally between multiple stars or symbols on `x=32..39, y=20..27` — touching diagonal corner pixels fuse separate stars into a single blob at normal viewing scale.
- **Boxy "ladder" chest and merged belt buckles**: Do not run parallel bright vertical chest stripes straight through a 2x2 center belt buckle (`x=23..24`) and into a closed horizontal thigh bar — converge the collar into a central seam above the belt and darken the belt pixels at `x=22` and `x=25` so the 2x2 buckle stands out cleanly.
- **Double horizontal hip stripes on back/side views**: When placing the tunic bottom hem on the upper thighs (`leg row 3`), do not also put a horizontal gold hem on the bottom row of the torso/jacket (`y=31` / `y=47`) — keep `y=30..31` dark tunic fabric so the skirt flows continuously from waist belt to thigh hem.
- **Sleeve cuffs bleeding into the waist belt**: Place tailored wrist cuffs at arm row 10 (`y=30` base / `y=46` right sleeve / `y=62` left sleeve) above 1 row of glove/hand pixels (`row 11`) — Minecraft arms and torso are both 12 pixels tall, so cuffs at rows 8–9 collide horizontally with the waist belt across all views.
- **Incomplete 360-degree limb bands**: Wrap horizontal tunic hems (`y=23`/`y=55`), boot cuffs (`y=28`/`y=60`), and wrist cuffs (`y=30`/`y=62`) across all 4 limb faces, including inner leg faces (`x=8..11` and `x=16..19`) and outer-back arm pixels (`x=47` and `x=63`) — missing edge pixels leave gaps in side profiles and 3D walking animations.
- **Leftover collar shadow tint**: When recoloring a skin's accent palette, check `TORSO BASE TOP` (`x=20..27, y=16..19`) for dark maroon/purple neck shading pixels that sit outside the main trim ramp and recolor them to match the new palette.
