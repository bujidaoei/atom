import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from . import MigrationError, migrate

parser = argparse.ArgumentParser(description="Back up and migrate an explicitly selected supported Atom API database.")
parser.add_argument("database", type=Path)
parser.add_argument("--backup", type=Path, required=True)
arguments = parser.parse_args()
try:
    print(json.dumps(asdict(migrate(arguments.database, arguments.backup))))
except MigrationError as error:
    print(json.dumps({"error": error.code}), file=sys.stderr)
    sys.exit(1)
