"""
Kathmandu Guesthouse Website Checker
=====================================
Uses the modern Google Places API (New) to find guesthouses/hotels in Kathmandu
and flags those that have no website — your potential clients.

SETUP:
1. Get a free Google Maps API key:
   - Go to: https://console.cloud.google.com/
   - Create a project → Enable "Places API"
   - Go to Credentials → Create API Key
   - The free tier gives you $200/month credit (~5,000 searches free)

2. Install dependencies:
   pip install requests pandas openpyxl

3. Run:
   python kathmandu_scraper.py

OUTPUT:
- kathmandu_no_website_[timestamp].xlsx   — leads with no website (your targets)
- kathmandu_all_results_[timestamp].xlsx  — full list for reference
"""

import sys
import io
import requests
import time
import json
import pandas as pd
from datetime import datetime

# Configure standard output to use UTF-8 to prevent encoding crashes on Windows consoles
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── CONFIG ────────────────────────────────────────────────────────────────────
import os
# Dynamically load environment variables from local .env if present
if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

# Search terms to cast a wide net
SEARCH_QUERIES = [
    "guesthouse Kathmandu Nepal",
    "guest house Thamel Kathmandu",
    "budget hotel Thamel Kathmandu",
    "homestay Kathmandu Nepal",
    "lodge Kathmandu Nepal",
    "inn Kathmandu Nepal",
    "guesthouse Boudhanath Kathmandu",
    "guesthouse Pashupatinath Kathmandu",
    "guesthouse Lazimpat Kathmandu",
    "guesthouse Patan Nepal",
]

# Kathmandu city center coordinates
LATITUDE = 27.7172
LONGITUDE = 85.3240
RADIUS_METERS = 15000.0  # 15km radius covers all of Kathmandu valley

# ── API FUNCTIONS ─────────────────────────────────────────────────────────────

def text_search_new(query, page_token=None):
    """Search Google Places using the modern Places API (New) Text Search."""
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": (
            "places.id,"
            "places.displayName,"
            "places.formattedAddress,"
            "places.nationalPhoneNumber,"
            "places.websiteUri,"
            "places.rating,"
            "places.userRatingCount,"
            "places.businessStatus,"
            "places.googleMapsUri,"
            "nextPageToken"
        )
    }
    
    body = {
        "textQuery": query,
        "languageCode": "en",
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": LATITUDE,
                    "longitude": LONGITUDE
                },
                "radius": RADIUS_METERS
            }
        }
    }
    
    if page_token:
        body["pageToken"] = page_token
        
    try:
        resp = requests.post(url, headers=headers, json=body)
        return resp.json()
    except Exception as e:
        return {"error": {"message": str(e), "status": "REQUEST_FAILED"}}


