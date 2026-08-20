
 #ifndef __MEM_RUBY_NETWORK_GARNET_0_NOCOUTVCSTATE_HH__
 #define __MEM_RUBY_NETWORK_GARNET_0_NOCOUTVCSTATE_HH__

 #include "mem/ruby/network/garnet/CommonTypes.hh"
 #include "noc/core/network/NocGarnetNetwork.hh"
 #include "noc/lib/network/NocSerializeNpsType.hh"
 #include "sim/serialize.hh"

 namespace gem5
 {
    // namespace ruby
    // {
    //     namespace garnet
    //     {
    //         enum VC_state_type;
    //     }
    // }

 namespace noc
 {

 namespace garnet
 {

 class NocOutVcState
 {
   public:
     NocOutVcState(int id, NocGarnetNetwork *network_ptr, uint32_t consumerVcs, Nps_Type nps_type = Nps_Type::VNOC);

     int get_credit_count()          { return m_credit_count; }
     inline bool has_credit()       { return (m_credit_count > 0); }
     void increment_credit();
     void decrement_credit();

     void serialize(CheckpointOut &cp) const;
     void unserialize(CheckpointIn &cp);

     inline bool
     isInState(gem5::ruby::garnet::VC_state_type state, gem5::Tick request_time)
     {
         return ((m_vc_state == state) && (request_time >= m_time) );
     }
     inline void
     setState(gem5::ruby::garnet::VC_state_type state, gem5::Tick time)
     {
         m_vc_state = state;
         m_time = time;
     }

   private:
     int m_id ;
     Nps_Type m_nps_type;
     gem5::Tick m_time;
     gem5::ruby::garnet::VC_state_type m_vc_state;
     int m_credit_count;
     int m_max_credit_count;
 };

 } // namespace garnet
 } // namespace noc
 } // namespace gem5

 #endif //__MEM_RUBY_NETWORK_GARNET_0_OUTVCSTATE_HH__
