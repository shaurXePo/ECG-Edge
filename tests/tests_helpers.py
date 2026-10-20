"""Shared test helper: a randomly-initialised NumpyNet."""
import numpy as np

from ecg_edge_ml.numpy_infer import NumpyNet


def random_net(n_rr, seed=0):
    rng = np.random.default_rng(seed)
    p = {"n_rr": np.array(n_rr)}
    for i, (co, ci, k) in enumerate([(8, 1, 7), (16, 8, 5), (32, 16, 5)], start=1):
        p[f"conv{i}_w"], p[f"conv{i}_b"] = rng.normal(size=(co, ci, k)) * 0.3, rng.normal(size=co) * 0.1
    if n_rr:
        p["fc1_w"], p["fc1_b"] = rng.normal(size=(16, 256 + n_rr)) * 0.2, rng.normal(size=16) * 0.1
        p["fc2_w"], p["fc2_b"] = rng.normal(size=(4, 16)) * 0.2, rng.normal(size=4) * 0.1
    else:
        p["fc1_w"], p["fc1_b"] = rng.normal(size=(4, 256)) * 0.2, rng.normal(size=4) * 0.1
    return NumpyNet({k: (v if k == "n_rr" else v.astype(np.float32)) for k, v in p.items()})
