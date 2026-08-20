from m5.objects.SimObject import SimObject
from m5.params import *
from m5.proxy import *


class rrob(SimObject):
    type = "rrob"
    cxx_header = "noc/core/network/rrob.hh"
    cxx_class = "gem5::noc::garnet::ReadReorderBuffer"

    # Maximum number of RROB entries
    # Default 64 for AXI-MM (2048 bytes), use 128 for HBM (4096 bytes)
    max_entries = Param.UInt32(64, "Maximum number of RROB entries")
    
    # Size of each RROB entry in bytes
    # Default 32 for AXI-MM (1024 bytes), use 64 for HBM (2048 bytes)
    entry_size = Param.UInt32(32, "Size of each RROB entry in bytes")
