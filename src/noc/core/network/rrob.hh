#ifndef __rrob_hh__
#define __rrob_hh__

#include <algorithm>
#include <array>
#include <unordered_map>
#include <list>
#include <iostream>
#include <cstdint>
#include <algorithm>

using AxiID = uint8_t;  // or whatever type your AXI ID is

// Alias for the linked list associated with an AXI ID
using AxiList = std::list<int>;

#include <unordered_map>
#include <list>
#include <cstdint>
#include <iterator>
#include <vector>

#include "base/logging.hh"
#include "sim/clocked_object.hh"
#include "sim/serialize.hh"
#include "params/rrob.hh"
#include "noc/lib/network/NocMessage.hh"
#include "noc/core/network/NocMemoryMsg.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"


namespace gem5{
    namespace ruby{
        namespace garnet{
            template <typename T_Msg, typename T_RouteInfo>
            class flit;
        }
    }
}


namespace gem5{
namespace noc{
namespace garnet{
    static constexpr size_t FLIT_SIZE = 16;            // Size of each flit in bytes.

    struct beatStatus{
        bool valid; // does this beat have data in data array?
        bool read;  // has this beat been read out yet? need to know for freeing up RROB entry
        bool sent;  // has this beat been translated to axi NocMemoryMsg and sent out buffer

        beatStatus() : valid(false), read(false), sent(false) {}
    };

    struct RROBEntry {

        int tag; // Unique tag for this entry.
        uint8_t axi_id;                                     // AXI ID associated with this entry.
        uint8_t beat_size;                                  // Size of the beat (in bytes) of the corresponding read request
                                                            // so we know how much data
                                                            // to read out of the entry
        size_t entry_size;                                  // Total size of an entry in bytes.
        size_t filled_flits;                              // Count of flits that have been written.
        std::vector<bool> flit_written;                    // Flags indicating which flits have been written.
        std::vector<uint8_t> data;                         // Buffer to hold the data for this entry.
        bool need_next_entry; // only in case of a 64-byte beat, need next entry to be filled out before we can read
        std::vector<beatStatus> beat_statuses;
        bool contains_last; //this rrob entry contains the last beat of an axi read burst
        uint8_t last_beat_idx; // only valid if contains_last
        int vnet; //vnet request came in on. must be sure response uses same

        RROBEntry(uint8_t axi, uint8_t beat_size, size_t entry_size,
                    bool need_next_entry, bool contains_last,
                    uint8_t last_beat_idx, int tag, int vnet)
        : tag(tag), axi_id(axi), beat_size(beat_size), entry_size(entry_size),
            filled_flits(0), flit_written(entry_size / FLIT_SIZE, false),
            data(entry_size, 0), need_next_entry(need_next_entry),
            contains_last(contains_last), last_beat_idx(last_beat_idx), vnet(vnet)
        {
            if (beat_size < entry_size)
                beat_statuses.resize(entry_size / beat_size, beatStatus());
            else
                beat_statuses.resize(1, beatStatus());
        }

        RROBEntry(): tag(-1), beat_size(0), entry_size(0), filled_flits(0),
            need_next_entry(false), contains_last(false), last_beat_idx(0),
            vnet(0) {

            beat_statuses.resize(1, beatStatus());
        }

        void markBeatsValid(size_t flit_index){
            if (beat_size >= entry_size) {
                if (filled_flits == flit_written.size())
                    beat_statuses[0].valid = true;
                return;
            }

            const size_t byte_start = flit_index * FLIT_SIZE;
            const size_t byte_end = std::min(byte_start + FLIT_SIZE, entry_size);
            for (size_t i = 0; i < beat_statuses.size(); i++) {
                const size_t beat_start = i * beat_size;
                const size_t beat_end = std::min(beat_start + beat_size,
                                                 entry_size);
                if (byte_end <= beat_start || byte_start >= beat_end)
                    continue;

                const size_t first_flit = beat_start / FLIT_SIZE;
                const size_t last_flit = (beat_end - 1) / FLIT_SIZE;
                bool all_written = true;
                for (size_t f = first_flit; f <= last_flit; f++) {
                    all_written &= flit_written[f];
                }
                if (all_written)
                    beat_statuses[i].valid = true;
            }
        }
    };

    using AxiID = uint8_t;
    using ValueType = RROBEntry;

    class AxiListManager {
    public:
        using AxiList = std::list<ValueType>;
        using Iterator = AxiList::iterator;
        using Tag = uint8_t; // Unique tag type

