"""Trusted credential-free Unix launcher applying limits before executing Orca.

Kept standalone so the production namespace needs no application package or secrets.
"""

import os
import resource
import sys


def main() -> None:
    cpu_seconds = int(sys.argv[1])
    command = sys.argv[2:]
    if not command or not os.path.isabs(command[0]):
        raise SystemExit(2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024, 200 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
