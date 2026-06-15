"""Generate the application icon (assets/icon.ico) using Pillow."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageDraw, ImageFont

SIZES = [16, 24, 32, 48, 64, 128, 256]
OUT = Path(__file__).parent.parent / "assets" / "icon.ico"
OUT.parent.mkdir(exist_ok=True)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = max(1, size // 16)
    r = size // 6

    # Background rounded rectangle
    bg = "#1a1a2e"
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=r, fill=bg)

    # Accent band at top
    band_h = max(2, size // 10)
    d.rounded_rectangle(
        [pad, pad, size - pad, pad + band_h + r],
        radius=r, fill="#4a9eff"
    )
    if pad + band_h > pad + r:
        d.rectangle([pad, pad + r, size - pad, pad + band_h], fill="#4a9eff")

    # Three horizontal text lines (books / document metaphor)
    line_x1 = size * 0.22
    line_x2 = size * 0.78
    line_y_start = size * 0.38
    line_gap = size * 0.15
    line_h = max(1, size // 28)
    colors = ["#ffffff", "#4a9eff", "#8a9bb5"]
    widths = [line_x2, line_x2 * 0.82, line_x2 * 0.65]
    for i in range(3):
        y = line_y_start + i * line_gap
        d.rounded_rectangle(
            [line_x1, y, widths[i], y + line_h],
            radius=max(1, line_h // 2),
            fill=colors[i],
        )

    # Small arrow/translate symbol at bottom-right
    ar_size = size * 0.2
    ax = size * 0.68
    ay = size * 0.70
    d.polygon(
        [
            (ax, ay + ar_size * 0.4),
            (ax + ar_size * 0.6, ay),
            (ax + ar_size * 0.6, ay + ar_size * 0.3),
            (ax + ar_size, ay + ar_size * 0.3),
            (ax + ar_size, ay + ar_size * 0.7),
            (ax + ar_size * 0.6, ay + ar_size * 0.7),
            (ax + ar_size * 0.6, ay + ar_size),
        ],
        fill="#2ecc71",
    )

    return img


def main() -> None:
    images = [draw_icon(s) for s in SIZES]
    images[0].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[1:],
    )
    print(f"Icon saved: {OUT}")


if __name__ == "__main__":
    main()
