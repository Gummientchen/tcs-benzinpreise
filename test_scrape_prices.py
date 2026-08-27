import os
import tempfile
import pytest
import scrape_prices

def test_load_stations_from_file(tmp_path):
    sample_content = """
    # Comment line
    https://benzin.tcs.ch/de/station/1/DIESEL, Interlaken
    https://benzin.tcs.ch/de/station/2/DIESEL; Brienz
    https://benzin.tcs.ch/de/station/3/DIESEL
    
    # Duplicate with different or same region
    https://benzin.tcs.ch/de/station/1/DIESEL, Interlaken
    """
    test_file = tmp_path / "urls.txt"
    test_file.write_text(sample_content, encoding="utf-8")

    stations = scrape_prices.load_stations_from_file(str(test_file))
    assert len(stations) == 3
    assert stations[0] == {"url": "https://benzin.tcs.ch/de/station/1/DIESEL", "region": "Interlaken"}
    assert stations[1] == {"url": "https://benzin.tcs.ch/de/station/2/DIESEL", "region": "Brienz"}
    assert stations[2] == {"url": "https://benzin.tcs.ch/de/station/3/DIESEL", "region": "Default"}

def test_actual_urls_file_loading():
    """Verify loading existing urls.txt works cleanly without error."""
    stations = scrape_prices.load_stations_from_file("urls.txt")
    assert len(stations) > 0
    # Duplicate station KvdfclwysRmOUvHUHsTd should be deduplicated
    urls = [s["url"] for s in stations]
    assert len(urls) == len(set(urls))
    # Check regions exist
    regions = {s["region"] for s in stations}
    assert "Interlaken" in regions
    assert "Brienz" in regions

def test_calculate_weight():
    # Brand new: weight 1.0
    assert scrape_prices.calculate_weight(0) == 1.0
    # 48 hours: 1 / (1 + 1)^2 = 0.25
    assert scrape_prices.calculate_weight(48) == 0.25
    # 12 hours: 1 / (1 + 0.25)^2 = 0.64
    assert scrape_prices.calculate_weight(12) == 0.64
    # 720 hours (30 days)
    w_30d = scrape_prices.calculate_weight(720)
    assert w_30d > 0
    assert abs(w_30d - round(1.0 / 256, 6)) < 1e-5
    # > 720 hours: 0.0
    assert scrape_prices.calculate_weight(721) == 0.0
    assert scrape_prices.calculate_weight(1000) == 0.0
    assert scrape_prices.calculate_weight(None) == 0.0
    assert scrape_prices.calculate_weight(-5) == 0.0

def test_calculate_weighted_average_normal():
    stations = [
        {"name": "S1", "price": 2.00, "age_hours": 0, "weight": 1.0},
        {"name": "S2", "price": 1.00, "age_hours": 48, "weight": 0.25},
    ]
    # (2.00*1.0 + 1.00*0.25) / (1.0 + 0.25) = 2.25 / 1.25 = 1.80
    avg, count = scrape_prices.calculate_weighted_average(stations)
    assert count == 2
    assert avg == 1.80

def test_calculate_weighted_average_ignores_old_and_unpriced():
    stations = [
        {"name": "S1", "price": 1.80, "age_hours": 10, "weight": 0.70},
        {"name": "S2", "price": 1.50, "age_hours": 800, "weight": 0.0},  # weight 0 (old)
        {"name": "S3", "price": None, "age_hours": 5, "weight": 0.85},   # no price
    ]
    avg, count = scrape_prices.calculate_weighted_average(stations)
    assert count == 1
    assert avg == 1.80

def test_calculate_weighted_average_fallback():
    # All stations older than 30 days (weight 0)
    stations = [
        {"name": "S1", "price": 1.70, "age_hours": 750, "weight": 0.0},
        {"name": "S2", "price": 1.80, "age_hours": 800, "weight": 0.0},
        {"name": "S3", "price": 1.90, "age_hours": 900, "weight": 0.0},
        {"name": "S4", "price": 2.00, "age_hours": 1000, "weight": 0.0},
    ]
    # Fallback should average the 3 newest stations: S1 (1.70), S2 (1.80), S3 (1.90)
    # (1.70 + 1.80 + 1.90) / 3 = 1.80
    avg, count = scrape_prices.calculate_weighted_average(stations)
    assert count == 3
    assert avg == 1.80

