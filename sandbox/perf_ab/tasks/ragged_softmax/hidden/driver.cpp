#include "ragged_softmax.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef __linux__
#include <sched.h>
#endif

#ifdef _OPENMP
#include <omp.h>
#endif

void epires_hidden_ragged_softmax_baseline(
    const float*, float*, const std::uint32_t*, std::size_t);

namespace {

using Kernel = void (*)(const float*, float*, const std::uint32_t*, std::size_t);
using Clock = std::chrono::steady_clock;

constexpr float kCanary = -1234567.0f;
constexpr std::size_t kGuard = 16;

struct Workload {
    std::string id;
    std::vector<float> input;
    std::vector<std::uint32_t> offsets;
};

struct CorrectnessResult {
    bool passed = true;
    int cases_total = 0;
    int cases_passed = 0;
    double max_abs_error = 0.0;
    double max_rel_error = 0.0;
    std::string failure;
};

struct TimingResult {
    std::string id;
    std::size_t rows = 0;
    std::size_t elements = 0;
    int iterations = 0;
    std::vector<double> baseline_samples;
    std::vector<double> candidate_samples;
    std::vector<double> speedup_samples;
    double baseline_median = 0.0;
    double candidate_median = 0.0;
    double speedup = 0.0;
};

Workload make_uniform_workload(
    const std::string& id,
    std::size_t rows,
    std::uint32_t min_length,
    std::uint32_t max_length,
    std::uint32_t seed,
    float standard_deviation = 4.0f) {
    std::mt19937 rng(seed);
    std::uniform_int_distribution<std::uint32_t> lengths(min_length, max_length);
    std::normal_distribution<float> values(0.0f, standard_deviation);

    Workload result;
    result.id = id;
    result.offsets.reserve(rows + 1);
    result.offsets.push_back(0);
    for (std::size_t row = 0; row < rows; ++row) {
        const std::uint32_t length = lengths(rng);
        for (std::uint32_t column = 0; column < length; ++column) {
            float value = values(rng);
            // Sparse, deterministic outliers exercise numerical stability
            // without disclosing the private seeds in the public benchmark.
            if (((row * 131U + column * 17U + seed) % 4093U) == 0U) {
                value = ((row + column) & 1U) ? 70.0f : -70.0f;
            }
            result.input.push_back(value);
        }
        result.offsets.push_back(static_cast<std::uint32_t>(result.input.size()));
    }
    return result;
}

Workload make_mixed_workload(
    const std::string& id, std::size_t rows, std::uint32_t seed) {
    std::mt19937 rng(seed);
    std::normal_distribution<float> values(0.0f, 3.0f);
    Workload result;
    result.id = id;
    result.offsets.reserve(rows + 1);
    result.offsets.push_back(0);
    for (std::size_t row = 0; row < rows; ++row) {
        std::uint32_t length;
        switch (row % 8U) {
            case 0: length = 1U; break;
            case 1: length = 3U; break;
            case 2: length = 15U; break;
            case 3: length = 31U; break;
            case 4: length = 63U; break;
            case 5: length = 127U; break;
            case 6: length = 511U; break;
            default: length = 2049U; break;
        }
        for (std::uint32_t column = 0; column < length; ++column) {
            result.input.push_back(values(rng));
        }
        result.offsets.push_back(static_cast<std::uint32_t>(result.input.size()));
    }
    return result;
}

std::vector<float> reference(const Workload& workload) {
    std::vector<float> result(workload.input.size());
    const std::size_t rows = workload.offsets.size() - 1;
    for (std::size_t row = 0; row < rows; ++row) {
        const std::size_t begin = workload.offsets[row];
        const std::size_t end = workload.offsets[row + 1];
        long double maximum = -std::numeric_limits<long double>::infinity();
        for (std::size_t i = begin; i < end; ++i) {
            maximum = std::max(maximum, static_cast<long double>(workload.input[i]));
        }
        long double denominator = 0.0L;
        for (std::size_t i = begin; i < end; ++i) {
            denominator += std::exp(static_cast<long double>(workload.input[i]) - maximum);
        }
        for (std::size_t i = begin; i < end; ++i) {
            result[i] = static_cast<float>(
                std::exp(static_cast<long double>(workload.input[i]) - maximum) / denominator);
        }
    }
    return result;
}

bool check_one(
    const Workload& workload, Kernel kernel, CorrectnessResult& result) {
    const std::vector<float> expected = reference(workload);
    std::vector<float> guarded(workload.input.size() + 2 * kGuard, kCanary);
    float* actual = guarded.data() + kGuard;
    std::fill(actual, actual + workload.input.size(), std::numeric_limits<float>::quiet_NaN());
    kernel(
        workload.input.data(), actual, workload.offsets.data(),
        workload.offsets.size() - 1);

    for (std::size_t i = 0; i < kGuard; ++i) {
        if (guarded[i] != kCanary || guarded[kGuard + workload.input.size() + i] != kCanary) {
            result.passed = false;
            result.failure = workload.id + ": output guard was modified";
            return false;
        }
    }

    for (std::size_t i = 0; i < expected.size(); ++i) {
        const double abs_error = std::abs(static_cast<double>(actual[i]) - expected[i]);
        const double rel_error = abs_error / std::max(1.0e-30, std::abs(static_cast<double>(expected[i])));
        result.max_abs_error = std::max(result.max_abs_error, abs_error);
        result.max_rel_error = std::max(result.max_rel_error, rel_error);
        const double tolerance = 2.0e-5 + 2.0e-5 * std::abs(static_cast<double>(expected[i]));
        if (!std::isfinite(actual[i]) || abs_error > tolerance) {
            std::ostringstream message;
            message << workload.id << ": mismatch at index " << i
                    << " expected=" << expected[i] << " actual=" << actual[i]
                    << " tolerance=" << tolerance;
            result.passed = false;
            result.failure = message.str();
            return false;
        }
    }

    // Elementwise tolerance alone can miss a broad normalization error on long
    // rows, so independently gate every row sum.
    for (std::size_t row = 0; row + 1 < workload.offsets.size(); ++row) {
        double sum = 0.0;
        for (std::size_t i = workload.offsets[row]; i < workload.offsets[row + 1]; ++i) {
            sum += actual[i];
        }
        if (std::abs(sum - 1.0) > 8.0e-5) {
            std::ostringstream message;
            message << workload.id << ": row " << row << " sums to " << sum;
            result.passed = false;
            result.failure = message.str();
            return false;
        }
    }
    ++result.cases_passed;
    return true;
}

CorrectnessResult check_correctness() {
    CorrectnessResult result;
    std::vector<Workload> cases;
    cases.push_back(make_uniform_workload("private_singletons", 4099, 1, 1, 0x91A73U));
    cases.push_back(make_uniform_workload("private_small_jagged", 2053, 1, 113, 0xC01D5U));
    cases.push_back(make_uniform_workload("private_boundary_lengths", 521, 241, 769, 0x52F19U, 8.0f));
    cases.push_back(make_uniform_workload("private_wide_rows", 41, 4093, 16387, 0xA7719U, 12.0f));
    cases.push_back(make_mixed_workload("private_mixed_tail", 1027, 0x6D2B1U));
    cases.push_back(make_uniform_workload("private_single_long_row", 1, 65537, 65537, 0xB311FU, 20.0f));
    result.cases_total = static_cast<int>(cases.size());
    for (const Workload& workload : cases) {
        if (!check_one(workload, ragged_softmax, result)) {
            return result;
        }
    }
    return result;
}

double measure(Kernel kernel, const Workload& workload, int iterations) {
    std::vector<float> output(workload.input.size());
    const std::size_t rows = workload.offsets.size() - 1;
    const auto start = Clock::now();
    for (int iteration = 0; iteration < iterations; ++iteration) {
        kernel(workload.input.data(), output.data(), workload.offsets.data(), rows);
    }
    const auto finish = Clock::now();
    volatile float sink = output[output.size() / 2];
    (void)sink;
    return std::chrono::duration<double>(finish - start).count();
}

double median(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    const std::size_t middle = values.size() / 2;
    if ((values.size() & 1U) != 0U) {
        return values[middle];
    }
    return 0.5 * (values[middle - 1] + values[middle]);
}

int calibrate_iterations(const Workload& workload) {
    constexpr double target_seconds = 0.25;
    int probe_iterations = 1;
    double elapsed = 0.0;
    do {
        elapsed = measure(epires_hidden_ragged_softmax_baseline, workload, probe_iterations);
        if (elapsed < 0.04 && probe_iterations < 512) {
            probe_iterations *= 2;
        } else {
            break;
        }
    } while (true);
    const double seconds_per_iteration = elapsed / probe_iterations;
    const int calibrated = static_cast<int>(std::ceil(target_seconds / seconds_per_iteration));
    return std::max(1, std::min(512, calibrated));
}

TimingResult benchmark_one(const Workload& workload) {
    constexpr int samples = 7;
    TimingResult result;
    result.id = workload.id;
    result.rows = workload.offsets.size() - 1;
    result.elements = workload.input.size();
    result.iterations = calibrate_iterations(workload);

    // Touch code and buffers before recording paired samples.
    measure(epires_hidden_ragged_softmax_baseline, workload, 1);
    measure(ragged_softmax, workload, 1);
    for (int sample = 0; sample < samples; ++sample) {
        double baseline_seconds;
        double candidate_seconds;
        if ((sample & 1) == 0) {
            baseline_seconds = measure(
                epires_hidden_ragged_softmax_baseline, workload, result.iterations);
            candidate_seconds = measure(ragged_softmax, workload, result.iterations);
        } else {
            candidate_seconds = measure(ragged_softmax, workload, result.iterations);
            baseline_seconds = measure(
                epires_hidden_ragged_softmax_baseline, workload, result.iterations);
        }
        result.baseline_samples.push_back(baseline_seconds);
        result.candidate_samples.push_back(candidate_seconds);
        result.speedup_samples.push_back(baseline_seconds / candidate_seconds);
    }
    result.baseline_median = median(result.baseline_samples);
    result.candidate_median = median(result.candidate_samples);
    result.speedup = median(result.speedup_samples);
    return result;
}

std::vector<int> affinity_cpus() {
    std::vector<int> result;
#ifdef __linux__
    cpu_set_t set;
    CPU_ZERO(&set);
    if (sched_getaffinity(0, sizeof(set), &set) == 0) {
        for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
            if (CPU_ISSET(cpu, &set)) {
                result.push_back(cpu);
            }
        }
    }
#endif
    return result;
}

