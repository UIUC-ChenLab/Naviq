#ifndef AXI_INTERFACE_H
#define AXI_INTERFACE_H

#include <cstdint>
#include <vector>
#include <memory>
#include "DataView.h"
#include "UBit.h"
#include <string>

// Forward declarations
class AxiAwChannel;
class AxiWChannel;
class AxiBChannel;
class AxiArChannel;
class AxiRChannel;

// AXI Burst Type enumeration (AWBURST/ARBURST)
enum class AxiBurstType : uint8_t {
    FIXED = 0,  // Fixed address burst
    INCR = 1,   // Incrementing address burst
    WRAP = 2    // Wrapping address burst
    // 3 is reserved
};

// AXI Response Type enumeration (BRESP/RRESP)
enum class AxiRespType : uint8_t {
    OKAY = 0,    // Normal access success
    EXOKAY = 1,  // Exclusive access okay
    SLVERR = 2,  // Slave error
    DECERR = 3   // Decode error
};

// AXI Lock Type enumeration (AWLOCK/ARLOCK)
enum class AxiLockType : uint8_t {
    NORMAL = 0,    // Normal access
    EXCLUSIVE = 1  // Exclusive access
    // For 2-bit lock: 0=Normal, 1=Exclusive, 2=Locked, 3=Reserved
};

// AXI Protection Type enumeration (AWPROT/ARPROT)
// 3-bit field: [0]=Unprivileged/Privileged, [1]=Secure/Non-secure, [2]=Data/Instruction
enum class AxiProtType : uint8_t {
    // Data access types
    DATA_NONSECURE_UNPRIVILEGED = 0b000,
    DATA_NONSECURE_PRIVILEGED = 0b001,
    DATA_SECURE_UNPRIVILEGED = 0b010,
    DATA_SECURE_PRIVILEGED = 0b011,
    // Instruction access types
    INSTRUCTION_NONSECURE_UNPRIVILEGED = 0b100,
    INSTRUCTION_NONSECURE_PRIVILEGED = 0b101,
    INSTRUCTION_SECURE_UNPRIVILEGED = 0b110,
    INSTRUCTION_SECURE_PRIVILEGED = 0b111
};

// AXI Cache Attributes enumeration (AWCACHE/ARCACHE)
// 4-bit field: [0]=Bufferable, [1]=Cacheable, [2]=Read-allocate, [3]=Write-allocate
enum class AxiCacheType : uint8_t {
    // Non-cacheable, non-bufferable
    NON_CACHEABLE_NON_BUFFERABLE = 0b0000,
    // Non-cacheable, bufferable
    NON_CACHEABLE_BUFFERABLE = 0b0001,
    // Cacheable, no allocate
    CACHEABLE_NO_ALLOCATE = 0b0010,
    // Cacheable, read allocate
    CACHEABLE_READ_ALLOCATE = 0b0110,
    // Cacheable, write allocate
    CACHEABLE_WRITE_ALLOCATE = 0b1010,
    // Cacheable, read and write allocate
    CACHEABLE_READ_WRITE_ALLOCATE = 0b1110
};

// Class to hold AXI Write Address (AW) channel values
class AxiAwChannel {
public:
    // Constructor - creates default DataView for awuser
    AxiAwChannel(int awaddr_width, int awid_width, int aw_user_bytes = 0);
    
    // Getter methods
    uint64_t getAwAddr() const { return awaddr_.u64(); }
    size_t getAwAddrWidth() const { return awaddr_.bits(); }
    uint8_t getAwLen() const { return awlen_.u8(); }
    uint8_t getAwSize() const { return awsize_.u8(); }
    uint8_t getAwBurst() const { return awburst_.u8(); }
    uint8_t getAwProt() const { return awprot_.u8(); }
    uint8_t getAwCache() const { return awcache_.u8(); }
    uint64_t getAwId() const { return awid_.u64(); }
    size_t getAwIdWidth() const { return awid_.bits(); }
    uint8_t getAwLock() const { return awlock_.u8(); }
    uint8_t getAwQos() const { return awqos_.u8(); }
    uint8_t getAwRegion() const { return awregion_.u8(); }
    DataView& getAwUser() { return awuser_; }
    const DataView& getAwUser() const { return awuser_; }
    size_t getAwUserWidthBytes() const { return awuser_width_bytes_; }
    bool getAwValid() const { return awvalid_; }
    bool getAwReady() const { return awready_; }
    
