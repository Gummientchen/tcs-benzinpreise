from seleniumbase import SB
import re
import time
import random

# Add your gas station URLs here
URLS = [
    "https://benzin.tcs.ch/de/station/JwQAWr1Sfe9fcpN95c7M/DIESEL",
    "https://benzin.tcs.ch/de/station/5AgjxEi1MQ8NT0iwxnpI/DIESEL",
    "https://benzin.tcs.ch/de/station/nkzAu0SOg1ESa7AOluXc/DIESEL",
    "https://benzin.tcs.ch/de/station/xfwW7WAzyFxwgiYVuV7z/DIESEL",
    "https://benzin.tcs.ch/de/station/mdnS1f1kErsgoqRH8Y0Q/DIESEL",
    "https://benzin.tcs.ch/de/station/VANJJZTCA4xALxzpSCuo/DIESEL",
    "https://benzin.tcs.ch/de/station/KvdfclwysRmOUvHUHsTd/DIESEL",
    "https://benzin.tcs.ch/de/station/uizryh2cOKrZdEHFuVuu/DIESEL",
    "https://benzin.tcs.ch/de/station/8DBnMqYBTpoFl8giTDhF/DIESEL",
    "https://benzin.tcs.ch/de/station/O3T5nFJcxYAshHWDNZRs/DIESEL",
]

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

def scrape_gas_prices():
    prices = []
    stations_data = []
    
    if not URLS:
        print("Please add some URLs to the URLS list.")
        return {"average_price": None, "stations": []}

    # uc=True uses Undetected ChromeDriver (good for bypassing protections)
    # user_data_dir creates a persistent profile folder so map tiles and assets are cached across runs
    with SB(uc=True, headless=False, user_data_dir="chrome_profile") as sb:
        # Limit window size to reduce map tiles loaded
        sb.set_window_size(625, 790)
        
        # First, open all URLs concurrently
        print("Triggering all gas stations to load in parallel...")
        for i, url in enumerate(URLS):
            if i == 0:
                print(f"Loading {url} in tab {i} (foreground)...")
                sb.uc_open(url)
            else:
                wait_time = random.uniform(0.1, 0.3)
                time.sleep(wait_time)
                print(f"Triggering {url} in background tab {i}...")
                sb.execute_script(f"window.open('{url}', '_blank');")
            
        print("All tabs triggered. Waiting a moment for pages to load in parallel...")
        time.sleep(3)
        
        # Next, go through each tab and extract the information
        for i, url in enumerate(URLS):
            try:
                sb.switch_to_window(i)
                print(f"Extracting data from tab {i} ({url}) ...")
                
                # Wait for the price element to be visible
                sb.wait_for_element_visible(PRICE_XPATH, timeout=15)
                
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
                print(f"  [Error] Could not extract from tab {i} ({url}): {e}")
                
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
            
    result = {
        "average_price": avg_price,
        "valid_stations_count": valid_count,
        "stations": stations_data
    }
    
    if valid_count > 0:
        print("-" * 40)
        print(f"Successfully calculated average from {valid_count} gas stations.")
        if avg_price is not None:
            print(f"Average Diesel price: {avg_price:.2f}")
    else:
        print("-" * 40)
        print("No valid prices found.")
        
    return result

if __name__ == "__main__":
    import json
    data = scrape_gas_prices()
    print(json.dumps(data, indent=2, ensure_ascii=False))
