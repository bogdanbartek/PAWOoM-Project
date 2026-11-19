"""Prosty podglad LAB5: serwuje index.html i przekazuje zapytania dalej.

Uruchomienie (z katalogu glownego repozytorium, wystarczy zwykly Python 3, bez instalacji):
    py lab6\\frontend\\server.py
Potem otworz w przegladarce:  http://127.0.0.1:8090

Po co serwer, skoro jest tylko jedna strona HTML: przegladarka nie pozwoli stronie
otwartej z innego adresu pytac bramki, Eureki ani RabbitMQ (CORS). Ten serwer jest
"posrednikiem" na tym samym adresie co strona, wiec CORS nie jest potrzebny, a zadna
z uslug ani bramka nie wymaga zmian.

Przekazywane sa TYLKO te sciezki (to nie jest otwarty proxy):
    /api/*          -> bramka          (GATEWAY_URL,   domyslnie http://127.0.0.1:8080)
    /infra/gateway  -> bramka /health
    /infra/eureka   -> Eureka /eureka/apps   (lista zarejestrowanych uslug)
    /infra/queues   -> RabbitMQ /api/queues  (liczba wiadomosci w kolejkach)
Nasluchuje tylko na 127.0.0.1.
"""
import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error as urlerror
from urllib import request as urlrequest

HOST = os.getenv("FRONTEND_HOST", "127.0.0.1")
PORT = int(os.getenv("FRONTEND_PORT", "8090"))
GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080")
EUREKA = os.getenv("EUREKA_URL", "http://127.0.0.1:8761")
RABBIT = os.getenv("RABBITMQ_API_URL", "http://127.0.0.1:15672")
RABBIT_AUTH = "Basic " + base64.b64encode(
    (os.getenv("RABBITMQ_USER", "guest") + ":" + os.getenv("RABBITMQ_PASSWORD", "guest")).encode()
).decode()

HERE = os.path.dirname(os.path.abspath(__file__))
PASS_HEADERS = ("Content-Type", "X-Cache", "X-Gateway")
# Bez systemowego proxy: zapytania maja isc prosto do lokalnych procesow.
OPENER = urlrequest.build_opener(urlrequest.ProxyHandler({}))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # jedno zapytanie = jedno polaczenie, bez keep-alive

    def log_message(self, fmt, *args):
        sys.stderr.write("[frontend] %s\n" % (fmt % args))

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj).encode("utf-8"), {"Content-Type": "application/json"})

    def _forward(self, base, path, extra_headers=None):
        length = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(length) if length else None
        req = urlrequest.Request(base + path, data=data, method=self.command)
        req.add_header("Accept", "application/json")
        content_type = self.headers.get("Content-Type")
        if content_type and data is not None:
            req.add_header("Content-Type", content_type)
        for key, value in (extra_headers or {}).items():
            req.add_header(key, value)
        try:
            resp = OPENER.open(req, timeout=15)
            status, body, headers = resp.status, resp.read(), resp.headers
        except urlerror.HTTPError as exc:  # 4xx/5xx z uslugi przekazujemy bez zmian
            status, body, headers = exc.code, exc.read(), exc.headers
        except (urlerror.URLError, OSError) as exc:
            self._json(502, {"detail": "Nie mozna polaczyc z %s (%s)" % (base, exc)})
            return
        self._send(status, body, {h: headers[h] for h in PASS_HEADERS if headers.get(h)})

    def _route(self):
        path = self.path
        if self.command == "GET" and path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as handle:
                self._send(200, handle.read(), {"Content-Type": "text/html; charset=utf-8"})
        elif path.startswith("/api/"):
            self._forward(GATEWAY, path)
        elif self.command == "GET" and path == "/infra/gateway":
            self._forward(GATEWAY, "/health")
        elif self.command == "GET" and path == "/infra/eureka":
            self._forward(EUREKA, "/eureka/apps")
        elif self.command == "GET" and path == "/infra/queues":
            self._forward(RABBIT, "/api/queues", {"Authorization": RABBIT_AUTH})
        else:
            self._json(404, {"detail": "Not found"})

    do_GET = do_POST = do_PUT = do_DELETE = _route


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("Podglad LAB5:  http://%s:%d   (Ctrl+C konczy)" % (HOST, PORT))
    print("Bramka: %s | Eureka: %s | RabbitMQ: %s" % (GATEWAY, EUREKA, RABBIT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
