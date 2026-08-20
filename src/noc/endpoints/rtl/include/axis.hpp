// AXI Stream testbench helpers: canonical word arrays (axi_rtl_bridge style) + Verilator harness pointers.
// Sizes and indices are in bits. tdata uses little-endian 32-bit lanes: bit b -> word b/32, lane b%32.

#pragma once

#include "axi_rtl_bridge.h"

#include <algorithm>
#include <array>
#include <bitset>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <memory>
#include <type_traits>
#include <vector>

namespace tb {

namespace axis_detail {

inline constexpr size_t bits_to_u32_words(size_t bits) { return (bits + 31u) / 32u; }

template <size_t N>
bool array_any_nonzero(const std::array<uint32_t, N>& a) noexcept {
    for (uint32_t w : a) {
        if (w != 0) return true;
    }
    return false;
}

/// Low min(64, N*32) bits as uint64 (lane0 = bits [31:0], lane1 = [63:32]).
template <size_t N>
uint64_t array_low_u64(const std::array<uint32_t, N>& a) noexcept {
    if constexpr (N == 0) return 0;
    uint64_t v = a[0];
    if constexpr (N >= 2) v |= (static_cast<uint64_t>(a[1]) << 32);
    return v;
}

template <size_t N>
bool array_any_bit_above(const std::array<uint32_t, N>& a, size_t from_bit) noexcept {
    const size_t start_word = from_bit / 32u;
    const unsigned start_off = static_cast<unsigned>(from_bit % 32u);
    if (start_word < N) {
        const uint32_t mask = ~((1u << start_off) - 1u);
        if ((a[start_word] & mask) != 0) return true;
        for (size_t w = start_word + 1; w < N; ++w) {
            if (a[w] != 0) return true;
        }
    }
    return false;
}

template <size_t N>
void pack_bitset_to_u32_words(const std::bitset<N>& bs, std::array<uint32_t, axis_detail::bits_to_u32_words(N)>& dst) noexcept {
    dst.fill(0u);
    for (size_t b = 0; b < N; ++b) {
        if (bs[b]) dst[b / 32u] |= (1u << (b % 32u));
    }
}

/// Inverse of `pack_bitset_to_u32_words` (bit-parallel u32[] layout).
template <size_t N>
std::bitset<N> bitset_from_u32_array(const std::array<uint32_t, axis_detail::bits_to_u32_words(N)>& arr) noexcept {
    static_assert(N > 0, "bitset_from_u32_array: N must be > 0");
    std::bitset<N> bs;
    for (size_t b = 0; b < N; ++b) {
        if ((arr[b / 32u] >> (b % 32u)) & 1u) bs.set(b);
    }
    return bs;
}

/// Pack logical bits [0, num_bits) to 1 in tkeep/tstrb arrays (bit-parallel keep).
template <size_t NWords>
void set_keep_strb_prefix(std::array<uint32_t, NWords>& arr, size_t num_bits, size_t cap_bits) noexcept {
    arr.fill(0u);
    const size_t n = std::min(num_bits, cap_bits);
    for (size_t b = 0; b < n; ++b) arr[b / 32u] |= (1u << (b % 32u));
}

/// Count leading 1 bits in tkeep (one bit per byte lane), up to cap_bits.
template <size_t NWords>
size_t count_tkeep_prefix_ones(const std::array<uint32_t, NWords>& tkeep, size_t cap_bits) noexcept {
    size_t c = 0;
    while (c < cap_bits) {
        const uint32_t w = tkeep[c / 32u];
        if (((w >> (c % 32u)) & 1u) == 0)
            break;
        ++c;
    }
    return c;
}

/// Byte i in canonical tdata packing (same as packet_bytes_to_axis_stream / drive_axis_beat).
template <size_t NW>
uint8_t tdata_byte_at(const std::array<uint32_t, NW>& tdata, size_t byte_index) noexcept {
    const size_t w = byte_index / 4u;
    const unsigned shift = static_cast<unsigned>((byte_index % 4u) * 8u);
    return static_cast<uint8_t>((tdata[w] >> shift) & 0xFFu);
}

/// Logical payload bit `b`: LSB-first within each byte (same mapping as the prior flat bitset).
inline bool byte_vec_bit(const std::vector<uint8_t>& v, size_t bit_idx) noexcept {
    return (static_cast<unsigned>(v[bit_idx / 8]) >> (bit_idx % 8)) & 1u;
}

inline void byte_vec_set_bit(std::vector<uint8_t>& v, size_t bit_idx, bool val) noexcept {
    const size_t bi = bit_idx / 8;
    const unsigned sh = static_cast<unsigned>(bit_idx % 8);
    if (val)
        v[bi] = static_cast<uint8_t>(v[bi] | (1u << sh));
    else
        v[bi] = static_cast<uint8_t>(v[bi] & ~(1u << sh));
}

}  // namespace axis_detail

// ---------------------------------------------------------------------------
// Generic canonical <-> DUT (same structure as pack_canonical_512_to_dut, parameterized width)
// ---------------------------------------------------------------------------

template <typename DutWideT, size_t NWords>
void pack_canonical_words_to_dut(DutWideT& dut, const std::array<uint32_t, NWords>& canonical) noexcept {
    constexpr int dw = wide_words32<DutWideT>::value;
    static_assert(dw > 0, "Unsupported DUT wide type");

    if constexpr (std::is_same_v<DutWideT, IData>) {
        dut = static_cast<IData>(canonical[0]);
        return;
    } else if constexpr (std::is_same_v<DutWideT, SData>) {
        dut = static_cast<SData>(static_cast<int16_t>(canonical[0]));
        return;
    } else if constexpr (std::is_same_v<DutWideT, CData>) {
        dut = static_cast<CData>(static_cast<uint8_t>(canonical[0]));
        return;
    } else if constexpr (std::is_same_v<DutWideT, QData>) {
        uint64_t v = uint64_t(canonical[0]);
        if (NWords >= 2) v |= (uint64_t(canonical[1]) << 32);
        dut = static_cast<QData>(v);
        return;
    } else {
        if constexpr (dw <= static_cast<int>(NWords)) {
            std::memcpy(&dut, canonical.data(), size_t(dw) * sizeof(uint32_t));
            return;
        } else {
            std::memcpy(&dut, canonical.data(), NWords * sizeof(uint32_t));
            uint32_t* p = reinterpret_cast<uint32_t*>(&dut);
            std::memset(p + NWords, 0, size_t(dw - static_cast<int>(NWords)) * sizeof(uint32_t));
            return;
        }
    }
}

template <typename DutWideT, size_t NWords>
void unpack_dut_to_canonical_words(const DutWideT& dut, std::array<uint32_t, NWords>& canonical) noexcept {
    constexpr int dw = wide_words32<DutWideT>::value;
    static_assert(dw > 0, "Unsupported DUT wide type");

    if constexpr (std::is_same_v<DutWideT, IData>) {
        canonical[0] = static_cast<uint32_t>(dut);
        for (size_t i = 1; i < NWords; ++i) canonical[i] = 0;
        return;
    } else if constexpr (std::is_same_v<DutWideT, SData>) {
        canonical[0] = static_cast<uint32_t>(dut);
        for (size_t i = 1; i < NWords; ++i) canonical[i] = 0;
        return;
    } else if constexpr (std::is_same_v<DutWideT, CData>) {
        canonical[0] = static_cast<uint32_t>(static_cast<uint8_t>(dut));
        for (size_t i = 1; i < NWords; ++i) canonical[i] = 0;
        return;
    } else if constexpr (std::is_same_v<DutWideT, QData>) {
        uint64_t v = static_cast<uint64_t>(dut);
        canonical[0] = static_cast<uint32_t>(v & 0xFFFFFFFFu);
        if (NWords >= 2) canonical[1] = static_cast<uint32_t>(v >> 32);
        for (size_t i = 2; i < NWords; ++i) canonical[i] = 0;
        return;
    } else {
        const int copy_n = (dw < static_cast<int>(NWords)) ? dw : static_cast<int>(NWords);
        std::memcpy(canonical.data(), &dut, size_t(copy_n) * sizeof(uint32_t));
        for (size_t i = static_cast<size_t>(copy_n); i < NWords; ++i) canonical[i] = 0;
        return;
    }
}

// ---------------------------------------------------------------------------
// Verilator harness (pointers) — defined before AxisInterface::apply_to_verilator.
// ---------------------------------------------------------------------------

template <size_t TDataBits, size_t TKeepBits, size_t TStrbBits, size_t TUserBits, size_t TIdBits, size_t TDestBits>
class AxisVerilatorHarness {
public:
    static constexpr size_t data_bits = TDataBits;
    static constexpr size_t keep_bits = TKeepBits;
    static constexpr size_t strb_bits = TStrbBits;
    static constexpr size_t user_bits = TUserBits;
    static constexpr size_t id_bits = TIdBits;
    static constexpr size_t dest_bits = TDestBits;

