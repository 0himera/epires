CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -march=native -DNDEBUG -fopenmp -Iinclude -Wall -Wextra
BUILD_DIR := build
TARGET := $(BUILD_DIR)/public_bench

.PHONY: all check bench clean

all: $(TARGET)

$(TARGET): src/kernel.cpp src/baseline.cpp src/public_bench.cpp include/ragged_softmax.h
	@mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) src/kernel.cpp src/baseline.cpp src/public_bench.cpp -o $(TARGET)

check: $(TARGET)
	OMP_NUM_THREADS=4 ./$(TARGET) check

bench: $(TARGET)
	OMP_NUM_THREADS=4 ./$(TARGET) bench

clean:
	rm -rf $(BUILD_DIR)
