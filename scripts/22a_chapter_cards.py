"""Generate two chapter title cards for the walkthrough video.

Track A card (green accent #3ccf8e) -- why home wins
Track B card (blue accent #6eb0ff) -- how possessions chain

Cards are rendered at 3840x2160 (source frame resolution; the ffmpeg
pipeline downscales to 1920x1080). Output written to
video/public/frames/chapter_track_a.png and chapter_track_b.png.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "video" / "public" / "frames"
OUT.mkdir(parents=True, exist_ok=True)
LOGO = ROOT / "dashboards" / "assets" / "euroleague-logo.png"

W, H = 3840, 2160
BG = (11, 13, 16)
INK = (231, 236, 241)
MUTED = (182, 191, 204)
DIM = (122, 133, 149)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/HelveticaNeue.ttc",
    "/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/HelveticaNeueDeskInterface.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                if path.endswith(".ttc"):
                    return ImageFont.truetype(path, size, index=(1 if bold else 0))
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_card(track: str, label: str, headline: str, sub: str, accent: tuple[int, int, int]) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    bar_w = 80
    d.rectangle((0, 0, bar_w, H), fill=accent)

    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA")
        scale = 160 / logo.height
        logo = logo.resize((int(logo.width * scale), 160), Image.LANCZOS)
        chip_pad = 28
        chip_w = logo.width + chip_pad * 2
        chip_h = logo.height + chip_pad * 2
        chip = Image.new("RGBA", (chip_w, chip_h), (255, 255, 255, 255))
        chip.paste(logo, (chip_pad, chip_pad), logo)
        img.paste(chip.convert("RGB"), (200, 180))

    cx = W // 2 + 40
    cy_label = int(H * 0.42)

    eyebrow_font = _font(90, bold=True)
    head_font = _font(280, bold=True)
    sub_font = _font(88)

    label_txt = f"TRACK {track}"
    bb = d.textbbox((0, 0), label_txt, font=eyebrow_font)
    tw = bb[2] - bb[0]
    d.text((cx - tw // 2, cy_label), label_txt, fill=accent, font=eyebrow_font)

    bb = d.textbbox((0, 0), headline, font=head_font)
    hw = bb[2] - bb[0]
    hh = bb[3] - bb[1]
    cy_head = cy_label + 170
    d.text((cx - hw // 2, cy_head), headline, fill=INK, font=head_font)

    bb = d.textbbox((0, 0), sub, font=sub_font)
    sw = bb[2] - bb[0]
    cy_sub = cy_head + hh + 120
    d.text((cx - sw // 2, cy_sub), sub, fill=MUTED, font=sub_font)

    foot = label
    foot_font = _font(60)
    bb = d.textbbox((0, 0), foot, font=foot_font)
    d.text((cx - (bb[2] - bb[0]) // 2, int(H * 0.88)), foot, fill=DIM, font=foot_font)

    out_path = OUT / f"chapter_track_{track.lower()}.png"
    img.save(out_path, "PNG", optimize=True)
    print(f"wrote {out_path}  ({out_path.stat().st_size / 1024:.0f} KB)")


def main() -> None:
    _draw_card(
        track="A",
        label="1 of 2  ---  chapter one",
        headline="Why home wins.",
        sub="Decomposing the +3.88 point home-court edge.",
        accent=(60, 207, 142),
    )
    _draw_card(
        track="B",
        label="2 of 2  ---  chapter two",
        headline="How possessions chain.",
        sub="One-point-one million plays, one action at a time.",
        accent=(110, 176, 255),
    )


if __name__ == "__main__":
    main()
