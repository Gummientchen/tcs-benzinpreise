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

TARGET_FUELS = ["diesel", "bleifrei_95", "bleifrei_98"]

def parse_fuel_items(fuel_items_raw):
    """
    Parses raw extracted fuel items from the DOM and returns a normalized dictionary
    containing all target fuels ('diesel', 'bleifrei_95', 'bleifrei_98').
    Missing fuels will have price: None, age_hours: None, weight: 0.0.
    
    fuel_items_raw is a list of dicts: [{'fuel_text': '...', 'age_text': '...'}, ...]
    """
    fuels = {
        "diesel": {"price": None, "age_hours": None, "weight": 0.0},
        "bleifrei_95": {"price": None, "age_hours": None, "weight": 0.0},
        "bleifrei_98": {"price": None, "age_hours": None, "weight": 0.0}
    }
    
    for item in fuel_items_raw:
        fuel_text = item.get("fuel_text", "")
        age_text = item.get("age_text", "")
        
        fuel_lower = fuel_text.lower()
        matched_key = None
        if "diesel" in fuel_lower:
            matched_key = "diesel"
        elif "bleifrei 95" in fuel_lower or "95" in fuel_lower:
            matched_key = "bleifrei_95"
        elif "bleifrei 98" in fuel_lower or "98" in fuel_lower:
            matched_key = "bleifrei_98"
            
        if matched_key:
            price = None
            match = re.search(r'(\d+\.\d+)', fuel_text)
            if match:
                price = float(match.group(1))
            
            age_hours = get_age_in_hours(age_text)
            weight = calculate_weight(age_hours) if price is not None else 0.0
            
            fuels[matched_key] = {
                "price": price,
                "age_hours": age_hours if price is not None else None,
                "weight": weight
            }
            
    return fuels

def calculate_weight(age_hours, t0=WEIGHT_HALF_DECAY_HOURS, max_age_hours=PRICE_MAX_AGE_HOURS):
    """
    Inverse square decay weight calculation:
    weight = 1.0 / (1.0 + age_hours / t0) ** 2
    Cutoff at max_age_hours (default 720h / 30 days) returns 0.0.
    """
    if age_hours is None or age_hours > max_age_hours or age_hours < 0:
        return 0.0
    return round(1.0 / ((1.0 + float(age_hours) / float(t0)) ** 2), 6)

def calculate_weighted_average(stations, fuel_key="diesel"):
    """
    Calculates weighted average price and valid stations count for a specific fuel_key.
    Only stations with valid price and weight > 0 for fuel_key contribute.
    Falls back to the 3 newest stations if no station has weight > 0.
    Returns (avg_price, valid_count).
    """
    valid = []
    for s in stations:
        fuel_data = s.get("fuels", {}).get(fuel_key) if "fuels" in s else (s if fuel_key == "diesel" else None)
        if fuel_data and fuel_data.get("price") is not None and fuel_data.get("weight", 0) > 0:
            valid.append({
                "price": fuel_data["price"],
                "weight": fuel_data["weight"],
                "age_hours": fuel_data.get("age_hours", 9999)
            })
            
    if valid:
        total_weight = sum(item["weight"] for item in valid)
        if total_weight > 0:
            weighted_sum = sum(item["price"] * item["weight"] for item in valid)
            return round(weighted_sum / total_weight, 4), len(valid)

    # Fallback to the 3 newest stations with valid prices
    priced = []
    for s in stations:
        fuel_data = s.get("fuels", {}).get(fuel_key) if "fuels" in s else (s if fuel_key == "diesel" else None)
        if fuel_data and fuel_data.get("price") is not None:
            priced.append({
                "price": fuel_data["price"],
                "age_hours": fuel_data.get("age_hours", 9999)
            })
            
    priced.sort(key=lambda x: x.get("age_hours", 9999))
    newest_3 = priced[:3]
    if newest_3:
        avg = round(sum(item["price"] for item in newest_3) / len(newest_3), 4)
        return avg, len(newest_3)

    return None, 0

def get_station_extremes(stations, fuel_key="diesel", max_age_hours=EXTREMES_MAX_AGE_HOURS, fallback_count=3):
    """
    Finds cheapest_station and most_expensive_station for a specific fuel_key.
    Candidate pool: stations with valid price and age_hours <= max_age_hours (default 120h / 5 days).
    Fallback pool: top fallback_count newest stations with valid prices.
    Ties broken by freshest update (lowest age_hours).
    Returns (cheapest_station, most_expensive_station).
    """
    candidates = []
    for s in stations:
        fuel_data = s.get("fuels", {}).get(fuel_key) if "fuels" in s else (s if fuel_key == "diesel" else None)
        if fuel_data and fuel_data.get("price") is not None and fuel_data.get("age_hours", 9999) <= max_age_hours:
            candidates.append((s, fuel_data["price"], fuel_data.get("age_hours", 9999)))
            
    if not candidates:
        priced = []
        for s in stations:
            fuel_data = s.get("fuels", {}).get(fuel_key) if "fuels" in s else (s if fuel_key == "diesel" else None)
            if fuel_data and fuel_data.get("price") is not None:
                priced.append((s, fuel_data["price"], fuel_data.get("age_hours", 9999)))
        priced.sort(key=lambda x: x[2])
        candidates = priced[:fallback_count]
        
    if not candidates:
        return None, None

    cheapest_item = min(candidates, key=lambda x: (x[1], x[2]))
    most_expensive_item = max(candidates, key=lambda x: (x[1], -x[2]))
    return cheapest_item[0], most_expensive_item[0]

