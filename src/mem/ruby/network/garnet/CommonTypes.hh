/*
 * Copyright (c) 2008 Princeton University
 * Copyright (c) 2016 Georgia Institute of Technology
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */


#ifndef __MEM_RUBY_NETWORK_GARNET_0_COMMONTYPES_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_COMMONTYPES_HH__

#include "mem/ruby/common/NetDest.hh"
#include "noc/core/network/NocNetDest.hh"

namespace gem5
{
namespace noc
{
namespace garnet
{
    const int AR_VNET = 2;
    const int R_VNET = 2;
    const int AW_VNET = 3;
    const int B_VNET = 3;
    const int W_VNET = 4;

    struct NocRouteInfo
    {
        NocRouteInfo()
            : vnet(0), src_ni(0), src_router(0), dest_ni(0), dest_router(0),
            hops_traversed(0)
        {}

        // destination format for table-based routing
        int vnet;
        NocNetDest net_dest;

        // src and dest format for topology-specific routing
        int src_ni;
        int src_router;
        int dest_ni;
        int dest_router;
        int hops_traversed;
    };
    enum class Nps_Type
    {
        VNOC,   // Vertical NoC
        HNOC,   // Horizontal NoC
        RPTR,   // Repeater
        NCRB,
        NIDB,
        INVALID // Invalid/Uninitialized type
    };

    // Helper function to convert enum to string (useful for debugging)
    static inline std::string NpsTypeToString(Nps_Type type) {
        switch(type) {
            case Nps_Type::VNOC: return "VNOC";
            case Nps_Type::HNOC: return "HNOC";
            case Nps_Type::RPTR: return "RPTR";
            case Nps_Type::NCRB: return "NCRB";
            case Nps_Type::NIDB: return "NIDB";
            default: return "INVALID";
        }
    }

    struct NocRouteMapKey {
        int src_id;
        int dst_id;
        int vc;

         bool operator==(const NocRouteMapKey& other) const {
             return src_id == other.src_id &&
                    dst_id == other.dst_id &&
                    vc == other.vc;
         }

        bool operator<(const NocRouteMapKey& other) const {
            if (src_id != other.src_id) return src_id < other.src_id;
            if (dst_id != other.dst_id) return dst_id < other.dst_id;
            return vc < other.vc;
        }
      };
}
}
}
namespace gem5
{

namespace ruby
{

namespace garnet
{

// All common enums and typedefs go here

enum flit_type {HEAD_, BODY_, TAIL_, HEAD_TAIL_,
                CREDIT_, NUM_FLIT_TYPE_};
enum axi_flit_type {AXI_HEAD_, AXI_TAIL_, AXI_BODY_, AXI_HEAD_TAIL_};
enum VC_state_type {IDLE_, VC_AB_, ACTIVE_, NUM_VC_STATE_TYPE_};
enum VNET_type {CTRL_VNET_, DATA_VNET_, NULL_VNET_, NUM_VNET_TYPE_};
enum flit_stage {I_, VA_, SA_, ST_, LT_, NUM_FLIT_STAGE_};
enum link_type { EXT_IN_, EXT_OUT_, INT_, NUM_LINK_TYPES_ };
enum RoutingAlgorithm { TABLE_ = 0, XY_ = 1, CUSTOM_ = 2,
                        NUM_ROUTING_ALGORITHM_};

struct RouteInfo
{
    RouteInfo()
        : vnet(0), src_ni(0), src_router(0), dest_ni(0), dest_router(0),
          hops_traversed(0)
    {}

    // destination format for table-based routing
    int vnet;
    NetDest net_dest;

    // src and dest format for topology-specific routing
    int src_ni;
    int src_router;
    int dest_ni;
    int dest_router;
    int hops_traversed;
};



#define INFINITE_ 10000

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif //__MEM_RUBY_NETWORK_GARNET_0_COMMONTYPES_HH__
