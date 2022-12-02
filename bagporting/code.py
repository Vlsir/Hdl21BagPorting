"""
# Python Code Writing
"""

from pathlib import Path

# PyPi Imports
import black  # Yes `black` the formatter, we trying to produce code that actually looks good!

# Local Imports
from .schematic import SchematicPinDir, load_sch
from .schematic_module import *


class CodeWriter:
    """
    # Code Writer

    Turn a `SchematicModule` into executable Hdl21 Python code.
    Each schematic becomes an Hdl21 generator function, named the same as its schematic `cell_name`.

    Note that the code produced here is aways uglier than typical Hdl21 code in a few ways.
    This is largely because BAG schematics never needed mind avoiding Python-language keywords such as `in` or `from`,
    and correspondingly seem to use them all over the place for signal, port, and instance names.

    This generally manifests in two ways:
    1. All Module accesses use the `add` and `get` methods. No setattr magic.
    2. All Instance connections use the `connect` method: `connect(portname: str, conn: Connectable)`

    """

    def __init__(self, sch: SchematicModule):
        self.sch: SchematicModule = sch  # The input SchematicModule
        self.code: str = ""  # The result code string
        self.indent: int = 0  # Current indentation level, in "tabs"
        self.tab: str = "    "  # Per-tab indentation string

    def to_code(self):
        """Convert the SchematicModule to Python code"""
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
    return CodeWriter(convsch).to_code()

def bag_sch_path_to_code(path: Path) -> str:
    """Load a YAML schematic from `path` and convert it to Hdl21 Python code."""
    sch = load_sch(path)
    code = bag_sch_to_code(sch)
    return black.format_str(code, mode=black.FileMode())
