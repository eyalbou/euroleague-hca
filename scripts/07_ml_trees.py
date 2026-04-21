"""Phase 6b -- Tree models (Random Forest + LightGBM) with SHAP.

D07-1 model-comparison table (baselines / logistic / RF / LightGBM / Elo-only)
D07-2 calibration curves overlay (all models)
D07-3 ROC curve overlay
D07-4 LightGBM feature importance
D07-5 Partial-dependence plot: P(home win) vs attendance_ratio
D07-6 SHAP summary bees-warm (approximated as per-feature mean |shap|)
D07-7 SHAP waterfall for 5 specific games
D07-8 Feature importance vs logistic coefficient side-by-side
"""
# %% imports
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.evals import calibration_curve_data, eval_binary, roc_data, time_based_splits
from euroleague_hca.warehouse import query

HAS_LGB = True
try:
    import lightgbm as lgb
except Exception:
    HAS_LGB = False

HAS_SHAP = True
try:
    import shap
except Exception:
    HAS_SHAP = False


# %% data
print(config.banner())
home = query("SELECT * FROM feat_game_team WHERE is_home=1")
home["home_win"] = (home["point_diff"] > 0).astype(int)
home["elo_diff"] = home["team_elo_pre"] - home["opp_elo_pre"]
home["attendance_ratio_filled"] = home["attendance_ratio"].fillna(home["attendance_ratio"].mean())
home["attendance_missing"] = home["attendance_ratio"].isna().astype(int)
home["days_rest_filled"] = home["days_rest"].fillna(home["days_rest"].median())
home["season"] = home["season"].astype(int)

features = ["elo_diff", "is_playoff", "days_rest_filled", "attendance_ratio_filled", "attendance_missing"]

X = home[features].values
y = home["home_win"].values
seasons = home["season"].values


# %% single walk-forward train/val/test split (last two seasons = val/test)
uniq = sorted(home["season"].unique())
train_s = set(uniq[:-2])
val_s = {uniq[-2]}
test_s = {uniq[-1]}
tr = home["season"].isin(train_s).values
va = home["season"].isin(val_s).values
te = home["season"].isin(test_s).values

X_tr, y_tr = X[tr], y[tr]
X_va, y_va = X[va], y[va]
X_te, y_te = X[te], y[te]

scaler = StandardScaler().fit(X_tr)
X_tr_s = scaler.transform(X_tr)
X_va_s = scaler.transform(X_va)
X_te_s = scaler.transform(X_te)


# %% baselines
models_eval: dict[str, dict] = {}
models_cal: dict[str, list] = {}
models_roc: dict[str, list] = {}

# Home-always
p_home_always = np.ones(len(y_te))
models_eval["home-always"] = eval_binary(y_te, np.clip(p_home_always, 1e-3, 1 - 1e-3))

# Majority
p_majority = np.full(len(y_te), y_tr.mean())
models_eval["majority-prior"] = eval_binary(y_te, p_majority)

# Elo-only (logistic on just elo_diff)
from sklearn.linear_model import LogisticRegression as LR
elo_lr = LR(max_iter=500).fit(home.loc[tr, ["elo_diff"]].values, y_tr)
p_elo = elo_lr.predict_proba(home.loc[te, ["elo_diff"]].values)[:, 1]
models_eval["elo-only"] = eval_binary(y_te, p_elo)
models_cal["elo-only"] = calibration_curve_data(y_te, p_elo)
models_roc["elo-only"] = roc_data(y_te, p_elo)

# Logistic (full feature set)
full_lr = LR(max_iter=1000).fit(X_tr_s, y_tr)
p_log = full_lr.predict_proba(X_te_s)[:, 1]
models_eval["logistic"] = eval_binary(y_te, p_log)
models_cal["logistic"] = calibration_curve_data(y_te, p_log)
models_roc["logistic"] = roc_data(y_te, p_log)
logistic_coefs = dict(zip(features, full_lr.coef_[0]))

# Random Forest
rf = RandomForestClassifier(n_estimators=300, max_depth=8, random_state=0, n_jobs=-1).fit(X_tr, y_tr)
p_rf = rf.predict_proba(X_te)[:, 1]
models_eval["random forest"] = eval_binary(y_te, p_rf)
models_cal["random forest"] = calibration_curve_data(y_te, p_rf)
models_roc["random forest"] = roc_data(y_te, p_rf)

# LightGBM
if HAS_LGB:
    lgbm = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31, random_state=0, verbose=-1)
    lgbm.fit(X_tr, y_tr, eval_set=[(X_va, y_va)])
    p_lgb = lgbm.predict_proba(X_te)[:, 1]
    models_eval["lightgbm"] = eval_binary(y_te, p_lgb)
    models_cal["lightgbm"] = calibration_curve_data(y_te, p_lgb)
    models_roc["lightgbm"] = roc_data(y_te, p_lgb)
    feat_importance = dict(zip(features, lgbm.feature_importances_))
