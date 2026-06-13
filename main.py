import os
import googlemaps
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))
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
	
	# Create reordered list
	return weekday_text[today_index:] + weekday_text[:today_index]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await update.message.reply_text(
		"Welcome to Restaurant Finder Bot!\n"
		"Send me a restaurant name and I will find nearby results for you."
	)

async def search_restaurant(update: Update, context: ContextTypes.DEFAULT_TYPE):
	query = update.message.text
	singapore_center = (1.3521, 103.8198)  # Singapore center coordinates
	radius = 30000  
	# Step 1 — Nearby search directly within Singapore
	nearby_results = gmaps.places_nearby(
		location=singapore_center,
		radius=radius,
		keyword=query
	)
	
	results = nearby_results.get("results", [])
	if not results:
		await update.message.reply_text("No nearby restaurants found in Singapore.")
		return
	
	# Step 2 — Filter results before looping
	relevant_types = {"restaurant", "cafe", "bakery", "bar", "meal_takeaway", "fast_food"}
	filtered_results = []
	for place in results:
		types = place.get("types", [])
		if any(t in relevant_types for t in types):
			filtered_results.append(place)
	
	results = filtered_results
	
	if not results:
		await update.message.reply_text("No nearby restaurants found in Singapore.")
		return
	
	reply_text = "Nearby results:\n"
	for i, place in enumerate(results[:5]):  # Limit to top 5
		reply_text += f"{i+1}. {place.get('name')} — {place.get('vicinity')}\n"
	
	# Step 3 — Get details for first two results
	def estimate_price_per_pax(price_level):
		mapping = {
			0: "Unknown",
			1: "Inexpensive (<$10 per pax)",
			2: "Moderate ($10–$30 per pax)",
			3: "Expensive ($30–$70 per pax)",
			4: "Very Expensive (>$70 per pax)"
		}
		return mapping.get(price_level, "Unknown")
	
	for idx in range(min(2, len(results))):
		place_id = results[idx]["place_id"]
		details = gmaps.place(
			place_id=place_id,
			fields=["name", "formatted_address", "rating", "opening_hours", "price_level"]
		)
		result = details.get("result", {})
	
		reply_text += f"\n--- Details for result {idx+1} ---\n"
		reply_text += f"Name: {result.get('name', 'Unknown')}\n"
		reply_text += f"Address: {result.get('formatted_address', 'Unknown')}\n"
	
		types = results[idx].get("types", [])
		filtered_types = [t for t in types if t in relevant_types]
		reply_text += f"Type: {', '.join(filtered_types) if filtered_types else 'Unknown'}\n"
	
		reply_text += f"Rating: {result.get('rating', 'Unknown')}\n"
		reply_text += f"Estimated price per pax: {estimate_price_per_pax(result.get('price_level', 0))}\n"
	
		if "opening_hours" in result:
			opening_hours = result["opening_hours"].get("weekday_text", [])
			reordered_hours = reorder_opening_hours(opening_hours)
			reply_text += "Opening Hours:\n"
			for line in reordered_hours:
				reply_text += f"  {line}\n"


	await update.message.reply_text(reply_text)

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_restaurant))

print("Bot running...")
app.run_polling()
