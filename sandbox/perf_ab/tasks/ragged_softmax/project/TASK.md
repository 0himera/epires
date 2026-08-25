# Task: optimize a ragged softmax kernel

Optimize `src/kernel.cpp` while preserving the API and numerical behavior in
`include/ragged_softmax.h`.

The primary objective is the geometric-mean runtime on private workloads. The
submission receives zero performance credit if any private correctness case
fails. You may use C++17, AVX2/FMA available through `-march=native`, and
OpenMP, but no new external dependencies.

Useful commands:

```sh
make check
make bench
```

Only `src/kernel.cpp` is part of the submitted solution. Do not edit the API,
Makefile, baseline, benchmark, or tests. Finish with the best correct
implementation in the working tree, not merely a description of it.
