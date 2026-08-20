#include "AxiCommand.h"

AxiWriteCommand::AxiWriteCommand(
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
) : AxiCommand(addr, addr_width, num_beats, beat_size_bytes, id, id_width),
    aw_user_(aw_user),
    w_user_(w_user),
    w_data_(w_data),
    channel_data_width_bytes_(channel_data_width_bytes),
    beats_sent_(0),
    all_beats_sent_(false),
    sent_aw_(false)
{
}

AxiWriteCommand::~AxiWriteCommand() {
}

void AxiWriteCommand::set_next_values(AxiAwChannel& aw_channel, AxiWChannel& w_channel) {
    if (!all_beats_sent_) {
        if (!sent_aw_) {
            // Set AW channel values
            aw_channel.setAwId(id_.u64());
            aw_channel.setAwAddr(addr_.u64());
            aw_channel.setAwLen(num_beats_ - 1);
            aw_channel.setAwSize(std::log2(beat_size_bytes_));
            aw_channel.setAwBurst(AxiBurstType::INCR);
            aw_channel.setAwProt(0);
            aw_channel.setAwCache(0);
            // Only set AW user data if it's not empty
            if (aw_user_ && aw_user_->size() > 0) {
                DataView aw_user_view = aw_user_->subview(0, aw_user_->size());
                if (aw_user_view.size() != aw_user_->size()) {
                    throw std::runtime_error("aw_user_view size does not match aw_user size");
                }
                aw_channel.setAwUser(aw_user_view);
            } else {
                aw_channel.setAwUser(DataView());
            }
            aw_channel.setAwValid(true);
            
            // W channel not valid until AW is accepted
            w_channel.setWValid(false);
        } else {
            // AW already sent, now send W data
            w_channel.setWValid(true);
            DataView w_data_view = w_data_->subview(
                beats_sent_ * channel_data_width_bytes_,
                channel_data_width_bytes_
            );
            w_channel.setWData(w_data_view);
            // Full-beat writes: one strobe bit per data byte (AXI WSTRB).
            {
                const size_t wbytes = w_channel.getWDataWidthBytes();
                std::vector<UBit> strb;
                strb.reserve(wbytes);
                for (size_t i = 0; i < wbytes; ++i) {
                    const unsigned on = (i < beat_size_bytes_) ? 1u : 0u;
                    strb.emplace_back(1u, on);
                }
                w_channel.setWStrb(strb);
            }
            // Only set W user data if it's not empty
            if (w_user_ && w_user_->size() > 0) {
                DataView w_user_view = w_user_->subview(beats_sent_ * w_user_->size(), w_user_->size());
                w_channel.setWUser(w_user_view);
            } else {
                w_channel.setWUser(DataView());
            }
            w_channel.setWLast(beats_sent_ == num_beats_ - 1);
            
            // AW channel no longer valid
            aw_channel.setAwValid(false);
        }
    } else {
        // All beats sent
        aw_channel.setAwValid(false);
        w_channel.setWValid(false);
    }
}

bool AxiWriteCommand::tick(AxiAwChannel& aw_channel, AxiWChannel& w_channel) {
    if (!sent_aw_) {
        if (aw_channel.getAwReady() && aw_channel.getAwValid()) {
            sent_aw_ = true;
        }
    } else if (!all_beats_sent_) {
        if (w_channel.getWReady() && w_channel.getWValid()) {
            beats_sent_++;
            if (beats_sent_ == num_beats_) {
                all_beats_sent_ = true;
            }
        }
    }
    
    return isDone();
}

AxiReadCommand::AxiReadCommand(
    uint64_t addr,
    size_t addr_width,
    size_t num_beats, 
    size_t beat_size_bytes,
    uint32_t id,
    size_t id_width,
    std::shared_ptr<DataView> ar_user
) : AxiCommand(addr, addr_width, num_beats, beat_size_bytes, id, id_width),
    ar_user_(ar_user),
    sent_ar_(false)
{
}

AxiReadCommand::~AxiReadCommand() {
}

void AxiReadCommand::set_next_values(AxiArChannel& ar_channel) {
    if (!sent_ar_) {
        ar_channel.setArId(id_.u64());
        ar_channel.setArAddr(addr_.u64());
        ar_channel.setArLen(num_beats_ - 1);
        ar_channel.setArSize(std::log2(beat_size_bytes_));
        ar_channel.setArBurst(AxiBurstType::INCR);
        ar_channel.setArProt(0);
        ar_channel.setArCache(0);
        // Only set AR user data if it's not empty
        if (ar_user_ && ar_user_->size() > 0) {
            DataView ar_user_view = ar_user_->subview(0, ar_user_->size());
            if (ar_user_view.size() != ar_user_->size()) {
                throw std::runtime_error("ar_user_view size does not match ar_user size");
            }
            ar_channel.setArUser(ar_user_view);
        } else {
            ar_channel.setArUser(DataView());
        }
        ar_channel.setArValid(true);
    } else {
        ar_channel.setArValid(false);
    }
}

bool AxiReadCommand::tick(AxiArChannel& ar_channel) {
    if (!sent_ar_) {
        if (ar_channel.getArReady() && ar_channel.getArValid()) {
            sent_ar_ = true;
        }
    }
    return isDone();
}
