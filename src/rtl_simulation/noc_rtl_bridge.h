#ifndef NOC_RTL_BRIDGE_H
#define NOC_RTL_BRIDGE_H

#include <array>
#include <cstdint>
#include <cstring>
#include <type_traits>

#include "verilated.h"


// -------------------------
// Canonical representations
// -------------------------

static constexpr int kWords512 = 16;   // 512b / 32b = 16 words
static constexpr int kWords128 = 4;    // 128b / 32b = 4 words

struct AxisNodeView {
	alignas(64) std::array<uint32_t, kWords512> tdata{};
	uint64_t tkeep = 0;     // 512b => 64b tkeep
	uint16_t tid   = 0;
	uint16_t tdest = 0;
	bool     tlast = false;
	bool     tvalid = false;
	bool     tready = false;
};

struct AxiNodeView {
	uint64_t awaddr = 0;
	uint8_t  awlen  = 0;
	uint8_t  awsize = 0;
	uint8_t  awburst= 0;
	uint8_t  awprot = 0;
	uint8_t  awcache= 0;
	uint32_t awid   = 0;
	uint8_t  awlock = 0;
	uint8_t  awqos  = 0;
	uint8_t  awregion = 0;
	uint32_t awuser = 0;
	bool     awvalid= false;
	bool     awready= false;

	alignas(64) std::array<uint32_t, kWords512> wdata{};
	uint64_t wstrb = 0;    // 512b => 64b
	alignas(64) std::array<uint32_t, kWords128> wuser{};  // 0 or 128 bits
	uint32_t wid   = 0;
	bool     wlast = false;
	bool     wvalid= false;
	bool     wready= false;

	uint8_t  bresp = 0;
	uint32_t bid   = 0;
	uint32_t buser = 0;
	bool     bvalid= false;
	bool     bready= false;

	uint64_t araddr = 0;
	uint8_t  arlen  = 0;
	uint8_t  arsize = 0;
	uint8_t  arburst= 0;
	uint8_t  arprot = 0;
	uint8_t  arcache= 0;
	uint32_t arid   = 0;
	uint8_t  arlock = 0;
	uint8_t  arqos  = 0;
	uint8_t  arregion = 0;
	uint32_t aruser = 0;
	bool     arvalid= false;
	bool     arready= false;

	alignas(64) std::array<uint32_t, kWords512> rdata{};
	uint8_t  rresp = 0;
	uint32_t rid   = 0;
	alignas(64) std::array<uint32_t, kWords128> ruser{};  // 0 or 128 bits
	bool     rlast = false;
	bool     rvalid= false;
	bool     rready= false;
};

// --------------------------------------
// Low-level helpers: DUT <-> canonical
// --------------------------------------

template <typename T>
 constexpr inline uint32_t to_u32(const T& v) noexcept {
	return static_cast<uint32_t>(v);
}

template <typename T>
constexpr inline void from_u32(T& dst, uint32_t v) noexcept {
	dst = static_cast<T>(v);
}

template <typename T>
 constexpr inline uint64_t to_u64(const T& v) noexcept {
	return static_cast<uint64_t>(v);
}

template <typename T>
constexpr inline void from_u64(T& dst, uint64_t v) noexcept {
	dst = static_cast<T>(v);
}

// Words in a Verilator wide storage type (in 32-bit words).
template <typename T>
struct wide_words32 {
	static constexpr int value = 0;
};

template <>
struct wide_words32<IData> {
	static constexpr int value = 1;
};

template <>
struct wide_words32<SData> {
	static constexpr int value = 1;  // SData is 16-bit, but stored in 1 word
};

template <>
struct wide_words32<CData> {
	static constexpr int value = 1;  // CData is 8-bit (char), but stored in 1 word
};

template <>
struct wide_words32<QData> {
	static constexpr int value = 2;
};

template <int N>
struct wide_words32<VlWide<N>> {
	static constexpr int value = N;
};

