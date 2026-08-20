#include "mem/packet.hh"
#include <iostream>
#include "cpu/testers/garnet_synthetic_traffic/tester.hh"

namespace gem5{
    void tester::printPacketData(PacketPtr pkt){

        std::cout<<"packet id: "<<pkt->id<<std::endl;
        std::cout<<" cmd string: "<<pkt->cmdString()<<std::endl;
        std::cout<<" size: "<<pkt->getSize()<<std::endl;

    }
}
