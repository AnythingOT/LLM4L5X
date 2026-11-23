"""Reusable blocks: one file gives a device's rungs, tags, plant model and tests.

    block = load_library()["Motor"]
    inst = block.instantiate({"name": "P101", "start": "P101_Start_PB", "stop": "P101_Stop_PB"})
    inst.rungs, inst.tags, inst.plant, inst.scenarios

Code builds the rungs; nothing is written by a model. The model's job (later) is only to say which
block a requirement needs and which signals it uses. Starter blocks live in library/blocks; a
company library is a folder of the same files, kept outside this repo.
"""

from .block import Block, Instance, LibraryError, load_block, load_library

__all__ = ["Block", "Instance", "LibraryError", "load_block", "load_library"]
