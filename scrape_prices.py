from seleniumbase import SB
import re
import time
import random

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

    # uc=True uses Undetected ChromeDriver (good for bypassing protections)
    # user_data_dir creates a persistent profile folder so map tiles and assets are cached across runs
    with SB(uc=True, headless=False, block_images=True, chromium_arg="--host-rules=MAP *tcsmaps.ch 127.0.0.1, MAP fonts.googleapis.com 127.0.0.1, MAP fonts.gstatic.com 127.0.0.1") as sb:
        # Limit window size to reduce map tiles loaded
        sb.set_window_size(750, 750)
        
        print(f"Processing {len(URLS)} gas stations in batches of 5 to balance speed and RAM/CPU...")
        
        chunk_size = 3
        for c_idx in range(0, len(URLS), chunk_size):
            chunk = URLS[c_idx:c_idx+chunk_size]
            print(f"\n--- Starting Batch {c_idx//chunk_size + 1} ({len(chunk)} stations) ---")
            
            # 1. Trigger background tabs for this chunk
            for j, url in enumerate(chunk):
                global_i = c_idx + j
                if len(sb.driver.window_handles) == 1 and j == 0:
                    print(f"Loading {url} in main tab {global_i} (foreground)...")
                    sb.uc_open(url)
                else:
                    wait_time = random.uniform(0.1, 0.3)
                    time.sleep(wait_time)
                    print(f"Triggering {url} in background tab {global_i}...")
                    sb.driver.execute_cdp_cmd('Target.createTarget', {'url': url})
                    
            print("Waiting a moment for batch pages to load in parallel...")
            time.sleep(3)
            
            # 2. Map out which handle belongs to which URL in this chunk
            url_to_handle = {}
            for handle in sb.driver.window_handles:
                try:
                    sb.switch_to_window(handle)
                    current_url = sb.get_current_url()
                    for u in chunk:
                        if u in current_url:
                            url_to_handle[u] = handle
                            break
                except Exception:
                    pass
                    
            # 3. Extract the information sequentially for this chunk
            for j, url in enumerate(chunk):
                global_i = c_idx + j
                try:
                    handle = url_to_handle.get(url)
                    if not handle:
                        print(f"  [Error] Tab for station {global_i} not found!")
                        continue
                        
                    sb.switch_to_window(handle)
                    print(f"Extracting data from tab {global_i} ({url}) ...")
                    
                    # Wait for the price element to be visible
                    sb.wait_for_element_visible(PRICE_XPATH, timeout=5)
                    
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
                    print(f"  [Error] Could not extract from tab {global_i} ({url}): {e}")

            # 4. Cleanup Memory! Close all tabs except one
            handles = sb.driver.window_handles
            if len(handles) > 1:
                # Keep exactly 1 tab open so driver doesn't exit
                for handle in handles[1:]:
                    try:
                        sb.switch_to_window(handle)
                        sb.driver.close()
                    except Exception:
                        pass
                # Switch back to the ONLY remaining tab
                sb.switch_to_window(sb.driver.window_handles[0])
            
            # Navigate to about:blank to purge previous heavy DOM data before next batch
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
            
    result = {
        "average_price": avg_price,
        "valid_stations_count": valid_count,
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
