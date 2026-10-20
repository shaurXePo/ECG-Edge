"""App-logic tests (NumPy only): sample file round trip, twin statistics, classification plumbing."""
import os
import tempfile

import numpy as np

from ecg_edge_ml import appcore as A
from ecg_edge_ml import data as D
from ecg_edge_ml.synthetic import synthetic_record
from tests_helpers import random_net  # noqa


def test_sample_file_roundtrip_and_fallback():
    recs = {"100": synthetic_record(40, 1), "200": synthetic_record(40, 2)}
    path = os.path.join(tempfile.mkdtemp(), "s.npz")
    A.save_samples(path, recs)
    back, real = A.load_samples(path)
    assert real and list(back) == ["100", "200"]
    assert np.allclose(back["100"]["x_mv"], recs["100"]["x_mv"], atol=1e-6)
    assert back["100"]["ann_symbols"].tolist() == recs["100"]["ann_symbols"].tolist()
    fallback, real = A.load_samples(os.path.join(tempfile.mkdtemp(), "missing.npz"))
    assert not real and all(k.startswith("synthetic") for k in fallback)


def test_twin_stats_identical_and_failing_q15_iir():
    rec = synthetic_record(60, 3)
    ref = A.filtered_mv(rec, "iir2_f64")
    assert A.twin_stats(ref, ref)["snr_db"] == float("inf")
    bad = A.twin_stats(A.filtered_mv(rec, "iir2_q15"), ref)
    good = A.twin_stats(A.filtered_mv(rec, "iirh_q15r"), A.filtered_mv(rec, "iirh_f64"))
    assert bad["snr_db"] < 10 < 30 < good["snr_db"]           # the ECG-Edge headline, visible in the app
    assert abs(bad["mean_err_lsb"]) > 50                       # a large constant offset


def test_aligned_shifts_by_delay():
    y = np.arange(10.0)
    assert A.aligned(y, 3).tolist() == [3, 4, 5, 6, 7, 8, 9, 0, 0, 0]
    assert A.aligned(y, 0) is y


def test_classify_rec_plumbing():
    rec = synthetic_record(80, 4)
    for n_rr in (0, 4):
        out = A.classify_rec(rec, "fir127_f64", random_net(n_rr))
        n = len(out["y_true"])
        assert n > 20 and out["prob"].shape == (n, 4) and out["windows"].shape == (n, D.WIN)
        assert np.allclose(out["prob"].sum(axis=1), 1.0, atol=1e-5)
        assert out["pred"].shape == (n,) and out["rr"].shape == (n, D.N_RR)
        assert out["r"].min() >= A.LEAD_S * 360                # lead-in beats are skipped


def test_split_labels():
    assert D.split_of("100").startswith("TEST") and D.split_of("208").startswith("TRAIN")
    assert D.split_of("106").startswith("VALIDATION") and D.split_of("102").startswith("not")


# ------------------------------------------------------------------ end-to-end pipeline
from ecg_edge_ml import detect  # noqa: E402


def test_detector_on_synthetic_is_accurate():
    rec = synthetic_record(120, 1)
    flt = A.make_filter("fir127_f64")
    y = A.filter_mv(flt, rec["x_mv"])
    det = detect.detect_r_peaks(y)
    truth = rec["ann_samples"] + flt.delay
    det, truth = det[det >= 1800], truth[truth >= 1800]
    tp, fp, fn = detect.match_peaks(det, truth, 27)
    assert tp / (tp + fn) > 0.95 and tp / (tp + fp) > 0.95


def test_match_peaks_greedy_one_to_one():
    assert detect.match_peaks([100, 105], [102], 10) == (1, 1, 0)        # one truth cannot match two detections
    assert detect.match_peaks([100], [300], 10) == (0, 1, 1)
    assert detect.match_peaks([], [5], 10) == (0, 0, 1)


def test_prepare_signal_resamples_and_converts_units():
    t = np.arange(0, 20, 1 / 250)
    x = np.sin(2 * np.pi * 1.0 * t) * 1000                              # 1 kHz-amplitude "uV" at 250 Hz
    y = A.prepare_signal(x, 250, "µV")
    assert abs(len(y) - 20 * 360) <= 2 and abs(np.max(np.abs(y)) - 1.0) < 0.02   # 1000 uV = 1 mV
    for bad in (np.zeros(100),):
        try:
            A.prepare_signal(bad, 360)
        except ValueError:
            continue
        raise AssertionError("short signal should raise")
    assert A.amplitude_warning(np.array([0.0, 9.0])) and A.amplitude_warning(np.array([0.0, 0.01]))
    assert A.amplitude_warning(np.array([0.0, 1.0])) is None


def test_run_pipeline_with_and_without_annotations():
    rec = synthetic_record(90, 5)
    net = random_net(4)
    res = A.run_pipeline(rec["x_mv"], "fir127_f64", net, ann=rec)
    n = len(res["r"])
    assert n > 40 and res["prob"].shape == (n, 4) and res["windows"].shape == (n, D.WIN)
    assert res["det"]["sensitivity"] > 0.95 and res["det"]["ppv"] > 0.95
    assert res["labels"].shape == (n,) and np.mean(res["labels"] >= 0) > 0.9   # detected beats got matched to labels
    assert set(np.unique(res["labels"])) <= {-1, 0, 1, 2}
    bare = A.run_pipeline(rec["x_mv"], "fir127_f64", net)                        # no annotations at all
    assert bare["labels"] is None and bare["det"] is None and len(bare["r"]) == n


def test_occlusion_map_finds_the_samples_the_model_uses():
    class Stub:                                                          # logit depends only on samples 100-119
        n_rr = 0
        def forward(self, x, rr=None):
            s = x[:, 100:120].sum(axis=1)
            return np.stack([s, -s, np.zeros_like(s), np.zeros_like(s)], axis=1)
    w = np.zeros(256, np.float32); w[100:120] = 1.0
    heat = A.occlusion_map(Stub(), w, None, cls=0)
    assert heat.shape == (256,) and 96 <= int(np.argmax(heat)) <= 124
    assert heat[:60].max() < 1e-6 and heat[160:].max() < 1e-6            # nothing else matters
