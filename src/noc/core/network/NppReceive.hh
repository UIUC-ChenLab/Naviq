#ifndef __NOC_CORE_NETWORK_NPP_RECEIVE_HH__
#define __NOC_CORE_NETWORK_NPP_RECEIVE_HH__

#include <algorithm>
#include <cstddef>

namespace gem5::noc::garnet
{

/** Fields needed to validate one packet at the front of a receive VC. */
struct NppReceiveFlit
{
    int packetId;
    int source;
    int vc;
    int index;
    int count;
    bool head;
    bool tail;
};

enum class NppReceiveStatus { Incomplete, Complete, Invalid, InsufficientWindow };

struct NppReceiveCheck
{
    NppReceiveStatus status;
    const char *reason;
};

/**
 * Check only the first NPP, without popping flits or returning credits.
 * A following packet may already be queued after its predecessor's tail.
 * This is an eligibility check for a shared drain, not a VC ownership lock:
 * the router must still hold each output VC to its source through the tail.
 */
template <class Queue, class Describe>
NppReceiveCheck
checkNppReceivePrefix(const Queue &queue, int maxPacketFlits,
                     int receiveWindow, Describe describe)
{
    if (queue.empty()) {
        return {NppReceiveStatus::Incomplete, "empty receive VC"};
    }
    const auto first = describe(queue.front());
    if (first.count < 1 || first.count > maxPacketFlits) {
        return {NppReceiveStatus::Invalid, "invalid packet length"};
    }
    if (!first.head || first.index != 0) {
        return {NppReceiveStatus::Invalid, "packet does not start with head 0"};
    }
    if (first.count > receiveWindow) {
        return {NppReceiveStatus::InsufficientWindow,
                "packet exceeds receive credit/storage window"};
    }
    const size_t available = std::min(queue.size(), size_t(first.count));
    for (size_t index = 0; index < available; ++index) {
        const auto flit = describe(queue[index]);
        if (flit.packetId != first.packetId || flit.source != first.source ||
            flit.vc != first.vc) {
            return {NppReceiveStatus::Invalid,
                    "packet/source/VC changed before tail"};
        }
        if (flit.index != int(index) || flit.count != first.count) {
            return {NppReceiveStatus::Invalid,
                    "noncontiguous flit index or inconsistent length"};
        }
        if (flit.head != (index == 0) ||
            flit.tail != (index + 1 == size_t(first.count))) {
            return {NppReceiveStatus::Invalid,
                    "head/tail does not match packet boundary"};
        }
    }
    return available == size_t(first.count) ?
        NppReceiveCheck{NppReceiveStatus::Complete, "complete packet"} :
        NppReceiveCheck{NppReceiveStatus::Incomplete, "waiting for packet tail"};
}

} // namespace gem5::noc::garnet

#endif // __NOC_CORE_NETWORK_NPP_RECEIVE_HH__
