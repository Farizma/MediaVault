"""Run Media Vault's interface on the high-performance GPU.

On a laptop with two GPUs Windows starts most apps on the integrated one, so the library (blurred backgrounds,
masked posters, the 3D box) can lag while the NVIDIA / AMD card idles; video playback already picks the fast GPU
itself (mpv / VLC). Windows' own per-app switch (Settings > System > Display > Graphics > "High performance") is a
registry value under HKCU: this sets the same value for MediaVault.exe, so it shows there and can be changed there.
A choice you made yourself in Windows is never overwritten. Takes effect the next time Media Vault starts.
"""
import sys

KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
OURS = "GpuPreference=2;"          # 2 = high performance (1 = power saving, 0 = let Windows decide)
MARK = r"Software\MediaVault"      # remembers that the value above was written by Media Vault, not by you


def _exe() -> str | None:
    return sys.executable if getattr(sys, "frozen", False) and sys.platform == "win32" else None


def apply(want: bool) -> str:
    """Set or clear the preference. Returns "set", "cleared", "yours" (you chose one in Windows) or "n/a"."""
    exe = _exe()
    if not exe:
        return "n/a"
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
        try:
            current = winreg.QueryValueEx(k, exe)[0]
        except OSError:
            current = None
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MARK) as m:
            try:
                ours = winreg.QueryValueEx(m, "gpu_preference_for")[0] == exe
            except OSError:
                ours = False
            if current is not None and not ours:
                return "yours"
            if want:
                winreg.SetValueEx(k, exe, 0, winreg.REG_SZ, OURS)
                winreg.SetValueEx(m, "gpu_preference_for", 0, winreg.REG_SZ, exe)
                return "set"
            if current is not None:
                winreg.DeleteValue(k, exe)
            try:
                winreg.DeleteValue(m, "gpu_preference_for")
            except OSError:
                pass
            return "cleared"
