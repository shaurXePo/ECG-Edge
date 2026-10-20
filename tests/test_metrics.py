import numpy as np

from ecg_edge_ml import metrics as M


def test_confusion_and_rates():
    yt = [0, 0, 0, 0, 1, 1, 2, 2, 2, 3]
    yp = [0, 0, 0, 1, 1, 0, 2, 2, 0, 3]
    cm = M.confusion(yt, yp)
    assert cm.sum() == 10 and cm[0, 1] == 1 and cm[1, 0] == 1
    m = M.per_class(cm)
    assert np.isclose(m["se"][2], 2 / 3)                 # 2 of 3 true V found
    assert np.isclose(m["ppv"][0], 3 / 5)                # 5 predicted N, 3 correct
    assert np.isclose(m["accuracy"], 0.7)


def test_missing_class_is_nan_not_zero():
    cm = M.confusion([0, 0, 1], [0, 0, 1])               # no V, no F in the data
    m = M.per_class(cm)
    assert np.isnan(m["se"][2]) and np.isnan(m["f1"][3])
    assert np.isclose(M.macro_f1(cm), 1.0)               # NaN classes ignored


def test_always_normal_baseline_has_high_accuracy_but_zero_v_sensitivity():
    yt = np.array([0] * 90 + [2] * 10)
    cm = M.confusion(yt, np.zeros_like(yt))
    m = M.per_class(cm)
    assert np.isclose(m["accuracy"], 0.9) and m["se"][2] == 0.0


def test_report_runs():
    assert "macro-F1" in M.report(M.confusion([0, 1, 2, 3], [0, 1, 2, 3]))


def test_roc_auc_known_values():
    assert M.roc_auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == 1.0          # perfect ranking
    assert M.roc_auc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == 0.0          # perfectly wrong
    assert M.roc_auc([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5]) == 0.5          # all ties -> chance
    assert np.isnan(M.roc_auc([0, 0, 0], [0.1, 0.2, 0.3]))                # no positives -> undefined
    rng = np.random.default_rng(0)
    y = rng.random(20000) < 0.1
    assert abs(M.roc_auc(y, rng.random(20000)) - 0.5) < 0.02             # random scores ~ chance


def test_average_precision_known_value():
    # ranking: pos, neg, pos, neg -> precision at the two positives = 1/1 and 2/3
    assert np.isclose(M.average_precision([1, 0, 1, 0], [0.9, 0.8, 0.7, 0.1]), (1 + 2 / 3) / 2)
    assert M.average_precision([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]) == 1.0


def test_softmax_rows_sum_to_one_and_are_stable():
    p = M.softmax(np.array([[1000.0, 1001.0, 999.0], [0.0, 0.0, 0.0]]))
    assert np.allclose(p.sum(axis=1), 1.0) and np.all(np.isfinite(p))
