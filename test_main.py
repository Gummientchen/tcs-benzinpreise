import os
import time
import json
import threading
import urllib.request
import urllib.error
import pytest
from unittest.mock import patch
import main

@pytest.fixture(autouse=True)
def cleanup_prices_json():
    """Ensure prices.json is removed before and after tests."""
    if os.path.exists("prices.json"):
        os.remove("prices.json")
    yield
    if os.path.exists("prices.json"):
        os.remove("prices.json")

def test_background_scraper_creates_file():
    mock_data = {"average_price": 1.50, "valid_stations_count": 1, "stations": []}
    
    with patch('scrape_prices.scrape_gas_prices', return_value=mock_data):
        # We need to run the loop but prevent it from running forever.
        # So we patch scrape_trigger.wait to raise an exception to break the loop after the first write.
        with patch('main.scrape_trigger.wait', side_effect=InterruptedError):
            try:
                main.background_scraper_loop()
            except InterruptedError:
                pass
            
        assert os.path.exists("prices.json")
        with open("prices.json", "r") as f:
            data = json.load(f)
            assert data["average_price"] == mock_data["average_price"]
            assert data["valid_stations_count"] == mock_data["valid_stations_count"]
            assert "fetched_at" in data

def test_api_endpoint_waits_and_serves():
    """Test that the /api/prices endpoint returns data and waits if needed."""
    
    mock_data = {
        "average_price": 2.00, 
        "valid_stations_count": 1, 
        "stations": [],
        "fetched_at": "2026-03-27T12:00:00+00:00"
    }
    
    # Start the server on a different port for testing
    port = 8089
    server_address = ('', port)
    httpd = main.ThreadingHTTPServer(server_address, main.GasPriceHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    
    # Give the server a moment to start
    time.sleep(0.5)
    
    # We simulate a delayed generation of prices.json
    def async_write():
        time.sleep(1)
        with open("prices.json", "w", encoding="utf-8") as f:
            json.dump(mock_data, f)
            
    writer_thread = threading.Thread(target=async_write)
    writer_thread.start()
    
    # This should block until the file is written
    req = urllib.request.Request(f"http://localhost:{port}/api/prices")
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        res_data = json.loads(response.read().decode())
        assert res_data == mock_data
        
    httpd.shutdown()
    httpd.server_close()

def test_health_endpoint():
    """Test that the /health endpoint returns 200 OK."""
    port = 8090
    server_address = ('', port)
    httpd = main.ThreadingHTTPServer(server_address, main.GasPriceHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    
    time.sleep(0.5)
    
    req = urllib.request.Request(f"http://localhost:{port}/health")
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        assert json.loads(response.read().decode()) == {"status": "ok"}
        
    httpd.shutdown()
    httpd.server_close()

def test_invalid_endpoint():
    """Test that an unknown endpoint returns 404."""
    port = 8091
    server_address = ('', port)
    httpd = main.ThreadingHTTPServer(server_address, main.GasPriceHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    
    time.sleep(0.5)
    
    req = urllib.request.Request(f"http://localhost:{port}/unknown")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(req)
        
    assert excinfo.value.code == 404
        
    httpd.shutdown()
    httpd.server_close()

def test_scraper_timeout_triggers_exit():
    """Test that a hanging scraper thread triggers os._exit(1)"""
    def hang_scraper():
        time.sleep(2)
        return {"average_price": 0, "valid_stations_count": 0, "stations": []}
        
    with patch('scrape_prices.scrape_gas_prices', side_effect=hang_scraper):
        with patch('threading.Thread.join') as mock_join:
            # We simulate that join finishes but thread is still alive
            mock_join.return_value = None
            with patch('threading.Thread.is_alive', return_value=True):
                with patch('os._exit') as mock_exit:
                    with patch('main.scrape_trigger.wait', side_effect=InterruptedError):
                        try:
                            main.background_scraper_loop()
                        except InterruptedError:
                            pass
                        
                    mock_exit.assert_called_once_with(1)

def test_write_failure_handled():
    """Test that the loop catches file write exceptions gracefully."""
    mock_data = {"average_price": 1.50, "valid_stations_count": 1, "stations": []}
    
    with patch('scrape_prices.scrape_gas_prices', return_value=mock_data):
        with patch('builtins.open', side_effect=IOError("Mocked mock file write error")):
            with patch('main.scrape_trigger.wait', side_effect=InterruptedError):
                try:
                    main.background_scraper_loop()
                except InterruptedError:
                    pass
                # if this hasn't crashed from the IOError, the test passes successfully.

def test_update_endpoint():
    """Test that the /api/prices/update endpoint triggers an update correctly."""
    port = 8092
    server_address = ('', port)
    httpd = main.ThreadingHTTPServer(server_address, main.GasPriceHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    
    time.sleep(0.5)
    
    # Verify event is unset
    main.scrape_trigger.clear()
    assert not main.scrape_trigger.is_set()
    
    req = urllib.request.Request(f"http://localhost:{port}/api/prices/update")
    with urllib.request.urlopen(req) as response:
        assert response.status == 200
        assert json.loads(response.read().decode()) == {"status": "update triggered"}
        
    assert main.scrape_trigger.is_set()
        
    httpd.shutdown()
    httpd.server_close()
