import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import scrape_prices

class GasPriceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            return

        if self.path == '/api/prices':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            # Add CORS headers if you want to access this from a frontend
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            print("Received request for /api/prices. Starting scraper...")
            
            # This calls the scraper in a thread with a timeout.
            class ScraperThread(threading.Thread):
                def __init__(self):
                    super().__init__()
                    self.result = {"average_price": None, "valid_stations_count": 0, "stations": []}
                def run(self):
                    self.result = scrape_prices.scrape_gas_prices()

            t = ScraperThread()
            t.start()
            # Wait up to 180 seconds for the scraper to finish
            t.join(timeout=180.0)
            
            if t.is_alive():
                print("[FATAL ERROR] Scraper thread timed out after 180 seconds!")
                print("The scraper is permanently hanging. Force crashing to allow Docker restart...")
                # Exit everything to guarantee process cleanup and a fresh state via Docker
                os._exit(1)
            
            data = t.result
            
            self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found. Use /api/prices to get the data.")

def run(port=8080):
    server_address = ('', port)
    # Use ThreadingHTTPServer so the /health endpoint works while the scraper is running!
    httpd = ThreadingHTTPServer(server_address, GasPriceHandler)
    print(f"Starting server on http://localhost:{port}...")
    print(f"To see the JSON data, open your browser and go to: http://localhost:{port}/api/prices")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()

if __name__ == "__main__":
    run()
