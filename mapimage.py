"""The zoomed map as a picture, for terminals that show images (kitty's graphics
protocol: Ghostty, cmux, WezTerm), so map characters can be truly bigger.

render() draws a grid of map cells into a PNG; place() and delete() are the
escape codes that put it on screen over a rectangle of cells, and take it off.
Needs Pillow (./play runs with it).
"""
import base64
import io

from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Menlo.ttc"
IMAGE_ID = 7  # the one image this program shows
PALETTE = {  # xterm's colors, close to most themes
    "black": (60, 60, 60), "red": (205, 49, 49), "green": (13, 188, 121), "brown": (229, 229, 16),
    "blue": (36, 114, 200), "magenta": (188, 63, 188), "cyan": (17, 168, 205), "white": (229, 229, 229),
    "brightblack": (102, 102, 102), "brightred": (241, 76, 76), "brightgreen": (35, 209, 139),
    "brightbrown": (245, 245, 67), "brightblue": (59, 142, 234), "brightmagenta": (214, 112, 214),
    "brightcyan": (41, 184, 219), "brightwhite": (255, 255, 255), "default": (229, 229, 229)}
_fonts = {}


CURSOR = (128, 128, 128)  # the block marking you, like the terminal's cursor


def render(grid, cell_w, cell_h, scale, cursor=None):
    """PNG of grid (rows of (ch, fg, bold, reverse)); each map square is scale x scale cells.
    cursor is the (row, column) of the square to mark with a cursor block."""
    bw, bh = cell_w * scale, cell_h * scale  # scale can be fractional (1.25x...)
    img = Image.new("RGBA", (max(1, round(len(grid[0]) * bw)), max(1, round(len(grid) * bh))), (0, 0, 0, 0))
    size = max(8, int(bh * 0.8))
    font = _fonts.get(size) or _fonts.setdefault(size, ImageFont.truetype(FONT, size))
    draw = ImageDraw.Draw(img)
    for j, row in enumerate(grid):
        for i, (ch, fg, bold, reverse) in enumerate(row):
            color = PALETTE.get(("bright" + fg) if bold and not fg.startswith("bright") else fg, PALETTE["default"])
            x, y = i * bw, j * bh
            if (j, i) == cursor:
                draw.rectangle([x, y, x + bw - 1, y + bh - 1], fill=CURSOR)
            if reverse:
                draw.rectangle([x, y, x + bw - 1, y + bh - 1], fill=color)
                color = (0, 0, 0)
            if ch.strip():
                draw.text((x + bw / 2, y + bh / 2), ch, font=font, fill=color, anchor="mm")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def place(png, row, col, cols, rows):
    """Escape codes showing png stretched over cols x rows cells from (row, col), cursor unmoved."""
    data = base64.standard_b64encode(png).decode()
    chunks = [data[k:k + 4096] for k in range(0, len(data), 4096)] or [""]
    out = [delete(), f"\x1b[{row + 1};{col + 1}H"]
    for n, chunk in enumerate(chunks):
        more = 1 if n < len(chunks) - 1 else 0
        head = f"a=T,f=100,i={IMAGE_ID},c={cols},r={rows},C=1,q=2,m={more}" if n == 0 else f"m={more}"
        out.append(f"\x1b_G{head};{chunk}\x1b\\")
    return "".join(out)


def delete():
    return f"\x1b_Ga=d,d=I,i={IMAGE_ID},q=2\x1b\\"


if __name__ == "__main__":
    png = render([[("@", "default", True, False), ("d", "red", False, False)],
                  [("#", "default", False, False), (" ", "default", False, True)]], 9, 18, 2)
    assert png.startswith(b"\x89PNG")
    assert render([[("@", "default", False, False)]], 9, 18, 1.25, cursor=(0, 0)).startswith(b"\x89PNG")
    esc = place(png, 4, 3, 4, 4)
    assert esc.startswith(delete() + "\x1b[5;4H\x1b_Ga=T,f=100,i=7,c=4,r=4,C=1,q=2,m=")
    assert esc.endswith("\x1b\\")
    print("mapimage ok")
