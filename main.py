import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import scrape_prices

scrape_trigger = threading.Event()
scrape_in_progress = threading.Event()

def background_scraper_loop():
    while True:
        scrape_in_progress.set()
        print("Running scheduled scrape...")
        class ScraperThread(threading.Thread):
            def __init__(self):
                super().__init__()
                self.result = {"average_price": None, "valid_stations_count": 0, "stations": []}
            def run(self):
                self.result = scrape_prices.scrape_gas_prices()

        t = ScraperThread()
        t.start()
        # Wait up to 300 seconds for the scraper to finish
        t.join(timeout=300.0)
        
        if t.is_alive():
            print("[FATAL ERROR] Scraper thread timed out after 300 seconds!")
            print("The scraper is permanently hanging. Force crashing to allow Docker restart...")
            # Exit everything to guarantee process cleanup and a fresh state via Docker
            os._exit(1)
            
        data = t.result
        
        import datetime
        data["fetched_at"] = datetime.datetime.now().astimezone().isoformat()
        
        try:
            with open("prices.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("Successfully saved scraped data to prices.json")
        except Exception as e:
            print(f"Failed to write prices.json: {e}")
            
        scrape_in_progress.clear()
        
        # Sleep for 4 hours, or until triggered manually
        scrape_trigger.wait(timeout=4 * 3600)
        scrape_trigger.clear()

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
            
            # If a scrape is actively running, wait for it to finish first
            if scrape_in_progress.is_set():
                print("A scrape is currently in progress. Waiting for it to finish...")
                scrape_in_progress.wait()
            
            # If it's the first run and prices.json doesn't exist, wait for it
            if not os.path.exists("prices.json"):
                print("prices.json not yet available. Waiting for the first background scrape to finish...")
                while not os.path.exists("prices.json"):
                    time.sleep(1)
            
            try:
                with open("prices.json", "r", encoding="utf-8") as f:
                    data = f.read()
                self.wfile.write(data.encode('utf-8'))
            except Exception as e:
                print(f"Error reading prices.json: {e}")
                self.wfile.write(json.dumps({"error": "Internal Server Error"}, indent=2).encode('utf-8'))
                
        elif self.path == '/api/prices/update':
            if not scrape_in_progress.is_set():
                scrape_trigger.set()
                status_msg = "update triggered"
            else:
                status_msg = "scrape already in progress"
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": status_msg}).encode('utf-8'))
            
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found. Use /api/prices to get the data.")

def run(port=8080):
    bg_thread = threading.Thread(target=background_scraper_loop, daemon=True)
    bg_thread.start()

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
