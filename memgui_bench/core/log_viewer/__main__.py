"""Run the MemGUI-Bench log viewer as a module."""

from .server import main

if __name__ == "__main__":
    import sys

    main(
        log_root=sys.argv[1] if len(sys.argv) > 1 else "",
        server_port=int(sys.argv[2]) if len(sys.argv) > 2 else 8760,
        base_path=sys.argv[3] if len(sys.argv) > 3 else "/",
    )

