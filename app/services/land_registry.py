"""
Land Registry Price Paid Data Service

Fetches sold property prices from the UK Land Registry's linked data API.
Data is free and public: https://landregistry.data.gov.uk/
"""

import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import re
from functools import lru_cache


class LandRegistryService:
    """Service to fetch sold property prices from Land Registry."""

    BASE_URL = "https://landregistry.data.gov.uk/data/ppi/transaction-record.json"

    # Property type mapping from Land Registry codes
    PROPERTY_TYPES = {
        'D': 'Detached',
        'S': 'Semi-Detached',
        'T': 'Terraced',
        'F': 'Flat/Maisonette',
        'O': 'Other'
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'PropertyInvestor/1.0'
        })

    def _extract_outcode(self, postcode: str) -> str:
        """Extract the outcode (first part) from a postcode. E.g., 'OL2 8HF' -> 'OL2'"""
        if not postcode:
            return ''
        # Normalize and extract outcode
        postcode = postcode.strip().upper().replace(' ', '')
        # UK postcodes: outcode is everything except last 3 characters
        if len(postcode) >= 4:
            return postcode[:-3].strip()
        return postcode

    def _extract_street(self, address: str) -> Optional[str]:
        """Try to extract street name from an address."""
        if not address:
            return None
        # Common patterns: "123 Street Name" or "Flat X, 123 Street Name"
        # Remove flat/unit numbers
        address = re.sub(r'^(flat|unit|apartment)\s+\d+[a-z]?,?\s*', '', address, flags=re.IGNORECASE)
        # Try to find street name after house number
        match = re.search(r'\d+[a-z]?\s+(.+?)(?:,|$)', address, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def get_sold_prices_by_postcode(
        self,
        postcode: str,
        limit: int = 50,
        years_back: int = 3
    ) -> List[Dict]:
        """
        Fetch sold prices for properties in the same postcode area.

        Args:
            postcode: Full or partial UK postcode
            limit: Maximum number of results
            years_back: How many years of history to fetch

        Returns:
            List of transaction records with price, date, address, property type
        """
        if not postcode:
            return []

        # Clean up postcode - try full postcode first, then outcode
        postcode = postcode.strip().upper()

        # Calculate date threshold
        min_date = (datetime.now() - timedelta(days=years_back * 365)).strftime('%Y-%m-%d')

        transactions = []

        # Try full postcode first (without space, then with space)
        postcodes_to_try = [
            postcode.replace(' ', ''),  # OL28HF
            postcode if ' ' in postcode else f"{postcode[:-3]} {postcode[-3:]}" if len(postcode) > 3 else postcode  # OL2 8HF
        ]

        for pc in postcodes_to_try:
            try:
                params = {
                    'propertyAddress.postcode': pc,
                    '_pageSize': limit,
                    '_sort': '-transactionDate',
                    'min-transactionDate': min_date
                }

                response = self.session.get(self.BASE_URL, params=params, timeout=10)

                if response.status_code == 200:
                    data = response.json()
                    items = data.get('result', {}).get('items', [])

                    if items:
                        transactions = self._parse_transactions(items)
                        if transactions:
                            break

            except Exception as e:
                print(f"Land Registry API error for {pc}: {e}")
                continue

        # If no results for exact postcode, try outcode (broader area)
        if not transactions:
            outcode = self._extract_outcode(postcode)
            if outcode and len(outcode) >= 2:
                transactions = self._get_by_outcode(outcode, limit, min_date)

        return transactions

    def _get_by_outcode(self, outcode: str, limit: int, min_date: str) -> List[Dict]:
        """Fetch transactions for an outcode area using SPARQL-like query."""
        try:
            # The API supports wildcards in some cases, but let's use a broader approach
            # Query without postcode filter and let the API return area results
            params = {
                'propertyAddress.postcode': f"{outcode} *",  # Wildcard match
                '_pageSize': min(limit, 100),
                '_sort': '-transactionDate',
                'min-transactionDate': min_date
            }

            response = self.session.get(self.BASE_URL, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                items = data.get('result', {}).get('items', [])
                return self._parse_transactions(items)

        except Exception as e:
            print(f"Land Registry outcode query error: {e}")

        return []

    def _parse_transactions(self, items: List[Dict]) -> List[Dict]:
        """Parse API response items into clean transaction records."""
        transactions = []

        for item in items:
            try:
                # Extract price
                price = item.get('pricePaid', 0)
                if isinstance(price, str):
                    price = int(price)

                # Extract date
                date_str = item.get('transactionDate', '')
                if isinstance(date_str, dict):
                    date_str = date_str.get('@value', '')

                # Parse date
                try:
                    if date_str:
                        trans_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        trans_date = None
                except:
                    trans_date = None

                # Extract address components
                prop_address = item.get('propertyAddress', {})
                if isinstance(prop_address, dict):
                    paon = prop_address.get('paon', '')  # Primary addressable object name (house number/name)
                    saon = prop_address.get('saon', '')  # Secondary (flat number)
                    street = prop_address.get('street', '')
                    locality = prop_address.get('locality', '')
                    town = prop_address.get('town', '')
                    postcode = prop_address.get('postcode', '')
                else:
                    paon = saon = street = locality = town = postcode = ''

                # Build address string
                address_parts = []
                if saon:
                    address_parts.append(str(saon))
                if paon:
                    address_parts.append(str(paon))
                if street:
                    address_parts.append(str(street))
                if locality:
                    address_parts.append(str(locality))
                if town:
                    address_parts.append(str(town))

                address = ', '.join(filter(None, address_parts))

                # Extract property type
                prop_type_code = item.get('propertyType', '')
                if isinstance(prop_type_code, dict):
                    # Sometimes it's a URI reference
                    prop_type_code = prop_type_code.get('@id', '').split('/')[-1] or 'O'
                prop_type = self.PROPERTY_TYPES.get(prop_type_code, prop_type_code)

                # New build flag
                new_build = item.get('newBuild', False)
                if isinstance(new_build, dict):
                    new_build = new_build.get('@value', 'false') == 'true'
                elif isinstance(new_build, str):
                    new_build = new_build.lower() == 'true'

                # Estate type (freehold/leasehold)
                estate_type = item.get('estateType', '')
                if isinstance(estate_type, dict):
                    estate_type = estate_type.get('@id', '').split('/')[-1]

                transactions.append({
                    'price': price,
                    'date': trans_date.strftime('%Y-%m-%d') if trans_date else date_str,
                    'date_formatted': trans_date.strftime('%b %Y') if trans_date else 'Unknown',
                    'address': address,
                    'street': street,
                    'postcode': postcode,
                    'property_type': prop_type,
                    'property_type_code': prop_type_code,
                    'new_build': new_build,
                    'estate_type': estate_type.title() if estate_type else 'Unknown'
                })

            except Exception as e:
                print(f"Error parsing transaction: {e}")
                continue

        return transactions

    def get_similar_sales(
        self,
        postcode: str,
        property_type: Optional[str] = None,
        years_back: int = 2,
        limit: int = 20
    ) -> Dict:
        """
        Get similar property sales with statistics.

        Returns:
            Dict with 'sales' list and 'stats' summary (avg, min, max prices)
        """
        all_sales = self.get_sold_prices_by_postcode(postcode, limit=100, years_back=years_back)

        # Filter by property type if specified
        if property_type and all_sales:
            type_lower = property_type.lower()
            filtered = []
            for sale in all_sales:
                sale_type = sale.get('property_type', '').lower()
                # Fuzzy match property types
                if (type_lower in sale_type or
                    sale_type in type_lower or
                    (type_lower in ['flat', 'apartment'] and 'flat' in sale_type) or
                    (type_lower in ['house', 'detached', 'semi-detached', 'terraced'] and
                     sale_type in ['detached', 'semi-detached', 'terraced'])):
                    filtered.append(sale)

            # If we have filtered results, use them; otherwise fall back to all
            if filtered:
                all_sales = filtered

        # Limit results
        sales = all_sales[:limit]

        # Calculate statistics
        if sales:
            prices = [s['price'] for s in sales if s['price'] > 0]
            stats = {
                'count': len(prices),
                'avg_price': sum(prices) // len(prices) if prices else 0,
                'min_price': min(prices) if prices else 0,
                'max_price': max(prices) if prices else 0,
                'years_covered': years_back
            }
        else:
            stats = {
                'count': 0,
                'avg_price': 0,
                'min_price': 0,
                'max_price': 0,
                'years_covered': years_back
            }

        return {
            'sales': sales,
            'stats': stats
        }


# Singleton instance
land_registry = LandRegistryService()


def get_sold_prices(postcode: str, years_back: int = 2, limit: int = 20) -> Dict:
    """Convenience function to get sold prices for a postcode."""
    return land_registry.get_similar_sales(postcode, years_back=years_back, limit=limit)


def get_similar_sales(postcode: str, property_type: str = None, years_back: int = 2) -> Dict:
    """Get similar property sales with statistics."""
    return land_registry.get_similar_sales(postcode, property_type, years_back)
