#ifndef __AXIMM_RTL_SLAVE_NODE_HH__
#define __AXIMM_RTL_SLAVE_NODE_HH__

#include <cstdint>
#include <memory>
#include <string>
#include <type_traits>
#include <utility>

#include "base/logging.hh"
#include "noc/endpoints/NocNode.hh"
#include "noc/endpoints/rtl/include/axi_rtl_bridge.h"
#include "noc/lib/axi/AXITypes.hh"

namespace gem5::noc
{

/**
 * Bridge one NoC AXI-MM destination endpoint to a Verilated AXI-MM slave.
 *
 * AXIMMHandler and mmNocSlaveUnit retain ownership of CDC, packetization, and
 * response ordering.  This class only translates their existing endpoint
 * State objects to the cycle-accurate Verilator port binding.
 */
template <typename DutT, typename ParamsT, typename WrapperTraits>
class AximmRtlSlaveNode : public NocNode
{
  private:
    using DutRoot = std::remove_pointer_t<decltype(std::declval<DutT>().rootp)>;
    using Binding = AxiPortBinding<DutRoot>;

  public:
    explicit AximmRtlSlaveNode(const ParamsT &p, const char *nodeName)
        : NocNode(p),
          m_nodeName(nodeName),
          m_dataWidthBits(p.data_width),
          m_resetCountdown(p.reset_cycles),
          m_dut(std::make_unique<DutT>()),
          m_binding(m_dut->rootp, typename WrapperTraits::AxiTraits{})
    {
        panic_if(m_dataWidthBits == 0 || m_dataWidthBits > 512 ||
                     (m_dataWidthBits % 8) != 0,
                 "%s requires an AXI-MM data width in [8, 512] bits",
                 m_nodeName);
        maxPorts = 1;
        clearOutput();
        WrapperTraits::clock(*m_dut) = 0;
        WrapperTraits::resetn(*m_dut) = 0;
        driveIdle();
        m_dut->eval();
    }

    bool
    done() override
    {
        // Destination nodes must not end the simulation early.  The traffic
        // source only reports done after its B/R responses are consumed.
        return m_resetComplete;
    }

    bool
    tick(int clockDomain) override
    {
        if (!clockDomains.empty() && clockDomain != clockDomains.front()) {
            return false;
        }

        if (m_resetCountdown > 0) {
            --m_resetCountdown;
            WrapperTraits::resetn(*m_dut) = 0;
            driveIdle();
            rawTick();
            clearOutput();
            if (m_resetCountdown == 0) {
                m_resetComplete = true;
            }
            return true;
        }

        WrapperTraits::resetn(*m_dut) = 1;
        driveInput();
        rawTick();
        captureOutput();
        return true;
    }

    void
    update(int portID, State *inputNocInterfaceState) override
    {
        if (portID != 0) {
            panic("%s::update invalid port %d", m_nodeName, portID);
        }
        auto *state = dynamic_cast<aximmMasterState *>(inputNocInterfaceState);
        if (!state) {
            panic("%s::update expected aximmMasterState", m_nodeName);
        }
        m_input = *state;
    }

    State *
    getCurrentState(int portID) override
    {
        if (portID != 0) {
            panic("%s::getCurrentState invalid port %d", m_nodeName, portID);
        }
        return &m_output;
    }

    int
    assignPort(const std::string &endpointName) override
    {
        if (!m_portAssigned && !portEndpointNames.empty() &&
            endpointName == portEndpointNames.front()) {
            m_portAssigned = true;
            return 0;
        }
        panic("%s::assignPort invalid endpoint '%s'", m_nodeName,
              endpointName.c_str());
    }

  private:
    static uint8_t
    encodeBurst(BurstType burst)
    {
        return static_cast<uint8_t>(burst);
    }

    static AximmResp
    decodeResp(uint8_t response)
    {
        return static_cast<AximmResp>(response & 0x3u);
    }

