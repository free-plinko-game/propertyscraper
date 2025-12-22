"""Claude API-based HTML parser for property data extraction."""
import json
import logging
import os
from typing import Optional, Dict, Any, List

from anthropic import Anthropic
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ClaudePropertyParser:
    """Use Claude API to parse property listing HTML into structured JSON."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        self.client = Anthropic(api_key=self.api_key)
        self.model = "claude-sonnet-4-20250514"

    def clean_html(self, html: str) -> str:
        """Clean HTML using BeautifulSoup to reduce tokens sent to Claude."""
        soup = BeautifulSoup(html, 'lxml')

        # Remove script, style, and other non-content elements
        for tag in soup.find_all(['script', 'style', 'noscript', 'iframe', 'svg', 'path', 'meta', 'link']):
            tag.decompose()

        # Remove comments
        from bs4 import Comment
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Remove empty elements
        for tag in soup.find_all():
            if not tag.get_text(strip=True) and not tag.find_all('img'):
                tag.decompose()

        # Get text with some structure preserved
        return soup.get_text(separator='\n', strip=True)

    def extract_relevant_html(self, html: str, source: str) -> str:
        """Extract only the relevant parts of HTML for property data."""
        soup = BeautifulSoup(html, 'lxml')

        # Remove script, style, and other non-content elements
        for tag in soup.find_all(['script', 'style', 'noscript', 'iframe', 'svg', 'path']):
            tag.decompose()

        # Try to find the main content area
        main_content = None

        if source == 'rightmove':
            # Rightmove specific selectors
            main_content = soup.find('main') or soup.find('article') or soup.find('div', {'id': 'root'})
        elif source == 'zoopla':
            # Zoopla specific selectors
            main_content = soup.find('main') or soup.find('article') or soup.find('div', {'class': 'listing-details'})

        if main_content:
            return str(main_content)

        # Fallback: return body content
        body = soup.find('body')
        if body:
            return str(body)

        return html

    def parse_property_listing(self, html: str, url: str, source: str, is_rental: bool = False) -> Optional[Dict[str, Any]]:
        """Parse a single property listing HTML using Claude API."""
        try:
            # Clean and extract relevant HTML
            relevant_html = self.extract_relevant_html(html, source)
            cleaned_text = self.clean_html(relevant_html)

            # Truncate if too long to save tokens
            max_chars = 15000
            if len(cleaned_text) > max_chars:
                cleaned_text = cleaned_text[:max_chars] + "\n... [truncated]"

            prompt = f"""Extract property listing data from this {source} webpage content.
The property URL is: {url}
This is a {"rental" if is_rental else "sale"} listing.

Webpage content:
{cleaned_text}

Extract the following information and return as JSON:
- price: The property price as an integer (in GBP, no currency symbol). For rentals, extract the monthly rent.
- address: Full property address as a string
- postcode: UK postcode extracted from address (format like "OL1 2AB")
- bedrooms: Number of bedrooms as integer
- bathrooms: Number of bathrooms as integer (if available)
- property_type: Type of property (one of: terrace, semi, detached, flat, bungalow, cottage, or the original type if doesn't match)
- description: Property description text (max 500 chars)
- image_urls: Array of image URLs found (max 10)
- listing_date: When the property was listed (ISO date format if found, null otherwise)
- key_features: Array of key features/bullet points if available

Return ONLY valid JSON, no other text. If a field cannot be found, use null.
Example format:
{{"price": 175000, "address": "123 Main St, Oldham OL1 2AB", "postcode": "OL1 2AB", "bedrooms": 3, "bathrooms": 1, "property_type": "terrace", "description": "...", "image_urls": ["url1", "url2"], "listing_date": null, "key_features": ["Garden", "Parking"]}}"""

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = response.content[0].text.strip()

            # Try to parse JSON from response
            # Handle potential markdown code blocks
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            property_data = json.loads(response_text)

            # Add source information
            property_data['url'] = url
            property_data['source'] = source
            property_data['is_rental'] = is_rental

            logger.info(f"Successfully parsed property: {property_data.get('address', 'Unknown')}")
            return property_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.debug(f"Response was: {response_text[:500] if 'response_text' in locals() else 'No response'}")
            return None
        except Exception as e:
            logger.error(f"Error parsing property listing: {e}")
            return None

    def parse_search_results(self, html: str, source: str, base_url: str) -> List[Dict[str, Any]]:
        """Parse search results page to extract listing URLs and basic info."""
        try:
            cleaned_text = self.clean_html(html)

            # Truncate if too long
            max_chars = 20000
            if len(cleaned_text) > max_chars:
                cleaned_text = cleaned_text[:max_chars] + "\n... [truncated]"

            prompt = f"""Extract property listing information from this {source} search results page.
Base URL is: {base_url}

Webpage content:
{cleaned_text}

Extract ALL property listings visible on this page. For each listing, extract:
- url: The full URL to the property listing page (combine with base URL if relative)
- price: Price as integer
- address: Property address
- bedrooms: Number of bedrooms
- property_type: Type of property

Also extract pagination information:
- current_page: Current page number
- total_pages: Total number of pages (if visible)
- next_page_url: URL for next page (if available)

Return as JSON with format:
{{"listings": [...], "pagination": {{"current_page": 1, "total_pages": null, "next_page_url": null}}}}

Return ONLY valid JSON, no other text."""

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = response.content[0].text.strip()

            # Handle markdown code blocks
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            return json.loads(response_text)

        except Exception as e:
            logger.error(f"Error parsing search results: {e}")
            return {"listings": [], "pagination": {"current_page": 1, "total_pages": None, "next_page_url": None}}

    def extract_source_id(self, url: str, source: str) -> str:
        """Extract the source-specific property ID from URL."""
        import re

        if not url:
            return ''

        if source == 'rightmove':
            match = re.search(r'/properties/(\d+)', url)
            if match:
                return match.group(1)
        elif source == 'zoopla':
            match = re.search(r'/details/(\d+)', url)
            if match:
                return match.group(1)

        # Fallback: use last path segment
        return url.rstrip('/').split('/')[-1].split('.')[0].split('?')[0]
