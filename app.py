"""
GitHub File Uploader — backend
--------------------------------
Menerima file dari halaman HTML, mengirimnya ke repository GitHub lewat
GitHub Contents API, lalu mengembalikan link publik (raw + jsDelivr CDN)
yang benar-benar bisa dipakai untuk mengunduh file tersebut.

Jalankan:
    pip install -r requirements.txt
    cp .env.example .env   # lalu isi token & nama repo
    python app.py

Buka:
    http://localhost:5000
"""

import base64
import os
import time
import unicodedata
import re

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
UPLOAD_FOLDER_IN_REPO = os.getenv("GITHUB_UPLOAD_PATH", "uploads")

GITHUB_API = "https://api.github.com"
MAX_FILE_SIZE_MB = 90  # GitHub Contents API praktisnya nyaman sampai ~90-100MB

app = Flask(__name__, static_folder=None)


def slugify_filename(name: str) -> str:
    """Bersihkan nama file supaya aman dipakai sebagai path di GitHub."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return name or "file"


def github_configured() -> bool:
    return bool(GITHUB_TOKEN and GITHUB_OWNER and GITHUB_REPO)


@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))


@app.route("/api/health")
def health():
    return jsonify(
        {
            "configured": github_configured(),
            "owner": GITHUB_OWNER or None,
            "repo": GITHUB_REPO or None,
            "branch": GITHUB_BRANCH,
        }
    )


@app.route("/api/upload", methods=["POST"])
def upload():
    if not github_configured():
        return (
            jsonify(
                {
                    "error": "Server belum dikonfigurasi. Isi GITHUB_TOKEN, "
                    "GITHUB_OWNER, dan GITHUB_REPO di file .env lalu restart server."
                }
            ),
            500,
        )

    if "file" not in request.files:
        return jsonify({"error": "Tidak ada file yang dikirim."}), 400

    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "Nama file kosong."}), 400

    raw_bytes = f.read()
    size_mb = len(raw_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        return (
            jsonify(
                {
                    "error": f"File terlalu besar ({size_mb:.1f}MB). "
                    f"Batas saat ini {MAX_FILE_SIZE_MB}MB."
                }
            ),
            400,
        )

    # Nama file final: pakai yang diisi user kalau ada, kalau tidak pakai nama asli
    custom_name = request.form.get("filename", "").strip()
    base_name = custom_name if custom_name else f.filename
    safe_name = slugify_filename(base_name)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    repo_path = f"{UPLOAD_FOLDER_IN_REPO}/{timestamp}-{safe_name}".strip("/")

    content_b64 = base64.b64encode(raw_bytes).decode("ascii")

    api_url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{repo_path}"
    payload = {
        "message": f"upload: {safe_name}",
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        resp = requests.put(api_url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return jsonify({"error": f"Gagal menghubungi GitHub: {exc}"}), 502

    if resp.status_code not in (200, 201):
        try:
            detail = resp.json().get("message", resp.text)
        except ValueError:
            detail = resp.text
        return (
            jsonify({"error": f"GitHub menolak upload ({resp.status_code}): {detail}"}),
            resp.status_code,
        )

    data = resp.json()
    html_url = data.get("content", {}).get("html_url")

    raw_url = (
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/{repo_path}"
    )
    # jsDelivr men-cache lewat CDN dan memaksa file ter-download dengan rapi
    cdn_url = (
        f"https://cdn.jsdelivr.net/gh/{GITHUB_OWNER}/{GITHUB_REPO}@{GITHUB_BRANCH}/"
        f"{repo_path}"
    )
    forced_download_url = f"{html_url}?raw=true" if html_url else raw_url

    return jsonify(
        {
            "filename": safe_name,
            "path": repo_path,
            "size_bytes": len(raw_bytes),
            "raw_url": raw_url,
            "cdn_url": cdn_url,
            "download_url": forced_download_url,
            "github_page": html_url,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