    static constexpr size_t tdata_num_u32 = axis_detail::bits_to_u32_words(TDataBits);
    static constexpr size_t tkeep_num_u32 = axis_detail::bits_to_u32_words(TKeepBits);
    static constexpr size_t tstrb_num_u32 = axis_detail::bits_to_u32_words(TStrbBits);
    static constexpr size_t tuser_num_u32 = axis_detail::bits_to_u32_words(TUserBits);

    IData* tdata = nullptr;
    IData* tkeep = nullptr;
    QData* tkeep64 = nullptr;
    IData* tstrb = nullptr;
    QData* tstrb64 = nullptr;
    QData* tuser = nullptr;
    QData* tid = nullptr;
    QData* tdest = nullptr;
    CData* tlast = nullptr;
    CData* tvalid = nullptr;
    CData* tready = nullptr;

    size_t expected_user_bits = 0;
    size_t expected_id_bits = 0;
    size_t expected_dest_bits = 0;

    AxisVerilatorHarness() = default;

    AxisVerilatorHarness(IData* tdata_ptr, QData* tkeep64_ptr, QData* tid_ptr, QData* tdest_ptr, CData* tlast_ptr,
                         CData* tvalid_ptr, CData* tready_ptr = nullptr)
        : tdata(tdata_ptr),
          tkeep64(tkeep64_ptr),
          tid(tid_ptr),
          tdest(tdest_ptr),
          tlast(tlast_ptr),
          tvalid(tvalid_ptr),
          tready(tready_ptr) {}
};

// ---------------------------------------------------------------------------
// Canonical AXI-Stream beat (software): fixed arrays like AxisNodeView, widths from template.
// ---------------------------------------------------------------------------

template <size_t TDataBits, size_t TKeepBits, size_t TStrbBits, size_t TUserBits, size_t TIdBits, size_t TDestBits>
struct AxisBeatView {
    static constexpr size_t data_words = axis_detail::bits_to_u32_words(TDataBits);
    static constexpr size_t keep_words = axis_detail::bits_to_u32_words(TKeepBits);
    static constexpr size_t strb_words = axis_detail::bits_to_u32_words(TStrbBits);
    static constexpr size_t user_words = axis_detail::bits_to_u32_words(TUserBits);
    static constexpr size_t id_words = axis_detail::bits_to_u32_words(TIdBits);
    static constexpr size_t dest_words = axis_detail::bits_to_u32_words(TDestBits);

