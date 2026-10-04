"""Verify a restored tree against a complete SHA256 inventory."""
import sys
from inventory import main

if __name__ == '__main__':
    raise SystemExit(main(['verify', *sys.argv[1:]]))
