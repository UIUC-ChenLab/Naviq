#ifndef __TILE_HH
#define __TILE_HH

#include "params/tile.hh"
#include "noc/core/interface/NocInterface.hh"
#include "noc/endpoints/NocNode.hh"

#include <deque>

//generates traffic

//acts in place of src/cpu/testers/garnet_synthetic_traffic/GarnetSyntheticTraffic.hh

namespace gem5
{
namespace noc{


class tile : public NocNode
{
    public:
        typedef tileParams Params;
        tile(const Params &p);

        //main simulation loop (1 cycle)
        bool tick(int clockDomain) override;
        bool done() { return (writes_done && reads_done); }
        void update(int portID, State* inputNocInterfaceState) override;
        State* getCurrentState(int portID) override;
        int assignPort(const std::string &endpointName) override;

        void updateMTile(aximmSlaveState TileControllerState);
        

        uint32_t next_read_axi_id = 0;
        uint32_t next_write_axi_id = 0;


    private:
        NocInterface* tileController;

        Tick simCycles;

        aximmMasterState currentState;
        aximmMasterState nextState;
        aximmSlaveState tileControllerState;

        // store read responses from NMU to be processed
        std::deque<aximmRWData> readResponses;

        // store read requests that are ready to send over NoC
        std::deque<aximmRWAddr> readRequests;
        std::deque<aximmRWAddr> writeRequests;
        std::deque<aximmRWData> writeData;

        void generateNextReadRequest();
        void generateNextWriteRequest();
        void generateNextWriteData(uint8_t len, uint8_t size);
        void printReadResponse();

        bool interleaved;
        bool do_reads;
        bool do_writes;
        bool reads_done;
        bool writes_done;

        int num_reads;
        int read_size;
        int read_length;
        int readMsgCount;
        int writeMsgCount;
        int RW_state;

        std::vector<uint64_t> addr_options;
        int num_dest;
        int current_write_dest;
        int current_read_dest;
        int bandwidth;
        int clk_period;

        Tick w_period_ps;
        Tick next_write_time;

        bool portAssigned;
};
}
}

#endif
