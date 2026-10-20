"""Filter-chain tests: float vs fixed-point models, delays, and the known Q15 IIR failure."""
import numpy as np

from ecg_edge_ml import dsp
from ecg_edge_ml.synthetic import synthetic_record


def _x_int(seconds=20, seed=1):
    return dsp.quantize_input(synthetic_record(seconds, seed)["x_mv"])


def _snr(y, ref):
    return 10 * np.log10(np.sum(ref ** 2) / np.sum((y - ref) ** 2))


def test_quantize_input_range_and_rounding():
    q = dsp.quantize_input(np.array([0.0, 5.0, -5.0, 100.0, 1e-9]))
    assert q.tolist() == [0, 32767, -32768, 32767, 0]          # clipped at the rails


def test_fir_is_linear_phase_delay():
    for n in (63, 127):
        h = dsp.design_fir(n)
        assert np.allclose(h, h[::-1])                         # symmetric taps -> linear phase
        assert dsp.make_filter(f"fir{n}_f64").delay == (n - 1) // 2


def test_fir_q15_close_to_float():
    x = _x_int()
    ref = dsp.make_filter("fir127_f64").apply(x)
    for name in ("fir127_q15", "fir127_q15r"):
        y = dsp.make_filter(name).apply(x)
        assert _snr(y, ref) > 50.0, name                       # README reports ~70 dB on real-ish data


def test_rounding_beats_truncation_in_fir():
    x = _x_int()
    ref = dsp.make_filter("fir127_f64").apply(x)
    e_trunc = np.mean(dsp.make_filter("fir127_q15").apply(x) - ref)
    e_round = np.mean(dsp.make_filter("fir127_q15r").apply(x) - ref)
    assert e_trunc < -0.3                                      # floor() biases by about -0.5 LSB
    assert abs(e_round) < 0.2


def test_q15_butterworth_iir_fails_but_hp1_rounding_works():
    """The ECG-Edge headline result: Butterworth+notch in Q15 is unusable at 0.5 Hz; hp1+rounding works."""
    x = _x_int(20)
    ref_b = dsp.make_filter("iir2_f64").apply(x)
    bad = dsp.make_filter("iir2_q15").apply(x)
    ref_h = dsp.make_filter("iirh_f64").apply(x)
    good = dsp.make_filter("iirh_q15r").apply(x)
    assert _snr(bad, ref_b) < 10.0
    assert _snr(good, ref_h) > 30.0


def test_float_iir_delay_is_small_positive():
    d = dsp.make_filter("iir2_f64").delay
    assert 0 < d < 40


def test_q15_cmsis_postshift_for_butterworth():
    cm = dsp.sos_to_cmsis(dsp.design_iir_sos(2))
    assert dsp.choose_post_shift(cm) >= 1                      # a1 ~ 1.98 needs |c| < 2
    assert np.max(np.abs(cm)) < 2.0 ** dsp.choose_post_shift(cm)


def test_unknown_filter_name_raises():
    try:
        dsp.make_filter("bogus")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_coefficient_response_q15_fir_vs_failing_iir():
    """Q15 rounding of the FIR taps barely moves the response; for the Butterworth IIR it distorts the 0.5 Hz edge
    far more than for the hp1 structure."""
    from ecg_edge_ml.appcore import response_pair
    f, a, b = response_pair("fir127_q15")
    pb = (f > 2) & (f < 35)
    assert np.max(np.abs(a[pb] - b[pb])) < 0.05                      # dB
    def low_edge_error(name):
        f, a, b = response_pair(name)
        m = (f > 0.2) & (f < 2.0)
        return float(np.max(np.abs(a[m] - b[m])))
    assert low_edge_error("iir2_q15") > 5 * low_edge_error("iirh_q15r")
    f, a, b = response_pair("iir2_f64")
    assert b is None and len(f) == len(a)
