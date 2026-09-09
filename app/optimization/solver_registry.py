"""
Solver abstraction layer.

The optimization engine (Phase 2) is written against Pyomo's generic
ConcreteModel API. This module is the single place that knows which
solvers are actually installed/licensed in the current environment, so
the rest of the app never hard-codes a solver name.

Preference order (first available wins), open-source first:
  1. HiGHS   (via Pyomo's appsi persistent interface - bundled with `highspy`, no external install)
  2. CBC     (via Pyomo SolverFactory('cbc') - PATH first, falling back to the CBC binary
              bundled inside the `pulp` package for the current OS/architecture, so no
              separate system install is needed either)
  3. Gurobi  (via Pyomo SolverFactory('gurobi'), needs a paid license - genuinely can't be
              auto-installed: Gurobi is closed-source and its license is tied to a machine/user)
  4. CPLEX   (via Pyomo SolverFactory('cplex'), same story - IBM commercial, license-gated)

No commercial solver is required to run this application - HiGHS and CBC are both
fully open-source and both work out of the box. Gurobi/CPLEX are detected if
you've separately installed and licensed them (common in industry/enterprise
deployments that already hold a license), used automatically as they outrank
nothing in practice but appear lower in preference since they're not guaranteed
present - the app never requires them.
"""
import os
import platform
import stat
from dataclasses import dataclass
from typing import Optional


@dataclass
class SolverInfo:
    key: str
    display_name: str
    available: bool
    kind: str          # "open-source" | "commercial"
    detail: str = ""
    executable: Optional[str] = None  # explicit binary path, when not resolved from PATH


def _check_highs() -> SolverInfo:
    try:
        from pyomo.contrib.appsi.solvers import Highs
        s = Highs()
        ok = s.available()
        return SolverInfo("highs", "HiGHS", bool(ok), "open-source",
                           "via Pyomo appsi + highspy (bundled)")
    except Exception as e:
        return SolverInfo("highs", "HiGHS", False, "open-source", str(e))


def _bundled_cbc_path() -> Optional[str]:
    """Locates the CBC binary bundled inside the `pulp` package for this OS/
    architecture, if `pulp` is installed. `pulp` ships prebuilt CBC binaries
    for common platforms (macOS x86_64, Windows, Linux x86_64/x86/arm64) so
    CBC can work without asking anyone to install a system package or set up
    a PATH entry themselves."""
    try:
        import pulp
    except ImportError:
        return None

    system = platform.system().lower()  # 'darwin' | 'linux' | 'windows'
    machine = platform.machine().lower()  # 'x86_64' | 'arm64' | 'aarch64' | ...
    os_dir = {"darwin": "osx", "linux": "linux", "windows": "win"}.get(system)
    if os_dir is None:
        return None
    if machine in ("arm64", "aarch64"):
        arch_dirs = ["arm64", "i64"]  # fall back to x86_64 build (may run via emulation)
    elif machine in ("x86_64", "amd64"):
        arch_dirs = ["i64"]
    else:
        arch_dirs = ["i32", "i64"]

    base = os.path.join(os.path.dirname(pulp.__file__), "solverdir", "cbc", os_dir)
    exe_name = "cbc.exe" if os_dir == "win" else "cbc"
    for arch_dir in arch_dirs:
        candidate = os.path.join(base, arch_dir, exe_name)
        if os.path.isfile(candidate):
            try:
                mode = os.stat(candidate).st_mode
                os.chmod(candidate, mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            except OSError:
                pass
            return candidate
    return None


def _check_cbc() -> SolverInfo:
    from pyomo.environ import SolverFactory
    try:
        sf = SolverFactory("cbc")
        if sf.available(exception_flag=False):
            return SolverInfo("cbc", "CBC", True, "open-source", "found on PATH")
    except Exception:
        pass

    bundled = _bundled_cbc_path()
    if bundled:
        try:
            sf = SolverFactory("cbc", executable=bundled)
            if sf.available(exception_flag=False):
                return SolverInfo("cbc", "CBC", True, "open-source",
                                   "bundled CBC binary via the `pulp` package (no separate install needed)",
                                   executable=bundled)
        except Exception as e:
            return SolverInfo("cbc", "CBC", False, "open-source", f"bundled binary found but failed to run: {e}")

    return SolverInfo("cbc", "CBC", False, "open-source",
                       "not found - install the `cbc` system package, or `pip install pulp` to use its bundled binary")


def _check_pyomo_solver(key: str, display: str, kind: str) -> SolverInfo:
    try:
        from pyomo.environ import SolverFactory
        sf = SolverFactory(key)
        ok = sf.available(exception_flag=False)
        detail = "found on PATH" if ok else f"not found - requires a separate {display} install and a valid license"
        return SolverInfo(key, display, bool(ok), kind, detail)
    except Exception as e:
        return SolverInfo(key, display, False, kind, str(e))


def detect_solvers() -> list[SolverInfo]:
    return [
        _check_highs(),
        _check_cbc(),
        _check_pyomo_solver("gurobi", "Gurobi", "commercial"),
        _check_pyomo_solver("cplex", "CPLEX", "commercial"),
    ]


def get_active_solver() -> SolverInfo:
    """Returns the first available solver in preference order."""
    for s in detect_solvers():
        if s.available:
            return s
    return SolverInfo("none", "No solver available", False, "n/a",
                       "Install HiGHS (pip install highspy) or CBC (pip install pulp) to enable optimization.")
