"""NumPy inference tests. The torch-equivalence test is skipped when torch is not installed."""
import numpy as np
import pytest

from ecg_edge_ml import numpy_infer as N


def _conv_ref(x, w, b, stride, pad):
    B, Ci, L = x.shape; Co, _, K = w.shape
    xp = np.pad(x, ((0, 0), (0, 0), (pad, pad)))
    Lout = (L + 2 * pad - K) // stride + 1
    y = np.zeros((B, Co, Lout))
    for n in range(B):
        for o in range(Co):
            for t in range(Lout):
                y[n, o, t] = np.sum(xp[n, :, t * stride: t * stride + K] * w[o]) + b[o]
    return y


def test_conv1d_matches_brute_force():
    rng = np.random.default_rng(0)
    for L, K, s, p in [(256, 7, 2, 3), (128, 5, 2, 2), (33, 5, 1, 2)]:
        x, w, b = rng.normal(size=(2, 3, L)), rng.normal(size=(4, 3, K)), rng.normal(size=4)
        assert np.allclose(N.conv1d(x, w, b, s, p), _conv_ref(x, w, b, s, p))
    assert N.conv1d(np.zeros((1, 1, 256)), np.zeros((8, 1, 7)), np.zeros(8), 2, 3).shape == (1, 8, 128)


def test_adaptive_pool_even_and_uneven():
    x = np.arange(2 * 3 * 32, dtype=float).reshape(2, 3, 32)
    assert np.allclose(N.adaptive_avg_pool1d(x, 8), x.reshape(2, 3, 8, 4).mean(axis=3))
    y = np.random.default_rng(1).normal(size=(1, 1, 30))
    ref = [y[0, 0, (i * 30) // 8: -((-(i + 1) * 30) // 8)].mean() for i in range(8)]
    assert np.allclose(N.adaptive_avg_pool1d(y, 8)[0, 0], ref)


def test_bn_folding_equals_conv_then_bn():
    rng = np.random.default_rng(2)
    x, w = rng.normal(size=(3, 2, 64)), rng.normal(size=(5, 2, 5))
    g, be, mu, var = rng.normal(size=5), rng.normal(size=5), rng.normal(size=5), rng.uniform(0.5, 2, size=5)
    z = N.conv1d(x, w, np.zeros(5), 2, 2)
    ref = g[None, :, None] * (z - mu[None, :, None]) / np.sqrt(var + N.BN_EPS)[None, :, None] + be[None, :, None]
    wf, bf = N.fold_bn(w, g, be, mu, var)
    assert np.allclose(N.conv1d(x, wf, bf, 2, 2), ref, atol=1e-10)


def _random_net(n_rr, seed=0):
    rng = np.random.default_rng(seed)
    p = {"n_rr": np.array(n_rr)}
    for i, (co, ci, k) in enumerate([(8, 1, 7), (16, 8, 5), (32, 16, 5)], start=1):
        p[f"conv{i}_w"], p[f"conv{i}_b"] = rng.normal(size=(co, ci, k)) * 0.3, rng.normal(size=co) * 0.1
    if n_rr:
        p["fc1_w"], p["fc1_b"] = rng.normal(size=(16, 256 + n_rr)) * 0.2, rng.normal(size=16) * 0.1
        p["fc2_w"], p["fc2_b"] = rng.normal(size=(4, 16)) * 0.2, rng.normal(size=4) * 0.1
    else:
        p["fc1_w"], p["fc1_b"] = rng.normal(size=(4, 256)) * 0.2, rng.normal(size=4) * 0.1
    return N.NumpyNet({k: (v if k == "n_rr" else v.astype(np.float32)) for k, v in p.items()})


def test_forward_shapes_and_rr_dependence():
    x = np.random.default_rng(3).normal(size=(5, 256)).astype(np.float32)
    assert _random_net(0).forward(x).shape == (5, 4)
    net = _random_net(4)
    a = net.forward(x, np.zeros((5, 4)))
    b = net.forward(x, np.ones((5, 4)))
    assert a.shape == (5, 4) and not np.allclose(a, b)
    try:
        net.forward(x)
    except ValueError:
        return
    raise AssertionError("expected ValueError without RR features")


def test_save_load_roundtrip(tmp_path=None):
    import tempfile, os
    net = _random_net(4)
    path = os.path.join(tempfile.mkdtemp(), "m.npz")
    net.save(path)
    net2 = N.NumpyNet.load(path)
    x = np.random.default_rng(4).normal(size=(3, 256)).astype(np.float32)
    rr = np.ones((3, 4), np.float32)
    assert np.allclose(net.forward(x, rr), net2.forward(x, rr))


def test_numpy_matches_torch():
    torch = pytest.importorskip("torch")
    from ecg_edge_ml.model import TinyECGNet
    for n_rr in (0, 4):
        torch.manual_seed(0)
        m = TinyECGNet(n_rr=n_rr)
        for bn in [l for l in m.modules() if isinstance(l, torch.nn.BatchNorm1d)]:   # non-trivial BN statistics
            bn.running_mean.normal_(0, 0.3); bn.running_var.uniform_(0.5, 2.0)
            bn.weight.data.uniform_(0.5, 1.5); bn.bias.data.normal_(0, 0.2)
        m.eval()
        x = torch.randn(7, 1, 256); rr = torch.rand(7, n_rr) * 2 if n_rr else None
        ref = m(x, rr).detach().numpy()
        sd = {k: v.numpy() for k, v in m.state_dict().items()}
        net = N.NumpyNet(N.from_torch_state_dict(sd, n_rr))
        got = net.forward(x[:, 0, :].numpy(), None if rr is None else rr.numpy())
        assert np.allclose(got, ref, atol=1e-4), (n_rr, np.abs(got - ref).max())
