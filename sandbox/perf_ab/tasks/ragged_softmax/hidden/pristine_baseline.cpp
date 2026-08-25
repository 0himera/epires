#include "ragged_softmax.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

// This file is compiled from the evaluator directory, never from the submitted
// worktree.  Keep the implementation deliberately identical to the task's
// initial kernel: the score is relative to the code the agent was asked to
// improve, not to a synthetic or cached timing.
void epires_hidden_ragged_softmax_baseline(
    const float* input,
    float* output,
    const std::uint32_t* offsets,
    std::size_t rows) {
    for (std::size_t row = 0; row < rows; ++row) {
        const std::size_t begin = offsets[row];
        const std::size_t end = offsets[row + 1];

        float maximum = -std::numeric_limits<float>::infinity();
        for (std::size_t i = begin; i < end; ++i) {
            maximum = std::max(maximum, input[i]);
        }

        std::vector<double> exponentials(end - begin);
        double denominator = 0.0;
        for (std::size_t i = begin; i < end; ++i) {
            const double value = std::exp(static_cast<double>(input[i] - maximum));
            exponentials[i - begin] = value;
            denominator += value;
        }

        for (std::size_t i = begin; i < end; ++i) {
            output[i] = static_cast<float>(exponentials[i - begin] / denominator);
        }
    }
}
