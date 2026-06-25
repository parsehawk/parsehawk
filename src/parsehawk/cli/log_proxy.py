from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime

ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logger-name", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise SystemExit("missing command")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        message = ANSI_PATTERN.sub("", line.rstrip("\n"))
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(
            f"{timestamp} - {args.logger_name}:INFO: {args.source}:0 - {message}",
            flush=True,
        )
    raise SystemExit(process.wait())


if __name__ == "__main__":
    main()