        // Constructor initializes the tag counter with configurable max entries
        AxiListManager(size_t max_entries = 64, size_t entry_size = 32)
            : nextTag(1), numEntries(0), m_max_entries(max_entries),
              m_entry_size(entry_size), rr_scan_axi_key(-1)
        {}

        void serialize(CheckpointOut &cp) const;
        void unserialize(CheckpointIn &cp);
        
        int getNumEntries() const {
            return numEntries;
        }

        void removeEntry(AxiID axi_id, Tag tag);

        // Add a value for the given axi_id and return a unique tag.
        Tag addEntry(AxiID axi_id, uint8_t beat_size, bool contains_last, uint8_t last_beat_idx, int vnet, bool need_next_entry = false) {

            if (numEntries >= m_max_entries) {
                // no room for more entries
                return -1; // or handle error appropriately
            }

            // Generate a unique tag.
            Tag tag = nextTag++;

            // Access or create the list associated with this axi_id.
            AxiList& list = lists[axi_id];
            list.push_back(RROBEntry(axi_id, beat_size, m_entry_size,
                                     need_next_entry, contains_last,
                                     last_beat_idx, tag, vnet));
            Iterator it = std::prev(list.end());

            // Map the tag to the iterator.
            tagToIterator[tag] = it;
            // Optionally store the axi_id if needed for later lookups.
            tagToAxiID[tag] = axi_id;

            numEntries++;
            return tag;
        }

        int getVnet(AxiID axi_id, Tag tag){
            auto list_it = lists.find(axi_id);
            if (list_it == lists.end()) {
                panic("getVnet: No entries found for AXI ID %d\n", axi_id);
            }

            AxiList& list = list_it->second;
            for (auto& entry : list) {
                if (entry.tag == tag) {
                    return entry.vnet;
                }
            }

            panic("getVnet: Tag %d not found under AXI ID %d\n", tag, axi_id);
        }

        void writeFlitEntry(Tag tag, std::array<uint8_t, 16>* data, int flit_idx){
            auto it = tagToIterator.find(tag);
            if (it != tagToIterator.end()) {
                RROBEntry& entry = *(it->second);

                size_t flitIndex = flit_idx;
                if (flitIndex < entry.flit_written.size()) {
                    std::copy(data->begin(), data->end(), entry.data.begin() + flitIndex * FLIT_SIZE);
                    entry.flit_written[flitIndex] = true;
                    entry.filled_flits++;
                    entry.markBeatsValid(flitIndex);
                } else {
                    std::cerr << "Error: Attempting to write beyond the entry size." << std::endl;
                }
            } else {
                std::cerr << "Error: Tag not found." << std::endl;
            }
        }

        RROBEntry readEntry(AxiID axi_id) {
            auto it = lists.find(axi_id);
            if (it == lists.end() || it->second.empty())
                panic("no entry to read from RROB");

            AxiList& list = it->second;
            RROBEntry entry = list.front();
            list.pop_front();
            numEntries--;

            return entry;
        }

        // Retrieve an iterator given a unique tag.
        // Returns nullptr if the tag is not found.
        Iterator getIterator(Tag tag) {
            auto it = tagToIterator.find(tag);
            if (it != tagToIterator.end())
                return it->second;
            return AxiList().end();  // or handle error appropriately
        }

        AxiList& getList(AxiID axi_id){
            auto it = lists.find(axi_id);
            if (it == lists.end())
                panic("AxiListManager::getList: No list exists for AxiID %d", axi_id);

            return it->second;
        }

        // Update the value at the given tag.
        bool updateValue(Tag tag, ValueType newValue) {
            auto it = tagToIterator.find(tag);
            if (it != tagToIterator.end()) {
                *(it->second) = newValue;
                return true;
            }
            return false;
        }

        AxiID getAxiID(Tag tag) {
            auto it = tagToAxiID.find(tag);
            if (it != tagToAxiID.end())
                return it->second;
            panic("AxiListManager Get Axi ID could not find tag %d\n", tag);
            return -1; // or handle error appropriately
        }

        std::vector<MsgPtr> generateAxiReadPayloads(AxiID axi_id, Tick curTime);

