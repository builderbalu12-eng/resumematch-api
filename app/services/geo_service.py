from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import asyncio

class GeoService:

    @staticmethod
    async def get_coordinates(address: str) -> dict | None:
        try:
            geolocator = Nominatim(user_agent="resumematch-crm")

            # run in thread (geopy is sync)
            loop = asyncio.get_event_loop()
            location = await loop.run_in_executor(
                None,
                lambda: geolocator.geocode(address, timeout=10)
            )

            if not location:
                return None

            return {
                "type": "Point",
                "coordinates": [location.longitude, location.latitude],
                "address": location.address,
                "city": address,
                "country": "India"
            }

        except GeocoderTimedOut:
            return None
        except Exception:
            return None

geo_service = GeoService()
