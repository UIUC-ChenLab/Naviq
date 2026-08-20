#ifndef __NocStreamMsg_HH__
#define __NocStreamMsg_HH__

#include <iostream>
#include <memory>

#include "mem/ruby/slicc_interface/RubySlicc_Util.hh"

#include "mem/ruby/protocol/MemoryRequestType.hh"
#include "mem/ruby/protocol/MachineID.hh"
#include "mem/ruby/protocol/MachineID.hh"
#include "mem/ruby/protocol/DataBlock.hh"
#include "mem/ruby/protocol/MessageSizeType.hh"
#include "mem/ruby/protocol/PrefetchBit.hh"
#include "noc/lib/network/NocMessage.hh"
#include "noc/lib/axi/AXITypes.hh"
namespace gem5
{

namespace noc
{

class NocSystem;


class NocStreamMsg :  public NocMessage
{

    public:
    enum class NocStreamMsgMode { BUFFER, NETWORK };

    // NETWORK-mode constructor: accepts stream data payload only
    NocStreamMsg(Tick curTime, NocSystem* ns, std::unique_ptr<Payload> pload)
        : NocMessage(curTime, ns),
          m_pload(pload ? std::move(*pload) : Payload{}),
          m_end_beat_idx(0),
          m_current_beat_idx(0),
          m_mode(NocStreamMsgMode::NETWORK)
    {
        m_MessageSize = gem5::noc::AxiMsgSizeType::W;
        setNocSystem(ns);
    }

    // BUFFER-mode constructor: accepts buffer payload only
    NocStreamMsg(Tick curTime, NocSystem* ns, std::unique_ptr<MessagePayload> payload)
        : NocMessage(curTime, ns),
          m_payload(payload ? std::move(*payload) : MessagePayload{}),
          m_end_beat_idx(0),
          m_current_beat_idx(0),
          m_mode(NocStreamMsgMode::BUFFER)
    {
        m_MessageSize = gem5::noc::AxiMsgSizeType::W;
        setNocSystem(ns);
    }

    //keep copy of og constructor for use in AbstractController.cc
    NocStreamMsg(Tick curTime, int blockSize, NocSystem* ns) : NocMessage(curTime, ns)
    {
        setNocSystem(ns);
        m_MessageSize = gem5::noc::AxiMsgSizeType::W;
        // default value of MessageSizeType
    }

    NocStreamMsg(const NocStreamMsg&) = default;
    NocStreamMsg
    &operator=(const NocStreamMsg&) = default;

    MsgPtr
    clone() const
    {
         return std::shared_ptr<NocMessage>(new NocStreamMsg(*this));
    }
    void setNocSystem(NocSystem *noc_system)
    {
        m_noc_system = noc_system;
    }
    NocSystem*
    getNocSystem()
    {
        return m_noc_system;
    }
    const gem5::noc::AxiMsgSizeType&
    getMessageSize() const
    {
        return m_MessageSize;
    }
    gem5::noc::AxiMsgSizeType&
    getMessageSize()
    {
        return m_MessageSize;
    }
    // void
    // setMessageSize(const gem5::noc::AxiMsgSizeType& local_MessageSize)
    // {
    //     m_MessageSize = local_MessageSize;
    // }

    void print(std::ostream& out) const;
    // for ruby, these destination functions done in protocol (build/NULL/mem/ruby/protocol/MI_example for ex)
    // but do here instead
    void
    setDestination(const NocNetDest& local_Destination)
    {
        m_Destination = local_Destination;
    }
    NocNetDest&
    getDestination()
    {
        return m_Destination;
    }

    // Satisfy NocMessage pure-virtuals for non-AXIMM messages.
    void setPayload(MessagePayload payload) override {
        if (m_mode != NocStreamMsgMode::BUFFER) {
            panic("NocStreamMsg::setPayload only valid in BUFFER mode");
        }
        m_payload = std::move(payload);
    }
    MessagePayload getPayload() const override {
        // if (m_mode != NocStreamMsgMode::BUFFER) {
        //     panic("NocStreamMsg::getPayload only valid in BUFFER mode");
        // }
        return m_payload;
    }

    Payload getData() const {
        // if (m_mode != NocStreamMsgMode::NETWORK) {
        //     panic("NocStreamMsg::getData only valid in NETWORK mode");
        // }
        return m_pload;
    }

    void
    setData(Payload payload){
        if (m_mode != NocStreamMsgMode::NETWORK) {
            panic("NocStreamMsg::setData only valid in NETWORK mode");
        }
        if(!std::holds_alternative<axisPayload>(payload))
            panic("NocStreamMsg::setData: expected axisPayload");
        m_pload = payload;
    }

    void setBeatSize(uint8_t beat_size){
        m_beat_size = beat_size;
    }
    uint8_t getBeatSize() const{
        return m_beat_size;
    }

    std::array<uint8_t, 16> getFlitData(uint8_t flit_id);

    bool containsLast();

    void setNumFlits(uint8_t num_flits)
    {
        m_num_flits = num_flits;
    }
    uint8_t getNumFlits() const
    {
        return m_num_flits;
    }


    uint8_t getBeatID() const{
        return m_axi_beat_id;
    }
    void setBeatID(uint8_t id){
        m_axi_beat_id = id;
    }
    uint8_t getEndBeatIdx() const{
        return m_end_beat_idx;
    }
    void setEndBeatIdx(uint8_t idx) { m_end_beat_idx = idx; }
    void setCurrentBeatIdx(uint8_t idx) { m_current_beat_idx = idx; }
    uint8_t getCurrentBeatIdx() const { return m_current_beat_idx; }
    uint8_t getStartBeatIdx(){
        uint8_t ret = m_current_beat_idx;
        ++m_current_beat_idx;
        return ret;
    }

    void setSourceNiID(int id){
        m_src_ni_id = id;
    }
    int getSourceNiID() const{
        return m_src_ni_id;
    }

    void setDestNiID(int id) { m_dest_ni_id = id; }
    int getDestNiID() const { return m_dest_ni_id; }

    NocStreamMsgMode getMode() const { return m_mode; }
    void setMode(NocStreamMsgMode mode) { m_mode = mode; }

    //private:
    NocNetDest m_Destination;
    gem5::noc::AxiMsgSizeType m_MessageSize;
    //  bool functionalRead(Packet* param_pkt);
    //  bool functionalRead(Packet* param_pkt, gem5::ruby::WriteMask& param_mask);
    //  bool functionalWrite(Packet* param_pkt);

    private:
        //TODO fix names or clean up how doing payload
        Payload m_pload; //<- what will actually house r/w data
        MessagePayload m_payload; // buffer-mode payload
        uint8_t m_beat_size; // beat size and burst len of the req/resp to/from slave

        NocSystem* m_noc_system;

        uint8_t m_num_flits; // number of flits used to transmit this message


        uint8_t m_axi_beat_id;
        uint8_t m_end_beat_idx;
        uint8_t m_current_beat_idx;

        int m_dest_ni_id;
        int m_src_ni_id;
        NocStreamMsgMode m_mode;
};

inline ::std::ostream&
operator<<(::std::ostream& out, const NocStreamMsg& obj)
{
    obj.print(out);
    out << ::std::flush;
    return out;
}

} // namespace noc
} // namespace gem5

#endif // __NocStreamMsg_HH__
