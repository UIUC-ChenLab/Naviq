#include "noc/core/network/rrob.hh"
#include "base/cprintf.hh"
#include "base/logging.hh"
#include "sim/serialize.hh"
#include "sim/sim_events.hh"
#include "debug/NocTiming.hh"

#include <algorithm>
#include <optional>

namespace gem5 {
namespace noc {
namespace garnet {

ReadReorderBuffer::ReadReorderBuffer(const Params &p)
    : SimObject(p),
      axiListManager(p.max_entries, p.entry_size),
      m_max_entries(p.max_entries),
      m_entry_size(p.entry_size),
      numAxiReads(0)
{
    fatal_if(m_entry_size == 0 || (m_entry_size % FLIT_SIZE) != 0,
             "RROB entry_size (%u) must be a non-zero multiple of flit size (%zu)",
             m_entry_size, FLIT_SIZE);
}

// return, along with the payload, the rrob entry id and beat id
std::vector<MsgPtr> AxiListManager::generateAxiReadPayloads(AxiID axi_id, Tick curTime){
    // generate any NPP read responses for the given axi_id depending on
    // burst size and data ready to be read from RROB entry
    std::vector<MsgPtr> npp_read_payloads;

    auto it = lists.find(axi_id);
    if (it == lists.end()){
        panic("No RROB entry found for axi_id %d\n", axi_id);
    }

    AxiList& list = it->second;

    aximmRWData namePayload; //TODO change, for now, just useful to mark the type and id
    namePayload.cmd = gem5::noc::AximmCommand::READ;
    namePayload.id = axi_id;

    // each message will just hold a single beat of rdata, but for NocMemoryMsg pload need size 16 static array
    std::array<aximmRWData, 4> data;

    // must guarantee reads are in order within AXI id, so only read from the head of the list until
    // get to non-valid portion of an entry
    for (auto it_entry = list.begin(); it_entry != list.end(); ++it_entry) {


        RROBEntry& entry = *it_entry;

        if (entry.need_next_entry) {
            auto next_it = std::next(it_entry);
            if (next_it == list.end()) {
                panic("AxiListManager::generateAxiReadPayloads no next entry exists \n");
            }

            RROBEntry& nextEntry = *next_it;

            // if need next entry, check that both entries are valid and not sent
            if (entry.beat_statuses[0].valid && !entry.beat_statuses[0].sent
                && nextEntry.beat_statuses[0].valid && !nextEntry.beat_statuses[0].sent) {

                // create a payload
                aximmRWData axi_payload;
                axi_payload.id = entry.axi_id;
                axi_payload.valid = true;
                axi_payload.last = nextEntry.contains_last; //only 1/2 beat in this rrob entry, don't even care about last_beat_idx
                                                            // this entry and next together must be last beat

                // printf("RROB pushing back read payload, Axi ID %d, entry beat size = %d\n",axi_id, entry.beat_size);
                // copy data from both entries into axi payload
                std::copy(entry.data.begin(),
                            entry.data.end(),
                            axi_payload.data.begin());
                std::copy(nextEntry.data.begin(),
                            nextEntry.data.end(),
                            axi_payload.data.begin() + entry.data.size());

                data[0] = axi_payload;
                std::shared_ptr<NocMemoryMsg> msg_ptr = std::shared_ptr<NocMemoryMsg>(new NocMemoryMsg(curTime, nullptr, AxiMsgSizeType::R, namePayload, data));
                msg_ptr->setRROBBeatID(0); // this entry only has 1 beat (technically 1/2 beat) stored here, so only using idx 0 for statuses. will need this idx to mark as read later
                msg_ptr->setAxiRROBTag(entry.tag);
                msg_ptr->setBeatSize(entry.beat_size);
                npp_read_payloads.push_back(msg_ptr);

                // npp_read_payloads.push_back(std::make_tuple(axi_payload, entry.tag, 0)); // tag is the entry id, beat id is 0 since this is a 64-byte beat

                entry.beat_statuses[0].sent = true; // mark this beat as sent
                nextEntry.beat_statuses[0].sent = true; // mark this beat as sent

                continue;
            } else if (!entry.beat_statuses[0].valid || !nextEntry.beat_statuses[0].valid){
                break;
            } else if (entry.beat_statuses[0].sent && nextEntry.beat_statuses[0].sent){
                // both have been sent, just waiting to delete entry after read. go to next entry to see if any data is valid
                continue;
            }
        } else {

            // for each beat in the entry, check if valid and !sent
            // if not valid, return, we have found all data at head of list that was valid
            for (int i=0; i<=entry.last_beat_idx; i++){
                if ((entry.beat_statuses[i].valid && !entry.beat_statuses[i].sent)){
                    // create a payload
                    aximmRWData axi_payload;
                    axi_payload.id = entry.axi_id;
                    axi_payload.valid = true;
                    axi_payload.last = entry.contains_last && entry.last_beat_idx == i;
                    std::copy(entry.data.begin() + (i*entry.beat_size),
                                entry.data.begin() + ((i+1)*entry.beat_size),
                                axi_payload.data.begin());

                    data[0] = axi_payload;
                    std::shared_ptr<NocMemoryMsg> msg_ptr = std::shared_ptr<NocMemoryMsg>(new NocMemoryMsg(curTime, nullptr, AxiMsgSizeType::R, namePayload, data));
                    msg_ptr->setRROBBeatID(i);
                    msg_ptr->setAxiRROBTag(entry.tag);
                    msg_ptr->setBeatSize(entry.beat_size);
                    npp_read_payloads.push_back(msg_ptr);

                    // npp_read_payloads.push_back(std::make_tuple(axi_payload, entry.tag, i)); // tag is the entry id, beat id is i

                    entry.beat_statuses[i].sent = true; // mark this beat as sent

                } else if (!entry.beat_statuses[i].valid) {
                    // if not valid, we have found all data at head of list that was valid
                    return npp_read_payloads;
                }
            }

        }




    }


    return npp_read_payloads;

}




int ReadReorderBuffer::reserve(uint8_t axi_id, uint8_t beat_size, bool contains_last, uint8_t last_beat_idx, int vnet, bool need_next_entry){

    return axiListManager.addEntry(axi_id, beat_size, contains_last, last_beat_idx, vnet, need_next_entry);

}

std::vector<uint8_t> ReadReorderBuffer::read(uint8_t axi_id){

    RROBEntry entry = axiListManager.readEntry(axi_id);

    return entry.data;

}

void ReadReorderBuffer::writeFlit(int tag, std::array<uint8_t, 16>* data, int flit_idx){
    axiListManager.writeFlitEntry(tag, data, flit_idx);

    // do callback to see if any read data beats can now be sent from NMU to tile
    if (wakeup_handler)
        wakeup_handler(axiListManager.getAxiID(tag));
    else
        panic("no wakeup_handler setup in RROB for when read data written \n");

}


std::vector<MsgPtr> ReadReorderBuffer::generateAxiReadPayloads(AxiID axi_id, Tick curTime){
    return axiListManager.generateAxiReadPayloads(axi_id, curTime);
}

void ReadReorderBuffer::markBeatRead(uint8_t axi_id, int tag, uint8_t beat_idx){

    // Get iterator to the RROB entry using the tag
    auto it = axiListManager.getIterator(tag);
    AxiListManager::AxiList& list = axiListManager.getList(axi_id);

    if (it == list.end()) {
        panic("RROB: Invalid tag %d provided to markBeatRead!", tag);
        return;
    }

    RROBEntry& entry = *it;
    RROBEntry nextEntry;

    auto nextIt = std::next(it);

    if (nextIt != list.end())
        nextEntry = *nextIt;


    // Sanity checks
    if (entry.axi_id != axi_id) {
        panic("RROB: AXI ID mismatch for tag %d: expected %u, got %u", tag, entry.axi_id, axi_id);
        return;
    }

    if (beat_idx >= entry.beat_statuses.size()) {
        panic("RROB: Invalid beat index %d for tag %d", beat_idx, tag);
        return;
    }

    // Mark the beat as read
    entry.beat_statuses[beat_idx].read = true;

    // Check if all beats have been read
    // bool all_read = std::all_of(entry.beat_statuses.begin(),
    //                                 entry.beat_statuses.end(),
    //                                 [](const beatStatus& status) { return status.read; });
    // --- ADD THIS LOGIC ---
    bool all_read = true;
    for (int i = 0; i <= entry.last_beat_idx; ++i) {
        if (!entry.beat_statuses[i].read) {
            all_read = false;
            break;
        }
    }
    // printf("RROB: Marked beat %d as read for tag %d (AXI ID %d). All read: %s\n",
    //         beat_idx, tag, axi_id, all_read ? "true" : "false");
    if (all_read) {
        if (entry.contains_last || (entry.need_next_entry && nextEntry.contains_last))
            numAxiReads--;

        // Remove entry from the list
        // printf("RROB: All beats read for tag %d, removing entry\n", tag);
        axiListManager.removeEntry(axi_id, tag); // This also removes the front entry from the list

        // axiListManager.removeEntry(axi_id, tag); // This also removes the front entry from the list
    }
}

void AxiListManager::removeEntry(AxiID axi_id, Tag tag) {
    // Find the iterator for the given tag
    auto it = tagToIterator.find(tag);
    if (it == tagToIterator.end()) {
        panic("RROB: Tag %d not found in tagToIterator map", tag);
    }

    // Verify AXI ID match
    auto axiIt = tagToAxiID.find(tag);
    if (axiIt == tagToAxiID.end() || axiIt->second != axi_id) {
        panic("RROB: AXI ID mismatch for tag %d: expected %u, got %u", tag, axi_id, axiIt->second);
    }

    AxiList& list = lists[axi_id];
    auto entryIt = it->second;

    // Potentially remove the next entry too
    if (entryIt->need_next_entry) {
        auto nextIt = std::next(entryIt);
        if (nextIt != list.end()) {
            // Search for tag associated with nextIt
            std::optional<Tag> nextTag;
            for (auto& pair : tagToIterator) {
                if (pair.second == nextIt) {
                    nextTag = pair.first;
                    break;
                }
            }

            if (nextTag.has_value()) {
                tagToIterator.erase(nextTag.value());
                tagToAxiID.erase(nextTag.value());
            } else {
                panic("RROB: Could not find tag for second half of multi-entry read (AXI ID %u)", axi_id);
            }

            list.erase(nextIt);
            numEntries--;
        } else {
            panic("RROB: Entry with tag %u required next entry, but none found", tag);
        }
    }


    // Remove main entry
    list.erase(entryIt);
    tagToIterator.erase(tag);
    tagToAxiID.erase(tag);
    numEntries--;

    // Clean up the list if it's empty
    if (list.empty()) {
        lists.erase(axi_id);
    }
}

void
AxiListManager::rebuildTagMaps()
{
    tagToIterator.clear();
    tagToAxiID.clear();
    for (auto &kv : lists) {
        const AxiID aid = kv.first;
        for (auto it = kv.second.begin(); it != kv.second.end(); ++it) {
            tagToIterator[it->tag] = it;
            tagToAxiID[it->tag] = aid;
        }
    }
}

namespace {

static void
serializeBeatStatus(CheckpointOut &cp, const beatStatus &b)
{
    ::gem5::paramOut(cp, "valid", b.valid);
    ::gem5::paramOut(cp, "read", b.read);
    ::gem5::paramOut(cp, "sent", b.sent);
}

static void
unserializeBeatStatus(CheckpointIn &cp, beatStatus &b)
{
    ::gem5::paramIn(cp, "valid", b.valid);
    ::gem5::paramIn(cp, "read", b.read);
    ::gem5::paramIn(cp, "sent", b.sent);
}

static void
serializeRROBEntry(CheckpointOut &cp, const RROBEntry &e)
{
    ::gem5::paramOut(cp, "tag", e.tag);
    ::gem5::paramOut(cp, "axi_id", (uint64_t)e.axi_id);
    ::gem5::paramOut(cp, "beat_size", (uint64_t)e.beat_size);
    ::gem5::paramOut(cp, "entry_size", (uint64_t)e.entry_size);
    ::gem5::paramOut(cp, "filled_flits", (uint64_t)e.filled_flits);
    ::gem5::paramOut(cp, "flitWrittenSize", (uint64_t)e.flit_written.size());
    for (size_t i = 0; i < e.flit_written.size(); i++) {
        const bool flit_written = e.flit_written[i];
        ::gem5::paramOut(cp, csprintf("flit_written%u", (unsigned)i),
                         flit_written);
    }
    ::gem5::arrayParamOut(cp, "data", e.data.data(), e.data.size());
    ::gem5::paramOut(cp, "need_next_entry", e.need_next_entry);
    ::gem5::paramOut(cp, "contains_last", e.contains_last);
    ::gem5::paramOut(cp, "last_beat_idx", (uint64_t)e.last_beat_idx);
    ::gem5::paramOut(cp, "vnet", e.vnet);
    ::gem5::paramOut(cp, "beatStatusesSize", (uint64_t)e.beat_statuses.size());
    for (size_t i = 0; i < e.beat_statuses.size(); i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("bs%u", (unsigned)i));
        serializeBeatStatus(cp, e.beat_statuses[i]);
    }
}

static RROBEntry
unserializeRROBEntry(CheckpointIn &cp)
{
    int tag = 0;
    uint64_t tmp = 0;
    uint8_t axi_id = 0;
    uint8_t beat_size = 0;
    size_t entry_size = 0;
    uint8_t last_beat_idx = 0;
    bool need_next_entry = false;
    bool contains_last = false;
    int vnet = 0;

    ::gem5::paramIn(cp, "tag", tag);
    ::gem5::paramIn(cp, "axi_id", tmp);
    axi_id = (uint8_t)tmp;
    ::gem5::paramIn(cp, "beat_size", tmp);
    beat_size = (uint8_t)tmp;
    ::gem5::paramIn(cp, "entry_size", tmp);
    entry_size = (size_t)tmp;
    ::gem5::paramIn(cp, "filled_flits", tmp);
    const size_t filled_flits = (size_t)tmp;

    uint64_t fws = 0;
    ::gem5::paramIn(cp, "flitWrittenSize", fws);
    std::vector<bool> flit_written(fws, false);
    for (size_t i = 0; i < flit_written.size(); i++) {
        bool fw = false;
        ::gem5::paramIn(cp, csprintf("flit_written%u", (unsigned)i), fw);
        flit_written[i] = fw;
    }

    std::vector<uint8_t> data(entry_size, 0);
    ::gem5::arrayParamIn(cp, "data", data.data(), data.size());

    ::gem5::paramIn(cp, "need_next_entry", need_next_entry);
    ::gem5::paramIn(cp, "contains_last", contains_last);
    ::gem5::paramIn(cp, "last_beat_idx", tmp);
    last_beat_idx = (uint8_t)tmp;
    ::gem5::paramIn(cp, "vnet", vnet);

    RROBEntry e(axi_id, beat_size, entry_size, need_next_entry, contains_last,
                last_beat_idx, tag, vnet);
    e.filled_flits = filled_flits;
    e.flit_written = flit_written;
    e.data = data;

    uint64_t bss = 0;
    ::gem5::paramIn(cp, "beatStatusesSize", bss);
    fatal_if(bss != e.beat_statuses.size(),
             "RROB checkpoint beat_statuses size mismatch for tag %d", tag);
    for (size_t i = 0; i < e.beat_statuses.size(); i++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("bs%u", (unsigned)i));
        unserializeBeatStatus(cp, e.beat_statuses[i]);
    }
    return e;
}

} // namespace

void
AxiListManager::serialize(CheckpointOut &cp) const
{
    ::gem5::paramOut(cp, "nextTag", (uint64_t)nextTag);
    ::gem5::paramOut(cp, "numEntries", numEntries);
    ::gem5::paramOut(cp, "m_max_entries", (uint64_t)m_max_entries);
    ::gem5::paramOut(cp, "m_entry_size", (uint64_t)m_entry_size);
    ::gem5::paramOut(cp, "rr_scan_axi_key", rr_scan_axi_key);

    std::vector<AxiID> sorted_keys;
    sorted_keys.reserve(lists.size());
    for (const auto &p : lists)
        sorted_keys.push_back(p.first);
    std::sort(sorted_keys.begin(), sorted_keys.end());

    ::gem5::paramOut(cp, "numLists", (uint64_t)sorted_keys.size());
    for (size_t li = 0; li < sorted_keys.size(); li++) {
        const AxiID aid = sorted_keys[li];
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("list%u", (unsigned)li));
        ::gem5::paramOut(cp, "axiId", (uint64_t)aid);
        const AxiList &lst = lists.at(aid);
        ::gem5::paramOut(cp, "listSize", (uint64_t)lst.size());
        size_t ei = 0;
        for (const auto &ent : lst) {
            Serializable::ScopedCheckpointSection sec2(
                cp, csprintf("ent%u", (unsigned)ei++));
            serializeRROBEntry(cp, ent);
        }
    }
}