template <typename DutWideT>
inline void unpack_dut_to_canonical_512(const DutWideT& dut,
										std::array<uint32_t, kWords512>& canonical) noexcept {
	constexpr int dw = wide_words32<DutWideT>::value;
	static_assert(dw > 0, "Unsupported DUT wide type");

	if constexpr (std::is_same_v<DutWideT, IData>) {
		canonical[0] = static_cast<uint32_t>(dut);
		for (int i = 1; i < kWords512; ++i) canonical[i] = 0;
		return;
	} else if constexpr (std::is_same_v<DutWideT, SData>) {
		// SData is 16-bit (short); sign-extend to 32-bit
		canonical[0] = static_cast<uint32_t>(dut);
		for (int i = 1; i < kWords512; ++i) canonical[i] = 0;
		return;
	} else if constexpr (std::is_same_v<DutWideT, CData>) {
		// CData is 8-bit (char); zero-extend to 32-bit
		canonical[0] = static_cast<uint32_t>(static_cast<uint8_t>(dut));
		for (int i = 1; i < kWords512; ++i) canonical[i] = 0;
		return;
	} else if constexpr (std::is_same_v<DutWideT, QData>) {
		uint64_t v = static_cast<uint64_t>(dut);
		canonical[0] = static_cast<uint32_t>(v & 0xFFFFFFFFu);
		canonical[1] = static_cast<uint32_t>(v >> 32);
		for (int i = 2; i < kWords512; ++i) canonical[i] = 0;
		return;
	} else {
		// VlWide<dw>: copy min(dw, 16) words directly into canonical
		const int copy_n = (dw < kWords512) ? dw : kWords512;
		std::memcpy(canonical.data(), &dut, size_t(copy_n) * sizeof(uint32_t));
		for (int i = copy_n; i < kWords512; ++i) canonical[i] = 0;
		return;
	}
}

template <typename DutWideT>
inline void pack_canonical_512_to_dut(DutWideT& dut,
										const std::array<uint32_t, kWords512>& canonical) noexcept {
	constexpr int dw = wide_words32<DutWideT>::value;
	static_assert(dw > 0, "Unsupported DUT wide type");

	if constexpr (std::is_same_v<DutWideT, IData>) {
		dut = static_cast<IData>(canonical[0]);
		return;
	} else if constexpr (std::is_same_v<DutWideT, SData>) {
		// SData is 16-bit (short); truncate from 32-bit (preserves sign)
		dut = static_cast<SData>(static_cast<int16_t>(canonical[0]));
		return;
	} else if constexpr (std::is_same_v<DutWideT, CData>) {
		// CData is 8-bit (char); truncate from 32-bit
		dut = static_cast<CData>(static_cast<uint8_t>(canonical[0]));
		return;
	} else if constexpr (std::is_same_v<DutWideT, QData>) {
		uint64_t v = (uint64_t(canonical[1]) << 32) | uint64_t(canonical[0]);
		dut = static_cast<QData>(v);
		return;
	} else {
		// VlWide<dw>
		if constexpr (dw <= kWords512) {
			// Truncate or exact
			std::memcpy(&dut, canonical.data(), size_t(dw) * sizeof(uint32_t));
			return;
		} else {
			// Zero-extend: copy 16 words then clear the rest
			std::memcpy(&dut, canonical.data(), kWords512 * sizeof(uint32_t));

			// Clear remaining words in DUT.
			// This relies on VlWide<dw> being a contiguous array of 32-bit words (true in practice).
			uint32_t* p = reinterpret_cast<uint32_t*>(&dut);
			std::memset(p + kWords512, 0, size_t(dw - kWords512) * sizeof(uint32_t));
			return;
		}
	}
}

// Helper functions for 128-bit wide buses (for wuser/ruser)
template <typename DutWideT>
inline void unpack_dut_to_canonical_128(const DutWideT& dut,
										std::array<uint32_t, kWords128>& canonical) noexcept {
	constexpr int dw = wide_words32<DutWideT>::value;
	static_assert(dw > 0, "Unsupported DUT wide type");

	if constexpr (std::is_same_v<DutWideT, IData>) {
		canonical[0] = static_cast<uint32_t>(dut);
		for (int i = 1; i < kWords128; ++i) canonical[i] = 0;
		return;
	} else if constexpr (std::is_same_v<DutWideT, SData>) {
		// SData is 16-bit (short); sign-extend to 32-bit
		canonical[0] = static_cast<uint32_t>(dut);
		for (int i = 1; i < kWords128; ++i) canonical[i] = 0;
		return;
	} else if constexpr (std::is_same_v<DutWideT, CData>) {
		// CData is 8-bit (char); zero-extend to 32-bit
		canonical[0] = static_cast<uint32_t>(static_cast<uint8_t>(dut));
		for (int i = 1; i < kWords128; ++i) canonical[i] = 0;
		return;
	} else if constexpr (std::is_same_v<DutWideT, QData>) {
		uint64_t v = static_cast<uint64_t>(dut);
		canonical[0] = static_cast<uint32_t>(v & 0xFFFFFFFFu);
		canonical[1] = static_cast<uint32_t>(v >> 32);
		for (int i = 2; i < kWords128; ++i) canonical[i] = 0;
		return;
	} else {
		// VlWide<dw>: copy min(dw, 4) words directly into canonical
		const int copy_n = (dw < kWords128) ? dw : kWords128;
		std::memcpy(canonical.data(), &dut, size_t(copy_n) * sizeof(uint32_t));
		for (int i = copy_n; i < kWords128; ++i) canonical[i] = 0;
		return;
	}
}

