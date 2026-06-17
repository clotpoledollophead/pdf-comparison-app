#!/usr/bin/env python3
"""
pdf_compare.py — Side-by-side visual diff of two PDFs.

Engine + CLI. The UI lives in app.py and imports build_pages()/pages_to_pdf_bytes().

Each output page shows the OLD document on the left and the NEW document on the
right, with differences highlighted on BOTH sides:

    red    = deleted  (text only in the left/old PDF)
    green  = added    (text only in the right/new PDF)
    amber  = changed  (text replaced between the two)

A word-level diff over the whole document drives the highlights, so insertions
and deletions don't smear the rest of a page as "all different". Pages with no
extractable text (scanned/image PDFs) fall back to a pixel-region diff. PDFs of
different lengths are handled: surplus pages of the longer document get a blank
placeholder panel opposite them.

CLI:
    python3 pdf_compare.py old.pdf new.pdf -o diff.pdf [--ignore-case] [--dpi N]
"""

import argparse
import difflib
import io
import sys
from dataclasses import dataclass

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------------
# Layout / palette
# ----------------------------------------------------------------------------
COL_W = 900            # rendered width (px) of each document column
GUTTER = 28
MARGIN = 26
HEADER_H = 52
LEGEND_H = 40

COLOR_REMOVED = (220, 38, 38)     # red    — deleted
COLOR_ADDED = (22, 163, 74)       # green  — added
COLOR_CHANGED = (217, 119, 6)     # amber  — changed
HILITE_ALPHA = 72
LABELS = {COLOR_REMOVED: "Deleted", COLOR_ADDED: "Added", COLOR_CHANGED: "Changed"}

BG = (255, 255, 255)
BLANK_BG = (238, 238, 240)
HEADER_BG = (26, 26, 26)
HEADER_FG = (255, 255, 255)
HEADER_SUB = (165, 165, 168)
LEGEND_BG = (246, 246, 244)
BORDER = (228, 228, 225)


@dataclass
class Word:
    page: int
    rect: fitz.Rect
    text: str


