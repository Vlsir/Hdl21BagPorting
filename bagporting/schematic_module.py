"""
# Schematic Module 

The circuit-level representation of BAG schematic content, 
and conversions from BAG schematics. 

The structure of the primary entity `SchematicModule` is sort of 
"half way" between the BAG YAML and hdl21.Module, 
and serves as a helpful translation step. 
"""


import inspect, os, sys, importlib, json
from copy import copy
from enum import Enum
from pathlib import Path
from dataclasses import field
from types import ModuleType
from typing import Any, Dict, List, Tuple, Set, Optional, Union

# PyPi Imports
from pydantic.dataclasses import dataclass

# Local Imports
from .schematic import *


@dataclass(frozen=True)
class Bus:
    """# Result of parsing and converting the maybe-scalar, maybe-bus names such as `i0<3:0>`.
    These names are used for schematic instances and terminals (ports) to indicate their widths."""

    name: str
    width: int


@dataclass(frozen=True)
class SignalRef:
    """# Reference to a Signal"""

    name: str


@dataclass
class Range:
    """# Slice Range, e.g. <3:1>"""

    top: int
    bot: int


@dataclass
class Slice:
    """# Signal Slice"""

    name: str
    index: Union[int, Range]


@dataclass
class Repeat:
    """# Signal Repitition"""

    target: Union[SignalRef, Slice]
    num: int


@dataclass
class Concat:
    """# Signal Concatenation"""

    parts: List["Connection"]


# The union-type of things that can be connected to an instance port
Connection = Union[SignalRef, Repeat, Concat, Slice]

# Patch up our self-references in that set of types
Concat.__pydantic_model__.update_forward_refs()


@dataclass
class Port:
    name: str
    width: int
    portdir: SchematicPinDir


@dataclass
class Instance:
    ident: Bus
    of: LibCell
    conns: Dict[str, Connection]


@dataclass
class SchematicModule:
    """# Converter internal schematic model
    The BAG YAML stuff, plus some internal inferred data we sort out along the way."""

    bagsch: BagSchematic
    dependencies: Set[LibCell]
    ports: List[Port]
    signals: List[Bus]
    instances: List[Instance]


def parse_port(name: str, terminal: BagSchematicTerminal) -> Port:
    """Parse an entry in the schematic `terminal` mapping to a `Port`."""
    bus = parse_instance_or_port_name(name)
    portdir = terminal.inner.direction
    return Port(name=bus.name, width=bus.width, portdir=portdir)


def convert_schematic(sch: BagSchematic) -> SchematicModule:
    """# FIXME!"""

    # Convert each Terminal to a Port
    # FIXME: probably dict-ify this?
    ports = [parse_port(n, t) for n, t in sch.terminals.items()]
    port_names = set([p.name for p in ports])

    signals: Set[Bus] = set()
    dependencies: Set[LibCell] = set()
    instances: List[Instance] = list()

    for sch_instname, sch_inst in sch.instances.items():
        # Add it to our dependencies set
        libcell = LibCell(sch_inst.lib_name, sch_inst.cell_name)
        dependencies.add(libcell)

        # Parse its name/ identifier, potentially to an array
        ident = parse_instance_or_port_name(sch_instname)

        # And peel out all the internal Signals by examining Instance connections
        conns: Dict[str, Connection] = dict()
        for portname, signame in sch_inst.connections.items():
            port_something = parse_instance_or_port_name(portname)

            conn = parse_connection(signame)
            sigs = get_signal_refs(conn)
            for sig in sigs:
                if sig not in port_names:
                    # FIXME: if there are non-unity-width internal signals, we fail
                    signals.add(Bus(sig, width=1))
            conns[port_something.name] = conn
        instances.append(Instance(ident=ident, of=libcell, conns=conns))

    return SchematicModule(
        bagsch=sch,
        dependencies=dependencies,
        ports=ports,
        signals=list(signals),
        instances=instances,
    )


