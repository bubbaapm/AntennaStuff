"""Allow `python -m vna_tester`."""
from .app import main
import sys
if __name__ == "__main__":
    sys.exit(main())
