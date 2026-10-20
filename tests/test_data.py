"""Data-pipeline tests: splits, label mapping, and that delay compensation really centres the R peak."""
import numpy as np

from ecg_edge_ml import data as D
from ecg_edge_ml import dsp
from ecg_edge_ml.synthetic import synthetic_record


def test_splits_are_inter_patient_and_complete():
    assert len(D.DS1) == 22 and len(D.DS2) == 22
    assert set(D.DS1).isdisjoint(D.DS2)
    assert set(D.EXCLUDED_RECORDS).isdisjoint(D.DS1 + D.DS2)
    assert set(D.VAL_RECORDS) <= set(D.DS1)
    assert set(D.TRAIN_RECORDS).isdisjoint(D.VAL_RECORDS)
    assert len(D.DS1) + len(D.DS2) + len(D.EXCLUDED_RECORDS) == 48       # all of MIT-BIH


def test_aami_mapping():
    assert D.AAMI_MAP["N"] == D.AAMI_MAP["L"] == D.AAMI_MAP["R"] == 0
    assert D.AAMI_MAP["A"] == D.AAMI_MAP["J"] == 1
    assert D.AAMI_MAP["V"] == D.AAMI_MAP["E"] == 2
    assert D.AAMI_MAP["F"] == 3
    for skipped in ("/", "f", "Q", "+", "~", "|"):                       # paced / unknown / non-beat
        assert skipped not in D.AAMI_MAP


def test_extract_shapes_and_labels():
    rec = synthetic_record(120, seed=3)
    flt = dsp.make_filter("fir127_f64")
    X, y, r = D.filter_and_extract(rec, flt)
    assert X.shape[1] == D.WIN + 2 * D.MARGIN and X.dtype == np.float32
    assert len(X) == len(y) == len(r) > 50
    sym = {"N": 0, "A": 1, "V": 2}
    expected = [sym[s] for s, a in zip(rec["ann_symbols"], rec["ann_samples"])
                if a >= D.SETTLE_S * dsp.FS_HZ and a + flt.delay + D.POST + D.MARGIN <= len(rec["x_mv"])]
    assert y.tolist() == expected                                        # same order, same labels
    assert set(np.unique(y)) == {0, 1, 2}


def test_delay_compensation_centres_the_qrs():
    """After FIR delay compensation the strongest deflection must sit at the window centre (+-3 samples)."""
    rec = synthetic_record(180, seed=5)
    for name in ("fir127_f64", "fir63_f64", "iirh_f64"):
        flt = dsp.make_filter(name)
        X, y, _ = D.filter_and_extract(rec, flt, margin=0)
        W = X - np.median(X, axis=1, keepdims=True)
        peak = np.argmax(np.abs(W), axis=1)
        off = np.abs(peak - D.PRE)
        assert np.mean(off <= 3) > 0.95, (name, np.mean(off <= 3))


def test_without_delay_compensation_the_peak_is_off_centre():
    """Negative control: the same test with delay=0 on a 127-tap FIR must FAIL - proves the test has teeth."""
    rec = synthetic_record(180, seed=5)
    flt = dsp.make_filter("fir127_f64")
    y_mv = flt.apply(dsp.quantize_input(rec["x_mv"])) * dsp.LSB_MV
    X, _, _ = D.extract_beats(y_mv, rec["ann_samples"], rec["ann_symbols"], delay=0, margin=0)
    peak = np.argmax(np.abs(X - np.median(X, axis=1, keepdims=True)), axis=1)
    assert np.mean(np.abs(peak - D.PRE) <= 3) < 0.2


def test_settling_and_edge_beats_are_skipped():
    y = np.zeros(4000)                                                   # settle time = 5 s = 1800 samples
    X, lab, r = D.extract_beats(y, [10, 2000, 3990], ["N", "N", "N"], delay=0)
    assert r.tolist() == [2000]                                          # first inside settle time, last runs off the end
    X, lab, r = D.extract_beats(y, [2000, 2100], ["N", "Q"], delay=0)
    assert r.tolist() == [2000]                                          # 'Q' is not an N/S/V/F beat


