from seleniumbase import SB
import re
import time
import random
import shutil

def load_urls_from_file(filepath="urls.txt"):
    import os
    if not os.path.exists(filepath):
        print(f"[Warning] {filepath} not found.")
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # Read lines, strip whitespace, ignore empty lines and commented lines
            urls = [
                line.strip() 
                for line in f 
                if line.strip() and not line.strip().startswith('#')
            ]
            
            # Remove duplicates while preserving order
            return list(dict.fromkeys(urls))
    except Exception as e:
        print(f"[Error] Failed to read {filepath}: {e}")
        return []

# Load URLs from urls.txt dynamically
URLS = load_urls_from_file("urls.txt")

PRICE_XPATH = '//*[@id="bottomDrawer"]/div[2]/ul/li[1]/div[1]/span'
AGE_XPATH = '//*[@id="bottomDrawer"]/div[2]/ul/li[1]/div[1]/a/div/p'
NAME_XPATH = '//*[@id="bottomDrawer"]/div[1]/div[1]/div/div/h3'
ADDRESS_XPATH = '//*[@id="bottomDrawer"]/div[1]/div[1]/div/div/div/p'
MAP_XPATH = '//*[@id="bottomDrawer"]/div[1]/div[1]/div/div/div/a'

def get_age_in_hours(date_text):
    """
    Parses a German age string like 'Letztes Update vor 2 Stunden' 
    and returns the approximate age in hours.
    """
    if not date_text:
        return 9999
        
    text = date_text.lower()
    
    # Minutes
    if 'minute' in text:
        return 0
        
    # Hours
    if 'stunde' in text:
        if 'einer' in text:
            return 1
        match = re.search(r'vor\s+(\d+)\s+stunden', text)
        if match:
            return int(match.group(1))
        return 1
        
    # Days
    if 'tag' in text:
        if 'einem' in text:
            return 24
        match = re.search(r'vor\s+(\d+)\s+tagen', text)
        if match:
            return int(match.group(1)) * 24
        return 24
    
    # Weeks
    if 'woche' in text:
        if 'einem' in text:
            return 168
        match = re.search(r'vor\s+(\d+)\s+wochen', text)
        if match:
            return int(match.group(1)) * 168
        return 168

    # Months
    if 'monat' in text:
        if 'einem' in text:
            return 730
        match = re.search(r'vor\s+(\d+)\s+monaten', text)
        if match:
            return int(match.group(1)) * 730
        return 730
        
    #Years - Definitely over 48h
    if 'jahr' in text:
        return 8760
        
    print(f"  [Warning] Unrecognized age format: '{date_text}'. Assuming >48h.")
    return 9999

