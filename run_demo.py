"""End-to-end demo + smoke test for SimForge. Run from /home/claude."""
import sys
import numpy as np
sys.path.insert(0, "/home/claude")

from simforge.core.engine import MonteCarloEngine, HAS_NUMBA
from simforge.core.calibration import calibration_report, reliability_table
from simforge.core.backtest import walk_forward_backtest, one_at_a_time, tornado
from simforge.core.prediction_log import PredictionLog
from simforge.sports.models import PoissonSoccer, PaceAdjustedBasketball
from simforge.sports.ratings import Elo, Glicko2
from simforge.sports.odds import american_to_prob, remove_vig, overround, edge, american_to_decimal
from simforge.sports.bankroll import BankrollManager, KellyConfig
from simforge.science.templates import sir_stochastic, mm1_queue, gbm_paths
from simforge.science.sweep import sweep_1d, sweep_2d, latin_hypercube
from simforge.viz import plots

print(f"numba acceleration available: {HAS_NUMBA}")
print("=" * 64)

# ---- 1. Monte Carlo engine + convergence
print("\n[1] Monte Carlo engine — European call option pricing")
def call_payoff(inp, p):
    ST = 100 * np.exp((p["r"] - 0.5*p["sig"]**2)*p["T"] + p["sig"]*np.sqrt(p["T"])*inp["z"])
    return {"payoff": np.exp(-p["r"]*p["T"]) * np.maximum(ST - p["K"], 0)}
eng = MonteCarloEngine(n_sims=200_000, seed=1)
res = eng.run(call_payoff, input_specs={"z": {"dist": "normal"}},
              params={"r": 0.03, "sig": 0.2, "T": 1.0, "K": 100})
s = res.summary()["payoff"]
print(f"    price estimate: {s['mean']:.4f} ± {s['se_mean']:.4f} (Black-Scholes ref 9.4134)")

# ---- 2. Calibration on a deliberately overconfident model
print("\n[2] Calibration — catching an overconfident model")
rng = np.random.default_rng(0)
true_p = rng.uniform(0, 1, 3000)
y = (rng.uniform(size=3000) < true_p).astype(int)
overconf = np.clip((true_p - 0.5) * 1.6 + 0.5, 0.001, 0.999)  # pushed toward extremes
rep = calibration_report(overconf, y)
print(f"    ECE={rep['ece']:.3f}  Brier={rep['brier']:.3f}  gap={rep['signed_calibration_gap']:+.3f}")
print(f"    verdict: {rep['verdict']}")

# ---- 3. Sports: Poisson soccer + odds comparison + calibrated Kelly
print("\n[3] Sports — soccer model vs market, then sized bet")
matches = [("A","B",2,1),("B","C",0,0),("C","A",1,3),("A","C",2,2),
           ("B","A",1,1),("C","B",2,0)]
soc = PoissonSoccer().fit(matches)
mp = soc.match_probs("A", "B")
print(f"    model P(home/draw/away) = {mp['home']:.3f}/{mp['draw']:.3f}/{mp['away']:.3f}")
# fake market: -140 home, +260 draw, +320 away
mkt_raw = [american_to_prob(-140), american_to_prob(260), american_to_prob(320)]
fair = remove_vig(mkt_raw)
print(f"    market overround = {overround(mkt_raw):.3f}, fair home = {fair[0]:.3f}")
print(f"    edge on home = {edge(mp['home'], fair[0]):+.3f}")

bm = BankrollManager(1000, KellyConfig(fraction=0.25, max_bet_frac=0.02))
# first without calibration proof -> should block
d0 = bm.size_bet(mp["home"], american_to_decimal(-140), fair[0], model_ece=None)
print(f"    no-calibration attempt: {d0.reason}")
# now with a good ECE
d1 = bm.size_bet(mp["home"], american_to_decimal(-140), fair[0], model_ece=0.03)
print(f"    with ECE=0.03: stake=${d1.stake} ({d1.stake_frac:.2%})  [{d1.reason}]")

# ---- 4. Ratings
print("\n[4] Ratings — Elo + Glicko2")
elo = Elo(k=24, home_adv=50)
for h,a,hs in [("A","B",1),("B","C",1),("A","C",0)]:
    elo.update(h,a,hs)
print(f"    Elo A={elo.rating('A'):.0f} B={elo.rating('B'):.0f} C={elo.rating('C'):.0f}")
g = Glicko2()
g.update_match("A","B",1); g.update_match("A","B",1)
print(f"    Glicko A win prob vs B = {g.win_prob('A','B'):.3f}  (A rd={g.get('A').rd:.1f})")

