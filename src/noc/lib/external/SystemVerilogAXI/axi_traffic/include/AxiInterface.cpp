#include "AxiInterface.h"

// AxiAwChannel implementation
AxiAwChannel::AxiAwChannel(int awaddr_width, int awid_width, int awuser_width_bytes) : 
    awaddr_(awaddr_width, 0), 
    awlen_(8, 0), 
    awsize_(3, 0), 
    awburst_(2, 0), 
    awprot_(3, 0), 
    awcache_(4, 0), 
    awid_(awid_width, 0), 
    awlock_(2, 0), 
    awqos_(4, 0), 
    awregion_(4, 0),
    awuser_width_bytes_(awuser_width_bytes),
    awvalid_(false), 
    awready_(false)
{
    // Create default buffer and DataView for awuser (DataView holds the shared_ptr)
    if (awuser_width_bytes > 0) {
        auto buffer = std::make_shared<std::vector<uint8_t>>(awuser_width_bytes, 0);
        awuser_ = DataView(buffer, awuser_width_bytes, 0);
    } else {
        awuser_ = DataView();  // Empty DataView
    }
}

void AxiAwChannel::setAwAddr(uint64_t addr) {
    awaddr_ = addr;
}

void AxiAwChannel::setAwLen(uint8_t len) {
    awlen_ = static_cast<uint64_t>(len);
}

void AxiAwChannel::setAwSize(uint8_t size) {
    awsize_ = static_cast<uint64_t>(size);
}

void AxiAwChannel::setAwBurst(uint8_t burst) {
    awburst_ = static_cast<uint64_t>(burst);
}

void AxiAwChannel::setAwBurst(AxiBurstType burst) {
    awburst_ = static_cast<uint64_t>(static_cast<uint8_t>(burst));
}

void AxiAwChannel::setAwProt(uint8_t prot) {
    awprot_ = static_cast<uint64_t>(prot);
}

void AxiAwChannel::setAwProt(AxiProtType prot) {
    awprot_ = static_cast<uint64_t>(static_cast<uint8_t>(prot));
}

void AxiAwChannel::setAwCache(uint8_t cache) {
    awcache_ = static_cast<uint64_t>(cache);
}

void AxiAwChannel::setAwCache(AxiCacheType cache) {
    awcache_ = static_cast<uint64_t>(static_cast<uint8_t>(cache));
}

void AxiAwChannel::setAwId(uint64_t id) {
    awid_ = id;
}

void AxiAwChannel::setAwLock(uint8_t lock) {
    awlock_ = static_cast<uint64_t>(lock);
}

void AxiAwChannel::setAwLock(AxiLockType lock) {
    awlock_ = static_cast<uint64_t>(static_cast<uint8_t>(lock));
}

AxiBurstType AxiAwChannel::getAwBurstEnum() const {
    return static_cast<AxiBurstType>(awburst_.u8());
}

AxiProtType AxiAwChannel::getAwProtEnum() const {
    return static_cast<AxiProtType>(awprot_.u8());
}

AxiCacheType AxiAwChannel::getAwCacheEnum() const {
    return static_cast<AxiCacheType>(awcache_.u8());
}

AxiLockType AxiAwChannel::getAwLockEnum() const {
    return static_cast<AxiLockType>(awlock_.u8());
}

void AxiAwChannel::setAwQos(uint8_t qos) {
    awqos_ = static_cast<uint64_t>(qos);
}

void AxiAwChannel::setAwRegion(uint8_t region) {
    awregion_ = static_cast<uint64_t>(region);
}

void AxiAwChannel::setAwValid(bool valid) {
    awvalid_ = valid;
}

void AxiAwChannel::setAwReady(bool ready) {
    awready_ = ready;
}

void AxiAwChannel::setAwUser(const DataView& user) {
    awuser_ = user;
}