        int16_t getNextReadyAxiID()
        {
            if (lists.empty()) {
                rr_scan_axi_key = -1;
                return -1;
            }

            std::vector<AxiID> keys;
            keys.reserve(lists.size());
            for (const auto &p : lists) {
                keys.push_back(p.first);
            }
            std::sort(keys.begin(), keys.end());

            if (rr_scan_axi_key < 0 ||
                std::find(keys.begin(), keys.end(), (AxiID)rr_scan_axi_key) ==
                    keys.end()) {
                rr_scan_axi_key = keys[0];
            }

            auto lit = lists.find((AxiID)rr_scan_axi_key);
            panic_if(lit == lists.end(),
                "RROB: rr_scan_axi_key %d not in lists", rr_scan_axi_key);

            bool listHasReadyEntry = false;
            const AxiID axiID = lit->first;

            if (!lit->second.empty()) {
                RROBEntry &headEntry = lit->second.front();
                if (headEntry.filled_flits == headEntry.flit_written.size() &&
                    !headEntry.need_next_entry) {
                    listHasReadyEntry = true;
                } else if (headEntry.filled_flits ==
                               headEntry.flit_written.size() &&
                           headEntry.need_next_entry) {
                    if (lit->second.size() > 1) {
                        RROBEntry &nextEntry = *(++lit->second.begin());
                        if (nextEntry.filled_flits ==
                            nextEntry.flit_written.size()) {
                            listHasReadyEntry = true;
                        }
                    }
                }
            }

            auto kit =
                std::find(keys.begin(), keys.end(), (AxiID)rr_scan_axi_key);
            panic_if(kit == keys.end(),
                "RROB: rr_scan_axi_key missing from sorted keys");
            ++kit;
            if (kit == keys.end()) {
                kit = keys.begin();
            }
            rr_scan_axi_key = *kit;

            if (listHasReadyEntry) {
                return axiID;
            }
            return -1;
        }

    private:
        void rebuildTagMaps();

        // Map from AXI ID to its dynamic list of values.
        std::unordered_map<AxiID, AxiList> lists;
        // Map from unique tag to iterator.
        std::unordered_map<Tag, Iterator> tagToIterator;
        // Optional: map from tag to axi_id if you need to associate the tag with its originating list.
        std::unordered_map<Tag, AxiID> tagToAxiID;
        // A counter to generate unique tags.
        Tag nextTag;

        int numEntries;
        size_t m_max_entries;  // Configurable max entries
        size_t m_entry_size;   // Configurable bytes per entry

        /** Current AXI ID bucket for getNextReadyAxiID round-robin (-1 = unset). */
        int rr_scan_axi_key;
    };


class ReadReorderBuffer : public SimObject {
public:
    typedef rrobParams Params;
    ReadReorderBuffer(const Params &p);

    // Reserve one RROB entry for a given AXI read.
    // This function may be called multiple times for a single AXI read request.
    // It returns a unique tag for the reserved slot.
    // If there is no available slot, -1 is returned.
    int reserve(uint8_t axi_id, uint8_t beat_size, bool contains_last, uint8_t last_beat_idx, int vnet, bool need_next_entry);

    // Read out the fully reassembled AXI response.
    std::vector<uint8_t> read(uint8_t axi_id);

    void writeFlit(int tag, std::array<uint8_t, 16>* data, int flit_idx);

    uint16_t getNumRemainingEntries() {return m_max_entries - axiListManager.getNumEntries();}
    uint16_t getMaxEntries() const { return m_max_entries; }
    uint16_t getEntrySizeBytes() const { return m_entry_size; }

    std::vector<MsgPtr> generateAxiReadPayloads(AxiID axi_id, Tick curTime);

    void markBeatRead(uint8_t axi_id, int tag, uint8_t beat_idx);

    int getVnet(AxiID axi_id, int tag){return axiListManager.getVnet(axi_id, tag);}

    // Register a callback that is invoked when read data is written to a rrob entry
    // The callback receives the axi_id.
    void setWakeupHandler(std::function<void(AxiID)> cb) {
        wakeup_handler = std::move(cb);
    }

    void incrementNumAxiReads(){numAxiReads++;}
    uint8_t getNumAxiReads(){return numAxiReads;}

    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;

private:
    AxiListManager axiListManager;
    uint16_t m_max_entries;  // Configurable max RROB entries
    uint16_t m_entry_size;   // Configurable bytes per RROB entry

    std::function<void(uint8_t)> wakeup_handler;

    uint8_t numAxiReads; // number of original axi read requests with data in this buffer
};

} // namespace garnet
} // namespace noc
} // namespace gem5

#endif