else:
    # Fallback to sklearn GradientBoosting
    gbc = GradientBoostingClassifier(n_estimators=300, learning_rate=0.05, max_depth=4, random_state=0).fit(X_tr, y_tr)
    p_lgb = gbc.predict_proba(X_te)[:, 1]
    models_eval["gradient boosting"] = eval_binary(y_te, p_lgb)
    models_cal["gradient boosting"] = calibration_curve_data(y_te, p_lgb)
    models_roc["gradient boosting"] = roc_data(y_te, p_lgb)
    feat_importance = dict(zip(features, gbc.feature_importances_))
    lgbm = gbc  # alias for downstream SHAP


# %% partial dependence on attendance_ratio
def partial_dependence(model, X, col_idx, grid=None):
    if grid is None:
        vals = X[:, col_idx]
        grid = np.linspace(np.nanpercentile(vals, 5), np.nanpercentile(vals, 95), 30)
    Xc = X.copy()
    preds = []
    for v in grid:
        Xc[:, col_idx] = v
        p = model.predict_proba(Xc)[:, 1].mean()
        preds.append(p)
    return list(grid), preds


att_idx = features.index("attendance_ratio_filled")
grid, pd_preds = partial_dependence(lgbm, X_tr, att_idx)


# %% SHAP values on test set (sampled)
shap_mean_abs = None
shap_waterfall_rows = []
if HAS_SHAP and hasattr(lgbm, "predict_proba"):
    try:
        explainer = shap.TreeExplainer(lgbm)
        test_idx = np.random.default_rng(0).choice(len(X_te), size=min(200, len(X_te)), replace=False)
        sv = explainer.shap_values(X_te[test_idx])
        if isinstance(sv, list):
            sv_pos = sv[1] if len(sv) > 1 else sv[0]
        else:
            sv_pos = sv
        shap_mean_abs = np.abs(sv_pos).mean(axis=0)
        # 5 waterfall examples
        for i in range(min(5, len(test_idx))):
            contributions = list(zip(features, [float(c) for c in sv_pos[i]]))
            shap_waterfall_rows.append({
                "idx": int(test_idx[i]),
                "base_value": float(explainer.expected_value if np.isscalar(explainer.expected_value)
                                    else explainer.expected_value[-1]),
                "pred": float(p_lgb[test_idx[i]]),
                "actual": int(y_te[test_idx[i]]),
                "contributions": contributions,
            })
    except Exception as e:  # noqa: BLE001
        shap_mean_abs = None
        print(f"SHAP failed: {e}")


# %% dashboard
dash = Dashboard(
    title="Phase 6b -- Tree models",
    slug="phase-07-ml-trees",
    subtitle=f"Train={sorted(train_s)} | val={sorted(val_s)} | test={sorted(test_s)}",
)
dash.kpis = [
    {"label": "Best model", "value": min(models_eval, key=lambda k: models_eval[k]["log_loss"])},
    {"label": "Best log-loss", "value": f"{min(m['log_loss'] for m in models_eval.values()):.3f}"},
    {"label": "Models", "value": str(len(models_eval))},
    {"label": "Test games", "value": str(int(te.sum()))},
]


# %% D07-1 comparison table
d07_1 = {
    "type": "table", "id": "D07-1", "title": "Model comparison (held-out test)",
    "columns": ["model", "accuracy", "log-loss", "Brier"],
    "rows": [[m, f"{v['accuracy']:.3f}", f"{v['log_loss']:.3f}", f"{v['brier']:.3f}"]
             for m, v in sorted(models_eval.items(), key=lambda kv: kv[1]["log_loss"])],
    "wide": True,
}


# %% D07-2 calibration overlay
cal_datasets = []
for name, cal in models_cal.items():
    cal_datasets.append({
        "label": name,
        "data": [{"x": c["predicted"], "y": c["empirical"], "n": c["n"]} for c in cal],
        "pointRadius": 5,
    })

d07_2 = {
    "type": "scatter", "id": "D07-2", "title": "Calibration curves overlay",
    "description": "Diagonal = perfect calibration.",
    "xTitle": "predicted probability", "yTitle": "empirical frequency",
    "datasets": cal_datasets,
    "trendline": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
    "trendlineLabel": "perfect",
    "wide": True,
}


# %% D07-3 ROC overlay
roc_datasets = []
for name, r in models_roc.items():
    roc_datasets.append({
        "label": name, "data": r, "pointRadius": 0, "showLine": True,
        "type": "line",
    })

