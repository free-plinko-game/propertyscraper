"""Selenium-based property scraper with Claude AI parsing and pagination support."""
import logging
import os
import random
import time
import re
from typing import Optional, List, Dict, Any, Callable
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from tqdm import tqdm

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

        # Don't wait for full page load (cookie banners can block this)
        chrome_options.page_load_strategy = 'eager'

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
            self.driver.set_page_load_timeout(30)  # Reduced from 60
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

            # Wait for page to load (reduced timeout)
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # Handle cookie consent (only on first page load)
            if not hasattr(self, '_cookie_handled'):
                self._handle_cookie_consent()
                self._cookie_handled = True

            # Brief wait for dynamic content
            time.sleep(0.5)

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
            # Rightmove specific - try immediately, no pre-wait
            if self.source == 'rightmove':
                try:
                    accept_btn = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
                    )
                    accept_btn.click()
                    logger.info("Rightmove cookie consent accepted")
                    return
                except Exception:
                    pass

            # Zoopla specific
            if self.source == 'zoopla':
                try:
                    accept_btn = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "button#accept[data-action='consent']"))
                    )
                    accept_btn.click()
                    logger.info("Zoopla cookie consent accepted")
                    return
                except Exception:
                    pass

            # Quick check for generic selectors (no wait)
            selectors = [
                (By.ID, "onetrust-accept-btn-handler"),
                (By.ID, "accept"),
                (By.CSS_SELECTOR, "button.accept"),
            ]

            for by, selector in selectors:
                try:
                    elements = self.driver.find_elements(by, selector)
                    if elements and elements[0].is_displayed():
                        elements[0].click()
                        logger.info(f"Cookie consent accepted via {selector}")
                        return
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"No cookie consent or already handled: {e}")

    def build_search_url(self, is_rental: bool = False, page: int = 0) -> str:
        """Build search URL for the source."""
        if self.source == 'rightmove':
            # Use location name-based URL for Oldham
            if is_rental:
                base = f'{self.base_url}/property-to-rent/Oldham.html?sortType=6&includeLetAgreed=false'
            else:
                base = f'{self.base_url}/property-for-sale/Oldham.html?sortType=6&includeSSTC=false'

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

    def scrape(self, is_rental: bool = False, progress_callback: Optional[Callable] = None, fast_mode: bool = True) -> List[Dict[str, Any]]:
        """Main scraping method with pagination support and progress tracking.

        Args:
            is_rental: Whether to scrape rental listings
            progress_callback: Optional callback for progress updates
            fast_mode: If True, extract data from search results (faster).
                      If False, visit each property page (more detailed but slower).
        """
        if fast_mode:
            return self._scrape_fast_mode(is_rental, progress_callback)
        else:
            return self._scrape_detailed_mode(is_rental, progress_callback)

    def _scrape_fast_mode(self, is_rental: bool, progress_callback: Optional[Callable]) -> List[Dict[str, Any]]:
        """Fast scraping - extract data directly from search results pages."""
        properties = []

        def update_progress(stage: str, current: int, total: int, message: str = ""):
            if progress_callback:
                progress_callback(stage, current, total, message)
            logger.info(f"[{stage}] {current}/{total} - {message}")

        try:
            update_progress("init", 0, 1, "Starting browser...")
            self.start_browser()
            self.parser = ClaudePropertyParser()
            update_progress("init", 1, 1, "Browser started")

            print(f"\n🚀 Fast mode: Extracting from search results pages...")

            page = 0
            with tqdm(total=self._max_pages, desc=f"📄 {self.source.title()} pages", unit="page") as pbar:
                while page < self._max_pages and len(properties) < self._max_properties:
                    search_url = self.build_search_url(is_rental=is_rental, page=page)
                    pbar.set_postfix_str(f"Page {page + 1}")

                    html = self.get_page_html(search_url)
                    if not html:
                        break

                    # Use Claude to parse all properties from search results
                    result = self.parser.parse_search_results(html, self.source, self.base_url)

                    if result and 'listings' in result:
                        for listing in result['listings']:
                            if len(properties) >= self._max_properties:
                                break

                            # Add required fields
                            listing['source'] = self.source
                            listing['is_rental'] = is_rental
                            listing['source_id'] = self.parser.extract_source_id(
                                listing.get('url', ''), self.source
                            )
                            if listing.get('address'):
                                listing['area'] = self._detect_area(listing['address'])

                            properties.append(listing)

                        logger.info(f"Page {page + 1}: extracted {len(result['listings'])} properties")

                    pbar.update(1)

                    # Check for more pages
                    if not result or not result.get('pagination', {}).get('next_page_url'):
                        if not self.has_next_page(html, page):
                            break

                    page += 1
                    self.wait_random_delay()

            print(f"✅ Completed: {len(properties)} properties extracted from {self.source}\n")

        except Exception as e:
            error_msg = f"Scraping failed for {self.source}: {str(e)}"
            logger.error(error_msg)
            self.errors.append(error_msg)

        finally:
            self.close_browser()

        return properties

    def _scrape_detailed_mode(self, is_rental: bool, progress_callback: Optional[Callable]) -> List[Dict[str, Any]]:
        """Detailed scraping - visit each property page for full data."""
        properties = []

        def update_progress(stage: str, current: int, total: int, message: str = ""):
            """Update progress via callback or logger."""
            if progress_callback:
                progress_callback(stage, current, total, message)
            logger.info(f"[{stage}] {current}/{total} - {message}")

        try:
            update_progress("init", 0, 1, "Starting browser...")
            self.start_browser()
            self.parser = ClaudePropertyParser()
            update_progress("init", 1, 1, "Browser started")

            page = 0
            all_listing_urls = []

            # Phase 1: Collect listing URLs from multiple pages
            update_progress("collecting", 0, self._max_pages, "Collecting listing URLs...")

            while page < self._max_pages and len(all_listing_urls) < self._max_properties:
                search_url = self.build_search_url(is_rental=is_rental, page=page)
                update_progress("collecting", page + 1, self._max_pages, f"Page {page + 1}: fetching listings...")

                html = self.get_page_html(search_url)
                if not html:
                    update_progress("collecting", page + 1, self._max_pages, f"Page {page + 1}: failed to load")
                    break

                self.wait_random_delay()

                # Extract listing URLs from this page
                page_urls = self.extract_listing_urls_from_html(html)
                all_listing_urls.extend([u for u in page_urls if u not in all_listing_urls])

                update_progress("collecting", page + 1, self._max_pages, f"Found {len(all_listing_urls)} listings so far")

                # Check for next page
                if not self.has_next_page(html, page):
                    break

                page += 1

            # Limit to max properties
            all_listing_urls = all_listing_urls[:self._max_properties]
            total_listings = len(all_listing_urls)
            update_progress("collecting", self._max_pages, self._max_pages, f"Collected {total_listings} listing URLs")

            # Phase 2: Process each listing with progress bar
            print(f"\n📋 Processing {total_listings} property listings from {self.source}...")

            with tqdm(total=total_listings, desc=f"🏠 {self.source.title()}", unit="property",
                      bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]") as pbar:

                for i, url in enumerate(all_listing_urls):
                    if self.properties_scraped >= self._max_properties:
                        break

                    self.wait_random_delay()

                    try:
                        html = self.get_page_html(url)
                        if not html:
                            pbar.update(1)
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

                            # Update progress bar description with last address
                            short_addr = property_data.get('address', 'Unknown')[:30]
                            pbar.set_postfix_str(f"✓ {short_addr}...")

                        pbar.update(1)
                        update_progress("scraping", i + 1, total_listings, f"Scraped: {property_data.get('address', 'Unknown')}" if property_data else "Skipped")

                    except Exception as e:
                        error_msg = f"Error extracting property from {url}: {str(e)}"
                        logger.error(error_msg)
                        self.errors.append(error_msg)
                        pbar.update(1)

            print(f"✅ Completed: {len(properties)} properties scraped from {self.source}\n")

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
