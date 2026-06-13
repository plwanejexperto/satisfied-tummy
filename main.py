import googlemaps
from dotenv import load_dotenv
import os

load_dotenv()

gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))

restaurant = input('Enter the restaurant name: ')
search = gmaps.places(query=restaurant)
plocation_result = gmaps.geocode(restaurant)
location = location_result[0]["geometry"]["location"]
lat_lng = (location["lat"], location["lng"])
print("Coordinates:", lat_lng)
nearby_results = gmaps.places_nearby(
	location=lat_lng,
	radius=1000,  # in meters
	keyword="mcdonalds"
)

for i, place in enumerate(nearby_results.get("results", [])):
	print(f"{i+1}. {place.get('name')} — {place.get('vicinity')}")
