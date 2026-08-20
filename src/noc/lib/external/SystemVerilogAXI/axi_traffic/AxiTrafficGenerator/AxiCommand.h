#ifndef AXI_COMMAND_H
#define AXI_COMMAND_H

#include "AxiInterface.h"
#include "DataView.h"
#include "UBit.h"
#include <vector>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <cmath>


// Base AXI Command class (from master perspective)
// Contains common members and methods shared by read and write commands
class AxiCommand {
public:
    virtual ~AxiCommand() = default;

    // Pure virtual method to check if command is complete
    virtual bool isDone() const = 0;

    // Common getters
    UBit getAddr() const { return addr_; }
    UBit getId() const { return id_; }
    size_t getNumBeats() const { return num_beats_; }
    size_t getBeatSizeBytes() const { return beat_size_bytes_; }

protected:
    // Protected constructor to prevent direct instantiation
    AxiCommand(
        uint64_t addr,
        size_t addr_width,
        size_t num_beats, 
        size_t beat_size_bytes,
        uint32_t id,
        size_t id_width
    ) : addr_(addr_width, addr),
        id_(id_width, id),
        num_beats_(num_beats),
        beat_size_bytes_(beat_size_bytes)
    {
    }

    // Common members shared by all command types
    UBit addr_;
    UBit id_;
    size_t num_beats_;
    size_t beat_size_bytes_;
};

// AXI Write Command (from master perspective)
// Handles AW and W channels only
class AxiWriteCommand : public AxiCommand {
public:
    AxiWriteCommand(
        uint64_t addr,
        size_t addr_width,
        size_t num_beats, 
        size_t beat_size_bytes,
        size_t channel_data_width_bytes,
        uint32_t id,
        size_t id_width,
        std::shared_ptr<DataView> aw_user, 
        std::shared_ptr<DataView> w_user, 
        std::shared_ptr<DataView> w_data
    );

    ~AxiWriteCommand();

    // Set values on AW and W channels for the next cycle
    void set_next_values(AxiAwChannel& aw_channel, AxiWChannel& w_channel);
    
    // Update state based on ready signals (returns true if command is complete)
    bool tick(AxiAwChannel& aw_channel, AxiWChannel& w_channel);

    // Check if command is complete (AW sent and all W beats sent)
    bool isDone() const override { return all_beats_sent_ && sent_aw_; }

    // Write-specific getters
    std::shared_ptr<DataView> getAwUser() const { return aw_user_; }
    std::shared_ptr<DataView> getWUser() const { return w_user_; }
    std::shared_ptr<DataView> getWData() const { return w_data_; }
    uint8_t getBeatsSent() const { return beats_sent_; }
    bool getAllBeatsSent() const { return all_beats_sent_; }
    bool getSentAw() const { return sent_aw_; }

private:
    std::shared_ptr<DataView> aw_user_;
    std::shared_ptr<DataView> w_user_;
    std::shared_ptr<DataView> w_data_;
    size_t channel_data_width_bytes_;
    uint8_t beats_sent_;
    bool all_beats_sent_;
    bool sent_aw_;
};

// AXI Read Command (from master perspective)
// Handles AR channel only
class AxiReadCommand : public AxiCommand {
public:
    AxiReadCommand(
        uint64_t addr,
        size_t addr_width,
        size_t num_beats, 
        size_t beat_size_bytes,
        uint32_t id,
        size_t id_width,
        std::shared_ptr<DataView> ar_user
    );

    ~AxiReadCommand();

    // Set values on AR channel for the next cycle
    void set_next_values(AxiArChannel& ar_channel);

    // Update state based on ready signal (returns true if AR is sent)
    bool tick(AxiArChannel& ar_channel);

    // Check if AR has been sent
    bool isDone() const override { return sent_ar_; }

    // Read-specific getters
    std::shared_ptr<DataView> getArUser() const { return ar_user_; }
    bool getSentAr() const { return sent_ar_; }

private:
    std::shared_ptr<DataView> ar_user_;
    bool sent_ar_;
};

#endif // AXI_COMMAND_H
