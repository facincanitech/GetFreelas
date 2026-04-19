"""
GetFreelas Local Server
Servidor local que o admin.html usa para disparar o scraper e ver o status.
Roda em http://localhost:8765
"""

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR      = Path(__file__).parent
LOG_FILE      = BASE_DIR / "last_run.json"
EMPRESAS_FILE = BASE_DIR.parent / "data" / "empresas_local.json"
PORT          = 8765

# Estado compartilhado
state = {
    "running": False,
    "last_run": None,
    "last_status": "nunca executado",
    "last_log": "",
    "last_jobs": 0
}

# Carrega último estado salvo
if LOG_FILE.exists():
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
            state.update(saved)
    except:
        pass

def save_state():
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in state.items() if k != "running"}, f, ensure_ascii=False, indent=2)

def run_scraper():
    if state["running"]:
        return
    state["running"] = True
    state["last_log"] = "Iniciando scraper...\n"

    try:
        script = BASE_DIR / "scraper.py"
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(BASE_DIR)
        )
        log = ""
        for line in proc.stdout:
            log += line
            state["last_log"] = log

        proc.wait()
        jobs_match = [l for l in log.splitlines() if "vagas publicadas" in l or "vagas selecionadas" in l]
        jobs_count = 0
        if jobs_match:
            import re
            m = re.search(r'(\d+)', jobs_match[-1])
            if m: jobs_count = int(m.group(1))

        state["last_run"]    = datetime.now().strftime("%d/%m/%Y %H:%M")
        state["last_jobs"]   = jobs_count
        state["last_status"] = "ok" if proc.returncode == 0 else "erro"
        state["last_log"]    = log

    except Exception as e:
        state["last_status"] = "erro"
        state["last_log"]    = str(e)
    finally:
        state["running"] = False
        save_state()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # silencia logs do servidor

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.cors()
        self.end_headers()

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def do_POST(self):
        if self.path == "/register":
            try:
                data = json.loads(self.read_body().decode("utf-8"))
                empresas = []
                if EMPRESAS_FILE.exists():
                    with open(EMPRESAS_FILE, encoding="utf-8") as f:
                        empresas = json.load(f)
                # Evita duplicata por email
                empresas = [e for e in empresas if e.get("email") != data.get("email")]
                data["receivedAt"] = datetime.now().isoformat()
                empresas.append(data)
                EMPRESAS_FILE.parent.mkdir(exist_ok=True)
                with open(EMPRESAS_FILE, "w", encoding="utf-8") as f:
                    json.dump(empresas, f, ensure_ascii=False, indent=2)
                self.send_json(200, {"ok": True})
            except Exception as e:
                self.send_json(500, {"ok": False, "error": str(e)})
        else:
            self.send_json(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/empresas":
            empresas = []
            if EMPRESAS_FILE.exists():
                with open(EMPRESAS_FILE, encoding="utf-8") as f:
                    empresas = json.load(f)
            self.send_json(200, {"empresas": empresas})

        elif self.path == "/status":
            self.send_json(200, {
                "running":     state["running"],
                "last_run":    state["last_run"],
                "last_status": state["last_status"],
                "last_jobs":   state["last_jobs"],
                "last_log":    state["last_log"][-3000:] if state["last_log"] else ""
            })

        elif self.path == "/scrape":
            if state["running"]:
                self.send_json(200, {"ok": False, "msg": "Scraper já está rodando..."})
                return
            t = threading.Thread(target=run_scraper, daemon=True)
            t.start()
            self.send_json(200, {"ok": True, "msg": "Scraper iniciado!"})

        elif self.path == "/ping":
            self.send_json(200, {"ok": True})

        else:
            self.send_json(404, {"error": "not found"})

def main():
    print(f"⚡ GetFreelas Server rodando em http://localhost:{PORT}")
    print("   Mantenha esta janela aberta enquanto usa o painel.\n")
    server = HTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")

if __name__ == "__main__":
    main()
