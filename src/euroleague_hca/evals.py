"""Shared evaluation helpers: time-based CV, calibration, baselines."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, brier_score_loss, log_loss, roc_curve,
)


def time_based_splits(seasons: np.ndarray, val_seasons: int = 1, test_seasons: int = 1) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Walk-forward splits: expanding-window train, next season as val, next-next as test."""
    uniq = sorted(np.unique(seasons))
    splits = []
    for i in range(len(uniq) - val_seasons - test_seasons):
        train_s = set(uniq[: i + 1])
        val_s = {uniq[i + 1]}
        test_s = {uniq[i + 2]} if i + 2 < len(uniq) else set()
        if not test_s:
            continue
        splits.append((
            np.where(pd.Series(seasons).isin(train_s))[0],
            np.where(pd.Series(seasons).isin(val_s))[0],
            np.where(pd.Series(seasons).isin(test_s))[0],
        ))
    return splits


def eval_binary(y_true: np.ndarray, p: np.ndarray) -> dict:
    p_clip = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "accuracy": float(accuracy_score(y_true, (p >= 0.5).astype(int))),
        "log_loss": float(log_loss(y_true, p_clip)),
        "brier": float(brier_score_loss(y_true, p)),
    }


def calibration_curve_data(y_true: np.ndarray, p: np.ndarray, n_bins: int = 10) -> list[dict]:
    bins = np.linspace(0, 1, n_bins + 1)
    out = []
    for i in range(n_bins):
        mask = (p >= bins[i]) & (p < bins[i + 1])
        if mask.sum() < 5:
            continue
        out.append({
            "bin_mid": float((bins[i] + bins[i + 1]) / 2),
            "predicted": float(p[mask].mean()),
            "empirical": float(y_true[mask].mean()),
            "n": int(mask.sum()),
        })
    return out


def roc_data(y_true: np.ndarray, p: np.ndarray, max_points: int = 200) -> list[dict]:
    fpr, tpr, _ = roc_curve(y_true, p)
    # downsample
    idx = np.linspace(0, len(fpr) - 1, min(max_points, len(fpr))).astype(int)
    return [{"x": float(fpr[i]), "y": float(tpr[i])} for i in idx]
