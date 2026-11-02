"""qr_utils: OLS with Newey-West HAC t-stats (no statsmodels available)."""
import numpy as np
from math import erf, sqrt


def ols_nw(y, X, names, nw_lag):
    """OLS with Newey-West (Bartlett) covariance.

    y: (n,) array; X: (n,k) array (include const column yourself).
    Returns dict with beta, se, t, p (normal approx), n, r2.
    """
    y = np.asarray(y, float)
    X = np.asarray(X, float)
    n, k = X.shape
    XtX = X.T @ X
    XtXinv = np.linalg.inv(XtX)
    beta = XtXinv @ (X.T @ y)
    e = y - X @ beta
    # meat
    u = X * e[:, None]  # (n,k) score contributions
    S = u.T @ u
    for l in range(1, nw_lag + 1):
        w = 1.0 - l / (nw_lag + 1.0)
        G = u[l:].T @ u[:-l]
        S += w * (G + G.T)
    V = XtXinv @ S @ XtXinv
    se = np.sqrt(np.maximum(np.diag(V), 0))
    t = np.where(se > 0, beta / se, np.nan)
    p = np.array([2 * (1 - _norm_cdf(abs(x))) if np.isfinite(x) else np.nan for x in t])
    ybar = y.mean()
    r2 = 1 - float((e ** 2).sum() / ((y - ybar) ** 2).sum())
    return {"names": list(names), "beta": beta, "se": se, "t": t, "p": p,
            "n": int(n), "r2": r2, "nw_lag": int(nw_lag)}


def _norm_cdf(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def reg_table(res, nd=6):
    rows = []
    for i, nm in enumerate(res["names"]):
        rows.append({"term": nm, "beta": round(float(res["beta"][i]), nd),
                     "se": round(float(res["se"][i]), nd),
                     "t_nw": round(float(res["t"][i]), 2),
                     "p": round(float(res["p"][i]), 4)})
    return rows


def max_drawdown(equity):
    """Max drawdown (negative fraction) of an equity curve (array)."""
    eq = np.asarray(equity, float)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(dd.min()), dd


def perf_stats(dret, periods_per_year=365):
    """Ann return (arithmetic, rf=0), ann vol, Sharpe from periodic simple returns."""
    r = np.asarray(dret, float)
    r = r[np.isfinite(r)]
    if len(r) < 10:
        return {"n": len(r)}
    mu, sd = r.mean(), r.std(ddof=1)
    ann_ret = mu * periods_per_year
    ann_vol = sd * np.sqrt(periods_per_year)
    # total-compound CAGR too
    eq = np.cumprod(1 + r)
    years = len(r) / periods_per_year
    cagr = eq[-1] ** (1 / years) - 1 if years > 0 else np.nan
    mdd, _ = max_drawdown(eq)
    return {"n": int(len(r)), "ann_ret_arith": float(ann_ret), "cagr": float(cagr),
            "ann_vol": float(ann_vol), "sharpe": float(ann_ret / ann_vol) if ann_vol > 0 else np.nan,
            "mdd": mdd, "total_x": float(eq[-1])}


def spearman(a, b):
    """Spearman rank correlation (no ties handling beyond average ranks)."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    ra = pd_rank(a); rb = pd_rank(b)
    ra = ra - ra.mean(); rb = rb - rb.mean()
    denom = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / denom) if denom > 0 else np.nan


def pd_rank(x):
    x = np.asarray(x, float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), float)
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1
        i = j + 1
    return ranks
