// #ifndef AXI_FILE_STRATEGY_H
// #define AXI_FILE_STRATEGY_H

// #include "AxiTrafficStrategy.h"
// #include "DataView.h"
// #include "AxiInterface.h"
// #include <fstream>
// #include <string>
// #include <cstdint>
// #include <memory>
// #include <vector>
// #include <deque>
// #include "AxiCommand.h"
// #include <algorithm>
// #include <cmath>
// #include <iostream>
// #include <sstream>
// #include <cstring>

// // File stream traffic generation strategy for AXI
// // Reads data from a file and generates write/read transactions
// class AxiFileStrategy : public AxiTrafficStrategy {
// public:
//     struct Config {
//         std::string file_path;
//         uint64_t base_addr = 0;              // Base address for transactions
//         uint32_t transaction_size_bytes = 64; // Size of each transaction in bytes
//         ReadWriteMode read_write_mode = ReadWriteMode::WRITE_ONLY;
//         uint64_t start_offset = 0;            // Start reading from byte offset in file
//         uint32_t max_awid = 15;               // Maximum AXI ID (for sizing vector)
//         uint64_t max_bytes = 0;               // Maximum bytes to read (0 = entire file)
//         uint32_t awid_value = 0;              // Constant AWID value
//         uint32_t arid_value = 0;              // Constant ARID value
//         uint8_t awsize = 6;                   // AWSize (3 bits, log2 of bytes per beat, 6 = 64 bytes)
//         uint8_t arsize = 6;                   // ARSize (3 bits, log2 of bytes per beat)
//         uint8_t awburst = 1;                  // AWBurst (INCR = 1)
//         uint8_t arburst = 1;                  // ARBurst (INCR = 1)
//         bool align_addresses = true;          // Align addresses to transaction_size_bytes
//     };
    
//     AxiFileStrategy();
    
//     ~AxiFileStrategy() override;
    
//     // Configure the strategy programmatically
//     void configure(const Config& config);
    
//     // AxiTrafficStrategy interface
//     std::shared_ptr<AxiWriteCommand> getNextWriteCommand(
//         const AxiInterface& axi_interface
//     ) override;
    
//     std::shared_ptr<AxiReadCommand> getNextReadCommand(
//         const AxiInterface& axi_interface
//     ) override;
    
//     bool hasMoreData() const override;
//     void reset() override;
//     std::string getModeName() const override { return "file_stream"; }
//     std::string getConfigString() const override;
//     ReadWriteMode getReadWriteMode() const override { return config_.read_write_mode; }
//     bool isInWritePhase() const override { return in_write_phase_; }
    
//     // Get statistics
//     uint64_t getBytesStreamed() const { return bytes_streamed_; }
//     uint64_t getTransactionsGenerated() const { return transaction_counter_; }

// private:
//     Config config_;
    
//     std::ifstream file_;
//     uint64_t file_size_;
//     uint64_t bytes_streamed_;
//     uint64_t bytes_read_from_file_;
//     bool file_eof_reached_;
    
//     // Transaction tracking
//     uint64_t transaction_counter_;
//     uint64_t current_write_addr_;
//     bool in_write_phase_;
    
//     // Helper to get the maximum AXI ID value (for sizing the vector)
//     size_t getMaxAxiId() const override { return config_.max_awid; }
    
//     // Helper methods
//     bool openFile();
//     void closeFile();
//     bool readFileData(std::vector<uint8_t>& data, size_t bytes_to_read);
//     uint64_t alignAddress(uint64_t addr, size_t data_width, size_t transaction_size_bytes) const;
//     size_t calculateNumBeats(size_t transaction_size_bytes, size_t data_width) const;
    
//     // Helper methods for creating commands
//     std::shared_ptr<AxiWriteCommand> createWriteCommand(
//         const AxiInterface& axi_interface
//     );
    
//     std::shared_ptr<AxiReadCommand> createReadCommand(
//         const AxiInterface& axi_interface,
//         uint64_t addr,
//         uint32_t transaction_size_bytes
//     );
    
//     // Mode-specific command getter methods
//     // Returns tuple of (write_command, read_command)
//     std::tuple<std::shared_ptr<AxiWriteCommand>, std::shared_ptr<AxiReadCommand>> getNextWriteOnly(
//         const AxiInterface& axi_interface
//     );
    
//     std::tuple<std::shared_ptr<AxiWriteCommand>, std::shared_ptr<AxiReadCommand>> getNextInterleaved(
//         const AxiInterface& axi_interface
//     );
    
//     std::tuple<std::shared_ptr<AxiWriteCommand>, std::shared_ptr<AxiReadCommand>> getNextSequential(
//         const AxiInterface& axi_interface
//     );
// };

// #endif // AXI_FILE_STRATEGY_H

