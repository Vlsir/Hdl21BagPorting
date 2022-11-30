import bag  # stick this right at the top so we're sure it works
import inspect, os, sys, importlib, json
from enum import Enum
from pathlib import Path
from dataclasses import field
from types import ModuleType
from typing import Any, Dict, List, Tuple, Set, Optional, Union
from pydantic.dataclasses import dataclass
from ruamel.yaml import YAML

yaml = YAML()


@dataclass
class BagSchematicInstance:
    """# BAG Schematic Instance Schema"""

    lib_name: str
    cell_name: str
    view_name: str
    connections: Dict[str, str]
    params: Dict[str, Any]
    is_primitive: bool

    # Unused Fields
    bbox: Tuple[int, int, int, int]
    xform: Any


class SchematicPinDir(Enum):
    INPUT = "ipin"
    OUTPUT = "opin"
    INOUT = "iopin"


@dataclass
class BagSchematicTerminalInner:
    """# BAG Schematic Terminal (Port)
    Inner Data"""

    inst: BagSchematicInstance
    attr: Dict[str, Any]

    @property
    def direction(self) -> SchematicPinDir:
        if self.inst.cell_name == "ipin":
            return SchematicPinDir.INPUT
        if self.inst.cell_name == "opin":
            return SchematicPinDir.OUTPUT
        if self.inst.cell_name == "iopin":
            return SchematicPinDir.INOUT
        raise ValueError(f"Invalid terminal pin cell_name {self.inst.cell_name}")


@dataclass
class BagSchematicTerminal:
    """# BAG Schematic Terminal (Port) Schema
    Most relevant data lies on the `Inner` internal attribute."""

    obj: Tuple[int, BagSchematicTerminalInner]
    stype: int
    ttype: int

    @property
    def inner(self) -> BagSchematicTerminalInner:
        # Get our `Inner` definition element
        return self.obj[1]


@dataclass
class BagSchematic:
    """#  BAG Schematic Schema"""

    # Cell Metadata
    lib_name: str
    cell_name: str
    view_name: str

    # Core schematic content
    terminals: Dict[str, BagSchematicTerminal]
    instances: Dict[str, BagSchematicInstance]

    # Unused Fields
    bbox: Tuple[int, int, int, int]
    shapes: List[Any]  # Annotation shapes, unexamined
    props: Any
    app_defs: Any


@dataclass(frozen=True)
class LibCell:
    """# Library and Cell (Names)"""

    lib: str
    cell: str


@dataclass(frozen=True)
class SourcePaths:
    """# Paths to source python-module and schematic-yaml for a BAG schematic generator"""

    prefix: Path  # Prefix/ search-path. FIXME: remove this, needed as a handoff temporarily.
    module_path: Path  # Python module
    sch_path: Path  # Schematic YAML


@dataclass(frozen=True)
class SchematicGenerator:
    """# Bag Schematic Generator
    The Python module, schematic, and source file-system paths."""

    source_paths: SourcePaths
    pymodule: Any  # really a python-module, pydantic doesn't really like em
    sch: BagSchematic


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


def try_candidate(source_paths: SourcePaths) -> Optional[SchematicGenerator]:
    """Try to import a `SchematicGenerator` from candidate `source_paths`."""

    # Check our cache
    if source_paths in session.sourcepaths_to_generators:
        return session.sourcepaths_to_generators[source_paths]

    try:
        sch = load_sch(source_paths.sch_path)
    except:
        return None

    # Now process the generator module
    # Remove the prefix and ".py" suffix
    relpath = source_paths.module_path.relative_to(source_paths.prefix)
    relpath = str(relpath)[:-3]  # Remove ".py"
    # And if it's a package, remove "__init__.py"
    if relpath.endswith("/__init__"):
        relpath = relpath[: -1 * len("/__init__")]

    try:
        # Convert that to a python-module path, primarily replacing slashes with dots.
        # Note that's a -Nix-specific thing there.
        modpath = relpath.replace("/", ".")
        # Key step here: import the generator module
        pymodule = importlib.import_module(modpath)
    except Exception as e:
        print(f"ERROR IMPORTING {modpath}: {e}")
        return None

    # Create the generator, cache and return it
    gen = SchematicGenerator(source_paths=source_paths, pymodule=pymodule, sch=sch)
    session.sourcepaths_to_generators[source_paths] = gen
    session.libcells_to_generators[LibCell(sch.lib_name, sch.cell_name)] = gen
    return gen


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


def find_bag_modules(mod: ModuleType) -> list:
    """Get a list of Bag (circuit) `Module` classes in (python) module `mod`."""
    from bag.design.module import Module

    accum = list()
    for k, v in mod.__dict__.items():
        if inspect.isclass(v) and issubclass(v, Module):
            accum.append(v)
    return accum


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


