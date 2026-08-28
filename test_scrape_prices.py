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

def test_parse_fuel_items_all_fuels():
    raw_items = [
        {"fuel_text": "Diesel : CHF/l 2.23", "age_text": "Letztes Update vor 4 Stunden"},
        {"fuel_text": "Bleifrei 95 : CHF/l 1.97", "age_text": "Letztes Update vor 4 Stunden"},
        {"fuel_text": "Bleifrei 98+ : CHF/l 2.10", "age_text": "Letztes Update vor 4 Stunden"}
    ]
    fuels = scrape_prices.parse_fuel_items(raw_items)
    assert fuels["diesel"]["price"] == 2.23
    assert fuels["diesel"]["age_hours"] == 4
    assert fuels["diesel"]["weight"] > 0

    assert fuels["bleifrei_95"]["price"] == 1.97
    assert fuels["bleifrei_95"]["age_hours"] == 4
    assert fuels["bleifrei_95"]["weight"] > 0

    assert fuels["bleifrei_98"]["price"] == 2.10
    assert fuels["bleifrei_98"]["age_hours"] == 4
    assert fuels["bleifrei_98"]["weight"] > 0

def test_parse_fuel_items_missing_98_and_unexpected_fuels():
    raw_items = [
        {"fuel_text": "Diesel : CHF/l 2.20", "age_text": "Letztes Update vor 6 Tagen"},
        {"fuel_text": "Bleifrei 95 : CHF/l 1.94", "age_text": "Letztes Update vor 6 Tagen"},
        {"fuel_text": "Erdgas / CNG : CHF/kg 1.85", "age_text": "Letztes Update vor 1 Tag"}
    ]
    fuels = scrape_prices.parse_fuel_items(raw_items)
    assert fuels["diesel"]["price"] == 2.20
    assert fuels["diesel"]["age_hours"] == 144

    assert fuels["bleifrei_95"]["price"] == 1.94
    assert fuels["bleifrei_95"]["age_hours"] == 144

    # Missing Bleifrei 98+ should have null fields
    assert fuels["bleifrei_98"]["price"] is None
    assert fuels["bleifrei_98"]["age_hours"] is None
    assert fuels["bleifrei_98"]["weight"] == 0.0

def test_calculate_weighted_average_multi_fuel():
    stations = [
        {
            "name": "S1",
            "fuels": {
                "diesel": {"price": 2.00, "age_hours": 0, "weight": 1.0},
                "bleifrei_95": {"price": 1.80, "age_hours": 0, "weight": 1.0},
                "bleifrei_98": {"price": 1.90, "age_hours": 0, "weight": 1.0}
            }
        },
        {
            "name": "S2",
            "fuels": {
                "diesel": {"price": 1.00, "age_hours": 48, "weight": 0.25},
                "bleifrei_95": {"price": 1.60, "age_hours": 48, "weight": 0.25},
                "bleifrei_98": {"price": None, "age_hours": None, "weight": 0.0}
            }
        }
    ]
    # Diesel: (2.0*1.0 + 1.0*0.25) / 1.25 = 1.80
    d_avg, d_cnt = scrape_prices.calculate_weighted_average(stations, fuel_key="diesel")
    assert d_cnt == 2
    assert d_avg == 1.80

    # Bleifrei 95: (1.80*1.0 + 1.60*0.25) / 1.25 = (1.80 + 0.40) / 1.25 = 2.20 / 1.25 = 1.76
    b95_avg, b95_cnt = scrape_prices.calculate_weighted_average(stations, fuel_key="bleifrei_95")
    assert b95_cnt == 2
    assert b95_avg == 1.76

    # Bleifrei 98: only S1 has valid price
    b98_avg, b98_cnt = scrape_prices.calculate_weighted_average(stations, fuel_key="bleifrei_98")
    assert b98_cnt == 1
    assert b98_avg == 1.90

def test_calculate_weighted_average_fallback():
    # All stations older than 30 days (weight 0)
    stations = [
        {"name": "S1", "fuels": {"diesel": {"price": 1.70, "age_hours": 750, "weight": 0.0}}},
        {"name": "S2", "fuels": {"diesel": {"price": 1.80, "age_hours": 800, "weight": 0.0}}},
        {"name": "S3", "fuels": {"diesel": {"price": 1.90, "age_hours": 900, "weight": 0.0}}},
        {"name": "S4", "fuels": {"diesel": {"price": 2.00, "age_hours": 1000, "weight": 0.0}}},
    ]
    # Fallback should average the 3 newest stations: S1 (1.70), S2 (1.80), S3 (1.90)
    avg, count = scrape_prices.calculate_weighted_average(stations, fuel_key="diesel")
    assert count == 3
    assert avg == 1.80

def test_get_station_extremes_multi_fuel():
    stations = [
        {
            "name": "S1",
            "fuels": {
                "diesel": {"price": 2.20, "age_hours": 24},
                "bleifrei_95": {"price": 1.95, "age_hours": 24},
                "bleifrei_98": {"price": 2.10, "age_hours": 24}
            }
        },
        {
            "name": "S2",
            "fuels": {
                "diesel": {"price": 2.10, "age_hours": 12},
                "bleifrei_95": {"price": 2.00, "age_hours": 12},
                "bleifrei_98": {"price": 2.05, "age_hours": 12}
            }
        }
    ]
    # Diesel cheapest S2 (2.10), most expensive S1 (2.20)
    d_cheap, d_exp = scrape_prices.get_station_extremes(stations, fuel_key="diesel")
    assert d_cheap["name"] == "S2"
    assert d_exp["name"] == "S1"

    # Bleifrei 95 cheapest S1 (1.95), most expensive S2 (2.00)
    b95_cheap, b95_exp = scrape_prices.get_station_extremes(stations, fuel_key="bleifrei_95")
    assert b95_cheap["name"] == "S1"
    assert b95_exp["name"] == "S2"

def test_calculate_regional_stats_multi_fuel():
    stations = [
        {
            "name": "S1",
            "region": "Brienz",
            "fuels": {
                "diesel": {"price": 2.10, "age_hours": 10, "weight": 0.8},
                "bleifrei_95": {"price": 1.90, "age_hours": 10, "weight": 0.8},
                "bleifrei_98": {"price": 2.00, "age_hours": 10, "weight": 0.8}
            }
        },
        {
            "name": "S2",
            "region": "Interlaken",
            "fuels": {
                "diesel": {"price": 2.20, "age_hours": 5, "weight": 0.9},
                "bleifrei_95": {"price": 1.95, "age_hours": 5, "weight": 0.9},
                "bleifrei_98": {"price": None, "age_hours": None, "weight": 0.0}
            }
        }
    ]
    stats = scrape_prices.calculate_regional_stats(stations)
    assert "Brienz" in stats
    assert "Interlaken" in stats
    assert stats["Brienz"]["diesel"]["valid_stations_count"] == 1
    assert stats["Brienz"]["bleifrei_95"]["valid_stations_count"] == 1
    assert stats["Brienz"]["bleifrei_98"]["valid_stations_count"] == 1
    assert stats["Interlaken"]["bleifrei_98"]["valid_stations_count"] == 0

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
