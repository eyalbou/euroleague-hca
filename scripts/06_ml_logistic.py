"""Phase 6a -- Logistic regression + baselines with time-based CV.

Builds one row per GAME (home perspective). Target = home_win.

D06-1 calibration curve
D06-2 coefficient plot with 95% CIs
D06-3 odds-ratio KPI card for is_home
D06-4 interaction coefficient is_home * attendance_ratio
D06-5 train/val/test log-loss over CV folds
"""
# %% imports
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.evals import calibration_curve_data, eval_binary, time_based_splits
from euroleague_hca.warehouse import query


# %% load -- one row per GAME, home perspective
print(config.banner())
home = query("SELECT * FROM feat_game_team WHERE is_home=1")
home["date"] = pd.to_datetime(home["date"])

# Target
home["home_win"] = (home["point_diff"] > 0).astype(int)

# Features
home["elo_diff"] = home["team_elo_pre"] - home["opp_elo_pre"]
home["attendance_ratio_filled"] = home["attendance_ratio"].fillna(home["attendance_ratio"].mean())
home["attendance_missing"] = home["attendance_ratio"].isna().astype(int)
home["is_home_col"] = 1  # for interaction (meaningless here since all rows are home)

# Rest diff -- we need both teams' rest; approximate via team days_rest
home["days_rest_filled"] = home["days_rest"].fillna(home["days_rest"].median())


# %% Baselines
base_majority = float(home["home_win"].mean())
base_home_always = 1.0


# %% Time-based CV
seasons = home["season"].values
splits = time_based_splits(seasons)
if not splits:
    raise RuntimeError("Not enough seasons for time-based CV")

features_base = ["elo_diff", "is_playoff", "days_rest_filled"]
features_att = features_base + ["attendance_ratio_filled", "attendance_missing"]

# We cannot include `is_home * attendance_ratio` as interaction here because every row is_home=1.
# For that interaction, we need to expand: reshape each game as two rows (home, away) and predict
# margin. We'll model it explicitly in a SEPARATE dataset.

fold_metrics = []
coefs_last = None
scaler_last = None
features_last = None

for i, (tr, va, te) in enumerate(splits):
    train = home.iloc[tr]
    val = home.iloc[va]
    test = home.iloc[te]
    X_cols = features_att

    scaler = StandardScaler()
    X_tr = scaler.fit_transform(train[X_cols])
    X_va = scaler.transform(val[X_cols])
    X_te = scaler.transform(test[X_cols])
    y_tr = train["home_win"].values
    y_va = val["home_win"].values
    y_te = test["home_win"].values

    lr = LogisticRegression(max_iter=1000)
    lr.fit(X_tr, y_tr)

    p_tr = lr.predict_proba(X_tr)[:, 1]
    p_va = lr.predict_proba(X_va)[:, 1]
    p_te = lr.predict_proba(X_te)[:, 1]

    fold_metrics.append({
        "fold": i, "train_ll": eval_binary(y_tr, p_tr)["log_loss"],
        "val_ll": eval_binary(y_va, p_va)["log_loss"],
        "test_ll": eval_binary(y_te, p_te)["log_loss"],
        "test_acc": eval_binary(y_te, p_te)["accuracy"],
        "test_brier": eval_binary(y_te, p_te)["brier"],
    })
    coefs_last = lr.coef_[0]
    scaler_last = scaler
    features_last = X_cols


# %% Final fit on everything for coefficients + calibration
X_cols = features_att
scaler = StandardScaler()
X_all = scaler.fit_transform(home[X_cols])
y_all = home["home_win"].values
lr = LogisticRegression(max_iter=1000)
lr.fit(X_all, y_all)
p_all = lr.predict_proba(X_all)[:, 1]

cal = calibration_curve_data(y_all, p_all, n_bins=10)

# SE approximation via bootstrap
rng = np.random.default_rng(42)
coef_draws = []
for _ in range(200):
    idx = rng.integers(0, len(home), len(home))
    lr_b = LogisticRegression(max_iter=500)
    lr_b.fit(X_all[idx], y_all[idx])
    coef_draws.append(lr_b.coef_[0])
