from m5.objects.ClockedObject import ClockedObject
from m5.objects.NocNetwork import NocGarnetNetworkInterface
from m5.objects.NocSlaveUnit import NocSlaveUnit
from m5.params import *
from m5.proxy import *


class sNocSlaveUnit(NocSlaveUnit):
    type = "sNocSlaveUnit"
    cxx_class = "gem5::noc::garnet::sNocSlaveUnit"
    cxx_header = "noc/core/network/nsu_types/sNocSlaveUnit.hh"

    axis_reassemble_frames = Param.Bool(
        False, "Synthetic compatibility mode: reassemble whole frames inside the NSU; real AXIS NoC delivers interleaved 64-byte chunks")
    axis_tid_width = Param.Unsigned(16, "Supported endpoint-facing AXIS TID width")
    axis_max_frame_bytes = Param.Unsigned(
        65536, "Synthetic reassembly only: maximum stored bytes per frame, including beat padding")
    axis_complete_frames = Param.Unsigned(
        8, "Synthetic reassembly only: completed frames buffered before endpoint backpressure")
    axis_beat_capture_file = Param.String(
        "", "Optional JSONL of beats enqueued to the endpoint FIFO, before its AXIS handshake; use a distinct path for each NSU")
