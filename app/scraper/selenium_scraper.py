"""Selenium-based property scraper with Claude AI parsing and pagination support."""
import logging
import os
import random
import time
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from flask import current_app
from .claude_parser import ClaudePropertyParser

logger = logging.getLogger(__name__)


class SeleniumScraper:
    """Selenium-based scraper with Claude AI parsing for property websites."""

    def __init__(self, source: str, headless: bool = True):
        self.source = source
        self.headless = headless
        self.driver = None
        self.parser = None
        self.properties_scraped = 0
        self.errors: List[str] = []

        # Config values
        self._delay_min = current_app.config.get('SCRAPE_DELAY_MIN', 3)
        self._delay_max = current_app.config.get('SCRAPE_DELAY_MAX', 7)
        self._max_properties = current_app.config.get('MAX_PROPERTIES_PER_SCRAPE', 50)
        self._max_pages = current_app.config.get('MAX_PAGES_PER_SCRAPE', 5)
        self._location_areas = current_app.config.get('LOCATION_AREAS', [])

    @property
    def base_url(self) -> str:
        if self.source == 'rightmove':
            return 'https://www.rightmove.co.uk'
        elif self.source == 'zoopla':
            return 'https://www.zoopla.co.uk'
        return ''

    def start_browser(self):
        """Initialize Selenium browser."""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        # Anti-detection options
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        try:
            # Look for local chromedriver first
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            local_chromedriver = os.path.join(project_root, 'chromedriver')

            if os.path.exists(local_chromedriver):
                logger.info(f"Using local chromedriver: {local_chromedriver}")
                service = Service(local_chromedriver)
            else:
                # Fall back to webdriver-manager
                from webdriver_manager.chrome import ChromeDriverManager
                logger.info("Using webdriver-manager for chromedriver")
                service = Service(ChromeDriverManager().install())

            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.set_page_load_timeout(60)
            # Remove webdriver property to avoid detection
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            logger.info(f"Browser started for {self.source}")
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            raise

    def close_browser(self):
        """Close browser."""
        if self.driver:
            self.driver.quit()
            logger.info(f"Browser closed for {self.source}")

    def wait_random_delay(self):
        """Wait random delay between requests."""
        delay = random.uniform(self._delay_min, self._delay_max)
        logger.debug(f"Waiting {delay:.2f} seconds")
        time.sleep(delay)

    def get_page_html(self, url: str) -> Optional[str]:
        """Navigate to URL and return page HTML."""
        try:
            logger.info(f"Fetching: {url}")
            self.driver.get(url)

            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Handle cookie consent
            self._handle_cookie_consent()

            # Small wait for dynamic content
            time.sleep(2)

            return self.driver.page_source

        except TimeoutException:
            logger.error(f"Timeout loading: {url}")
            self.errors.append(f"Timeout loading: {url}")
            return None
        except WebDriverException as e:
            logger.error(f"WebDriver error: {e}")
            self.errors.append(f"WebDriver error: {str(e)}")
            return None

    def _handle_cookie_consent(self):
        """Handle cookie consent banners."""
        try:
            # Common cookie consent button selectors
            selectors = [
                "button[id*='accept']",
                "button[class*='accept']",
                "button:contains('Accept')",
                "button:contains('Got it')",
                "button:contains('Allow')",
                "#onetrust-accept-btn-handler",
                ".cookie-consent-accept",
            ]

            for selector in selectors:
                try:
                    if selector.startswith("button:contains"):
                        # Use XPath for contains
                        text = selector.split("'")[1]
                        elements = self.driver.find_elements(By.XPATH, f"//button[contains(text(), '{text}')]")
                    else:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)

                    if elements:
                        elements[0].click()
                        logger.debug("Cookie consent handled")
                        time.sleep(1)
                        return
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"No cookie consent or already handled: {e}")

    def build_search_url(self, is_rental: bool = False, page: int = 0) -> str:
        """Build search URL for the source."""
        if self.source == 'rightmove':
            location_id = 'REGION%5E904'  # Oldham
            if is_rental:
                base = f'{self.base_url}/property-to-rent/find.html?locationIdentifier={location_id}&sortType=6&propertyTypes=&includeLetAgreed=false'
            else:
                base = f'{self.base_url}/property-for-sale/find.html?locationIdentifier={location_id}&sortType=6&propertyTypes=&includeSSTC=false'

            if page > 0:
                # Rightmove uses index (0, 24, 48, etc.)
                index = page * 24
                base += f'&index={index}'
            return base

        elif self.source == 'zoopla':
            if is_rental:
                base = f'{self.base_url}/to-rent/property/oldham/?q=Oldham&search_source=to-rent'
            else:
                base = f'{self.base_url}/for-sale/property/oldham/?q=Oldham&search_source=for-sale'

            if page > 0:
                base += f'&pn={page + 1}'
            return base

        return ''

    def extract_listing_urls_from_html(self, html: str) -> List[str]:
        """Extract listing URLs from search results HTML using BeautifulSoup."""
        from bs4 import BeautifulSoup
        urls = []

        soup = BeautifulSoup(html, 'lxml')

        if self.source == 'rightmove':
            # Find property links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '/properties/' in href and href not in urls:
                    full_url = urljoin(self.base_url, href.split('#')[0].split('?')[0])
                    if full_url not in urls:
                        urls.append(full_url)

        elif self.source == 'zoopla':
            # Find property links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '/details/' in href and href not in urls:
                    full_url = urljoin(self.base_url, href.split('#')[0].split('?')[0])
                    if full_url not in urls:
                        urls.append(full_url)

        logger.info(f"Found {len(urls)} listing URLs on page")
        return urls

    def has_next_page(self, html: str, current_page: int) -> bool:
        """Check if there's a next page of results."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')

        if self.source == 'rightmove':
            # Look for pagination
            pagination = soup.find('div', class_='pagination') or soup.find('nav', {'aria-label': 'Pagination'})
            if pagination:
                next_btn = pagination.find('a', text=re.compile(r'Next|>'))
                if next_btn and 'disabled' not in str(next_btn.get('class', [])):
                    return True

            # Check if there are more properties by looking at results count
            results_count = soup.find(text=re.compile(r'\d+ properties'))
            if results_count:
                match = re.search(r'(\d+)\s*properties', results_count)
                if match:
                    total = int(match.group(1))
                    if (current_page + 1) * 24 < total:
                        return True

        elif self.source == 'zoopla':
            # Look for next page link
            next_link = soup.find('a', {'aria-label': 'Next page'}) or soup.find('a', text='Next')
            if next_link:
                return True

        return False

    def scrape(self, is_rental: bool = False) -> List[Dict[str, Any]]:
        """Main scraping method with pagination support."""
        properties = []

        try:
            self.start_browser()
            self.parser = ClaudePropertyParser()

            page = 0
            all_listing_urls = []

            # Collect listing URLs from multiple pages
            while page < self._max_pages and len(all_listing_urls) < self._max_properties:
                search_url = self.build_search_url(is_rental=is_rental, page=page)
                logger.info(f"Scraping page {page + 1}: {search_url}")

                html = self.get_page_html(search_url)
                if not html:
                    logger.error(f"Failed to get HTML for page {page + 1}")
                    break

                self.wait_random_delay()

                # Extract listing URLs from this page
                page_urls = self.extract_listing_urls_from_html(html)
                all_listing_urls.extend([u for u in page_urls if u not in all_listing_urls])

                logger.info(f"Total URLs collected: {len(all_listing_urls)}")

                # Check for next page
                if not self.has_next_page(html, page):
                    logger.info("No more pages available")
                    break

                page += 1

            # Limit to max properties
            all_listing_urls = all_listing_urls[:self._max_properties]
            logger.info(f"Processing {len(all_listing_urls)} property listings")

            # Process each listing
            for url in all_listing_urls:
                if self.properties_scraped >= self._max_properties:
                    logger.info(f"Reached max properties limit ({self._max_properties})")
                    break

                self.wait_random_delay()

                try:
                    html = self.get_page_html(url)
                    if not html:
                        continue

                    # Parse with Claude
                    property_data = self.parser.parse_property_listing(
                        html=html,
                        url=url,
                        source=self.source,
                        is_rental=is_rental
                    )

                    if property_data:
                        # Extract source ID
                        property_data['source_id'] = self.parser.extract_source_id(url, self.source)

                        # Detect area
                        if property_data.get('address'):
                            property_data['area'] = self._detect_area(property_data['address'])

                        properties.append(property_data)
                        self.properties_scraped += 1
                        logger.info(f"Scraped property {self.properties_scraped}: {property_data.get('address', 'Unknown')}")

                except Exception as e:
                    error_msg = f"Error extracting property from {url}: {str(e)}"
                    logger.error(error_msg)
                    self.errors.append(error_msg)

        except Exception as e:
            error_msg = f"Scraping failed for {self.source}: {str(e)}"
            logger.error(error_msg)
            self.errors.append(error_msg)

        finally:
            self.close_browser()

        return properties

    def _detect_area(self, address: str) -> Optional[str]:
        """Detect area from address based on known areas."""
        if not address:
            return None
        address_upper = address.upper()
        for area in self._location_areas:
            if area.upper() in address_upper:
                return area
        return 'Oldham'

    def get_errors(self) -> List[str]:
        """Get list of errors that occurred during scraping."""
        return self.errors.copy()


class RightmoveSeleniumScraper(SeleniumScraper):
    """Rightmove scraper using Selenium and Claude."""

    def __init__(self, headless: bool = True):
        super().__init__(source='rightmove', headless=headless)


class ZooplaSeleniumScraper(SeleniumScraper):
    """Zoopla scraper using Selenium and Claude."""

    def __init__(self, headless: bool = True):
        super().__init__(source='zoopla', headless=headless)