coef_draws = np.array(coef_draws)
coef_ci = [(float(np.percentile(coef_draws[:, j], 2.5)), float(np.percentile(coef_draws[:, j], 97.5)))
           for j in range(X_all.shape[1])]


# %% Second dataset for is_home * attendance_ratio interaction
# Reshape: one row per team-game
fgt = query("SELECT * FROM feat_game_team")
fgt["date"] = pd.to_datetime(fgt["date"])
fgt["team_win"] = (fgt["point_diff"] > 0).astype(int)
fgt["elo_diff_team"] = fgt["team_elo_pre"] - fgt["opp_elo_pre"]
fgt["attendance_ratio_filled"] = fgt["attendance_ratio"].fillna(fgt["attendance_ratio"].mean())
fgt["attendance_missing"] = fgt["attendance_ratio"].isna().astype(int)
fgt["days_rest_filled"] = fgt["days_rest"].fillna(fgt["days_rest"].median())
fgt["is_home_x_att"] = fgt["is_home"] * fgt["attendance_ratio_filled"]

inter_features = [
    "is_home", "elo_diff_team", "is_playoff", "days_rest_filled",
    "attendance_ratio_filled", "attendance_missing", "is_home_x_att",
]
scaler2 = StandardScaler()
X_int = scaler2.fit_transform(fgt[inter_features])
y_int = fgt["team_win"].values
lr2 = LogisticRegression(max_iter=1000)
lr2.fit(X_int, y_int)
int_coefs = lr2.coef_[0]
int_odds = {f: float(np.exp(c)) for f, c in zip(inter_features, int_coefs)}


# %% dashboard
is_home_coef_idx = inter_features.index("is_home")
is_home_odds = float(np.exp(int_coefs[is_home_coef_idx]))
# Probability lift at 50/50 Elo matchup: from 0.5 to is_home_odds / (1 + is_home_odds)
prob_lift = is_home_odds / (1 + is_home_odds) - 0.5

dash = Dashboard(
    title="Phase 6a -- Logistic regression + baselines",
    slug="phase-06-ml-logistic",
    subtitle="Time-based CV. Target = home_win.",
)
dash.kpis = [
    {"label": "is_home OR", "value": f"{is_home_odds:.2f}",
     "caption": f"+{prob_lift*100:.1f}pp at 50/50 matchup"},
    {"label": "Home baseline", "value": f"{base_majority*100:.1f}%"},
    {"label": "CV folds", "value": str(len(fold_metrics))},
    {"label": "N games", "value": str(len(home))},
]


# %% D06-1 calibration curve
d06_1 = {
    "type": "scatter", "id": "D06-1", "title": "Calibration curve (logistic)",
    "description": "Predicted P(home wins) vs observed frequency. Diagonal = perfect calibration.",
    "xTitle": "predicted probability", "yTitle": "empirical frequency",
    "datasets": [
        {"label": "bins", "data": [{"x": c["predicted"], "y": c["empirical"], "n": c["n"]} for c in cal],
         "color": "#4f8cff", "pointRadius": 6},
    ],
    "trendline": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
    "trendlineLabel": "perfect",
}


# %% D06-2 coefficient plot with CI (base model)
d06_2 = {
    "type": "forest", "id": "D06-2", "title": "Logistic coefficients (standardized) with 95% bootstrap CI",
    "description": "Home-only model. Coefs on z-scored features.",
    "teams": [
        {"label": f, "mean": float(coefs_last[i]),
         "lo": coef_ci[i][0], "hi": coef_ci[i][1]}
        for i, f in enumerate(features_last)
    ],
    "xTitle": "coefficient (standardized)", "wide": True,
}


# %% D06-3 odds-ratio card (text chart)
d06_3 = {
    "type": "text", "id": "D06-3", "title": "is_home odds ratio in plain English",
    "html": f"""
        <p>The logistic model's coefficient on <code>is_home</code> translates to an
        <strong>odds ratio of {is_home_odds:.2f}</strong>.</p>
        <p>Practical interpretation: at a completely even (50/50) Elo matchup, being the home team raises
        the predicted win probability from 50% to <strong>{(is_home_odds/(1+is_home_odds))*100:.1f}%</strong>
        -- a lift of <strong>{prob_lift*100:+.1f} percentage points</strong>.</p>
        <p>This is the headline ML answer to "how much does HCA matter?".</p>
    """,
}


