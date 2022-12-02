"""
# Bag3 Schematics => Hdl21 Porting

Run script, with a few modes. 
This is largely a means for quick tests and demos, and *is not* going to become the primary mechanism for "batching". 
And don't give us this "__main__" stuff, this is always to be run as a script. 
"""

import sys
from enum import Enum
from bagporting.code import bag_sch_path_to_code
from bagporting.wip import find_candidates


class Actions(Enum):
    # The available command-line actions
    # Could this be a more elaborate CLI library thing? Sure.
    PORT = "port"  # Port a schematic-yaml files to Hdl21 Python
    SEARCH = "search"  # Search paths for schematics


action = Actions(sys.argv[1])
args = sys.argv[2:]

if action == Actions.PORT:
    print(bag_sch_path_to_code(args[0]))

if action == Actions.SEARCH:
    find_candidates()
