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
    Get rental averages as a dictionary.

    Args:
        location: Filter by location (None for global 'All' averages)

    Returns:
        Dict with bedroom count as key and average data as value
    """
    filter_location = location if location else 'All'

    averages = RentalAverage.query.filter_by(
        location=filter_location
    ).order_by(RentalAverage.bedrooms).all()

    # If no location-specific data found, fall back to global
    if not averages and location:
        averages = RentalAverage.query.filter_by(
            location='All'
        ).order_by(RentalAverage.bedrooms).all()

    result = {}
    for avg in averages:
        key = f"{avg.bedrooms}_bed"
        result[key] = avg.to_dict()

    return result


def get_rental_locations() -> List[str]:
    """
    Get list of locations that have rental data.

    Returns:
        List of location names
    """
    locations = db.session.query(
        RentalAverage.location
    ).filter(
        RentalAverage.location != 'All'
    ).distinct().order_by(RentalAverage.location).all()

    return [loc[0] for loc in locations]


def get_estimated_rent(bedrooms: Optional[int], location: Optional[str] = None) -> Optional[float]:
    """
    Get estimated monthly rent for a given bedroom count and location.

    Args:
        bedrooms: Number of bedrooms
        location: Location to get rent for (defaults to global average)

    Returns:
        Estimated monthly rent or None if no data available
    """
    if bedrooms is None:
        return None

    # Try location-specific first
    if location:
        rental_avg = RentalAverage.query.filter_by(
            bedrooms=bedrooms,
            location=location
        ).first()

        if rental_avg:
            return rental_avg.average_rent

    # Fall back to global average
    rental_avg = RentalAverage.query.filter_by(
        bedrooms=bedrooms,
        location='All'
    ).first()

    if rental_avg:
        return rental_avg.average_rent

    # If exact match not found, try to interpolate from global data
    lower = RentalAverage.query.filter(
        RentalAverage.bedrooms < bedrooms,
        RentalAverage.location == 'All'
    ).order_by(RentalAverage.bedrooms.desc()).first()

    upper = RentalAverage.query.filter(
        RentalAverage.bedrooms > bedrooms,
        RentalAverage.location == 'All'
    ).order_by(RentalAverage.bedrooms.asc()).first()

    if lower and upper:
        # Linear interpolation
        ratio = (bedrooms - lower.bedrooms) / (upper.bedrooms - lower.bedrooms)
        return lower.average_rent + ratio * (upper.average_rent - lower.average_rent)
    elif lower:
        # Extrapolate up (rough estimate: 15% more per bedroom)
        beds_diff = bedrooms - lower.bedrooms
        return lower.average_rent * (1.15 ** beds_diff)
    elif upper:
        # Extrapolate down (rough estimate: 15% less per bedroom)
        beds_diff = upper.bedrooms - bedrooms
        return upper.average_rent / (1.15 ** beds_diff)

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
