# Patch: server.py

Add the import (next to the other simcore imports):

```python
from simcore.mc_engine import run_monte_carlo
```

Add a new branch in `run_view()`, alongside the existing `instant`/`ode`/`pde`/`sweep_1d`:

```python
    elif kind == "monte_carlo":
        n_sims = params.pop("n_sims", view.get("default_n_sims", 20000))
        seed = params.pop("seed", None)
        result = run_monte_carlo(view["fn"], view["input_specs"], params,
                                  n_sims=n_sims, seed=seed)
```

That's the entire server-side change. `registry.py` needs NO changes -- it
already treats "kind" as an opaque string per view, which is exactly why this
was a one-file patch instead of a rearchitecture.

---

# Worked example: adding an uncertainty view to the fusion module

This goes in `modules/fusion/model.py`, alongside the existing views. It reuses
`physics.energy_balance_rhs` -- same equations, no new physics -- but treats
density `n` as genuinely uncertain (measurement uncertainty is real in plasma
diagnostics) instead of a fixed point, and reports a distribution of outcomes
instead of one curve.

```python
def _energy_balance_uq_view(inputs, params):
    """inputs['n_frac'] ~ sampled multiplier on n (e.g. 0.9-1.1x nominal,
    representing diagnostic uncertainty). Returns final temperature and Q
    as distributions instead of single numbers."""
    import numpy as np
    n_nominal = params["n"]
    n = n_nominal * inputs["n_frac"]
    T0, tau, heating_MW, volume, t_end = (
        params["T0"], params["tau"], params["heating_MW"], params["volume"], params["t_end"]
    )
    # NOTE: running the full scipy ODE solver per Monte Carlo sample would be
    # slow at n_sims=20000. For UQ views, use a much smaller n_sims (a few
    # hundred to a couple thousand) or, where possible, a cheaper closed-form
    # approximation instead of the full solve_ivp path. This is a real
    # performance tradeoff, not a rounding error -- be deliberate about it.
    from simcore.ode_engine import solve_ode
    y0 = [3.0 * n * ph.KEV_TO_J]  # NOTE: n is now an array here (vectorized
                                  # per-sample) -- energy_balance_rhs as written
                                  # assumes scalar n, so a UQ view needs either
                                  # a vectorized rhs or a per-sample Python loop.
                                  # Flagging this rather than papering over it:
                                  # this view needs a small rhs rewrite to be
                                  # correct, not just a wrapper.
    ...

MODULE["views"]["energy_balance_uncertainty"] = {
    "kind": "monte_carlo",
    "name": "Energy Balance (density uncertainty)",
    "fn": _energy_balance_uq_view,
    "input_specs": {"n_frac": {"dist": "normal", "loc": 1.0, "scale": 0.05}},
    "default_n_sims": 2000,  # small on purpose -- see note above
    "params_schema": {
        # same schema as energy_balance -- n here is the NOMINAL value,
        # the actual sampled n varies via n_frac
        "n": {"type": "float", "min": 1e19, "max": 1e21, "default": 1e20, "log": True, "unit": "/m^3"},
        "tau": {"type": "float", "min": 0.01, "max": 10, "default": 3.0, "log": True, "unit": "s"},
        "volume": {"type": "float", "min": 1, "max": 2000, "default": 830, "unit": "m^3"},
        "heating_MW": {"type": "float", "min": 0, "max": 200, "default": 50, "unit": "MW"},
        "T0": {"type": "float", "min": 0.1, "max": 20, "default": 2.0, "unit": "keV"},
        "t_end": {"type": "float", "min": 1, "max": 200, "default": 60, "unit": "s"},
    },
}
```

**Being straight about this example:** I left the vectorization gap visible
instead of hiding it behind fake-working code, because `energy_balance_rhs`
as written takes a scalar `n` and this view needs it to handle an array of
sampled `n` values (one per Monte Carlo trial) simultaneously for it to run at
any reasonable speed. That's maybe 20 minutes of real work (vectorize the rhs
or loop over samples calling solve_ode per-sample, which is simpler but much
slower). Say the word if you want that actually finished rather than sketched.

The `instant`-kind views (`triple_product`, `size_sweep`) are the better first
target for a monte_carlo sibling view, since they're plain functions with no
solver in the loop -- e.g. a `triple_product_uncertainty` view sampling `n`,
`T`, and `tau` all as distributions would work today with zero rhs rewriting,
just by pointing `input_specs` at `physics.triple_product` directly.
