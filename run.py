import os
import sys


def _bundled_portaudio():
    """Version Linux autonome (AppImage) : utiliser la PortAudio livrée si le système n'en a pas."""
    base = getattr(sys, "_MEIPASS", None)
    if not base or sys.platform != "linux":
        return
    lib = os.path.join(base, "libportaudio.so.2")
    if not os.path.exists(lib):
        return
    import ctypes.util
    orig = ctypes.util.find_library

    def find(name):
        found = orig(name)
        return found if found or name != "portaudio" else lib
    ctypes.util.find_library = find


if __name__ == "__main__":
    _bundled_portaudio()
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        from catpilot.selftest import run
        sys.exit(run(sys.argv[2] if len(sys.argv) > 2 else "selftest.txt"))
    from catpilot.gui import main
    main()
