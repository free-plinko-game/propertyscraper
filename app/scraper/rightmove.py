"""Rightmove property scraper."""
import logging
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

from .base import BaseScraper

logger = logging.getLogger(__name__)


class RightmoveScraper(BaseScraper):
    """Scraper for Rightmove property listings."""

    @property
    def source_name(self) -> str:
        return 'rightmove'

    @property
    def base_url(self) -> str:
        return 'https://www.rightmove.co.uk'

    def build_search_url(self, is_rental: bool = False) -> str:
        """Build Rightmove search URL for Oldham."""
        # Oldham location identifier on Rightmove
        # REGION%5E904 is Oldham, Greater Manchester
        location_id = 'REGION%5E904'

        if is_rental:
            return f'{self.base_url}/property-to-rent/find.html?locationIdentifier={location_id}&sortType=6&propertyTypes=&includeLetAgreed=false&mustHave=&dontShow=&furnishTypes=&keywords='
        else:
            return f'{self.base_url}/property-for-sale/find.html?locationIdentifier={location_id}&sortType=6&propertyTypes=&includeSSTC=false&mustHave=&dontShow=&furnishTypes=&keywords='

    def _handle_cookie_consent(self):
        """Handle cookie consent banner if present."""
        try:
            # Try to find and click the accept cookies button
            accept_btn = self.page.query_selector('button[id*="accept"], button:has-text("Accept"), button:has-text("Got it")')
            if accept_btn:
                accept_btn.click()
                self.page.wait_for_timeout(1000)
                logger.debug("Cookie consent accepted")
        except Exception as e:
            logger.debug(f"No cookie consent or already handled: {e}")

    def extract_listing_urls(self) -> List[str]:
        """Extract property listing URLs from search results."""
        urls = []
        try:
            # Handle cookie consent first
            self._handle_cookie_consent()

            # Wait for page content with multiple fallback selectors
            try:
                self.page.wait_for_selector('.propertyCard, .l-searchResult, [data-test="propertyCard"]', timeout=15000)
            except Exception:
                # Take screenshot for debugging
                logger.warning("Could not find property cards, page may have changed structure")
                # Try to get any links that look like property listings
                pass

            # Get all property cards using multiple selectors
            cards = self.page.query_selector_all('.propertyCard, .l-searchResult, [data-test="propertyCard"]')

            if not cards:
                # Fallback: find all links that match property URL pattern
                all_links = self.page.query_selector_all('a[href*="/properties/"]')
                for link in all_links:
                    href = link.get_attribute('href')
                    if href and '/properties/' in href and 'href' not in href:
                        full_url = urljoin(self.base_url, href.split('#')[0].split('?')[0])
                        if full_url not in urls and full_url.count('/') > 4:
                            urls.append(full_url)
                logger.info(f"Found {len(urls)} property URLs via fallback method")
                return list(set(urls))[:50]

            for card in cards:
                try:
                    # Find the link in the card
                    link = card.query_selector('.propertyCard-link')
                    if link:
                        href = link.get_attribute('href')
                        if href and '/properties/' in href:
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
        """Extract property data from a Rightmove listing page."""
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
            price_elem = self.page.query_selector('[data-testid="property-price"]')
            if not price_elem:
                price_elem = self.page.query_selector('.propertyHeaderPrice')
            if price_elem:
                price_text = price_elem.inner_text()
                data['price'] = self.parse_price(price_text)

            # Extract address
            address_elem = self.page.query_selector('[data-testid="address-label"]')
            if not address_elem:
                address_elem = self.page.query_selector('h1._2uQQ3SV0eMHL1P6t5ZDo2q')
            if not address_elem:
                address_elem = self.page.query_selector('h1')
            if address_elem:
                data['address'] = address_elem.inner_text().strip()
                data['postcode'] = self.extract_postcode(data['address'])
                data['area'] = self.detect_area(data['address'])

            # Extract bedrooms, bathrooms, property type from key features
            self._extract_key_features(data)

            # Extract description
            desc_elem = self.page.query_selector('[data-testid="truncated-description"]')
            if not desc_elem:
                desc_elem = self.page.query_selector('.STw8udCxUaBUMfOOZu0iL')
            if desc_elem:
                data['description'] = desc_elem.inner_text().strip()[:2000]

            # Extract images
            data['image_urls'] = self._extract_images()

            # Extract listing date
            date_elem = self.page.query_selector('[data-testid="property-price-added"]')
            if date_elem:
                data['listing_date'] = self.parse_date(date_elem.inner_text())

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
        """Extract Rightmove property ID from URL."""
        match = re.search(r'/properties/(\d+)', url)
        if match:
            return match.group(1)
        return url.split('/')[-1].split('.')[0]

    def _extract_key_features(self, data: Dict[str, Any]):
        """Extract bedrooms, bathrooms, property type from key features."""
        try:
            # Try to find bedrooms from various elements
            bed_elem = self.page.query_selector('[data-testid="property-beds"]')
            if bed_elem:
                data['bedrooms'] = self.parse_bedrooms(bed_elem.inner_text())

            bath_elem = self.page.query_selector('[data-testid="property-baths"]')
            if bath_elem:
                data['bathrooms'] = self.parse_bedrooms(bath_elem.inner_text())

            # Property type
            type_elem = self.page.query_selector('[data-testid="property-type"]')
            if type_elem:
                data['property_type'] = self.normalize_property_type(type_elem.inner_text())

            # If not found, try alternative selectors
            if not data.get('bedrooms') or not data.get('property_type'):
                info_items = self.page.query_selector_all('._1fcftXUEbWfJOJzIUeIHKt')
                for item in info_items:
                    text = item.inner_text().lower()
                    if 'bed' in text and not data.get('bedrooms'):
                        data['bedrooms'] = self.parse_bedrooms(text)
                    elif 'bath' in text and not data.get('bathrooms'):
                        data['bathrooms'] = self.parse_bedrooms(text)

            # Try to get property type from title/header
            if not data.get('property_type'):
                title_elem = self.page.query_selector('h1')
                if title_elem:
                    title = title_elem.inner_text()
                    data['property_type'] = self.normalize_property_type(title)

        except Exception as e:
            logger.debug(f"Error extracting key features: {e}")

    def _extract_images(self) -> List[str]:
        """Extract property image URLs."""
        images = []
        try:
            # Try different image selectors
            img_elements = self.page.query_selector_all('[data-testid="gallery-image"] img')
            if not img_elements:
                img_elements = self.page.query_selector_all('.swiper-slide img')
            if not img_elements:
                img_elements = self.page.query_selector_all('._2zqynvtIxFMCq5dCVNRxoX img')

            for img in img_elements[:10]:  # Limit to 10 images
                src = img.get_attribute('src')
                if src and 'rightmove' in src:
                    # Get higher resolution version
                    src = re.sub(r'_max_\d+x\d+', '_max_656x437', src)
                    if src not in images:
                        images.append(src)

        except Exception as e:
            logger.debug(f"Error extracting images: {e}")

        return images