void AxiAwChannel::clear() {
    awaddr_ = 0ULL;
    awlen_ = 0ULL;
    awsize_ = 0ULL;
    awburst_ = 0ULL;
    awprot_ = 0ULL;
    awcache_ = 0ULL;
    awid_ = 0ULL;
    awlock_ = 0ULL;
    awqos_ = 0ULL;
    awregion_ = 0ULL;
    awvalid_ = false;
    awready_ = false;
}

// AxiWChannel implementation
AxiWChannel::AxiWChannel(size_t wdata_width_bytes, size_t wid_width, size_t wuser_width_bytes) :
    wdata_width_bytes_(wdata_width_bytes),
    wid_(wid_width, 0),
    wuser_width_bytes_(wuser_width_bytes),
    // One strobe bit per WDATA byte (AXI WSTRB width == DATA_WIDTH/8).
    wstrb_(std::vector<UBit>(wdata_width_bytes, UBit(1, 0))),
    wlast_(false), 
    wvalid_(false),
    wready_(false)
{
    // Create default buffers and DataViews for wdata, wstrb, and wuser (DataViews hold the shared_ptrs)
    if (wdata_width_bytes > 0) {
        auto wdata_buffer = std::make_shared<std::vector<uint8_t>>(wdata_width_bytes, 0);
        wdata_ = DataView(wdata_buffer, wdata_width_bytes, 0);
    } else {
        wdata_ = DataView();
    }
    
    // Create buffer for wuser
    if (wuser_width_bytes > 0) {
        auto wuser_buffer = std::make_shared<std::vector<uint8_t>>(wuser_width_bytes, 0);
        wuser_ = DataView(wuser_buffer, wuser_width_bytes, 0);
    } else {
        wuser_ = DataView();
    }
}

void AxiWChannel::setWId(uint64_t id) {
    wid_ = id;
}

void AxiWChannel::setWLast(bool last) {
    wlast_ = last;
}

void AxiWChannel::setWValid(bool valid) {
    wvalid_ = valid;
}

void AxiWChannel::setWReady(bool ready) {
    wready_ = ready;
}

void AxiWChannel::setWData(const DataView& data) {
    wdata_ = data;
	if (wdata_.size() != wdata_width_bytes_) {
		throw std::runtime_error("wdata_ size does not match wdata_width_");
	}
}

void AxiWChannel::setWStrb(const std::vector<UBit>& strb) {
    if (strb.size() != wdata_width_bytes_) {
        throw std::runtime_error(
                "wstrb size does not match wdata width (expected one strobe bit "
                "per data byte)");
    }
    wstrb_ = strb;
}

void AxiWChannel::setWUser(const DataView& user) {
    wuser_ = user;
	if (wuser_.size() != wuser_width_bytes_) {
		throw std::runtime_error("wuser_ size does not match wuser_width_bytes_");
	}
}

void AxiWChannel::clear() {
    wid_ = 0ULL;
    wlast_ = false;
    wvalid_ = false;
    wready_ = false;
    for (auto& s : wstrb_) {
        s = 0;
    }
}

// AxiBChannel implementation
AxiBChannel::AxiBChannel(int bid_width, int b_user_bytes) : 
    bid_(bid_width, 0), 
    bresp_(2, 0),
    buser_width_bytes_(b_user_bytes),
    bvalid_(false),
    bready_(false)
{
    // Create default buffer and DataView for buser (DataView holds the shared_ptr)
    if (b_user_bytes > 0) {
        auto buffer = std::make_shared<std::vector<uint8_t>>(b_user_bytes, 0);
        buser_ = DataView(buffer, b_user_bytes, 0);
    } else {
        buser_ = DataView();  // Empty DataView
    }
}

void AxiBChannel::setBId(uint64_t id) {
    bid_ = id;
}

void AxiBChannel::setBResp(uint8_t resp) {
    bresp_ = static_cast<uint64_t>(resp);
}

void AxiBChannel::setBResp(AxiRespType resp) {
    bresp_ = static_cast<uint64_t>(static_cast<uint8_t>(resp));
}

AxiRespType AxiBChannel::getBRespEnum() const {
    return static_cast<AxiRespType>(bresp_.u8());
}

