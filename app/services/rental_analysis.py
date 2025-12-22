"""Rental market analysis service."""
import logging
from typing import Dict, Optional
from sqlalchemy import func

from app.models import db, Property, RentalAverage

logger = logging.getLogger(__name__)


def update_rental_averages():
    """
    Calculate and update rental averages by bedroom count.
    Called after each rental scrape.
    """
    logger.info("Updating rental averages...")

    # Get rental properties grouped by bedrooms
    results = db.session.query(
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

    for row in results:
        if row.bedrooms is None or row.bedrooms < 0:
            continue

        # Find or create rental average record
        rental_avg = RentalAverage.query.filter_by(bedrooms=row.bedrooms).first()

        if rental_avg:
            rental_avg.average_rent = row.avg_rent
            rental_avg.sample_count = row.count
            rental_avg.min_rent = row.min_rent
            rental_avg.max_rent = row.max_rent
        else:
            rental_avg = RentalAverage(
                bedrooms=row.bedrooms,
                average_rent=row.avg_rent,
                sample_count=row.count,
                min_rent=row.min_rent,
                max_rent=row.max_rent
            )
            db.session.add(rental_avg)

        logger.info(f"{row.bedrooms} bed: avg £{row.avg_rent:.0f}/month "
                    f"(range: £{row.min_rent}-£{row.max_rent}, n={row.count})")

    db.session.commit()
    logger.info("Rental averages updated successfully")


def get_rental_averages() -> Dict[str, dict]:
    """
    Get rental averages as a dictionary.

    Returns:
        Dict with bedroom count as key and average data as value
    """
    averages = RentalAverage.query.order_by(RentalAverage.bedrooms).all()

    result = {}
    for avg in averages:
        key = f"{avg.bedrooms}_bed"
        result[key] = avg.to_dict()

    return result


def get_estimated_rent(bedrooms: Optional[int]) -> Optional[float]:
    """
    Get estimated monthly rent for a given bedroom count.

    Args:
        bedrooms: Number of bedrooms

    Returns:
        Estimated monthly rent or None if no data available
    """
    if bedrooms is None:
        return None

    rental_avg = RentalAverage.query.filter_by(bedrooms=bedrooms).first()

    if rental_avg:
        return rental_avg.average_rent

    # If exact match not found, try to interpolate
    lower = RentalAverage.query.filter(
        RentalAverage.bedrooms < bedrooms
    ).order_by(RentalAverage.bedrooms.desc()).first()

    upper = RentalAverage.query.filter(
        RentalAverage.bedrooms > bedrooms
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


def get_rental_stats() -> dict:
    """
    Get overall rental market statistics.

    Returns:
        Dictionary with market statistics
    """
    total_rentals = Property.query.filter(Property.is_rental == True).count()

    avg_rent = db.session.query(func.avg(Property.price)).filter(
        Property.is_rental == True,
        Property.price.isnot(None)
    ).scalar()

    min_rent = db.session.query(func.min(Property.price)).filter(
        Property.is_rental == True,
        Property.price.isnot(None)
    ).scalar()

    max_rent = db.session.query(func.max(Property.price)).filter(
        Property.is_rental == True,
        Property.price.isnot(None)
    ).scalar()

    return {
        'total_listings': total_rentals,
        'average_rent': round(avg_rent, 2) if avg_rent else None,
        'min_rent': min_rent,
        'max_rent': max_rent
    }