    alignas(64) std::array<uint32_t, data_words> tdata{};
    alignas(64) std::array<uint32_t, keep_words> tkeep{};
    alignas(64) std::array<uint32_t, strb_words> tstrb{};
    alignas(64) std::array<uint32_t, user_words> tuser{};
    alignas(64) std::array<uint32_t, id_words> tid{};
    alignas(64) std::array<uint32_t, dest_words> tdest{};
    bool tlast = false;
    bool tvalid = false;
    bool tready = false;
};

template <size_t TDataBits, size_t TKeepBits, size_t TStrbBits, size_t TUserBits, size_t TIdBits, size_t TDestBits>
class AxisInterface : public AxisBeatView<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits> {
public:
    using Base = AxisBeatView<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits>;
    using Base::data_words;
    using Base::dest_words;
    using Base::id_words;
    using Base::keep_words;
    using Base::strb_words;
    using Base::user_words;

    static constexpr size_t data_bits = TDataBits;
    static constexpr size_t keep_bits = TKeepBits;
    static constexpr size_t strb_bits = TStrbBits;
    static constexpr size_t user_bits = TUserBits;
    static constexpr size_t id_bits = TIdBits;
    static constexpr size_t dest_bits = TDestBits;

    void apply_to_verilator(AxisVerilatorHarness<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits>& h)
        const {
        using H = AxisVerilatorHarness<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits>;

        if (h.expected_user_bits != 0) {
            assert(h.expected_user_bits == TUserBits && "AxisVerilatorHarness expected_user_bits must match TUserBits");
        }
        if (h.expected_id_bits != 0) {
            assert(h.expected_id_bits == TIdBits && "AxisVerilatorHarness expected_id_bits must match TIdBits");
        }
        if (h.expected_dest_bits != 0) {
            assert(h.expected_dest_bits == TDestBits && "AxisVerilatorHarness expected_dest_bits must match TDestBits");
        }

        if (axis_detail::array_any_nonzero(this->tuser)) {
            assert(h.tuser != nullptr && "tuser non-zero but AxisVerilatorHarness::tuser is null");
        }
        if (axis_detail::array_any_nonzero(this->tid)) {
            assert(h.tid != nullptr && "tid non-zero but AxisVerilatorHarness::tid is null");
        }
        if (axis_detail::array_any_nonzero(this->tdest)) {
            assert(h.tdest != nullptr && "tdest non-zero but AxisVerilatorHarness::tdest is null");
        }

        if (h.tuser && TUserBits > 64) {
            assert(!axis_detail::array_any_bit_above(this->tuser, 64) && "tuser does not fit QData*");
        }
        if (h.tid && TIdBits > 64) {
            assert(!axis_detail::array_any_bit_above(this->tid, 64) && "tid does not fit QData*");
        }
        if (h.tdest && TDestBits > 64) {
            assert(!axis_detail::array_any_bit_above(this->tdest, 64) && "tdest does not fit QData*");
        }

        if (this->tvalid) {
            assert(h.tdata != nullptr && "tvalid set but tdata is null");
            assert((h.tkeep64 != nullptr || h.tkeep != nullptr) && "tvalid set but no tkeep connection");
            assert(h.tvalid != nullptr && "tvalid set but tvalid port pointer is null");
        }
        if (this->tlast) {
            assert(h.tlast != nullptr && "tlast set but tlast port pointer is null");
        }
        if (axis_detail::array_any_nonzero(this->tstrb)) {
            assert((h.tstrb64 != nullptr || h.tstrb != nullptr) && "tstrb non-zero but no tstrb connection");
        }

        if (h.tdata) {
            std::memcpy(h.tdata, this->tdata.data(), H::tdata_num_u32 * sizeof(uint32_t));
        }
        if (h.tkeep64) {
            *h.tkeep64 = static_cast<QData>(axis_detail::array_low_u64(this->tkeep));
        } else if (h.tkeep) {
            std::memcpy(h.tkeep, this->tkeep.data(), H::tkeep_num_u32 * sizeof(uint32_t));
        }
        if (h.tstrb64) {
            *h.tstrb64 = static_cast<QData>(axis_detail::array_low_u64(this->tstrb));
        } else if (h.tstrb) {
            std::memcpy(h.tstrb, this->tstrb.data(), H::tstrb_num_u32 * sizeof(uint32_t));
        }
        if (h.tuser) {
            *h.tuser = static_cast<QData>(axis_detail::array_low_u64(this->tuser));
        }
        if (h.tid) {
            *h.tid = static_cast<QData>(axis_detail::array_low_u64(this->tid));
        }
        if (h.tdest) {
            *h.tdest = static_cast<QData>(axis_detail::array_low_u64(this->tdest));
        }
        if (h.tlast) *h.tlast = static_cast<CData>(this->tlast ? 1 : 0);
        if (h.tvalid) *h.tvalid = static_cast<CData>(this->tvalid ? 1 : 0);
        if (h.tready) *h.tready = static_cast<CData>(this->tready ? 1 : 0);
    }
};

/// Port binding: shadow (AxisInterface) <-> DUT via Traits (same idea as AxisPortBinding in axi_rtl_bridge.h).
template <typename RootT, typename Traits, size_t TDataBits, size_t TKeepBits, size_t TStrbBits, size_t TUserBits,
          size_t TIdBits, size_t TDestBits>
class AxisTbBinding {
public:
    RootT* r = nullptr;
    AxisInterface<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits> shadow;