def _font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for p in (f"/usr/share/fonts/truetype/dejavu/{name}",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ----------------------------------------------------------------------------
# Extraction + diff
# ----------------------------------------------------------------------------
def extract_words(doc):
    out = []
    for pno in range(doc.page_count):
        for x0, y0, x1, y1, w, *_ in doc[pno].get_text("words"):
            out.append(Word(pno, fitz.Rect(x0, y0, x1, y1), w))
    return out


def diff_words(a, b, ignore_case):
    norm = (lambda s: s.lower()) if ignore_case else (lambda s: s)
    sm = difflib.SequenceMatcher(a=[norm(w.text) for w in a],
                                 b=[norm(w.text) for w in b], autojunk=False)
    left, right = {}, {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "delete":
            for i in range(i1, i2):
                left[i] = COLOR_REMOVED
        elif tag == "insert":
            for j in range(j1, j2):
                right[j] = COLOR_ADDED
        elif tag == "replace":
            for i in range(i1, i2):
                left[i] = COLOR_CHANGED
            for j in range(j1, j2):
                right[j] = COLOR_CHANGED
    return left, right


def boxes_per_page(words, colors, npages):
    per = {p: [] for p in range(npages)}
    for idx, color in colors.items():
        w = words[idx]
        per[w.page].append((w.rect, color))
    return per


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------
def render_page(page, highlights):
    zoom = COL_W / page.rect.width if page.rect.width else 1.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    if highlights:
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for rect, color in highlights:
            box = (rect.x0 * zoom - 1, rect.y0 * zoom - 1,
                   rect.x1 * zoom + 1, rect.y1 * zoom + 1)
            od.rectangle(box, fill=(*color, HILITE_ALPHA), outline=(*color, 175), width=1)
        img = Image.alpha_composite(img, overlay)
    return img.convert("RGB")


def pixel_diff_overlays(left, right, thresh=40):
    w, h = min(left.width, right.width), min(left.height, right.height)
    la = np.asarray(left.resize((w, h)).convert("L"), dtype=np.int16)
    ra = np.asarray(right.resize((w, h)).convert("L"), dtype=np.int16)
    mask = np.abs(la - ra) > thresh
    block = max(8, w // 120)
    ov = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(0, h, block):
        for x in range(0, w, block):
            if mask[y:y + block, x:x + block].mean() > 0.12:
                ov[y:y + block, x:x + block] = (*COLOR_CHANGED, HILITE_ALPHA)
    overlay = Image.fromarray(ov, "RGBA")
    return overlay.resize(left.size), overlay.resize(right.size)


def fit_to_column(img):
    if img.width != COL_W:
        img = img.resize((COL_W, round(img.height * COL_W / img.width)))
    return img


def blank_panel(height):
    img = Image.new("RGB", (COL_W, max(height, 200)), BLANK_BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, COL_W - 1, img.height - 1), outline=BORDER, width=1)
    f = _font(24)
    label = "No corresponding page"
    d.text(((COL_W - d.textlength(label, font=f)) / 2, img.height / 2 - 14),
           label, fill=(150, 150, 154), font=f)
    return img


def _ellipsize(draw, text, font, max_w):
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def draw_legend(draw, x, y, w):
    """The info bar: three swatch+label chips, centred in a light strip."""
    draw.rectangle((x, y, x + w, y + LEGEND_H), fill=LEGEND_BG)
    draw.line((x, y, x + w, y), fill=BORDER, width=1)
    draw.line((x, y + LEGEND_H, x + w, y + LEGEND_H), fill=BORDER, width=1)
    f = _font(17)
    sw, gap, pad = 22, 8, 34            # swatch, swatch-label gap, chip padding
    items = [(COLOR_REMOVED, "Deleted"), (COLOR_ADDED, "Added"), (COLOR_CHANGED, "Changed")]
    widths = [sw + gap + draw.textlength(lbl, font=f) for _, lbl in items]
    total = sum(widths) + pad * (len(items) - 1)
    cx = x + (w - total) / 2
    cy = y + LEGEND_H / 2
    for (color, lbl), iw in zip(items, widths):
        draw.rounded_rectangle((cx, cy - 8, cx + sw, cy + 8), radius=4,
                               fill=(*color, 255), outline=(*color, 255))
        draw.text((cx + sw + gap, cy - 9), lbl, fill=(60, 60, 62), font=f)
        cx += iw + pad


def compose_pair(left_img, right_img, page_no, name_l, name_r):
    left_img, right_img = fit_to_column(left_img), fit_to_column(right_img)
    body_h = max(left_img.height, right_img.height)
    W = MARGIN * 2 + COL_W * 2 + GUTTER
    head = HEADER_H + LEGEND_H
    H = MARGIN + head + body_h + MARGIN
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    # header band
    d.rectangle((0, 0, W, HEADER_H), fill=HEADER_BG)
    lx, rx = MARGIN, MARGIN + COL_W + GUTTER
    fn = _font(21, bold=True)
    d.text((lx, 9), _ellipsize(d, name_l, fn, COL_W - 90), fill=HEADER_FG, font=fn)
    d.text((rx, 9), _ellipsize(d, name_r, fn, COL_W - 90), fill=HEADER_FG, font=fn)
    pg = f"page {page_no}"
    fp = _font(15)
    d.text((W - MARGIN - d.textlength(pg, font=fp), 14), pg, fill=HEADER_SUB, font=fp)

    # info bar
    draw_legend(d, 0, HEADER_H, W)

    # panels
    top = head + MARGIN
    for x, im in ((lx, left_img), (rx, right_img)):
        canvas.paste(im, (x, top))
        d.rectangle((x, top, x + COL_W - 1, top + im.height - 1), outline=BORDER, width=1)
    return canvas


def summary_page(stats, name_l, name_r):
    W = MARGIN * 2 + COL_W * 2 + GUTTER
    H = 380
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, W, 78), fill=HEADER_BG)
    d.text((MARGIN, 22), "Comparison summary", fill=HEADER_FG, font=_font(30, bold=True))
    draw_legend(d, 0, 78, W)

    y = 78 + LEGEND_H + 28
    f = _font(21)
    d.text((MARGIN, y), f"Left · old      {name_l}   ({stats['pages_l']} pages)",
           fill=(40, 40, 40), font=f); y += 34
    d.text((MARGIN, y), f"Right · new   {name_r}   ({stats['pages_r']} pages)",
           fill=(40, 40, 40), font=f); y += 50
    for color, n in ((COLOR_REMOVED, stats["removed"]),
                     (COLOR_ADDED, stats["added"]),
                     (COLOR_CHANGED, stats["changed"])):
        d.rounded_rectangle((MARGIN, y + 2, MARGIN + 22, y + 20), radius=4, fill=color)
        d.text((MARGIN + 36, y), f"{LABELS[color]}: {n} words", fill=(50, 50, 52), font=f)
        y += 34
    d.text((MARGIN, y + 14),
           "Highlights are word-level; image-only pages use a pixel region diff.",
           fill=(125, 125, 128), font=_font(15))
    return canvas


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
def build_pages(path_a, path_b, ignore_case=False, include_summary=True):
    """Return (list_of_PIL_pages, stats_dict, name_a, name_b)."""
    doc_a, doc_b = fitz.open(path_a), fitz.open(path_b)
    words_a, words_b = extract_words(doc_a), extract_words(doc_b)
    left_colors, right_colors = diff_words(words_a, words_b, ignore_case)
    boxes_a = boxes_per_page(words_a, left_colors, doc_a.page_count)
    boxes_b = boxes_per_page(words_b, right_colors, doc_b.page_count)
    name_a, name_b = path_a.split("/")[-1], path_b.split("/")[-1]

    stats = {
        "pages_l": doc_a.page_count, "pages_r": doc_b.page_count,
        "removed": sum(c == COLOR_REMOVED for c in left_colors.values()),
        "added": sum(c == COLOR_ADDED for c in right_colors.values()),
        "changed": sum(c == COLOR_CHANGED for c in left_colors.values()),
    }

    pages = []
    if include_summary:
        pages.append(summary_page(stats, name_a, name_b))

    for i in range(max(doc_a.page_count, doc_b.page_count)):
        has_a, has_b = i < doc_a.page_count, i < doc_b.page_count
        left_img = render_page(doc_a[i], boxes_a.get(i, [])) if has_a else None
        right_img = render_page(doc_b[i], boxes_b.get(i, [])) if has_b else None

        if has_a and has_b and not boxes_a.get(i) and not boxes_b.get(i):
            if not (doc_a[i].get_text("words") and doc_b[i].get_text("words")):
                ol, orr = pixel_diff_overlays(left_img, right_img)
                left_img = Image.alpha_composite(left_img.convert("RGBA"), ol).convert("RGB")
                right_img = Image.alpha_composite(right_img.convert("RGBA"), orr).convert("RGB")

        if not has_a:
            right_img = fit_to_column(right_img)
            left_img = blank_panel(right_img.height)
        if not has_b:
            left_img = fit_to_column(left_img)
            right_img = blank_panel(left_img.height)

        pages.append(compose_pair(left_img, right_img, i + 1, name_a, name_b))
    return pages, stats, name_a, name_b


