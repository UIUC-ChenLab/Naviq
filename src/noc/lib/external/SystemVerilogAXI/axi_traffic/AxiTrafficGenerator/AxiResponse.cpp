#include "AxiResponse.h"

AxiWriteResponse::AxiWriteResponse(
    uint32_t id,
    size_t id_width,
    uint8_t resp,
    std::shared_ptr<DataView> buser
) : AxiResponse(id, id_width, resp),
    buser_(buser),
    sent_bresp_(false)
{
}

AxiWriteResponse::~AxiWriteResponse() {
}

void AxiWriteResponse::set_next_values(AxiBChannel& b_channel) {
    if (!sent_bresp_) {
        b_channel.setBId(id_.u64());
        b_channel.setBResp(resp_.u8());
        // Only set B user data if it's not empty
        if (buser_ && buser_->size() > 0) {
            DataView buser_view = buser_->subview(0, buser_->size());
            b_channel.setBUser(buser_view);
        } else {
            b_channel.setBUser(DataView());
        }
        b_channel.setBValid(true);
    } else {
        b_channel.setBValid(false);
    }
}

bool AxiWriteResponse::tick(AxiBChannel& b_channel) {
    if (!sent_bresp_) {
        if (b_channel.getBReady() && b_channel.getBValid()) {
            sent_bresp_ = true;
        }
    }
    return isDone();
}

AxiReadResponse::AxiReadResponse(
    uint32_t id,
    size_t id_width,
    size_t num_beats,
    size_t beat_size,
    std::shared_ptr<DataView> r_data,
    uint8_t resp,
    std::shared_ptr<DataView> ruser
) : AxiResponse(id, id_width, resp),
    num_beats_(num_beats),
    beat_size_(beat_size),
    r_data_(r_data),
    ruser_(ruser),
    beats_sent_(0),
    all_beats_sent_(false)
{
}

AxiReadResponse::~AxiReadResponse() {
}

void AxiReadResponse::set_next_values(AxiRChannel& r_channel) {
    if (!all_beats_sent_) {
        r_channel.setRId(id_.u64());
        r_channel.setRResp(resp_.u8());
        r_channel.setRLast(beats_sent_ == num_beats_ - 1);
        
        // Set R data for current beat (r_data_ should always be valid)
        if (r_data_ && r_data_->size() > 0) {
            DataView r_data_view = r_data_->subview(beats_sent_ * beat_size_, beat_size_);
            r_channel.setRData(r_data_view);
        } else {
            throw std::runtime_error("AxiReadResponse: r_data_ is null or empty");
        }
        
        // Only set R user data if it's not empty
        if (ruser_ && ruser_->size() > 0) {
            DataView ruser_view = ruser_->subview(beats_sent_ * ruser_->size(), ruser_->size());
            r_channel.setRUser(ruser_view);
        } else {
            r_channel.setRUser(DataView());
        }
        
        r_channel.setRValid(true);
    } else {
        r_channel.setRValid(false);
    }
}

bool AxiReadResponse::tick(AxiRChannel& r_channel) {
    if (!all_beats_sent_) {
        if (r_channel.getRReady() && r_channel.getRValid()) {
            beats_sent_++;
            if (beats_sent_ == num_beats_) {
                all_beats_sent_ = true;
            }
        }
    }
    return isDone();
}