    explicit AxisTbBinding(RootT* root) : r(root) {}

    AxisInterface<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits>& view() noexcept { return shadow; }
    const AxisInterface<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits>& view() const noexcept {
        return shadow;
    }

    /// Drive DUT inputs from shadow (master driving AXIS).
    void pack_to_dut(const Traits& t) noexcept {
        if constexpr (TDataBits > 0) pack_canonical_words_to_dut(t.tdata_ref(*r), shadow.tdata);
        if constexpr (TKeepBits > 0) from_u64(t.tkeep_ref(*r), axis_detail::array_low_u64(shadow.tkeep));
        if constexpr (TUserBits > 0) from_u64(t.tuser_ref(*r), axis_detail::array_low_u64(shadow.tuser));
        if constexpr (TIdBits > 0) from_u64(t.tid_ref(*r), axis_detail::array_low_u64(shadow.tid));
        if constexpr (TDestBits > 0) from_u64(t.tdest_ref(*r), axis_detail::array_low_u64(shadow.tdest));
        from_u32(t.tlast_ref(*r), shadow.tlast ? 1u : 0u);
        from_u32(t.tvalid_ref(*r), shadow.tvalid ? 1u : 0u);
    }

    /// Sample DUT outputs into shadow (e.g. tready).
    void unpack_from_dut(const Traits& t) noexcept {
        if constexpr (TDataBits > 0) unpack_dut_to_canonical_words(t.tdata_ref(*r), shadow.tdata);
        if constexpr (TKeepBits > 0) {
            const uint64_t kv = to_u64(t.tkeep_ref(*r));
            shadow.tkeep.fill(0);
            shadow.tkeep[0] = static_cast<uint32_t>(kv & 0xFFFFFFFFu);
            if (shadow.tkeep.size() >= 2) shadow.tkeep[1] = static_cast<uint32_t>(kv >> 32);
        }
        if constexpr (TUserBits > 0) {
            const uint64_t uv = to_u64(t.tuser_ref(*r));
            shadow.tuser.fill(0);
            shadow.tuser[0] = static_cast<uint32_t>(uv & 0xFFFFFFFFu);
            if (shadow.tuser.size() >= 2) shadow.tuser[1] = static_cast<uint32_t>(uv >> 32);
        }
        if constexpr (TIdBits > 0) {
            const uint64_t iv = to_u64(t.tid_ref(*r));
            shadow.tid.fill(0);
            shadow.tid[0] = static_cast<uint32_t>(iv & 0xFFFFFFFFu);
            if (shadow.tid.size() >= 2) shadow.tid[1] = static_cast<uint32_t>(iv >> 32);
        }
        if constexpr (TDestBits > 0) {
            const uint64_t dv = to_u64(t.tdest_ref(*r));
            shadow.tdest.fill(0);
            shadow.tdest[0] = static_cast<uint32_t>(dv & 0xFFFFFFFFu);
            if (shadow.tdest.size() >= 2) shadow.tdest[1] = static_cast<uint32_t>(dv >> 32);
        }
        shadow.tlast = (to_u32(t.tlast_ref(*r)) != 0);
        shadow.tvalid = (to_u32(t.tvalid_ref(*r)) != 0);
        shadow.tready = (to_u32(t.tready_ref(*r)) != 0);
    }
};

template <size_t TPayloadBits, size_t TUserBits, size_t TIdBits, size_t TDestBits>
class AxisMessage {
public:
    static constexpr size_t payload_bits = TPayloadBits;

