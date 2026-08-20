#ifndef __NOC_AXI_HANDSHAKE_STRESS_GENERATOR_HH__
#define __NOC_AXI_HANDSHAKE_STRESS_GENERATOR_HH__

#include "noc/endpoints/generator/AxiRandomTrafficGenerator.hh"
#include "params/AxiHandshakeStressGenerator.hh"

#include <cstdint>
#include <random>

namespace gem5
{
namespace noc
{

/**
 * A deterministic AXI-MM handshake-stress source.
 *
 * The wrapped random traffic generator continues to own transaction creation.
 * This class only inserts legal stalls at channel boundaries: an offered AW,
 * W, or AR transfer is hidden until allowed, while BREADY and RREADY are
 * independently gated.  A fixed ``fault_seed`` therefore makes a stress run
 * repeatable without mutating addresses, payload bytes, IDs, or responses.
 */
class AxiHandshakeStressGenerator : public AxiRandomTrafficGenerator
{
  public:
    typedef AxiHandshakeStressGeneratorParams Params;
    AxiHandshakeStressGenerator(const Params &p);
    ~AxiHandshakeStressGenerator() override = default;

    bool tick(int clockDomain) override;

  private:
    bool percentAllows(uint8_t percent);
    void applyHandshakeGates(aximmMasterState &state);

    uint8_t awValidPercent = 100;
    uint8_t wValidPercent = 100;
    uint8_t arValidPercent = 100;
    uint8_t bReadyPercent = 100;
    uint8_t rReadyPercent = 100;

    std::mt19937_64 rng;
    std::uniform_int_distribution<int> percentDist{0, 99};
};

} // namespace noc
} // namespace gem5

#endif // __NOC_AXI_HANDSHAKE_STRESS_GENERATOR_HH__
