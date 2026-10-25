"""Auto-test de l'exécutable (lancé par GitHub Actions) : « CATPilot.exe --selftest fichier.txt ».

Vérifie que les briques livrées avec le logiciel fonctionnent : FT8/FT4, PSK31, RTTY, SSTV,
fichier des pays, fond de carte.
"""
import math
import sys
import traceback


def run(path):
    lines, ok = [], True

    def check(name, fn):
        nonlocal ok
        try:
            lines.append(f"OK   {name} : {fn()}")
        except Exception as e:
            ok = False
            lines.append(f"ÉCHEC {name} : {e!r}\n{traceback.format_exc()}")

    import numpy as np

    def ft8():
        from . import ftx
        x = np.random.default_rng(0).normal(0, 0.05, 15 * 12000).astype(np.float32)
        s = ftx.synth(ftx.tones("CQ F4JCF JN33", "FT8"), 1200, 12000, "FT8", 0.1)
        x[6000:6000 + len(s)] += s
        res = ftx.decode(x, 12000, "FT8")
        assert any(r["text"] == "CQ F4JCF JN33" for r in res), res
        return f"{len(res)} décodage(s), {res[0]['snr']} dB"

    def ft4():
        from . import ftx
        x = np.random.default_rng(1).normal(0, 0.05, int(7.5 * 12000)).astype(np.float32)
        s = ftx.synth(ftx.tones("F4JCF DL1ABC -10", "FT4"), 1000, 12000, "FT4", 0.1)
        x[6000:6000 + len(s)] += s
        res = ftx.decode(x, 12000, "FT4")
        assert any(r["text"] == "F4JCF DL1ABC -10" for r in res), res
        return "décodé"

    def psk():
        from . import modems
        sig = modems.psk31_modulate("CQ DE F4JCF K", 1000, 12000, 0.3)
        rx = modems.Psk31Rx()
        rx.set_freq(1000)
        txt = rx.feed(np.concatenate([np.zeros(6000), sig, np.zeros(6000)]).astype(np.float32), 12000)
        assert "F4JCF" in txt, txt
        return repr(txt)

    def rtty():
        from . import modems
        sig = modems.rtty_modulate("CQ DE F4JCF K", 1500, 12000, amp=0.3)
        rx = modems.RttyRx()
        rx.set_freq(1500)
        txt = rx.feed(np.concatenate([np.zeros(6000), sig, np.zeros(6000)]).astype(np.float32), 12000)
        assert "F4JCF" in txt, txt
        return repr(txt)

    def sstv_test():
        import sstv
        from PIL import Image
        img = Image.new("RGB", (320, 240), (200, 100, 30))
        a = sstv.encode(img, sstv.Mode.ROBOT_36, sample_rate=12000).astype(np.float32) / 32768
        out = sstv.decode(np.concatenate([np.zeros(6000, np.float32), a]), 12000)
        assert out and out[-1].info.get("sstv_complete"), out
        return f"Robot 36 {out[-1].size}"

    def cty_test():
        from . import cty
        assert cty.lookup("VE2EH")["name"] == "Canada"
        return f"{len(cty.entities())} pays DXCC"

    def carte():
        from .worldmap import _map_data
        d = _map_data()
        assert len(d["land"]) > 100
        return f"{len(d['land'])} contours"

    for name, fn in (("FT8", ft8), ("FT4", ft4), ("PSK31", psk), ("RTTY", rtty), ("SSTV", sstv_test),
                     ("cty.dat", cty_test), ("carte", carte)):
        check(name, fn)

    def flags():
        from . import qsl
        for call, want in (("F4JCF", "fr"), ("DL1ABC", "de"), ("GM3XYZ", "gb-sct"), ("EA8AA", "ic"), ("JA1A", "jp")):
            iso, _n = qsl.country_of(call)
            assert iso == want and qsl.flag_path(iso), (call, iso)
        return f"{len(qsl.dxcc_table())} pays, drapeaux présents"
    check("Drapeaux", flags)

    def son():
        import sounddevice as sd
        return sd.get_portaudio_version()[1]
    check("Son (PortAudio)", son)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "selftest.txt"))
