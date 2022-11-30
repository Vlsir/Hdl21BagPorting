import bag  # stick this right at the top so we're sure it works
import inspect, os, sys, importlib
import json
from pathlib import Path
from dataclasses import field
from types import ModuleType
from typing import Any, Dict, List, Tuple, Set, Optional
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


@dataclass
class BagSchematic:
    """#  BAG Schematic Schema"""

    # Cell Metadata
    lib_name: str
    cell_name: str
    view_name: str

    # Core schematic content
    terminals: Dict[str, Any]  # FIXME: more specifics
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


@dataclass(frozen=True)
class SchematicGeneratorPaths:
    # Turns out loading this YAML takes FOREVER, so we'll cache these things on disk
    lib_name: str
    cell_name: str
    module_path: Path
    sch_path: Path


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
    relpath = str(relpath)
    relpath = relpath[:-3]  # Remove ".py"
    # relpath = str(source_paths.module_path)[len(str(source_paths.prefix)) + 1 : -3]
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

    # gps = SchematicGeneratorPaths(
    #     lib_name=lib_name,
    #     cell_name=cell_name,
    #     module_path=path,
    #     sch_path=sch_yaml_path,
    # )
    # open("paths.json", "a").write(json.dumps(gps, default=pydantic_encoder) + ",")

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


# for src in walk():
#     pass
#     # print(sch)
#     # for cls in find_bag_modules(mod):
#     #     print(cls.__qualname__)
#     #     print(inspect.signature(cls.design))

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


def ordered_stuff():
    """
    Scratch-space, looking at ordered cells and their dependencies
    """
    ordered = json.load(open("ordered_paths.json", "r"))
    for paths in ordered:
        p = SchematicGeneratorPaths(**paths)
        sch = load_sch(p.sch_path)
        print(sch.cell_name)
        # for name, term in sch.terminals.items():
        #     inst = BagSchematicInstance(**term["obj"][1]["inst"])
        #     # print(name)
        #     # print(inst)
        print(f"({(sch.lib_name, sch.cell_name)}) depends on:")
        for inst in sch.instances.values():
            print(f"     {(inst.lib_name, inst.cell_name)}")


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


if __name__ == "__main__":
    main()