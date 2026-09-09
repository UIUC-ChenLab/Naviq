#!/usr/bin/env python3
"""Compile the real packet strategy and check narrow TUSER under backpressure.

Run with Python directly; gem5 and Verilated models are not required. Checks
remain active with NDEBUG, matching gem5.fast's assertion configuration.
"""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest


AXI = Path(__file__).resolve().parents[2] / "lib/external/SystemVerilogAXI/axi_traffic"
HARNESS = r'''
#include "AxisInterface.h"
#include "AxisPacketStrategy.h"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void require(bool condition, const std::string& message)
{
    if (!condition) throw std::runtime_error(message);
}

static DataView userView(size_t bytes, uint32_t value)
{
    auto data = std::make_shared<std::vector<uint8_t>>(bytes);
    for (size_t i = 0; i < bytes; ++i) (*data)[i] = (value >> (8 * i)) & 255;
    return DataView(data, bytes, 0);
}

static void checkStorage(size_t width, size_t bytes, uint32_t value)
{
    AxisInterface channel(512, 6, 10, width);
    require(channel.getTUserWidth() == width, "TUSER bit width changed");
    require(channel.getTUser().size() == bytes, "TUSER byte allocation mismatch");
    channel.setTUser(userView(bytes, value));
    for (size_t i = 0; i < bytes; ++i)
        require(channel.getTUser()[i] == ((value >> (8 * i)) & 255),
                "TUSER setter lost a byte");
    for (size_t wrongBytes : {bytes + 1, bytes ? bytes - 1 : size_t(1)}) {
        bool rejected = false;
        try { channel.setTUser(userView(wrongBytes, 0)); }
        catch (const std::runtime_error&) { rejected = true; }
        require(rejected, "TUSER setter accepted an incorrect byte count");
        require(channel.getTUser().size() == bytes, "Rejected setter changed storage");
        for (size_t i = 0; i < bytes; ++i)
            require(channel.getTUser()[i] == ((value >> (8 * i)) & 255),
                    "Rejected setter changed sideband");
    }
}

struct Beat {
    std::vector<uint8_t> data, user;
    uint64_t keep = 0, id = 0, dest = 0;
    bool last = false;
    bool operator==(const Beat& other) const {
        return data == other.data && user == other.user && keep == other.keep &&
               id == other.id && dest == other.dest && last == other.last;
    }
};

static Beat sample(const AxisInterface& channel)
{
    Beat beat;
    beat.data.assign(channel.getTData().begin(), channel.getTData().end());
    if (channel.getTUser().size())
        beat.user.assign(channel.getTUser().begin(), channel.getTUser().end());
    for (size_t i = 0; i < channel.getTKeep().size(); ++i)
        beat.keep |= channel.getTKeep()[i].u64() << i;
    beat.id = channel.getTId();
    beat.dest = channel.getTDest();
    beat.last = channel.getTLast();
    return beat;
}

static void checkStrategy(size_t width, size_t userBytes, uint32_t user)
{
    AxisInterface channel(512, 6, 10, width);
    AxisPacketStrategy::Config config;
    config.profile = "ipv4_udp";
    config.max_packets = 6;
    config.min_payload_bytes = config.max_payload_bytes = 137;
    config.flow_count = 2;
    config.data_width = 512;
    config.tid_width = 6;
    config.tdest_width = 10;
    config.tid = 27;
    config.tdest = 513;
    config.tuser = user;
    AxisPacketStrategy strategy;
    strategy.configure(config);
    strategy.initializeBuffers(channel);
    strategy.reset();

    unsigned packets = 0, beats = 0, packetBeat = 0, stalled = 0;
    unsigned stallCycles[3] = {};
    bool held = false;
    Beat previous;
    std::vector<uint8_t> packet;
    for (unsigned cycle = 0; cycle < 10000 && strategy.hasMoreData(); ++cycle) {
        strategy.setInterfaceValues(channel);
        require(!held || channel.getTValid(), "TVALID disappeared while stalled");
        bool ready = true;
        if (channel.getTValid()) {
            const Beat current = sample(channel);
            require(!held || current == previous, "Stalled AXIS beat changed");
            require(current.id == 27 && current.dest == 513, "TID/TDEST changed");
            require(current.user.size() == userBytes, "Strategy TUSER storage changed");
            for (size_t i = 0; i < userBytes; ++i)
                require(current.user[i] == ((user >> (8 * i)) & 255),
                        "Strategy lost TUSER metadata");
            require(packetBeat < 3, "Extra packet beat");
            require(current.last == (packetBeat == 2), "Incorrect TLAST");
            const uint64_t expectedKeep = packetBeat == 2 ? (1ULL << 37) - 1 : ~0ULL;
            require(current.keep == expectedKeep, "Incorrect TKEEP");
            ready = stalled == 3;  // Stall first, middle and partial final beats.
            if (!ready) {
                ++stallCycles[packetBeat];
                ++stalled;
                previous = current;
                held = true;
            } else {
                held = false;
                stalled = 0;
                ++beats;
                ++packetBeat;
                for (size_t i = 0; i < current.data.size(); ++i)
                    if ((current.keep >> i) & 1) packet.push_back(current.data[i]);
                if (current.last) {
                    require(packet.size() == 165, "Packet length changed");
                    require(packet[0] == 0x45 && packet[9] == 17, "IPv4/UDP header changed");
                    require(packet[4] == 0x10 && packet[5] == packets,
                            "Packet sequence repeated or skipped");
                    for (unsigned i = 0; i < 137; ++i)
                        require(packet[28 + i] == ((0xa0 + packets + i) & 255),
                                "Packet payload changed");
                    ++packets;
                    packetBeat = 0;
                    packet.clear();
                }
            }
        }
        channel.setTReady(ready);
        strategy.calculateNextValues(channel);
        strategy.tick(channel);
    }
    require(!strategy.hasMoreData(), "Packet strategy timed out");
    require(packets == 6 && beats == 18 && packet.empty(), "Packet/beat count mismatch");
    for (unsigned count : stallCycles)
        require(count == 18, "Did not exercise every packet phase under backpressure");
    std::cout << "width=" << width << " user=" << user << " packets=" << packets
              << " beats=" << beats << " stalled_cycles=54 PASS\n";
}

int main()
{
    try {
        for (const auto& item : std::vector<std::vector<unsigned>>{
                {0, 0, 0}, {1, 1, 1}, {8, 1, 0xa5}, {9, 2, 0x101}}) {
            checkStorage(item[0], item[1], item[2]);
            checkStrategy(item[0], item[1], item[2]);
        }
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
'''


class AxisPacketUserTest(unittest.TestCase):
    def test_narrow_user_storage_and_stalled_strategy(self):
        with tempfile.TemporaryDirectory(prefix="axis-packet-user-") as temporary:
            directory = Path(temporary)
            harness = directory / "test.cc"
            harness.write_text(HARNESS)
            strategies = AXI / "AxisTrafficGenerator/strategies"
            sources = [harness, AXI / "include/AxisInterface.cpp",
                       AXI / "include/DataView.cpp",
                       strategies / "AxisTrafficStrategy.cpp",
                       strategies / "AxisPacketStrategy.cpp",
                       strategies / "AxisPacketUtils.cpp"]
            binary = directory / "test"
            command = [*shlex.split(os.environ.get("CXX", "g++")),
                       "-std=c++17", "-O2", "-DNDEBUG",
                       "-I" + str(AXI / "include"), "-I" + str(strategies),
                       *map(str, sources), "-o", str(binary)]
            build = subprocess.run(command, text=True, capture_output=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("PASS"), 4, result.stdout)
            print(result.stdout, end="")


if __name__ == "__main__":
    unittest.main()
