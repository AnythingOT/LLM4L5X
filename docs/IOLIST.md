# I/O list

`generate/iolist.py` reads an Excel I/O list. Headers are matched loosely and may sit below title rows:

| column | also accepted |
|---|---|
| Tag | Tag name, Signal, Name, Mapped tag |
| Description | Desc, Service, Function |
| Address | I/O address, PLC address, Logix address |
| Type | Signal type, I/O type: DI, DO, AI, AO (or Digital input ...); taken from a `:I.` / `:O.` address when empty |
| Device | Equipment, Loop, Instrument; when empty, the tag prefix before the first `_` (P101_Cmd -> P101) |
| Range low / Range high, Units, Contact (NO/NC) | optional |

**Errors** (fix before use): invalid Logix name, no signal type, the same tag twice (case ignored),
the same address twice, an input on an output address or the reverse, range low not below range high.
**Warnings**: no address (not mapped until it has one), no description, analog with no range.
Addresses are used as written, never invented: the right form depends on the module.

**Devices**: signals grouped by device are recognised conservatively. A pump has one command output,
with optional running and overload inputs. A valve has an open output (plus optional close) and limit
switches (ZSO / ZSC). `plant_yaml()` proposes a plant file (see DEVICES.md) for those. Anything else is
listed as not recognised rather than guessed.

## Mapping routines

Logic uses only mapped tags (`P101_Running`), never raw I/O (`Local:1:I.Data.0`). `mapping_l5x()`
writes two routines from a checked I/O list (it refuses a list with errors):

- **MAP_IN**: `XIC(Local:1:I.Data.0)OTE(P101_Running);`, `MOV(Local:3:I.Ch0Data,LT101_PV);`
- **MAP_OUT**: `XIC(P101_Cmd)XIO(Sim_Mode)OTE(Local:2:O.Data.0);`; analog outputs are cleared in Sim_Mode.

Call them from MainRoutine:
```
XIO(Sim_Mode)JSR(MAP_IN,0);     first rung: field inputs, skipped in simulation
...your logic...
JSR(MAP_OUT,0);                 last rung: field outputs, forced off in simulation
```
Why MAP_IN is skipped by its JSR rather than by `XIO(Sim_Mode)` in each rung: an OTE whose rung is
false writes 0 every scan, which would overwrite what the plant model or test writes. A routine that
is not scanned writes nothing. MAP_OUT always runs so physical outputs go **off** in Sim_Mode: a
simulation on real hardware cannot move a field device. Show Sim_Mode on the HMI; never leave it on.

Rung comments carry the description and address; tags get the description and analog range. Points
without an address are skipped and listed. Analog values are moved as they arrive: scale on the card,
or add scaling to MAP_IN.
