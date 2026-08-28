from seleniumbase import SB
import re
import time
import random
import shutil

WEIGHT_HALF_DECAY_HOURS = 48.0
PRICE_MAX_AGE_HOURS = 720.0  # 30 days
EXTREMES_MAX_AGE_HOURS = 120.0  # 5 days

def load_stations_from_file(filepath="urls.txt"):
    """
    Parses urls.txt supporting lines in formats:
    - URL, Region
    - URL; Region
    - URL (defaults region to 'Default')
    Ignores lines starting with '#' and empty lines.
    Deduplicates URLs while preserving order.
    Returns a list of dicts: [{'url': ..., 'region': ...}, ...]
    """
    import os
    if not os.path.exists(filepath):
        print(f"[Warning] {filepath} not found.")
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            stations = []
            seen_urls = set()
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Check for delimiter (, or ;)
                if ',' in line:
                    parts = line.split(',', 1)
                    url = parts[0].strip()
                    region = parts[1].strip() or "Default"
                elif ';' in line:
                    parts = line.split(';', 1)
                    url = parts[0].strip()
                    region = parts[1].strip() or "Default"
                else:
                    url = line
                    region = "Default"
                
                if url not in seen_urls:
                    seen_urls.add(url)
                    stations.append({"url": url, "region": region})
            return stations
    except Exception as e:
        print(f"[Error] Failed to read {filepath}: {e}")
        return []

def load_urls_from_file(filepath="urls.txt"):
    return [s["url"] for s in load_stations_from_file(filepath)]

# Load station configurations dynamically
STATIONS_CONFIG = load_stations_from_file("urls.txt")
URLS = [s["url"] for s in STATIONS_CONFIG]

# Diesel
PRICE_XPATH = '//*[@id="bottomDrawer"]/div[2]/ul/li[1]/div[1]/span'
AGE_XPATH = '//*[@id="bottomDrawer"]/div[2]/ul/li[1]/div[1]/a/div/p'
NAME_XPATH = '//*[@id="bottomDrawer"]/div[1]/div[1]/div/div/h3'
ADDRESS_XPATH = '//*[@id="bottomDrawer"]/div[1]/div[1]/div/div/div/p'
MAP_XPATH = '//*[@id="bottomDrawer"]/div[1]/div[1]/div/div/div/a'

## Need some functionality which can also extract Bleifrei 95 and Bleifrei 98+ (if available). this nees to happen with the same request so we do not increase the number of requests to the server.

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
        if 'einem' in text or 'einer' in text:
            return 168
        match = re.search(r'vor\s+(\d+)\s+wochen?', text)
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

def calculate_weight(age_hours, t0=WEIGHT_HALF_DECAY_HOURS, max_age_hours=PRICE_MAX_AGE_HOURS):
    """
    Inverse square decay weight calculation:
    weight = 1.0 / (1.0 + age_hours / t0) ** 2
    Cutoff at max_age_hours (default 720h / 30 days) returns 0.0.
    """
    if age_hours is None or age_hours > max_age_hours or age_hours < 0:
        return 0.0
    return round(1.0 / ((1.0 + float(age_hours) / float(t0)) ** 2), 6)

def calculate_weighted_average(stations):
    """
    Calculates weighted average price and valid stations count.
    Only stations with valid price and weight > 0 contribute.
    Falls back to the 3 newest stations if no station has weight > 0.
    Returns (avg_price, valid_count).
    """
    valid = [s for s in stations if s.get("price") is not None and s.get("weight", 0) > 0]
    if valid:
        total_weight = sum(s["weight"] for s in valid)
        if total_weight > 0:
            weighted_sum = sum(s["price"] * s["weight"] for s in valid)
            return round(weighted_sum / total_weight, 4), len(valid)

    # Fallback to the 3 newest stations with valid prices
    priced_stations = [s for s in stations if s.get("price") is not None]
    priced_stations.sort(key=lambda x: x.get("age_hours", 9999))
    newest_3 = priced_stations[:3]
    if newest_3:
        avg = round(sum(s["price"] for s in newest_3) / len(newest_3), 4)
        return avg, len(newest_3)

    return None, 0