    static void
    copyAddressToView(const aximmRWAddr &input, bool isWrite, AxiNodeView &view)
    {
        if (isWrite) {
            view.awaddr = input.addr;
            view.awlen = input.len;
            view.awsize = input.size;
            view.awburst = encodeBurst(input.burst);
            view.awprot = input.prot;
            view.awcache = input.cache;
            view.awid = input.id;
            view.awlock = input.lock;
            view.awqos = input.qos;
            view.awregion = input.region;
            view.awuser = input.user;
            view.awvalid = input.valid;
        } else {
            view.araddr = input.addr;
            view.arlen = input.len;
            view.arsize = input.size;
            view.arburst = encodeBurst(input.burst);
            view.arprot = input.prot;
            view.arcache = input.cache;
            view.arid = input.id;
            view.arlock = input.lock;
            view.arqos = input.qos;
            view.arregion = input.region;
            view.aruser = input.user;
            view.arvalid = input.valid;
        }
    }

    void
    driveIdle()
    {
        m_binding.view() = AxiNodeView{};
        m_binding.pack_to_dut(typename WrapperTraits::AxiTraits{});
    }

    void
    driveInput()
    {
        AxiNodeView &view = m_binding.view();
        view = AxiNodeView{};
        copyAddressToView(m_input.aw, true, view);
        copyAddressToView(m_input.ar, false, view);
        for (size_t byte = 0; byte < m_dataWidthBits / 8; ++byte) {
            const size_t word = byte / 4;
            const size_t shift = (byte % 4) * 8;
            view.wdata[word] |=
                static_cast<uint32_t>(m_input.w.data[byte]) << shift;
        }
        view.wstrb = m_input.w.wstrb;
        view.wuser[0] = m_input.w.user;
        view.wid = m_input.w.id;
        view.wlast = m_input.w.last;
        view.wvalid = m_input.w.valid;
        view.bready = m_input.bReady;
        view.rready = m_input.rReady;
        m_binding.pack_to_dut(typename WrapperTraits::AxiTraits{});
    }

    void
    rawTick()
    {
        WrapperTraits::clock(*m_dut) = 0;
        m_dut->eval();
        WrapperTraits::clock(*m_dut) = 1;
        m_dut->eval();
    }

    void
    clearOutput()
    {
        m_output = aximmSlaveState{};
        m_output.awReady = false;
        m_output.wReady = false;
        m_output.arReady = false;
        m_output.b.valid = false;
        m_output.r.valid = false;
    }

    void
    captureOutput()
    {
        m_binding.unpack_from_dut(typename WrapperTraits::AxiTraits{});
        const AxiNodeView &view = m_binding.view();
        m_output.awReady = view.awready;
        m_output.wReady = view.wready;
        m_output.arReady = view.arready;

        m_output.b = {};
        m_output.b.id = view.bid;
        m_output.b.resp = decodeResp(view.bresp);
        m_output.b.user = static_cast<uint8_t>(view.buser);
        m_output.b.valid = view.bvalid;

        m_output.r = {};
        m_output.r.cmd = AximmCommand::READ;
        m_output.r.id = view.rid;
        m_output.r.resp = decodeResp(view.rresp);
        m_output.r.user = static_cast<uint8_t>(view.ruser[0]);
        m_output.r.last = view.rlast;
        m_output.r.valid = view.rvalid;
        for (size_t byte = 0; byte < m_dataWidthBits / 8; ++byte) {
            const size_t word = byte / 4;
            const size_t shift = (byte % 4) * 8;
            m_output.r.data[byte] = static_cast<uint8_t>(
                (view.rdata[word] >> shift) & 0xffu);
        }
    }

    const char *m_nodeName;
    const uint32_t m_dataWidthBits;
    uint32_t m_resetCountdown;
    bool m_resetComplete = false;
    bool m_portAssigned = false;
    aximmMasterState m_input;
    aximmSlaveState m_output;
    std::unique_ptr<DutT> m_dut;
    Binding m_binding;
};

} // namespace gem5::noc

#endif // __AXIMM_RTL_SLAVE_NODE_HH__
