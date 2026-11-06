#!/usr/bin/env python3
"""Render a 10x side-by-side Front/Back/Right/Left + UV comparison sheet for 64x64 Minecraft skins."""
import sys
from PIL import Image


def crop_face(skin: Image.Image, x: int, y: int, w: int, h: int) -> Image.Image:
    return skin.crop((x, y, x + w, y + h))


def composite_part(base_crop: Image.Image, overlay_crop: Image.Image) -> Image.Image:
    out = base_crop.copy()
    out.alpha_composite(overlay_crop)
    return out


def render_views(skin: Image.Image) -> Image.Image:
    canvas = Image.new("RGBA", (68, 36), (0, 0, 0, 0))

    # Front view (16x32) at (2, 2)
    fx, fy = 2, 2
    canvas.alpha_composite(composite_part(crop_face(skin, 8, 8, 8, 8), crop_face(skin, 40, 8, 8, 8)), (fx + 4, fy))
    canvas.alpha_composite(composite_part(crop_face(skin, 20, 20, 8, 12), crop_face(skin, 20, 36, 8, 12)), (fx + 4, fy + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 44, 20, 4, 12), crop_face(skin, 44, 36, 4, 12)), (fx, fy + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 36, 52, 4, 12), crop_face(skin, 52, 52, 4, 12)), (fx + 12, fy + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 4, 20, 4, 12), crop_face(skin, 4, 36, 4, 12)), (fx + 4, fy + 20))
    canvas.alpha_composite(composite_part(crop_face(skin, 20, 52, 4, 12), crop_face(skin, 4, 52, 4, 12)), (fx + 8, fy + 20))

    # Back view (16x32) at (22, 2)
    bx, by = 22, 2
    canvas.alpha_composite(composite_part(crop_face(skin, 24, 8, 8, 8), crop_face(skin, 56, 8, 8, 8)), (bx + 4, by))
    canvas.alpha_composite(composite_part(crop_face(skin, 32, 20, 8, 12), crop_face(skin, 32, 36, 8, 12)), (bx + 4, by + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 44, 52, 4, 12), crop_face(skin, 60, 52, 4, 12)), (bx, by + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 52, 20, 4, 12), crop_face(skin, 52, 36, 4, 12)), (bx + 12, by + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 28, 52, 4, 12), crop_face(skin, 12, 52, 4, 12)), (bx + 4, by + 20))
    canvas.alpha_composite(composite_part(crop_face(skin, 12, 20, 4, 12), crop_face(skin, 12, 36, 4, 12)), (bx + 8, by + 20))

    # Right profile (8x32) at (42, 2)
    rx, ry = 42, 2
    canvas.alpha_composite(composite_part(crop_face(skin, 0, 8, 8, 8), crop_face(skin, 32, 8, 8, 8)), (rx, ry))
    canvas.alpha_composite(composite_part(crop_face(skin, 16, 20, 4, 12), crop_face(skin, 16, 36, 4, 12)), (rx, ry + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 40, 20, 4, 12), crop_face(skin, 40, 36, 4, 12)), (rx + 4, ry + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 0, 20, 4, 12), crop_face(skin, 0, 36, 4, 12)), (rx + 2, ry + 20))

    # Left profile (8x32) at (54, 2)
    lx, ly = 54, 2
    canvas.alpha_composite(composite_part(crop_face(skin, 16, 8, 8, 8), crop_face(skin, 48, 8, 8, 8)), (lx, ly))
    canvas.alpha_composite(composite_part(crop_face(skin, 40, 52, 4, 12), crop_face(skin, 56, 52, 4, 12)), (lx, ly + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 28, 20, 4, 12), crop_face(skin, 28, 36, 4, 12)), (lx + 4, ly + 8))
    canvas.alpha_composite(composite_part(crop_face(skin, 24, 52, 4, 12), crop_face(skin, 8, 52, 4, 12)), (lx + 2, ly + 20))

    return canvas


def build_comparison_sheet(orig_path: str, new_path: str, out_path: str, scale: int = 10) -> None:
    orig = Image.open(orig_path).convert("RGBA")
    new = Image.open(new_path).convert("RGBA")
    orig_views = render_views(orig)
    new_views = render_views(new)

    sheet_w = (68 + 68) * scale + 60
    sheet_h = (68 * 2) * scale + 80
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (48, 52, 60, 255))

    def paste_scaled(dst: Image.Image, src: Image.Image, px: int, py: int) -> None:
        up = src.resize((src.width * scale, src.height * scale), Image.NEAREST)
        dst.alpha_composite(up, (px, py))

    paste_scaled(sheet, orig_views, 20, 30)
    paste_scaled(sheet, orig, 20 + 70 * scale, 30)
    paste_scaled(sheet, new_views, 20, 50 + 68 * scale)
    paste_scaled(sheet, new, 20 + 70 * scale, 50 + 68 * scale)
    sheet.save(out_path)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: render_skin_preview.py <orig.png> <new.png> <preview_out.png>")
        sys.exit(1)
    build_comparison_sheet(sys.argv[1], sys.argv[2], sys.argv[3])
