# I/O list

`inputs/iolist.py` reads an Excel I/O list. Headers are matched loosely and may sit below title rows:

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
switches (ZSO / ZSC). `plant_yaml()` proposes a plant file (see PLANT.md) for those. Anything else is
listed as not recognised rather than guessed.
