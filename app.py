"""SCAN2BOOK indító: argumentum nélkül grafikus felület, argumentumokkal parancssor."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from scan2book.cli import main
    else:
        from scan2book.gui import main
    raise SystemExit(main())
