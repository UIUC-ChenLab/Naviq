#include "noc/lib/axi/AXITypes.hh"
#include "base/logging.hh"

#include <string>
#include <iostream>

namespace gem5 
{
namespace noc {

       // Code for output operator
::std::ostream&
operator<<(::std::ostream& out, const AxiMsgSizeType& obj)
{
    out << MessageSizeType_to_string(obj);
    out << ::std::flush;
    return out;
}

// Code to convert state to a string
std::string
MessageSizeType_to_string(const AxiMsgSizeType obj)
{
    switch(obj) {
      case AxiMsgSizeType::AR:
        return "AR";
      case AxiMsgSizeType::AW:
        return "AW";
      case AxiMsgSizeType::R:
        return "R";
      case AxiMsgSizeType::W:
        return "W";
      case AxiMsgSizeType::B:
        return "B";
      default:
        panic("Invalid range for type MessageSizeType");
    }
    // Appease the compiler since this function has a return value
    return "";
}
}
}