def _run_scraper_logic():
    start_time = time.time()
    prices = []
    stations_data = []
    
    if not URLS:
        print("Please add some URLs to the URLS list.")
        return {"average_price": None, "valid_stations_count": 0, "stations": []}

    import os
    lock_file = os.path.join("downloaded_files", "driver_fixing.lock")
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
            print("  Removed redundant lock file before starting SeleniumBase.")
        except Exception as e:
            print(f"  Could not remove lock file: {e}")

        time.sleep(1)

    # Manage caching
    cache_dir = "chrome_cache"
    cache_time_file = "chrome_cache_time.txt"

    if os.path.exists(cache_dir):
        if os.path.exists(cache_time_file):
            try:
                with open(cache_time_file, "r") as f:
                    last_time = float(f.read().strip())
                # 7 days in seconds = 7 * 24 * 3600 = 604800
                if time.time() - last_time > 604800:
                    print("Cache is older than 7 days. Purging to clear space...")
                    shutil.rmtree(cache_dir, ignore_errors=True)
                    os.remove(cache_time_file)
            except Exception:
                shutil.rmtree(cache_dir, ignore_errors=True)
                if os.path.exists(cache_time_file):
                    os.remove(cache_time_file)
        else:
            shutil.rmtree(cache_dir, ignore_errors=True)
            
    if not os.path.exists(cache_time_file):
        with open(cache_time_file, "w") as f:
            f.write(str(time.time()))

    chrome_args = (
        "--host-rules=MAP *tcsmaps.ch 127.0.0.1, MAP fonts.googleapis.com 127.0.0.1, MAP fonts.gstatic.com 127.0.0.1,"
        "--disable-webgl,--disable-gpu,--disable-software-rasterizer,"
        "--js-flags=--max-old-space-size=256"
    )
    with SB(uc=True, headless=False, block_images=True, user_data_dir=cache_dir, chromium_arg=chrome_args) as sb:
        # Limit window size to reduce map tiles loaded
        sb.set_window_size(750, 750)
        
        print(f"Loading {len(URLS)} gas stations strictly sequentially to force RAM under 1GB...")
        
        for i, url in enumerate(URLS):
            try:
                print(f"Extracting data from station {i+1}/{len(URLS)} ({url}) ...")
                sb.uc_open(url)
                
                # Wait for the price element to be visible
                sb.wait_for_element_visible(PRICE_XPATH, timeout=10)
                
                price_text = sb.get_text(PRICE_XPATH)
                age_text = sb.get_text(AGE_XPATH)
                name_text = sb.get_text(NAME_XPATH)
                address_text = sb.get_text(ADDRESS_XPATH)
                map_href = sb.get_attribute(MAP_XPATH, "href")
                
                print(f"  Raw price text: '{price_text}'")
                print(f"  Raw age text:   '{age_text}'")
                print(f"  Name: {name_text}")
                
                age_hours = get_age_in_hours(age_text)
                
                # Extract float price
                price = None
                match = re.search(r'(\d+\.\d+)', price_text)
                if match:
                    price = float(match.group(1))
                    if age_hours > 48:
                        print(f"  [Old] Price >48h (approx. {age_hours}h). Kept in output, ignored for avg.")
                    else:
                        prices.append(price)
                        print(f"  [Added] Extracted price: {price}")
                else:
                    print("  [Error] Could not parse float price from text.")
                    
                # Extract coords from google maps link
                lat, lng = None, None
                if map_href:
                    coord_match = re.search(r'(-?\d+\.\d+)[,%](-?\d+\.\d+)', map_href)
                    if coord_match:
                        lat = float(coord_match.group(1))
                        lng = float(coord_match.group(2))
                
                station = {
                    "url": url,
                    "name": name_text,
                    "address": address_text,
                    "latitude": lat,
                    "longitude": lng,
                    "price": price,
                    "age_hours": age_hours
                }
                stations_data.append(station)
                    
            except Exception as e:
                print(f"  [Error] Could not extract from tab {i+1} ({url}): {e}")
            
            # Navigate cleanly away to instantly free the page memory
            sb.uc_open("about:blank")
                
    if prices:
        avg_price = sum(prices) / len(prices)
        valid_count = len(prices)
    else:
        # Fallback to the 3 newest stations
        valid_stations = [s for s in stations_data if s["price"] is not None]
        valid_stations.sort(key=lambda x: x["age_hours"])
        newest_3 = valid_stations[:3]
        if newest_3:
            avg_price = sum(s["price"] for s in newest_3) / len(newest_3)
            valid_count = len(newest_3)
            print("-" * 40)
            print(f"[Fallback] No stations under 48h found. Averaging the {valid_count} newest stations.")
        else:
            avg_price = None
            valid_count = 0
            
    if avg_price is not None:
        avg_price = round(avg_price, 4)
            
    execution_time = round(time.time() - start_time, 2)
            
    result = {
        "average_price": avg_price,
        "valid_stations_count": valid_count,
        "execution_time_seconds": execution_time,
        "stations": stations_data
    }
    
    if valid_count > 0:
        print("-" * 40)
        print(f"Successfully calculated average from {valid_count} gas stations.")
        if avg_price is not None:
            print(f"Average Diesel price: {avg_price:.4f}")
    else:
        print("-" * 40)
        print("No valid prices found.")
        
    return result

def scrape_gas_prices(retry=True):
    try:
        return _run_scraper_logic()
    except Exception as e:
        if retry:
            import os
            import shutil
            print(f"  [Error] Scraper crash detected: {e}")
            print("  Attempting to clear 'downloaded_files' folder and retry...")
            if os.path.exists("downloaded_files"):
                try:
                    shutil.rmtree("downloaded_files")
                    print("  Cleared 'downloaded_files' successfully.")
                except Exception as rme:
                    print(f"  Could not delete 'downloaded_files': {rme}")
            return scrape_gas_prices(retry=False)
        else:
            print(f"  [Fatal] Scraper failed again after retry: {e}")
            return {"average_price": None, "valid_stations_count": 0, "stations": []}

if __name__ == "__main__":
    import json
    data = scrape_gas_prices()
    print(json.dumps(data, indent=2, ensure_ascii=False))
