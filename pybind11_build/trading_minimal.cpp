
#include <pybind11/pybind11.h>

namespace py = pybind11;

// A simple free function: add two numbers
double add(double a, double b) {
    return a + b;
}

PYBIND11_MODULE(trading_minimal, m) {
    m.doc() = "Minimal pybind11 example: add(a, b)";
    m.def("add", &add, "Add two numbers", py::arg("a"), py::arg("b"));
}
