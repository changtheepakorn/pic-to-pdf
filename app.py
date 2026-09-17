"""
Pic to PDF - Web Server & Local UI Backend
Serves the web application and handles image fetching & PDF compilation.
"""

import os
import sys
import io
import json
import base64
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pic_to_pdf import (
    PAPER_SIZES_MM,
    parse_paper_dimensions,
    fetch_image,
    create_pdf,
    MM_TO_PT,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(WEB_DIR, exist_ok=True)

PORT = int(os.environ.get("PORT", 5500))


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class AppRequestHandler(BaseHTTPRequestHandler):
    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.serve_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
        elif path == "/api/presets":
            self.send_json_response(200, {
                "presets": PAPER_SIZES_MM,
                "units": "mm"
            })
        elif path.startswith("/output/"):
            filename = os.path.basename(path)
            file_path = os.path.join(OUTPUT_DIR, filename)
            if os.path.exists(file_path):
                self.serve_file(file_path, "application/pdf")
            else:
                self.send_error(404, "PDF file not found")
        else:
            # Try serving static file from web dir
            safe_filename = os.path.normpath(path.lstrip("/"))
            file_path = os.path.join(WEB_DIR, safe_filename)
            if os.path.commonpath([WEB_DIR, file_path]) == WEB_DIR and os.path.isfile(file_path):
                mime, _ = mimetypes.guess_type(file_path)
                self.serve_file(file_path, mime or "application/octet-stream")
            else:
                self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            self.send_json_response(400, {"error": "Invalid JSON body"})
            return

        if path == "/api/fetch-image":
            self.handle_fetch_image(payload)
        elif path == "/api/generate-pdf":
            self.handle_generate_pdf(payload)
        else:
            self.send_error(404, "Endpoint not found")

    def handle_fetch_image(self, payload: dict):
        url = payload.get("url", "").strip()
        if not url:
            self.send_json_response(400, {"error": "Missing 'url' parameter"})
            return

        try:
            img = fetch_image(url)
            width, height = img.size

            # Create thumbnail data URL for rapid, smooth frontend rendering
            max_thumb_size = (1200, 1200)
            thumb = img.copy()
            thumb.thumbnail(max_thumb_size)
            
            thumb_buffer = io.BytesIO()
            thumb.save(thumb_buffer, format="JPEG", quality=85)
            thumb_b64 = base64.b64encode(thumb_buffer.getvalue()).decode("utf-8")
            data_url = f"data:image/jpeg;base64,{thumb_b64}"

            self.send_json_response(200, {
                "success": True,
                "width": width,
                "height": height,
                "aspect_ratio": round(width / height, 4),
                "preview_data_url": data_url,
                "original_source": url,
            })
        except Exception as e:
            self.send_json_response(500, {
                "success": False,
                "error": f"Failed to fetch image: {str(e)}"
            })

    def handle_generate_pdf(self, payload: dict):
        pages_data = payload.get("pages", [])
        if not pages_data:
            self.send_json_response(400, {"error": "No pages provided"})
            return

        title = payload.get("title", "Image Document")
        filename = payload.get("filename", "converted_document.pdf")
        if not filename.endswith(".pdf"):
            filename += ".pdf"

        try:
            pdf_buffer = io.BytesIO()
            create_pdf(pages_data, pdf_buffer, title=title)
            pdf_bytes = pdf_buffer.getvalue()

            # Also save a copy to the output directory
            save_path = os.path.join(OUTPUT_DIR, filename)
            with open(save_path, "wb") as f:
                f.write(pdf_bytes)

            b64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")

            self.send_json_response(200, {
                "success": True,
                "filename": filename,
                "file_size": len(pdf_bytes),
                "saved_path": save_path,
                "pdf_base64": b64_pdf,
                "download_url": f"/output/{filename}",
            })
        except Exception as e:
            self.send_json_response(500, {
                "success": False,
                "error": f"Failed to generate PDF: {str(e)}"
            })

    def serve_file(self, file_path: str, content_type: str):
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {str(e)}")

    def send_json_response(self, status_code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Clean logging
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")


def find_available_port(start_port: int = PORT, max_attempts: int = 20) -> int:
    import socket
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", p))
                return p
            except OSError:
                continue
    return start_port


def get_local_ip() -> str:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def start_server(port: int = PORT, open_browser: bool = True):
    is_cloud_env = any(k in os.environ for k in ("RENDER", "RAILWAY_STATIC_URL", "DYNO", "FLY_APP_NAME", "KOYEB_APP_NAME"))
    if "PORT" in os.environ:
        actual_port = int(os.environ["PORT"])
    else:
        actual_port = find_available_port(port)

    server_address = ("", actual_port)
    httpd = ThreadedHTTPServer(server_address, AppRequestHandler)
    url = f"http://localhost:{actual_port}/"
    local_ip = get_local_ip()

    print("==================================================", flush=True)
    print(" ไม่รกจอ Pic to PDF by Chang is running at:", flush=True)
    print(f"   - บนเครื่องนี้:  {url}", flush=True)
    if local_ip != "127.0.0.1":
        print(f"   - ผ่านเครือข่าย: http://{local_ip}:{actual_port}/  (เข้าจากมือถือ/iPad/คอมเครื่องอื่น)", flush=True)
    print(f" Output folder: {OUTPUT_DIR}", flush=True)
    print(" Press Ctrl+C in this window to stop the server.", flush=True)
    print("==================================================", flush=True)

    if open_browser and not is_cloud_env and "PORT" not in os.environ:
        def _open():
            import time
            time.sleep(0.8)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...", flush=True)
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Start Pic-to-PDF Web Server")
    parser.add_argument("--port", type=int, default=PORT, help="Server port")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    start_server(port=args.port, open_browser=not args.no_browser)
