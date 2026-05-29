import os
import sys
import io
import time
import requests
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file

# Flask backend core for LeadScout

app = Flask(__name__)

# Dynamically load environment variables from local .env if present
if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("API_KEY")

# Default coordinates for Kathmandu, Nepal
DEFAULT_LAT = 27.7172
DEFAULT_LNG = 85.3240
DEFAULT_RADIUS = 15000.0  # 15km

# In-memory storage for active search results (session-like behaviour for simplicity)
active_results = []

def search_places_api(query, lat=None, lng=None, radius=None, page_token=None):
    """Call Google Places API (New) Text Search."""
    if not API_KEY:
        return {"error": {"message": "Google Places API Key is missing. Please configure GOOGLE_MAPS_API_KEY in your Vercel Environment Variables or local .env file.", "status": "MISSING_API_KEY"}}
        
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
        "languageCode": "en"
    }
    
    # Only bias search to coordinates if explicitly provided (saves custom searches worldwide)
    if lat is not None and lng is not None and radius is not None:
        body["locationBias"] = {
            "circle": {
                "center": {
                    "latitude": lat,
                    "longitude": lng
                },
                "radius": radius
            }
        }
    
    if page_token:
        body["pageToken"] = page_token
        
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        return resp.json()
    except Exception as e:
        return {"error": {"message": str(e), "status": "CONNECTION_FAILED"}}

