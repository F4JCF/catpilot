"""Compile ft8_lib et sa couche d'appel en bibliothèque partagée (ft8lib.dll / libft8lib.so).

Utilisé par GitHub Actions avant PyInstaller (gcc MinGW sous Windows), ou à la main sous Linux.
"""
import glob
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
lib = os.path.join(here, "ft8_lib")
srcs = [os.path.join(here, "ft8wrap.c")] + sorted(glob.glob(os.path.join(lib, "ft8", "*.c"))) + \
       [os.path.join(lib, "fft", "kiss_fft.c"), os.path.join(lib, "fft", "kiss_fftr.c"),
        os.path.join(lib, "common", "monitor.c")]
out = os.path.join(here, "..", "catpilot", "ft8lib.dll" if os.name == "nt" else "libft8lib.so")
cc = os.environ.get("CC", "gcc")
cmd = [cc, "-O3", "-std=gnu11", "-shared", "-o", out, "-I", lib, "-DNDEBUG",
       "-include", os.path.join(here, "compat.h"), "-Werror=implicit-function-declaration"] + srcs + ["-lm"]
if os.name == "nt":
    cmd += ["-static-libgcc", "-static"]
else:
    cmd += ["-fPIC"]
print(" ".join(cmd))
sys.exit(subprocess.call(cmd))
