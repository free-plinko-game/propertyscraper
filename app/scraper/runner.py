"""Scraper runner with rate limiting and database integration."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

import click
from flask import current_app

from app.models import db, Property, ScrapeLog, RentalAverage
from app.scraper.rightmove import RightmoveScraper
from app.scraper.zoopla import ZooplaScraper
from app.services.rental_analysis import update_rental_averages

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def can_scrape(source: str = 'all') -> bool:
    """Check if we can scrape based on cooldown period."""
    cooldown_hours = current_app.config.get('SCRAPE_COOLDOWN_HOURS', 24)
    cutoff = datetime.utcnow() - timedelta(hours=cooldown_hours)

    query = ScrapeLog.query.filter(
        ScrapeLog.started_at > cutoff,
        ScrapeLog.status == 'completed'
    )

    if source != 'all':
        query = query.filter(ScrapeLog.source == source)

    last_scrape = query.order_by(ScrapeLog.started_at.desc()).first()

    if last_scrape:
        time_since = datetime.utcnow() - last_scrape.started_at
        hours_remaining = cooldown_hours - (time_since.total_seconds() / 3600)
        logger.info(f"Last scrape was {time_since.total_seconds() / 3600:.1f} hours ago. "
                    f"Cooldown: {hours_remaining:.1f} hours remaining.")
        return False

    return True


def save_properties(properties: List[Dict[str, Any]], scrape_log: ScrapeLog) -> tuple:
    """Save scraped properties to database."""
    new_count = 0
    updated_count = 0

    for prop_data in properties:
        try:
            # Check if property already exists
            existing = Property.query.filter_by(
                source=prop_data['source'],
                source_id=prop_data['source_id']
            ).first()

            if existing:
                # Update existing property
                existing.price = prop_data.get('price', existing.price)
                existing.address = prop_data.get('address', existing.address)
                existing.postcode = prop_data.get('postcode', existing.postcode)
                existing.area = prop_data.get('area', existing.area)
                existing.bedrooms = prop_data.get('bedrooms', existing.bedrooms)
                existing.bathrooms = prop_data.get('bathrooms', existing.bathrooms)
                existing.property_type = prop_data.get('property_type', existing.property_type)
                existing.description = prop_data.get('description', existing.description)
                existing.image_urls = prop_data.get('image_urls', existing.image_urls)
                existing.listing_date = prop_data.get('listing_date', existing.listing_date)
                existing.updated_at = datetime.utcnow()
                updated_count += 1
                logger.debug(f"Updated property: {existing.address}")
            else:
                # Create new property
                new_property = Property(
                    source=prop_data['source'],
                    source_id=prop_data['source_id'],
                    url=prop_data['url'],
                    price=prop_data.get('price'),
                    address=prop_data.get('address'),
                    postcode=prop_data.get('postcode'),
                    area=prop_data.get('area'),
                    bedrooms=prop_data.get('bedrooms'),
                    bathrooms=prop_data.get('bathrooms'),
                    property_type=prop_data.get('property_type'),
                    description=prop_data.get('description'),
                    image_urls=prop_data.get('image_urls', []),
                    listing_date=prop_data.get('listing_date'),
                    is_rental=prop_data.get('is_rental', False)
                )
                db.session.add(new_property)
                new_count += 1
                logger.debug(f"Added new property: {new_property.address}")

        except Exception as e:
            logger.error(f"Error saving property: {e}")
            scrape_log.errors = (scrape_log.errors or '') + f"\nError saving property: {str(e)}"

    db.session.commit()
    return new_count, updated_count


def run_scraper(force: bool = False, source: str = 'all', scrape_type: str = 'all'):
    """Run the property scraper."""
    click.echo(f"Starting property scraper (source={source}, type={scrape_type}, force={force})")

    # Check cooldown
    if not force and not can_scrape(source):
        cooldown = current_app.config.get('SCRAPE_COOLDOWN_HOURS', 24)
        click.echo(f"Scraping is on cooldown. Please wait or use --force to override.")
        click.echo(f"Cooldown period: {cooldown} hours")
        return

    scrapers = []
    if source in ['all', 'rightmove']:
        scrapers.append(('rightmove', RightmoveScraper))
    if source in ['all', 'zoopla']:
        scrapers.append(('zoopla', ZooplaScraper))

    scrape_types = []
    if scrape_type in ['all', 'sale']:
        scrape_types.append(('sale', False))
    if scrape_type in ['all', 'rent']:
        scrape_types.append(('rent', True))

    total_new = 0
    total_updated = 0
    total_found = 0

    for source_name, scraper_class in scrapers:
        for type_name, is_rental in scrape_types:
            click.echo(f"\n{'='*50}")
            click.echo(f"Scraping {source_name} for {type_name} properties...")
            click.echo(f"{'='*50}")

            # Create scrape log
            scrape_log = ScrapeLog(
                source=source_name,
                scrape_type=type_name,
                started_at=datetime.utcnow(),
                status='running'
            )
            db.session.add(scrape_log)
            db.session.commit()

            try:
                # Run scraper
                scraper = scraper_class(headless=True)
                properties = scraper.scrape(is_rental=is_rental)

                # Save properties
                new_count, updated_count = save_properties(properties, scrape_log)

                # Update scrape log
                scrape_log.completed_at = datetime.utcnow()
                scrape_log.properties_found = len(properties)
                scrape_log.properties_new = new_count
                scrape_log.properties_updated = updated_count
                scrape_log.status = 'completed'

                if scraper.get_errors():
                    scrape_log.errors = '\n'.join(scraper.get_errors())

                total_new += new_count
                total_updated += updated_count
                total_found += len(properties)

                click.echo(f"Found: {len(properties)} | New: {new_count} | Updated: {updated_count}")

            except Exception as e:
                logger.error(f"Scraper failed: {e}")
                scrape_log.completed_at = datetime.utcnow()
                scrape_log.status = 'failed'
                scrape_log.errors = (scrape_log.errors or '') + f"\nFatal error: {str(e)}"
                click.echo(f"Error: {e}")

            db.session.commit()

    # Update rental averages if we scraped rentals
    if scrape_type in ['all', 'rent']:
        click.echo("\nUpdating rental averages...")
        update_rental_averages()

    click.echo(f"\n{'='*50}")
    click.echo("SCRAPING COMPLETE")
    click.echo(f"{'='*50}")
    click.echo(f"Total found: {total_found}")
    click.echo(f"Total new: {total_new}")
    click.echo(f"Total updated: {total_updated}")
