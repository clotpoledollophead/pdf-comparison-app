#!/usr/bin/env python3
"""
Redline — a clean side-by-side PDF comparison UI.

Run:
    pip install streamlit pymupdf pillow numpy
    streamlit run app.py
"""

import io
import tempfile

import streamlit as st
from PIL import Image

import pdf_compare as engine

st.set_page_config(page_title="Redline · PDF compare", page_icon="▮",
                   layout="centered", initial_sidebar_state="collapsed")

# ----------------------------------------------------------------------------
# Styling — paper-white surface, ink type, an editorial serif wordmark,
# and the three semantic diff colors as the only accents.
# ----------------------------------------------------------------------------
RED, GREEN, AMBER = "#DC2626", "#16A34A", "#D97706"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=Inter:wght@400;500;600&display=swap');

.stApp {{ background:#FBFBFA; }}
#MainMenu, footer, header {{ visibility:hidden; }}
.block-container {{ max-width:760px; padding-top:3.2rem; padding-bottom:4rem;
    font-family:'Inter',system-ui,sans-serif; color:#1A1A1A; }}

.wordmark {{ font-family:'Newsreader',serif; font-size:2.7rem; font-weight:500;
    letter-spacing:-.01em; line-height:1; margin:0; }}
.wordmark .mark {{ color:{RED}; }}
.tagline {{ color:#6B6B6E; font-size:.96rem; margin:.55rem 0 0; }}
.rule {{ border:none; border-top:1px solid #E7E7E3; margin:1.8rem 0 1.4rem; }}

.eyebrow {{ font-size:.72rem; font-weight:600; letter-spacing:.09em;
    text-transform:uppercase; color:#9A9A9E; margin:0 0 .6rem; }}

/* legend / info bar */
.legend {{ display:flex; gap:1.6rem; align-items:center; justify-content:center;
    background:#F5F5F2; border:1px solid #E7E7E3; border-radius:10px;
    padding:.7rem 1rem; margin:.4rem 0 1.6rem; }}
.legend .item {{ display:flex; align-items:center; gap:.5rem;
    font-size:.86rem; color:#3A3A3C; }}
.legend .sw {{ width:26px; height:15px; border-radius:4px; display:inline-block; }}

/* uploader + button polish */
[data-testid="stFileUploaderDropzone"] {{ background:#fff; border:1.5px dashed #DADAD6;
    border-radius:12px; }}
.stButton>button {{ width:100%; background:#1A1A1A; color:#fff; border:none;
    border-radius:10px; padding:.7rem 1rem; font-weight:600; font-size:.96rem;
    font-family:'Inter',sans-serif; transition:transform .04s ease, background .15s; }}
.stButton>button:hover {{ background:#000; }}
.stButton>button:active {{ transform:translateY(1px); }}
.stDownloadButton>button {{ width:100%; background:#fff; color:#1A1A1A;
    border:1.5px solid #1A1A1A; border-radius:10px; padding:.7rem 1rem;
    font-weight:600; font-family:'Inter',sans-serif; }}
.stDownloadButton>button:hover {{ background:#1A1A1A; color:#fff; }}

.stat {{ display:inline-flex; align-items:center; gap:.45rem; margin-right:1.4rem;
    font-size:.92rem; color:#3A3A3C; }}
.stat b {{ font-weight:600; }}
.dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
.pagecap {{ font-size:.78rem; color:#9A9A9E; margin:.2rem 0 1.4rem; text-align:center; }}
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<p class="wordmark">Red<span class="mark">line</span></p>'
    '<p class="tagline">Compare two PDFs side by side. Differences are marked on both copies.</p>'
    '<hr class="rule">', unsafe_allow_html=True)

LEGEND_HTML = f"""
<div class="legend">
  <span class="item"><span class="sw" style="background:{RED}"></span>Deleted</span>
  <span class="item"><span class="sw" style="background:{GREEN}"></span>Added</span>
  <span class="item"><span class="sw" style="background:{AMBER}"></span>Changed</span>
</div>"""
st.markdown(LEGEND_HTML, unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------------
c1, c2 = st.columns(2, gap="medium")
with c1:
    st.markdown('<p class="eyebrow">Original · old</p>', unsafe_allow_html=True)
    old_file = st.file_uploader("old", type="pdf", label_visibility="collapsed", key="old")
with c2:
    st.markdown('<p class="eyebrow">Revised · new</p>', unsafe_allow_html=True)
    new_file = st.file_uploader("new", type="pdf", label_visibility="collapsed", key="new")

o1, o2, _ = st.columns([1, 1, 1])
ignore_case = o1.toggle("Ignore case", value=False)
high_detail = o2.toggle("High detail", value=False,
                        help="Sharper previews and export, larger file.")

run = st.button("Compare PDFs", type="primary", disabled=not (old_file and new_file))


def _save_tmp(uploaded):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(uploaded.getbuffer()); tmp.flush(); tmp.close()
    return tmp.name


if run and old_file and new_file:
    engine.COL_W = 1300 if high_detail else 900
    with st.spinner("Comparing…"):
        pa, pb = _save_tmp(old_file), _save_tmp(new_file)
        pages, stats, na, nb = engine.build_pages(pa, pb, ignore_case=ignore_case)
        pdf_bytes = engine.pages_to_pdf_bytes(pages)
        previews = []
        for pg in pages:
            b = io.BytesIO(); pg.save(b, format="PNG"); previews.append(b.getvalue())
    st.session_state.update(result=dict(pdf=pdf_bytes, previews=previews,
                                        stats=stats, na=na, nb=nb))

# ----------------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------------
res = st.session_state.get("result")
if res:
    s = res["stats"]
    st.markdown('<hr class="rule">', unsafe_allow_html=True)
    st.markdown(
        f'<div style="margin-bottom:1rem">'
        f'<span class="stat"><span class="dot" style="background:{RED}"></span>'
        f'<b>{s["removed"]}</b> deleted</span>'
        f'<span class="stat"><span class="dot" style="background:{GREEN}"></span>'
        f'<b>{s["added"]}</b> added</span>'
        f'<span class="stat"><span class="dot" style="background:{AMBER}"></span>'
        f'<b>{s["changed"]}</b> changed</span></div>', unsafe_allow_html=True)

    st.download_button("Download comparison PDF", res["pdf"],
                       file_name="comparison.pdf", mime="application/pdf")

    st.markdown(LEGEND_HTML, unsafe_allow_html=True)
    for i, png in enumerate(res["previews"]):
        st.image(png, use_container_width=True)
        cap = "Summary" if i == 0 else f"Page {i}"
        st.markdown(f'<p class="pagecap">{cap}</p>', unsafe_allow_html=True)
else:
    st.markdown('<p style="color:#9A9A9E;font-size:.9rem;margin-top:1.4rem">'
                'Upload both PDFs to begin. Different page counts are fine — '
                'surplus pages get a blank panel opposite them.</p>',
                unsafe_allow_html=True)