    // Methods to set values
    void setAwAddr(uint64_t addr);
    void setAwLen(uint8_t len);
    void setAwSize(uint8_t size);
    void setAwBurst(uint8_t burst);
    void setAwBurst(AxiBurstType burst);  // Enum-based setter
    void setAwProt(uint8_t prot);
    void setAwProt(AxiProtType prot);  // Enum-based setter
    void setAwCache(uint8_t cache);
    void setAwCache(AxiCacheType cache);  // Enum-based setter
    void setAwId(uint64_t id);
    void setAwLock(uint8_t lock);
    void setAwLock(AxiLockType lock);  // Enum-based setter
    void setAwQos(uint8_t qos);
    void setAwRegion(uint8_t region);
    void setAwValid(bool valid);
    void setAwReady(bool ready);
    
    // Enum-based getters
    AxiBurstType getAwBurstEnum() const;
    AxiProtType getAwProtEnum() const;
    AxiCacheType getAwCacheEnum() const;
    AxiLockType getAwLockEnum() const;

    // Set awuser (creates a view or copies the view)
    void setAwUser(const DataView& user);
    
    // Clear all values
    void clear();

private:
    UBit awaddr_;  // Address (up to 64 bits)
    UBit awlen_;  // 8 bits
    UBit awsize_;  // 3 bits
    UBit awburst_;  // 2 bits
    UBit awprot_;  // 3 bits
    UBit awcache_;  // 4 bits
    UBit awid_;  // ID (up to 64 bits)
    UBit awlock_;  // 2 bits
    UBit awqos_;  // 4 bits
    UBit awregion_;  // 4 bits
    DataView awuser_;  // View into buffer for awuser (DataView holds the shared_ptr)
    size_t awuser_width_bytes_;         // Number of bytes needed for awuser
    bool awvalid_;
    bool awready_;
};

// Class to hold AXI Write Data (W) channel values
class AxiWChannel {
public:
    // Constructor - creates default DataViews for wdata, wstrb, wuser
    // wdata_width is in bytes
    AxiWChannel(size_t wdata_width_bytes, size_t wid_width, size_t wuser_width_bytes = 0);
    
    // Getter methods
    const DataView& getWData() const { return wdata_; }
    DataView& getWData() { return wdata_; }
    const std::vector<UBit>& getWStrb() const { return wstrb_; }
    std::vector<UBit>& getWStrb() { return wstrb_; }
    size_t getWDataWidthBytes() const { return wdata_width_bytes_; }
    uint64_t getWId() const { return wid_.u64(); }
    size_t getWIdWidth() const { return wid_.bits(); }
    bool getWLast() const { return wlast_; }
    DataView& getWUser()  { return wuser_; }
    const DataView& getWUser() const { return wuser_; }
    size_t getWUserWidthBytes() const { return wuser_width_bytes_; }
    bool getWValid() const { return wvalid_; }
    bool getWReady() const { return wready_; }
    
    // Methods to set values
    void setWId(uint64_t id);
    void setWLast(bool last);
    void setWValid(bool valid);
    void setWReady(bool ready);
    
    // Set data (creates views or copies the views)
    void setWData(const DataView& data);
    void setWStrb(const std::vector<UBit>& strb);
    void setWUser(const DataView& user);

    // Clear all values
    void clear();

private:
    DataView wdata_;  // View into buffer for wdata (DataView holds the shared_ptr)
    std::vector<UBit> wstrb_;  // vector of wstrb bits (1 for each byte)
    size_t wdata_width_bytes_; // in bytes
    UBit wid_;  // ID (up to 64 bits)
    bool wlast_;
    DataView wuser_;  // View into buffer for wuser (DataView holds the shared_ptr)
    size_t wuser_width_bytes_; // in bytes
    bool wvalid_;
    bool wready_;
};

// Class to hold AXI Write Response (B) channel values
class AxiBChannel {
public:
    // Constructor - creates default DataView for buser
    AxiBChannel(int bid_width, int buser_width_bytes = 0);
    
