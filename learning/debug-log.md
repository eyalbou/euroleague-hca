# Debug log -- things that went wrong and how we fixed them

One line per incident. Scope: infra, environment, data quirks, numerical issues. Not statistical
findings (those belong in `reports/`).

---

## 2026-04 -- pip resolver hit a private artifactory

**Symptom:** `pip install pandas` failed with `ERROR: Could not find a version that satisfies the
requirement pandas (from versions: none)` and a connection error to
`repo.dev.wixpress.com`.

**Root cause:** Machine pip config pointed to an internal PyPI mirror that wasn't reachable from
this project.

**Fix:** `pip install --index-url https://pypi.org/simple/ -e .[ml]`.

**Prevention:** README now documents the explicit `--index-url` flag for the first install on a new
machine.

---

## 2026-04 -- lightgbm import failed with libomp missing

**Symptom:** `OSError: dlopen(.../lightgbm/lib/lib_lightgbm.dylib, 6): Library not loaded:
@rpath/libomp.dylib`.

**Root cause:** macOS doesn't ship OpenMP runtime by default; lightgbm needs it.

**Fix:** `brew install libomp`.

**Prevention:** Added `brew install libomp` as a prerequisite step in the README's macOS section.

---

## 2026-04 -- `config.DASHBOARD_DIR` typo

**Symptom:** `AttributeError: module 'euroleague_hca.config' has no attribute 'DASHBOARD_DIR'. Did
you mean: 'DASHBOARDS_DIR'?`.

**Root cause:** Attribute is `DASHBOARDS_DIR` (plural), the caller used the singular form.

**Fix:** Rename at the call site.

**Prevention:** None yet -- we should consider adding `from euroleague_hca.config import
DASHBOARDS_DIR as DASHBOARD_DIR` or just standardize on the plural everywhere.

---

## 2026-04 -- LightGBM held-out log-loss was worse than logistic

**Symptom:** LightGBM test log-loss 0.724 vs logistic 0.631 on mock data (~3400 rows).

**Likely cause:** Gradient-boosted tree ensembles overfit small tabular datasets with many
near-duplicate rows. We have ~3400 rows and ~6 features after encoding.

**Action:** Kept LightGBM in the pipeline for learning value, but documented in the final report
that logistic is the production-quality model at this sample size. Regularized LightGBM params
(high `min_data_in_leaf`, low `num_leaves`) would likely close the gap but aren't a priority.

**Prevention:** Always run a logistic baseline first; don't assume more flexible = better.

---

## 2026-04 -- 2023 had double the games of every other season

**Symptom:** `fact_game` grouped by season showed 2023 = 605 games, every other season ~310.

**Root cause:** `pq.write_to_dataset(..., partition_cols=["season"])` *appends* to existing
season partition directories; it does not overwrite. Sequence that triggered the bug:
1. `ELH_SAMPLE=1 python scripts/01_ingest.py` -- wrote mock 2023 games into `bronze/fact_game/season=2023/`
2. `ELH_SAMPLE=0 python scripts/01_ingest.py` -- wrote all 10 seasons; 2023 got a second parquet
   file in the same partition dir.

The silver layer concatenated both, producing 2x rows for 2023 only. All downstream numbers for
2023 were silently double-counted.

**Fix:** `bronze._write_partitioned` now `shutil.rmtree(entity_dir)` before writing. The bronze
layer is now a pure function of raw/ on every run. Re-ran the whole analysis chain; 2023 back to
313 games.

**Prevention lesson:** any layer that rebuilds from an earlier layer should be idempotent by
construction (wipe + rewrite), not by assumption. `pq.write_to_dataset` defaults to appending,
which is surprising if you expect parquet dataset = "table". Alternative: pass
`existing_data_behavior="delete_matching"` -- but wiping the whole directory is cheaper and
catches stale entities too.

---

## 2026-04 -- SHAP + LightGBM deprecation warning

**Symptom:** `LightGBM binary classifier with TreeExplainer shap values output has changed to a
list of ndarray`.

**Root cause:** SHAP >=0.45 changed the return type for LGBM binary classifiers.

**Fix:** Accept either a list of arrays or a single array in the SHAP-aggregation code.

**Prevention:** None -- upstream library change. Pin SHAP version if this breaks again.