d07_3 = {
    "type": "scatter", "id": "D07-3", "title": "ROC curves overlay",
    "description": "Area under diagonal = random. Higher curve = better.",
    "xTitle": "False Positive Rate", "yTitle": "True Positive Rate",
    "datasets": roc_datasets,
    "trendline": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
    "trendlineLabel": "random",
    "wide": True,
}


# %% D07-4 LightGBM feature importance
fi_sorted = sorted(feat_importance.items(), key=lambda kv: kv[1], reverse=True)
d07_4 = {
    "type": "bar", "id": "D07-4", "title": "LightGBM feature importance",
    "description": "Gain-based importance.",
    "labels": [f for f, _ in fi_sorted],
    "datasets": [{"label": "importance", "data": [float(v) for _, v in fi_sorted]}],
    "horizontal": True, "legend": False,
}


# %% D07-5 Partial dependence plot
d07_5 = {
    "type": "line", "id": "D07-5", "title": "Partial dependence: P(home win) vs attendance_ratio",
    "description": "Holding other features at their training distribution -- the dose-response curve from the tree model.",
    "labels": [f"{g:.2f}" for g in grid],
    "datasets": [{"label": "P(home win)", "data": pd_preds, "color": "#4f8cff"}],
    "yTitle": "P(home win)", "xTitle": "attendance_ratio", "wide": True,
}


# %% D07-6 SHAP summary
if shap_mean_abs is not None:
    order = np.argsort(shap_mean_abs)[::-1]
    d07_6 = {
        "type": "bar", "id": "D07-6", "title": "SHAP mean |value| per feature (test set)",
        "description": "Approximation of the SHAP bees-warm: per-feature mean absolute contribution.",
        "labels": [features[i] for i in order],
        "datasets": [{"label": "mean |SHAP|", "data": [float(shap_mean_abs[i]) for i in order]}],
        "horizontal": True, "legend": False,
    }
else:
    d07_6 = {
        "type": "placeholder", "id": "D07-6", "title": "SHAP summary",
        "message": "SHAP unavailable or failed -- see D07-4 feature importance instead.",
    }


# %% D07-7 SHAP waterfall table
if shap_waterfall_rows:
    d07_7 = {
        "type": "table", "id": "D07-7", "title": "SHAP waterfalls for 5 sample games",
        "description": "Per-feature contribution to the predicted P(home win) for 5 test-set games.",
        "columns": ["game idx", "actual", "predicted", "base"] + features,
        "rows": [
            [w["idx"], w["actual"], f"{w['pred']:.3f}", f"{w['base_value']:.3f}"] +
            [f"{c:+.3f}" for _, c in w["contributions"]]
            for w in shap_waterfall_rows
        ],
        "wide": True,
    }
else:
    d07_7 = {
        "type": "placeholder", "id": "D07-7", "title": "SHAP waterfalls",
        "message": "SHAP unavailable -- waterfalls skipped.",
    }


# %% D07-8 feature importance vs logistic coefficient
d07_8 = {
    "type": "bar", "id": "D07-8",
    "title": "LightGBM importance vs logistic coefficient magnitude",
    "description": "Do the linear and tree models agree on what matters?",
    "labels": features,
    "datasets": [
        {"label": "LightGBM importance (norm)",
         "data": [float(feat_importance[f]) / max(feat_importance.values()) for f in features]},
        {"label": "|logistic coef| (norm)",
         "data": [abs(logistic_coefs[f]) / max(abs(c) for c in logistic_coefs.values()) for f in features]},
    ],
    "yTitle": "normalized magnitude", "wide": True,
}


dash.add_section("compare", "Model comparison", "Baselines vs logistic vs trees.",
                 charts=[d07_1, d07_2, d07_3])
dash.add_section("importance", "Feature importance",
                 "LightGBM and SHAP -- what does the tree model use?",
                 charts=[d07_4, d07_5, d07_6])
dash.add_section("interpret", "Interpretation",
                 "Per-game SHAP + linear-vs-tree agreement.",
                 charts=[d07_7, d07_8])

out = dash.write()
print(f"dashboard: {out}")
print("model eval:")
for m, v in sorted(models_eval.items(), key=lambda kv: kv[1]["log_loss"]):
    print(f"  {m:20s} acc={v['accuracy']:.3f} ll={v['log_loss']:.3f} brier={v['brier']:.3f}")

with open(config.REPORTS_DIR / "trees_output.json", "w") as f:
    json.dump({
        "models_eval": models_eval,
        "models_cal": models_cal,
        "models_roc": models_roc,
        "feature_importance": {k: float(v) for k, v in feat_importance.items()},
        "partial_dependence_attendance": {"x": grid, "y": pd_preds},
    }, f, indent=2)