    // Getter methods
    uint64_t getBId() const { return bid_.u64(); }
    size_t getBIdWidth() const { return bid_.bits(); }
    uint8_t getBResp() const { return bresp_.u8(); }
    DataView& getBUser() { return buser_; }
    const DataView& getBUser() const { return buser_; }
    size_t getBUserWidthBytes() const { return buser_width_bytes_; }
    bool getBValid() const { return bvalid_; }
    bool getBReady() const { return bready_; }
    
    // Methods to set values
    void setBId(uint64_t id);
    void setBResp(uint8_t resp);
    void setBResp(AxiRespType resp);  // Enum-based setter
    void setBValid(bool valid);
    void setBReady(bool ready);
    
    // Enum-based getter
    AxiRespType getBRespEnum() const;
    
    // Set buser (creates a view or copies the view)
    void setBUser(const DataView& user);
    
    // Clear all values
    void clear();

private:
    UBit bid_;  // ID (up to 64 bits)
    UBit bresp_;  // 2 bits
    DataView buser_;  // View into buffer for buser (DataView holds the shared_ptr)
    size_t buser_width_bytes_; // in bytes
    bool bvalid_;
    bool bready_;
};

// Class to hold AXI Read Address (AR) channel values
class AxiArChannel {
public:
    // Constructor - creates default DataView for aruser
    AxiArChannel(int araddr_width, int arid_width, int aruser_width_bytes = 0);
    
    // Getter methods
    uint64_t getArAddr() const { return araddr_.u64(); }
    size_t getArAddrWidth() const { return araddr_.bits(); }
    uint8_t getArLen() const { return arlen_.u8(); }
    uint8_t getArSize() const { return arsize_.u8(); }
    uint8_t getArBurst() const { return arburst_.u8(); }
    uint8_t getArProt() const { return arprot_.u8(); }
    uint8_t getArCache() const { return arcache_.u8(); }
    uint64_t getArId() const { return arid_.u64(); }
    size_t getArIdWidth() const { return arid_.bits(); }
    uint8_t getArLock() const { return arlock_.u8(); }
    uint8_t getArQos() const { return arqos_.u8(); }
    uint8_t getArRegion() const { return arregion_.u8(); }
    DataView& getArUser() { return aruser_; }
    const DataView& getArUser() const { return aruser_; }
    size_t getArUserWidthBytes() const { return aruser_width_bytes_; }
    bool getArValid() const { return arvalid_; }
    bool getArReady() const { return arready_; }
    
    // Methods to set values
    void setArAddr(uint64_t addr);
    void setArLen(uint8_t len);
    void setArSize(uint8_t size);
    void setArBurst(uint8_t burst);
    void setArBurst(AxiBurstType burst);  // Enum-based setter
    void setArProt(uint8_t prot);
    void setArProt(AxiProtType prot);  // Enum-based setter
    void setArCache(uint8_t cache);
    void setArCache(AxiCacheType cache);  // Enum-based setter
    void setArId(uint64_t id);
    void setArLock(uint8_t lock);
    void setArLock(AxiLockType lock);  // Enum-based setter
    void setArQos(uint8_t qos);
    void setArRegion(uint8_t region);
    void setArValid(bool valid);
    void setArReady(bool ready);
    
    // Enum-based getters
    AxiBurstType getArBurstEnum() const;
    AxiProtType getArProtEnum() const;
    AxiCacheType getArCacheEnum() const;
    AxiLockType getArLockEnum() const;
    
    // Set aruser (creates a view or copies the view)
    void setArUser(const DataView& user);
    
    // Clear all values
    void clear();

private:
    UBit araddr_;  // Address (up to 64 bits)
    UBit arlen_;  // 8 bits
    UBit arsize_;  // 3 bits
    UBit arburst_;  // 2 bits
    UBit arprot_;  // 3 bits
    UBit arcache_;  // 4 bits
    UBit arid_;  // ID (up to 64 bits)
    UBit arlock_;  // 2 bits
    UBit arqos_;  // 4 bits
    UBit arregion_;  // 4 bits
    DataView aruser_;  // View into buffer for aruser (DataView holds the shared_ptr)
    size_t aruser_width_bytes_; // in bytes
    bool arvalid_;
    bool arready_;
};

