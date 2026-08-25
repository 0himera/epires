#pragma once

#include <cstddef>
#include <cstdint>

// Compute a numerically stable softmax independently for every row in a
// ragged, flattened matrix. Row r occupies [offsets[r], offsets[r + 1]).
// All inputs are finite and every row is non-empty. Input and output do not
// alias. The implementation must work for arbitrary row lengths.
void ragged_softmax(
    const float* input,
    float* output,
    const std::uint32_t* offsets,
    std::size_t rows);
