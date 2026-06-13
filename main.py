import os
import re
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler
from telegram.helpers import escape_markdown
from dotenv import load_dotenv
from datetime import datetime
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import certifi
from bson import ObjectId
import logging

load_dotenv()

GOOGLE_API_KEY = googlemaps.Client(key=os.getenv("GOOGLE_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- MongoDB Connection ---
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client["satisfiedTummy"]
restaurants_collection = db["restaurants"]

logging.basicConfig(level=logging.INFO)

# --- DB Connectivity Test ---
def test_database_connection():
	try:
		client.admin.command('ping')
		print("✅ MongoDB connection successful!")
		db_list = client.list_database_names()
		print("Databases:", db_list)
		collections = db.list_collection_names()
		print("Collections in 'satisfiedTummy':", collections)
	except Exception as e:
		print(f"❌ MongoDB connection failed: {e}")
	print()

test_database_connection()

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

def format_opening_hours(opening_hours) -> str:
	import re
	
	weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
	
	# Convert list like ["Monday: 8AM–5PM", ...] → dict
	if isinstance(opening_hours, list):
		hours_dict = {}
		for entry in opening_hours:
			match = re.match(r"(?i)(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*[:\-]?\s*(.+)", entry.strip())
			if match:
				hours_dict[match.group(1).capitalize()] = match.group(2).strip()
	else:
		hours_dict = dict(opening_hours)
	
	# Normalize values by removing day prefixes carefully
	cleaned = {}
	for day in weekdays:
		val = hours_dict.get(day, "Unknown")
		val = re.sub(rf"^{day}\s*[:\-]?\s*", "", val.strip(), flags=re.IGNORECASE)
		cleaned[day] = val.strip()
	
	hours_list = [cleaned.get(day, "Unknown") for day in weekdays]
	
	# Case 1: all same hours → "Daily: ..."
	if all(h == hours_list[0] for h in hours_list):
		return f"    Daily: {hours_list[0]}"
	
	# Case 2: group consecutive days with same hours
	grouped = []
	start_day = weekdays[0]
	prev_hours = hours_list[0]
	
	for i in range(1, 7):
		current_hours = hours_list[i]
		if current_hours != prev_hours:
			end_day = weekdays[i - 1]
			if start_day == end_day:
				grouped.append(f"{start_day}: {prev_hours}")
			else:
				grouped.append(f"{start_day} - {end_day}: {prev_hours}")
			start_day = weekdays[i]
			prev_hours = current_hours
	
	# Add last group
	end_day = weekdays[6]
	if start_day == end_day:
		grouped.append(f"{start_day}: {prev_hours}")
	else:
		grouped.append(f"{start_day} - {end_day}: {prev_hours}")
	
	return "\n".join([f"    {line}" for line in grouped])


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

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await update.message.reply_text(
		"👋 Welcome to *Satisfied Tummy Bot!*\n"
		"Send me a restaurant name and I’ll find it! No commands required.\n\n"
		"Other Commands:\n"
		"• /listrestaurants – Show all saved restaurants\n"
		"• /search <keyword> – Search for tags in saved database\n"
		"• /searchrest <keyword> – Search for specific restaurants saved db",
		parse_mode="Markdown"	
	)

async def send_long_message(update, blocks, parse_mode="MarkdownV2"):
	MAX_LEN = 4000
	buffer = ""
	
	for block in blocks:
		entry = block + "\n\n"
		if len(buffer) + len(entry) > MAX_LEN:
			await update.message.reply_text(buffer, parse_mode=parse_mode)
			buffer = ""
		buffer += entry
	
	if buffer:
		await update.message.reply_text(buffer, parse_mode=parse_mode)



async def search_restaurant(update: Update, context: ContextTypes.DEFAULT_TYPE):
	# DEBUG: log message arrival 
	print("=== Handler: search_restaurant called ===") ##debug
	print("Current state:", context.user_data.get("_conversation_state"))
	print("Incoming text:", repr(update.message.text if update.message else None)) ##debug
	if context.user_data.get("saved_restaurant_id"):
		print("Skipping search because user is tagging a restaurant")
		return ConversationHandler.END
	query = update.message.text
	if not GOOGLE_API_KEY:
		await update.message.reply_text("⚠ Missing Google API key.")
		return ConversationHandler.END
	singapore_center = {"latitude": 1.3521, "longitude": 103.8198}
	radius = 30000  
	
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
	try:
		response = requests.post(url, headers=headers, json=data, timeout=10)
		response.raise_for_status()
	except requests.RequestException as e:
		await update.message.reply_text(f"⚠ Error fetching results: {e}")
		return ConversationHandler.END
	
	results = response.json().get("places", [])
	if not results:
		await update.message.reply_text("No nearby restaurants found in Singapore.")
		return ConversationHandler.END
	
	relevant_types = {"restaurant", "cafe", "bakery", "bar", "meal_takeaway", "fast_food"}
	filtered_results = []
	for place in results:
		types = place.get("types", [])
		has_relevant_type = False
		for t in types:
			if t in relevant_types:
				has_relevant_type = True
				break
		has_name = place.get("displayName", {}).get("text")
		if has_relevant_type and has_name:
			filtered_results.append(place)
	if not filtered_results:
		await update.message.reply_text("No relevant restaurants found in Singapore.")
		return ConversationHandler.END
	
	reply_text = "🍽️ Nearby results:\n"
	context.user_data["search_results"] = []
	keyboard = []  
	button_count = 0
	for i, place in enumerate(filtered_results[:5]):
		name = escape_markdown(place["displayName"]["text"])
		addr = escape_markdown(place.get("formattedAddress", "Unknown"))
		types = [t for t in place.get("types", []) if t in relevant_types]
		types_text = escape_markdown(", ".join(types))
		rating = place.get("rating", "Unknown")
		price_level = place.get("priceLevel", 0)
		price_range = place.get("priceRange", {})
		
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
	
		loc = place.get("location", {})
		lat_lng = loc.get("latLng", {})
		lat = lat_lng.get("latitude")
		lng = lat_lng.get("longitude")
		if lat is None or lng is None:
			lat = loc.get("latitude")
			lng = loc.get("longitude")
	
		mrt_names = get_nearest_mrts(lat, lng, GOOGLE_API_KEY) if lat and lng else []
		mrt_text = escape_markdown(", ".join(mrt_names)) if mrt_names else "Unknown"
		
		maps_url = place.get("googleMapsUri", None)
	
		reservations = get_place_details(place["id"], GOOGLE_API_KEY)
		reservations_text = "Yes" if reservations else "No"
		hours = get_opening_hours(place["id"], GOOGLE_API_KEY)
		if hours:
			simplified_hours = format_opening_hours(hours)
			hours_text = escape_markdown(simplified_hours)
		else:
			hours_text = "Unknown"

		if maps_url:
			maps_md = f"[Maps Link]({maps_url})"
		else:
			maps_md = "No link available"
			
		existing = restaurants_collection.find_one({
			"name": place["displayName"]["text"],
			"address": place.get("formattedAddress", "Unknown")
		})
		
		reply_text += (
			f"\n{i+1}. 🏷️ *{name}*\n"
			f"📍 {addr}\n"
			f"🍽️ {types_text}\n"
			f"⭐ {rating} | 💰 {est_price}\n"
			f"🚇 {mrt_text}\n"
			f"Reservations: {reservations_text}\n"
			f"Opening Hours:\n{hours_text}\n"
			f"🔗 {maps_md}\n"
		)
		restaurant_data = {
			"name": name,
			"address": addr,
			"type": types,
			"rating": rating,
			"price_per_pax": est_price,
			"nearest_mrts": mrt_names,
			"reservations": reservations_text,
			"link": maps_url,
			"opening_hours": {
				day: hours[j]
				for j, day in enumerate(
					["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
				)
				if hours
			},
			"tags": [],
		}
		
		if existing:
			reply_text += "⚠️ *Already saved in database*\n"
		else:
			context.user_data["search_results"].append(restaurant_data)
			idx_in_search_results = len(context.user_data["search_results"]) - 1  # real index
			button_count += 1  # display count
			keyboard.append([
				InlineKeyboardButton(f"💾 Save #{i+1}", callback_data=f"save_restaurant_{idx_in_search_results}")
			])


	if keyboard:
		keyboard.append([InlineKeyboardButton("💾 Save None", callback_data="save_restaurant_none")])
		await update.message.reply_text(
			reply_text,
			parse_mode="Markdown",
			reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
		)
		return WAITING_SAVE
	else:
		await update.message.reply_text(reply_text, parse_mode="Markdown")
		await update.message.reply_text("✅ All results are already in your database — nothing new to save.")
		return None
	
	

async def save_restaurant(update: Update, context: ContextTypes.DEFAULT_TYPE):
	print("=== Handler: save_restaurant called ===")
	print("Current state:", context.user_data.get("_conversation_state"))
	try:
		query = update.callback_query
		print("callback_query.data:", query.data)
		await query.answer("Saving...")  # Answer callback first
		print("callback answered")
		# Extract which restaurant index to save
		data = query.data  # e.g. "save_restaurant_0"
		if query.data == "save_restaurant_none":
			await query.message.reply_text(
				"✅ No restaurants were saved. You can search again anytime."
			)
			# Clear any previous search results if you want
			context.user_data["search_results"] = []
			context.user_data["_conversation_state"] = None
			return ConversationHandler.END  
		match = re.match(r"save_restaurant_(\d+)", data)
		if not match:
			print("save_restaurant: invalid callback data:", query.data)
			await query.message.reply_text("⚠ Invalid selection.")
			return ConversationHandler.END
		
		index = int(match.group(1))
		search_results = context.user_data.get("search_results", [])
		print(f"🔹 Total search_results: {len(search_results)}, Selected index: {index}")
		
		if index >= len(search_results):
			print("save_restaurant: selected index out of range")
			await query.message.reply_text("⚠ Invalid restaurant index.")
			return ConversationHandler.END
		
		query_data = search_results[index]
		print(f"🔹 query_data: {query_data}")
		
		result = restaurants_collection.insert_one(query_data)
		print("Inserted ID:", result.inserted_id)
		
		saved_restaurant_id = result.inserted_id
		context.user_data["saved_restaurant_id"] = saved_restaurant_id
		context.user_data["_conversation_state"] = WAITING_TAGS
		print(f"✅ Restaurant saved with ID: {saved_restaurant_id}")
		# Ask user for tags next
		await query.message.reply_text(
			f"✅ Saved '{query_data['name']}' to your database.\n\n"
			"Please send me some tags for this restaurant (comma-separated), or /skip to skip tagging."
		)
		print(f"⚡ Triggered save_restaurant with data: {update.callback_query.data}")
		print("Conversation state after save_restaurant:", context.user_data.get("_conversation_state"))
		print("Current state (before return):", WAITING_TAGS)
		return WAITING_TAGS  # Move conversation to tag input step
		
	except Exception as e:
		print(f"❌ Exception in save_restaurant: {e}")
		await update.effective_message.reply_text(f"❌ Error saving restaurant: {e}")
		return ConversationHandler.END

async def add_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Receives tags and saves them to MongoDB."""
		print("=== Handler: add_tags called ===") ##debug
		print("Current state:", context.user_data.get("_conversation_state"))
		print("Incoming tag message:", repr(update.message.text if update.message else None)) ##debug
		print("context.user_data before add_tags:", context.user_data) ##debug
		

		tags_text = update.message.text.strip()
		saved_restaurant_id = context.user_data.get("saved_restaurant_id")
		print("saved_restaurant_id:", saved_restaurant_id)
		
		if tags_text.lower() in ("/skip", "skip"):
			await update.message.reply_text("⏩ Skipped adding tags.")
			context.user_data.pop("saved_restaurant_id", None)
			print("User skipped tagging. Cleaned context.user_data")
			return ConversationHandler.END
		
		if not saved_restaurant_id:
			await update.message.reply_text("⚠ Error: No restaurant found to add tags to.")
			print("No saved_restaurant_id found — aborting add_tags")
			return ConversationHandler.END
		
		tags = [tag.strip() for tag in tags_text.split(",") if tag.strip()]
		print("Parsed tags:", tags)

		try:
			res = restaurants_collection.update_one(
				{"_id": ObjectId(saved_restaurant_id)},
				{"$set": {"tags": tags}}
			)
			print("Mongo update result:", res.raw_result if hasattr(res, "raw_result") else res)
			await update.message.reply_text(f"✅ Tags added: {', '.join(tags)}")
			# Clean up user data
			context.user_data.pop("saved_restaurant_id", None)
			print("Tags saved successfully. context.user_data cleaned.")

		except Exception as e:
			await update.message.reply_text(f"❌ Failed to save tags: {e}")
			print("Exception while saving tags:", e)

		return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
	context.user_data.pop("saved_restaurant_id", None)
	await update.message.reply_text("❌ Cancelled tagging")
	return ConversationHandler.END
	
# --- DB COMMANDS ---	
async def list_restaurants(update: Update, context: ContextTypes.DEFAULT_TYPE):
	restaurants = list(restaurants_collection.find())
	if not restaurants:
		await update.message.reply_text("No restaurants saved yet.")
		return
	
	# Build lines of "Name — Address"
	lines = []
	for r in restaurants:
		name = r.get("name", "Unnamed")
		addr = r.get("address", "No address")
		lines.append(f"• {name} — {addr}")
	
	# Send in chunks to avoid message too long error
	chunk_size = 20  # lines per message, adjust if needed
	for i in range(0, len(lines), chunk_size):
		chunk_text = "\n".join(lines[i:i+chunk_size])
		await update.message.reply_text(chunk_text)


async def search_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
	if not context.args: #when user does not enter a keyword
		await update.message.reply_text("Usage: /searchdb <keyword>")
		return
	
	#if user types /searchdb sushi bar, context.args = ["sushi", "bar"]. need to merge lst into 1 string
	keyword = " ".join(context.args).lower() 
	query = { #search for the keyword in name, tags, type fields
		"$or": [
			{"name": {"$regex": keyword, "$options": "i"}}, #"$regex": match strings by patterns (eg. dev --> developer, device etc.)
			{"tags": {"$regex": keyword, "$options": "i"}}, #"$options": "i" means case insensitive
			{"type": {"$regex": keyword, "$options": "i"}},
		]
	}
	results = list(restaurants_collection.find(query))
	
	if not results: #list is empty --> no results
		await update.message.reply_text(f"No restaurants found for '{keyword}'.")
		return
	
	restaurant_blocks = []  # <-- list of blocks, one per restaurant
	for r in results:
		name = escape_markdown(r.get('name', 'Unnamed'), version=2)
		escaped_t = escape_markdown(t, version=2)
		types_list = r.get('type', [])
		types = ", ".join(escaped_t for t in types_list) #escaped_t for t in types_list means all escaped strings, ", ".join means join with comma and space
		rating = escape_markdown(str(r.get('rating', 'Unknown')), version=2)
		price = escape_markdown(r.get('price_per_pax', 'Unknown'), version=2)
		mrts = ", ".join(escape_markdown(m, version=2) for m in r.get('nearest_mrts', []))
		reservations = escape_markdown(r.get('reservations', 'Unknown'), version=2)
		tags = ", ".join(escape_markdown(t, version=2) for t in r.get('tags', []))
		block = (
			f"• *Name:* {name}\n"
			f"  *Type:* {types}\n"
			f"  *Rating:* {rating}\n"
			f"  *Price per pax:* {price}\n"
			f"  *Nearest MRTs:* {mrts}\n"
			f"  *Reservations:* {reservations}\n"
		)
		opening_hours = r.get('opening_hours', {})
		if opening_hours:
			simplified_hours = format_opening_hours(opening_hours)
			block += "  *Opening Hours:*\n"
			for line in simplified_hours.splitlines():
				if ":" in line:
					day_part, time_part = line.split(":", 1)
					block += f"    {escape_markdown(day_part.strip(), version=2)}: {escape_markdown(time_part.strip(), version=2)}\n"
				else:
					block += f"    {escape_markdown(line.strip(), version=2)}\n"
	
		block += f"  *Tags:* {tags}"
		restaurant_blocks.append(block)
	
	# Send all restaurants in chunks
	await send_long_message(update, restaurant_blocks, parse_mode="MarkdownV2")


SEARCHING, WAITING_SAVE, WAITING_TAGS = range(3)

conv_handler = ConversationHandler(
	entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, search_restaurant)],
	states={
		SEARCHING: [
			MessageHandler(filters.TEXT & ~filters.COMMAND, search_restaurant)
		],
		WAITING_SAVE: [
			#CallbackQueryHandler(save_restaurant, pattern=r"^save_restaurant_\d+$")
			CallbackQueryHandler(save_restaurant),
		],
		WAITING_TAGS: [
			MessageHandler(filters.TEXT & ~filters.COMMAND, add_tags)
			#CommandHandler("skip", add_tags),
		],
	},
	fallbacks=[CommandHandler("cancel", cancel)],
)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# --- Add ConversationHandler and other command handlers ---
app.add_handler(conv_handler)
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("listrestaurants", list_restaurants))
app.add_handler(CommandHandler("search", search_db))
app.add_handler(CommandHandler("cancel", cancel))


print("🤖 Bot running...")

logging.basicConfig(level=logging.INFO)

app.run_polling()


#Random python syntax 

#dictionary.get(key_defaultvalue) --> returns value of key (if key exists), if key does not exist, returns default value