template <typename DutWideT>
inline void pack_canonical_128_to_dut(DutWideT& dut,
										const std::array<uint32_t, kWords128>& canonical) noexcept {
	constexpr int dw = wide_words32<DutWideT>::value;
	static_assert(dw > 0, "Unsupported DUT wide type");

	if constexpr (std::is_same_v<DutWideT, IData>) {
		dut = static_cast<IData>(canonical[0]);
		return;
	} else if constexpr (std::is_same_v<DutWideT, SData>) {
		// SData is 16-bit (short); truncate from 32-bit (preserves sign)
		dut = static_cast<SData>(static_cast<int16_t>(canonical[0]));
		return;
	} else if constexpr (std::is_same_v<DutWideT, CData>) {
		// CData is 8-bit (char); truncate from 32-bit
		dut = static_cast<CData>(static_cast<uint8_t>(canonical[0]));
		return;
	} else if constexpr (std::is_same_v<DutWideT, QData>) {
		uint64_t v = (uint64_t(canonical[1]) << 32) | uint64_t(canonical[0]);
		dut = static_cast<QData>(v);
		return;
	} else {
		// VlWide<dw>
		if constexpr (dw <= kWords128) {
			// Truncate or exact
			std::memcpy(&dut, canonical.data(), size_t(dw) * sizeof(uint32_t));
			return;
		} else {
			// Zero-extend: copy 4 words then clear the rest
			std::memcpy(&dut, canonical.data(), kWords128 * sizeof(uint32_t));

			// Clear remaining words in DUT.
			// This relies on VlWide<dw> being a contiguous array of 32-bit words (true in practice).
			uint32_t* p = reinterpret_cast<uint32_t*>(&dut);
			std::memset(p + kWords128, 0, size_t(dw - kWords128) * sizeof(uint32_t));
			return;
		}
	}
}


// --------------------------------------
// Port bindings (bind once, run fast)
// --------------------------------------

template <typename RootT>
class AxisPortBinding {
public:
	RootT* r;
	AxisNodeView shadow;

	template <typename Traits>
	explicit AxisPortBinding(RootT* root, Traits) : r(root) {}

	// Convenience accessors: return references to shadow for easier access
	AxisNodeView& view() noexcept { return shadow; }
	const AxisNodeView& view() const noexcept { return shadow; }

	// Provide pack/unpack through traits that expose references to signals.
	template <typename Traits>
	inline void pack_to_dut(const Traits& t) noexcept {
		// Drive tdata/tkeep/etc from shadow (inputs to DUT).
		pack_canonical_512_to_dut(t.tdata_ref(*r), shadow.tdata);

		// tkeep may not be exactly 64-bit in DUT; clamp via casts.
		from_u64(t.tkeep_ref(*r), shadow.tkeep);
		from_u32(t.tid_ref(*r),   shadow.tid);
		from_u32(t.tdest_ref(*r), shadow.tdest);

		from_u32(t.tlast_ref(*r), shadow.tlast ? 1u : 0u);
		from_u32(t.tvalid_ref(*r), shadow.tvalid ? 1u : 0u);
		// tready is output from DUT in typical AXIS master; do not drive unless your role requires it.
	}

	template <typename Traits>
	inline void unpack_from_dut(const Traits& t) noexcept {
		// Sample tready/valid/etc from DUT (outputs).
		unpack_dut_to_canonical_512(t.tdata_ref(*r), shadow.tdata);

		shadow.tkeep  = to_u64(t.tkeep_ref(*r));
		shadow.tid    = static_cast<uint16_t>(to_u32(t.tid_ref(*r)));
		shadow.tdest  = static_cast<uint16_t>(to_u32(t.tdest_ref(*r)));
		shadow.tlast  = (to_u32(t.tlast_ref(*r))  != 0);
		shadow.tvalid = (to_u32(t.tvalid_ref(*r)) != 0);
		shadow.tready = (to_u32(t.tready_ref(*r)) != 0);
	}
};



