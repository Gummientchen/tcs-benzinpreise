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
]

PRICE_XPATH = '//*[@id="bottomDrawer"]/div[2]/ul/li[1]/div[1]/span'
AGE_XPATH = '//*[@id="bottomDrawer"]/div[2]/ul/li[1]/div[1]/a/div/p'

def get_age_in_hours(date_text):
    """
    Parses a German age string like 'Letztes Update vor 2 Stunden' 
    and returns the approximate age in hours.
    """
    text = date_text.lower()
    
    # Minutes
    if 'minute' in text:
        # even "vor 59 Minuten" is 0 hours (or ~1 hour), well under 48h
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
        
    # Weeks, Months, Years - Definitely over 48h
    if 'woche' in text or 'monat' in text or 'jahr' in text:
        return 9999
        
    # Default fallback (assume very old if we can't parse it)
    print(f"  [Warning] Unrecognized age format: '{date_text}'. Assuming >48h.")
    return 9999

def scrape_gas_prices():
    prices = []
    
    if not URLS:
        print("Please add some URLs to the URLS list.")
        return

    # uc=True uses Undetected ChromeDriver (good for bypassing protections)
    with SB(uc=True, headless=False) as sb:
        for i, url in enumerate(URLS):
            if i > 0:
                wait_time = random.uniform(0.3, 1.2)
                print(f"Waiting for {wait_time:.1f} seconds to avoid rate limits...")
                time.sleep(wait_time)
                
            try:
                print(f"Scraping {url} ...")
                sb.uc_open(url)
                
                # Wait for the price element to be visible
                sb.wait_for_element_visible(PRICE_XPATH, timeout=15)
                
                price_text = sb.get_text(PRICE_XPATH)
                age_text = sb.get_text(AGE_XPATH)
                
                print(f"  Raw price text: '{price_text}'")
                print(f"  Raw age text:   '{age_text}'")
                
                age_hours = get_age_in_hours(age_text)
                if age_hours > 48:
                    print(f"  [Ignored] Price is older than 48h (approx. {age_hours}h).")
                    continue
                
                # Extract float price
                match = re.search(r'(\d+\.\d+)', price_text)
                if match:
                    price = float(match.group(1))
                    prices.append(price)
                    print(f"  [Added] Extracted price: {price}")
                else:
                    print("  [Error] Could not parse float price from text.")
                    
            except Exception as e:
                print(f"  [Error] Could not scrape {url}: {e}")
                
    if prices:
        avg_price = sum(prices) / len(prices)
        print("-" * 40)
        print(f"Successfully scraped {len(prices)} valid gas stations.")
        print(f"Average Diesel price: {avg_price:.2f}")
        return avg_price
    else:
        print("-" * 40)
        print("No valid prices found under 48h.")
        return None

if __name__ == "__main__":
    scrape_gas_prices()