std::string json_escape(const std::string& value) {
    std::ostringstream output;
    for (const unsigned char character : value) {
        switch (character) {
            case '\\': output << "\\\\"; break;
            case '"': output << "\\\""; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default:
                if (character < 0x20) {
                    output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                           << static_cast<int>(character) << std::dec;
                } else {
                    output << character;
                }
        }
    }
    return output.str();
}

void print_number_array(const std::vector<double>& values) {
    std::cout << '[';
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i != 0) std::cout << ',';
        std::cout << values[i];
    }
    std::cout << ']';
}

void print_result(
    const CorrectnessResult& correctness,
    const std::vector<TimingResult>& timings,
    double elapsed_seconds) {
    std::cout << std::setprecision(12);
    std::cout << "{\"correctness\":{\"passed\":"
              << (correctness.passed ? "true" : "false")
              << ",\"cases_total\":" << correctness.cases_total
              << ",\"cases_passed\":" << correctness.cases_passed
              << ",\"max_abs_error\":" << correctness.max_abs_error
              << ",\"max_rel_error\":" << correctness.max_rel_error
              << ",\"failure\":";
    if (correctness.failure.empty()) {
        std::cout << "null";
    } else {
        std::cout << '"' << json_escape(correctness.failure) << '"';
    }
    std::cout << "},\"workloads\":[";
    for (std::size_t i = 0; i < timings.size(); ++i) {
        if (i != 0) std::cout << ',';
        const TimingResult& timing = timings[i];
        std::cout << "{\"id\":\"" << timing.id << "\",\"rows\":" << timing.rows
                  << ",\"elements\":" << timing.elements
                  << ",\"iterations\":" << timing.iterations
                  << ",\"baseline_seconds\":" << timing.baseline_median
                  << ",\"candidate_seconds\":" << timing.candidate_median
                  << ",\"speedup\":" << timing.speedup
                  << ",\"baseline_samples_seconds\":";
        print_number_array(timing.baseline_samples);
        std::cout << ",\"candidate_samples_seconds\":";
        print_number_array(timing.candidate_samples);
        std::cout << ",\"paired_speedup_samples\":";
        print_number_array(timing.speedup_samples);
        std::cout << '}';
    }
    std::cout << "],\"metadata\":{\"elapsed_seconds\":" << elapsed_seconds
              << ",\"clock\":\"steady_clock\",\"paired_interleaved\":true"
              << ",\"samples_per_workload\":7,\"target_pair_side_seconds\":0.25"
              << ",\"omp_threads\":";
#ifdef _OPENMP
    std::cout << omp_get_max_threads();
#else
    std::cout << 1;
#endif
    std::cout << ",\"affinity_cpus\":[";
    const std::vector<int> cpus = affinity_cpus();
    for (std::size_t i = 0; i < cpus.size(); ++i) {
        if (i != 0) std::cout << ',';
        std::cout << cpus[i];
    }
    std::cout << "]}}\n";
}

}  // namespace