template <typename RootT>
class AxiPortBinding {
public:
	RootT* r;
	AxiNodeView shadow;

	template <typename Traits>
	explicit AxiPortBinding(RootT* root, Traits) : r(root) {}

	// Convenience accessors: return references to shadow for easier access
	AxiNodeView& view() noexcept { return shadow; }
	const AxiNodeView& view() const noexcept { return shadow; }

	// Provide pack/unpack through traits that expose references to signals.
	template <typename Traits>
	inline void pack_to_dut(const Traits& t) noexcept {
		// AW
		from_u64(t.awaddr_ref(*r), shadow.awaddr);
		from_u32(t.awlen_ref(*r),  shadow.awlen);
		from_u32(t.awsize_ref(*r), shadow.awsize);
		from_u32(t.awburst_ref(*r), shadow.awburst);
		from_u32(t.awprot_ref(*r), shadow.awprot);
		from_u32(t.awcache_ref(*r), shadow.awcache);
		from_u32(t.awid_ref(*r),   shadow.awid);
		from_u32(t.awlock_ref(*r), shadow.awlock);
		from_u32(t.awqos_ref(*r), shadow.awqos);
		from_u32(t.awregion_ref(*r), shadow.awregion);
		from_u32(t.awuser_ref(*r), shadow.awuser);
		from_u32(t.awvalid_ref(*r), shadow.awvalid ? 1u : 0u);
		// awready sampled

		// W
		pack_canonical_512_to_dut(t.wdata_ref(*r), shadow.wdata);
		from_u64(t.wstrb_ref(*r), shadow.wstrb);
		pack_canonical_128_to_dut(t.wuser_ref(*r), shadow.wuser);
		from_u32(t.wid_ref(*r),   shadow.wid);
		from_u32(t.wlast_ref(*r), shadow.wlast ? 1u : 0u);
		from_u32(t.wvalid_ref(*r), shadow.wvalid ? 1u : 0u);
		// wready sampled

		// B (bready drives if you are the master)
		from_u32(t.bready_ref(*r), shadow.bready ? 1u : 0u);

		// AR
		from_u64(t.araddr_ref(*r), shadow.araddr);
		from_u32(t.arlen_ref(*r),  shadow.arlen);
		from_u32(t.arsize_ref(*r), shadow.arsize);
		from_u32(t.arburst_ref(*r), shadow.arburst);
		from_u32(t.arprot_ref(*r), shadow.arprot);
		from_u32(t.arcache_ref(*r), shadow.arcache);
		from_u32(t.arid_ref(*r),   shadow.arid);
		from_u32(t.arlock_ref(*r), shadow.arlock);
		from_u32(t.arqos_ref(*r), shadow.arqos);
		from_u32(t.arregion_ref(*r), shadow.arregion);
		from_u32(t.aruser_ref(*r), shadow.aruser);
		from_u32(t.arvalid_ref(*r), shadow.arvalid ? 1u : 0u);
		// arready sampled

		// R (rready drives if you are the master)
		from_u32(t.rready_ref(*r), shadow.rready ? 1u : 0u);
	}

	template <typename Traits>
	inline void unpack_from_dut(const Traits& t) noexcept {
		// AW (only unpack ready - other signals are driven by master)
		shadow.awready = (to_u32(t.awready_ref(*r)) != 0);

		// W
		shadow.wready  = (to_u32(t.wready_ref(*r))  != 0);

		// B
		shadow.bresp   = static_cast<uint8_t>(to_u32(t.bresp_ref(*r)));
		shadow.bid     = to_u32(t.bid_ref(*r));
		shadow.buser   = to_u32(t.buser_ref(*r));
		shadow.bvalid  = (to_u32(t.bvalid_ref(*r)) != 0);

		// AR (only unpack ready - other signals are driven by master)
		shadow.arready = (to_u32(t.arready_ref(*r)) != 0);

		// R
		unpack_dut_to_canonical_512(t.rdata_ref(*r), shadow.rdata);
		shadow.rresp   = static_cast<uint8_t>(to_u32(t.rresp_ref(*r)));
		shadow.rid     = to_u32(t.rid_ref(*r));
		unpack_dut_to_canonical_128(t.ruser_ref(*r), shadow.ruser);
		shadow.rlast   = (to_u32(t.rlast_ref(*r)) != 0);
		shadow.rvalid  = (to_u32(t.rvalid_ref(*r)) != 0);
	}
};

#endif // NOC_RTL_BRIDGE_H