// Class to hold AXI Read Data (R) channel values
class AxiRChannel {
public:
    // Constructor - creates default DataViews for rdata, ruser
    // rdata_width is in bytes
    AxiRChannel(size_t rdata_width_bytes, size_t rid_width, size_t ruser_width_bytes = 0);
    
    // Getter methods
    const DataView& getRData() const { return rdata_; }
    DataView& getRData() { return rdata_; }
    size_t getRDataWidthBytes() const { return rdata_width_bytes_; }
    uint8_t getRResp() const { return rresp_.u8(); }
    uint64_t getRId() const { return rid_.u64(); }
    size_t getRIdWidth() const { return rid_.bits(); }
    bool getRLast() const { return rlast_; }
    DataView& getRUser() { return ruser_; }
    const DataView& getRUser() const { return ruser_; }
    size_t getRUserWidthBytes() const { return ruser_width_bytes_; }
    bool getRValid() const { return rvalid_; }
    bool getRReady() const { return rready_; }
    
    // Methods to set values
    void setRResp(uint8_t resp);
    void setRResp(AxiRespType resp);  // Enum-based setter
    void setRLast(bool last);
    void setRValid(bool valid);
    void setRReady(bool ready);
    void setRId(uint64_t id);
    
    // Enum-based getter
    AxiRespType getRRespEnum() const;
    
    // Set data (creates views or copies the views)
    void setRData(const DataView& data);
    void setRUser(const DataView& user);
    
    // Clear all values
    void clear();

private:
    DataView rdata_;  // View into buffer for rdata (DataView holds the shared_ptr)
    size_t rdata_width_bytes_; // in bytes
    UBit rresp_;  // 2 bits
    UBit rid_;  // ID (up to 64 bits)
    bool rlast_;
    DataView ruser_;  // View into buffer for ruser (DataView holds the shared_ptr)
    size_t ruser_width_bytes_; // in bytes
    bool rvalid_;
    bool rready_;
};

// AXI Interface class that instantiates all 5 AXI channels
// Provides a convenient wrapper to access all channels together
class AxiInterface {
public:
    // Constructor - creates all 5 channels with specified widths
    // Parameters:
    //   addr_width: Address width in bits (for AW and AR channels)
    //   data_width: Data width in bits (for W and R channels)
    //   id_width: ID width in bits (for all channels)
    //   aw_user_bytes: AW user field width in bytes (default 0)
    //   w_user_bytes: W user field width in bytes (default 0)
    //   b_user_bytes: B user field width in bytes (default 0)
    //   ar_user_bytes: AR user field width in bytes (default 0)
    //   r_user_bytes: R user field width in bytes (default 0)
    AxiInterface(
        size_t addr_width,
        size_t data_width,
        size_t id_width,
        size_t awuser_width = 0,
        size_t wuser_width = 0,
        size_t buser_width = 0,
        size_t aruser_width = 0,
        size_t ruser_width = 0
    );
    
    // Destructor
    ~AxiInterface() = default;
    
    // Get const references to channels (for read-only access)
    const AxiAwChannel& getAwChannel() const { return aw_channel_; }
    const AxiWChannel& getWChannel() const { return w_channel_; }
    const AxiBChannel& getBChannel() const { return b_channel_; }
    const AxiArChannel& getArChannel() const { return ar_channel_; }
    const AxiRChannel& getRChannel() const { return r_channel_; }
    
    // Get non-const references to channels (for modification)
    AxiAwChannel& getAwChannel() { return aw_channel_; }
    AxiWChannel& getWChannel() { return w_channel_; }
    AxiBChannel& getBChannel() { return b_channel_; }
    AxiArChannel& getArChannel() { return ar_channel_; }
    AxiRChannel& getRChannel() { return r_channel_; }
    
    // Clear all channels
    void clear();

private:
    AxiAwChannel aw_channel_;  // Write Address channel
    AxiWChannel w_channel_;    // Write Data channel
    AxiBChannel b_channel_;    // Write Response channel
    AxiArChannel ar_channel_;  // Read Address channel
    AxiRChannel r_channel_;    // Read Data channel
};

#endif // AXI_INTERFACE_H