def get_station_extremes(stations, max_age_hours=EXTREMES_MAX_AGE_HOURS, fallback_count=3):
    """
    Finds cheapest_station and most_expensive_station.
    Candidate pool: stations with valid price and age_hours <= max_age_hours (default 120h / 5 days).
    Fallback pool: top fallback_count newest stations with valid prices.
    Ties broken by freshest update (lowest age_hours).
    Returns (cheapest_station, most_expensive_station).
    """
    candidates = [
        s for s in stations 
        if s.get("price") is not None and s.get("age_hours", 9999) <= max_age_hours
    ]
    if not candidates:
        priced_stations = [s for s in stations if s.get("price") is not None]
        priced_stations.sort(key=lambda x: x.get("age_hours", 9999))
        candidates = priced_stations[:fallback_count]
        
    if not candidates:
        return None, None

    cheapest = min(candidates, key=lambda s: (s["price"], s.get("age_hours", 9999)))
    most_expensive = max(candidates, key=lambda s: (s["price"], -s.get("age_hours", 9999)))
    return cheapest, most_expensive

def calculate_regional_stats(stations):
    """
    Groups stations by region and computes:
    - average_price
    - valid_stations_count
    - cheapest_station
    - most_expensive_station
    Returns dict: {region_name: {...}, ...}
    """
    from collections import defaultdict
    by_region = defaultdict(list)
    for s in stations:
        region = s.get("region") or "Default"
        by_region[region].append(s)

    regions_stats = {}
    for region, reg_stations in by_region.items():
        avg_price, valid_count = calculate_weighted_average(reg_stations)
        cheapest, most_expensive = get_station_extremes(reg_stations)
        regions_stats[region] = {
            "average_price": avg_price,
            "valid_stations_count": valid_count,
            "cheapest_station": cheapest,
            "most_expensive_station": most_expensive
        }
    return regions_stats

def _run_scraper_logic():
    start_time = time.time()
    stations_data = []
    
    stations_config = load_stations_from_file("urls.txt")
    if not stations_config:
        print("Please add some URLs to the URLS list.")
        return {
            "average_price": None,
            "valid_stations_count": 0,
            "cheapest_station": None,
            "most_expensive_station": None,
            "regions": {},
            "stations": []
        }

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
        
        print(f"Loading {len(stations_config)} gas stations strictly sequentially to force RAM under 1GB...")
        
        for i, config_item in enumerate(stations_config):
            url = config_item["url"]
            region = config_item["region"]
            try:
                print(f"Extracting data from station {i+1}/{len(stations_config)} ({url}) ...")
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
                print(f"  Region: {region}")
                
                age_hours = get_age_in_hours(age_text)
                weight = calculate_weight(age_hours)
                
                # Extract float price
                price = None
                match = re.search(r'(\d+\.\d+)', price_text)
                if match:
                    price = float(match.group(1))
                    if weight <= 0:
                        print(f"  [Old] Price >30d (approx. {age_hours}h, weight 0). Kept in output, ignored for avg.")
                    else:
                        print(f"  [Added] Extracted price: {price} (age ~{age_hours}h, weight {weight:.4f})")
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
                    "region": region,
                    "latitude": lat,
                    "longitude": lng,
                    "price": price,
                    "age_hours": age_hours,
                    "weight": weight
                }
                stations_data.append(station)
                    
            except Exception as e:
                print(f"  [Error] Could not extract from tab {i+1} ({url}): {e}")
            
            # Navigate cleanly away to instantly free the page memory
            sb.uc_open("about:blank")
                
    avg_price, valid_count = calculate_weighted_average(stations_data)
    cheapest_station, most_expensive_station = get_station_extremes(stations_data)
    regions_stats = calculate_regional_stats(stations_data)
    execution_time = round(time.time() - start_time, 2)
            
    result = {
        "average_price": avg_price,
        "valid_stations_count": valid_count,
        "cheapest_station": cheapest_station,
        "most_expensive_station": most_expensive_station,
        "regions": regions_stats,
        "execution_time_seconds": execution_time,
        "stations": stations_data
    }
    
    if valid_count > 0:
        print("-" * 40)
        print(f"Successfully calculated weighted average from {valid_count} gas stations.")
        if avg_price is not None:
            print(f"Weighted Average Diesel price: {avg_price:.4f}")
        if cheapest_station:
            print(f"Cheapest station: {cheapest_station.get('name')} ({cheapest_station.get('price')}) in {cheapest_station.get('region')}")
        if most_expensive_station:
            print(f"Most expensive station: {most_expensive_station.get('name')} ({most_expensive_station.get('price')}) in {most_expensive_station.get('region')}")
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
            return {
                "average_price": None,
                "valid_stations_count": 0,
                "cheapest_station": None,
                "most_expensive_station": None,
                "regions": {},
                "stations": []
            }

if __name__ == "__main__":
    import json
    data = scrape_gas_prices()
    print(json.dumps(data, indent=2, ensure_ascii=False))
