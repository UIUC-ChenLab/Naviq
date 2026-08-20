// #include "AxiFileStrategy.h"
// #include "AxiInterface.h"


// AxiFileStrategy::AxiFileStrategy()
//     : bytes_streamed_(0),
//     bytes_read_from_file_(0),
//     file_eof_reached_(false),
//     transaction_counter_(0),
//     current_write_addr_(0),
//     in_write_phase_(true)
// {
// }

// AxiFileStrategy::~AxiFileStrategy() {
//     closeFile();
// }

// void AxiFileStrategy::configure(const Config& config) {
//     config_ = config;
//     reset();
// }

// bool AxiFileStrategy::openFile() {
//     closeFile();
    
//     file_.open(config_.file_path, std::ios::binary);
//     if (!file_.is_open()) {
//         std::cerr << "Error: Could not open file: " << config_.file_path << std::endl;
//         return false;
//     }
    
//     // Get file size
//     file_.seekg(0, std::ios::end);
//     file_size_ = file_.tellg();
//     file_.seekg(config_.start_offset, std::ios::beg);
    
//     bytes_read_from_file_ = config_.start_offset;
    
//     if (config_.max_bytes > 0 && config_.max_bytes < file_size_ - config_.start_offset) {
//         file_size_ = config_.start_offset + config_.max_bytes;
//     }
    
//     return true;
// }

// void AxiFileStrategy::closeFile() {
//     if (file_.is_open()) {
//         file_.close();
//     }
//     file_eof_reached_ = false;
// }

// void AxiFileStrategy::reset() {
//     if (file_.is_open()) {
//         file_.seekg(config_.start_offset, std::ios::beg);
//         bytes_read_from_file_ = config_.start_offset;
//     }
    
//     bytes_streamed_ = 0;
//     transaction_counter_ = 0;
//     current_write_addr_ = config_.base_addr;
//     file_eof_reached_ = false;
    
//     // Reset mode-specific state
//     in_write_phase_ = true;
    
//     // Initialize write and read request tracking
//     initializeWriteRequestTracking();
//     initializeReadRequestTracking();
    
//     // Open file if configured
//     if (!config_.file_path.empty()) {
//         openFile();
//     }
// }

// bool AxiFileStrategy::hasMoreData() const {
//     if (config_.read_write_mode == ReadWriteMode::WRITE_ONLY) {
//         // For write-only, check if we've read all data from file
//         if (file_eof_reached_) {
//             return false;
//         }
//         if (config_.max_bytes > 0 && bytes_streamed_ >= config_.max_bytes) {
//             return false;
//         }
//         return true;
//     } else if (config_.read_write_mode == ReadWriteMode::INTERLEAVED) {
//         // Check if we have more writes or finished reads
//         if (!file_eof_reached_ && (config_.max_bytes == 0 || bytes_streamed_ < config_.max_bytes)) {
//             return true;  // More writes possible
//         }
//         return !finished_writes_.empty() || !allWritesCompleted();  // Or finished reads or outstanding writes
//     } else {  // SEQUENTIAL
//         if (in_write_phase_) {
//             // Still in write phase
//             if (file_eof_reached_) {
//                 // Check if all writes have completed
//                 return !allWritesCompleted() || !finished_writes_.empty();
//             }
//             if (config_.max_bytes > 0 && bytes_streamed_ >= config_.max_bytes) {
//                 return !allWritesCompleted() || !finished_writes_.empty();
//             }
//             return true;
//         } else {
//             // In read phase
//             return !finished_writes_.empty();
//         }
//     }
// }


// bool AxiFileStrategy::readFileData(std::vector<uint8_t>& data, size_t bytes_to_read) {
//     data.resize(bytes_to_read, 0);
    
//     // Check if we've read max_bytes
//     if (config_.max_bytes > 0 && 
//         bytes_read_from_file_ - config_.start_offset >= config_.max_bytes) {
//         return false;
//     }
    
//     // Read data from file
//     if (!file_.read(reinterpret_cast<char*>(data.data()), bytes_to_read)) {
//         size_t bytes_read = file_.gcount();
        
//         // Fill remaining bytes with zeros if partial read
//         if (bytes_read > 0 && bytes_read < bytes_to_read) {
//             std::memset(data.data() + bytes_read, 0, bytes_to_read - bytes_read);
//             bytes_read_from_file_ += bytes_read;
//             file_eof_reached_ = true;
//             return true;
//         }
        
//         // EOF reached
//         if (bytes_read == 0) {
//             file_eof_reached_ = true;
//             std::memset(data.data(), 0, bytes_to_read);
//             return false;
//         }
//     }
    