# ---- 5. Backtest walk-forward with market comparison
print("\n[5] Walk-forward backtest — model vs market calibration")
data = []
for i in range(800):
    strength = rng.uniform(-1, 1)
    p_true = 1/(1+np.exp(-strength))
    out = int(rng.uniform() < p_true)
    p_mkt = np.clip(p_true + rng.normal(0, 0.05), 0.01, 0.99)
    data.append({"strength": strength, "outcome": out, "mkt": p_mkt})
def predict(hist, feat):
    return 1/(1+np.exp(-0.9*feat["strength"]))  # slightly shrunk model
bt = walk_forward_backtest(data, predict, market_key="mkt")
cmp = bt.vs_market()
print(f"    model Brier={cmp['model']['brier']:.3f} ECE={cmp['model']['ece']:.3f}")
print(f"    market Brier={cmp['market']['brier']:.3f} ECE={cmp['market']['ece']:.3f}")

# ---- 6. Sensitivity
print("\n[6] Sensitivity — tornado on the option model")
def price_scalar(inp, p):
    z = np.random.default_rng(2).standard_normal(20000)
    ST = 100*np.exp((p["r"]-0.5*p["sig"]**2)*p["T"]+p["sig"]*np.sqrt(p["T"])*z)
    return np.exp(-p["r"]*p["T"])*np.maximum(ST-p["K"],0)
def wrap(inp, p):  # inputs carried in p for tornado convenience
    return price_scalar(inp, inp)
base = {"r":0.03,"sig":0.2,"T":1.0,"K":100}
torn = tornado(wrap, base, {"sig":(0.1,0.4),"K":(90,110),"r":(0.0,0.06)})
for b in torn["bars"]:
    print(f"    {b['input']:4s} span={b['span']:.3f}")

# ---- 7. Science templates
print("\n[7] Science templates")
t,S,I,R = sir_stochastic(N=5000, I0=5, beta=0.35, gamma=0.1, seed=3)
print(f"    stochastic SIR peak infected = {I.max()} at t={t[I.argmax()]:.1f}")
q = mm1_queue(0.8, 1.0, t_max=50000, seed=4)
wq_theory = q['rho'] / (1 - q['rho'])  # 4.0 for rho=0.8
print(f"    M/M/1 rho={q['rho']:.2f} Wq={q['mean_queue_wait']:.2f} (theory {wq_theory:.2f}) "
      f"W={q['mean_time_in_system']:.2f} (theory {wq_theory + 1/1.0:.2f})")
paths = gbm_paths(n_paths=5000, seed=5)
print(f"    GBM terminal mean={paths[-1].mean():.2f} (expect ~105.1)")

# ---- 8. Parameter sweep
print("\n[8] Parameter sweep — R0 vs final epidemic size")
def final_size(beta, gamma):
    _,S,_,_ = sir_stochastic(N=2000, I0=5, beta=beta, gamma=gamma, seed=7)[0:4] if False else (0,)*4
    t,S,I,R = sir_stochastic(N=2000, I0=5, beta=beta, gamma=gamma, seed=7)
    return R[-1]/2000
sw = sweep_1d(final_size, "beta", np.linspace(0.12, 0.5, 6), base={"gamma":0.1})
print(f"    final size across beta: {np.round(sw['output'],2)}")

# ---- 9. Prediction log + drift
print("\n[9] Prediction log — resolve + rolling calibration")
log = PredictionLog("/home/claude/preds.csv")
ids = []
for i in range(120):
    p = float(np.clip(rng.uniform(), 0.01, 0.99))
    rid = log.log("soccer_poisson", f"match_{i}", p, market="polymarket")
    ids.append((rid, p))
for rid, p in ids:
    log.resolve(rid, int(rng.uniform() < p))
roll = log.rolling_calibration(window=30)
print(f"    logged {len(ids)} preds, rolling Brier last value = {roll[-1]:.3f}")

# ---- 10. Figures
print("\n[10] Rendering figures...")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(7,4)); plots.plot_distribution(res.outputs["payoff"], "Option payoff", ax=ax)
plots.save(fig, "/home/claude/fig_dist.png")
fig, ax = plt.subplots(figsize=(5.5,5.5)); plots.plot_reliability(reliability_table(overconf,y), "Overconfident model", ax=ax)
plots.save(fig, "/home/claude/fig_reliability.png")
fig, ax = plt.subplots(figsize=(7,4)); plots.plot_convergence(res.convergence("payoff"), ax=ax)
plots.save(fig, "/home/claude/fig_convergence.png")
print("    saved 3 figures")
print("\n" + "="*64 + "\nALL MODULES OK")