def test_calculate_weighted_average_empty():
    avg, count = scrape_prices.calculate_weighted_average([])
    assert avg is None
    assert count == 0

def test_get_station_extremes_5day_filter():
    stations = [
        {"name": "CheapButOld", "price": 1.50, "age_hours": 150},      # > 120h (5 days)
        {"name": "CheapestIn5Days", "price": 1.75, "age_hours": 24},   # <= 120h
        {"name": "ExpensiveIn5Days", "price": 1.95, "age_hours": 12},  # <= 120h
    ]
    cheapest, most_expensive = scrape_prices.get_station_extremes(stations)
    assert cheapest["name"] == "CheapestIn5Days"
    assert cheapest["price"] == 1.75
    assert most_expensive["name"] == "ExpensiveIn5Days"
    assert most_expensive["price"] == 1.95

def test_get_station_extremes_tie_breaker():
    stations = [
        {"name": "StationOlder", "price": 1.75, "age_hours": 48},
        {"name": "StationFresher", "price": 1.75, "age_hours": 6},
    ]
    cheapest, most_expensive = scrape_prices.get_station_extremes(stations)
    # Lower age_hours wins tie-break
    assert cheapest["name"] == "StationFresher"

def test_get_station_extremes_fallback():
    # All stations older than 5 days (120h)
    stations = [
        {"name": "S1", "price": 1.70, "age_hours": 200},
        {"name": "S2", "price": 1.65, "age_hours": 300},
        {"name": "S3", "price": 1.85, "age_hours": 400},
        {"name": "S4_VeryOld", "price": 1.20, "age_hours": 900}, # Excluded from top 3 newest
    ]
    cheapest, most_expensive = scrape_prices.get_station_extremes(stations)
    # Candidates are top 3 newest: S1, S2, S3
    assert cheapest["name"] == "S2"
    assert cheapest["price"] == 1.65
    assert most_expensive["name"] == "S3"
    assert most_expensive["price"] == 1.85

def test_calculate_regional_stats():
    stations = [
        {"name": "S1", "region": "Brienz", "price": 1.70, "age_hours": 10, "weight": 0.8},
        {"name": "S2", "region": "Brienz", "price": 1.80, "age_hours": 20, "weight": 0.6},
        {"name": "S3", "region": "Interlaken", "price": 1.90, "age_hours": 5, "weight": 0.9},
    ]
    stats = scrape_prices.calculate_regional_stats(stations)
    assert "Brienz" in stats
    assert "Interlaken" in stats
    assert stats["Brienz"]["valid_stations_count"] == 2
    assert stats["Brienz"]["cheapest_station"]["name"] == "S1"
    assert stats["Brienz"]["most_expensive_station"]["name"] == "S2"
    assert stats["Interlaken"]["valid_stations_count"] == 1
    assert stats["Interlaken"]["cheapest_station"]["name"] == "S3"

def test_get_age_in_hours():
    assert scrape_prices.get_age_in_hours("Letztes Update vor 2 Stunden") == 2
    assert scrape_prices.get_age_in_hours("vor einer Stunde") == 1
    assert scrape_prices.get_age_in_hours("vor 10 Minuten") == 0
    assert scrape_prices.get_age_in_hours("vor 3 Tagen") == 72
    assert scrape_prices.get_age_in_hours("vor einem Tag") == 24
    assert scrape_prices.get_age_in_hours("vor 1 Woche") == 168
    assert scrape_prices.get_age_in_hours("vor einer Woche") == 168
    assert scrape_prices.get_age_in_hours("vor 2 Wochen") == 336
    assert scrape_prices.get_age_in_hours("vor einem Monat") == 730
    assert scrape_prices.get_age_in_hours("vor 1 Jahr") == 8760
    assert scrape_prices.get_age_in_hours("") == 9999