void
AxiListManager::unserialize(CheckpointIn &cp)
{
    lists.clear();
    tagToIterator.clear();
    tagToAxiID.clear();

    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "nextTag", tmp);
    nextTag = (Tag)tmp;
    ::gem5::paramIn(cp, "numEntries", numEntries);
    ::gem5::paramIn(cp, "m_max_entries", tmp);
    m_max_entries = (size_t)tmp;
    ::gem5::paramIn(cp, "m_entry_size", tmp);
    m_entry_size = (size_t)tmp;
    ::gem5::paramIn(cp, "rr_scan_axi_key", rr_scan_axi_key);

    uint64_t nl = 0;
    ::gem5::paramIn(cp, "numLists", nl);
    for (size_t li = 0; li < nl; li++) {
        Serializable::ScopedCheckpointSection sec(
            cp, csprintf("list%u", (unsigned)li));
        uint64_t aid_u = 0;
        ::gem5::paramIn(cp, "axiId", aid_u);
        const AxiID aid = (AxiID)aid_u;
        uint64_t ls = 0;
        ::gem5::paramIn(cp, "listSize", ls);
        for (size_t j = 0; j < ls; j++) {
            Serializable::ScopedCheckpointSection sec2(
                cp, csprintf("ent%u", (unsigned)j));
            lists[aid].push_back(unserializeRROBEntry(cp));
        }
    }

    rebuildTagMaps();

    int sum = 0;
    for (const auto &p : lists)
        sum += (int)p.second.size();
    fatal_if(sum != numEntries,
             "RROB AxiListManager::unserialize numEntries mismatch");
}

void
ReadReorderBuffer::serialize(CheckpointOut &cp) const
{
    SimObject::serialize(cp);
    ::gem5::paramOut(cp, "m_max_entries", m_max_entries);
    ::gem5::paramOut(cp, "m_entry_size", m_entry_size);
    ::gem5::paramOut(cp, "numAxiReads", (uint64_t)numAxiReads);
    {
        Serializable::ScopedCheckpointSection sec(cp, "axiListManager");
        axiListManager.serialize(cp);
    }
}

void
ReadReorderBuffer::unserialize(CheckpointIn &cp)
{
    SimObject::unserialize(cp);
    uint64_t tmp = 0;
    ::gem5::paramIn(cp, "m_max_entries", tmp);
    m_max_entries = (uint16_t)tmp;
    ::gem5::paramIn(cp, "m_entry_size", tmp);
    m_entry_size = (uint16_t)tmp;
    ::gem5::paramIn(cp, "numAxiReads", tmp);
    numAxiReads = (uint8_t)tmp;
    {
        Serializable::ScopedCheckpointSection sec(cp, "axiListManager");
        axiListManager.unserialize(cp);
    }
}

}
}
}
