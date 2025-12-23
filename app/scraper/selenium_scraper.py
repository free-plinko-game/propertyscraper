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

    def __init__(self, source: str, headless: bool = True, location: str = 'Oldham'):
        self.source = source
        self.headless = headless
        self.location = location  # The search location (e.g., 'Oldham', 'Manchester')
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

    def wait_random_delay(self, multiplier: float = 1.0):
        """Wait random delay between requests."""
        delay = random.uniform(self._delay_min, self._delay_max) * multiplier
        logger.debug(f"Waiting {delay:.2f} seconds")
        time.sleep(delay)

    def simulate_human_behavior(self):
        """Simulate human-like behavior on the page."""
        try:
            # Random scroll
            scroll_amount = random.randint(300, 700)
            self.driver.execute_script(f"window.scrollBy(0, {scroll_amount})")
            time.sleep(random.uniform(0.5, 1.5))

            # Scroll back up a bit
            self.driver.execute_script(f"window.scrollBy(0, -{random.randint(100, 200)})")
            time.sleep(random.uniform(0.3, 0.8))
        except Exception:
            pass

    def get_page_html(self, url: str, wait_for_listings: bool = False) -> Optional[str]:
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

            # Wait for listings to appear on search result pages
            if wait_for_listings:
                try:
                    if self.source == 'zoopla':
                        # Wait for Zoopla listing cards to load
                        WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR,
                                '[data-testid="regular-listings"], [data-testid="search-results"], .listing-results'))
                        )
                    elif self.source == 'rightmove':
                        # Wait for Rightmove listing cards
                        WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR,
                                '.l-searchResults, [data-test="results-list"]'))
                        )
                    # Extra wait for dynamic content to fully render
                    time.sleep(2)
                except TimeoutException:
                    logger.warning(f"Timeout waiting for listings to load on {url}")
                    # Continue anyway, maybe partial content loaded

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
        from urllib.parse import quote

        if self.source == 'rightmove':
            # Format location for URL (capitalize, replace spaces with hyphens)
            location_formatted = self.location.replace(' ', '-').title()
            if is_rental:
                base = f'{self.base_url}/property-to-rent/{location_formatted}.html?sortType=6&includeLetAgreed=false'
            else:
                base = f'{self.base_url}/property-for-sale/{location_formatted}.html?sortType=6&includeSSTC=false'

            if page > 0:
                # Rightmove uses index (0, 24, 48, etc.)
                index = page * 24
                base += f'&index={index}'
            return base

        elif self.source == 'zoopla':
            # Format location for URL (lowercase, replace spaces with hyphens for path)
            location_path = self.location.lower().replace(' ', '-')
            location_query = quote(self.location)
            if is_rental:
                base = f'{self.base_url}/to-rent/property/{location_path}/?q={location_query}&search_source=to-rent'
            else:
                base = f'{self.base_url}/for-sale/property/{location_path}/?q={location_query}&search_source=for-sale'

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
            # Look for next page link - try multiple selectors
            # 1. aria-label
            next_link = soup.find('a', {'aria-label': 'Next page'})
            if next_link:
                return True

            # 2. Text containing "Next"
            next_link = soup.find('a', text=re.compile(r'Next', re.I))
            if next_link:
                return True

            # 3. Pagination container with page numbers
            pagination = soup.find('nav', {'aria-label': re.compile(r'pagination', re.I)}) or \
                        soup.find('div', class_=re.compile(r'pagination', re.I)) or \
                        soup.find('ul', class_=re.compile(r'pagination', re.I))
            if pagination:
                # Look for a link to a higher page number
                page_links = pagination.find_all('a', href=True)
                for link in page_links:
                    href = link.get('href', '')
                    # Check if there's a page number parameter higher than current
                    pn_match = re.search(r'pn=(\d+)', href)
                    if pn_match:
                        linked_page = int(pn_match.group(1))
                        if linked_page > current_page + 1:
                            return True

            # 4. Check total results vs current position
            results_text = soup.find(text=re.compile(r'of\s+\d+\s+results', re.I)) or \
                          soup.find(text=re.compile(r'\d+\s+properties', re.I))
            if results_text:
                match = re.search(r'(\d+)\s*(results|properties)', str(results_text), re.I)
                if match:
                    total = int(match.group(1))
                    # Zoopla shows ~25 per page
                    if (current_page + 1) * 25 < total:
                        return True

            # 5. Look for any link with pn= parameter higher than current page
            all_links = soup.find_all('a', href=re.compile(r'pn=\d+'))
            for link in all_links:
                pn_match = re.search(r'pn=(\d+)', link.get('href', ''))
                if pn_match and int(pn_match.group(1)) > current_page + 1:
                    return True

        return False

    def _navigate_to_next_page(self, target_page: int) -> Optional[str]:
        """Navigate to next page by clicking pagination - more human-like than URL change."""
        try:
            # First simulate some human behavior
            self.simulate_human_behavior()

            # Longer delay before pagination (appear human)
            self.wait_random_delay(multiplier=1.5)

            # Scroll to bottom where pagination usually is
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1, 2))

            # Try to find and click the next page button
            next_page_num = target_page + 1  # Pages are 1-indexed in UI

            if self.source == 'zoopla':
                # Try multiple selectors for Zoopla pagination
                selectors = [
                    f'a[aria-label="Page {next_page_num}"]',
                    f'a[href*="pn={next_page_num}"]',
                    'a[aria-label="Next page"]',
                    'a:has-text("Next")',
                ]
            else:
                selectors = [
                    f'a[href*="index={target_page * 24}"]',
                    'a[data-test="pagination-next"]',
                ]

            clicked = False
            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            # Scroll element into view
                            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", elem)
                            time.sleep(random.uniform(0.5, 1))

                            # Click it
                            elem.click()
                            clicked = True
                            logger.info(f"Clicked pagination via selector: {selector}")
                            break
                except Exception:
                    continue

                if clicked:
                    break

            if not clicked:
                # Fallback to direct URL navigation
                logger.info(f"Pagination click failed, falling back to direct URL")
                search_url = self.build_search_url(is_rental=self._current_is_rental, page=target_page)
                return self.get_page_html(search_url, wait_for_listings=True)

            # Wait for new page to load
            time.sleep(random.uniform(2, 4))

            # Wait for listings
            try:
                if self.source == 'zoopla':
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR,
                            '[data-testid="regular-listings"], [data-testid="search-results"]'))
                    )
                elif self.source == 'rightmove':
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR,
                            '.l-searchResults, [data-test="results-list"]'))
                    )
                time.sleep(2)
            except TimeoutException:
                logger.warning(f"Timeout waiting for page {target_page + 1} to load after click")

            return self.driver.page_source

        except Exception as e:
            logger.error(f"Error navigating to page {target_page + 1}: {e}")
            return None

    def scrape(self, is_rental: bool = False, progress_callback: Optional[Callable] = None, fast_mode: bool = True) -> List[Dict[str, Any]]:
        """Main scraping method with pagination support and progress tracking.

        Args:
            is_rental: Whether to scrape rental listings
            progress_callback: Optional callback for progress updates
            fast_mode: If True, extract data from search results (faster).
                      If False, visit each property page (more detailed but slower).
        """
        self._current_is_rental = is_rental  # Store for pagination fallback
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
                    pbar.set_postfix_str(f"Page {page + 1}")

                    if page == 0:
                        # First page - navigate directly
                        search_url = self.build_search_url(is_rental=is_rental, page=page)
                        html = self.get_page_html(search_url, wait_for_listings=True)
                    else:
                        # Subsequent pages - try clicking pagination to appear more human
                        html = self._navigate_to_next_page(page)

                    if not html:
                        break

                    # Use Claude to parse all properties from search results
                    result = self.parser.parse_search_results(html, self.source, self.base_url)

                    if result and 'listings' in result and result['listings']:
                        for listing in result['listings']:
                            if len(properties) >= self._max_properties:
                                break

                            # Skip invalid listings
                            if not isinstance(listing, dict):
                                continue

                            # Must have a URL (required by database)
                            url = listing.get('url') or ''
                            if not url:
                                logger.debug(f"Skipping listing without URL: {listing.get('address', 'Unknown')}")
                                continue

                            # Must have at least an address or price
                            if not listing.get('address') and not listing.get('price'):
                                continue

                            # Add required fields
                            listing['source'] = self.source
                            listing['search_location'] = self.location
                            listing['is_rental'] = is_rental
                            listing['url'] = url  # Ensure URL is set
                            listing['source_id'] = self.parser.extract_source_id(url, self.source)

                            address = listing.get('address') or ''
                            if address:
                                listing['area'] = self._detect_area(address)

                            properties.append(listing)

                        logger.info(f"Page {page + 1}: extracted {len(result['listings'])} properties")
                    else:
                        logger.warning(f"Page {page + 1}: no listings found in response")
                        # Debug: check what's on the page
                        if html:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(html, 'lxml')
                            # Check for common block indicators
                            page_text = soup.get_text().lower()
                            if 'captcha' in page_text or 'verify' in page_text or 'robot' in page_text:
                                logger.warning(f"Page {page + 1}: Possible CAPTCHA/bot detection page")
                            elif 'no results' in page_text or 'no properties' in page_text:
                                logger.info(f"Page {page + 1}: No results message detected - end of listings")
                            else:
                                # Log a snippet of page content for debugging
                                title = soup.find('title')
                                title_text = title.get_text() if title else 'No title'
                                logger.debug(f"Page {page + 1} title: {title_text}")

                    pbar.update(1)

                    # Check for more pages
                    has_pagination = result and result.get('pagination', {}).get('next_page_url')
                    has_next = self.has_next_page(html, page)
                    found_listings = result and result.get('listings') and len(result['listings']) > 0

                    logger.debug(f"Page {page + 1}: has_pagination={has_pagination}, has_next={has_next}, found_listings={found_listings}")

                    # Continue if we have pagination info, or HTML shows next page,
                    # or we found listings on this page (assume more pages until proven otherwise)
                    if not has_pagination and not has_next:
                        # Even without pagination signals, if we found listings, try one more page
                        if not found_listings:
                            logger.info(f"Stopping pagination: no next page detected and no listings found")
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
                            property_data['search_location'] = self.location

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
        # Default to the search location
        return self.location

    def get_errors(self) -> List[str]:
        """Get list of errors that occurred during scraping."""
        return self.errors.copy()


class RightmoveSeleniumScraper(SeleniumScraper):
    """Rightmove scraper using Selenium and Claude."""

    def __init__(self, headless: bool = True, location: str = 'Oldham'):
        super().__init__(source='rightmove', headless=headless, location=location)


class ZooplaSeleniumScraper(SeleniumScraper):
    """Zoopla scraper using Selenium and Claude."""

    def __init__(self, headless: bool = True, location: str = 'Oldham'):
        super().__init__(source='zoopla', headless=headless, location=location)