def collect_places_new(query):
    """Collect all places for a query (handles pagination)."""
    places = []
    seen_ids = set()
    
    print(f"\n  Searching: '{query}'")
    
    # First page
    data = text_search_new(query)
    
    # Handle API errors immediately
    if "error" in data:
        err = data["error"]
        print(f"    ⚠️ Google API Error Status: {err.get('status', 'ERROR')}")
        print(f"    Error Details: {err.get('message', 'Unknown error')}")
        return places, seen_ids
        
    results = data.get("places", [])
    for place in results:
        pid = place.get("id")
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            places.append(place)
            
    print(f"    Found {len(results)} places (page 1)")
    
    # Next pages (Google allows pagination up to 3 pages total)
    for i in range(2):
        next_token = data.get("nextPageToken")
        if not next_token:
            break
            
        time.sleep(2.0)  # Safe delay for token activation
        data = text_search_new(query, page_token=next_token)
        
        if "error" in data:
            break
            
        new_places = data.get("places", [])
        new_count = 0
        for place in new_places:
            pid = place.get("id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                places.append(place)
                new_count += 1
                
        if new_count > 0:
            print(f"    +{new_count} more places (page {i+2})")
            
    return places, seen_ids


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if API_KEY == "YOUR_GOOGLE_MAPS_API_KEY_HERE" or not API_KEY:
        print("=" * 60)
        print("⚠️  Please add your Google Maps API key to this script.")
        print("   Open kathmandu_scraper.py and replace:")
        print('   API_KEY = "YOUR_GOOGLE_MAPS_API_KEY_HERE"')
        print("   with your actual key, then run again.")
        print("=" * 60)
        return

    print("=" * 60)
    print("  Kathmandu Guesthouse Website Checker (Places API New)")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Step 1: Collect unique places across all queries
    all_places = {}
    for query in SEARCH_QUERIES:
        places, ids = collect_places_new(query)
        for p in places:
            all_places[p["id"]] = p
        time.sleep(0.5)

    unique_count = len(all_places)
    print(f"\n{'─'*60}")
    print(f"  Total unique properties found: {unique_count}")
    print(f"{'─'*60}")

    if unique_count == 0:
        print("\n⚠️  No properties found. Please verify your Google API Key and status.")
        return

    # Step 2: Extract details
    results = []
    no_website_count = 0

    print(f"\n  Processing details for each property...")
    
    for i, (place_id, place) in enumerate(all_places.items(), 1):
        name = place.get("displayName", {}).get("text", "Unknown Guesthouse")
        website = place.get("websiteUri", "")
        phone = place.get("nationalPhoneNumber", "")
        address = place.get("formattedAddress", "")
        rating = place.get("rating", "")
        reviews = place.get("userRatingCount", "")
        maps_url = place.get("googleMapsUri", f"https://www.google.com/maps/place/?q=place_id:{place_id}")
        status = place.get("businessStatus", "OPERATIONAL")
        
        has_website = bool(website)
        
        if not has_website:
            no_website_count += 1
            print(f"  [{i}/{unique_count}] {name[:45]:<45} ← NO WEBSITE ✓")
        else:
            print(f"  [{i}/{unique_count}] {name[:45]:<45} (has website)")
        
        results.append({
            "Name": name,
            "Has Website": "Yes" if has_website else "No",
            "Website": website,
            "Phone": phone,
            "Address": address,
            "Rating": rating,
            "Total Reviews": reviews,
            "Business Status": status,
            "Google Maps": maps_url,
        })

    # Step 3: Save to Excel
    df_all = pd.DataFrame(results)
    df_no_website = df_all[df_all["Has Website"] == "No"].copy()
    
    # Sort by review count descending
    df_no_website["Total Reviews"] = pd.to_numeric(df_no_website["Total Reviews"], errors="coerce").fillna(0)
    df_no_website = df_no_website.sort_values("Total Reviews", ascending=False)
    df_all["Total Reviews"] = pd.to_numeric(df_all["Total Reviews"], errors="coerce").fillna(0)
    df_all = df_all.sort_values("Total Reviews", ascending=False)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    no_website_file = f"kathmandu_no_website_{timestamp}.xlsx"
    all_results_file = f"kathmandu_all_results_{timestamp}.xlsx"

    # Style the Excel output
    with pd.ExcelWriter(no_website_file, engine="openpyxl") as writer:
        df_no_website.to_excel(writer, index=False, sheet_name="No Website Leads")
        ws = writer.sheets["No Website Leads"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    with pd.ExcelWriter(all_results_file, engine="openpyxl") as writer:
        df_all.to_excel(writer, index=False, sheet_name="All Results")
        ws = writer.sheets["All Results"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    # Step 4: Summary
    print(f"\n{'=' * 60}")
    print(f"  ✅ DONE!")
    print(f"{'─' * 60}")
    print(f"  Total properties scanned:    {unique_count}")
    print(f"  Properties WITH websites:    {unique_count - no_website_count}")
    print(f"  Properties WITHOUT websites: {no_website_count}  ← your leads")
    print(f"{'─' * 60}")
    print(f"  📄 Leads file:   {no_website_file}")
    print(f"  📄 Full results: {all_results_file}")
    print(f"{'=' * 60}\n")

    # Print top 20 leads
    print("  TOP 20 LEADS (sorted by review count):\n")
    top20 = df_no_website.head(20)
    for _, row in top20.iterrows():
        reviews = int(row["Total Reviews"]) if row["Total Reviews"] else 0
        rating = row["Rating"] if row["Rating"] else "N/A"
        print(f"  • {row['Name']}")
        print(f"    Rating: {rating}/5  |  Reviews: {reviews}  |  Phone: {row['Phone']}")
        print(f"    {row['Address']}")
        print(f"    Maps: {row['Google Maps']}")
        print()


if __name__ == "__main__":
    main()
