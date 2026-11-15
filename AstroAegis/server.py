"""HTTP server (standard library only).  Run:  python3 server.py [--port 8765]"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from engine import KnowledgeBase
from engine.simulator import MODES
from store import Store, ValidationError

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_BODY = 256 * 1024


def load_i18n() -> dict:
    return json.loads((ROOT / "data" / "i18n_en.json").read_text("utf-8"))


def make_handler(kb: KnowledgeBase, store: Store):
    i18n = load_i18n()

    class Handler(BaseHTTPRequestHandler):
        server_version = "AstroAegis/1.0"

        # -- plumbing
        def log_message(self, fmt, *args):  # quieter logs
            if "--verbose" in __import__("sys").argv:
                super().log_message(fmt, *args)

        def _send(self, code: int, payload, ctype="application/json; charset=utf-8"):
            body = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(
                payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code: int, msg: str):
            self._send(code, {"error": msg})

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValidationError("Πολύ μεγάλο αίτημα.")
            if n == 0:
                return {}
            try:
                data = json.loads(self.rfile.read(n).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise ValidationError("Μη έγκυρο JSON.")
            if not isinstance(data, dict):
                raise ValidationError("Αναμενόταν αντικείμενο JSON.")
            return data

        def _route(self, method: str):
            path = urlparse(self.path).path
            try:
                if not path.startswith("/api/"):
                    return self._static(path) if method == "GET" else self._error(405, "Method not allowed")
                self._api(method, path[len("/api/"):].strip("/"))
            except ValidationError as e:
                self._error(HTTPStatus.BAD_REQUEST, str(e))
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "Δεν βρέθηκε.")
            except Exception as e:  # pragma: no cover
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Σφάλμα server: {e}")

        def do_GET(self): self._route("GET")
        def do_POST(self): self._route("POST")
        def do_PUT(self): self._route("PUT")
        def do_DELETE(self): self._route("DELETE")

        # -- static files
        def _static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC / rel).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                return self._error(HTTPStatus.NOT_FOUND, "Δεν βρέθηκε.")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        # -- API
        def _api(self, method: str, route: str):
            parts = route.split("/") if route else []
            if parts == ["meta"] and method == "GET":
                return self._send(200, {**kb.meta(), "i18n": i18n, "modes": MODES})
            if parts == ["database", "import"] and method == "POST":
                body = self._body()
                doc = body.get("data")
                if not isinstance(doc, dict):
                    raise ValidationError("Database JSON must contain an object.")
                if isinstance(doc.get("diagnostic_rules"), list) and "input_vocabulary" in doc:
                    filename = "diagnostic_rules.json"
                elif isinstance(doc.get("signals"), dict):
                    filename = "thresholds.json"
                else:
                    raise ValidationError("Unsupported JSON. Expected diagnostic_rules.json or thresholds.json schema.")
                target = ROOT / "data" / filename
                target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), "utf-8")
                fresh = KnowledgeBase()
                kb.__dict__.clear(); kb.__dict__.update(fresh.__dict__)
                store.kb = kb
                return self._send(200, {"ok": True, "file": filename, "rules": len(kb.rules), "signals": len(kb.signals)})
            if parts == ["astronauts"]:
                if method == "GET":
                    return self._send(200, store.list())
                if method == "POST":
                    return self._send(201, store.create(self._body()))
            if len(parts) >= 2 and parts[0] == "astronauts":
                aid = parts[1]
                sub = parts[2] if len(parts) > 2 else None
                if sub is None:
                    if method == "GET":
                        return self._send(200, store.get(aid))
                    if method == "PUT":
                        return self._send(200, store.update_profile(aid, self._body()))
                    if method == "DELETE":
                        store.delete(aid)
                        return self._send(200, {"ok": True})
                elif sub == "state" and method in ("PUT", "POST"):
                    return self._send(200, store.update_state(aid, self._body()))
                elif sub == "simulate" and method == "POST":
                    b = self._body()
                    mode = b.get("mode", "nominal")
                    if mode not in MODES:
                        raise ValidationError(f"Άγνωστη λειτουργία: {mode}")
                    seed = b.get("seed")
                    if seed is not None and not isinstance(seed, int):
                        raise ValidationError("Το seed πρέπει να είναι ακέραιος.")
                    return self._send(200, store.simulate(aid, mode, seed, b.get("rule_id"), b.get("level"),
                                                          bool(b.get("keep_symptoms"))))
                elif sub == "reset" and method == "POST":
                    return self._send(200, store.reset(aid))
                elif sub == "history" and method == "GET":
                    return self._send(200, store.history(aid))
            self._error(HTTPStatus.NOT_FOUND, "Άγνωστο endpoint.")

    return Handler


def create_server(host="127.0.0.1", port=8765, state_path=None) -> ThreadingHTTPServer:
    kb = KnowledgeBase()
    store = Store(kb, state_path)
    return ThreadingHTTPServer((host, port), make_handler(kb, store))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    srv = create_server(args.host, args.port)
    print(f"Astro Health Monitor: http://{args.host}:{args.port}   (Ctrl+C για έξοδο)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