//     bytes_read_from_file_ += bytes_to_read;
//     return true;
// }

// uint64_t AxiFileStrategy::alignAddress(uint64_t addr, size_t data_width, size_t transaction_size_bytes) const {
//     if (!config_.align_addresses) {
//         return addr;
//     }
    
//     // Align to transaction_size_bytes boundary
//     uint64_t mask = ~(static_cast<uint64_t>(transaction_size_bytes) - 1);
//     return addr & mask;
// }

// size_t AxiFileStrategy::calculateNumBeats(size_t transaction_size_bytes, size_t data_width) const {
//     size_t bytes_per_beat = data_width / 8;
//     return (transaction_size_bytes + bytes_per_beat - 1) / bytes_per_beat;  // Ceiling division
// }

// std::shared_ptr<AxiWriteCommand> AxiFileStrategy::createWriteCommand(
//     const AxiInterface& axi_interface
// ) {
//     // Extract sizes from AxiInterface
//     size_t addr_width = axi_interface.getAwChannel().getAwAddrWidth();
//     size_t data_width = axi_interface.getWChannel().getWDataWidthBytes() * 8; // Convert bytes to bits
//     size_t id_width = axi_interface.getAwChannel().getAwIdWidth();
//     size_t aw_user_width_bytes = axi_interface.getAwChannel().getAwUserWidthBytes();
//     size_t w_user_width_bytes = axi_interface.getWChannel().getWUserWidthBytes();
    
//     // Create DataViews from the channels (create copies that share the underlying buffers)
//     std::shared_ptr<DataView> aw_user_view;
//     if (aw_user_width_bytes > 0) {
//         const DataView& aw_user_ref = axi_interface.getAwChannel().getAwUser();
//         aw_user_view = std::make_shared<DataView>(aw_user_ref.contents, aw_user_ref.size(), 0);
//     } else {
//         aw_user_view = std::make_shared<DataView>();
//     }
    
//     std::shared_ptr<DataView> w_user_view;
//     if (w_user_width_bytes > 0) {
//         const DataView& w_user_ref = axi_interface.getWChannel().getWUser();
//         w_user_view = std::make_shared<DataView>(w_user_ref.contents, w_user_ref.size(), 0);
//     } else {
//         w_user_view = std::make_shared<DataView>();
//     }
    
//     // For w_data_view, use the W channel's data view (shares the underlying buffer)
//     const DataView& w_data_ref = axi_interface.getWChannel().getWData();
//     std::shared_ptr<DataView> w_data_view = std::make_shared<DataView>(w_data_ref.contents, w_data_ref.size(), 0);
    
//     // Read data from file
//     size_t transaction_size = config_.transaction_size_bytes;
//     std::vector<uint8_t> file_data;
//     bool data_available = readFileData(file_data, transaction_size);
    
//     if (!data_available) {
//         return nullptr;
//     }
    
//     // Align address if needed
//     uint64_t addr = alignAddress(current_write_addr_, data_width, transaction_size);
    
//     // Calculate number of beats
//     size_t num_beats = calculateNumBeats(transaction_size, data_width);
//     size_t bytes_per_beat = data_width / 8;
    
//     // Prepare data - copy file_data into w_data_view
//     size_t total_data_size = num_beats * bytes_per_beat;
//     if (w_data_view->size() < total_data_size) {
//         std::cerr << "Warning: w_data_view too small, resizing" << std::endl;
//     }
    
//     // Copy file data to the first part of w_data_view
//     size_t copy_size = std::min(file_data.size(), total_data_size);
//     std::memcpy(w_data_view->data(), file_data.data(), copy_size);
//     // Fill remaining with zeros
//     if (copy_size < total_data_size) {
//         std::memset(w_data_view->data() + copy_size, 0, total_data_size - copy_size);
//     }
    
//     // Create write command
//     auto command = std::make_shared<AxiWriteCommand>(
//         addr,
//         addr_width,
//         num_beats,
//         bytes_per_beat,
//         config_.awid_value,
//         id_width,
//         aw_user_view,
//         w_user_view,
//         w_data_view
//     );
    
//     // Update state
//     current_write_addr_ = addr + transaction_size;
//     bytes_streamed_ += transaction_size;
//     transaction_counter_++;
    
//     return command;
// }

// std::shared_ptr<AxiReadCommand> AxiFileStrategy::createReadCommand(
//     const AxiInterface& axi_interface,
//     uint64_t addr,
//     uint32_t transaction_size_bytes
// ) {
//     // Extract sizes from AxiInterface
//     size_t addr_width = axi_interface.getArChannel().getArAddrWidth();
//     size_t data_width = axi_interface.getRChannel().getRDataWidthBytes() * 8; // Convert bytes to bits
//     size_t id_width = axi_interface.getArChannel().getArIdWidth();
//     size_t ar_user_width_bytes = axi_interface.getArChannel().getArUserWidthBytes();
    
