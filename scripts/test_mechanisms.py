import pandas as pd
import numpy as np
from euroleague_hca import config

fact_gt = pd.read_parquet(config.SILVER_DIR / "fact_game_team_stats.parquet")

# Filter to games where we have boxscore stats
fact_gt = fact_gt.dropna(subset=["fga", "fta", "orb", "tov"])

# We need home vs away for the same games
home = fact_gt[fact_gt["is_home"] == 1].set_index("game_id")
away = fact_gt[fact_gt["is_home"] == 0].set_index("game_id")

common_games = home.index.intersection(away.index)
home = home.loc[common_games]
away = away.loc[common_games]

# Gaps (Home - Away)
# eFG% = (FGM + 0.5 * 3PM) / FGA
home_efg = (home["fgm"] + 0.5 * home["fg3m"]) / home["fga"]
away_efg = (away["fgm"] + 0.5 * away["fg3m"]) / away["fga"]
efg_gap = (home_efg - away_efg).mean() * 100

home_3p = home["fg3m"] / home["fg3a"].replace(0, np.nan)
away_3p = away["fg3m"] / away["fg3a"].replace(0, np.nan)
p3_gap = (home_3p - away_3p).mean() * 100

home_ft = home["ftm"] / home["fta"].replace(0, np.nan)
away_ft = away["ftm"] / away["fta"].replace(0, np.nan)
ft_gap = (home_ft - away_ft).mean() * 100

# Per 100 poss
home_poss = home["possessions"]
away_poss = away["possessions"] # should be same as home_poss

fta_gap = ((home["fta"] - away["fta"]) / home_poss).mean() * 100
foul_gap = ((home["pf"] - away["pf"]) / home_poss).mean() * 100 # negative is better for home
tov_gap = ((home["tov"] - away["tov"]) / home_poss).mean() * 100 # negative is better for home

# ORB% = ORB / (ORB + opp_DRB)
home_orb_pct = home["orb"] / (home["orb"] + away["drb"])
away_orb_pct = away["orb"] / (away["orb"] + home["drb"])
orb_gap = (home_orb_pct - away_orb_pct).mean() * 100

print(f"eFG% gap: {efg_gap:.2f}%")
print(f"3P% gap: {p3_gap:.2f}%")
print(f"FT% gap: {ft_gap:.2f}%")
print(f"FTA gap per 100: {fta_gap:.2f}")
print(f"Foul gap per 100: {foul_gap:.2f}")
print(f"TOV gap per 100: {tov_gap:.2f}")
print(f"ORB% gap: {orb_gap:.2f}%")

# Regression decomposition
import statsmodels.api as sm

y = home["point_diff"]
X = pd.DataFrame({
    "efg_gap": home_efg - away_efg,
    "p3_gap": home_3p - away_3p,
    "ft_gap": home_ft - away_ft,
    "fta_gap": (home["fta"] - away["fta"]) / home_poss * 100,
    "foul_gap": (home["pf"] - away["pf"]) / home_poss * 100,
    "tov_gap": (home["tov"] - away["tov"]) / home_poss * 100,
    "orb_gap": home_orb_pct - away_orb_pct
}).fillna(0)

X = sm.add_constant(X)
model = sm.OLS(y, X).fit()
print(model.summary())


means = X.mean()
contribs = model.params * means
print("\nContributions to HCA:")
print(contribs)
print("Sum of contribs:", contribs.sum())
print("Actual HCA:", y.mean())
