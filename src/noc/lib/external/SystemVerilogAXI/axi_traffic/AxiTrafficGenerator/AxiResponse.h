#ifndef AXI_RESPONSE_H
#define AXI_RESPONSE_H

#include "AxiInterface.h"
#include "DataView.h"
#include "UBit.h"
#include <vector>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>


// Base AXI Response class (from slave perspective)
// Contains common members and methods shared by read and write responses
class AxiResponse {
public:
    virtual ~AxiResponse() = default;

    // Pure virtual method to check if response is complete
    virtual bool isDone() const = 0;

    // Common getters
    UBit getId() const { return id_; }
    uint8_t getResp() const { return resp_.u8(); }

protected:
    // Protected constructor to prevent direct instantiation
    AxiResponse(
        uint32_t id,
        size_t id_width,
        uint8_t resp = 0  // 0 = OKAY
    ) : id_(id_width, id),
        resp_(2, resp)
    {
    }

    // Common members shared by all response types
    UBit id_;
    UBit resp_;
};

// AXI Write Response (from slave perspective)
// Handles B channel only
class AxiWriteResponse : public AxiResponse {
public:
    AxiWriteResponse(
        uint32_t id,
        size_t id_width,
        uint8_t resp = 0,  // 0 = OKAY
        std::shared_ptr<DataView> buser = nullptr
    );

    ~AxiWriteResponse();

    // Set values on B channel for the next cycle
    void set_next_values(AxiBChannel& b_channel);

    // Update state based on ready signal (returns true if response is complete)
    bool tick(AxiBChannel& b_channel);

    // Check if response has been sent
    bool isDone() const override { return sent_bresp_; }

    // Write-specific getters
    std::shared_ptr<DataView> getBUser() const { return buser_; }
    bool getSentBresp() const { return sent_bresp_; }

private:
    std::shared_ptr<DataView> buser_;
    bool sent_bresp_;
};

// AXI Read Response (from slave perspective)
// Handles R channel only
class AxiReadResponse : public AxiResponse {
public:
    AxiReadResponse(
        uint32_t id,
        size_t id_width,
        size_t num_beats,
        size_t beat_size,
        std::shared_ptr<DataView> r_data,
        uint8_t resp = 0,  // 0 = OKAY
        std::shared_ptr<DataView> ruser = nullptr
    );

    ~AxiReadResponse();

    // Set values on R channel for the next cycle
    void set_next_values(AxiRChannel& r_channel);

    // Update state based on ready signal (returns true if all beats sent)
    bool tick(AxiRChannel& r_channel);

    // Check if all R beats have been sent
    bool isDone() const override { return all_beats_sent_; }

    // Read-specific getters
    size_t getNumBeats() const { return num_beats_; }
    size_t getBeatSize() const { return beat_size_; }
    std::shared_ptr<DataView> getRData() const { return r_data_; }
    std::shared_ptr<DataView> getRUser() const { return ruser_; }
    uint8_t getBeatsSent() const { return beats_sent_; }
    bool getAllBeatsSent() const { return all_beats_sent_; }

private:
    size_t num_beats_;
    size_t beat_size_;
    std::shared_ptr<DataView> r_data_;
    std::shared_ptr<DataView> ruser_;
    uint8_t beats_sent_;
    bool all_beats_sent_;
};

#endif // AXI_RESPONSE_H

