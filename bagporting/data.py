"""
# BAG Schematic Porting 

Data Model 
"""

from enum import Enum
from pathlib import Path
from dataclasses import field
from typing import Any, Dict, List, Tuple, Set, Union
from pydantic.dataclasses import dataclass


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