//     // Calculate number of beats
//     size_t num_beats = calculateNumBeats(transaction_size_bytes, data_width);
//     size_t bytes_per_beat = data_width / 8;
    
//     // Create DataViews from the channels (create copies that share the underlying buffers)
//     std::shared_ptr<DataView> ar_user_view;
//     if (ar_user_width_bytes > 0) {
//         const DataView& ar_user_ref = axi_interface.getArChannel().getArUser();
//         ar_user_view = std::make_shared<DataView>(ar_user_ref.contents, ar_user_ref.size(), 0);
//     } else {
//         ar_user_view = std::make_shared<DataView>();
//     }
    
//     // Create and return command
//     return std::make_shared<AxiReadCommand>(
//         addr,
//         addr_width,
//         num_beats,
//         bytes_per_beat,
//         config_.arid_value,
//         id_width,
//         ar_user_view
//     );
// }

// std::shared_ptr<AxiWriteCommand> AxiFileStrategy::getNextWriteCommand(
//     const AxiInterface& axi_interface
// ) {
//     switch (config_.read_write_mode) {
//         case ReadWriteMode::WRITE_ONLY: {
//             auto [write_cmd, read_cmd] = getNextWriteOnly(axi_interface);
//             return write_cmd;
//         }
//         case ReadWriteMode::INTERLEAVED: {
//             auto [write_cmd, read_cmd] = getNextInterleaved(axi_interface);
//             return write_cmd;
//         }
//         case ReadWriteMode::SEQUENTIAL: {
//             // In sequential mode, only generate writes in write phase
//             if (!in_write_phase_) {
//                 return nullptr;
//             }
//             auto [write_cmd, read_cmd] = getNextSequential(axi_interface);
//             return write_cmd;
//         }
//         default:
//             return nullptr;
//     }
// }

// std::shared_ptr<AxiReadCommand> AxiFileStrategy::getNextReadCommand(
//     const AxiInterface& axi_interface
// ) {
//     switch (config_.read_write_mode) {
//         case ReadWriteMode::WRITE_ONLY:
//             return nullptr;
//         case ReadWriteMode::INTERLEAVED: {
//             auto [write_cmd, read_cmd] = getNextInterleaved(axi_interface);
            
//             // Track the sent read request if one was created
//             if (read_cmd) {
//                 uint32_t arid = static_cast<uint32_t>(read_cmd->getId().u64());
//                 // Extract address and size from the read command
//                 uint64_t read_addr = read_cmd->getAddr().u64();
//                 uint32_t transaction_size = static_cast<uint32_t>(read_cmd->getNumBeats() * read_cmd->getBeatSizeBytes());
//                 trackSentReadRequest(arid, read_addr, transaction_size);
//             }
            
//             return read_cmd;
//         }
//         case ReadWriteMode::SEQUENTIAL: {
//             // In sequential mode, only generate reads in read phase
//             if (in_write_phase_) {
//                 return nullptr;
//             }
//             auto [write_cmd, read_cmd] = getNextSequential(axi_interface);
            
//             // Track the sent read request if one was created
//             if (read_cmd) {
//                 uint32_t arid = static_cast<uint32_t>(read_cmd->getId().u64());
//                 // Extract address and size from the read command
//                 uint64_t read_addr = read_cmd->getAddr().u64();
//                 uint32_t transaction_size = static_cast<uint32_t>(read_cmd->getNumBeats() * read_cmd->getBeatSizeBytes());
//                 trackSentReadRequest(arid, read_addr, transaction_size);
//             }
            
//             return read_cmd;
//         }
//         default:
//             return nullptr;
//     }
// }

// std::tuple<std::shared_ptr<AxiWriteCommand>, std::shared_ptr<AxiReadCommand>> AxiFileStrategy::getNextWriteOnly(
//     const AxiInterface& axi_interface
// ) {
//     if (!hasMoreData()) {
//         return std::make_tuple(nullptr, nullptr);
//     }
    
//     // Create write command
//     auto command = createWriteCommand(axi_interface);
//     if (!command) {
//         return std::make_tuple(nullptr, nullptr);
//     }
    
//     return std::make_tuple(command, nullptr);
// }