# %% D06-4 interaction coefficient
d06_4 = {
    "type": "text", "id": "D06-4", "title": "is_home x attendance_ratio interaction",
    "html": f"""
        <p>Including an interaction term <code>is_home * attendance_ratio</code> gives:</p>
        <ul>
          <li><code>is_home</code> main effect: odds ratio = <strong>{int_odds['is_home']:.2f}</strong></li>
          <li><code>attendance_ratio</code> main effect: odds ratio = <strong>{int_odds['attendance_ratio_filled']:.2f}</strong></li>
          <li><code>is_home x attendance_ratio</code>: odds ratio = <strong>{int_odds['is_home_x_att']:.2f}</strong></li>
        </ul>
        <p>Sign of the interaction tells us whether home advantage grows or shrinks as the arena fills.
        An odds ratio > 1 means home advantage strengthens with higher attendance -- evidence for H6
        (attendance dose-response).</p>
    """,
}


# %% D06-5 fold log-loss
d06_5 = {
    "type": "line", "id": "D06-5", "title": "Train / val / test log-loss across CV folds",
    "description": "Walk-forward folds; train expands, val is next season, test is the season after.",
    "labels": [f"fold {m['fold']}" for m in fold_metrics],
    "datasets": [
        {"label": "train", "data": [m["train_ll"] for m in fold_metrics], "color": "#9aa4b2"},
        {"label": "val", "data": [m["val_ll"] for m in fold_metrics], "color": "#f5c264"},
        {"label": "test", "data": [m["test_ll"] for m in fold_metrics], "color": "#4f8cff"},
    ],
    "yTitle": "log-loss",
}


# Baselines comparison table
baseline_rows = [
    ["home-always", f"{base_home_always:.3f}", "--", "--"],
    ["majority class", f"{base_majority:.3f}", "--", "--"],
]
mean_test_acc = float(np.mean([m["test_acc"] for m in fold_metrics]))
mean_test_ll = float(np.mean([m["test_ll"] for m in fold_metrics]))
mean_test_br = float(np.mean([m["test_brier"] for m in fold_metrics]))
baseline_rows.append(["logistic (this model)", f"{mean_test_acc:.3f}", f"{mean_test_ll:.3f}", f"{mean_test_br:.3f}"])

baseline_table = {
    "type": "table", "id": "D06-0", "title": "Baselines vs logistic (held-out test folds)",
    "columns": ["model", "accuracy", "log-loss", "Brier"],
    "rows": baseline_rows, "wide": True,
}


dash.add_section("calibration", "Calibration + coefficients",
                 "Does the model's 0.7 really mean 70%?", charts=[d06_1, d06_2])
dash.add_section("headline", "Odds-ratio headline",
                 "Plain-English translation of the is_home coefficient.",
                 charts=[d06_3, d06_4])
dash.add_section("cv", "Cross-validation", "Walk-forward folds.",
                 charts=[d06_5, baseline_table])

out = dash.write()
print(f"dashboard: {out}")
print(f"is_home odds ratio = {is_home_odds:.3f} | prob lift at 50/50 = +{prob_lift*100:.1f}pp")
print(f"mean test log-loss = {mean_test_ll:.3f} | mean test acc = {mean_test_acc:.3f}")

# Save model output for integrated dashboard
import json
with open(config.REPORTS_DIR / "logistic_output.json", "w") as f:
    json.dump({
        "is_home_odds": is_home_odds,
        "prob_lift_pp": prob_lift * 100,
        "mean_test_log_loss": mean_test_ll,
        "mean_test_accuracy": mean_test_acc,
        "mean_test_brier": mean_test_br,
        "baseline_home_always_acc": base_home_always,
        "baseline_majority_acc": base_majority,
        "interaction_ORs": int_odds,
        "calibration_full": cal,
    }, f, indent=2)
