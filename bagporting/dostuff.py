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

yaml = YAML()

from .data import *

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


def load_sch(sch_yaml_path: Path) -> BagSchematic:
    """Load `sch_yaml_path` to a `BagSchematic`."""

    # Load the schematic-yaml
    sch = yaml.load(open(sch_yaml_path, "r"))
    # Convert it to a structured type
    sch = BagSchematic(**sch)

    # Check some stuff about it
    if sch.view_name != "schematic":
        raise RuntimeError(f"INVALID SCHEMATIC FOR {sch_yaml_path}: {sch['view_name']}")

    # Checks out; return it.
    return sch


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


def schematic_to_code(sch: BagSchematic) -> str:
    return CodeWriter(sch).to_code()


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
class ConverterSchematic:
    """# Converter internal schematic model
    The BAG YAML stuff, plus some internal inferred data we sort out along the way."""

    bagsch: BagSchematic
    dependencies: Set[LibCell]
    ports: List[Port]
    signals: List[Bus]
    instances: List[Instance]


def parse_port(name: str, terminal: BagSchematicTerminal) -> Port:
    print(name)
    bus = parse_instance_or_port_name(name)
    print(bus)
    portdir = terminal.inner.direction
    return Port(name=bus.name, width=bus.width, portdir=portdir)


def convert_schematic(sch: BagSchematic) -> ConverterSchematic:
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

    return ConverterSchematic(
        bagsch=sch,
        dependencies=dependencies,
        ports=ports,
        signals=list(signals),
        instances=instances,
    )


class CodeWriter:
    """
    # Code Writer

    Turn a `ConverterSchematic` into executable Hdl21 Python code.
    Each schematic becomes an Hdl21 generator function, named the same as its schematic `cell_name`.

    Note that the code produced here is aways uglier than typical Hdl21 code in a few ways.
    This is largely because BAG schematics never needed mind avoiding Python-language keywords such as `in` or `from`,
    and correspondingly seem to use them all over the place for signal, port, and instance names.

    This generally manifests in two ways:
    1. All Module accesses use the `add` and `get` methods. No setattr magic.
    2. All Instance connections use the `connect` method: `connect(portname: str, conn: Connectable)`

    """

    def __init__(self, sch: ConverterSchematic):
        self.sch: ConverterSchematic = sch  # The input ConverterSchematic
        self.code: str = ""  # The result code string
        self.indent: int = 0  # Current indentation level, in "tabs"
        self.tab: str = "    "  # Per-tab indentation string

    def to_code(self):
        """Convert the ConverterSchematic to Python code"""
        sch = self.sch

        # Write some header stuff
        # FIXME: add the schematic's dependencies
        self.writeln(f"import hdl21 as h")
        self.writeln(f"")

        # FIXME: write actual custom parameter types
        self.writeln(f"@h.paramclass")
        self.writeln(f"class Params:")
        self.indent += 1
        self.writeln(f"... # coming soon?")
        self.indent -= 1

        # Create the Generator function
        self.writeln(f"@h.generator")
        self.writeln(f"def {sch.bagsch.cell_name}(params: Params) -> h.Module:")
        self.indent += 1

        # Create the Module
        self.writeln(f"m = h.Module()")
        self.writeln("")

        for port in sch.ports:
            self.write_port(port)
        self.writeln("")

        for signal in sch.signals:
            self.write_signal(signal)
        self.writeln("")

        for instance in sch.instances:
            self.write_instance(instance)
        self.writeln("")

        # And return the resultant Module
        self.writeln("")
        self.writeln(f"return m")

        self.indent -= 1
        return self.code

    def write_port(self, port: Port) -> None:
        port_constructors = {
            SchematicPinDir.INPUT: "h.Input",
            SchematicPinDir.OUTPUT: "h.Output",
            SchematicPinDir.INOUT: "h.Inout",
        }
        constructor = port_constructors.get(port.portdir, None)
        if constructor is None:
            self.fail("Invalid port direction for {port}")
        width = ""
        if port.width > 1:
            width = f"width={port.width}"
        self.writeln(f'm.add({constructor}({width}), name="{port.name}")')

    def write_signal(self, signal: Bus) -> None:
        width = ""
        if signal.width > 1:
            width = f"width={signal.width}"
        self.writeln(f'm.add(h.Signal({width}), name="{signal.name}")')

    def format_conn(self, conn: Connection) -> str:
        """Create a formatted code-string for a `Connection`."""
        if isinstance(conn, SignalRef):
            return f'm.get("{conn.name}")'
        if isinstance(conn, Slice):
            if isinstance(conn.index, Range):
                return f'm.get("{conn.name}")[{conn.index.top}:{conn.index.bot}]'
            return f"{conn.name}[{conn.index}]"
        if isinstance(conn, Concat):
            parts = ", ".join(self.format_conn(p) for p in conn.parts)
            return f"h.Concat({parts})"
        if isinstance(conn, Repeat):
            # Turn these into Hdl21 Concats too
            parts = ", ".join(conn.num * [self.format_conn(conn.target)])
            return f"h.Concat({parts})"
        raise TypeError

    def write_instance(self, instance: Instance) -> None:
        """Write an Instance"""

        # If this is an instance array, add a multiplier in front of it
        array_mult = ""
        if instance.ident.width > 1:
            array_mult = f"{instance.ident.width} * "

        # FIXME: generator parameters to these
        self.writeln(
            f'i = m.add({array_mult}{instance.of.cell}(h.Default)(), name="{instance.ident.name}")'
        )
        # Format each of its connections
        for k, v in instance.conns.items():
            line = f'i.connect("{k}", {self.format_conn(v)})'
            self.writeln(line)

    def writeln(self, line: str):
        """Write a line with indentation"""
        self.code += self.tab * self.indent + line + "\n"


def bag_sch_to_code(bagsch: BagSchematic) -> str:
    convsch = convert_schematic(bagsch)
    return schematic_to_code(convsch)


def fail(msg: str):
    """Error helper. Great place to stick a breakpoint."""
    raise RuntimeError(msg)


def main():
    ordered_stuff()
