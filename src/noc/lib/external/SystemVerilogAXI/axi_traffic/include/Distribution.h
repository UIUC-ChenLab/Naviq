#ifndef DISTRIBUTION_H
#define DISTRIBUTION_H

#include <random>
#include <memory>
#include <cstdint>
#include <cassert>

// Enumeration of supported distribution types
enum class DistributionType {
    UNIFORM,    // Uniform integer distribution
    BINOMIAL,   // Binomial distribution
    FIXED,      // Fixed value (always returns the same value)
    INCREMENT   // Incrementing distribution (cycles from min to max)
};

// Abstract base class for random distributions
// Provides a polymorphic interface for sampling random values
// All distributions share a common RNG via shared_ptr
template<typename T>
class Distribution {
public:
    // Constructor that takes a shared_ptr to the RNG
    explicit Distribution(std::shared_ptr<std::mt19937> rng)
        : rng_(std::move(rng)) {}
    
    virtual ~Distribution() = default;
    
    // Sample a random value from the distribution
    // Uses the shared RNG stored in the distribution
    virtual T sample() = 0;
    
    // Get the distribution type
    virtual DistributionType getType() const = 0;
    
    // Get the shared RNG (for external use if needed)
    std::shared_ptr<std::mt19937> getRng() const { return rng_; }
    
protected:
    std::shared_ptr<std::mt19937> rng_;
};

// Uniform integer distribution wrapper
template<typename T>
class UniformDistribution : public Distribution<T> {
public:
    UniformDistribution(std::shared_ptr<std::mt19937> rng, T min, T max)
        : Distribution<T>(std::move(rng)), dist_(min, max) {}
    
    T sample() override {
        return dist_(*this->rng_);
    }
    
    DistributionType getType() const override {
        return DistributionType::UNIFORM;
    }
    
    void reconfigure(T min, T max) {
        dist_ = std::uniform_int_distribution<T>(min, max);
    }
    
private:
    std::uniform_int_distribution<T> dist_;
};

// Binomial distribution wrapper
// Handles offset internally so sample() returns values in range [min, max]
template<typename T>
class BinomialDistribution : public Distribution<T> {
public:
    BinomialDistribution(std::shared_ptr<std::mt19937> rng, T min, T max, double probability)
        : Distribution<T>(std::move(rng)), min_(min), trials_(max - min), probability_(probability),
          dist_(trials_, probability) {}
    
    T sample() override {
        // Binomial gives us [0, trials], add min to get [min, max]
        return min_ + dist_(*this->rng_);
    }
    
    DistributionType getType() const override {
        return DistributionType::BINOMIAL;
    }
    
    void reconfigure(T min, T max, double probability) {
        min_ = min;
        trials_ = max - min;
        probability_ = probability;
        dist_ = std::binomial_distribution<T>(trials_, probability);
    }
    
    T getMin() const { return min_; }
    T getTrials() const { return trials_; }
    double getProbability() const { return probability_; }
    
private:
    T min_;
    T trials_;
    double probability_;
    std::binomial_distribution<T> dist_;
};

// Fixed distribution wrapper
// Always returns the same fixed value (ignores RNG)
template<typename T>
class FixedDistribution : public Distribution<T> {
public:
    FixedDistribution(std::shared_ptr<std::mt19937> rng, T value)
        : Distribution<T>(std::move(rng)), value_(value) {}
    
    T sample() override {
        // Ignore RNG, always return the fixed value
        return value_;
    }
    
    DistributionType getType() const override {
        return DistributionType::FIXED;
    }
    
    void reconfigure(T value) {
        value_ = value;
    }
    
    T getValue() const { return value_; }
    
private:
    T value_;
};

// Increment distribution wrapper
// Increments from min to max (inclusive) and then resets back to min
// The incrementing happens on every sample() call
// Can increment by a specified value (useful for AXI addresses which increment by data width)
template<typename T>
class IncrementDistribution : public Distribution<T> {
public:
    IncrementDistribution(std::shared_ptr<std::mt19937> rng, T min, T max, T increment = 1)
        : Distribution<T>(std::move(rng)), min_(min), max_(max), increment_(increment), current_(min) {}
    
    T sample() override {
        // Return current value, then increment using the default increment value
        return sample(increment_);
    }
    
    // Non-virtual overload that allows specifying an increment value for this sample
    // This is useful for AXI addresses which may increment by data width (e.g., 4, 8, 16 bytes)
    T sample(T increment) {
        // Return current value, then increment by the specified amount
        T result = current_;
        
        // Increment by the specified amount and wrap around if would exceed max
        if (current_ + increment > max_) {
            current_ = min_;
        } else {
            current_ += increment;
        }
        
        return result;
    }
    
    DistributionType getType() const override {
        return DistributionType::INCREMENT;
    }
    
    void reconfigure(T min, T max, T increment = 1) {
        min_ = min;
        max_ = max;
        increment_ = increment;
        current_ = min;
    }
    
    void setIncrement(T increment) {
        increment_ = increment;
    }
    
    T getMin() const { return min_; }
    T getMax() const { return max_; }
    T getIncrement() const { return increment_; }
    T getCurrent() const { return current_; }
    
private:
    T min_;
    T max_;
    T increment_;
    T current_;
};

// Factory function to create a distribution based on type
// Both uniform and binomial distributions return values in range [min, max]
// The offset handling is done internally by each distribution type
// For FIXED distribution, min is used as the fixed value (max and probability are ignored)
// For INCREMENT distribution, values cycle from min to max (inclusive), probability is ignored
// All distributions share the same RNG via shared_ptr
template<typename T>
std::unique_ptr<Distribution<T>> createDistribution(
    std::shared_ptr<std::mt19937> rng,
    DistributionType type,
    T min,
    T max,
    double probability = 0.5
) {
    switch (type) {
        case DistributionType::UNIFORM:
            return std::make_unique<UniformDistribution<T>>(rng, min, max);
            
        case DistributionType::BINOMIAL:
            return std::make_unique<BinomialDistribution<T>>(rng, min, max, probability);
            
        case DistributionType::FIXED:
            return std::make_unique<FixedDistribution<T>>(rng, min);
            
        case DistributionType::INCREMENT:
            return std::make_unique<IncrementDistribution<T>>(rng, min, max);
            
        default:
            // Fallback to uniform
            return std::make_unique<UniformDistribution<T>>(rng, min, max);
    }
}

// Convenience overload to create a fixed distribution
template<typename T>
std::unique_ptr<Distribution<T>> createDistribution(
    std::shared_ptr<std::mt19937> rng,
    DistributionType type,
    T fixed_value
) {
    assert(type == DistributionType::FIXED && 
           "createDistribution overload requires DistributionType::FIXED");
    if (type != DistributionType::FIXED) {
        // Fallback: return nullptr or throw, but assert should catch this in debug
        return nullptr;
    }
    return std::make_unique<FixedDistribution<T>>(rng, fixed_value);
}

// Convenience overload to create an increment distribution with a specified increment value
// This is useful for AXI addresses which increment by data width (e.g., 4, 8, 16 bytes)
template<typename T>
std::unique_ptr<Distribution<T>> createDistribution(
    std::shared_ptr<std::mt19937> rng,
    DistributionType type,
    T min,
    T max,
    T increment
) {
    assert(type == DistributionType::INCREMENT && 
           "createDistribution overload requires DistributionType::INCREMENT");
    if (type != DistributionType::INCREMENT) {
        // Fallback: return nullptr or throw, but assert should catch this in debug
        return nullptr;
    }
    return std::make_unique<IncrementDistribution<T>>(rng, min, max, increment);
}

#endif // DISTRIBUTION_H