    /// Wire-order payload bytes; bit `b` of the logical stream is LSB `b%8` of byte `b/8` (matches `drive_axis_beat`).
    std::shared_ptr<std::vector<uint8_t>> tdata;
    size_t sent_bits = 0;
    size_t total_bits = 0;
    std::bitset<TUserBits> tuser{};
    std::bitset<TIdBits> tid{};
    std::bitset<TDestBits> tdest{};

    explicit AxisMessage(std::shared_ptr<std::vector<uint8_t>> p, size_t total_bits_in = TPayloadBits)
        : tdata(std::move(p)), sent_bits(0), total_bits(total_bits_in) {
        assert(tdata && "AxisMessage tdata is null");
        assert(total_bits_in <= TPayloadBits && "total_bits exceeds capacity");
        assert(tdata->size() >= (total_bits_in + 7) / 8 && "tdata byte vector too small for total_bits");
    }

    size_t remaining_bits() const {
        return total_bits > sent_bits ? total_bits - sent_bits : 0;
    }

    bool exhausted() const { return sent_bits >= total_bits; }

    void reset_progress() { sent_bits = 0; }
};

template <size_t TDataBits, size_t TKeepBits, size_t TStrbBits, size_t TUserBits, size_t TIdBits, size_t TDestBits,
          size_t TPayloadBits>
bool drive_axis_beat(AxisInterface<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits>& iface,
                     AxisMessage<TPayloadBits, TUserBits, TIdBits, TDestBits>& msg, size_t beat_data_bits) {
    assert(msg.tdata && "AxisMessage tdata is null");
    const size_t rem = msg.remaining_bits();
    const size_t n = std::min({rem, beat_data_bits, TDataBits});

    if constexpr (TUserBits > 0) axis_detail::pack_bitset_to_u32_words(msg.tuser, iface.tuser);
    if constexpr (TIdBits > 0) axis_detail::pack_bitset_to_u32_words(msg.tid, iface.tid);
    if constexpr (TDestBits > 0) axis_detail::pack_bitset_to_u32_words(msg.tdest, iface.tdest);

    if (n == 0) {
        iface.tdata.fill(0u);
        iface.tkeep.fill(0u);
        if constexpr (TStrbBits > 0) iface.tstrb.fill(0u);
        iface.tvalid = false;
        iface.tlast = false;
        return false;
    }

    iface.tdata.fill(0u);
    for (size_t i = 0; i < n; ++i) {
        if (axis_detail::byte_vec_bit(*msg.tdata, msg.sent_bits + i)) iface.tdata[i / 32u] |= (1u << (i % 32u));
    }

    // tkeep/tstrb use one enable bit per *byte* (same convention as packet_bytes_to_axis_stream); n is payload bits.
    const size_t keep_prefix_bytes = (n + 7u) / 8u;
    axis_detail::set_keep_strb_prefix(iface.tkeep, keep_prefix_bytes, TKeepBits);
    if constexpr (TStrbBits > 0) {
        axis_detail::set_keep_strb_prefix(iface.tstrb, keep_prefix_bytes, TStrbBits);
    }

    iface.tvalid = true;
    msg.sent_bits += n;
    iface.tlast = (msg.sent_bits >= msg.total_bits);

    return true;
}

/// Inverse of `drive_axis_beat`: copy up to `min(remaining_bits(), beat_data_bits, TDataBits)` payload bits from
/// `iface.tdata` into `msg.tdata` at `sent_bits`. Requires `msg.total_bits` set before the first call (same as the
/// message used with `drive_axis_beat`). Updates `msg.sent_bits`. Ignores `iface.tvalid` (caller filters beats).
template <size_t TDataBits, size_t TKeepBits, size_t TStrbBits, size_t TUserBits, size_t TIdBits, size_t TDestBits,
          size_t TPayloadBits>
bool ingest_axis_beat(const AxisInterface<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits>& iface,
    AxisMessage<TPayloadBits, TUserBits, TIdBits, TDestBits>& msg, size_t beat_data_bits) {
    assert(msg.tdata && "AxisMessage tdata is null");
    assert(msg.total_bits > 0 && "ingest_axis_beat: set total_bits on AxisMessage (same as for drive_axis_beat)");
    assert(msg.sent_bits <= msg.total_bits);

    const size_t rem = msg.remaining_bits();
    const size_t n = std::min({rem, beat_data_bits, TDataBits});
    if (n == 0)
        return false;

    const size_t need_bytes = (msg.sent_bits + n + 7) / 8;
    if (msg.tdata->size() < need_bytes)
        msg.tdata->resize(need_bytes, 0);

    for (size_t i = 0; i < n; ++i) {
        const bool bit = ((iface.tdata[i / 32u] >> (i % 32u)) & 1u) != 0;
        axis_detail::byte_vec_set_bit(*msg.tdata, msg.sent_bits + i, bit);
    }
    msg.sent_bits += n;
    return true;
}

/// Concatenate wire-order bytes from AXIS beats (inverse of `packet_bytes_to_axis_stream` for the same template params).
/// Stops after the first beat with `tlast` (if any); otherwise consumes all beats.
template <size_t TDataBits, size_t TKeepBits, size_t TStrbBits, size_t TUserBits, size_t TIdBits, size_t TDestBits>
std::vector<uint8_t> axis_beats_to_bytes(const std::vector<AxisInterface<TDataBits, TKeepBits, TStrbBits, TUserBits,
    TIdBits, TDestBits>>& beats) {
    static_assert(TDataBits % 8 == 0, "TDataBits must be a multiple of 8");
    constexpr size_t bytes_per_beat = TDataBits / 8;
    std::vector<uint8_t> out;
    for (const auto& b : beats) {
        const size_t B = std::min(axis_detail::count_tkeep_prefix_ones(b.tkeep, TKeepBits), bytes_per_beat);
        out.reserve(out.size() + B);
        for (size_t i = 0; i < B; ++i)
            out.push_back(axis_detail::tdata_byte_at(b.tdata, i));
        if (b.tlast)
            break;
    }
    return out;
}

/// Build an AxisMessage payload from raw bytes (same wire order as `drive_axis_beat` / `packet_bytes_to_axis_stream`).
/// Sideband fields default to zero unless passed.
template <size_t TPayloadBits, size_t TUserBits, size_t TIdBits, size_t TDestBits>
AxisMessage<TPayloadBits, TUserBits, TIdBits, TDestBits> bytes_to_axis_message(const std::vector<uint8_t>& bytes,
    const std::bitset<TUserBits>& user = {}, const std::bitset<TIdBits>& id = {},
    const std::bitset<TDestBits>& dest = {}) {
    const size_t nbits = std::min(bytes.size() * 8u, static_cast<size_t>(TPayloadBits));
    const size_t nbytes = (nbits + 7) / 8;
    auto p = std::make_shared<std::vector<uint8_t>>();
    p->reserve(nbytes);
    for (size_t i = 0; i < nbytes && i < bytes.size(); ++i) p->push_back(bytes[i]);
    if (p->size() < nbytes)
        p->resize(nbytes, 0);
    AxisMessage<TPayloadBits, TUserBits, TIdBits, TDestBits> msg(std::move(p), nbits);
    msg.tuser = user;
    msg.tid = id;
    msg.tdest = dest;
    return msg;
}

/// Rebuild an `AxisMessage` from a sequence of beats (bytes via `axis_beats_to_bytes`, then `bytes_to_axis_message`).
/// When `use_first_beat_sideband` is true, copies tid/tuser/tdest from the first beat (bit-parallel arrays).
template <size_t TDataBits, size_t TKeepBits, size_t TStrbBits, size_t TUserBits, size_t TIdBits, size_t TDestBits,
          size_t TPayloadBits>
AxisMessage<TPayloadBits, TUserBits, TIdBits, TDestBits> axis_beats_to_axis_message(
    const std::vector<AxisInterface<TDataBits, TKeepBits, TStrbBits, TUserBits, TIdBits, TDestBits>>& beats,
    bool use_first_beat_sideband = true) {
    const std::vector<uint8_t> bytes = axis_beats_to_bytes(beats);
    std::bitset<TUserBits> u{};
    std::bitset<TIdBits> tidv{};
    std::bitset<TDestBits> dstv{};
    if (use_first_beat_sideband && !beats.empty()) {
        const auto& b0 = beats[0];
        if constexpr (TUserBits > 0) u = axis_detail::bitset_from_u32_array<TUserBits>(b0.tuser);
        if constexpr (TIdBits > 0) tidv = axis_detail::bitset_from_u32_array<TIdBits>(b0.tid);
        if constexpr (TDestBits > 0) dstv = axis_detail::bitset_from_u32_array<TDestBits>(b0.tdest);
    }
    return bytes_to_axis_message<TPayloadBits, TUserBits, TIdBits, TDestBits>(bytes, u, tidv, dstv);
}

}  // namespace tb
