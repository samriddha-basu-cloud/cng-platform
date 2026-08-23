"""
Solver abstraction layer.

The optimization engine (Phase 2) is written against Pyomo's generic
ConcreteModel API. This module is the single place that knows which
solvers are actually installed/licensed in the current environment, so
the rest of the app never hard-codes a solver name.

Preference order (first available wins), open-source first:
  1. HiGHS   (via Pyomo's appsi persistent interface - bundled with `highspy`, no external install)
  2. CBC     (via Pyomo SolverFactory('cbc'), needs the `cbc` binary on PATH)
  3. Gurobi  (via Pyomo SolverFactory('gurobi'), needs a license)
  4. CPLEX   (via Pyomo SolverFactory('cplex'), needs a license)

No commercial solver is required to run this application.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SolverInfo:
    key: str
    display_name: str
    available: bool
    kind: str          # "open-source" | "commercial"
    detail: str = ""


def _check_highs() -> SolverInfo:
    try:
        from pyomo.contrib.appsi.solvers import Highs
        s = Highs()
        ok = s.available()
        return SolverInfo("highs", "HiGHS", bool(ok), "open-source",
                           "via Pyomo appsi + highspy (bundled)")
    except Exception as e:
        return SolverInfo("highs", "HiGHS", False, "open-source", str(e))


def _check_pyomo_solver(key: str, display: str, kind: str) -> SolverInfo:
    try:
        from pyomo.environ import SolverFactory
        sf = SolverFactory(key)
        ok = sf.available(exception_flag=False)
        return SolverInfo(key, display, bool(ok), kind,
                           "found on PATH" if ok else "not found")
    except Exception as e:
        return SolverInfo(key, display, False, kind, str(e))


def detect_solvers() -> list[SolverInfo]:
    return [
        _check_highs(),
        _check_pyomo_solver("cbc", "CBC", "open-source"),
        _check_pyomo_solver("gurobi", "Gurobi", "commercial"),
        _check_pyomo_solver("cplex", "CPLEX", "commercial"),
    ]


def get_active_solver() -> SolverInfo:
    """Returns the first available solver in preference order."""
    for s in detect_solvers():
        if s.available:
            return s
    return SolverInfo("none", "No solver available", False, "n/a",
                       "Install HiGHS (pip install highspy) or CBC to enable optimization.")
