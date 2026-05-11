"""Subprocess entry point. Sets ffmpeg PATH, applies the soundfile monkey-patch,
then runs demucs.separate."""
import os
import sys
from pathlib import Path

# 1) Make sure static-ffmpeg is on PATH (demucs's AudioFile uses subprocess ffmpeg)
try:
    from static_ffmpeg import run as _sf
    _ff, _ = _sf.get_or_fetch_platform_executables_else_raise()
    os.environ["PATH"] = os.path.dirname(_ff) + os.pathsep + os.environ.get("PATH", "")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

# 2) Monkey-patch demucs.audio.save_audio (torchaudio.save fails on torchcodec)
from services.demucs_patch import apply_patch  # noqa: E402
apply_patch()

# 3) Run demucs CLI
from demucs.separate import main  # noqa: E402
main()
