import os
import subprocess

print("Running EuroLeague master pipeline...")
os.environ["ELH_COMPETITION"] = "E"

scripts = [
    "scripts/01_ingest.py",
    "scripts/02_validate.py",
    "scripts/03_features.py",
    "scripts/04_descriptive_hca.py",
    "scripts/04b_descriptive_ext.py",
    "scripts/05_hypothesis_tests.py",
    "scripts/06_ml_logistic.py",
    "scripts/07_ml_trees.py",
    "scripts/07b_hierarchical.py",
    "scripts/07c_mixedlm.py",
    "scripts/07d_ridge_fe.py",
    "scripts/08_covid_experiment.py",
    "scripts/09_integrated_dashboard.py",
    "scripts/10_analyst_dashboard.py"
]

for s in scripts:
    print(f"Running {s}...")
    subprocess.run([".venv/bin/python", s], check=True)

print("EuroLeague master pipeline complete.")
