#!/usr/bin/env python3

import os
import re
import sys


def cfg_lint_check():
    print("Running cfg lint check...")
    exit_code = 0
    for file in sys.argv[1:]:
        status_code = 0
        blank_line = 0
        cfg_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), os.pardir, file)
        )
        with open(cfg_path, "r") as f:
            contents = f.read()
            for num, line in enumerate(contents.splitlines(), 1):
                # Only strip whitespaces, handle other blank characters below
                stripped_line = line.lstrip(" ")
                blank_line = blank_line + 1 if re.search(r"^\s*$", stripped_line) else 0
                if blank_line >= 2:
                    print(f"{file}:{num}: Too many blank lines")
                    status_code = 1
                if re.search(r"\s$", line):
                    print(f"{file}:{num}: Trailing whitespaces")
                    status_code = 1
                if re.search(r"^\s", stripped_line):
                    print(f"{file}:{num}: Wrong indent(Unexpected blank characters")
                    status_code = 1
                if (len(line) - len(stripped_line)) % 4:
                    print(f"{file}:{num}: Wrong indent(4x spaces mismatch)")
                    status_code = 1
            if not contents.endswith("\n"):
                print(f"{file} Missing final newline")
                status_code = 1
        exit_code = exit_code or status_code
    sys.exit(exit_code)


if __name__ == "__main__":
    cfg_lint_check()
