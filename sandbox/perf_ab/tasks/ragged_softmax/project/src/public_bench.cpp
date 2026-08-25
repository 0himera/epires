#include "ragged_softmax.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <random>
#include <string>
#include <vector>

void ragged_softmax_baseline(
    const float*, float*, const std::uint32_t*, std::size_t);

namespace {

struct Workload {
    std::vector<float> input;
    std::vector<std::uint32_t> offsets;
};

Workload make_workload(
    std::size_t rows,
    std::uint32_t min_length,
    std::uint32_t max_length,
    std::uint32_t seed) {
    std::mt19937 rng(seed);
    std::uniform_int_distribution<std::uint32_t> lengths(min_length, max_length);
    std::normal_distribution<float> values(0.0f, 4.0f);

    Workload result;
    result.offsets.reserve(rows + 1);
    result.offsets.push_back(0);
    for (std::size_t row = 0; row < rows; ++row) {
        const auto length = lengths(rng);
        for (std::uint32_t i = 0; i < length; ++i) {
            result.input.push_back(values(rng));
        }
        result.offsets.push_back(static_cast<std::uint32_t>(result.input.size()));
    }
    return result;
}

std::vector<float> reference(const Workload& workload) {
    std::vector<float> output(workload.input.size());
    const std::size_t rows = workload.offsets.size() - 1;
    for (std::size_t row = 0; row < rows; ++row) {
        const std::size_t begin = workload.offsets[row];
        const std::size_t end = workload.offsets[row + 1];
        long double maximum = -INFINITY;
        for (std::size_t i = begin; i < end; ++i) {
            maximum = std::max(maximum, static_cast<long double>(workload.input[i]));
        }
        long double denominator = 0.0L;
        for (std::size_t i = begin; i < end; ++i) {
            denominator += std::exp(static_cast<long double>(workload.input[i]) - maximum);
        }
        for (std::size_t i = begin; i < end; ++i) {
            output[i] = static_cast<float>(
                std::exp(static_cast<long double>(workload.input[i]) - maximum) / denominator);
        }
    }
    return output;
}

bool check() {
    for (std::uint32_t seed : {7U, 19U, 71U}) {
        Workload workload = make_workload(257, 1, 513, seed);
        if (workload.input.size() > 10) {
            workload.input[3] = 80.0f;
            workload.input[9] = -80.0f;
        }
        const auto expected = reference(workload);
        std::vector<float> actual(workload.input.size(), 0.0f);
        ragged_softmax(
            workload.input.data(),
            actual.data(),
            workload.offsets.data(),
            workload.offsets.size() - 1);
        for (std::size_t i = 0; i < actual.size(); ++i) {
            const float tolerance = 2.0e-5f + 2.0e-5f * std::abs(expected[i]);
            if (!std::isfinite(actual[i]) || std::abs(actual[i] - expected[i]) > tolerance) {
                std::cerr << "mismatch at seed=" << seed << " index=" << i
                          << " expected=" << expected[i] << " actual=" << actual[i] << '\n';
                return false;
            }
        }
    }
    return true;
}

using Kernel = void (*)(const float*, float*, const std::uint32_t*, std::size_t);

double measure(Kernel kernel, const Workload& workload, int iterations) {
    std::vector<float> output(workload.input.size());
    const std::size_t rows = workload.offsets.size() - 1;
    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < iterations; ++i) {
        kernel(workload.input.data(), output.data(), workload.offsets.data(), rows);
    }
    const auto finish = std::chrono::steady_clock::now();
    volatile float sink = output[output.size() / 2];
    (void)sink;
    return std::chrono::duration<double>(finish - start).count();
}

double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    return values[values.size() / 2];
}

void bench() {
    const Workload workload = make_workload(4096, 31, 257, 2026);
    ragged_softmax(
        workload.input.data(),
        std::vector<float>(workload.input.size()).data(),
        workload.offsets.data(),
        workload.offsets.size() - 1);

    std::vector<double> ratios;
    for (int repetition = 0; repetition < 7; ++repetition) {
        double candidate = 0.0;
        double baseline = 0.0;
        if (repetition % 2 == 0) {
            baseline = measure(ragged_softmax_baseline, workload, 8);
            candidate = measure(ragged_softmax, workload, 8);
        } else {
            candidate = measure(ragged_softmax, workload, 8);
            baseline = measure(ragged_softmax_baseline, workload, 8);
        }
        ratios.push_back(baseline / candidate);
    }
    std::cout << std::fixed << std::setprecision(4)
              << "public median speedup: " << median(ratios) << "x\n";
}

}  // namespace

int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "check";
    if (mode == "check") {
        if (!check()) {
            return EXIT_FAILURE;
        }
        std::cout << "public correctness: PASS\n";
        return EXIT_SUCCESS;
    }
    if (mode == "bench") {
        if (!check()) {
            return EXIT_FAILURE;
        }
        bench();
        return EXIT_SUCCESS;
    }
    std::cerr << "usage: public_bench [check|bench]\n";
    return EXIT_FAILURE;
}
