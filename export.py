import bag  # stick this right at the top so we're sure it works
import inspect, os, sys, importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from pydantic.dataclasses import dataclass
from pydantic.json import pydantic_encoder
from ruamel.yaml import YAML

yaml = YAML()


@dataclass
class SchematicGeneratorSource:
    # Source python-module and schematic-yaml for a BAG schematic generator
    module_path: Path
    module: Any  # really a python-module
    sch_path: Path
    sch: dict  # really a more-specific dict of YAML-stuff


@dataclass
class SchematicGeneratorPaths:
    # Turns out loading this YAML takes FOREVER, so we'll cache these things on disk
    lib_name: str
    cell_name: str
    module_path: Path
    sch_path: Path


generator_paths = list()
srcs = dict()
not_found = set()


def empty_sch(lib_name: str, cell_name: str) -> dict:
    return dict(lib_name=lib_name, cell_name=cell_name, instances={})


# Primitive cells, defined not by these imports but (somewhere) elsewhere
prim_cells = [
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
schs = {k: empty_sch(*k) for k in prim_cells}


def write_paths():
    # Walk all the places we might find BAG's schematic generators, yielding one at a time
    # This begins with the realization that BAG never learned to use Python's package system,
    # and places everything it uses on sys.path. (A shortcut here for filtering down to relevant modules.)
    for prefix in sys.path:
        for root, dirs, files in os.walk(prefix, followlinks=False):
            if "schematic" not in root:
                continue
            for file in files:
                # Filter down to python files
                path = Path(os.path.join(root, file))
                if path.suffix != ".py":
                    continue

                # Check for a corresponding `netlist_info/{modname}.yaml`
                sch_yaml_path = (path.parent / "netlist_info" / path.stem).with_suffix(
                    ".yaml"
                )
                try:
                    lib_name, view_name, sch = load_sch(sch_yaml_path)
                except FileNotFoundError:
                    continue
                except Exception as e:
                    print(f"YAML ERROR LOADING {sch_yaml_path}: {e}")

                if (lib_name, cell_name) in srcs:
                    continue  # Already processed

                # Now process the generator module
                # Remove the prefix and ".py" suffix
                relpath = str(path)[len(prefix) + 1 : -3]
                # And if it's a package, remove "__init__.py"
                if relpath.endswith("/__init__"):
                    relpath = relpath[: -1 * len("/__init__")]

                modpath = relpath.replace("/", ".")
                # print(modpath)
                try:
                    mod = importlib.import_module(modpath)
                except Exception as e:
                    print(f"ERROR IMPORTING {modpath}: {e}")
                    continue

                gps = SchematicGeneratorPaths(
                    lib_name=lib_name,
                    cell_name=cell_name,
                    module_path=path,
                    sch_path=sch_yaml_path,
                )
                open("paths.json", "a").write(
                    json.dumps(gps, default=pydantic_encoder) + ","
                )

                # Create a source-files wrapper
                src = SchematicGeneratorSource(
                    module_path=path, module=mod, sch_path=sch_yaml_path, sch=sch
                )
                # Add it to our definitions
                # srcs[(lib_name, cell_name)] = src
                # And yield it for any more processing
                yield src


def load_sch(sch_yaml_path: Path) -> tuple:
    if not sch_yaml_path.exists():
        raise FileNotFoundError()

    # Load the schematic-yaml
    try:
        sch = yaml.load(open(sch_yaml_path, "r"))
    except Exception as e:
        print(f"YAML ERROR LOADING {sch_yaml_path}: {e}")
        raise e

    if sch.get("view_name", "") != "schematic":
        print(f"INVALID SCHEMATIC FOR {sch_yaml_path}: {sch['view_name']}")
        raise RuntimeError()
    lib_name = sch.get("lib_name", None)
    cell_name = sch.get("cell_name", None)
    if lib_name is None or cell_name is None:
        print(
            f"INVALID SCHEMATIC LIB/CELL FOR {sch_yaml_path}: {(lib_name, cell_name)}"
        )
        raise RuntimeError()
    return (lib_name, cell_name, sch)


def get_sch(lib_name: str, cell_name: str):
    if (lib_name, cell_name) in schs:
        return schs[(lib_name, cell_name)]
    # Not defined, try to get from disk
    path = paths.get((lib_name, cell_name), None)
    if path is None:
        not_found.add((lib_name, cell_name))
        return None
    lib_name, cell_name, sch = load_sch(path.sch_path)
    schs[(lib_name, cell_name)] = sch
    return sch


def find_bag_modules(mod) -> list:
    accum = list()
    for k, v in mod.__dict__.items():
        if inspect.isclass(v) and issubclass(v, Module):
            accum.append(v)
    return accum


def order_helper(sch: dict, accum: list):
    # Recursive depth-first ordering helper
    insts = sch["instances"]
    for inst in insts.values():
        inst_sch = get_sch(inst["lib_name"], inst["cell_name"])
        if inst_sch is not None:
            order_helper(inst_sch, accum)
    key = (sch["lib_name"], sch["cell_name"])
    if key not in accum:
        accum.append(key)


# for src in walk():
#     pass
#     # print(sch)
#     # for cls in find_bag_modules(mod):
#     #     print(cls.__qualname__)
#     #     print(inspect.signature(cls.design))

paths = json.load(open("paths.json", "r"))
paths = [SchematicGeneratorPaths(**path) for path in paths]
paths = {(path.lib_name, path.cell_name): path for path in paths}

# accum = list()
# for path in paths.values():
#     sch = get_sch(path.lib_name, path.cell_name)
#     order_helper(sch, accum)
# print(f"NOT_FOUND: {not_found}")
# print(f"ORDER: {accum}")
# if not_found:
#     raise TabError()
# open("order.json", "w").write(json.dumps(accum))

# order = json.load(open("order.json", "r"))
# ordered_paths = [paths[tuple(k)] for k in order if tuple(k) not in prim_cells]
# open("ordered_paths.json", "w").write(json.dumps(ordered_paths, default=pydantic_encoder))


@dataclass 
class BagSchematicInstance:
    # Schema for BAG's Schematic Instances 
    lib_name: str 
    cell_name: str 
    view_name: str 
    connections: Dict[str, str]
    params: Dict[str, list]
    is_primitive: bool 

    # Other, ignored fields, largely relating to geometry 
    bbox: Any 
    xform: Any 
 

ordered = json.load(open("ordered_paths.json", "r"))
for paths in ordered:
    p = SchematicGeneratorPaths(**paths)
    sch = load_sch(p.sch_path)[2]
    for name, term in sch['terminals'].items():
        inst = BagSchematicInstance(**term['obj'][1]['inst'])
        print(name)
        print(inst)
    # for name, inst in sch['instances'].items():
    #     i = BagSchematicInstance(inst_name=name, **inst)
    #     print(i)


