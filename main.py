import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import scrape_prices

class GasPriceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/prices':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            # Add CORS headers if you want to access this from a frontend
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            print("Received request for /api/prices. Starting scraper...")
            
            # This calls the scraper synchronously. 
            # Note: The request will hang until the scraper finishes (can take a minute).
            data = scrape_prices.scrape_gas_prices()
            
            self.wfile.write(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found. Use /api/prices to get the data.")

def run(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, GasPriceHandler)
    print(f"Starting server on http://localhost:{port}...")
    print(f"To see the JSON data, open your browser and go to: http://localhost:{port}/api/prices")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()

if __name__ == "__main__":
    run()
