"""
simforge_bridge.py — Agent-callable wrapper layer over SimForge, plus an HTTP
bridge to the ARC-SIM platform server.

Why a wrapper layer instead of exposing SimForge's classes as tools directly:
an LLM tool call passes flat JSON kwargs in, and needs JSON-safe data back out.
SimForge's real API deals in fitted PoissonSoccer instances, KellyConfig
dataclasses, and numpy model functions -- none of which survive a JSON round
trip. Every function below takes only JSON-safe args and returns only
JSON-safe dicts, so it drops straight into agent_tools.py's @tool pattern.

Drop this file next to agent_tools.py. See PATCH_agent_tools_simforge.md for
the tool registrations.
"""
from __future__ import annotations
import numpy as np
import requests

from simforge.sports.models import PoissonSoccer, PaceAdjustedBasketball
from simforge.sports.odds import american_to_prob, remove_vig, edge, american_to_decimal
from simforge.sports.bankroll import BankrollManager, KellyConfig
from simforge.core.calibration import calibration_report
from simforge.core.prediction_log import PredictionLog
from simforge.science.templates import sir_stochastic, mm1_queue, gbm_paths

ARC_SIM_BASE_URL = "http://localhost:8000"
PRED_LOG_PATH = "C:\\atherix-red\\simforge_predictions.csv"


# ---------------------------------------------------------------------------
# Sports forecasting (feeds your existing trading-bot / Polymarket work)
# ---------------------------------------------------------------------------
def forecast_soccer_match(matches: list, home: str, away: str,
                           market_odds: dict | None = None) -> dict:
    """matches: [[home, away, home_goals, away_goals], ...] historical results.
    market_odds: optional {"home": american_odds, "draw": ..., "away": ...}."""
    soc = PoissonSoccer().fit([tuple(m) for m in matches])
    probs = soc.match_probs(home, away)
    out = {"model_probs": probs}
    if market_odds:
        raw = [american_to_prob(market_odds[k]) for k in ("home", "draw", "away")]
        fair = remove_vig(raw)
        out["market_fair_probs"] = {"home": fair[0], "draw": fair[1], "away": fair[2]}
        out["edge_home"] = edge(probs["home"], fair[0])
        out["edge_draw"] = edge(probs["draw"], fair[1])
        out["edge_away"] = edge(probs["away"], fair[2])
    return out


def forecast_basketball_matchup(home: str, away: str, team_stats: dict) -> dict:
    """team_stats: {"TeamName": {"off_rtg": .., "def_rtg": .., "pace": ..}, ...}"""
    model = PaceAdjustedBasketball()
    for team, s in team_stats.items():
        model.set_team(team, s["off_rtg"], s["def_rtg"], s["pace"])
    return model.match_probs(home, away)


def check_calibration(predicted_probs: list, outcomes: list) -> dict:
    """outcomes: list of 0/1. Full honesty report -- ECE, Brier, plain verdict."""
    return calibration_report(predicted_probs, outcomes)


def size_bet(p_model: float, american_odds: float, p_market_fair: float,
             bankroll: float, model_ece: float | None = None,
             kelly_fraction: float = 0.25, max_bet_frac: float = 0.02) -> dict:
    """Calibration-gated Kelly sizing. Refuses to size without a proven ECE --
    this is enforced in bankroll.py itself, not re-implemented here."""
    cfg = KellyConfig(fraction=kelly_fraction, max_bet_frac=max_bet_frac)
    bm = BankrollManager(bankroll, cfg)
    dec = bm.size_bet(p_model, american_to_decimal(american_odds), p_market_fair, model_ece)
    return {"stake": dec.stake, "stake_frac": dec.stake_frac, "reason": dec.reason,
            "kelly_raw": dec.kelly_raw, "edge": dec.edge, "blocked": dec.blocked}


def log_prediction(model: str, event: str, p_pred: float, market: str = "",
                    p_market: float | None = None) -> dict:
    log = PredictionLog(PRED_LOG_PATH)
    rid = log.log(model, event, p_pred, market=market, p_market=p_market)
    return {"prediction_id": rid}


def resolve_prediction(prediction_id: str, outcome: int, pnl: float | None = None) -> dict:
    log = PredictionLog(PRED_LOG_PATH)
    log.resolve(prediction_id, outcome, pnl)
    return {"resolved": prediction_id, "outcome": outcome}


# ---------------------------------------------------------------------------
# General science templates -- available to the AGI fork too, not just
# trading: any agent task involving spread, queueing, or growth dynamics.
# ---------------------------------------------------------------------------
def run_epidemic_sim(population: int, initial_infected: int, beta: float,
                      gamma: float, seed: int | None = None) -> dict:
    t, S, I, R = sir_stochastic(N=population, I0=initial_infected, beta=beta,
                                 gamma=gamma, seed=seed)
    return {"peak_infected": int(I.max()), "peak_time": float(t[I.argmax()]),
            "final_recovered": int(R[-1]), "final_susceptible": int(S[-1])}


def run_queue_sim(arrival_rate: float, service_rate: float, t_max: float = 10000,
                   seed: int | None = None) -> dict:
    return mm1_queue(arrival_rate, service_rate, t_max, seed=seed)


def run_gbm_price_paths(s0: float = 100.0, mu: float = 0.05, sigma: float = 0.2,
                         t_years: float = 1.0, n_paths: int = 5000,
                         seed: int | None = None) -> dict:
    paths = gbm_paths(S0=s0, mu=mu, sigma=sigma, t1=t_years, n_paths=n_paths, seed=seed)
    terminal = paths[-1]
    return {"terminal_mean": float(terminal.mean()), "terminal_std": float(terminal.std()),
            "terminal_p5": float(np.percentile(terminal, 5)),
            "terminal_p95": float(np.percentile(terminal, 95))}


# ---------------------------------------------------------------------------
# ARC-SIM bridge -- HTTP, not import, since ARC-SIM runs as its own uvicorn
# process (per its own README). This is the same shape as your existing
# http_request/fetch_url tools, just pointed at your own local server.
# ---------------------------------------------------------------------------
def list_arcsim_modules(base_url: str = ARC_SIM_BASE_URL) -> dict:
    r = requests.get(f"{base_url}/api/modules", timeout=10)
    r.raise_for_status()
    return r.json()


def run_arcsim_view(module_id: str, view_id: str, params: dict,
                     sweep: dict | None = None, base_url: str = ARC_SIM_BASE_URL) -> dict:
    body = {"params": params}
    if sweep:
        body["sweep"] = sweep
    r = requests.post(f"{base_url}/api/{module_id}/{view_id}/run", json=body, timeout=60)
    r.raise_for_status()
    return r.json()
