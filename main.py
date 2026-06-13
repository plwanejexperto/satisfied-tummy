import googlemaps
from dotenv import load_dotenv
import os

load_dotenv()

gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))

def estimate_price_per_pax(price_level):
	mapping = {
		0: "Unknown",
		1: "Inexpensive (<$10 per pax)",
		2: "Moderate ($10–$30 per pax)",
		3: "Expensive ($30–$70 per pax)",
		4: "Very Expensive (>$70 per pax)"
	}
	return mapping.get(price_level, "Unknown")

restaurant = input('Enter the restaurant name: ')

# Step 1 — Get coordinates for the restaurant
location_result = gmaps.geocode(restaurant)
if not location_result:
	print("Location not found.")
	exit()

location = location_result[0]["geometry"]["location"]
lat_lng = (location["lat"], location["lng"])
print("Coordinates:", lat_lng)

# Step 2 — Find nearby matching restaurants
nearby_results = gmaps.places_nearby(
	location=lat_lng,
	radius=100000,  # in meters
	keyword=restaurant
)

results = nearby_results.get("results", [])
if not results:
	print("No nearby restaurants found.")
	exit()

print("\nNearby Results:")
for i, place in enumerate(results):
	print(f"{i+1}. {place.get('name')} — {place.get('vicinity')}")

# Step 3 — Get details for the first two results (if available)
for idx in range(min(2, len(results))):
	place_id = results[idx]["place_id"]
	details = gmaps.place(place_id=place_id, fields=["name", "formatted_address", "rating", "opening_hours", "price_level"])
	result = details.get("result", {})

	print(f"\n--- Details for result {idx+1} ---")
	print("Name:", result.get("name", "Unknown"))
	print("Address:", result.get("formatted_address", "Unknown"))
	print("Rating:", result.get("rating", "Unknown"))
	print("Estimated price per pax:", estimate_price_per_pax(result.get("price_level", 0)))

	# Print all opening hours
	if "opening_hours" in result:
		print("Opening Hours:")
		for line in result["opening_hours"].get("weekday_text", []):
			print("  ", line)