def pages_to_pdf_bytes(pages):
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True,
                  append_images=pages[1:], resolution=150.0)
    return buf.getvalue()


def compare(path_a, path_b, out_path, ignore_case=False, dpi=None, no_summary=False):
    if dpi:
        global COL_W
        COL_W = max(400, round(dpi * 8.5))
    pages, *_ = build_pages(path_a, path_b, ignore_case, include_summary=not no_summary)
    if not pages:
        print("Nothing to compare.", file=sys.stderr)
        sys.exit(1)
    with open(out_path, "wb") as fh:
        fh.write(pages_to_pdf_bytes(pages))
    print(f"Wrote {out_path}  ({len(pages)} pages)")


def main():
    ap = argparse.ArgumentParser(description="Side-by-side visual diff of two PDFs.")
    ap.add_argument("old_pdf"); ap.add_argument("new_pdf")
    ap.add_argument("-o", "--output", default="comparison.pdf")
    ap.add_argument("--ignore-case", action="store_true")
    ap.add_argument("--dpi", type=int, default=None)
    ap.add_argument("--no-summary", action="store_true")
    a = ap.parse_args()
    compare(a.old_pdf, a.new_pdf, a.output, a.ignore_case, a.dpi, a.no_summary)


if __name__ == "__main__":
    main()
