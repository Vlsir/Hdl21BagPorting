"""
# Bag => Hdl21 Porting 

The part that needs BAG. 
BAG is a gigantic pain to use, to import in any other program, really just to be anywhere near. 
This breaks out the sections of portion action that need it, hopefully to be run in the smallest context possible. 

Generally running this will require being in a context in which "bag programs" ("generators", kinda) can run.
Usually that means navigating to a BAG workspace and doing whatever shell-fu it insists upon. 
"""

import bag  # stick this right at the top so we're sure it works
import inspect, os, sys, importlib, json
from enum import Enum
from pathlib import Path
from dataclasses import field
from types import ModuleType
from typing import Any, Dict, List, Tuple, Set, Optional, Union
from pydantic.dataclasses import dataclass

from .data import session, SourcePaths, BagSchematic, SchematicGenerator


def find_bag_modules(mod: ModuleType) -> list:
    """Get a list of Bag (circuit) `Module` classes in (python) module `mod`."""
    from bag.design.module import Module

    accum = list()
    for k, v in mod.__dict__.items():
        if inspect.isclass(v) and issubclass(v, Module):
            accum.append(v)
    return accum


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
