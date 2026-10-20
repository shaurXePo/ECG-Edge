"""appui.py - look and feel for the Streamlit app: CSS theme, small HTML components, and matplotlib plots.

Design language: dark "monitoring console" chrome (see .streamlit/config.toml) with traces drawn on ECG paper
(1 mm = 40 ms x 0.1 mV small boxes, 5 mm = 200 ms x 0.5 mV large boxes), one consistent colour per beat class.
All user-visible strings that reach HTML come from constants in this repo, never from uploaded files.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

# ------------------------------------------------------------------ palette
BG, CARD, BORDER = "#0B1220", "#111B2E", "#1F2A44"
TEXT, MUTED, ACCENT = "#E6EDF7", "#8FA3BF", "#2DD4BF"
CLASS_COLORS = ["#34D399", "#FBBF24", "#F87171", "#A78BFA"]          # N, S, V, F
CLASS_NAMES = ["Normal", "Supraventricular", "Ventricular", "Fusion"]
CLASS_LETTERS = ["N", "S", "V", "F"]
PAPER, PAPER_MINOR, PAPER_MAJOR, INK = "#FFF7F5", "#F6D3D0", "#EBA9A5", "#1A1A1A"

FILTER_LABELS = {
    "fir127_f64": "FIR 127 · float64 (reference)",
    "fir127_q15": "FIR 127 · Q15 truncating (CMSIS)",
    "fir127_q15r": "FIR 127 · Q15 rounding",
    "fir63_f64": "FIR 63 · float64",
    "iir2_f64": "Butterworth IIR · float64",
    "iir2_q15": "Butterworth IIR · Q15 (fails)",
    "iirh_f64": "First-order-HP IIR · float64",
    "iirh_q15": "First-order-HP IIR · Q15 truncating",
    "iirh_q15r": "First-order-HP IIR · Q15 rounding",
    "raw": "No filter (raw input)",
}

_RC = {
    "figure.facecolor": CARD, "savefig.facecolor": CARD, "axes.facecolor": CARD,
    "axes.edgecolor": BORDER, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": TEXT, "axes.titlecolor": TEXT, "grid.color": BORDER, "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
}


# ------------------------------------------------------------------ CSS + HTML components
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, .stApp, [data-testid="stMarkdownContainer"] {{ font-family: 'Inter', system-ui, -apple-system, sans-serif; }}
.stApp {{ background: radial-gradient(1100px 520px at 12% -8%, #16264a 0%, {BG} 58%); }}
header[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer {{ visibility: hidden; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1280px; }}
[data-testid="stSidebar"] {{ background: #0D1524; border-right: 1px solid {BORDER}; }}
[data-testid="stSidebar"] .block-container {{ padding-top: 1rem; }}
h1, h2, h3, h4 {{ letter-spacing: -0.015em; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background: {CARD}; border: 1px solid {BORDER} !important; border-radius: 14px; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; border-bottom: 1px solid {BORDER}; }}
.stTabs [data-baseweb="tab"] {{ height: 44px; padding: 0 16px; border-radius: 10px 10px 0 0; color: {MUTED}; font-weight: 600; }}
.stTabs [aria-selected="true"] {{ color: {ACCENT}; background: rgba(45,212,191,0.08); }}
.hero {{ padding: 26px 30px; border-radius: 18px; border: 1px solid {BORDER};
  background: linear-gradient(135deg, rgba(45,212,191,0.14) 0%, rgba(99,102,241,0.12) 55%, rgba(17,27,46,0.9) 100%); }}
.hero h1 {{ margin: 0 0 6px 0; font-size: 2.05rem; font-weight: 800; color: {TEXT}; }}
.hero p {{ margin: 0 0 14px 0; color: {MUTED}; font-size: 1.02rem; max-width: 860px; line-height: 1.5; }}
.chip {{ display: inline-block; padding: 4px 11px; margin: 0 6px 6px 0; border-radius: 999px; font-size: 0.78rem;
  font-weight: 600; color: {ACCENT}; background: rgba(45,212,191,0.10); border: 1px solid rgba(45,212,191,0.35); }}
.kpis {{ display: grid; gap: 14px; margin: 16px 0 6px 0; }}
.kpi {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; padding: 16px 18px; }}
.kpi .v {{ font-size: 1.85rem; font-weight: 800; line-height: 1.1; }}
.kpi .l {{ color: {MUTED}; font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }}
.kpi .s {{ color: {MUTED}; font-size: 0.8rem; margin-top: 6px; }}
.flow {{ display: flex; align-items: stretch; flex-wrap: wrap; gap: 8px; margin: 10px 0 4px 0; }}
.step {{ flex: 1 1 130px; background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; padding: 11px 13px; min-width: 120px; }}
.step.on {{ border-color: {ACCENT}; box-shadow: 0 0 0 1px rgba(45,212,191,0.35), 0 0 22px rgba(45,212,191,0.12); }}
.step .n {{ color: {ACCENT}; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; }}
.step .t {{ color: {TEXT}; font-weight: 700; font-size: 0.93rem; margin: 2px 0; }}
.step .d {{ color: {MUTED}; font-size: 0.76rem; line-height: 1.35; }}
.arrow {{ align-self: center; color: {MUTED}; font-size: 1.2rem; }}
.pill {{ display: inline-block; padding: 3px 12px; border-radius: 999px; font-weight: 700; font-size: 0.85rem; color: #0B1220; }}
.callout {{ border-radius: 12px; padding: 12px 15px; margin: 8px 0; font-size: 0.9rem; line-height: 1.5; border: 1px solid; }}
.callout b {{ display: block; margin-bottom: 2px; }}
.callout.warn {{ background: rgba(245,158,11,0.10); border-color: rgba(245,158,11,0.45); color: #FCD9A1; }}
.callout.bad  {{ background: rgba(239,68,68,0.10);  border-color: rgba(239,68,68,0.45);  color: #FBC5C5; }}
.callout.info {{ background: rgba(45,212,191,0.08); border-color: rgba(45,212,191,0.35); color: #BFEFE7; }}
.pbar {{ display: flex; align-items: center; gap: 10px; margin: 7px 0; font-size: 0.85rem; }}
.pbar .lab {{ width: 112px; color: {MUTED}; }}
.pbar .trk {{ flex: 1; height: 10px; background: #0B1424; border-radius: 6px; overflow: hidden; }}
.pbar .fil {{ height: 100%; border-radius: 6px; }}
.pbar .val {{ width: 52px; text-align: right; font-variant-numeric: tabular-nums; color: {TEXT}; }}
.dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; }}
.muted {{ color: {MUTED}; font-size: 0.82rem; }}
.brand {{ font-weight: 800; font-size: 1.25rem; color: {TEXT}; }}
.brand span {{ color: {ACCENT}; }}
</style>
"""


