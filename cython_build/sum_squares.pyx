
# distutils: language=c
# cython: language_level=3

def sum_squares_cy(int n):
    cdef long i, total
    total = 0
    for i in range(n):
        total += i * i
    return total
