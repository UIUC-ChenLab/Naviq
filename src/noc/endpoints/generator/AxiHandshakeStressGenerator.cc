#include "noc/endpoints/generator/AxiHandshakeStressGenerator.hh"

#include "noc/lib/external/SystemVerilogAXI/axi_traffic/AxiTrafficGenerator/AxiTrafficGenerator.h"
#include "noc/lib/external/SystemVerilogAXI/axi_traffic/include/AxiInterface.h"

#include <algorithm>
#include <cstring>

namespace gem5
{
namespace noc
{

namespace
{

AxiRespType
mapResp(AximmResp response)
{
    switch (response) {
      case AximmResp::OKAY:
        return AxiRespType::OKAY;
      case AximmResp::EXOKAY:
        return AxiRespType::EXOKAY;
      case AximmResp::SLVERR:
        return AxiRespType::SLVERR;
      case AximmResp::DECERR:
        return AxiRespType::DECERR;
      default:
        return AxiRespType::OKAY;
    }
}

} // anonymous namespace

AxiHandshakeStressGenerator::AxiHandshakeStressGenerator(const Params &p)
    : AxiRandomTrafficGenerator(p),
      awValidPercent(std::min<uint8_t>(p.aw_valid_percent, 100)),
      wValidPercent(std::min<uint8_t>(p.w_valid_percent, 100)),
      arValidPercent(std::min<uint8_t>(p.ar_valid_percent, 100)),
      bReadyPercent(std::min<uint8_t>(p.b_ready_percent, 100)),
      rReadyPercent(std::min<uint8_t>(p.r_ready_percent, 100)),
      rng(p.fault_seed ? p.fault_seed : std::random_device{}())
{
    if (auto *state = dynamic_cast<aximmMasterState *>(currentState.get())) {
        applyHandshakeGates(*state);
    }
}

bool
AxiHandshakeStressGenerator::percentAllows(uint8_t percent)
{
    if (percent >= 100)
        return true;
    if (percent == 0)
        return false;
    return percentDist(rng) < static_cast<int>(percent);
}

void
AxiHandshakeStressGenerator::applyHandshakeGates(aximmMasterState &state)
{
    if (state.aw.valid && !percentAllows(awValidPercent))
        state.aw.valid = false;
    if (state.w.valid && !percentAllows(wValidPercent))
        state.w.valid = false;
    if (state.ar.valid && !percentAllows(arValidPercent))
        state.ar.valid = false;

    state.bReady = percentAllows(bReadyPercent);
    state.rReady = percentAllows(rReadyPercent);
}

bool
AxiHandshakeStressGenerator::tick(int clockDomain)
{
    if (clockDomain != clockDomains[0])
        return false;

    auto *next = dynamic_cast<aximmMasterState *>(nextState.get());
    auto *nocState = dynamic_cast<aximmSlaveState *>(nocInterfaceState.get());
    auto *visible = dynamic_cast<aximmMasterState *>(currentState.get());
    auto interface = std::get<AXIInterface>(signals);

    const bool awReady = nocState ? nocState->awReady : true;
    const bool wReady = nocState ? nocState->wReady : true;
    const bool arReady = nocState ? nocState->arReady : true;
    const bool rawAwValid = interface->getAwChannel().getAwValid();
    const bool rawWValid = interface->getWChannel().getWValid();
    const bool rawArValid = interface->getArChannel().getArValid();

    const bool visibleAwValid = visible ? visible->aw.valid : rawAwValid;
    const bool visibleWValid = visible ? visible->w.valid : rawWValid;
    const bool visibleArValid = visible ? visible->ar.valid : rawArValid;

    // A hidden VALID must not handshake with the wrapped generator.
    interface->getAwChannel().setAwReady(
        awReady && (!rawAwValid || visibleAwValid));
    interface->getWChannel().setWReady(
        wReady && (!rawWValid || visibleWValid));
    interface->getArChannel().setArReady(
        arReady && (!rawArValid || visibleArValid));

    const aximmWResp &b = nocState ? nocState->b : aximmWResp{};
    interface->getBChannel().setBValid(b.valid);
    if (b.valid) {
        interface->getBChannel().setBId(b.id);
        interface->getBChannel().setBResp(mapResp(b.resp));
    }

    const aximmRWData &r = nocState ? nocState->r : aximmRWData{};
    interface->getRChannel().setRValid(r.valid);
    if (r.valid) {
        interface->getRChannel().setRLast(r.last);
        interface->getRChannel().setRId(r.id);
        interface->getRChannel().setRResp(mapResp(r.resp));
        auto &rdata = interface->getRChannel().getRData();
        const size_t copyBytes = std::min(rdata.size(), r.data.size());
        if (copyBytes) {
            std::memcpy(rdata.data(), r.data.data(), copyBytes);
        }
        if (copyBytes < rdata.size()) {
            std::memset(rdata.data() + copyBytes, 0, rdata.size() - copyBytes);
        }
    } else {
        interface->getRChannel().setRLast(false);
    }

    interface->getBChannel().setBReady(visible ? visible->bReady : true);
    interface->getRChannel().setRReady(visible ? visible->rReady : true);

    std::get<AxiTrafficGenerator>(trafficGenerator).updateResponses(false);
    std::get<AxiTrafficGenerator>(trafficGenerator).generateNextCycle();

    copyAxiValuesFromChannel(*next);
    applyHandshakeGates(*next);
    currentState = next->clone();
    return true;
}

} // namespace noc
} // namespace gem5
