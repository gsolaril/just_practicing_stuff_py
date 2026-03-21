
from setuptools import setup, Extension
import sys
import pybind11

include_dirs = [pybind11.get_include()]

ext_modules = [
    Extension(
        "trading_minimal",
        ["trading_minimal.cpp"],
        include_dirs=include_dirs,
        language="c++",
        extra_compile_args=["-std=c++14"],
    )
]

setup(
    name="trading_minimal",
    version="0.0.1",
    ext_modules=ext_modules,
)