@dataclass(frozen=True)
class SchematicGeneratorPaths:
    # FIXME: deprecate
    lib_name: str
    cell_name: str
    module_path: Path
    sch_path: Path


def ordered_stuff():
    """
    Scratch-space
    Looking at ordered cells and their dependencies
    Lots of file-side caching of intermediate results being debugged in here,
    especially after some long searches over the file system.
    """
    # paths = json.load(open("paths.json", "r"))
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
    # open("order.json", "w").write(json.dumps(accum))

    # order = json.load(open("order.json", "r"))
    # ordered_paths = [paths[tuple(k)] for k in order if tuple(k) not in prim_cells]
    # open("ordered_paths.json", "w").write(json.dumps(ordered_paths, default=pydantic_encoder))

    ordered = json.load(open("ordered_paths.json", "r"))
    ordered = [SchematicGeneratorPaths(**paths) for paths in ordered]

    for p in ordered:
        sch = load_sch(p.sch_path)
        print(p)
        print_schematic_stuff(sch)


def print_schematic_stuff(sch: BagSchematic):
    """# Print some fun facts about schematic `sch`. """

    print(f"({(sch.lib_name, sch.cell_name)})")

    terminal_names = set(sch.terminals.keys())
    print(terminal_names)

    for name, term in sch.terminals.items():
        print(parse_instance_or_port_name(name))
        print(f"  {name} {term.inner.direction}")

    print(f"depends on:")
    for inst in sch.instances.values():
        print(f"     {(inst.lib_name, inst.cell_name)}")
        for portname, signame in inst.connections.items():
            if signame not in terminal_names:
                print(f"Internal signal: {signame}")


@dataclass
class Bus:
    """# Result of parsing and converting the maybe-scalar, maybe-bus names such as `i0<3:0>`.
    These names are used for schematic instances and terminals (ports) to indicate their widths. """

    name: str
    width: int


@dataclass
class Bus:
    name: str
    width: int


@dataclass
class SignalRef:
    """# Reference to a Signal"""

    name: str


@dataclass
class Range:
    """ # Slice Range, e.g. <3:1>"""

    top: int
    bot: int


@dataclass
class Slice:
    """ # Signal Slice"""

    name: str
    index: Union[int, Range]


@dataclass
class Repeat:
    """# Signal Repitition"""

    name: str
    n: int


@dataclass
class Concat:
    """# Signal Concatenation"""

    parts: List["Connection"]


# The union-type of things that can be connected to an instance port
Connection = Union[SignalRef, Repeat, Concat, Slice]


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
    _fail = lambda: fail(f"Invalid instance or port name {name}")

    if "," in name or "*" in name:
        _fail()

    if "<" not in name:  # Scalar case
        return Bus(name=name, width=1)

    # Otherwise, parse the name as a `Slice`, and check that it's valid for a bus
    slice = parse_slice(name)
    if not isinstance(slice.index, Range) or slice.index.bot != 0:
        _fail()
    return Bus(name=name, width=slice.top + 1)

    # # OK now the fun part, parsing apart name and width.
    # # Format: `name<width:0>`
    # # The angle-bracket part must be at the end, and the low-side index must be zero. Or fail.
    # split = name.split("<")
    # if len(split) != 2:
    #     _fail()
    # name, suffix = split[0], split[1]
    # if not suffix.endswith(">"):
    #     _fail()
    # suffix = suffix[:-1]  # Strip out the ending ">"
    # split = suffix.split(":")
    # if len(split) != 2:
    #     _fail()
    # if split[1] != "0":
    #     _fail()
    # try:  # Convert the leading section to an integer
    #     width = int(split[0])
    # except:
    #     fail(f"Could not covert `{split[0]}` to int in `{name}`")

    # # Success
    # return Bus(name=name, width=width)


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
    if conn.startswith("<*"):
        # That's a repeat
        raise TabError("?")

    if conn.endswith(">"):
        # That's a slice
        raise TabError("?")

    # Otherwise we've got a scalar signal reference
    return SignalRef(name=conn)


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
    top = int(split[0])
    bot = int(split[1])
    return Slice(name=name, index=Range(top, bot))


def main():
    # Step 1: look for candidate python-module / schematic-YAML pairs
    search_paths = [Path(p) for p in sys.path]
    candidate_generator = find_candidates(search_paths)

    # Step 2: try to turn each into a `SchematicGenerator`
    # Results are stored on `sesssion`
    for candidate in candidate_generator:
        try_candidate(candidate)

    # Step 3: arrange them in dependency order(?) (Does that matter?)
    # Step 4: convert stuff
    # Step 5: write Python code
    # Step 6: Profit(?)


def fail(msg: str):
    """Error helper. Great place to stick a breakpoint."""
    raise RuntimeError(msg)


if __name__ == "__main__":
    ordered_stuff()
    # main()
