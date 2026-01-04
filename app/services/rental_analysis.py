"""Rental market analysis service."""
import logging
from typing import Dict, List, Optional
from sqlalchemy import func

from app.models import db, Property, RentalAverage

logger = logging.getLogger(__name__)


def update_rental_averages():
    """
    Calculate and update rental averages by bedroom count AND location.
    Called after each rental scrape.
    """
    logger.info("Updating rental averages...")

    # First, calculate global averages (location = 'All')
    global_results = db.session.query(
        Property.bedrooms,
        func.avg(Property.price).label('avg_rent'),
        func.count(Property.id).label('count'),
        func.min(Property.price).label('min_rent'),
        func.max(Property.price).label('max_rent')
    ).filter(
        Property.is_rental == True,
        Property.bedrooms.isnot(None),
        Property.price.isnot(None)
    ).group_by(
        Property.bedrooms
    ).all()

    for row in global_results:
        if row.bedrooms is None or row.bedrooms < 0:
            continue

        _upsert_rental_average(
            bedrooms=row.bedrooms,
            location='All',
            avg_rent=row.avg_rent,
            count=row.count,
            min_rent=row.min_rent,
            max_rent=row.max_rent
        )
        logger.info(f"Global - {row.bedrooms} bed: avg £{row.avg_rent:.0f}/month "
                    f"(range: £{row.min_rent}-£{row.max_rent}, n={row.count})")

    # Then calculate per-location averages
    location_results = db.session.query(
        Property.search_location,
        Property.bedrooms,
        func.avg(Property.price).label('avg_rent'),
        func.count(Property.id).label('count'),
        func.min(Property.price).label('min_rent'),
        func.max(Property.price).label('max_rent')
    ).filter(
        Property.is_rental == True,
        Property.bedrooms.isnot(None),
        Property.price.isnot(None),
        Property.search_location.isnot(None)
    ).group_by(
        Property.search_location,
        Property.bedrooms
    ).all()

    for row in location_results:
        if row.bedrooms is None or row.bedrooms < 0:
            continue

        _upsert_rental_average(
            bedrooms=row.bedrooms,
            location=row.search_location,
            avg_rent=row.avg_rent,
            count=row.count,
            min_rent=row.min_rent,
            max_rent=row.max_rent
        )
        logger.info(f"{row.search_location} - {row.bedrooms} bed: avg £{row.avg_rent:.0f}/month "
                    f"(range: £{row.min_rent}-£{row.max_rent}, n={row.count})")

    db.session.commit()
    logger.info("Rental averages updated successfully")


def _upsert_rental_average(bedrooms: int, location: str, avg_rent: float,
                           count: int, min_rent: int, max_rent: int):
    """Insert or update a rental average record."""
    rental_avg = RentalAverage.query.filter_by(
        bedrooms=bedrooms,
        location=location
    ).first()

    if rental_avg:
        rental_avg.average_rent = avg_rent
        rental_avg.sample_count = count
        rental_avg.min_rent = min_rent
        rental_avg.max_rent = max_rent
    else:
        rental_avg = RentalAverage(
            bedrooms=bedrooms,
            location=location,
            average_rent=avg_rent,
            sample_count=count,
            min_rent=min_rent,
            max_rent=max_rent
        )
        db.session.add(rental_avg)


def get_rental_averages(location: Optional[str] = None) -> Dict[str, dict]:
    """
    Get rental averages as a dictionary, calculated directly from rental properties.

    Args:
        location: Filter by location (None for all locations)

    Returns:
        Dict with bedroom count as key and average data as value
    """
    # Calculate directly from Property table for accurate location-specific data
    query = db.session.query(
        Property.bedrooms,
        func.avg(Property.price).label('avg_rent'),
        func.count(Property.id).label('count'),
        func.min(Property.price).label('min_rent'),
        func.max(Property.price).label('max_rent')
    ).filter(
        Property.is_rental == True,
        Property.bedrooms.isnot(None),
        Property.price.isnot(None)
    )

    if location:
        query = query.filter(Property.search_location == location)

    results = query.group_by(Property.bedrooms).order_by(Property.bedrooms).all()

    result = {}
    for row in results:
        if row.bedrooms is None or row.bedrooms < 0:
            continue
        key = f"{row.bedrooms}_bed"
        result[key] = {
            'bedrooms': row.bedrooms,
            'location': location or 'All',
            'average_rent': round(row.avg_rent, 2),
            'sample_count': row.count,
            'min_rent': row.min_rent,
            'max_rent': row.max_rent,
            'updated_at': None
        }

    return result


