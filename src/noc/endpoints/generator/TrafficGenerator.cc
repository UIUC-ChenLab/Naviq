#include "noc/endpoints/generator/TrafficGenerator.hh"
#include "debug/NocHBM.hh"
#include "NsuInfo.h"

#include <sstream>

namespace gem5{

namespace noc{

namespace {

std::vector<NsuInfo>
buildAximmNsuList(const TrafficGeneratorParams& p)
{
    std::vector<NsuInfo> list;
    if (p.nsu_min_addrs.size() > 0) {
        if (p.nsu_min_addrs.size() != p.nsu_address_spaces.size())
            panic("TrafficGenerator: nsu_min_addrs and nsu_address_spaces must have the same size");
        list.reserve(p.nsu_min_addrs.size());
        for (size_t i = 0; i < p.nsu_min_addrs.size(); ++i)
            list.push_back(NsuInfo(p.nsu_min_addrs[i], p.nsu_address_spaces[i]));
    } else {
		panic("Trafficgenerator: nsu_min_addrs and nsu_address_spaces MUST BE NON-ZERO");
	}
    return list;
}

} // anonymous namespace

TrafficGenerator::~TrafficGenerator() = default;

TrafficGenerator::TrafficGenerator(const Params &p) : NocNode(p),
    protocol(p.protocol),
    mode(p.mode),
    signals(
        (p.protocol == "AXIS")
            ? std::variant<AXISInterface, AXIInterface>(AXISInterface(std::make_shared<AxisInterface>(p.data_width, p.tid_width, p.tdest_width, p.tuser_width)))
            : std::variant<AXISInterface, AXIInterface>(AXIInterface(std::make_shared<AxiInterface>(
                  /* addr width bits */ p.addr_width,
                  /* data width bits */ p.data_width,
                  /* id width bits */ p.id_width,
                  /* user widths (bytes) */ p.aw_user_width/8, p.w_user_width/8, p.b_user_width/8, p.ar_user_width/8, p.r_user_width/8)))
    ),
    trafficGenerator(
        (p.protocol == "AXIS")
            ? std::variant<AxiTrafficGenerator, AxisTrafficGenerator>(
                  std::in_place_type<AxisTrafficGenerator>,
                  std::get<AXISInterface>(signals))
            : std::variant<AxiTrafficGenerator, AxisTrafficGenerator>(
                  std::in_place_type<AxiTrafficGenerator>,
                  std::get<AXIInterface>(signals),
                  buildAximmNsuList(p),
                  true)
    )
{
    maxPorts = 1;
    if (protocol == "AXIS") {
        nextState = std::make_unique<axisMasterState>(
            p.data_width, p.tid_width, p.tdest_width
        );
        nocInterfaceState = std::make_unique<axisSlaveState>();
    } else if (protocol == "AXIMM") {
        nextState = std::make_unique<aximmMasterState>();
        nocInterfaceState = std::make_unique<aximmSlaveState>();
    } else {
        panic("Unknown protocol: %s", protocol.c_str());
    }


    // // TODO: add support for setting mode for AxiTrafficGenerator
    // if(std::get_if<AxisTrafficGenerator>(&trafficGenerator) != nullptr)
    //     std::get<AxisTrafficGenerator>(trafficGenerator)->setMode(mode);

    // Set AXIMM bandwidth limits on the generator (passed from base params, not strategy config)
    if (protocol == "AXIMM") {
        std::get<AxiTrafficGenerator>(trafficGenerator).setBandwidthLimits(
            p.max_write_bandwidth_mbps,
            p.max_read_bandwidth_mbps,
            static_cast<double>(p.clock_period_ns));
    }

    // Initialize current state with the first generated AXIS cycle
    if (protocol == "AXIS") {
        updateAxisCurrentState();
    } else if (protocol == "AXIMM") {
        updateAxiCurrentState();
    }
}

void
TrafficGenerator::copyAxisValuesFromChannel(axisMasterState& state) {
    axisData& dst = state.data;

    auto axisSignals = std::get<AXISInterface>(signals);

    // --- Copy TDATA ---
    const size_t bytes = axisSignals->getTData().size();
    if (dst.tdata.size() < bytes)
        panic("TrafficGenerator::copyAxisValuesFromChannel: TDATA size from signals is larger than the expected");

    std::memcpy(dst.tdata.data(), axisSignals->getTData().data(), bytes);

    // --- Scalar fields ---
    dst.tid    = axisSignals->getTId();
    dst.tdest = axisSignals->getTDest();
    dst.tlast = axisSignals->getTLast();
    dst.tvalid = axisSignals->getTValid();

    // --- TKEEP: vector<uint8_t> → bitmask ---
    dst.tkeep = 0;
    for (size_t i = 0; i < axisSignals->getTKeep().size(); ++i) {
        if (std::get<AXISInterface>(signals)->getTKeep()[i].u64())
            dst.tkeep |= (1ULL << i);
    }

    // --- TUSER (if used) ---
    if (axisSignals->getTUser().size() > 0) {
        dst.tuser = 0;
        const size_t userBytes = std::min<size_t>(axisSignals->getTUser().size(),
                                                  sizeof(dst.tuser));
        for (size_t i = 0; i < userBytes; ++i) {
            dst.tuser |= static_cast<uint32_t>(axisSignals->getTUser()[i]) << (8 * i);
        }
    }
}

void
TrafficGenerator::setInvalidAxisBeat(axisMasterState& state) {
    axisData& dst = state.data;
    dst.tvalid = false;
}

void
TrafficGenerator::copyAxiValuesFromChannel(aximmMasterState& state) {
	// Access AXI signals interface
	auto axiSignals = std::get<AXIInterface>(signals);

	// Helper to map AxiBurstType -> BurstType
	auto mapBurst = [](AxiBurstType b) -> BurstType {
		switch (b) {
			case AxiBurstType::FIXED: return BurstType::FIXED;
			case AxiBurstType::INCR:  return BurstType::INCR;
			case AxiBurstType::WRAP:  return BurstType::WRAP;
			default:                  return BurstType::INCR;
		}
	};

	// ---------------- AW channel -> state.aw ----------------
	const AxiAwChannel& aw = axiSignals->getAwChannel();
	state.aw.valid = aw.getAwValid();
	if (state.aw.valid) {
		state.aw.cmd   = AximmCommand::WRITE;
		state.aw.id    = static_cast<uint32_t>(aw.getAwId());
		state.aw.addr  = aw.getAwAddr();
		state.aw.len   = aw.getAwLen();
		state.aw.size  = aw.getAwSize();
		state.aw.burst = mapBurst(aw.getAwBurstEnum());
		state.aw.lock  = (aw.getAwLock() != 0);
		state.aw.cache = aw.getAwCache();
		state.aw.prot  = aw.getAwProt();
		state.aw.qos   = aw.getAwQos();
		state.aw.region= aw.getAwRegion();
		// Optional user (take first byte if present)
		state.aw.user  = aw.getAwUser().size() > 0 ? aw.getAwUser()[0] : 0;
	} else {
		state.aw.valid = false;
	}

	// ---------------- W channel -> state.w ----------------
	const AxiWChannel& w = axiSignals->getWChannel();
	state.w.valid = w.getWValid();
	if (state.w.valid) {
		state.w.cmd  = AximmCommand::WRITE;
		state.w.id   = static_cast<uint32_t>(w.getWId());
		state.w.last = w.getWLast();
		// Copy WDATA (bounded by aximmRWData buffer size)
		const size_t wdata_bytes = w.getWData().size();
		const size_t copy_bytes  = std::min(wdata_bytes, state.w.data.size());
		if (copy_bytes > 0) {
			std::memcpy(state.w.data.data(), w.getWData().data(), copy_bytes);
		}
		// Fill remaining bytes with 0 if any
		if (copy_bytes < state.w.data.size()) {
			std::memset(state.w.data.data() + copy_bytes, 0, state.w.data.size() - copy_bytes);
		}
		// Convert WSTRB bytes (one bit per byte) to 64-bit mask
		state.w.wstrb = 0ULL;
		const size_t wstrb_bytes = w.getWStrb().size();
		DPRINTF(NocTiming, "[TrafficGenerator] WSTRB conversion: size=%llu\n",
				(unsigned long long)wstrb_bytes);
		for (size_t i = 0; i < std::min<size_t>(wstrb_bytes, 64); ++i) {
			if (w.getWStrb()[i].u8() != 0) state.w.wstrb |= (1ULL << i);
		}
		DPRINTF(NocTiming, "[TrafficGenerator] WSTRB result: 0x%llx\n", (unsigned long long)state.w.wstrb);
	} else {
		state.w.valid = false;
	}

	// ---------------- AR channel -> state.ar ----------------
	const AxiArChannel& ar = axiSignals->getArChannel();
	state.ar.valid = ar.getArValid();
	if (state.ar.valid) {
		state.ar.cmd   = AximmCommand::READ;
		state.ar.id    = static_cast<uint32_t>(ar.getArId());
		state.ar.addr  = ar.getArAddr();
		state.ar.len   = ar.getArLen();
		state.ar.size  = ar.getArSize();
		state.ar.burst = mapBurst(ar.getArBurstEnum());
		state.ar.lock  = (ar.getArLock() != 0);
		state.ar.cache = ar.getArCache();
		state.ar.prot  = ar.getArProt();
		state.ar.qos   = ar.getArQos();
		state.ar.region= ar.getArRegion();
		// Optional user (take first byte if present)
		state.ar.user  = ar.getArUser().size() > 0 ? ar.getArUser()[0] : 0;
	} else {
		state.ar.valid = false;
	}

	// ---------------- Master ready signals ----------------
	state.rReady = axiSignals->getRChannel().getRReady();
	state.bReady = axiSignals->getBChannel().getBReady();
}

bool
TrafficGenerator::tick(int clockDomain) {
	if (clockDomain != clockDomains[0])
		return false;
    // TODO: fix
    // std::printf("[TrafficGenerator] tick @ %llu RW_state=%d reads_done=%d writes_done=%d "
    //     "readReq=%zu writeReq=%zu writeData=%zu\n",
    //     (unsigned long long)curTick(),
    //     RW_state,
    //     (int)reads_done, (int)writes_done,
    //     readRequests.size(), writeRequests.size(), writeData.size());


    if(protocol == "AXIS"){
        // TODO: add debugging print statements
        axisMasterState* nextStateCasted = dynamic_cast<axisMasterState*>(nextState.get()); // TODO: dynamic cast or static cast?

        bool tvalid = std::get<AXISInterface>(signals)->getTValid();
		bool tready = std::get<AXISInterface>(signals)->getTReady();
		copyAxisValuesFromChannel(*nextStateCasted);

        if (tvalid & tready) {
            DPRINTF(NocTiming,
                "[TrafficGenerator] enqueue AXIS beat: tid=%u tdest=%u tlast=%d tvalid=%d tuser=%u tkeep=0x%016llx bytes=%u\n",
                nextStateCasted->data.tid,
                nextStateCasted->data.tdest,
                (int)nextStateCasted->data.tlast,
                (int)nextStateCasted->data.tvalid,
                (unsigned)nextStateCasted->data.tuser,
                (unsigned long long)nextStateCasted->data.tkeep,
                (unsigned)nextStateCasted->data.getTotalByteSize());
        }

		std::get<AxisTrafficGenerator>(trafficGenerator).tick();
		copyAxisValuesFromChannel(*nextStateCasted);
        currentState = nextStateCasted->clone();

        return true;
    }
    else if(protocol == "AXIMM"){
		// Map NI (slave) ready signals and responses into AXI interface,
		// update the generator, then copy master channel outputs into state.
		aximmMasterState* nextStateCasted = dynamic_cast<aximmMasterState*>(nextState.get());
		aximmSlaveState* nocInterfaceStateCasted = dynamic_cast<aximmSlaveState*>(nocInterfaceState.get());
		auto axiIf = std::get<AXIInterface>(signals);

		// Helper: map AximmResp -> AxiRespType
		auto mapResp = [](AximmResp r) -> AxiRespType {
			switch (r) {
				case AximmResp::OKAY:   return AxiRespType::OKAY;
				case AximmResp::EXOKAY: return AxiRespType::EXOKAY;
				case AximmResp::SLVERR: return AxiRespType::SLVERR;
				case AximmResp::DECERR: return AxiRespType::DECERR;
				default:                return AxiRespType::OKAY;
			}
		};

		// Ready signals from NI into interface
		bool aw_ready = nocInterfaceStateCasted ? nocInterfaceStateCasted->awReady : true;
		bool w_ready  = nocInterfaceStateCasted ? nocInterfaceStateCasted->wReady  : true;
		bool ar_ready = nocInterfaceStateCasted ? nocInterfaceStateCasted->arReady : true;
		axiIf->getAwChannel().setAwReady(aw_ready);
		axiIf->getWChannel().setWReady(w_ready);
		axiIf->getArChannel().setArReady(ar_ready);

		// Responses from NI into interface
		const aximmWResp& b = nocInterfaceStateCasted ? nocInterfaceStateCasted->b : aximmWResp{};
		axiIf->getBChannel().setBValid(b.valid);
		if (b.valid) {
			axiIf->getBChannel().setBId(b.id);
			axiIf->getBChannel().setBResp(mapResp(b.resp));
		}
		axiIf->getBChannel().setBReady(true); 

		const aximmRWData& r = nocInterfaceStateCasted ? nocInterfaceStateCasted->r : aximmRWData{};
		axiIf->getRChannel().setRValid(r.valid);
		if (r.valid) {
			axiIf->getRChannel().setRLast(r.last);
			axiIf->getRChannel().setRId(r.id);
			axiIf->getRChannel().setRResp(mapResp(r.resp));
			// Copy RDATA into interface view
			auto& rdataView = axiIf->getRChannel().getRData();
			size_t copy_bytes = std::min(rdataView.size(), r.data.size());
			if (copy_bytes > 0) {
				std::memcpy(rdataView.data(), r.data.data(), copy_bytes);
			}
			if (copy_bytes < rdataView.size()) {
				std::memset(rdataView.data() + copy_bytes, 0, rdataView.size() - copy_bytes);
			}
		} else {
			axiIf->getRChannel().setRLast(false);
		}
		axiIf->getRChannel().setRReady(true);  // Master always ready to accept read responses

		// bool bValid = axiIf->getBChannel().getBValid();
		// bool bReady = axiIf->getBChannel().getBReady(); 
		// printf("DEBUG: BChannel bValid=%d bReady=%d\n", bValid, bReady);
		// Let generator process responses (B/R) then produce next outputs
		std::get<AxiTrafficGenerator>(trafficGenerator).updateResponses();
		std::get<AxiTrafficGenerator>(trafficGenerator).generateNextCycle();

		// Copy AW/W/AR from interface into next master state
		copyAxiValuesFromChannel(*nextStateCasted);

		// Gated by NocHBM: AXI request "made" when channel handshakes (valid && ready).
		auto dumpAddr = [](const aximmRWAddr& a) {
			std::ostringstream oss;
			oss << "{cmd=" << (a.cmd == AximmCommand::READ ? "READ" : "WRITE")
			    << " id=" << a.id
			    << " addr=0x" << std::hex << a.addr << std::dec
			    << " len=" << static_cast<unsigned>(a.len)
			    << " size=" << static_cast<unsigned>(a.size)
			    << " burst=" << static_cast<unsigned>(a.burst)
			    << "}";
			return oss.str();
		};
		if (nextStateCasted->aw.valid && aw_ready) {
			DPRINTF(NocHBM,
			        "[AXI_REQ_MADE][TG] tick=%llu AW %s\n",
			        (unsigned long long)curTick(),
			        dumpAddr(nextStateCasted->aw).c_str());
		}
		if (nextStateCasted->ar.valid && ar_ready) {
			DPRINTF(NocHBM,
			        "[AXI_REQ_MADE][TG] tick=%llu AR %s\n",
			        (unsigned long long)curTick(),
			        dumpAddr(nextStateCasted->ar).c_str());
		}
		if (nextStateCasted->w.valid && w_ready && nextStateCasted->w.last) {
			DPRINTF(NocHBM,
			        "[AXI_WLAST_MADE][TG] tick=%llu W id=%u wstrb=0x%llx "
			        "last=1\n",
			        (unsigned long long)curTick(),
			        nextStateCasted->w.id,
			        (unsigned long long)nextStateCasted->w.wstrb);
		}

		currentState = nextStateCasted->clone();
		return true;
    }
    return false;
}

void
TrafficGenerator::update(int portID, State* inputNocInterfaceState)
{
    if (portID != 0) {
        panic("TrafficGenerator::update invalid portID %d", portID);
    }
	if(protocol == "AXIS"){ 
		axisSlaveState* nocInterfaceStateCasted = dynamic_cast<axisSlaveState*>(inputNocInterfaceState);
		bool tready = nocInterfaceStateCasted ? nocInterfaceStateCasted->tready : true;
		auto axisSignals = std::get<AXISInterface>(signals);
		axisSignals->setTReady(tready);
		std::get<AxisTrafficGenerator>(trafficGenerator).update();
		nocInterfaceState = nocInterfaceStateCasted->clone();

	} else if(protocol == "AXIMM"){
		aximmSlaveState* nocInterfaceStateCasted = dynamic_cast<aximmSlaveState*>(inputNocInterfaceState);
		nocInterfaceState = nocInterfaceStateCasted->clone();
	}
}

State*
TrafficGenerator::getCurrentState(int portID)
{
    if (portID != 0)
        panic("TrafficGenerator::getCurrentState invalid portID %d", portID);
    return currentState.get();
}

int
TrafficGenerator::assignPort(const std::string &endpointName)
{
    if (endpointName == portEndpointNames[0] && !portAssigned) {
        portAssigned = true;
        return 0;
    }
    panic("TrafficGenerator::assignPort invalid endpointName: %s",
          endpointName.c_str());
}

::AxisTrafficGenerator*
TrafficGenerator::axisGenerator() {
    if (protocol != "AXIS")
        return nullptr;
    return &std::get<AxisTrafficGenerator>(trafficGenerator);
}

::AxiTrafficGenerator*
TrafficGenerator::axiGenerator() {
    if (protocol != "AXIMM")
        return nullptr;
    return &std::get<AxiTrafficGenerator>(trafficGenerator);
}

void
TrafficGenerator::updateAxisCurrentState() {
    if (protocol != "AXIS")
        return;
    axisMasterState* nextStateCasted = dynamic_cast<axisMasterState*>(nextState.get());
    axisSlaveState* nocInterfaceStateCasted = dynamic_cast<axisSlaveState*>(nocInterfaceState.get());
    bool tready = nocInterfaceStateCasted ? nocInterfaceStateCasted->tready : true;
    auto axisSignals = std::get<AXISInterface>(signals);
    axisSignals->setTReady(tready);
    std::get<AxisTrafficGenerator>(trafficGenerator).update();
    copyAxisValuesFromChannel(*nextStateCasted);
    currentState = nextStateCasted->clone();
}

void
TrafficGenerator::updateAxiCurrentState() {
    if (protocol != "AXIMM")
        return;
    aximmMasterState* nextStateCasted = dynamic_cast<aximmMasterState*>(nextState.get());
    aximmSlaveState* nocInterfaceStateCasted = dynamic_cast<aximmSlaveState*>(nocInterfaceState.get());
	// Map NI (slave) ready signals into AXI interface channels
	bool aw_ready = nocInterfaceStateCasted ? nocInterfaceStateCasted->awReady : true;
	bool w_ready  = nocInterfaceStateCasted ? nocInterfaceStateCasted->wReady  : true;
	bool ar_ready = nocInterfaceStateCasted ? nocInterfaceStateCasted->arReady : true;
	auto axiIf = std::get<AXIInterface>(signals);
	axiIf->getAwChannel().setAwReady(aw_ready);
	axiIf->getWChannel().setWReady(w_ready);
	axiIf->getArChannel().setArReady(ar_ready);
    std::get<AxiTrafficGenerator>(trafficGenerator).generateNextCycle();
    copyAxiValuesFromChannel(*nextStateCasted);
    currentState = nextStateCasted->clone();
}


} // end namespace noc
} //end namespace gem5
