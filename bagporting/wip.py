"""
This part is WORK IN PROGRESS
See, it says right there in the name. 
"""

import inspect, os, sys, importlib, json
from copy import copy
from enum import Enum
from pathlib import Path
from dataclasses import field
from types import ModuleType
from typing import Any, Dict, List, Tuple, Set, Optional, Union

# PyPi Imports
import black  # Yes `black` the formatter, produce code that actually looks good!
from pydantic.dataclasses import dataclass
from ruamel.yaml import YAML


from enum import Enum
from pathlib import Path
from dataclasses import field
from typing import Any, Dict, List, Tuple, Set, Union
from pydantic.dataclasses import dataclass


# Local Imports
from .schematic import *
from .schematic_module import *
from .code import *


@dataclass
class Session:
    """# Porting "Session"
    More or less the global state of a run through all this action."""

    candidates: Set[SourcePaths] = field(default_factory=set)
    sourcepaths_to_generators: Dict[SourcePaths, SchematicGenerator] = field(
        default_factory=dict
    )
    libcells_to_schematics: Dict[LibCell, BagSchematic] = field(default_factory=dict)
    libcells_to_generators: Dict[LibCell, SchematicGenerator] = field(
        default_factory=dict
    )
    not_found: Set[LibCell] = field(default_factory=set)


session = Session()  # Create a program-level `Session`


# Primitive cells, defined not by these imports but (somewhere) elsewhere
prim_cells = [
    LibCell(lib, cell)
    for (lib, cell) in [
        ("BAG_prim", "nmos4_standard"),
        ("BAG_prim", "pmos4_standard"),
        ("BAG_prim", "ndio_standard"),
        ("BAG_prim", "pdio_standard"),
        ("BAG_prim", "res_metal_1"),
        ("BAG_prim", "res_metal_2"),
        ("BAG_prim", "res_metal_3"),
        ("BAG_prim", "res_metal_4"),
        ("BAG_prim", "res_metal_5"),
        ("BAG_prim", "res_metal_6"),
        ("BAG_prim", "res_metal_7"),
        ("BAG_prim", "res_metal_8"),
        ("BAG_prim", "res_metal_9"),
        ("basic", "cds_thru"),
        ("basic", "noConn"),
        ("analogLib", "cap"),
        ("analogLib", "dcblock"),
        ("analogLib", "dcfeed"),
        ("analogLib", "gnd"),
        ("analogLib", "idc"),
        ("analogLib", "ind"),
        ("analogLib", "iprobe"),
        ("analogLib", "port"),
        ("analogLib", "res"),
        ("analogLib", "switch"),
        ("analogLib", "vdc"),
        ("analogLib", "vcvs"),
        ("analogLib", "vpulse"),
        ("analogLib", "vpwlf"),
        ("analogLib", "vsin"),
        ("analogLib", "vsrc"),
    ]
]


def find_candidates(
    search_paths: List[Path],
) -> List[SourcePaths]:  # Really a generator "yield" thing, sue me.
    """
    Walk all the places we might find BAG's schematic generators, yielding one at a time
    This begins with the realization that BAG never learned to use Python's package system,
    and places everything it uses, i.e. all the "design packages", on sys.path.
    (A shortcut here for filtering down to relevant modules.)

    Yields a sequence of `SourcePaths`s which can be thought of as "candidates".
    Each has:
    * a parent directory named "schematic"
    * a `netlist_info/{modname}.yaml` file, and
    * a python file by the same {modname}
    """
    for prefix in search_paths:
        print(f"Searching `{prefix}`")
        for root, dirs, files in os.walk(prefix, followlinks=False):
            if "schematic" not in root:
                continue
            for file in files:
                # Filter down to python files
                path = Path(os.path.join(root, file)).absolute()
                if path.suffix != ".py":
                    continue

                # Check for a corresponding `netlist_info/{modname}.yaml`
                sch_yaml_path = (
                    (path.parent / "netlist_info" / path.stem)
                    .with_suffix(".yaml")
                    .absolute()
                )
                if not sch_yaml_path.exists():
                    continue  # No YAML, keep looking elsewhere

                yield SourcePaths(
                    prefix=prefix, module_path=path, sch_path=sch_yaml_path
                )

                # Add it to our definitions
                # session.srcs[(lib_name, cell_name)] = src
                # And yield it for any more processing
                # yield src


def get_sch(libcell: LibCell):
    lib_name, cell_name = libcell.lib, libcell.cell
    if libcell in session.libcells_to_schematics:
        return session.libcells_to_schematics[libcell]

    # Not defined, try to get from disk
    # FIXME: where?
    path = paths.get((lib_name, cell_name), None)
    if path is None:
        session.not_found.add(libcell)
        return None

    sch = load_sch(path.sch_path)
    session.libcells_to_schematics[libcell] = sch
    return sch


def order_helper(sch: BagSchematic, order: List[BagSchematic], seen: Set[LibCell]):
    """# Recursive depth-first ordering helper"""

    libcell = LibCell(sch.lib_name, sch.cell_name)
    if libcell in seen:
        return  # Already done
    seen.add(libcell)

    for inst in sch.instances.values():
        target = LibCell(inst.lib_name, inst.cell_name)
        if target in prim_cells:
            continue  # Don't include the primitive cells
        order_helper(sch=get_sch(target), order=order, seen=seen)

    # Finally, add `sch` to the end of the list
    order.append(sch)


def ordered_stuff():
    """
    Scratch-space
    Looking at ordered cells and their dependencies
    Lots of file-side caching of intermediate results being debugged in here,
    especially after some long searches over the file system.
    """
    # paths = json.load(open("data/paths.json", "r"))
    # paths = [SchematicGeneratorPaths(**path) for path in paths]
    # paths = {(path.lib_name, path.cell_name): path for path in paths}

    # accum = list()
    # for path in paths.values():
    #     sch = get_sch(LibCell(path.lib_name, path.cell_name))
    #     order_helper(sch, accum)
    # print(f"NOT_FOUND: {not_found}")
    # print(f"ORDER: {accum}")
    # if not_found:
    #     raise TabError()
    # open("data/order.json", "w").write(json.dumps(accum))

    # order = json.load(open("data/order.json", "r"))
    # ordered_paths = [paths[tuple(k)] for k in order if tuple(k) not in prim_cells]
    # open("data/ordered_paths.json", "w").write(json.dumps(ordered_paths, default=pydantic_encoder))

    ordered = json.load(open("data/ordered_paths.json", "r"))
    ordered = [SchematicGeneratorPaths(**paths) for paths in ordered]

    for p in ordered:
        sch = load_sch(p.sch_path)
        print(p)
        print_schematic_stuff(sch)
        code = bag_sch_to_code(sch)
        code = black.format_str(code, mode=black.FileMode())
        print(code)
        exec(code)


def print_schematic_stuff(sch: BagSchematic):
    """# Print some fun facts about schematic `sch`."""

    print(f"({(sch.lib_name, sch.cell_name)})")

    terminal_names = set(sch.terminals.keys())
    print(terminal_names)

    for name, term in sch.terminals.items():
        print(parse_instance_or_port_name(name))
        print(f"  {name} {term.inner.direction}")

    print(f"depends on:")
    internal_signals: Set[str] = set()
    for inst in sch.instances.values():
        print(f"     {(inst.lib_name, inst.cell_name)}")
        for portname, signame in inst.connections.items():
            conn = parse_connection(signame)
            sigs = get_signal_refs(conn)
            for sig in sigs:
                if sig not in terminal_names:
                    internal_signals.add(sig)

    print("  Internal signals:")
    print(f"  {internal_signals}")