def get_rental_locations() -> List[str]:
    """
    Get list of locations that have rental properties.

    Returns:
        List of location names
    """
    # Get locations from actual rental properties
    locations = db.session.query(
        Property.search_location
    ).filter(
        Property.is_rental == True,
        Property.search_location.isnot(None)
    ).distinct().order_by(Property.search_location).all()

    return [loc[0] for loc in locations if loc[0]]


def get_estimated_rent(bedrooms: Optional[int], location: Optional[str] = None) -> Optional[float]:
    """
    Get estimated monthly rent for a given bedroom count and location.
    Calculates directly from rental properties for accuracy.

    Args:
        bedrooms: Number of bedrooms
        location: Location to get rent for (defaults to global average)

    Returns:
        Estimated monthly rent or None if no data available
    """
    if bedrooms is None:
        return None

    # Try location-specific first - calculate directly from Property table
    if location:
        result = db.session.query(
            func.avg(Property.price)
        ).filter(
            Property.is_rental == True,
            Property.bedrooms == bedrooms,
            Property.search_location == location,
            Property.price.isnot(None)
        ).scalar()

        if result:
            return float(result)

    # Fall back to global average across all locations
    result = db.session.query(
        func.avg(Property.price)
    ).filter(
        Property.is_rental == True,
        Property.bedrooms == bedrooms,
        Property.price.isnot(None)
    ).scalar()

    if result:
        return float(result)

    # If exact bedroom match not found, try to interpolate
    # Get nearest lower bedroom count average
    lower = db.session.query(
        Property.bedrooms,
        func.avg(Property.price).label('avg_rent')
    ).filter(
        Property.is_rental == True,
        Property.bedrooms < bedrooms,
        Property.price.isnot(None)
    ).group_by(Property.bedrooms).order_by(Property.bedrooms.desc()).first()

    # Get nearest higher bedroom count average
    upper = db.session.query(
        Property.bedrooms,
        func.avg(Property.price).label('avg_rent')
    ).filter(
        Property.is_rental == True,
        Property.bedrooms > bedrooms,
        Property.price.isnot(None)
    ).group_by(Property.bedrooms).order_by(Property.bedrooms.asc()).first()

    if lower and upper:
        # Linear interpolation
        ratio = (bedrooms - lower.bedrooms) / (upper.bedrooms - lower.bedrooms)
        return lower.avg_rent + ratio * (upper.avg_rent - lower.avg_rent)
    elif lower:
        # Extrapolate up (rough estimate: 15% more per bedroom)
        beds_diff = bedrooms - lower.bedrooms
        return float(lower.avg_rent) * (1.15 ** beds_diff)
    elif upper:
        # Extrapolate down (rough estimate: 15% less per bedroom)
        beds_diff = upper.bedrooms - bedrooms
        return float(upper.avg_rent) / (1.15 ** beds_diff)

    return None


def get_rental_stats(location: Optional[str] = None) -> dict:
    """
    Get overall rental market statistics.

    Args:
        location: Filter by location (None for all)

    Returns:
        Dictionary with market statistics
    """
    query = Property.query.filter(Property.is_rental == True)

    if location:
        query = query.filter(Property.search_location == location)

    total_rentals = query.count()

    price_query = db.session.query(
        func.avg(Property.price),
        func.min(Property.price),
        func.max(Property.price)
    ).filter(
        Property.is_rental == True,
        Property.price.isnot(None)
    )

    if location:
        price_query = price_query.filter(Property.search_location == location)

    result = price_query.first()
    avg_rent, min_rent, max_rent = result if result else (None, None, None)

    return {
        'total_listings': total_rentals,
        'average_rent': round(avg_rent, 2) if avg_rent else None,
        'min_rent': min_rent,
        'max_rent': max_rent,
        'location': location or 'All Locations'
    }
