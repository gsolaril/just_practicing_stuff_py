import os, numpy
# Limit native thread oversubscription inside each worker process.
# This often prevents abrupt native crashes in NumPy/LAPACK-based workloads
# when running multiple processes from Jupyter on Windows.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

def ols_test(points: int, dim: int = 2, scale: float = 1000, width: float = 20, seed: int = 12345):
    
    rng = numpy.random.default_rng(seed + dim)
    x = rng.standard_normal((dim, points))
    a0 = rng.random() * 2 - 1
    a1 = rng.random(dim) * 2 - 1

    a1 = a1 * scale / width
    x = x * width / scale

    error = rng.standard_normal(points)
    error *= numpy.sqrt(scale)
    y = a0 + (a1 @ x) + error

    coefs, *_ = numpy.linalg.lstsq(x.T, y, rcond=None)
    return list(map(float, coefs))

