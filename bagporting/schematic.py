""" 
# Bag Schematic
Data Model
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set, Optional, Union

# PyPi Imports
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
    """# BAG Schematic Pin Direction
    Values equal the strings stored in YAML."""

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


@dataclass(frozen=True)
class SchematicGeneratorPaths:
    # FIXME: deprecate
    lib_name: str
    cell_name: str
    module_path: Path
    sch_path: Path


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
