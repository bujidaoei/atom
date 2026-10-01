import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from . import MigrationError, migrate

parser = argparse.ArgumentParser(description="Back up and migrate an explicitly selected supported Atom API database.")
parser.add_argument("database", type=Path)
parser.add_argument("--backup", type=Path, required=True)
parser.add_argument("--target-version", type=int, choices=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10), default=1)
arguments = parser.parse_args()
try:
    print(json.dumps(asdict(migrate(arguments.database, arguments.backup, target_version=arguments.target_version))))
except MigrationError as error:
    print(json.dumps({"error": error.code}), file=sys.stderr)
    sys.exit(1)