// std::tuple<std::shared_ptr<AxiWriteCommand>, std::shared_ptr<AxiReadCommand>> AxiFileStrategy::getNextInterleaved(
//     const AxiInterface& axi_interface
// ) {
//     std::shared_ptr<AxiReadCommand> read_cmd = nullptr;
//     std::shared_ptr<AxiWriteCommand> write_cmd = nullptr;
    
//     // Check if we should generate a read command (from finished writes)
//     if (!finished_writes_.empty()) {
//         // Generate read for the oldest finished write request
//         const WriteRequestInfo& write_info = finished_writes_.front();
//         uint64_t read_addr = write_info.addr;
//         uint32_t transaction_size = write_info.transaction_size_bytes;
//         finished_writes_.pop_front();
        
//         read_cmd = createReadCommand(axi_interface, read_addr, transaction_size);
//     }
    
//     // Try to generate a write command if we have more data
//     if (!file_eof_reached_ && (config_.max_bytes == 0 || bytes_streamed_ < config_.max_bytes)) {
//         // Get current address before creating command (since createWriteCommand updates current_write_addr_)
//         size_t data_width = axi_interface.getWChannel().getWDataWidthBytes() * 8; // Convert bytes to bits
//         uint64_t addr_before = current_write_addr_;
        
//         write_cmd = createWriteCommand(axi_interface);
        
//         if (write_cmd) {
//             // Calculate the address that was used (it's the aligned version of addr_before)
//             uint64_t addr = alignAddress(addr_before, data_width, config_.transaction_size_bytes);
            
//             // Track write request (includes data extraction if verification is enabled)
//             uint32_t write_id = static_cast<uint32_t>(config_.awid_value);
//             trackSentWriteRequest(write_id, addr, config_.transaction_size_bytes, write_cmd);
//         }
//     }
    
//     // Return both commands (either or both may be nullptr)
//     return std::make_tuple(write_cmd, read_cmd);
// }

// std::tuple<std::shared_ptr<AxiWriteCommand>, std::shared_ptr<AxiReadCommand>> AxiFileStrategy::getNextSequential(
//     const AxiInterface& axi_interface
// ) {
//     // Check if we should transition from write phase to read phase
//     if (in_write_phase_ && file_eof_reached_ && allWritesCompleted() && !finished_writes_.empty()) {
//         // All writes have been sent and all have received bresp
//         // Transition to read phase to start reading the finished writes
//         in_write_phase_ = false;
//     }
    
//     // First, check if we're in read phase
//     if (!in_write_phase_) {
//         if (!finished_writes_.empty()) {
//             // Generate read for the oldest finished write request
//             const WriteRequestInfo& write_info = finished_writes_.front();
//             uint64_t read_addr = write_info.addr;
//             uint32_t transaction_size = write_info.transaction_size_bytes;
//             finished_writes_.pop_front();
            
//             auto read_cmd = createReadCommand(axi_interface, read_addr, transaction_size);
//             return std::make_tuple(nullptr, read_cmd);
//         }
//         return std::make_tuple(nullptr, nullptr);  // No more addresses to read
//     }
    
//     // In write phase, generate a write command
//     if (!hasMoreData()) {
//         return std::make_tuple(nullptr, nullptr);
//     }
    
//     // Get current address before creating command (since createWriteCommand updates current_write_addr_)
//     size_t data_width_bytes = axi_interface.getWChannel().getWDataWidthBytes();
//     uint64_t addr_before = current_write_addr_;
    
//     auto command = createWriteCommand(axi_interface);
//     if (!command) {
//         return std::make_tuple(nullptr, nullptr);
//     }
    
//     // Calculate the address that was used (it's the aligned version of addr_before)
//     uint64_t addr = alignAddress(addr_before, data_width_bytes, config_.transaction_size_bytes);
    
//     // Track write request (includes data extraction if verification is enabled)
//     uint32_t write_id = static_cast<uint32_t>(config_.awid_value);
//     trackSentWriteRequest(write_id, addr, config_.transaction_size_bytes, command);
    
//     return std::make_tuple(command, nullptr);
// }

// std::string AxiFileStrategy::getConfigString() const {
//     std::ostringstream oss;
//     oss << "mode=file_stream"
//         << ",file=" << config_.file_path
//         << ",base_addr=0x" << std::hex << config_.base_addr << std::dec
//         << ",transaction_size=" << config_.transaction_size_bytes;
    
//     if (config_.read_write_mode == ReadWriteMode::WRITE_ONLY) {
//         oss << ",read_write_mode=write_only";
//     } else if (config_.read_write_mode == ReadWriteMode::INTERLEAVED) {
//         oss << ",read_write_mode=interleaved";
//     } else {
//         oss << ",read_write_mode=sequential";
//     }
    
//     return oss.str();
// }