def parse_instance_or_port_name(name: str) -> Bus:
    """
    Instance and port names use this format:
    * i0 == single instance
    * i1<3:0> == array of four
    Both are parsed as the `Bus` type, the former with a width of 1.

    Connection names also "concatenate" with commas,
    and "replicate" with <*N> type notation,
    which (we think?) isn't allowed here.
    But check for it, and fail if it happens.
    """

    if "," in name or "*" in name:
        fail(f"Invalid instance or port name {name}")

    if "<" not in name:  # Scalar case
        return Bus(name=name, width=1)

    # Otherwise, parse the name as a `Slice`, and check that it's valid for a bus
    slice = parse_slice(name)
    if not isinstance(slice.index, Range) or slice.index.bot != 0:
        fail(f"Invalid instance or port name {name}")

    # Success: return a new `Bus` declaration
    return Bus(name=slice.name, width=slice.index.top + 1)


def parse_connection(conn: str) -> Connection:
    """
    # Parse a `Connection` from YAML-format string `conn`
    Formats:
    * Repeat == `<*3>foo
    * Concat == `bar,baz`
    * Slice == `foo<3:1>`
    * SignalRef == `foo`
    """
    if "," in conn:
        # This will create and return a `Concat`
        # Recursively parse each part
        parts = conn.split(",")
        parts = [parse_connection(part) for part in parts]
        return Concat(parts)

    # Not a concatenation: either a bus, a slice, or a repeat
    if conn.startswith("<*"):  # Parse as a `Repeat`
        return parse_repeat(conn)

    if conn.endswith(">"):  # Parse as a `Slice`
        return parse_slice(conn)

    # Otherwise we've got a scalar signal reference
    return SignalRef(name=conn)


def parse_repeat(conn: str) -> Repeat:
    """# Signal Repitition
    Example: `<*2>VSS`
    Sadly "repeats of Slices" are supported, e.g. `<*2>foo<1>`.
    We guess that must be right-associative, i.e. this is saying
    `<*2> (foo<1>)`, or "repeat the 1th bit of `foo` twice`."""

    # Search for the *first* ">"
    idx = conn.index(">")
    prefix, suffix = conn[: idx + 1], conn[idx + 1 :]

    # Convert the integer part of the prefix. Rip off the "<*" and ">"
    num = int(prefix[2:-1])

    if suffix.endswith(">"):
        target = parse_slice(suffix)
    else:
        target = SignalRef(suffix)

    return Repeat(target, num)


def parse_slice(name: str) -> Slice:
    """# Parse a `Slice` from YAML-format string `name`.
    Format: `name<width-1:0>`
    The angle-bracket part must be at the end, or fail."""

    _fail = lambda: fail(f"Invalid Slice syntax {name}")

    if not name.endswith(">"):
        _fail()

    split = name.split("<")
    if len(split) != 2:
        _fail()

    name, suffix = split[0], split[1]
    suffix = suffix[:-1]  # Strip out the ending ">"

    if ":" not in suffix:  # Single index
        return Slice(name=name, index=int(suffix))

    # Range case
    split = suffix.split(":")
    if len(split) != 2:
        _fail()
    top, bot = [int(s) for s in split]
    return Slice(name=name, index=Range(top, bot))


def get_signal_refs(conn: Connection) -> Set[str]:
    """# Get all the signal (names) referred to by potentially nested connection `conn`."""

    def helper(conn: Connection, seen: Set[str]):
        # Recursive helper implementation
        if isinstance(conn, (SignalRef, Slice)):
            seen.add(conn.name)
        elif isinstance(conn, Concat):
            [helper(part, seen) for part in conn.parts]
        elif isinstance(conn, Repeat):
            helper(conn.target, seen)
        else:
            raise TypeError(conn)

    # Kick off our recursive helper with an empty set
    rv = set()
    helper(conn, rv)
    return rv


def fail(msg: str):
    """Error helper. Great place to stick a breakpoint."""
    raise RuntimeError(msg)
