# app/services/lead_finder.py

import googlemaps
import asyncio
from app.config import settings
from datetime import datetime
from bson import ObjectId

CATEGORY_MAP = {
    "restaurant":  "restaurant",
    "jeweler":     "jewelry_store",
    "salon":       "beauty_salon",
    "gym":         "gym",
    "clinic":      "dentist",
    "clothing":    "clothing_store",
    "bakery":      "bakery",
    "realestate":  "real_estate_agency",
    "carrepair":   "car_repair",
    "hotel":       "lodging",
}

ALL_CATEGORIES = list(CATEGORY_MAP.keys())


class LeadFinder:

    @staticmethod
    async def find_and_save_leads(
        city: str,
        category: str,
        radius_km: float,
        owner_id: str,
        mongo,
        limit: int = 50
    ) -> list:

        if category == "all":
            per_cat = max(1, limit // len(ALL_CATEGORIES))  # 50/10 = 5 each
            all_saved = []
            for cat in ALL_CATEGORIES:
                saved = await LeadFinder._fetch_category(
                    city, cat, radius_km, owner_id, mongo, max_results=per_cat
                )
                all_saved.extend(saved)
            print(f"✅ Total saved across all categories: {len(all_saved)}")
            return all_saved
        else:
            return await LeadFinder._fetch_category(
                city, category, radius_km, owner_id, mongo, max_results=limit
            )

    @staticmethod
    async def _fetch_category(
        city: str,
        category: str,
        radius_km: float,
        owner_id: str,
        mongo,
        max_results: int = 50
    ) -> list:

        gmaps = googlemaps.Client(key=settings.google_maps_api_key)
        loop = asyncio.get_event_loop()

        # Step 1 — geocode city
        geocode = await loop.run_in_executor(None, lambda: gmaps.geocode(city))
        if not geocode:
            return []

        city_lat = geocode[0]['geometry']['location']['lat']
        city_lng = geocode[0]['geometry']['location']['lng']

        # Step 2 — nearby search (max 3 pages)
        place_type = CATEGORY_MAP.get(category, category)
        all_places = []
        token = None

        for _ in range(3):
            if len(all_places) >= max_results:
                break
            kwargs = {
                "location": (city_lat, city_lng),
                "type": place_type,
                "radius": radius_km * 1000,
            }
            if token:
                kwargs["page_token"] = token
                await asyncio.sleep(2)

            resp = await loop.run_in_executor(None, lambda k=kwargs: gmaps.places_nearby(**k))
            all_places.extend(resp.get("results", []))
            token = resp.get("next_page_token")
            if not token:
                break

        # ✅ Cap to max_results
        all_places = all_places[:max_results]

        # Step 3 — fetch details + save
        saved = []

        for place in all_places:
            try:
                detail = await loop.run_in_executor(
                    None,
                    lambda p=place: gmaps.place(
                        p["place_id"],
                        fields=["name", "website", "formatted_phone_number",
                                "formatted_address", "rating", "geometry"]
                    )["result"]
                )
            except Exception as e:
                print(f"⚠️ Failed to fetch place details: {e}")
                continue

            website = detail.get("website", "")
            has_real_website = bool(
                website and
                "facebook.com" not in website and
                "instagram.com" not in website
            )

            loc = detail.get("geometry", {}).get("location", {})
            lat_val = loc.get("lat", 0)
            lng_val = loc.get("lng", 0)

            doc = {
                "_id": ObjectId(),
                "owner_id": owner_id,
                "name": detail.get("name"),
                "company": detail.get("name"),
                "phone": detail.get("formatted_phone_number"),
                "address": detail.get("formatted_address"),
                "website": website or None,
                "has_website": has_real_website,
                "category": category,
                "status": "lead",
                "rating": detail.get("rating"),
                "lat": lat_val,
                "lng": lng_val,
                "location": {
                    "type": "Point",
                    "coordinates": [lng_val, lat_val],
                    "address": detail.get("formatted_address"),
                    "city": city,
                    "country": "India"
                },
                "source": "google_maps",
                "tags": ["no-website"] if not has_real_website else ["has-website"],
                "notes": f"Found via Google Maps. Rating: {detail.get('rating', 'N/A')}",
                "social_links": {},
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }

            existing = await mongo.clients.find_one({
                "owner_id": owner_id,
                "name": doc["name"],
                "address": doc["address"]
            })

            if not existing:
                await mongo.clients.insert_one(doc)
                doc_out = {**doc}
                doc_out["_id"] = str(doc_out["_id"])
                saved.append(doc_out)

        print(f"✅ Saved {len(saved)} new leads for '{category}' in '{city}'")
        return saved


lead_finder = LeadFinder()
