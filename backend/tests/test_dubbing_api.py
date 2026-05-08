"""Backend API tests for Çince → Türkçe Dublaj API.
Covers: healthcheck, voices, upload (valid/invalid), polling, jobs list, download, delete.
"""
import os
import time
import subprocess
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://autosync-dub.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

TEST_VIDEO = Path("/tmp/test.mp4")


def _ensure_test_video():
    if TEST_VIDEO.exists() and TEST_VIDEO.stat().st_size > 1000:
        return
    # generate
    import edge_tts
    import asyncio
    asyncio.run(edge_tts.Communicate("你好世界，今天天气很好", "zh-CN-YunxiNeural").save("/tmp/zh.mp3"))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=darkred:s=320x240:d=10",
         "-i", "/tmp/zh.mp3", "-map", "0:v", "-map", "1:a", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(TEST_VIDEO)],
        check=True, capture_output=True,
    )


@pytest.fixture(scope="session", autouse=True)
def setup_video():
    _ensure_test_video()


# ---------- Health & meta ----------
class TestMeta:
    def test_healthcheck(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data.get("name") == "Çince → Türkçe Dublaj API"
        assert data.get("status") == "ok"

    def test_voices_list(self):
        r = requests.get(f"{API}/voices", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data.get("default") == "tr-TR-AhmetNeural"
        ids = [v["id"] for v in data["voices"]]
        assert "tr-TR-AhmetNeural" in ids
        assert "tr-TR-EmelNeural" in ids


# ---------- Upload validation ----------
class TestUploadValidation:
    def test_reject_unsupported_extension(self):
        files = {"file": ("dummy.txt", b"not a video", "text/plain")}
        r = requests.post(f"{API}/upload", files=files, timeout=15)
        assert r.status_code == 400
        assert "Desteklenmeyen" in r.text or "format" in r.text.lower()


# ---------- Full pipeline lifecycle ----------
class TestPipelineLifecycle:
    job_id = None

    def test_01_upload_valid_mp4(self):
        with TEST_VIDEO.open("rb") as f:
            files = {"file": ("test.mp4", f, "video/mp4")}
            r = requests.post(f"{API}/upload", files=files, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "job_id" in data
        assert data["status"] in ("queued", "running")
        TestPipelineLifecycle.job_id = data["job_id"]

    def test_02_job_progresses_to_done(self):
        jid = TestPipelineLifecycle.job_id
        assert jid, "upload must run first"
        deadline = time.time() + 240  # 4 min budget for first whisper load
        seen_stages = set()
        last = None
        while time.time() < deadline:
            r = requests.get(f"{API}/job/{jid}", timeout=15)
            assert r.status_code == 200
            j = r.json()
            last = j
            seen_stages.add(j.get("stage"))
            if j.get("status") == "done":
                break
            if j.get("status") == "error":
                pytest.fail(f"Job errored: {j.get('error')}")
            time.sleep(2)
        assert last and last.get("status") == "done", f"Did not finish. Last: {last}"
        assert last.get("progress") == 100
        assert last.get("output_url", "").endswith(f"/api/job/{jid}/download")
        # We expect at least extract+transcribe+done to have been observed
        assert "done" in seen_stages

    def test_03_segments_populated(self):
        jid = TestPipelineLifecycle.job_id
        r = requests.get(f"{API}/job/{jid}", timeout=15)
        j = r.json()
        segs = j.get("segments") or []
        assert isinstance(segs, list)
        # generated ZH speech should yield >=1 segment
        assert len(segs) >= 1
        for s in segs:
            assert "text_zh" in s and "text_tr" in s
            assert "start" in s and "end" in s

    def test_04_jobs_list_contains(self):
        jid = TestPipelineLifecycle.job_id
        r = requests.get(f"{API}/jobs", timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        ids = [i["id"] for i in items]
        assert jid in ids

    def test_05_download_returns_mp4(self):
        jid = TestPipelineLifecycle.job_id
        r = requests.get(f"{API}/job/{jid}/download", timeout=60)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("video/mp4")
        out = Path(f"/tmp/dl_{jid}.mp4")
        out.write_bytes(r.content)
        assert out.stat().st_size > 1000
        # ffprobe verify it has video+audio streams
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
            capture_output=True, text=True,
        )
        types = probe.stdout.strip().splitlines()
        assert "video" in types
        assert "audio" in types

    def test_06_delete_job(self):
        jid = TestPipelineLifecycle.job_id
        r = requests.delete(f"{API}/job/{jid}", timeout=15)
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # subsequent GET => 404
        r2 = requests.get(f"{API}/job/{jid}", timeout=10)
        assert r2.status_code == 404


class TestNotFound:
    def test_get_unknown_job_404(self):
        r = requests.get(f"{API}/job/does-not-exist", timeout=10)
        assert r.status_code == 404

    def test_delete_unknown_job_404(self):
        r = requests.delete(f"{API}/job/does-not-exist", timeout=10)
        assert r.status_code == 404
