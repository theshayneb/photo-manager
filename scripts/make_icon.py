"""Draws the app icon: photo_manager/assets/icon.png and icon.ico.

Run: python scripts/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

S = 1024  # drawn large, then scaled down for smooth edges
OUT = Path(__file__).resolve().parents[1] / "photo_manager" / "assets"


def vertical_gradient(size, top, bottom):
    w, h = size
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return grad.resize((w, h))


def rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def draw() -> Image.Image:
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # Background tile: deep blue gradient, rounded.
    tile = vertical_gradient((S, S), (37, 99, 235), (30, 41, 82))
    icon.paste(tile, (0, 0), rounded_mask((S, S), 220))

    # Photo card with a white border.
    card_box = (150, 190, 874, 790)
    card = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((card_box[0] + 18, card_box[1] + 28, card_box[2] + 18, card_box[3] + 28), 60,
                        fill=(0, 0, 0, 90))  # shadow
    d.rounded_rectangle(card_box, 60, fill=(255, 255, 255, 255))
    icon.alpha_composite(card)

    # The picture: sky, sun, two mountains.
    inner = (card_box[0] + 48, card_box[1] + 48, card_box[2] - 48, card_box[3] - 48)
    iw, ih = inner[2] - inner[0], inner[3] - inner[1]
    pic = Image.new("RGBA", (iw, ih))
    pic.paste(vertical_gradient((iw, ih), (125, 211, 252), (224, 242, 254)))
    p = ImageDraw.Draw(pic)
    p.ellipse((iw * 0.62, ih * 0.12, iw * 0.84, ih * 0.40), fill=(250, 204, 21))
    p.polygon([(0, ih), (iw * 0.34, ih * 0.38), (iw * 0.72, ih)], fill=(21, 128, 61))
    p.polygon([(iw * 0.36, ih), (iw * 0.66, ih * 0.54), (iw, ih * 0.92), (iw, ih)], fill=(22, 101, 52))
    icon.paste(pic, inner[:2], rounded_mask((iw, ih), 28))

    # A keyword tag in the corner.
    tag = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    t = ImageDraw.Draw(tag)
    x, y = 610, 650
    t.polygon([(x, y + 95), (x + 95, y), (x + 290, y), (x + 290, y + 190), (x + 95, y + 190)],
              fill=(249, 115, 22))
    t.ellipse((x + 85, y + 75, x + 125, y + 115), fill=(255, 255, 255))
    icon.alpha_composite(tag)
    return icon


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "icon.png")
    big.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT / "icon.png", OUT / "icon.ico")


if __name__ == "__main__":
    main()
