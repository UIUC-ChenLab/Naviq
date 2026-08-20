#ifndef __CDC_QUEUE_HH
#define __CDC_QUEUE_HH

#include "base/types.hh"
#include "mem/ruby/common/TypeDefines.hh"
#include "noc/lib/axi/AXITypes.hh"
#include "noc/lib/interface/ResponseInfo.hh"
#include "sim/serialize.hh"
#include <deque>
#include <memory>
#include <optional>
#include <string>

namespace gem5 {
namespace noc {

/**
 * Clock-domain crossing FIFO used by protocol handlers. Entries remain owned
 * by the queue until the receiving domain dequeues them; callers preserve
 * ready/valid payload stability while a front entry is stalled.
 */
class CDCQueue {
    public:
        CDCQueue(int size) : maxSize(size) {}
        virtual ~CDCQueue() = default;

        /// Labels DPRINTF(NocCDC, ...) lines; call from NocInterface::init per channel.
        void setDebugContext(gem5::ruby::NodeID ni, std::string endpoint,
                             std::string channel);
        // Take ownership of state (move). Caller must clone once if they only have a raw pointer.
        bool enqueue(std::unique_ptr<State> data, Tick enqueueTick);
        bool enqueue(std::unique_ptr<State> data, ResponseInfo responseInfo, Tick enqueueTick);
        // Return ownership of the state to the caller.
        std::unique_ptr<State> dequeue(Tick dequeueTick);
        /// True if dequeue(t) would return non-null (non-empty and CDC delay elapsed).
        bool canDequeueToNoC(Tick curTick) const;
        /// Head State if canDequeueToNoC; otherwise nullptr. Does not dequeue.
        const State* peekFrontState(Tick curTick) const;
        // Peek at head entry's ResponseInfo without dequeuing. Returns nullopt if empty or no ResponseInfo.
        std::optional<ResponseInfo> peekResponseInfo() const;
        bool isEmpty();
        bool isFull();

        void serialize(CheckpointOut &cp) const;
        void unserialize(CheckpointIn &cp);

    private:

        struct FIFOEntry {
            std::unique_ptr<State> data;
            std::optional<ResponseInfo> responseInfo;
            Tick enqueueTick;
            Tick dequeueTick;
            bool dequeueTickValid;
            bool sampled;
        };

        int maxSize;
        std::deque<FIFOEntry> fifo;

        bool dbg = false;
        gem5::ruby::NodeID dbg_ni = 0;
        std::string dbg_endpoint;
        std::string dbg_channel;
};

}}
#endif
