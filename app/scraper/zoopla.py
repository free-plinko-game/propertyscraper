"""Zoopla property scraper."""
import logging
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

from .base import BaseScraper

logger = logging.getLogger(__name__)


class ZooplaScraper(BaseScraper):
    """Scraper for Zoopla property listings."""

    @property
    def source_name(self) -> str:
        return 'zoopla'

    @property
    def base_url(self) -> str:
        return 'https://www.zoopla.co.uk'

    def build_search_url(self, is_rental: bool = False) -> str:
        """Build Zoopla search URL for Oldham."""
        if is_rental:
            return f'{self.base_url}/to-rent/property/oldham/?q=Oldham%2C%20Greater%20Manchester&results_sort=newest_listings&search_source=to-rent'
        else:
            return f'{self.base_url}/for-sale/property/oldham/?q=Oldham%2C%20Greater%20Manchester&results_sort=newest_listings&search_source=for-sale'

    def extract_listing_urls(self) -> List[str]:
        """Extract property listing URLs from search results."""
        urls = []
        try:
            # Wait for listings to load
            self.page.wait_for_selector('[data-testid="search-result"]', timeout=15000)

            # Get all property cards
            cards = self.page.query_selector_all('[data-testid="search-result"]')

            for card in cards:
                try:
                    link = card.query_selector('a[data-testid="listing-details-link"]')
                    if not link:
                        link = card.query_selector('a[href*="/for-sale/details/"]')
                    if not link:
                        link = card.query_selector('a[href*="/to-rent/details/"]')

                    if link:
                        href = link.get_attribute('href')
                        if href:
                            full_url = urljoin(self.base_url, href)
                            if full_url not in urls:
                                urls.append(full_url)
                except Exception as e:
                    logger.debug(f"Error extracting URL from card: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error extracting listing URLs: {e}")
            self.errors.append(f"Error extracting listing URLs: {str(e)}")

        return urls

    def extract_property_data(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract property data from a Zoopla listing page."""
        if not self.navigate(url):
            return None

        data = {
            'url': url,
            'source_id': self._extract_source_id(url),
        }

        try:
            # Wait for the page to load
            self.page.wait_for_selector('h1', timeout=10000)

            # Extract price
            price_elem = self.page.query_selector('[data-testid="price"]')
            if not price_elem:
                price_elem = self.page.query_selector('p[data-testid="price"]')
            if not price_elem:
                # Try finding by text pattern
                price_elems = self.page.query_selector_all('p')
                for elem in price_elems:
                    text = elem.inner_text()
                    if '£' in text and (',' in text or text.count('0') >= 3):
                        price_elem = elem
                        break
            if price_elem:
                price_text = price_elem.inner_text()
                data['price'] = self.parse_price(price_text)

            # Extract address
            address_elem = self.page.query_selector('[data-testid="address-label"]')
            if not address_elem:
                address_elem = self.page.query_selector('h1')
            if address_elem:
                data['address'] = address_elem.inner_text().strip()
                data['postcode'] = self.extract_postcode(data['address'])
                data['area'] = self.detect_area(data['address'])

            # Extract property features
            self._extract_features(data)

            # Extract description
            desc_elem = self.page.query_selector('[data-testid="listing_description"]')
            if not desc_elem:
                desc_elem = self.page.query_selector('[data-testid="truncated_description"]')
            if desc_elem:
                data['description'] = desc_elem.inner_text().strip()[:2000]

            # Extract images
            data['image_urls'] = self._extract_images()

            # Extract listing date
            self._extract_listing_date(data)

            # Validate we have minimum required data
            if data.get('price') and data.get('address'):
                return data
            else:
                logger.warning(f"Missing required data for {url}")
                return None

        except Exception as e:
            logger.error(f"Error extracting property data from {url}: {e}")
            self.errors.append(f"Error extracting data from {url}: {str(e)}")
            return None

    def _extract_source_id(self, url: str) -> str:
        """Extract Zoopla property ID from URL."""
        match = re.search(r'/details/(\d+)', url)
        if match:
            return match.group(1)
        return url.split('/')[-1].split('?')[0]

    def _extract_features(self, data: Dict[str, Any]):
        """Extract bedrooms, bathrooms, property type from features."""
        try:
            # Try specific feature selectors
            features = self.page.query_selector_all('[data-testid="beds-label"]')
            for feature in features:
                text = feature.inner_text().lower()
                if 'bed' in text:
                    data['bedrooms'] = self.parse_bedrooms(text)
                    break

            baths = self.page.query_selector_all('[data-testid="baths-label"]')
            for bath in baths:
                text = bath.inner_text().lower()
                if 'bath' in text:
                    data['bathrooms'] = self.parse_bedrooms(text)
                    break

            # Property type from key info
            type_elem = self.page.query_selector('[data-testid="property-type"]')
            if type_elem:
                data['property_type'] = self.normalize_property_type(type_elem.inner_text())

            # Fallback: try to extract from title/header
            if not data.get('bedrooms') or not data.get('property_type'):
                title_elem = self.page.query_selector('h1')
                if title_elem:
                    title = title_elem.inner_text().lower()
                    if not data.get('bedrooms'):
                        match = re.search(r'(\d+)\s*bed', title)
                        if match:
                            data['bedrooms'] = int(match.group(1))

                    if not data.get('property_type'):
                        data['property_type'] = self.normalize_property_type(title)

            # Try alternative feature locations
            feature_items = self.page.query_selector_all('li[class*="feature"]')
            for item in feature_items:
                text = item.inner_text().lower()
                if 'bed' in text and not data.get('bedrooms'):
                    data['bedrooms'] = self.parse_bedrooms(text)
                elif 'bath' in text and not data.get('bathrooms'):
                    data['bathrooms'] = self.parse_bedrooms(text)

        except Exception as e:
            logger.debug(f"Error extracting features: {e}")

    def _extract_images(self) -> List[str]:
        """Extract property image URLs."""
        images = []
        try:
            # Try different image selectors
            img_elements = self.page.query_selector_all('[data-testid="gallery-image"] img')
            if not img_elements:
                img_elements = self.page.query_selector_all('picture img')
            if not img_elements:
                img_elements = self.page.query_selector_all('[class*="gallery"] img')

            for img in img_elements[:10]:  # Limit to 10 images
                src = img.get_attribute('src')
                if not src:
                    src = img.get_attribute('data-src')
                if src and ('zoopla' in src or 'zoocdn' in src):
                    # Try to get higher resolution
                    src = re.sub(r'/\d+_\d+/', '/656_437/', src)
                    if src not in images:
                        images.append(src)

        except Exception as e:
            logger.debug(f"Error extracting images: {e}")

        return images

    def _extract_listing_date(self, data: Dict[str, Any]):
        """Extract listing date from page."""
        try:
            date_selectors = [
                '[data-testid="date-available"]',
                '[data-testid="listing-date"]',
                'p:has-text("Added")'
            ]

            for selector in date_selectors:
                try:
                    date_elem = self.page.query_selector(selector)
                    if date_elem:
                        date_text = date_elem.inner_text()
                        data['listing_date'] = self.parse_date(date_text)
                        if data.get('listing_date'):
                            break
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Error extracting listing date: {e}")
