import subprocess
import sys

print("Starting EuroLeague and EuroCup pipelines in parallel...")

p1 = subprocess.Popen([sys.executable, "scripts/run_master_E.py"])
p2 = subprocess.Popen([sys.executable, "scripts/12_eurocup.py"])

p1.wait()
p2.wait()

print("Both pipelines finished.")
