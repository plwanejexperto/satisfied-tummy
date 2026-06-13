# 🍽️ Satisfied Tummy Bot

A Telegram bot for discovering, saving, and organising restaurants in Singapore. Search by name using the Google Places API, view details like opening hours, price range, and nearby MRT stations, then save favourites to a MongoDB database with custom tags.

## Features

- **Restaurant search** — searches Google Places for restaurants in Singapore, filtered to food-relevant types (restaurants, cafes, bakeries, bars, etc.)
- **Rich details** — shows ratings, estimated price per pax, nearest MRT stations (with walking distance), reservations availability, and formatted opening hours
- **Save to database** — inline buttons let you save any result to MongoDB directly from the chat
- **Tagging** — after saving, add comma-separated tags (e.g. `date night, halal, cheap`) to organise your list
- **Browse saved restaurants** — list all saved entries or search by name, type, or tag

## Commands

| Command | Description |
|---|---|
| _(any text)_ | Search Google Places for a restaurant |
| `/listrestaurants` | List all saved restaurants |
| `/search <keyword>` | Search saved restaurants by name, type, or tag |
| `/cancel` | Cancel an in-progress tagging flow |
| `/start` | Show welcome message |

## Project Structure

```
.
├── main.py          # Bot logic, handlers, DB operations
├── .env             # Environment variables (not committed)
└── .env.example     # Template for required environment variables
```

## Setup

### Prerequisites

- Python 3.9+
- A [Telegram bot token](https://core.telegram.org/bots/tutorial) from BotFather
- A [Google Places API key](https://developers.google.com/maps/documentation/places/web-service/get-api-key) with the Places API (New) enabled
- A [MongoDB Atlas](https://www.mongodb.com/atlas) cluster (free tier works fine)

### Installation

```bash
git clone https://github.com/your-username/satisfied-tummy-bot.git
cd satisfied-tummy-bot
pip install python-telegram-bot pymongo requests python-dotenv certifi
```

### Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

```env
GOOGLE_API_KEY=your_google_places_api_key
TELEGRAM_TOKEN=your_telegram_bot_token
MONGO_URI=your_mongodb_connection_string
```

### Run

```bash
python main.py
```

The bot will log a MongoDB connectivity test on startup, then begin polling for messages.

## Dependencies

| Package | Purpose |
|---|---|
| `python-telegram-bot` | Telegram Bot API wrapper |
| `pymongo` | MongoDB client |
| `requests` | HTTP calls to Google Places API |
| `python-dotenv` | Load environment variables from `.env` |
| `certifi` | TLS certificates for MongoDB Atlas |

## Notes

- Restaurant search is biased toward Singapore (radius: 30 km from 1.3521°N, 103.8198°E)
- MRT stations within 500 m are shown; if none are that close, the nearest one is shown instead
- The bot uses Google Places API (New) endpoints (`places.googleapis.com/v1/`) for place details and opening hours
- MongoDB database name: `satisfiedTummy`, collection: `restaurants`