def test_crops():
    rng = np.random.default_rng(0)
    X = np.arange(10 * (D.WIN + 2 * D.MARGIN), dtype=np.float32).reshape(10, -1)
    assert D.center_crop(X).shape == (10, D.WIN)
    assert np.array_equal(D.center_crop(X)[0], X[0, D.MARGIN:D.MARGIN + D.WIN])
    rc = D.random_crop(X, rng)
    assert rc.shape == (10, D.WIN)
    assert np.all(np.diff(rc, axis=1) == 1)                              # contiguous slice of the row


def test_prep_removes_mean_only():
    X = np.array([[1.0, 2.0, 3.0], [10.0, 10.0, 16.0]], dtype=np.float32)
    P = D.prep(X)
    assert np.allclose(P.mean(axis=1), 0.0, atol=1e-6)
    assert np.allclose(P[0], [-1.0, 0.0, 1.0])                           # amplitude NOT rescaled


# ------------------------------------------------------------------ RR features
def test_beat_times_uses_all_beat_symbols_but_not_rhythm_marks():
    bt = D.beat_times([10, 20, 30, 40, 50], ["N", "+", "Q", "~", "/"])
    assert bt.tolist() == [10, 30, 50]                 # Q and / are beats; + and ~ are not


def test_rr_features_regular_and_premature():
    fs = dsp.FS_HZ
    beats = [0, 360, 720, 1080, 1260, 1620]            # 1 s apart, then one EARLY beat at 1260 (0.5 s)
    F = D.rr_features(beats, [1260], fs=fs)
    assert np.allclose(F[0], [0.5, 1.0, 0.5, 1.0])     # pre=0.5 s, post=1 s, pre/avg=0.5 (premature), post/avg=1
    F = D.rr_features(beats, [720], fs=fs)
    assert np.allclose(F[0], [1.0, 1.0, 1.0, 1.0])     # regular rhythm -> all ratios 1


def test_rr_features_edges_and_clipping():
    beats = [0, 360, 720, 1080, 1260, 1620]
    first = D.rr_features(beats, [0])[0]
    assert np.allclose(first, [1.0, 1.0, 1.0, 1.0])    # no previous beat: copies post-RR
    last = D.rr_features(beats, [1620])[0]
    assert np.isclose(last[0], 1.0) and np.isclose(last[1], 1.0)   # no next beat: copies pre-RR
    F = D.rr_features([0, 360 * 10, 360 * 10 + 36], [360 * 10])     # a 10 s pause and a 0.1 s interval
    assert F[0, 0] == 3.0 and F[0, 1] == 0.2           # clipped to [0.2, 3.0] s
    assert np.all((F[:, 2:] >= 0.0) & (F[:, 2:] <= 3.0))


def test_rr_features_single_beat_record():
    F = D.rr_features([100], [100])
    assert np.allclose(F[0], [D.DEFAULT_RR_S, D.DEFAULT_RR_S, 1.0, 1.0])


def test_beats_and_rr_on_synthetic_record():
    rec = synthetic_record(120, seed=2)
    X, y, F, r = D.beats_and_rr(rec, dsp.make_filter("fir127_f64"))
    assert F.shape == (len(y), D.N_RR) and F.dtype == np.float32
    assert np.all(np.isfinite(F))
    assert 0.4 < float(np.median(F[:, 0])) < 1.5       # median pre-RR ~ 0.85 s by construction


def test_beat_keys_and_common_masks():
    k1 = D.beat_keys("100", [1000, 2000, 3000])
    k2 = D.beat_keys("100", [2000, 3000, 4000])        # a longer filter delay dropped the first beat, kept another
    m1, m2 = D.common_masks([k1, k2])
    assert m1.tolist() == [False, True, True] and m2.tolist() == [True, True, False]
    assert np.array_equal(k1[m1], k2[m2])
    assert D.beat_keys("101", [5])[0] > D.beat_keys("100", [9_999_999])[0]   # records never collide
