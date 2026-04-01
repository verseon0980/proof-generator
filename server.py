from http.server import HTTPServer, SimpleHTTPRequestHandler
from api.certify import handler
import os

class CombinedHandler(handler):
    def do_GET(self):
        # Serve index.html for all GET requests
        if self.path == "/" or self.path == "/index.html":
            try:
                with open("index.html", "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", len(content))
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"index.html not found")
        else:
            self.send_response(404)
            self.end_headers()

port = int(os.environ.get("PORT", 8000))
server = HTTPServer(("0.0.0.0", port), CombinedHandler)
print(f"Listening on port {port}")
server.serve_forever()