def inject_css(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(st, title: str, subtitle: str, chips) -> None:
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p>' +
                "".join(f'<span class="chip">{c}</span>' for c in chips) + "</div>", unsafe_allow_html=True)


def kpi_row(st, items) -> None:
    """items: (label, value, sub, colour). Rendered as one responsive grid."""
    cells = "".join(f'<div class="kpi"><div class="l">{l}</div><div class="v" style="color:{c}">{v}</div>'
                    f'<div class="s">{s}</div></div>' for l, v, s, c in items)
    st.markdown(f'<div class="kpis" style="grid-template-columns:repeat({len(items)},minmax(0,1fr))">{cells}</div>',
                unsafe_allow_html=True)


def pipeline_diagram(st, filter_label: str) -> None:
    steps = [("1", "ECG in", "single lead, int16 Q15, ±5 mV, 360 Hz", False),
             ("2", "Filter", filter_label, True),
             ("3", "R-peak detector", "Pan-Tompkins style: derivative, square, integrate, adaptive threshold", False),
             ("4", "Beat window + RR", "256 samples around R plus 4 timing features", False),
             ("5", "Tiny CNN", "3 conv layers + hidden layer, 7,612 parameters", False),
             ("6", "N · S · V · F", "per-beat class with probabilities", False)]
    parts = []
    for i, (n, t, d, on) in enumerate(steps):
        parts.append(f'<div class="step{" on" if on else ""}"><div class="n">STEP {n}</div>'
                     f'<div class="t">{t}</div><div class="d">{d}</div></div>')
        if i < len(steps) - 1:
            parts.append('<div class="arrow">›</div>')
    st.markdown(f'<div class="flow">{"".join(parts)}</div>', unsafe_allow_html=True)


def pill(k: int) -> str:
    return f'<span class="pill" style="background:{CLASS_COLORS[k]}">{CLASS_LETTERS[k]} · {CLASS_NAMES[k]}</span>'


def prob_bars(st, prob) -> None:
    rows = "".join(f'<div class="pbar"><div class="lab">{CLASS_NAMES[k]}</div><div class="trk"><div class="fil" '
                   f'style="width:{max(p * 100, 0.6):.1f}%;background:{CLASS_COLORS[k]}"></div></div>'
                   f'<div class="val">{p * 100:.1f}%</div></div>' for k, p in enumerate(prob))
    st.markdown(rows, unsafe_allow_html=True)


def callout(st, kind: str, title: str, text: str) -> None:
    st.markdown(f'<div class="callout {kind}"><b>{title}</b>{text}</div>', unsafe_allow_html=True)


