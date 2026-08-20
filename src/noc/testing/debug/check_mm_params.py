import inspect

import m5

print("gem5 start")

import _m5
import m5.internal.params

members = {name for name, _ in inspect.getmembers(_m5)}
print("has param_mmNocMasterUnit:", "param_mmNocMasterUnit" in members)
print("has param_mmNocSlaveUnit:", "param_mmNocSlaveUnit" in members)
print("has param_NocMasterUnit:", "param_NocMasterUnit" in members)
print("has param_NocSlaveUnit:", "param_NocSlaveUnit" in members)
print("has param_NocGarnetNetworkInterface:", "param_NocGarnetNetworkInterface" in members)
print(
    "internal has mmNocMasterUnitParams:",
    hasattr(m5.internal.params, "mmNocMasterUnitParams"),
)
print(
    "internal has mmNocSlaveUnitParams:",
    hasattr(m5.internal.params, "mmNocSlaveUnitParams"),
)

if hasattr(_m5, "param_mmNocMasterUnit"):
    print("param_mmNocMasterUnit members:",
          [n for n, _ in inspect.getmembers(_m5.param_mmNocMasterUnit) if "mmNoc" in n])

if hasattr(_m5, "param_mmNocSlaveUnit"):
    print("param_mmNocSlaveUnit members:",
          [n for n, _ in inspect.getmembers(_m5.param_mmNocSlaveUnit) if "mmNoc" in n])
if hasattr(_m5, "param_NocMasterUnit"):
    print("param_NocMasterUnit members:",
          [n for n, _ in inspect.getmembers(_m5.param_NocMasterUnit) if "Noc" in n])
