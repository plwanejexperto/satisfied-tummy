import googlemaps
from dotenv import load_dotenv
import os

load_dotenv()

gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))

restaurant = input('Enter the restaurant name: ')
search = gmaps.places(query=restaurant)
place_id = search["results"][0]["place_id"]
place_id2 = search["results"][1]["place_id"]
#print(place_id)

details = gmaps.place(place_id=place_id, fields=["name", "formatted_address", "rating", "opening_hours", "price_level"])

def estimate_price_per_pax(price_level):
	mapping = {
		0: "Unknown",
		1: "Inexpensive (<$10 per pax)",
		2: "Moderate ($10–$30 per pax)",
		3: "Expensive ($30–$70 per pax)",
		4: "Very Expensive (>$70 per pax)"
	}
	return mapping.get(price_level, "Unknown")

result = details["result"]

print("Name:", result["name"])
print("Address:", result["formatted_address"])
print("Rating:", result.get("rating"))
print("Estimated price per pax:", estimate_price_per_pax(result.get("price_level", 0)))

print()


# Print all opening hours
if "opening_hours" in result:
	for line in result["opening_hours"]["weekday_text"]:
		print(line)
		
details = gmaps.place(place_id=place_id2, fields=["name", "formatted_address", "rating", "opening_hours", "price_level"])
print("Name:", result["name"])
