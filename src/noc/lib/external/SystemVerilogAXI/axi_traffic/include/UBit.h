#ifndef UBIT_H
#define UBIT_H

#include <cstdint>
#include <stdexcept>
#include <type_traits>

class UBit {
	public:
		using storage_t = std::uint64_t;
	
		explicit UBit(std::uint32_t bits, storage_t value = 0)
			: bits_(bits), mask_(compute_mask(bits)), v_(value & mask_) {}
	
		std::uint32_t bits() const noexcept { return bits_; }
		storage_t u64() const noexcept { return v_; }
		std::uint32_t u32() const noexcept { return static_cast<std::uint32_t>(v_); }
		std::uint16_t u16() const noexcept { return static_cast<std::uint16_t>(v_); }
		std::uint8_t u8() const noexcept { return static_cast<std::uint8_t>(v_); }
	
		// Member ops (cheap, no friend)
		UBit& operator+=(storage_t x) noexcept {
			v_ = (v_ + x) & mask_;
			return *this;
		}
	
		UBit& operator-=(storage_t x) noexcept {
			v_ = (v_ - x) & mask_;
			return *this;
		}
	
		UBit& operator&=(storage_t x) noexcept {
			v_ = (v_ & x) & mask_;
			return *this;
		}
	
		// Assignment operators (modify value only, keep bit width)
		// Copy assignment (default behavior is fine since we just copy the UBit)
		UBit& operator=(const UBit& other) noexcept = default;
	
		// Assignment operator for uint64_t (handles all integer types via implicit conversion)
		UBit& operator=(std::uint64_t value) noexcept {
			v_ = value & mask_;
			return *this;
		}
	
		// ---- friend operators (minimal, controlled) ----
		friend UBit operator+(UBit a, storage_t b) noexcept {
			a += b;
			return a;
		}
	
		friend UBit operator+(storage_t a, UBit b) noexcept {
			b += a;
			return b;
		}
	
		friend bool operator==(const UBit& a, const UBit& b) noexcept {
			return a.bits_ == b.bits_ && a.v_ == b.v_;
		}
	
		friend bool operator!=(const UBit& a, const UBit& b) noexcept {
			return !(a == b);
		}
	
	private:
		static storage_t compute_mask(std::uint32_t bits) {
			if (bits == 0 || bits > 64)
				throw std::invalid_argument("UBit bits must be [1,64]");
			return bits == 64 ? ~storage_t(0) : ((storage_t(1) << bits) - 1);
		}
	
		std::uint32_t bits_;
		storage_t mask_;
		storage_t v_;
	};
	
#endif