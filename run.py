import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        from catpilot.selftest import run
        sys.exit(run(sys.argv[2] if len(sys.argv) > 2 else "selftest.txt"))
    from catpilot.gui import main
    main()