@app.route('/')
def index():
    """Render the dashboard UI."""
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def api_search():
    """Execute dynamic search and filtering."""
    global active_results
    data = request.json or {}
    
    query = data.get('query', '')
    location_name = data.get('locationName', 'Kathmandu')
    radius_km = float(data.get('radius', 15))
    filter_type = data.get('filterType', 'all')  # 'all' or 'no_website'
    
    if not query:
        return jsonify({"success": False, "error": "Search query is required"}), 400
        
    # Geographic settings
    lat, lng, radius_meters = None, None, None
    is_custom_nepal_city = False
    
    loc_clean = location_name.strip().lower()
    if 'pokhara' in loc_clean:
        lat, lng = 28.2096, 83.9856
        is_custom_nepal_city = True
    elif 'lalitpur' in loc_clean or 'patan' in loc_clean:
        lat, lng = 27.6744, 85.3240
        is_custom_nepal_city = True
    elif 'bhaktapur' in loc_clean:
        lat, lng = 27.6710, 85.4298
        is_custom_nepal_city = True
    elif 'chitwan' in loc_clean:
        lat, lng = 27.5260, 84.3489
        is_custom_nepal_city = True
    elif 'kathmandu' in loc_clean:
        lat, lng = DEFAULT_LAT, DEFAULT_LNG
        is_custom_nepal_city = True
        
    if is_custom_nepal_city:
        radius_meters = radius_km * 1000.0
        api_query = query
    else:
        # Append location to search text for robust global searching
        api_query = f"{query} in {location_name}" if location_name else query
        
    # Place collection
    places = []
    seen_ids = set()
    next_token = None
    
    # Fetch up to 3 pages (Google Places API limit for single search query)
    for page_idx in range(3):
        res = search_places_api(api_query, lat, lng, radius_meters, page_token=next_token)
        
        if "error" in res:
            err = res["error"]
            return jsonify({
                "success": False,
                "error": f"API Error: {err.get('message', 'Unknown error')} ({err.get('status', 'ERROR')})"
            }), 500
            
        page_places = res.get("places", [])
        for place in page_places:
            pid = place.get("id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                
                # Parse fields safely
                name = place.get("displayName", {}).get("text", "Unknown Business")
                website = place.get("websiteUri", "")
                phone = place.get("nationalPhoneNumber", "")
                address = place.get("formattedAddress", "")
                rating = place.get("rating", None)
                reviews = place.get("userRatingCount", 0)
                maps_url = place.get("googleMapsUri", f"https://www.google.com/maps/place/?q=place_id:{pid}")
                status = place.get("businessStatus", "OPERATIONAL")
                
                has_website = bool(website)
                
                places.append({
                    "id": pid,
                    "name": name,
                    "has_website": has_website,
                    "website": website,
                    "phone": phone,
                    "address": address,
                    "rating": rating,
                    "reviews": int(reviews),
                    "status": status,
                    "maps_url": maps_url
                })
                
        next_token = res.get("nextPageToken")
        if not next_token:
            break
        time.sleep(1.0) # Safe delay for token activation
        
    # Sort results by reviews count descending
    places = sorted(places, key=lambda x: x['reviews'], reverse=True)
    
    # Store globally for exporting
    active_results = places
    
    # Apply UI filter
    filtered_places = places
    if filter_type == 'no_website':
        filtered_places = [p for p in places if not p['has_website']]
        
    # Calculate stats
    total_found = len(places)
    no_website_count = sum(1 for p in places if not p['has_website'])
    coverage_rate = int(((total_found - no_website_count) / total_found * 100)) if total_found > 0 else 100
    
    return jsonify({
        "success": True,
        "results": filtered_places,
        "stats": {
            "total_found": total_found,
            "no_website": no_website_count,
            "has_website": total_found - no_website_count,
            "coverage_rate": coverage_rate,
            "estimated_value_usd": no_website_count * 500  # Estimate $500 per basic website client
        }
    })

@app.route('/api/pitch', methods=['POST'])
def api_pitch():
    """Generate custom tailored cold email and phone pitches for a lead using TDNI brand assets."""
    data = request.json or {}
    name = data.get('name', 'Business Owner')
    rating = data.get('rating', 'N/A')
    reviews = data.get('reviews', 0)
    address = data.get('address', 'your area')
    
    # Generate email pitch
    email_subject = f"Website concept & direct booking setup for {name} — TDNI Web Solutions"
    email_body = (
        f"Hi team at {name},\n\n"
        f"We are the consulting team at Tech Design Nepal International (TDNI). We were recently looking up "
        f"outstanding businesses in {address.split(',')[0] if address else 'Kathmandu'} and noticed your incredible customer reviews on Google Maps "
        f"({reviews} reviews with a rating of {rating}/5!). You clearly run a fantastic business that guests absolutely love.\n\n"
        f"However, I noticed that you don't have a website listed on your Google Maps profile. "
        f"Currently, potential customers searching online have to book through third-party platforms like "
        f"Booking.com or Agoda, which charge hefty commissions (up to 15-20% per booking).\n\n"
        f"At TDNI (https://techdesignnepal.com/), we specialize in building premium, elegant, and mobile-friendly websites "
        f"specifically engineered to help businesses like yours take direct bookings and save thousands in commission fees.\n\n"
        f"We have actually drafted a quick home page mockup concept for {name}. Would you be open to a "
        f"quick 5-minute call or a coffee to see how a direct-booking website could increase your profit margins this season?\n\n"
        f"You can reach us at contact@techdesignnepal.com or call/WhatsApp us directly at +977 9766386790.\n\n"
        f"Best regards,\n"
        f"The TDNI Team\n"
        f"Tech Design Nepal International (TDNI)\n"
        f"Phone/WhatsApp: +977 9766386790\n"
        f"Web: https://techdesignnepal.com/"
    )
    
    # Generate phone pitch
    phone_script = (
        f"\"Namaste! Am I speaking with the owner or manager of {name}?\n\n"
        f"[Wait for response]\n\n"
        f"Great! I'm calling from TDNI — Tech Design Nepal International. We are a premium local web design agency. "
        f"I'm reaching out because I saw you have a massive rating of {rating}/5 with {reviews} reviews on Google Maps. "
        f"First of all, congratulations on such excellent feedback from your guests!\n\n"
        f"I noticed that when tourists search for your business, you don't have a direct website "
        f"where they can view services and book. This means you might be losing a lot of bookings to Expedia or Booking.com, "
        f"who take big commission cuts.\n\n"
        f"At TDNI (techdesignnepal.com), we build high-quality direct booking websites specifically designed to save you from paying commissions. "
        f"Our design team is actually looking at a custom website mockup we drafted for {name} right now. Could I send you a preview link over WhatsApp, or maybe "
        f"swing by for a quick 5-minute chat? What time works best for you?\""
    )
    
    return jsonify({
        "success": True,
        "email_subject": email_subject,
        "email_body": email_body,
        "phone_script": phone_script
    })

@app.route('/api/export', methods=['POST'])
def api_export():
    """Export current active results to styled Excel using pandas/openpyxl."""
    global active_results
    data = request.json or {}
    filter_type = data.get('filterType', 'all')  # 'all' or 'no_website'
    
    if not active_results:
        return jsonify({"success": False, "error": "No active search results to export. Please perform a search first."}), 400
        
    export_list = active_results
    if filter_type == 'no_website':
        export_list = [p for p in active_results if not p['has_website']]
        
    if not export_list:
        return jsonify({"success": False, "error": "No leads match your export criteria."}), 400
        
    # Convert keys to user-friendly Excel column headers
    excel_data = []
    for p in export_list:
        excel_data.append({
            "Name": p["name"],
            "Has Website": "Yes" if p["has_website"] else "No",
            "Website Link": p["website"],
            "Phone": p["phone"],
            "Address": p["address"],
            "Rating": p["rating"] if p["rating"] is not None else "N/A",
            "Total Reviews": p["reviews"],
            "Business Status": p["status"],
            "Google Maps Link": p["maps_url"]
        })
        
    df = pd.DataFrame(excel_data)
    
    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"leadscout_{filter_type}_{timestamp}.xlsx"
    filepath = os.path.join(os.getcwd(), filename)
    
    # Style the Excel using openpyxl writer
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        sheet_name = "Leads (No Website)" if filter_type == 'no_website' else "All Search Results"
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        ws = writer.sheets[sheet_name]
        
        # Apply custom column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)
            
    # Send the file to the client and clean it up afterwards
    try:
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to send file: {str(e)}"}), 500

if __name__ == '__main__':
    # Run locally on standard port 5000
    app.run(host='127.0.0.1', port=5000, debug=True)
