#include "noc/endpoints/legacy/tile.hh"


#include "noc/core/network/NocMemoryMsg.hh"
#include "sim/sim_events.hh"
#include "sim/sim_exit.hh"
#include "mem/ruby/protocol/MessageSizeType.hh"
#include "base/logging.hh"
#include "debug/NocTiming.hh"
#include "debug/NocControl.hh"

#include <cstdio>
#include <iostream>

namespace gem5{

namespace noc{


tile::tile(const Params &p) : NocNode(p),
    tileController(p.tile_controller),
    simCycles(p.sim_cycles),
    interleaved(p.interleaved),
    do_reads(p.do_reads),
    do_writes(p.do_writes),
    num_reads(p.num_reads),
    read_size(p.read_size),
    read_length(p.read_length),
    readMsgCount(0),
    writeMsgCount(0),
    addr_options(p.addr_options),
    current_write_dest(0),
    current_read_dest(0),
    bandwidth(p.bandwidth),
    clk_period(p.clk_period)
{
    maxPorts = 1;
    RW_state = do_writes ? 0 : 2;
    num_dest = addr_options.size()/2;

    reads_done = (do_reads ? false : true);
    writes_done = (do_writes ? false : true);

    // double bandwidth = 300;
    double total_bytes = (read_length + 1) * (1 << read_size);
    // double clk_period = 1000;//1 ns is 1000 ps
    w_period_ps = (Tick)  (total_bytes*1000*clk_period / bandwidth) ;
    next_write_time = Tick(0);
    portAssigned = false;
}



bool tile::tick(int clockDomain){
    if (clockDomain != clockDomains[0])
        return false;

    DPRINTF(NocControl, "[Tile] tick @ %llu RW_state=%d reads_done=%d writes_done=%d "
                "readReq=%zu writeReq=%zu writeData=%zu\n",
                (unsigned long long)curTick(),
                RW_state,
                (int)reads_done, (int)writes_done,
                readRequests.size(), writeRequests.size(), writeData.size());

    // if a read response is received, buffer it
    if (currentState.rReady && tileControllerState.r.valid){
        readResponses.push_back(tileControllerState.r);
        if (tileControllerState.r.last) {
            DPRINTF(NocTiming, "Tile received last read beat, read resp num %d\n", readMsgCount);
            RW_state = do_writes ? 0 : 2;
            if (readMsgCount == num_reads)
                reads_done = true;
        }
    }
    if (currentState.bReady && tileControllerState.b.valid){
        DPRINTF(NocTiming, "Tile received write response, write resp num %d\n",writeMsgCount);
        if (RW_state ==1) RW_state = do_reads ? 2 : 0;
        if (writeMsgCount == num_reads)
            writes_done = true;
    }

    generateNextReadRequest();
    generateNextWriteRequest();
    printReadResponse();



    currentState = nextState;
    return true;
}

void tile::update(int portID, State* inputNocInterfaceState)
{
    if (portID != 0)
        panic("tile::update invalid portID %d", portID);
    auto* slaveState = dynamic_cast<aximmSlaveState*>(inputNocInterfaceState);
    if (!slaveState) {
        panic("tile::update expected aximmSlaveState");
    }
    updateMTile(*slaveState);
}

State*
tile::getCurrentState(int portID)
{
    if (portID != 0)
        panic("tile::getCurrentState invalid portID %d", portID);
    return &currentState;
}

int
tile::assignPort(const std::string &endpointName)
{
    if (endpointName == portEndpointNames[0] && !portAssigned) {
        portAssigned = true;
        return 0;
    }
    panic("tile::assignPort invalid endpointName: %s",
          endpointName.c_str());
}

void tile::updateMTile(aximmSlaveState TileControllerState)
{
    auto updateState = [](auto& queue, auto& cur, auto& next, bool ready) {
        using T = std::decay_t<decltype(cur)>;  // figure out the correct type (aximmRWAddr or aximmRWData)

        // if NSU/tile controller accepting request this cycle, dequeue it and set next
        if (ready && cur.valid) {
            queue.pop_front();
            if (!queue.empty()) {
                next = queue.front();
            } else {
                next = T{};
                next.valid = false;
            }
        } else if (!cur.valid) {
        // no valid request this cycle, get one if there is one for next cycle
            if (!queue.empty()) {
                next = queue.front();
            } else {
                next = T{};
                next.valid = false;
            }
        } else {
        // slave (tile controller) wasn't ready, but current state was valid, maintain state
            next = cur;
        }
    };

    updateState(readRequests, currentState.ar, nextState.ar, TileControllerState.arReady);
    updateState(writeRequests, currentState.aw, nextState.aw, TileControllerState.awReady);
    updateState(writeData, currentState.w, nextState.w, TileControllerState.wReady);

    nextState.rReady = true;
    nextState.bReady = true;

    this->tileControllerState = TileControllerState;
    currentState = nextState;

}

void tile::generateNextReadRequest() {

    // for now just send 1 request
    if (do_reads){
        if ((interleaved && RW_state==2) || !interleaved){
            if(readMsgCount < num_reads){
                aximmRWAddr payload;
                payload.addr = addr_options[current_read_dest*2];
                payload.cmd = AximmCommand::READ;
                payload.len=read_length;
                payload.size=read_size;
                payload.valid = true;
                payload.id = 0;
                // payload.id = next_read_axi_id%4;

                // printf("Generating message %d, Number of reads = %d, Read Size = %d, Read length = %d\n", readMsgCount, num_reads,read_size, read_length);
                DPRINTF(NocTiming, "Tile pushing generated msg onto readRequests queue, will be send out on next clock cycle.\n");
                readRequests.push_back(payload);
                current_read_dest++;
                next_read_axi_id++;

                if (current_read_dest == num_dest){
                    readMsgCount++;
                    current_read_dest = 0;
                }
                RW_state = 3;


            }
        }
    }
}

void tile::generateNextWriteRequest() {

    // for now just send 1 request
    aximmRWAddr payload;

    payload.addr = addr_options[current_write_dest*2];
    payload.cmd = AximmCommand::WRITE;
    payload.len=read_length;
    payload.size=read_size;
    payload.valid = true;
    payload.id = 0;
    // payload.id = next_write_axi_id%4;

    // printf("write data empty? %ld, state %d, dest %d\n", writeData.size(), RW_state, current_write_dest);
    if (do_writes && writeData.empty()) {
        if ((interleaved && RW_state==0) || !interleaved){
            if(writeMsgCount < num_reads){
                if (curTick()>= next_write_time){

                    writeRequests.push_back(payload);
                    next_write_axi_id++;
                    generateNextWriteData(payload.len, payload.size);
                    current_write_dest++;
                    if (current_write_dest == num_dest){
                        writeMsgCount++;
                        current_write_dest = 0;
                    }
                    RW_state = 1;
                    next_write_time = curTick() + w_period_ps;

                // printf("generating write req to addr %lu \n", payload.addr);
                // printf("  with data: \n");
                // for (int i=0; i<(payload.len + 1); i++){
                //     for (int j=0; j<(1<<payload.size); j++){
                //         if (j%8 == 0)
                //             printf("\n");
                //         printf(" %d ", writeData[i].data[j]);
                //     }
                // }
                }
            }
        }
    }

}

void tile::generateNextWriteData(uint8_t len, uint8_t size) {

    aximmRWData payload;
    uint16_t numBytes = (1 << size);
    std::array<uint8_t, 64> data;
    payload.cmd = AximmCommand::WRITE;
    payload.id = 0;
    // payload.id = next_write_axi_id %4;
    payload.valid = true;

    for (int i=0; i<(len+1); i++){
        for (int j=0; j<numBytes; j++){
            data[j] = j;
        }
        payload.data = data;
        if (i == len)
            payload.last = true;
        else
            payload.last = false;

        writeData.push_back(payload);
    }
}

void
tile::printReadResponse(){

    // dequeue any read response received and print to screen
    aximmRWData resp;

    if(!readResponses.empty()){
        resp = readResponses.front();
        readResponses.pop_front();
        // printf("in tile::tick, dequeued msg from the response buffer \n");
        // printf("got read response beat with data: \n");
        // for (int i=0; i<64; i++){ // just print 64 bytes, largest response possible
        //     if (i%8==0)
        //         printf("\n");
        //     printf("%d ", resp.data[i]);
        // }
    }

}


}
}


//./build/NULL/gem5.debug --debug-flags=GarnetSyntheticTraffic src/noc/noc_config.py

//./build/NULL/gem5.debug --debug-flags=GarnetSyntheticTraffic configs/example/garnet_synth_traffic.py --num-cpus=4 --num-dirs=4 --network=garnet --topology=Mesh_XY --mesh-rows=2 --sim-cycles=100000 --synthetic=uniform_random --injectionrate=0.01
