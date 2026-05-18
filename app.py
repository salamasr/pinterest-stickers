import os
import json
import uuid
import shutil
import zipfile
import tempfile
import threading
import subprocess
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, abort

app = Flask(__name__)

JOBS = {}  # job_id -> { status, message, progress, file }
JOBS_LOCK = threading.Lock()

MAX_STICKERS = 30
STICKER_SIZE = (512, 512)
TRAY_SIZE    = (96, 96)
MAX_KB       = 100
OUTPUT_DIR   = Path(tempfile.gettempdir()) / "sticker_jobs"
OUTPUT_DIR.mkdir(exist_ok=True)


def update_job(job_id, **kwargs):
    with JOBS_LOCK:
        JOBS[job_id].update(kwargs)


def process_board(job_id, board_url, pack_name, pack_author):
    try:
        job_dir = OUTPUT_DIR / job_id
        raw_dir = job_dir / "raw"
        proc_dir = job_dir / "processed"
        raw_dir.mkdir(parents=True)
        proc_dir.mkdir(parents=True)

        update_job(job_id, status="running", message="Downloading pins from Pinterest…", progress=10)

        result = subprocess.run(
            ["gallery-dl", "--no-mtime", "-d", str(raw_dir),
             "--filename", "{id}.{extension}", board_url],
            capture_output=True, text=True, timeout=300
        )

        exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        images = sorted(
            [f for f in raw_dir.rglob("*") if f.suffix.lower() in exts],
            key=lambda f: f.stat().st_mtime
        )

        if not images:
            update_job(job_id, status="error", message="No images found. Check the board URL — it may be private or invalid.")
            return

        update_job(job_id, message=f"Found {len(images)} pins. Processing stickers…", progress=40)

        from PIL import Image

        stickers = []
        total = min(len(images), MAX_STICKERS)
        for i, src in enumerate(images[:MAX_STICKERS], 1):
            try:
                img = Image.open(src).convert("RGBA")
                w, h = img.size
                side = min(w, h)
                img = img.crop(((w-side)//2, (h-side)//2, (w+side)//2, (h+side)//2))
                img = img.resize(STICKER_SIZE, Image.LANCZOS)

                out = proc_dir / f"sticker_{i:02d}.webp"
                quality = 85
                while quality >= 40:
                    img.save(out, "WEBP", quality=quality, method=6)
                    if out.stat().st_size <= MAX_KB * 1024:
                        break
                    quality -= 10

                if out.stat().st_size <= MAX_KB * 1024:
                    stickers.append(out)

                pct = 40 + int((i / total) * 45)
                update_job(job_id, message=f"Processing sticker {i}/{total}…", progress=pct)
            except Exception:
                continue

        if not stickers:
            update_job(job_id, status="error", message="Could not process any images.")
            return

        update_job(job_id, message="Building .wastickers file…", progress=90)

        # Tray icon
        tray_img = Image.open(stickers[0]).convert("RGBA").resize(TRAY_SIZE, Image.LANCZOS)
        tray_path = proc_dir / "tray.webp"
        tray_img.save(tray_path, "WEBP", quality=80)

        metadata = {
            "title": pack_name,
            "name": pack_name,
            "identifier": pack_name.lower().replace(" ", "_"),
            "publisher": pack_author,
            "privacy_policy_website": "",
            "license_agreement_website": "",
            "image_data_version": "1",
            "avoid_cache": False,
            "animated_sticker_pack": False,
            "sticker_packs": [{
                "identifier": pack_name.lower().replace(" ", "_"),
                "name": pack_name,
                "publisher": pack_author,
                "tray_image_file": "tray.webp",
                "privacy_policy_website": "",
                "license_agreement_website": "",
                "image_data_version": "1",
                "avoid_cache": False,
                "animated_sticker_pack": False,
                "stickers": [
                    {"image_file": f.name, "emojis": ["😂"]}
                    for f in sorted(proc_dir.glob("sticker_*.webp"))
                ]
            }]
        }

        out_zip = job_dir / f"{pack_name.replace(' ', '_')}.wastickers"
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("contents.json", json.dumps(metadata, indent=2))
            zf.write(tray_path, "tray.webp")
            for f in sorted(proc_dir.glob("sticker_*.webp")):
                zf.write(f, f.name)

        update_job(job_id, status="done", message=f"Done! {len(stickers)} stickers packed.",
                   progress=100, file=str(out_zip), count=len(stickers))

    except subprocess.TimeoutExpired:
        update_job(job_id, status="error", message="Download timed out. Board may be too large or private.")
    except Exception as e:
        update_job(job_id, status="error", message=f"Error: {str(e)}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start():
    data = request.get_json()
    board_url  = (data.get("url") or "").strip()
    pack_name  = (data.get("name") or "My Meme Pack").strip()
    pack_author = (data.get("author") or "Me").strip()

    if not board_url or "pinterest" not in board_url:
        return jsonify(error="Please provide a valid Pinterest URL."), 400

    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "starting", "message": "Starting…", "progress": 0}

    t = threading.Thread(target=process_board, args=(job_id, board_url, pack_name, pack_author), daemon=True)
    t.start()

    return jsonify(job_id=job_id)


@app.route("/api/status/<job_id>")
def status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        abort(404)
    return jsonify({k: v for k, v in job.items() if k != "file"})


@app.route("/api/download/<job_id>")
def download(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        abort(404)
    path = job.get("file")
    if not path or not Path(path).exists():
        abort(404)
    return send_file(path, as_attachment=True, download_name=Path(path).name)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