void AxiBChannel::setBValid(bool valid) {
    bvalid_ = valid;
}

void AxiBChannel::setBReady(bool ready) {
    bready_ = ready;
}

void AxiBChannel::setBUser(const DataView& user) {
    buser_ = user;
	if (buser_.size() != buser_width_bytes_) {
		throw std::runtime_error("buser_ size does not match buser_width_bytes_");
	}
}

void AxiBChannel::clear() {
    bid_ = 0ULL;
    bresp_ = 0ULL;
    bvalid_ = false;
    bready_ = false;
}

// AxiArChannel implementation
AxiArChannel::AxiArChannel(int araddr_width, int arid_width, int ar_user_bytes) : 
    araddr_(araddr_width, 0), 
    arlen_(8, 0), 
    arsize_(3, 0), 
    arburst_(2, 0), 
    arprot_(3, 0),
    arcache_(4, 0), 
    arid_(arid_width, 0), 
    arlock_(2, 0), 
    arqos_(4, 0), 
    arregion_(4, 0),
    aruser_width_bytes_(ar_user_bytes),
    arvalid_(false), 
    arready_(false)
{
    // Create default buffer and DataView for aruser (DataView holds the shared_ptr)
    if (ar_user_bytes > 0) {
        auto buffer = std::make_shared<std::vector<uint8_t>>(ar_user_bytes, 0);
        aruser_ = DataView(buffer, ar_user_bytes, 0);
    } else {
        aruser_ = DataView();  // Empty DataView
    }
}

void AxiArChannel::setArAddr(uint64_t addr) {
    araddr_ = addr;
}

void AxiArChannel::setArLen(uint8_t len) {
    arlen_ = static_cast<uint64_t>(len);
}

void AxiArChannel::setArSize(uint8_t size) {
    arsize_ = static_cast<uint64_t>(size);
}

void AxiArChannel::setArBurst(uint8_t burst) {
    arburst_ = static_cast<uint64_t>(burst);
}

void AxiArChannel::setArBurst(AxiBurstType burst) {
    arburst_ = static_cast<uint64_t>(static_cast<uint8_t>(burst));
}

void AxiArChannel::setArProt(uint8_t prot) {
    arprot_ = static_cast<uint64_t>(prot);
}

void AxiArChannel::setArProt(AxiProtType prot) {
    arprot_ = static_cast<uint64_t>(static_cast<uint8_t>(prot));
}

void AxiArChannel::setArCache(uint8_t cache) {
    arcache_ = static_cast<uint64_t>(cache);
}

void AxiArChannel::setArCache(AxiCacheType cache) {
    arcache_ = static_cast<uint64_t>(static_cast<uint8_t>(cache));
}

void AxiArChannel::setArId(uint64_t id) {
    arid_ = id;
}

void AxiArChannel::setArLock(uint8_t lock) {
    arlock_ = static_cast<uint64_t>(lock);
}

void AxiArChannel::setArLock(AxiLockType lock) {
    arlock_ = static_cast<uint64_t>(static_cast<uint8_t>(lock));
}

AxiBurstType AxiArChannel::getArBurstEnum() const {
    return static_cast<AxiBurstType>(arburst_.u8());
}

AxiProtType AxiArChannel::getArProtEnum() const {
    return static_cast<AxiProtType>(arprot_.u8());
}

AxiCacheType AxiArChannel::getArCacheEnum() const {
    return static_cast<AxiCacheType>(arcache_.u8());
}

AxiLockType AxiArChannel::getArLockEnum() const {
    return static_cast<AxiLockType>(arlock_.u8());
}

void AxiArChannel::setArQos(uint8_t qos) {
    arqos_ = static_cast<uint64_t>(qos);
}

void AxiArChannel::setArRegion(uint8_t region) {
    arregion_ = static_cast<uint64_t>(region);
}

void AxiArChannel::setArValid(bool valid) {
    arvalid_ = valid;
}

void AxiArChannel::setArReady(bool ready) {
    arready_ = ready;
}

