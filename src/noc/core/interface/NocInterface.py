# copied and modified from build/NULL/mem/ruby/protocol/MI_example/MI_example_L1Cache_Controller.py

from m5.objects.NocMessageBuffer import NocMessageBuffer
from m5.params import *
from m5.objects.ClockedObject import ClockedObject
from m5.SimObject import SimObject
from m5.proxy import *

# Depth of each NocInterface <-> NI MessageBuffer. The CDC fifo in
# AXISHandler / AXIMMHandler stays at 8; this queue must be >= the largest
# atomic batch from depacketize (e.g. sNocSlaveUnit can emit many NocStreamMsg
# per net flit when S_DATA_WIDTH is narrow). 8 is too small and can deadlock
# or corrupt state when areNSlotsAvailable(Msgs.size()) never succeeds.
_NOC_IF_PROTOCOL_QUEUE_DEPTH = 32


class NocInterface(ClockedObject):
    type = "NocInterface"
    cxx_header = "noc/core/interface/NocInterface.hh"
    cxx_class = "gem5::noc::NocInterface"


    id = Param.Int(0, "id of the tile controller")
    version = Param.Int("")

    system = Param.System(Parent.any, "system object parameter")
    
    endpoint_name = Param.String(
        "", "NMU/NSU endpoint name from config"
    )

    protocol = Param.String("AXIMM", "Protocol: AXIMM or AXIS")
    role = Param.String("Master", "Endpoint role: master or slave")

    noc_system = Param.NocSystem("")

    # AXIS configuration (used when AXIS)
    axis_data_width = Param.UInt32(512, "AXIS TDATA width (bits)")
    axis_id_width = Param.UInt32(6, "AXIS TID width")
    axis_dest_width = Param.UInt32(4, "AXIS TDEST width")

    # wrapper
    protocol_parameters = VectorParam.Unsigned([], "")

    # These can be used by a protocol to enable reuse of the same machine
    # types to model different levels of the cache hierarchy
    upstream_destinations = VectorParam.NocInterface(
        [], "Possible destinations for requests sent towards the CPU"
    )
    downstream_destinations = VectorParam.NocInterface(
        [], "Possible destinations for requests sent towards memory"
    )

    buffers = VectorParam.NocMessageBuffer("AXI channel queues between the NodeInterface and the NMU/NSU")
    protocol_buffer_size = Param.Unsigned(
        _NOC_IF_PROTOCOL_QUEUE_DEPTH,
        "Depth of each NocInterface <-> NMU/NSU protocol MessageBuffer",
    )

    noc_probe = Param.NocProbe(
        NULL, "Optional NocProbe for node-side CDC / beat hook callbacks"
    )

    record_mode = Param.UInt32(0,   "Mode to record to CSV File:\n" \
                                    "\t0: No data points exported to CSV" \
                                    "\t1: Per transaction granularity exported to CSV (required for latency and BW plots)" \
                                    "\t2: Every cycle information exported to CSV (required for ready/valid % plots)")


    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        protocol_buffer_size = int(self.protocol_buffer_size)

        # kinda wish i didn't have to make this initiation here but 
        # maybe i can visit and rewrite once i'm more familiar with gem5 stuff
        if self.protocol == "AXIMM":
            self.buffers = [
                NocMessageBuffer(
                    ordered=True, buffer_size=protocol_buffer_size
                )
                for _ in range(5)
            ]
            self.protocol_parameters = []
        elif self.protocol == "AXIS":
            self.buffers = [
                NocMessageBuffer(
                    ordered=True, buffer_size=protocol_buffer_size
                )
            ]
            self.protocol_parameters = [self.axis_data_width, self.axis_id_width, self.axis_dest_width]
            # TODO: add warning if any aximm parameters are set
        else:
            raise ValueError(f"Unknown protocol: {self.protocol}")

        if int(self.record_mode) not in (0, 1, 2):
            raise ValueError(f"Invalid record mode: {self.record_mode}")
