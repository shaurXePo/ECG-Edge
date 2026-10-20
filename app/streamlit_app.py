"""ECG-Edge-ML web app.   Run locally:  streamlit run app/streamlit_app.py

Deploy: Streamlit Community Cloud, main file path  app/streamlit_app.py  (uses app/requirements.txt, no PyTorch).
The firmware itself cannot run in a browser: numbers here come from Python models of the same arithmetic plus
recorded experiment results (see the About tab).  Look and feel lives in app/appui.py and .streamlit/config.toml.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

import appui as U
from ecg_edge_ml import appcore as A
from ecg_edge_ml.data import CLASSES, split_of
from ecg_edge_ml.dsp import FLOAT_TWIN, FS_HZ, LSB_MV, make_filter
from ecg_edge_ml.metrics import confusion, per_class

st.set_page_config(page_title="ECG-Edge-ML", page_icon="🫀", layout="wide", initial_sidebar_state="expanded")
U.inject_css(st)


# ------------------------------------------------------------------------------------------ cached work
@st.cache_resource
def get_samples():
    return A.load_samples()


@st.cache_resource
def get_net():
    return A.load_net()


SAMPLES, IS_REAL = get_samples()
NET = get_net()


@st.cache_data(show_spinner=False)
def _filtered_demo(rec_name, filt):
    return A.filtered_mv(SAMPLES[rec_name], filt)


@st.cache_data(show_spinner="Running the pipeline...")
def _pipeline_demo(rec_name, filt):
    return A.run_pipeline(SAMPLES[rec_name]["x_mv"], filt, NET, ann=SAMPLES[rec_name])


def get_filtered(sig, filt):
    return _filtered_demo(sig["key"], filt) if sig["key"] else A.filtered_mv({"x_mv": sig["x_mv"]}, filt)


def get_pipeline(sig, filt):
    if sig["key"]:
        return _pipeline_demo(sig["key"], filt)
    with st.spinner("Running the pipeline..."):
        return A.run_pipeline(sig["x_mv"], filt, NET)


# ------------------------------------------------------------------------------------------ sidebar
sig = None
with st.sidebar:
    st.markdown('<div class="brand">🫀 ECG-Edge<span>-ML</span></div>'
                '<div class="muted">Fixed-point ECG filtering + tiny beat classifier</div>', unsafe_allow_html=True)
    st.markdown("#### Signal")
    src = st.radio("Source", ["Demo excerpt", "Upload CSV"], horizontal=True, label_visibility="collapsed", key="src")
    if src == "Demo excerpt":
        rec_name = st.selectbox("Record", list(SAMPLES), key="rec")
        sig = dict(x_mv=SAMPLES[rec_name]["x_mv"], ann=SAMPLES[rec_name], key=rec_name,
                   caption=(f"Record {rec_name} · {split_of(rec_name)}" if IS_REAL else f"{rec_name} (synthetic)"))
    else:
        fs_in = st.number_input("Sampling rate [Hz]", 50.0, 2000.0, 360.0, key="fs")
        unit = st.selectbox("Unit of the samples", ["mV", "µV", "V"], key="unit")
        up = st.file_uploader("CSV / TXT, one column of ECG samples (10 s to 10 min)", type=["csv", "txt"], key="up")
        if up is None:
            st.info("Upload a single-lead ECG, or switch to a demo excerpt.")
        else:
            try:
                num = pd.read_csv(up).select_dtypes("number")
                if num.shape[1] == 0:
                    raise ValueError("no numeric column found")
                x_up = A.prepare_signal(num.iloc[:, 0].to_numpy(), float(fs_in), unit)
                warn = A.amplitude_warning(x_up)
                if warn:
                    st.warning(warn)
                sig = dict(x_mv=x_up, ann=None, key=None,
                           caption=f"Uploaded signal · {len(x_up) / FS_HZ:.0f} s at {FS_HZ} Hz after resampling")
            except Exception as e:  # a bad file must never crash the app
                st.error(f"Could not read this file: {e}")
    st.markdown("#### Filter")
    filt = st.selectbox("Filter", A.FILTER_CHOICES, index=0, format_func=lambda k: U.FILTER_LABELS[k],
                        label_visibility="collapsed", key="filt")
    st.markdown("---")
    U.status(st, [(NET is not None, "classifier loaded" if NET is not None else "classifier missing: run export_numpy.py"),
                  (IS_REAL, "real MIT-BIH excerpts" if IS_REAL else "synthetic fallback data (run make_app_sample.py)")])
    st.markdown('<div class="muted" style="margin-top:10px">Educational project. Not a medical device. '
                'Do not use for diagnosis.</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------------------------------ header
U.hero(st, "ECG-Edge-ML",
       "What happens to a heartbeat classifier when the ECG filter in front of it runs in 16-bit fixed-point on a "
       "Cortex-M4 instead of in floating point? An end-to-end pipeline: filter, R-peak detection, neural network, "
       "and an honest measurement of the difference.",
       ["Cortex-M4 · Q15 · CMSIS-DSP", "MIT-BIH · inter-patient split", "7,612-parameter CNN", "Pan-Tompkins-style detector"])
# headline numbers are copied from the author's runs (3 seeds / 49,554 DS2 test beats); see the Evidence tab
U.kpi_row(st, [("V-beat sensitivity", "0.81–0.88", "3 seeds, 3,210 unseen V beats", U.CLASS_COLORS[2]),
               ("S-beat sensitivity", "0.11–0.14", "weak: one patient dominates S", U.CLASS_COLORS[1]),
               ("Q15 FIR vs float", "agreement 1.000", "predictions unchanged, 49,554 beats", U.ACCENT),
               ("Failing Q15 Butterworth", "5.7% changed", "of predictions vs its float twin", "#F87171")])
U.pipeline_diagram(st, U.FILTER_LABELS[filt])

tab_pipe, tab_lab, tab_evid, tab_about = st.tabs(["Live pipeline", "Filter lab", "Evidence", "About"])

# ------------------------------------------------------------------------------------------ Live pipeline
with tab_pipe:
    if NET is None:
        U.callout(st, "bad", "Classifier not found",
                  "Create it with <code>python scripts/export_numpy.py --ckpt runs/rr_v3/model.pt --out models/rr_v3.npz</code>")
    elif sig is None:
        U.callout(st, "info", "No signal yet", "Choose a demo excerpt or upload a CSV in the sidebar.")
    else:
        res = get_pipeline(sig, filt)
        n = len(res["r"])
        st.markdown(f'<div class="muted">{sig["caption"]}  ·  the classifier was trained on float64 127-tap FIR beats</div>',
                    unsafe_allow_html=True)
        if n == 0:
            U.callout(st, "warn", "No beats detected", "Check the unit and the sampling rate in the sidebar.")
        else:
            counts = np.bincount(res["pred"], minlength=4)
            hr = 60.0 * FS_HZ / float(np.median(np.diff(res["r_all"]))) if len(res["r_all"]) > 1 else float("nan")
            U.kpi_row(st, [("beats classified", f"{n}", "after the 5 s filter warm-up", U.TEXT),
                           ("median heart rate", f"{hr:.0f} bpm", "from detected R peaks", U.TEXT),
                           ("predicted V", f"{int(counts[2])}", "ventricular", U.CLASS_COLORS[2]),
                           ("predicted S", f"{int(counts[1])}", "supraventricular", U.CLASS_COLORS[1])])
            with st.container(border=True):
                st.markdown("##### Detected beats on the filtered signal")
                dur = len(res["y"]) / FS_HZ
                t0 = 0
                if dur > 12:
                    t0 = st.slider("Timeline start [s]", 0, int(dur) - 10, min(10, int(dur) - 10), key="t0")
                fig = U.plot_timeline(res["y"], res["r"], res["pred"], float(t0), 10.0)
                st.pyplot(fig)
                plt.close(fig)
                if res["det"]:
                    d = res["det"]
                    st.markdown(f'<div class="muted">R-peak detector vs the annotations: sensitivity <b>{d["sensitivity"]:.3f}</b>, '
                                f'precision <b>{d["ppv"]:.3f}</b> (TP {d["tp"]}, FP {d["fp"]}, FN {d["fn"]})</div>',
                                unsafe_allow_html=True)

            left, right = st.columns([1.55, 1], gap="medium")
            opts = ["all beats", "predicted S", "predicted V", "predicted F"] + (["errors only"] if res["labels"] is not None else [])
            with left:
                with st.container(border=True):
                    st.markdown("##### Why did the model say that?")
                    st.markdown('<div class="muted">Occlusion map: the model is re-run with a 67 ms piece of the beat blanked out; '
                                'red shows how much the predicted class loses. Bright = the model relies on that part.</div>',
                                unsafe_allow_html=True)
                    show = st.radio("Browse", opts, horizontal=True, key="show")
                    if show == "all beats":
                        idx = np.arange(n)
                    elif show == "errors only":
                        idx = np.flatnonzero((res["labels"] >= 0) & (res["labels"] != res["pred"]))
                    else:
                        idx = np.flatnonzero(res["pred"] == {"predicted S": 1, "predicted V": 2, "predicted F": 3}[show])
                    if len(idx) == 0:
                        st.info("No beats in this category.")
                        i = None
                    else:
                        k = st.slider("Beat", 0, len(idx) - 1, 0, key="k") if len(idx) > 1 else 0
                        i = int(idx[k])
                        cls = int(res["pred"][i])
                        heat = A.occlusion_map(NET, res["windows"][i], res["rr"][i] if NET.n_rr else None, cls)
                        lab = int(res["labels"][i]) if res["labels"] is not None else -1
                        tt = (np.arange(res["windows"].shape[1]) - 96) * 1000 / FS_HZ
                        title = f"predicted {CLASSES[cls]}" + (f"  ·  annotated {CLASSES[lab]}" if lab >= 0 else "")
                        fig = U.plot_beat(tt, res["windows"][i], heat, title)
                        st.pyplot(fig)
                        plt.close(fig)
            with right:
                with st.container(border=True):
                    st.markdown("##### Model output")
                    if i is None:
                        st.markdown('<div class="muted">Select a beat.</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(U.pill(cls), unsafe_allow_html=True)
                        U.prob_bars(st, res["prob"][i])
                        pre, post, rpre, rpost = (float(v) for v in res["rr"][i])
                        st.markdown(f'<div class="muted">RR timing features<br>previous interval <b>{pre:.2f} s</b> · '
                                    f'next interval <b>{post:.2f} s</b><br>vs recent average: <b>{rpre:.2f}×</b> before, '
                                    f'<b>{rpost:.2f}×</b> after</div>', unsafe_allow_html=True)
                        if lab >= 0:
                            st.markdown(f'<div class="muted" style="margin-top:8px">Annotated class: {U.pill(lab)}</div>',
                                        unsafe_allow_html=True)

            if res["labels"] is not None and np.any(res["labels"] >= 0):
                with st.expander("Scoring against the annotations"):
                    ok = res["labels"] >= 0
                    cm = confusion(res["labels"][ok], res["pred"][ok])
                    m = per_class(cm)
                    c1, c2 = st.columns([1, 1], gap="medium")
                    fig = U.plot_confusion(cm)
                    c1.pyplot(fig)
                    plt.close(fig)
                    fmt = lambda v: "–" if np.isnan(v) else f"{v:.3f}"
                    c2.dataframe(pd.DataFrame({"class": CLASSES, "beats": cm.sum(axis=1),
                                               "sensitivity": [fmt(v) for v in m["se"]],
                                               "precision": [fmt(v) for v in m["ppv"]]}), hide_index=True)
                    c2.markdown('<div class="muted">A short excerpt: for illustration, not evaluation. '
                                'See the Evidence tab for the full test set.</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------------------------------ Filter lab
with tab_lab:
    if sig is None:
        U.callout(st, "info", "No signal yet", "Choose a demo excerpt or upload a CSV in the sidebar.")
    else:
        x = sig["x_mv"]
        y = get_filtered(sig, filt)
        flt = make_filter(filt)
        twin = FLOAT_TWIN.get(filt)
        y_twin = get_filtered(sig, twin) if twin else None
        dur = len(x) / FS_HZ
        t0 = int(A.LEAD_S)
        if dur > A.LEAD_S + 8:
            t0 = st.slider("Window start [s]", int(A.LEAD_S), int(dur) - 6, min(int(A.LEAD_S) + 5, int(dur) - 6), key="lab_t0")
        a_, b_ = int(t0 * FS_HZ), int(min(t0 + 6, dur) * FS_HZ)
        t = np.arange(a_, b_) / FS_HZ
        with st.container(border=True):
            st.markdown(f"##### {U.FILTER_LABELS[filt]}")
            err = (y - y_twin)[a_:b_] / LSB_MV if twin else None
            fig = U.plot_filter_lab(t, x[a_:b_], A.aligned(y, flt.delay)[a_:b_], err, filt, 1000 * flt.delay / FS_HZ)
            st.pyplot(fig)
            plt.close(fig)
        if twin:
            s = A.twin_stats(y, y_twin)
            U.kpi_row(st, [("SNR vs float twin", "identical" if np.isinf(s["snr_db"]) else f"{s['snr_db']:.1f} dB",
                            "higher is better", U.ACCENT if s["snr_db"] > 30 else "#F87171"),
                           ("max |error|", f"{s['max_abs_err_lsb']:.0f} LSB", "int16 LSB = 0.153 µV", U.TEXT),
                           ("mean error (offset)", f"{s['mean_err_lsb']:.0f} LSB", "constant bias in the output", U.TEXT)])
            if filt == "iir2_q15":
                U.callout(st, "bad", "This is the failing filter",
                          "Rounding the coefficients to 16 bit removes the 0.5 Hz high-pass edge (see the response below), and "
                          "truncation bias is amplified inside the feedback loop. Compare with the first-order-HP IIR (rounding) "
                          "or the Q15 FIR in the sidebar.")
        else:
            U.callout(st, "info", "Reference signal",
                      "This is a float or unfiltered reference. Pick a Q15 variant in the sidebar to see its error against float.")
        f_hz, db0, db1 = A.response_pair(filt)
        with st.container(border=True):
            c1, c2 = st.columns([1.1, 1], gap="medium")
            fig = U.plot_response(f_hz, db0, db1, U.FILTER_LABELS[filt])
            c1.pyplot(fig)
            plt.close(fig)
            c2.markdown("##### Frequency response")
            if db1 is None:
                c2.markdown('<div class="muted">Float64 design. Pick a Q15 filter to compare the response of its '
                            '16-bit coefficients against this one.</div>', unsafe_allow_html=True)
            else:
                band = (f_hz > 0.2) & (f_hz < 2.0)
                dev = float(np.max(np.abs(db0[band] - db1[band])))
                c2.markdown(f'<div class="muted">Dashed = the response of the Q15-rounded coefficients. '
                            f'Rounding the coefficients <i>alone</i> (before any per-sample truncation) moves the 0.2–2 Hz '
                            f'gain by up to <b>{dev:.1f} dB</b>. This ignores arithmetic noise, so it understates '
                            f'the real error.</div>', unsafe_allow_html=True)

# ------------------------------------------------------------------------------------------ Evidence
with tab_evid:
    st.markdown("### Does the filter's arithmetic change what the classifier predicts?")
    st.markdown('<div class="muted">One trained model (trained on float64 127-tap FIR beats) scored on the 22 unseen DS2 '
                'patients through ten filter variants. Nothing is retrained, so any difference comes from the filter alone.</div>',
                unsafe_allow_html=True)
    if A.EXPERIMENT_CSV.exists():
        df = pd.read_csv(A.EXPERIMENT_CSV)
        fixed = [k for k in ["fir127_q15", "fir127_q15r", "iir2_q15", "iirh_q15", "iirh_q15r"] if k in set(df["filter"])]
        sub = df.set_index("filter")
        ref_ppv = float(sub.loc["fir127_f64", "V_ppv"]) if "fir127_f64" in sub.index else 0.75
        with st.container(border=True):
            flags = [k in FLOAT_TWIN and FLOAT_TWIN[k] in sub.index and
                     float(sub.loc[k, "V_ppv"]) < float(sub.loc[FLOAT_TWIN[k], "V_ppv"]) - 0.05 for k in df["filter"]]
            fig = U.plot_agreement([U.FILTER_LABELS[k] for k in fixed],
                                   [100.0 * (1.0 - float(sub.loc[k, "agree_twin"])) for k in fixed],
                                   [U.FILTER_LABELS[k] for k in df["filter"]], [float(v) for v in df["V_ppv"]],
                                   flags, ref_ppv)
            st.pyplot(fig)
            plt.close(fig)
        with st.expander("Full results table"):
            st.dataframe(df.round(3), hide_index=True)
    else:
        U.callout(st, "info", "Results file not found", "Run <code>python -m ecg_edge_ml.experiment</code> and commit "
                  "<code>results/filter_experiment/results.csv</code>.")
    with st.container(border=True):
        st.markdown("##### Effect of RR-interval (timing) features, DS2 test, three seeds")
        st.dataframe(pd.DataFrame({
            "model": ["beat shape only", "+ RR (seed 0)", "+ RR (seed 1)", "+ RR (seed 2)"],
            "accuracy": [0.761, 0.826, 0.851, 0.788], "S sensitivity": [0.027, 0.113, 0.125, 0.143],
            "V sensitivity": [0.799, 0.824, 0.805, 0.875], "V precision": [0.592, 0.756, 0.700, 0.478]}), hide_index=True)
        st.markdown('<div class="muted">Accuracy is not the headline: about 89% of beats are normal, so always answering "N" '
                    'scores 89%. Timing roughly quadruples S sensitivity but it stays low, and V precision swings between '
                    'seeds.</div>', unsafe_allow_html=True)
    U.callout(st, "warn", "How far to trust this",
              "One model, one seed per row, no confidence intervals. S and F each rest on one or two patients. Treat the "
              "V class as the only reliable one. The failing Q15 Butterworth changes V precision while V's ROC-AUC barely "
              "moves, which fits a constant offset, but that explanation is a hypothesis, not a verified result.")

# ------------------------------------------------------------------------------------------ About
with tab_about:
    with st.expander("What runs where", expanded=True):
        st.markdown("The Cortex-M4 firmware ([ECG-Edge](https://github.com/shaurXePo/ECG-Edge)) needs a board or an emulator "
                    "and cannot run in a browser. This app runs Python models of the same Q15 arithmetic (reported "
                    "bit-exact to the CMSIS kernels by ECG-Edge; not re-verified here), a NumPy copy of the trained network, "
                    "and shows recorded experiment results.")
    with st.expander("How the model works"):
        st.markdown("A 256-sample window around each R peak (about 0.7 s) goes through three strided 1-D convolutions "
                    "(BatchNorm folded in for deployment). Four timing features (previous and next RR interval, and each "
                    "relative to the recent average) are appended before a 16-unit hidden layer and a 4-way output: "
                    "N (normal), S (supraventricular), V (ventricular), F (fusion). 7,612 parameters, trained on 18 MIT-BIH "
                    "patients, validated on 4, tested on 22 unseen patients.")
    with st.expander("Limitations"):
        st.markdown("- Single lead, 44 patients: results will not transfer to other leads or devices.\n"
                    "- S and F sensitivity is low and depends on one or two patients each.\n"
                    "- On a device, RR features need the **next** beat, so a label arrives about one RR (~0.8 s) late.\n"
                    "- The R-peak detector is a simplified Pan-Tompkins; check its score on the demo excerpts.\n"
                    "- Not a medical device. Educational use only.")
    with st.expander("Data and licence"):
        st.markdown("MIT-BIH Arrhythmia Database, PhysioNet Open Data licence. Moody GB, Mark RG (2001); "
                    "Goldberger AL et al. (2000). Short excerpts are redistributed with attribution.")