int main() {
    const auto started = Clock::now();
#ifdef _OPENMP
    omp_set_dynamic(0);
#endif
    try {
        const CorrectnessResult correctness = check_correctness();
        std::vector<TimingResult> timings;
        if (correctness.passed) {
            std::vector<Workload> workloads;
            workloads.push_back(make_uniform_workload(
                "private_short_rows", 32771, 1, 17, 0x41A2DU));
            workloads.push_back(make_uniform_workload(
                "private_medium_rows", 4093, 47, 293, 0x8D731U));
            workloads.push_back(make_mixed_workload(
                "private_mixed_lengths", 6143, 0x13B9FU));
            workloads.push_back(make_uniform_workload(
                "private_wide_rows", 191, 2047, 8191, 0xEE251U));
            for (const Workload& workload : workloads) {
                timings.push_back(benchmark_one(workload));
            }
        }
        const double elapsed = std::chrono::duration<double>(Clock::now() - started).count();
        print_result(correctness, timings, elapsed);
        return correctness.passed ? EXIT_SUCCESS : 2;
    } catch (const std::exception& error) {
        CorrectnessResult failure;
        failure.passed = false;
        failure.failure = std::string("driver exception: ") + error.what();
        const double elapsed = std::chrono::duration<double>(Clock::now() - started).count();
        print_result(failure, {}, elapsed);
        return 3;
    }
}
