# Redline

Compare two PDFs side by side and export a new PDF with differences highlighted
on **both** copies. Works with documents of different lengths.

![sample](comparison_sample.pdf)

| Color | Meaning |
|-------|---------|
| 🟥 Red | Deleted — text present only in the old PDF |
| 🟩 Green | Added — text present only in the new PDF |
| 🟧 Amber | Changed — text replaced between the two |

A legend/info bar is shown in the app and baked into every exported page, so the
output PDF is self-explanatory on its own.

---

## Install

```bash
pip install streamlit pymupdf pillow numpy
```

Python 3.10+.

## Use the app

```bash
streamlit run app.py
```

Upload the original and revised PDF, click **Compare PDFs**, preview each page
inline, and download the result.

Options:
- **Ignore case** — treat words that differ only in capitalization as equal.
- **High detail** — sharper previews and export (larger file).

## Use the command line

```bash
# basic
python3 pdf_compare.py old.pdf new.pdf -o comparison.pdf

# ignore case, higher render detail
python3 pdf_compare.py old.pdf new.pdf -o comparison.pdf --ignore-case --dpi 150

# drop the leading summary page
python3 pdf_compare.py old.pdf new.pdf -o comparison.pdf --no-summary
```

| Flag | Description |
|------|-------------|
| `-o, --output` | Output path (default `comparison.pdf`) |
| `--ignore-case` | Case-insensitive word matching |
| `--dpi N` | Render detail; higher is sharper and larger |
| `--no-summary` | Skip the summary page |

---

## How it works

1. **Extract** — every word and its bounding box is pulled from each PDF with
   PyMuPDF, in reading order, as one flat sequence per document.
2. **Diff** — a word-level `difflib` comparison runs over the whole document
   (not page by page), so a single insertion or deletion doesn't smear the rest
   of a page as different. Opcodes map to colors: delete → red, insert → green,
   replace → amber.
3. **Render** — each page is rasterized and translucent highlight boxes are
   drawn over the differing words using their bounding boxes, so marks land
   exactly on the right tokens.
4. **Compose** — old on the left, new on the right, with a header, the legend
   bar, and page panels. Pages are assembled into a single output PDF.

**Different lengths.** Pages are paired positionally (page *i* vs page *i*). The
shorter document gets a blank "No corresponding page" panel opposite the surplus
pages of the longer one.

**Scanned / image PDFs.** When a paired page has no extractable text, the tool
falls back to a coarse pixel-region diff so visual differences are still marked
in amber.

---

## Project structure

```
app.py                  Streamlit UI (Redline)
pdf_compare.py          Comparison engine + CLI
README.md               This file
comparison_sample.pdf   Example output (3-page vs 4-page input)
```

The engine exposes a small API the UI builds on:

```python
import pdf_compare as engine

pages, stats, name_a, name_b = engine.build_pages("old.pdf", "new.pdf",
                                                  ignore_case=False)
pdf_bytes = engine.pages_to_pdf_bytes(pages)
# stats -> {"pages_l", "pages_r", "removed", "added", "changed"}
```

---

## Limitations

- **Positional page pairing.** If a whole page is inserted mid-document, pages
  after it pair "off by one" — the word-level highlights stay correct, but the
  side-by-side alignment shifts. Fine for revisions, less so for heavy
  restructuring.
- **Counts are word-level**, not character-level, so a one-letter typo counts as
  one changed word.
- The **pixel fallback flags regions**, not exact pixels.

## Requirements

`streamlit` (app only), `pymupdf`, `pillow`, `numpy`.
