# Patch: agent_tools.py

Add near the top, with the other imports:

```python
import simforge_bridge as sf
```

Add these tool registrations (anywhere in the file, grouped together is cleanest):

```python
@tool("forecast_soccer_match", "Forecast a soccer match using historical results, optionally comparing to market odds.",
      [{"name": "matches", "description": "List of [home, away, home_goals, away_goals] historical results"},
       {"name": "home", "description": "Home team name for the match to forecast"},
       {"name": "away", "description": "Away team name for the match to forecast"},
       {"name": "market_odds", "description": "Optional dict {home, draw, away} of American odds"}])
def forecast_soccer_match(matches, home, away, market_odds=None):
    return sf.forecast_soccer_match(matches, home, away, market_odds)


@tool("forecast_basketball_matchup", "Forecast a basketball matchup from team ratings.",
      [{"name": "home", "description": "Home team name"},
       {"name": "away", "description": "Away team name"},
       {"name": "team_stats", "description": "Dict of team -> {off_rtg, def_rtg, pace}"}])
def forecast_basketball_matchup(home, away, team_stats):
    return sf.forecast_basketball_matchup(home, away, team_stats)


@tool("check_calibration", "Score a set of probabilistic predictions against actual outcomes -- Brier, ECE, plain-language verdict on whether the probabilities can be trusted.",
      [{"name": "predicted_probs", "description": "List of predicted probabilities [0,1]"},
       {"name": "outcomes", "description": "List of actual outcomes, 0 or 1"}])
def check_calibration(predicted_probs, outcomes):
    return sf.check_calibration(predicted_probs, outcomes)


@tool("size_bet", "Calibration-gated Kelly position sizing. Refuses to size a bet unless a calibration (ECE) score is supplied.",
      [{"name": "p_model", "description": "Model's predicted probability"},
       {"name": "american_odds", "description": "Market odds, American format"},
       {"name": "p_market_fair", "description": "Vig-removed fair market probability"},
       {"name": "bankroll", "description": "Total bankroll available"},
       {"name": "model_ece", "description": "Model's ECE from a real backtest -- required to size anything"}])
def size_bet(p_model, american_odds, p_market_fair, bankroll, model_ece=None):
    return sf.size_bet(p_model, american_odds, p_market_fair, bankroll, model_ece)


@tool("run_epidemic_sim", "Run a stochastic SIR epidemic simulation.",
      [{"name": "population", "description": "Total population N"},
       {"name": "initial_infected", "description": "Initial infected count"},
       {"name": "beta", "description": "Transmission rate"},
       {"name": "gamma", "description": "Recovery rate"}])
def run_epidemic_sim(population, initial_infected, beta, gamma):
    return sf.run_epidemic_sim(population, initial_infected, beta, gamma)


@tool("run_queue_sim", "Run an M/M/1 queue simulation for wait times and utilization.",
      [{"name": "arrival_rate", "description": "Customer arrival rate"},
       {"name": "service_rate", "description": "Service rate"},
       {"name": "t_max", "description": "Simulation time horizon"}])
def run_queue_sim(arrival_rate, service_rate, t_max=10000):
    return sf.run_queue_sim(arrival_rate, service_rate, t_max)


@tool("run_arcsim_view", "Run an ARC-SIM physics module view (fusion energy balance, radial profile, etc). Call list_arcsim_modules first to see what's available and each view's required params.",
      [{"name": "module_id", "description": "e.g. 'fusion'"},
       {"name": "view_id", "description": "e.g. 'energy_balance', 'triple_product', 'radial_profile', 'size_sweep'"},
       {"name": "params", "description": "Dict of params matching that view's params_schema"}])
def run_arcsim_view(module_id, view_id, params):
    return sf.run_arcsim_view(module_id, view_id, params)


@tool("list_arcsim_modules", "List every registered ARC-SIM physics module, its views, and each view's parameter schema.", [])
def list_arcsim_modules():
    return sf.list_arcsim_modules()
```

---

# Note for scope.py

`run_arcsim_view` and `list_arcsim_modules` make HTTP calls, so add them to
`NETWORK_TOOLS` in `scope.py`:

```python
NETWORK_TOOLS = {
    ...
    "run_arcsim_view": ("base_url",),   # only relevant if you override base_url
    "list_arcsim_modules": ("base_url",),
}
```

In practice this won't block anything by default: `ARC_SIM_BASE_URL` points at
`localhost:8000`, and scope.py's default policy already allows `127.0.0.0/8`.
It only matters once you deploy ARC-SIM on the Hostinger VPS (per its README)
and start calling it by VPS IP instead of localhost -- at that point you'll
need `scope.add_to_scope("<vps-ip>", "my own ARC-SIM server")` or the agent's
calls to it will get denied by the same fail-closed logic that protects you
from hitting real targets. Worth doing deliberately rather than being
surprised by it.
