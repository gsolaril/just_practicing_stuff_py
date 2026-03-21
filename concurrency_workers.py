from __future__ import annotations


def cpu_burn(iterations: int, dim: int = 2) -> int:
    """Pure-Python CPU work for multiprocessing demos.

    Kept in a separate module so ProcessPoolExecutor workers can import it
    reliably (Jupyter __main__ pickling can be flaky on Windows).
    """
    total = 0
    for i in range(iterations):
        total += (i * dim) % 97
    return total


def ols_numpy_score(points: int, dim: int = 2, scale: float = 1000.0, seed: int = 12345) -> float:
    """CPU-heavy OLS-like score using NumPy only.

    Returns a small scalar so results are cheap to pickle back to the parent.
    We also force single-threaded BLAS behavior (as much as possible) to reduce
    oversubscription crashes on Windows.
    """
    # Ensure we don't spawn lots of native threads inside each worker.
    import os

    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    import numpy as np

    rng = np.random.default_rng(seed + dim)
    x = rng.standard_normal((points, dim))
    # Make y roughly in the same scale as x
    beta_true = rng.standard_normal(dim)
    y = x @ beta_true + rng.standard_normal(points) * (np.sqrt(scale) / 10.0)

    # OLS via least squares: coef shape (dim,)
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    return float(coef.sum())


def ols_numpy_params(
    points: int,
    dim: int = 2,
    scale: float = 1000.0,
    width: float = 20.0,
    seed: int = 12345,
) -> list[float]:
    """OLS-like regression using NumPy only.

    The goal is to mirror the original statsmodels idea:
    - Create random design matrix X with dim features
    - Synthesize y from a random intercept + linear model on X
    - Solve OLS via least squares (NumPy)

    Returns a small list of floats (the parameter vector) to keep results cheap
    to pickle between processes.
    """
    import os

    # Reduce risk of oversubscription inside multiprocessing workers.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    import numpy as np

    rng = np.random.default_rng(seed + dim)

    # Random parameters similar in spirit to the original code.
    a0 = rng.random()  # scalar intercept-like term
    a1 = rng.random(dim)  # linear coefficients
    x = rng.standard_normal((dim, points))

    # Apply scaling to keep magnitudes comparable to the original intent.
    a0 = a0 * 2.0 - 1.0
    a1 = a1 * 2.0 - 1.0
    a1 = a1 * scale / width
    x = x * width / scale

    # y = intercept + linear combination of features, plus noise
    # x has shape (dim, points), so a1 @ x -> (points,)
    y = a0 + (a1 @ x)
    y = y + rng.standard_normal(points) * (np.sqrt(scale) / 10.0)

    # OLS: solve X beta = y, where X = x.T has shape (points, dim).
    X = x.T
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)

    return [float(v) for v in coef]

