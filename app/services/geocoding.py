"""Geocoding service using postcodes.io and OpenStreetMap Nominatim."""
import logging
import re
import time
import requests
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

# UK postcode regex patterns
UK_POSTCODE_PATTERN = re.compile(
    r'\b([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})\b',  # Full postcode
    re.IGNORECASE
)
UK_OUTCODE_PATTERN = re.compile(
    r'\b([A-Z]{1,2}\d{1,2}[A-Z]?)\b',  # Outward code only
    re.IGNORECASE
)


def extract_postcode_from_address(address: str) -> Optional[str]:
    """Extract a UK postcode or outcode from an address string."""
    if not address:
        return None

    # Try to find a full postcode first
    match = UK_POSTCODE_PATTERN.search(address)
    if match:
        return match.group(1).upper()

    # Fall back to outcode
    match = UK_OUTCODE_PATTERN.search(address)
    if match:
        return match.group(1).upper()

    return None


# Nominatim requires a user agent
USER_AGENT = "PropertyInvestorDashboard/1.0"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"

# Rate limiting - Nominatim allows max 1 request per second
_last_request_time = 0


def geocode_postcode(postcode: str) -> Optional[Tuple[float, float]]:
    """
    Geocode a UK postcode using postcodes.io (free, fast, no rate limit).
    Supports both full postcodes (OL9 7AB) and partial outcodes (OL9).

    Args:
        postcode: UK postcode (full or partial)

    Returns:
        Tuple of (latitude, longitude) or None if geocoding fails
    """
    if not postcode:
        return None

    # Clean postcode
    postcode = postcode.strip().upper()

    try:
        # First try as full postcode
        response = requests.get(f"{POSTCODES_IO_URL}/{postcode}", timeout=5)

        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 200 and data.get('result'):
                result = data['result']
                return (result['latitude'], result['longitude'])

        # If that fails, try as outcode (partial postcode like "OL9")
        # Extract just the outward code if it looks like a partial
        outcode = postcode.split()[0] if ' ' in postcode else postcode
        if len(outcode) <= 4:  # Outcodes are 2-4 characters
            response = requests.get(f"https://api.postcodes.io/outcodes/{outcode}", timeout=5)

            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 200 and data.get('result'):
                    result = data['result']
                    return (result['latitude'], result['longitude'])

        return None

    except requests.RequestException as e:
        logger.error(f"Postcode geocoding failed for '{postcode}': {e}")
        return None


def geocode_postcodes_bulk(postcodes: List[str]) -> dict:
    """
    Geocode multiple UK postcodes in a single request (up to 100).

    Args:
        postcodes: List of UK postcodes

    Returns:
        Dict mapping postcode to (lat, lng) tuple
    """
    if not postcodes:
        return {}

    # Clean postcodes
    clean_postcodes = [p.strip().upper() for p in postcodes if p]

    # postcodes.io allows up to 100 postcodes per request
    results = {}

    try:
        response = requests.post(
            POSTCODES_IO_URL,
            json={"postcodes": clean_postcodes[:100]},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 200 and data.get('result'):
                for item in data['result']:
                    if item.get('result'):
                        pc = item['query']
                        r = item['result']
                        results[pc] = (r['latitude'], r['longitude'])

    except requests.RequestException as e:
        logger.error(f"Bulk postcode geocoding failed: {e}")

    return results


def geocode_address(address: str, postcode: Optional[str] = None) -> Optional[Tuple[float, float]]:
    """
    Geocode an address to lat/lng coordinates using OpenStreetMap Nominatim.

    Args:
        address: Full address string
        postcode: Optional postcode for more accurate results

    Returns:
        Tuple of (latitude, longitude) or None if geocoding fails
    """
    global _last_request_time

    # Rate limiting - wait if needed
    elapsed = time.time() - _last_request_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    # Build search query - postcode gives best results for UK
    if postcode:
        query = f"{postcode}, UK"
    else:
        query = f"{address}, UK"

    params = {
        'q': query,
        'format': 'json',
        'limit': 1,
        'countrycodes': 'gb'
    }

    headers = {
        'User-Agent': USER_AGENT
    }

    try:
        _last_request_time = time.time()
        response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        results = response.json()
        if results:
            lat = float(results[0]['lat'])
            lon = float(results[0]['lon'])
            logger.debug(f"Geocoded '{query}' to ({lat}, {lon})")
            return (lat, lon)
        else:
            logger.warning(f"No geocoding results for '{query}'")
            return None

    except requests.RequestException as e:
        logger.error(f"Geocoding request failed for '{query}': {e}")
        return None
    except (KeyError, ValueError, IndexError) as e:
        logger.error(f"Error parsing geocoding response for '{query}': {e}")
        return None


def geocode_property(prop) -> bool:
    """
    Geocode a property and update its lat/lng.

    Args:
        prop: Property model instance

    Returns:
        True if geocoding succeeded, False otherwise
    """
    from app.models import db

    # Skip if already geocoded
    if prop.latitude is not None and prop.longitude is not None:
        return True

    result = geocode_address(prop.address, prop.postcode)
    if result:
        prop.latitude, prop.longitude = result
        db.session.commit()
        return True

    return False


def geocode_all_properties(batch_size: int = 100) -> dict:
    """
    Geocode all properties that don't have coordinates yet.
    Uses fast bulk postcode geocoding when postcodes are available.

    Args:
        batch_size: Number of properties to process in one batch

    Returns:
        Dict with geocoding stats
    """
    from app.models import db, Property

    # Get properties without coordinates
    properties = Property.query.filter(
        (Property.latitude.is_(None)) | (Property.longitude.is_(None))
    ).limit(batch_size).all()

    stats = {
        'total': len(properties),
        'success': 0,
        'failed': 0
    }

    if not properties:
        return stats

    # Try to geocode each property
    for prop in properties:
        result = None

        # Strategy 1: Use stored postcode
        if prop.postcode:
            result = geocode_postcode(prop.postcode)

        # Strategy 2: Extract postcode from address
        if not result:
            extracted_pc = extract_postcode_from_address(prop.address)
            if extracted_pc:
                result = geocode_postcode(extracted_pc)
                logger.debug(f"Extracted postcode '{extracted_pc}' from address")

        # Strategy 3: Fall back to Nominatim with address
        if not result:
            result = geocode_address(prop.address, prop.postcode)

        if result:
            prop.latitude, prop.longitude = result
            stats['success'] += 1
        else:
            stats['failed'] += 1

    # Commit all changes at once
    db.session.commit()

    return stats


def get_area_coordinates() -> dict:
    """
    Get center coordinates for each search_location area.

    Returns:
        Dict mapping location name to (lat, lng) tuple
    """
    from app.models import db, Property
    from sqlalchemy import func

    # Get average coordinates per search_location
    results = db.session.query(
        Property.search_location,
        func.avg(Property.latitude).label('lat'),
        func.avg(Property.longitude).label('lng'),
        func.count(Property.id).label('count')
    ).filter(
        Property.latitude.isnot(None),
        Property.longitude.isnot(None),
        Property.search_location.isnot(None)
    ).group_by(Property.search_location).all()

    areas = {}
    for row in results:
        if row.lat and row.lng:
            areas[row.search_location] = {
                'lat': row.lat,
                'lng': row.lng,
                'property_count': row.count
            }

    return areas
