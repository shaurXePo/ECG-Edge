import pytest

torch = pytest.importorskip("torch")

from ecg_edge_ml.data import N_RR, WIN
from ecg_edge_ml.model import TinyECGNet, count_params


def test_baseline_shape_and_size():
    m = TinyECGNet()
    assert tuple(m(torch.zeros(3, 1, WIN)).shape) == (3, 4)
    assert count_params(m) == 4396                    # see model.py docstring
    assert count_params(m) < 10_000                   # must stay MCU-sized


def test_rr_model_shape_and_size():
    m = TinyECGNet(n_rr=N_RR)
    assert tuple(m(torch.zeros(3, 1, WIN), torch.zeros(3, N_RR)).shape) == (3, 4)
    assert count_params(m) == 7612
    assert count_params(m) < 10_000


def test_rr_model_requires_rr_input():
    m = TinyECGNet(n_rr=N_RR)
    try:
        m(torch.zeros(2, 1, WIN))
    except ValueError:
        return
    raise AssertionError("expected ValueError when RR features are missing")


def test_rr_features_change_the_output():
    torch.manual_seed(0)
    m = TinyECGNet(n_rr=N_RR).eval()
    x = torch.randn(2, 1, WIN)
    a = m(x, torch.zeros(2, N_RR))
    b = m(x, torch.ones(2, N_RR) * 2.0)
    assert not torch.allclose(a, b)


def test_feature_map_before_classifier_is_8_positions():
    m = TinyECGNet()
    assert tuple(m.features(torch.zeros(1, 1, WIN)).shape) == (1, 32, 8)