def status(st, items) -> None:
    """items: (ok: bool, text)."""
    st.markdown("".join(f'<div class="muted"><span class="dot" style="background:{"#34D399" if ok else "#F59E0B"}"></span>{t}</div>'
                        for ok, t in items), unsafe_allow_html=True)


# ------------------------------------------------------------------ plots
def _paper(ax, x0, x1, y0, y1, minor_x, major_x, minor_y, major_y):
    ax.set_facecolor(PAPER)
    for ticks, fn, color, lw in [(np.arange(np.ceil(x0 / minor_x) * minor_x, x1, minor_x), ax.axvline, PAPER_MINOR, 0.4),
                                 (np.arange(np.ceil(y0 / minor_y) * minor_y, y1, minor_y), ax.axhline, PAPER_MINOR, 0.4),
                                 (np.arange(np.ceil(x0 / major_x) * major_x, x1, major_x), ax.axvline, PAPER_MAJOR, 0.8),
                                 (np.arange(np.ceil(y0 / major_y) * major_y, y1, major_y), ax.axhline, PAPER_MAJOR, 0.8)]:
        for t in ticks:
            fn(t, color=color, lw=lw, zorder=0)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)
    for s in ax.spines.values():
        s.set_visible(False)


def _ylim(y, pad=0.25):
    lo, hi = float(np.min(y)), float(np.max(y))
    span = max(hi - lo, 0.6)
    return lo - pad * span, hi + pad * span


def plot_timeline(y_mv, r, pred, t0_s: float, dur_s: float = 10.0, fs: int = 360):
    a, b = int(t0_s * fs), int(min(t0_s + dur_s, len(y_mv) / fs) * fs)
    t = np.arange(a, b) / fs
    seg = y_mv[a:b]
    with plt.rc_context(_RC):
        fig, ax = plt.subplots(figsize=(11, 3.1))
        y0, y1 = _ylim(seg, 0.30)
        _paper(ax, t[0], t[-1], y0, y1, 0.04, 0.2, 0.1, 0.5)
        ax.plot(t, seg, color=INK, lw=1.0, zorder=3)
        for c, k in zip(r, pred):
            if a <= c < b:
                ax.plot(c / fs, y1 - 0.09 * (y1 - y0), "v", color=CLASS_COLORS[k], ms=9, mec="#0B1220", mew=0.8, zorder=4)
        for k, n in enumerate(CLASS_LETTERS):
            ax.plot([], [], "v", color=CLASS_COLORS[k], label=f"{n} · {CLASS_NAMES[k]}", mec="#0B1220")
        ax.legend(ncol=4, loc="lower center", bbox_to_anchor=(0.5, 1.0), fontsize=8, labelcolor=MUTED)
        ax.set_xticks(np.arange(np.ceil(t[0]), t[-1], 1.0))
        ax.set_yticks([]); ax.set_xlabel("time [s]")
        fig.tight_layout()
    return fig


def plot_filter_lab(t, x_in, y_out, y_err_lsb, out_label: str, delay_ms: float):
    n = 3 if y_err_lsb is not None else 2
    with plt.rc_context(_RC):
        fig, axes = plt.subplots(n, 1, figsize=(11, 2.15 * n), sharex=True)
        for ax, y, lab in [(axes[0], x_in, "input [mV]"), (axes[1], y_out, f"{out_label} [mV]")]:
            y0, y1 = _ylim(y, 0.2)
            _paper(ax, t[0], t[-1], y0, y1, 0.04, 0.2, 0.1, 0.5)
            ax.plot(t, y, color=INK, lw=0.9, zorder=3)
            ax.set_ylabel(lab, fontsize=8); ax.set_yticks([])
        if y_err_lsb is not None:
            ax = axes[2]
            ax.plot(t, y_err_lsb, color="#F87171", lw=0.9)
            ax.axhline(0, color=BORDER, lw=0.8)
            ax.set_ylabel("error vs float\n[int16 LSB]", fontsize=8)
            ax.grid(True, color=BORDER, lw=0.4)
        axes[-1].set_xlabel(f"time [s]   (output shifted left by the {delay_ms:.0f} ms group delay)")
        fig.tight_layout()
    return fig


