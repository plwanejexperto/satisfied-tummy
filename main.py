import os
import requests
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

def get_nearest_mrts(lat, lng, api_key, radius=1000):
		url = "https://places.googleapis.com/v1/places:searchNearby"
		headers = {
			"Content-Type": "application/json",
			"X-Goog-Api-Key": api_key,
			"X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location"
		}
		data = {
			"includedTypes": ["subway_station"],
			"maxResultCount": 3,
			"rankPreference": "DISTANCE",
			"locationRestriction": {
				"circle": {
					"center": {"latitude": lat, "longitude": lng},
					"radius": radius
				}
			}
		}
		response = requests.post(url, headers=headers, json=data)
		if response.status_code != 200:
			return []
		return [p["displayName"]["text"] for p in response.json().get("places", [])]

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
		loc = place.get("location", {}).get("latLng", {})
		lat, lng = loc.get("latitude"), loc.get("longitude")
		mrt_names = get_nearest_mrts(lat, lng, GOOGLE_API_KEY) if lat and lng else []
		mrt_text = ", ".join(mrt_names) if mrt_names else "Unknown"
	
		reply_text += f"\n--- Details for result {idx+1} ---\n"
		reply_text += f"Name: {name}\n"
		reply_text += f"Address: {addr}\n"
		reply_text += f"Type: {', '.join(types)}\n"
		reply_text += f"Rating: {rating}\n"
		reply_text += f"Estimated price per pax: {est_price}\n"
		reply_text += f"Nearest MRT(s): {mrt_text}\n"
		reply_text += f"Link: {maps_url}\n"
		hours = get_opening_hours(place["id"], GOOGLE_API_KEY)
		if hours:
			reply_text += "Opening Hours:\n"
			for h in hours:
				reply_text += f"  {h}\n"
	
	await update.message.reply_text(reply_text)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_restaurant))

print("Bot running...")
app.run_polling()