def calculate_fuels_stats(stations, fuel_keys=TARGET_FUELS):
    """
    Calculates average_price, valid_stations_count, cheapest_station,
    and most_expensive_station for each fuel type in fuel_keys.
    """
    fuels_stats = {}
    for fuel in fuel_keys:
        avg_price, valid_count = calculate_weighted_average(stations, fuel_key=fuel)
        cheapest, most_expensive = get_station_extremes(stations, fuel_key=fuel)
        fuels_stats[fuel] = {
            "average_price": avg_price,
            "valid_stations_count": valid_count,
            "cheapest_station": cheapest,
            "most_expensive_station": most_expensive
        }
    return fuels_stats

def calculate_regional_stats(stations, fuel_keys=TARGET_FUELS):
    """
    Groups stations by region and computes per-fuel stats.
    Returns dict: {region_name: {fuel_name: {...}, ...}, ...}
    """
    from collections import defaultdict
    by_region = defaultdict(list)
    for s in stations:
        region = s.get("region") or "Default"
        by_region[region].append(s)

    regions_stats = {}
    for region, reg_stations in by_region.items():
        regions_stats[region] = calculate_fuels_stats(reg_stations, fuel_keys=fuel_keys)
    return regions_stats

def _get_empty_result():
    empty_fuel_stat = {
        "average_price": None,
        "valid_stations_count": 0,
        "cheapest_station": None,
        "most_expensive_station": None
    }
    return {
        "average_price": None,
        "valid_stations_count": 0,
        "cheapest_station": None,
        "most_expensive_station": None,
        "fuels": {fuel: dict(empty_fuel_stat) for fuel in TARGET_FUELS},
        "regions": {},
        "stations": []
    }

def _run_scraper_logic():
    start_time = time.time()
    stations_data = []
    
    stations_config = load_stations_from_file("urls.txt")
    if not stations_config:
        print("Please add some URLs to the URLS list.")
        return _get_empty_result()

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
                
                name_text = sb.get_text(NAME_XPATH)
                address_text = sb.get_text(ADDRESS_XPATH)
                map_href = sb.get_attribute(MAP_XPATH, "href")
                
                # Extract all fuel items from the bottomDrawer in a single JS execution
                raw_fuel_items = sb.execute_script("""
                    const items = document.querySelectorAll('#bottomDrawer ul li.fuel-list-item');
                    return Array.from(items).map(li => {
                        const span = li.querySelector('div span');
                        const p = li.querySelector('a p');
                        return {
                            fuel_text: span ? span.textContent.trim() : '',
                            age_text: p ? p.textContent.trim() : ''
                        };
                    });
                """)
                
                # Fallback if JS query returns empty (e.g. classes differed)
                if not raw_fuel_items:
                    price_text = sb.get_text(PRICE_XPATH)
                    age_text = sb.get_text(AGE_XPATH)
                    raw_fuel_items = [{"fuel_text": f"Diesel : {price_text}", "age_text": age_text}]
                
                fuels = parse_fuel_items(raw_fuel_items)
                
                # Extract coords from google maps link
                lat, lng = None, None
                if map_href:
                    coord_match = re.search(r'(-?\d+\.\d+)[,%](-?\d+\.\d+)', map_href)
                    if coord_match:
                        lat = float(coord_match.group(1))
                        lng = float(coord_match.group(2))
                
                diesel_info = fuels.get("diesel", {})
                station = {
                    "url": url,
                    "name": name_text,
                    "address": address_text,
                    "region": region,
                    "latitude": lat,
                    "longitude": lng,
                    "price": diesel_info.get("price"),
                    "age_hours": diesel_info.get("age_hours"),
                    "weight": diesel_info.get("weight", 0.0),
                    "fuels": fuels
                }
                stations_data.append(station)
                
                print(f"  Name: {name_text} | Region: {region}")
                for f_key in TARGET_FUELS:
                    f_val = fuels.get(f_key, {})
                    if f_val.get("price") is not None:
                        print(f"    {f_key}: CHF {f_val['price']} (age ~{f_val.get('age_hours')}h, weight {f_val.get('weight', 0.0):.4f})")
                    else:
                        print(f"    {f_key}: N/A")
                    
            except Exception as e:
                print(f"  [Error] Could not extract from tab {i+1} ({url}): {e}")
            
            # Navigate cleanly away to instantly free the page memory
            sb.uc_open("about:blank")
                
    fuels_stats = calculate_fuels_stats(stations_data)
    regions_stats = calculate_regional_stats(stations_data)
    execution_time = round(time.time() - start_time, 2)
            
    diesel_stats = fuels_stats.get("diesel", {})
    result = {
        "average_price": diesel_stats.get("average_price"),
        "valid_stations_count": diesel_stats.get("valid_stations_count", 0),
        "cheapest_station": diesel_stats.get("cheapest_station"),
        "most_expensive_station": diesel_stats.get("most_expensive_station"),
        "fuels": fuels_stats,
        "regions": regions_stats,
        "execution_time_seconds": execution_time,
        "stations": stations_data
    }
    
    diesel_count = diesel_stats.get("valid_stations_count", 0)
    if diesel_count > 0:
        print("-" * 40)
        print(f"Successfully calculated multi-fuel statistics from {len(stations_data)} gas stations.")
        for f_key in TARGET_FUELS:
            f_stat = fuels_stats.get(f_key, {})
            print(f"  {f_key.upper()}: avg={f_stat.get('average_price')} (valid={f_stat.get('valid_stations_count')})")
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
            return _get_empty_result()

if __name__ == "__main__":
    import json
    data = scrape_gas_prices()
    print(json.dumps(data, indent=2, ensure_ascii=False))
