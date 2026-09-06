`ifndef URO_INTERFACES_SV
`define URO_INTERFACES_SV

// Packet-ordered result of the flow lookup. Physical table identity stays
// inside the table; downstream logic only needs the software queue value and
// packet measurements.
interface ifc_uro_lookup_result #(
    parameter int VALUE_WIDTH = 32,
    parameter int BEAT_WIDTH  = 8
);
    logic valid;
    logic ready;
    logic eligible;
    logic [15:0] payload_bytes;
    logic [BEAT_WIDTH-1:0] payload_beats;
    logic hit;
    logic [VALUE_WIDTH-1:0] value;

    modport producer (
        output valid, eligible, payload_bytes, payload_beats, hit, value,
        input ready
    );
    modport consumer (
        input valid, eligible, payload_bytes, payload_beats, hit, value,
        output ready
    );
endinterface

`endif
