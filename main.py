import os
import re
import requests
import math
import googlemaps
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

GOOGLE_API_KEY = googlemaps.Client(key=os.getenv("GOOGLE_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

def estimate_price_per_pax(price_level):
	mapping = {
		0: "Unknown",
		1: "Inexpensive (<$10 per pax)",
		2: "Moderate ($10–$30 per pax)",
		3: "Expensive ($30–$70 per pax)",
		4: "Very Expensive (>$70 per pax)"
	}
	return mapping.get(price_level, "Unknown")

def reorder_opening_hours(weekday_text):
	days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
	today_index = datetime.today().weekday()  # Monday=0, Sunday=6
	return weekday_text[today_index:] + weekday_text[:today_index]

def get_place_price_range(place_id, api_key):
	"""Get actual price range for a place from Google Places API v1."""
	url = f"https://places.googleapis.com/v1/places/{place_id}"
	headers = {
		"Content-Type": "application/json",
		"X-Goog-Api-Key": api_key,
		"X-Goog-FieldMask": "priceRange"
	}
	response = requests.get(url, headers=headers)
	if response.status_code != 200:
		return None
	
	data = response.json()
	price_range = data.get("priceRange")
	if not price_range:
		return None
	
	start_price = price_range.get("startPrice", {}).get("units")
	end_price = price_range.get("endPrice", {}).get("units")
	
	if start_price and end_price:
		return f"${start_price}–${end_price}"
	elif start_price:
		return f"From ${start_price}"
	elif end_price:
		return f"Up to ${end_price}"
	else:
		return None
		
def get_nearest_mrts(lat, lng, api_key, radius=2000, max_results=3, debug=False, timeout=8):
		if not api_key or lat is None or lng is None:
			return []
		
		from math import radians, cos, sin, asin, sqrt
		def _haversine_m(lat1, lon1, lat2, lon2):
			R = 6371000
			dlat = radians(lat2 - lat1)
			dlon = radians(lon2 - lon1)
			a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
			c = 2 * asin(sqrt(a))
			return R * c
		
		def _parse_results(data):
			out = []
			for r in data.get("results", []):
				place_types = r.get("types", [])
				name = r.get("name") or ""
				geom = r.get("geometry", {}).get("location", {})
				plat, plng = geom.get("lat"), geom.get("lng")
				if plat is None or plng is None:
					continue
				dist = _haversine_m(lat, lng, plat, plng)
				# MRT filter
				if ("subway_station" in place_types) or any(w in name.lower() for w in ["mrt", "station", "lrt"]):
					out.append((name, dist))
			return out
		
		def clean_mrt_results(results):
			seen = {}
			clean = []
			
			def normalize_name(name):
				name = name.lower()
				# Remove "Exit X"
				name = re.sub(r"exit\s*\w+", "", name)
				# Remove parentheses and their contents
				name = re.sub(r"\(.*?\)", "", name)
				# Remove common station suffixes
				name = re.sub(r"\b(mrt|lrt|station)\b", "", name)
				# Remove station codes like TE15
				name = re.sub(r"\b[a-z]{1,3}\d{1,3}\b", "", name)
				# Remove extra whitespace
				name = re.sub(r"\s+", " ", name).strip()
				return name
			
			for name, dist in results:
				clean_name = normalize_name(name)
				if clean_name not in seen or dist < seen[clean_name][1]:
					seen[clean_name] = (clean_name.title(), dist)  # store cleaned name
			
			for v in seen.values():
				clean.append(v)
			return clean

		
		legacy_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
		all_results = []
		
		keywords = ["MRT station", "MRT/LRT Station", "subway_station", "transit_station"]
		for kw in keywords:
			params = {
				"location": f"{lat},{lng}",
				"rankby": "distance",
				"keyword": kw,
				"key": api_key
			}
			try:
				resp = requests.get(legacy_url, params=params, timeout=timeout)
				if resp.status_code == 200:
					data = resp.json()
					all_results.extend(_parse_results(data))
			except Exception as e:
				if debug:
					print(f"Rankby request failed for keyword '{kw}':", e)
		# Remove "Vivocity Sentosa Express" explicitly
		all_results = [r for r in all_results if "vivocity" not in r[0].lower()]
		
		# Sort by distance and deduplicate
		all_results.sort(key=lambda x: x[1])
		all_results = clean_mrt_results(all_results)
		# Filter: MRT stations within 500m
		mrts_within_500m = [f"{name} ({int(dist)} m)" for name, dist in all_results if dist <= 500]
		
		if mrts_within_500m:
			return mrts_within_500m
		elif all_results:
			# Show only the nearest MRT if none within 500m
			name, dist = all_results[0]
			return [f"{name} ({int(dist)} m)"]
		
		return [f"{name} ({int(dist)} m)" for name, dist in all_results[:max_results]]


def get_opening_hours(place_id, api_key):
		url = f"https://places.googleapis.com/v1/places/{place_id}"
		headers = {
			"Content-Type": "application/json",
			"X-Goog-Api-Key": api_key,
			"X-Goog-FieldMask": "regularOpeningHours.weekdayDescriptions"
		}
		r = requests.get(url, headers=headers)
		if r.status_code != 200:
			return []
		data = r.json().get("regularOpeningHours", {}).get("weekdayDescriptions", [])
		return data

def get_place_details(place_id, api_key):
		url = f"https://places.googleapis.com/v1/places/{place_id}"
		headers = {
			"Content-Type": "application/json",
			"X-Goog-Api-Key": api_key,
			"X-Goog-FieldMask": "reservable"
		}
		r = requests.get(url, headers=headers)
		if r.status_code != 200:
			return None
		return r.json().get("reservable")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await update.message.reply_text(
		"Welcome to Restaurant Finder Bot!\n"
		"Send me a restaurant name and I will find nearby results for you."
	)

async def search_restaurant(update: Update, context: ContextTypes.DEFAULT_TYPE):
	query = update.message.text
	singapore_center = {"latitude": 1.3521, "longitude": 103.8198}
	radius = 30000  
	
	# Step 1 — Nearby search using Places API v1
	url = "https://places.googleapis.com/v1/places:searchText"
	headers = {
		"Content-Type": "application/json",
		"X-Goog-Api-Key": GOOGLE_API_KEY,
		"X-Goog-FieldMask": (
			"places.id,places.displayName,places.formattedAddress,"
			"places.types,places.location,places.rating,places.priceLevel,places.priceRange,places.googleMapsUri"
		)
	}
	data = {
		"textQuery": query,
		"locationBias": {
			"circle": {
				"center": singapore_center,
				"radius": radius
			}
		}
	}
	
	response = requests.post(url, headers=headers, json=data)
	if response.status_code != 200:
		await update.message.reply_text("Error fetching results from Google Places API.")
		return
	
	results = response.json().get("places", [])
	if not results:
		await update.message.reply_text("No nearby restaurants found in Singapore.")
		return
	
	# Step 2 — Filter relevant places
	relevant_types = {"restaurant", "cafe", "bakery", "bar", "meal_takeaway", "fast_food"}
	filtered_results = [
		p for p in results 
		if any(t in relevant_types for t in p.get("types", []))
		and p.get("displayName", {}).get("text")
	]
	if not filtered_results:
		await update.message.reply_text("No relevant restaurants found in Singapore.")
		return
	
	reply_text = "Nearby results:\n"
	for i, place in enumerate(filtered_results[:5]):
		name = place["displayName"]["text"]
		addr = place.get("formattedAddress", "Unknown")
		reply_text += f"{i+1}. {name} — {addr}\n"
	
	# Step 3 — Detailed info for first two
	for idx, place in enumerate(filtered_results[:2]):
		name = place["displayName"]["text"]
		addr = place.get("formattedAddress", "Unknown")
		types = [t for t in place.get("types", []) if t in relevant_types]
		rating = place.get("rating", "Unknown")
		price_level = place.get("priceLevel", 0)
		price_range = place.get("priceRange", {})
		maps_url = place.get("googleMapsUri", "No link available")
	
		# Extract priceRange if present
		if price_range:
			start = price_range.get("startPrice", {}).get("units")
			end = price_range.get("endPrice", {}).get("units")
			if start and end:
				est_price = f"${start}–${end}"
			elif start:
				est_price = f"From ${start}"
			elif end:
				est_price = f"Up to ${end}"
			else:
				est_price = estimate_price_per_pax(price_level)
		else:
			est_price = estimate_price_per_pax(price_level)
	
		# Get nearest MRTs
		loc = place.get("location", {})
		lat_lng = loc.get("latLng", {})
		lat = lat_lng.get("latitude")
		lng = lat_lng.get("longitude")
		
		if lat is None or lng is None:
			# Try a fallback if latLng missing
			lat = loc.get("latitude")
			lng = loc.get("longitude")
		mrt_names = get_nearest_mrts(lat, lng, GOOGLE_API_KEY) if lat and lng else []
		mrt_text = ", ".join(mrt_names) if mrt_names else "Unknown"
		
		reservations = get_place_details(place["id"], GOOGLE_API_KEY)
		if reservations is None:
			reservations_text = "Unknown"
		else:
			reservations_text = "Yes" if reservations else "No"
	
		reply_text += f"\n--- Details for result {idx+1} ---\n"
		reply_text += f"Name 🏷️: {name}\n"
		reply_text += f"Address 📍: {addr}\n"
		reply_text += f"Type 🍽️: {', '.join(types)}\n"
		reply_text += f"Rating ⭐: {rating}\n"
		reply_text += f"Estimated price per pax 💰: {est_price}\n"
		reply_text += f"Nearest MRT/LRT(s) 🚇: {mrt_text}\n"
		reply_text += f"Reservations available 📅: {reservations_text}\n"
		reply_text += f"Link 🔗: {maps_url}\n"
		hours = get_opening_hours(place["id"], GOOGLE_API_KEY)
		if hours:
			reply_text += "Opening Hours ⏰:\n"
			for h in hours:
				reply_text += f"  {h}\n"
	
	await update.message.reply_text(reply_text)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_restaurant))

print("Bot running...")
app.run_polling()
