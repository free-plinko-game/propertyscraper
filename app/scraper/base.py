"""Base scraper class with rate limiting and common functionality."""
import random
import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from playwright.sync_api import sync_playwright, Browser, Page
import re

from flask import current_app

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Base class for property scrapers with rate limiting."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.properties_scraped = 0
        self.errors: List[str] = []

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the source name (e.g., 'rightmove', 'zoopla')."""
        pass

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Return the base URL for the source."""
        pass

    def get_delay(self) -> float:
        """Get a random delay between requests."""
        min_delay = current_app.config.get('SCRAPE_DELAY_MIN', 3)
        max_delay = current_app.config.get('SCRAPE_DELAY_MAX', 7)
        return random.uniform(min_delay, max_delay)

    def get_max_properties(self) -> int:
        """Get maximum properties to scrape per session."""
        return current_app.config.get('MAX_PROPERTIES_PER_SCRAPE', 50)

    def wait_between_requests(self):
        """Wait a random amount of time between requests."""
        delay = self.get_delay()
        logger.debug(f"Waiting {delay:.2f} seconds before next request")
        time.sleep(delay)

    def start_browser(self):
        """Start the Playwright browser."""
        playwright = sync_playwright().start()
        self.browser = playwright.chromium.launch(headless=self.headless)
        context = self.browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        self.page = context.new_page()
        logger.info(f"Browser started for {self.source_name}")

    def close_browser(self):
        """Close the browser."""
        if self.browser:
            self.browser.close()
            logger.info(f"Browser closed for {self.source_name}")

    def navigate(self, url: str, wait_selector: Optional[str] = None) -> bool:
        """Navigate to a URL with error handling."""
        try:
            logger.info(f"Navigating to: {url}")
            self.page.goto(url, wait_until='networkidle', timeout=30000)
            if wait_selector:
                self.page.wait_for_selector(wait_selector, timeout=10000)
            return True
        except Exception as e:
            error_msg = f"Failed to navigate to {url}: {str(e)}"
            logger.error(error_msg)
            self.errors.append(error_msg)
            return False

    @abstractmethod
    def build_search_url(self, is_rental: bool = False) -> str:
        """Build the search URL for properties."""
        pass

    @abstractmethod
    def extract_listing_urls(self) -> List[str]:
        """Extract property listing URLs from search results page."""
        pass

    @abstractmethod
    def extract_property_data(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract property data from a listing page."""
        pass

    def parse_price(self, price_text: str) -> Optional[int]:
        """Parse price from text to integer."""
        if not price_text:
            return None
        # Remove currency symbols, commas, and text
        cleaned = re.sub(r'[£,pcm\s]', '', price_text.lower())
        # Extract numbers
        match = re.search(r'(\d+)', cleaned)
        if match:
            return int(match.group(1))
        return None

    def parse_bedrooms(self, text: str) -> Optional[int]:
        """Parse bedroom count from text."""
        if not text:
            return None
        match = re.search(r'(\d+)', text)
        if match:
            return int(match.group(1))
        return None

    def extract_postcode(self, address: str) -> Optional[str]:
        """Extract postcode from address."""
        if not address:
            return None
        # UK postcode pattern
        pattern = r'([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})'
        match = re.search(pattern, address.upper())
        if match:
            return match.group(1)
        return None

    def detect_area(self, address: str) -> Optional[str]:
        """Detect area from address based on known Oldham areas."""
        if not address:
            return None
        address_upper = address.upper()
        areas = current_app.config.get('LOCATION_AREAS', [])
        for area in areas:
            if area.upper() in address_upper:
                return area
        return 'Oldham'

    def normalize_property_type(self, prop_type: str) -> Optional[str]:
        """Normalize property type to standard values."""
        if not prop_type:
            return None
        prop_type_lower = prop_type.lower()
        if 'terrace' in prop_type_lower:
            return 'terrace'
        elif 'semi' in prop_type_lower or 'semi-detached' in prop_type_lower:
            return 'semi'
        elif 'detached' in prop_type_lower and 'semi' not in prop_type_lower:
            return 'detached'
        elif 'flat' in prop_type_lower or 'apartment' in prop_type_lower:
            return 'flat'
        elif 'bungalow' in prop_type_lower:
            return 'bungalow'
        elif 'cottage' in prop_type_lower:
            return 'cottage'
        return prop_type_lower

    def parse_date(self, date_text: str) -> Optional[date]:
        """Parse listing date from text."""
        if not date_text:
            return None
        try:
            # Handle relative dates like "Added today", "Added yesterday"
            date_lower = date_text.lower()
            if 'today' in date_lower:
                return date.today()
            elif 'yesterday' in date_lower:
                from datetime import timedelta
                return date.today() - timedelta(days=1)
            # Try parsing common formats
            from dateutil import parser
            return parser.parse(date_text, fuzzy=True).date()
        except Exception:
            return None

    def scrape(self, is_rental: bool = False) -> List[Dict[str, Any]]:
        """Main scraping method."""
        properties = []
        max_properties = self.get_max_properties()

        try:
            self.start_browser()
            search_url = self.build_search_url(is_rental=is_rental)

            if not self.navigate(search_url):
                return properties

            self.wait_between_requests()

            # Extract listing URLs from search results
            listing_urls = self.extract_listing_urls()
            logger.info(f"Found {len(listing_urls)} listings on {self.source_name}")

            # Limit to max properties
            listing_urls = listing_urls[:max_properties]

            # Visit each listing and extract data
            for url in listing_urls:
                if self.properties_scraped >= max_properties:
                    logger.info(f"Reached max properties limit ({max_properties})")
                    break

                self.wait_between_requests()

                try:
                    property_data = self.extract_property_data(url)
                    if property_data:
                        property_data['is_rental'] = is_rental
                        property_data['source'] = self.source_name
                        properties.append(property_data)
                        self.properties_scraped += 1
                        logger.info(f"Scraped property {self.properties_scraped}: {property_data.get('address', 'Unknown')}")
                except Exception as e:
                    error_msg = f"Error extracting property from {url}: {str(e)}"
                    logger.error(error_msg)
                    self.errors.append(error_msg)

        except Exception as e:
            error_msg = f"Scraping failed for {self.source_name}: {str(e)}"
            logger.error(error_msg)
            self.errors.append(error_msg)
        finally:
            self.close_browser()

        return properties

    def get_errors(self) -> List[str]:
        """Get list of errors that occurred during scraping."""
        return self.errors.copy()