void AxiArChannel::setArUser(const DataView& user) {
    aruser_ = user;
	if (aruser_.size() != aruser_width_bytes_) {
		throw std::runtime_error("aruser_ size does not match aruser_width_bytes_");
	}
}

void AxiArChannel::clear() {
    araddr_ = 0ULL;
    arlen_ = 0ULL;
    arsize_ = 0ULL;
    arburst_ = 0ULL;
    arprot_ = 0ULL;
    arcache_ = 0ULL;
    arid_ = 0ULL;
    arlock_ = 0ULL;
    arqos_ = 0ULL;
    arregion_ = 0ULL;
    arvalid_ = false;
    arready_ = false;
}

// AxiRChannel implementation
AxiRChannel::AxiRChannel(size_t rdata_width_bytes, size_t rid_width, size_t ruser_width_bytes) : 
    rdata_width_bytes_(rdata_width_bytes),
    rid_(rid_width, 0), 
    rresp_(2, 0),
    ruser_width_bytes_(ruser_width_bytes),
    rlast_(false), 
    rvalid_(false),
    rready_(false)
{
    // Create default buffers and DataViews for rdata and ruser (DataViews hold the shared_ptrs)
    if (rdata_width_bytes > 0) {
        auto rdata_buffer = std::make_shared<std::vector<uint8_t>>(rdata_width_bytes, 0);
        rdata_ = DataView(rdata_buffer, rdata_width_bytes, 0);
    } else {
        rdata_ = DataView();
    }
    
    // Create buffer for ruser
    if (ruser_width_bytes > 0) {
        auto ruser_buffer = std::make_shared<std::vector<uint8_t>>(ruser_width_bytes, 0);
        ruser_ = DataView(ruser_buffer, ruser_width_bytes, 0);
    } else {
        ruser_ = DataView();
    }
}

void AxiRChannel::setRResp(uint8_t resp) {
    rresp_ = static_cast<uint64_t>(resp);
}

void AxiRChannel::setRResp(AxiRespType resp) {
    rresp_ = static_cast<uint64_t>(static_cast<uint8_t>(resp));
}

AxiRespType AxiRChannel::getRRespEnum() const {
    return static_cast<AxiRespType>(rresp_.u8());
}

void AxiRChannel::setRLast(bool last) {
    rlast_ = last;
}

void AxiRChannel::setRValid(bool valid) {
    rvalid_ = valid;
}

void AxiRChannel::setRReady(bool ready) {
    rready_ = ready;
}

void AxiRChannel::setRId(uint64_t id) {
    rid_ = id;
}

void AxiRChannel::setRData(const DataView& data) {
    rdata_ = data;
	if (rdata_.size() != rdata_width_bytes_) {
		throw std::runtime_error("rdata_ size does not match rdata_width_bytes_");
	}
}

void AxiRChannel::setRUser(const DataView& user) {
    ruser_ = user;
	if (ruser_.size() != ruser_width_bytes_) {
		throw std::runtime_error("ruser_ size does not match ruser_width_bytes_");
	}
}

void AxiRChannel::clear() {
    rresp_ = 0ULL;
    rid_ = 0ULL;
    rlast_ = false;
    rvalid_ = false;
    rready_ = false;
}

// AxiInterface implementation
AxiInterface::AxiInterface(
    size_t addr_width,
    size_t data_width,
    size_t id_width,
    size_t awuser_width,
    size_t wuser_width,
    size_t buser_width,
    size_t aruser_width,
    size_t ruser_width
) : aw_channel_(addr_width, id_width, awuser_width / 8),
    w_channel_(data_width / 8, id_width, wuser_width / 8),
    b_channel_(id_width, buser_width / 8),
    ar_channel_(addr_width, id_width, aruser_width / 8),
    r_channel_(data_width / 8, id_width, ruser_width / 8)
{
}

void AxiInterface::clear() {
    aw_channel_.clear();
    w_channel_.clear();
    b_channel_.clear();
    ar_channel_.clear();
    r_channel_.clear();
}

