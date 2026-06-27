import os
import json
import argparse
import datetime
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTP server that handles each request in a separate thread."""
    daemon_threads = True

# Import modular components
from models import DigestRecipient, InterviewEvent, DigestFrequency, DigestPayload
from digest_builder import build_digest
from renderer import render_digest_html, render_digest_text

# ── Configuration ──────────────────────────────────────────────────────────────
# Configurable batch size: set env var DIGEST_BATCH_SIZE to override (default 5)
DIGEST_BATCH_SIZE = int(os.environ.get("DIGEST_BATCH_SIZE", 5))

# File Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
INTERVIEWS_FILE = os.path.join(DATA_DIR, 'interviews.json')
LOGS_FILE = os.path.join(DATA_DIR, 'sent_logs.json')
UNSUBSCRIBE_BASE = "https://orchestrator.example.com"

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(INTERVIEWS_FILE):
        with open(INTERVIEWS_FILE, 'w') as f:
            json.dump([], f, indent=2)
    if not os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, 'w') as f:
            json.dump([], f, indent=2)

ensure_dirs() # Run immediately on module import to guarantee directories exist

# ── Core Database Mapping ──────────────────────────────────────────────────────
def get_upcoming_interviews(ref_date_str=None):
    """
    Reads interviews.json, filters upcoming events on or after ref_date_str,
    sorts chronologically, and returns the top DIGEST_BATCH_SIZE as
    InterviewEvent dataclass objects.
    """
    if not ref_date_str:
        ref_date_str = datetime.date.today().isoformat()

    with open(INTERVIEWS_FILE, 'r') as f:
        interviews_data = json.load(f)

    events = []
    for item in interviews_data:
        if item['date'] >= ref_date_str:
            dt = datetime.datetime.fromisoformat(f"{item['date']}T{item['time']}")
            events.append(InterviewEvent(
                interview_id=item['id'],
                candidate_name=item['candidate_name'],
                role_title=item['role'],
                interviewer_name=item['interviewer_name'],
                scheduled_at=dt,
                meeting_link=item.get('meeting_link'),
                location=item.get('location')
            ))

    # Sort chronologically then cap at DIGEST_BATCH_SIZE
    events.sort(key=lambda x: x.scheduled_at)
    return events[:DIGEST_BATCH_SIZE]


def _build_payload(digest_type: str, ref_date_str: str) -> DigestPayload:
    """Shared helper: load events and build the DigestPayload."""
    top_n = get_upcoming_interviews(ref_date_str)
    freq = DigestFrequency.DAILY if digest_type.lower() == "daily" else DigestFrequency.WEEKLY
    recipient = DigestRecipient(
        user_id="u-default-recruiter",
        email="digest-recipients@example.com",
        display_name="Recruiter",
        frequency=freq
    )
    ref_dt = datetime.datetime.fromisoformat(ref_date_str)
    return build_digest(recipient, top_n, now=ref_dt)


def generate_digest_html_output(digest_type="daily", ref_date_str=None):
    """
    Public API used by the web server and tests.
    Returns (html_str, count, date_range_str).
    """
    if not ref_date_str:
        ref_date_str = datetime.date.today().isoformat()

    ref_date = datetime.date.fromisoformat(ref_date_str)

    # Date range label
    if digest_type.lower() == "weekly":
        end_date = ref_date + datetime.timedelta(days=6)
        date_range = f"{ref_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}"
    else:
        date_range = ref_date.strftime('%B %d, %Y')

    payload = _build_payload(digest_type, ref_date_str)

    rendered_html = render_digest_html(
        payload=payload,
        unsubscribe_url=f"{UNSUBSCRIBE_BASE}/unsubscribe?user_id={payload.recipient.user_id}"
    )
    return rendered_html, payload.total_count, date_range


def generate_all_outputs(digest_type="daily", ref_date_str=None):
    """
    Generates and writes HTML and plain-text fallback.
    Returns a result dict suitable for logging.
    """
    if not ref_date_str:
        ref_date_str = datetime.date.today().isoformat()

    payload = _build_payload(digest_type, ref_date_str)
    unsubscribe_url = f"{UNSUBSCRIBE_BASE}/unsubscribe?user_id={payload.recipient.user_id}"

    # ── Empty digest suppression ───────────────────────────────────────────────
    if payload.total_count == 0:
        return {
            "status": "skipped",
            "reason": "no_upcoming_interviews",
            "digest_type": digest_type,
            "reference_date": ref_date_str,
            "interviews_count": 0,
        }

    # ── HTML output ────────────────────────────────────────────────────────────
    html = render_digest_html(payload, unsubscribe_url=unsubscribe_url)
    html_path = os.path.join(OUTPUT_DIR, 'digest_email.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    # ── Plain-text fallback ────────────────────────────────────────────────────
    text = render_digest_text(payload, unsubscribe_url=unsubscribe_url)
    txt_path = os.path.join(OUTPUT_DIR, 'digest_email.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(text)

    ref_date = datetime.date.fromisoformat(ref_date_str)
    if digest_type.lower() == "weekly":
        end_date = ref_date + datetime.timedelta(days=6)
        date_range = f"{ref_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}"
    else:
        date_range = ref_date.strftime('%B %d, %Y')

    return {
        "status": "success",
        "digest_type": digest_type,
        "reference_date": ref_date_str,
        "date_range": date_range,
        "interviews_count": payload.total_count,
        "batch_size_limit": DIGEST_BATCH_SIZE,
        "output_html": html_path,
        "output_text": txt_path,
    }


# ── HTTP Request Handler ───────────────────────────────────────────────────────
class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def send_file(self, file_path, content_type):
        if not os.path.exists(file_path):
            self.send_error(404, "File not found")
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        with open(file_path, 'rb') as f:
            self.wfile.write(f.read())

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path in ('/', '/index.html'):
            self.send_file(os.path.join(BASE_DIR, 'src', 'web', 'index.html'), 'text/html')
        elif path == '/main.js':
            self.send_file(os.path.join(BASE_DIR, 'src', 'web', 'main.js'), 'application/javascript')
        elif path == '/api/interviews':
            with open(INTERVIEWS_FILE, 'r') as f:
                interviews = json.load(f)
            self.send_json(200, interviews)
        elif path == '/api/logs':
            with open(LOGS_FILE, 'r') as f:
                logs = json.load(f)
            self.send_json(200, logs)
        elif path == '/api/config':
            self.send_json(200, {"batch_size": DIGEST_BATCH_SIZE})
        elif path == '/api/download/txt':
            txt_path = os.path.join(OUTPUT_DIR, 'digest_email.txt')
            if not os.path.exists(txt_path):
                self.send_json(404, {"error": "Text file not generated yet. Click Generate Preview first."})
                return
            with open(txt_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="digest_email.txt"')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404, "Page Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_json(400, {"status": "error", "message": "Invalid JSON"})
            return

        if path == '/api/interviews':
            required = ['candidate_name', 'role', 'interviewer_name', 'date', 'time']
            if not all(k in data for k in required):
                self.send_json(400, {"status": "error", "message": "Missing fields"})
                return
            with open(INTERVIEWS_FILE, 'r') as f:
                interviews = json.load(f)
            new_id = f"int-{int(datetime.datetime.now().timestamp() * 1000)}"
            new_interview = {
                "id": new_id,
                "candidate_name": data['candidate_name'],
                "role": data['role'],
                "interviewer_name": data['interviewer_name'],
                "date": data['date'],
                "time": data['time'],
                "status": "Scheduled"
            }
            interviews.append(new_interview)
            with open(INTERVIEWS_FILE, 'w') as f:
                json.dump(interviews, f, indent=2)
            self.send_json(201, {"status": "success", "interview": new_interview})

        elif path == '/api/generate':
            digest_type = data.get('type', 'daily')
            ref_date = data.get('ref_date') or None
            try:
                result = generate_all_outputs(digest_type, ref_date)
                if result["status"] == "skipped":
                    self.send_json(200, {
                        "status": "skipped",
                        "message": "No upcoming interviews found. Digest suppressed.",
                        "count": 0,
                        "html": "",
                        "text": "",
                        "date_range": ""
                    })
                    return

                html_path = result["output_html"]
                txt_path = result["output_text"]
                with open(html_path, 'r', encoding='utf-8') as f:
                    html = f.read()
                with open(txt_path, 'r', encoding='utf-8') as f:
                    text = f.read()

                self.send_json(200, {
                    "status": "success",
                    "html": html,
                    "text": text,
                    "count": result["interviews_count"],
                    "date_range": result["date_range"],
                    "batch_size_limit": result["batch_size_limit"],
                })
            except Exception as e:
                self.send_json(500, {"status": "error", "message": str(e)})

        elif path == '/api/send':
            digest_type = data.get('type', 'daily')
            count = data.get('count', 0)
            date_range = data.get('date_range', '')

            if count == 0:
                self.send_json(200, {
                    "status": "skipped",
                    "message": "No interviews to send — digest suppressed."
                })
                return

            with open(LOGS_FILE, 'r') as f:
                logs = json.load(f)
            log_entry = {
                "id": f"log-{int(datetime.datetime.now().timestamp() * 1000)}",
                "timestamp": datetime.datetime.now().isoformat(),
                "type": digest_type.capitalize(),
                "count": count,
                "date_range": date_range,
                "recipient": "digest-recipients@example.com",
                "status": "Sent"
            }
            logs.insert(0, log_entry)
            with open(LOGS_FILE, 'w') as f:
                json.dump(logs, f, indent=2)
            self.send_json(200, {"status": "success", "message": "Email digest sent successfully!"})
        else:
            self.send_json(404, {"status": "error", "message": "Endpoint not found"})

    def do_DELETE(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path.startswith('/api/interviews'):
            params = urllib.parse.parse_qs(parsed_url.query)
            interview_id = params.get('id', [None])[0]
            if not interview_id:
                self.send_json(400, {"status": "error", "message": "Missing ID parameter"})
                return
            with open(INTERVIEWS_FILE, 'r') as f:
                interviews = json.load(f)
            filtered = [i for i in interviews if i['id'] != interview_id]
            if len(filtered) == len(interviews):
                self.send_json(404, {"status": "error", "message": "Interview not found"})
                return
            with open(INTERVIEWS_FILE, 'w') as f:
                json.dump(filtered, f, indent=2)
            self.send_json(200, {"status": "success", "message": "Interview deleted"})
        else:
            self.send_json(404, {"status": "error", "message": "Endpoint not found"})


# ── Main Entry Point ───────────────────────────────────────────────────────────
def main():
    ensure_dirs()

    parser = argparse.ArgumentParser(description="Digest Notification Engine")
    parser.add_argument('--cli', action='store_true', help="Run in CLI generation mode")
    parser.add_argument('--type', choices=['daily', 'weekly'], default='daily', help="Type of digest")
    parser.add_argument('--ref-date', help="Reference date YYYY-MM-DD (default: today)")
    parser.add_argument('--serve', action='store_true', help="Run interactive web server dashboard")
    parser.add_argument('--port', type=int, default=8000, help="Port for dashboard (default: 8000)")
    args = parser.parse_args()

    if args.serve:
        server_address = ('', args.port)
        httpd = ThreadingHTTPServer(server_address, DashboardHandler)
        print(f"==================================================")
        print(f"Dashboard running at: http://localhost:{args.port}")
        print(f"Batch size limit    : {DIGEST_BATCH_SIZE} (DIGEST_BATCH_SIZE)")
        print(f"Press Ctrl+C to terminate.")
        print(f"==================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            httpd.server_close()

    elif args.cli:
        ref_date = args.ref_date or datetime.date.today().isoformat()
        result = generate_all_outputs(args.type, ref_date)
        print(json.dumps(result, indent=2))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