def plot_response(f, db_float, db_fixed, title: str):
    with plt.rc_context(_RC):
        fig, ax = plt.subplots(figsize=(6.2, 3.3))
        ax.axvspan(0.5, 40, color=ACCENT, alpha=0.07, lw=0)
        ax.axvline(60, color=MUTED, lw=0.8, ls=":")
        ax.semilogx(f[1:], db_float[1:], color=ACCENT, lw=1.8, label="float64 design")
        if db_fixed is not None:
            ax.semilogx(f[1:], db_fixed[1:], color="#FBBF24", lw=1.4, ls="--", label="Q15 coefficients")
        ax.set_xlim(0.1, 180); ax.set_ylim(-70, 6)
        ax.set_xlabel("frequency [Hz]"); ax.set_ylabel("gain [dB]")
        ax.grid(True, which="both", color=BORDER, lw=0.4)
        ax.text(0.55, -66, "pass band 0.5–40 Hz", color=MUTED, fontsize=7.5)
        ax.text(62, -66, "60 Hz", color=MUTED, fontsize=7.5)
        ax.set_title(title, fontsize=9, loc="left")
        ax.legend(loc="lower left", bbox_to_anchor=(0.0, 0.08), fontsize=8, labelcolor=MUTED)
        fig.tight_layout()
    return fig


_OCC = LinearSegmentedColormap.from_list("occ", [(0.97, 0.25, 0.25, 0.0), (0.97, 0.25, 0.25, 0.62)])


def plot_beat(tt_ms, window, heat, title: str):
    with plt.rc_context(_RC):
        fig, ax = plt.subplots(figsize=(6.4, 3.2))
        y0, y1 = _ylim(window, 0.25)
        _paper(ax, tt_ms[0], tt_ms[-1], y0, y1, 40, 200, 0.1, 0.5)
        h = np.clip(heat, 0, None)
        if h.max() > 0:
            ax.imshow(h[None, :], extent=[tt_ms[0], tt_ms[-1], y0, y1], aspect="auto", cmap=_OCC,
                      vmin=0, vmax=h.max(), zorder=1, interpolation="bilinear")
        ax.plot(tt_ms, window, color=INK, lw=1.3, zorder=3)
        ax.axvline(0, color="#444", lw=0.7, ls="--", zorder=2)
        ax.set_yticks([]); ax.set_xlabel("time from R peak [ms]")
        ax.set_title(title, fontsize=9.5, loc="left")
        fig.tight_layout()
    return fig


def plot_confusion(cm):
    cm = np.asarray(cm)
    norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
    with plt.rc_context(_RC):
        fig, ax = plt.subplots(figsize=(4.6, 3.6))
        ax.imshow(norm, cmap=LinearSegmentedColormap.from_list("c", [CARD, "#0F766E", ACCENT]), vmin=0, vmax=1)
        for i in range(4):
            for j in range(4):
                ax.text(j, i, f"{cm[i, j]:,}", ha="center", va="center", fontsize=9,
                        color="#0B1220" if norm[i, j] > 0.55 else TEXT, fontweight="bold" if i == j else "normal")
        ax.set_xticks(range(4), CLASS_LETTERS); ax.set_yticks(range(4), CLASS_LETTERS)
        ax.set_xlabel("predicted"); ax.set_ylabel("annotated")
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
        fig.tight_layout()
    return fig


def plot_agreement(names, pct_changed, names2, v_ppv, flags, ppv_ref):
    """Two panels: % of beats whose prediction changes vs the float twin, and V precision per filter.
    flags[i] marks a fixed-point filter whose V precision fell clearly below its own float twin."""
    with plt.rc_context(_RC):
        fig, (a, b) = plt.subplots(1, 2, figsize=(10.5, 3.3), gridspec_kw={"width_ratios": [1, 1.25]})
        a.barh(range(len(names)), pct_changed, height=0.62,
               color=["#F87171" if v > 1.0 else ACCENT for v in pct_changed])
        for i, v in enumerate(pct_changed):
            a.text(v + 0.1, i, f"{v:.1f}%", va="center", fontsize=8.5, color=TEXT)
        a.set_yticks(range(len(names)), names); a.invert_yaxis()
        a.set_xlim(0, max(max(pct_changed) * 1.3, 1.0))
        a.set_title("Beats whose predicted class changes vs the float twin", fontsize=9, loc="left")
        a.grid(True, axis="x", color=BORDER, lw=0.4)
        b.barh(range(len(names2)), v_ppv, height=0.62,
               color=["#F87171" if f else "#64748B" for f in flags])
        for i, v in enumerate(v_ppv):
            b.text(v + 0.01, i, f"{v:.2f}", va="center", fontsize=8.5, color=TEXT)
        b.set_yticks(range(len(names2)), names2); b.invert_yaxis(); b.set_xlim(0, 1.05)
        b.axvline(ppv_ref, color=ACCENT, lw=0.8, ls="--")
        b.set_title("V precision per filter (dashed: float FIR reference)", fontsize=9, loc="left")
        b.grid(True, axis="x", color=BORDER, lw=0.4)
        fig.tight_layout()
    return fig
