"""
Land Registry Price Paid Data Service

Fetches sold property prices from the UK Land Registry's linked data API.
Data is free and public: https://landregistry.data.gov.uk/

Uses both REST API and SPARQL endpoint for flexible querying by:
- Full postcode
- Partial postcode (outcode)
- Street name + town
- Address components
"""

import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import re
from functools import lru_cache


class LandRegistryService:
    """Service to fetch sold property prices from Land Registry."""

    BASE_URL = "https://landregistry.data.gov.uk/data/ppi/transaction-record.json"
    SPARQL_URL = "https://landregistry.data.gov.uk/landregistry/query"

    # Property type mapping from Land Registry codes
    PROPERTY_TYPES = {
        'D': 'Detached',
        'S': 'Semi-Detached',
        'T': 'Terraced',
        'F': 'Flat/Maisonette',
        'O': 'Other'
    }

    # Property type URIs in SPARQL results
    PROPERTY_TYPE_URIS = {
        'detached': 'Detached',
        'semi-detached': 'Semi-Detached',
        'terraced': 'Terraced',
        'flat-maisonette': 'Flat/Maisonette',
        'otherPropertyType': 'Other'
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

    def _extract_town(self, address: str) -> Optional[str]:
        """Try to extract town/city from an address."""
        if not address:
            return None
        # Split by comma and look for town-like parts
        parts = [p.strip() for p in address.split(',')]
        # Common UK towns often appear after street, before postcode
        # Look for parts that don't look like street numbers or postcodes
        for part in reversed(parts):
            # Skip if it looks like a postcode
            if re.match(r'^[A-Z]{1,2}\d', part, re.IGNORECASE):
                continue
            # Skip if it's just a number
            if re.match(r'^\d+[a-z]?$', part, re.IGNORECASE):
                continue
            # Skip common street suffixes
            if re.match(r'.*\b(street|road|lane|avenue|drive|close|way|court|place|gardens|crescent|terrace)\b.*', part, re.IGNORECASE):
                continue
            if len(part) > 2:
                return part
        return None

    def _sparql_query(self, query: str) -> List[Dict]:
        """Execute a SPARQL query against the Land Registry endpoint."""
        try:
            response = self.session.post(
                self.SPARQL_URL,
                data={'query': query},
                headers={'Accept': 'application/sparql-results+json'},
                timeout=15
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('results', {}).get('bindings', [])
        except Exception as e:
            print(f"SPARQL query error: {e}")
        return []

    def _parse_sparql_results(self, results: List[Dict]) -> List[Dict]:
        """Parse SPARQL results into transaction records."""
        transactions = []
        for row in results:
            try:
                price = int(row.get('price', {}).get('value', 0))
                date_str = row.get('date', {}).get('value', '')

                # Parse date
                trans_date = None
                date_formatted = 'Unknown'
                if date_str:
                    try:
                        trans_date = datetime.strptime(date_str[:10], '%Y-%m-%d')
                        date_formatted = trans_date.strftime('%b %Y')
                    except:
                        date_formatted = date_str[:10]

                # Build address
                paon = row.get('paon', {}).get('value', '')
                saon = row.get('saon', {}).get('value', '')
                street = row.get('street', {}).get('value', '')
                town = row.get('town', {}).get('value', '')
                postcode = row.get('postcode', {}).get('value', '')

                address_parts = []
                if saon:
                    address_parts.append(saon)
                if paon:
                    address_parts.append(paon)
                if street:
                    address_parts.append(street)
                if town:
                    address_parts.append(town)
                address = ', '.join(filter(None, address_parts))

                # Property type from URI
                prop_type_uri = row.get('propertyType', {}).get('value', '')
                prop_type = 'Unknown'
                for key, value in self.PROPERTY_TYPE_URIS.items():
                    if key in prop_type_uri.lower():
                        prop_type = value
                        break

                # New build
                new_build_val = row.get('newBuild', {}).get('value', '')
                new_build = 'true' in new_build_val.lower() if new_build_val else False

                transactions.append({
                    'price': price,
                    'date': trans_date.strftime('%Y-%m-%d') if trans_date else date_str,
                    'date_formatted': date_formatted,
                    'address': address,
                    'street': street,
                    'postcode': postcode,
                    'property_type': prop_type,
                    'new_build': new_build,
                    'estate_type': 'Unknown'
                })
            except Exception as e:
                print(f"Error parsing SPARQL result: {e}")
                continue
        return transactions

    def get_sold_prices_by_address(
        self,
        address: str,
        town: Optional[str] = None,
        limit: int = 50,
        years_back: int = 3
    ) -> List[Dict]:
        """
        Fetch sold prices using address components (street, town).
        Uses SPARQL for flexible matching.

        Args:
            address: Full address string to extract street from
            town: Town/city name (extracted from address if not provided)
            limit: Maximum results
            years_back: Years of history

        Returns:
            List of transaction records
        """
        street = self._extract_street(address)
        if not town:
            town = self._extract_town(address)

        if not street and not town:
            return []

        min_date = (datetime.now() - timedelta(days=years_back * 365)).strftime('%Y-%m-%d')

        # Build SPARQL query with available filters
        filters = [f'FILTER (?date >= "{min_date}"^^xsd:date)']

        if street:
            # Use CONTAINS for fuzzy street matching
            street_clean = street.replace("'", "\\'").upper()
            filters.append(f'FILTER (CONTAINS(UCASE(?street), "{street_clean}"))')

        if town:
            town_clean = town.replace("'", "\\'").upper()
            filters.append(f'FILTER (CONTAINS(UCASE(?town), "{town_clean}"))')

        query = f"""
        PREFIX ppd: <http://landregistry.data.gov.uk/def/ppi/>
        PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>

        SELECT ?price ?date ?paon ?saon ?street ?town ?postcode ?propertyType ?newBuild
        WHERE {{
            ?txn ppd:pricePaid ?price ;
                 ppd:transactionDate ?date ;
                 ppd:propertyAddress ?addr ;
                 ppd:propertyType ?propertyType .

            ?addr lrcommon:street ?street ;
                  lrcommon:town ?town .

            OPTIONAL {{ ?addr lrcommon:paon ?paon }}
            OPTIONAL {{ ?addr lrcommon:saon ?saon }}
            OPTIONAL {{ ?addr lrcommon:postcode ?postcode }}
            OPTIONAL {{ ?txn ppd:newBuild ?newBuild }}

            {' '.join(filters)}
        }}
        ORDER BY DESC(?date)
        LIMIT {limit}
        """

        results = self._sparql_query(query)
        return self._parse_sparql_results(results)

    def get_sold_prices_by_outcode(
        self,
        outcode: str,
        limit: int = 50,
        years_back: int = 3
    ) -> List[Dict]:
        """
        Fetch sold prices for a postcode outcode area using SPARQL.
        Much more reliable than the REST API wildcards.

        Args:
            outcode: Postcode outcode (e.g., 'M35', 'OL2')
            limit: Maximum results
            years_back: Years of history

        Returns:
            List of transaction records
        """
        if not outcode or len(outcode) < 2:
            return []

        outcode = outcode.strip().upper()
        min_date = (datetime.now() - timedelta(days=years_back * 365)).strftime('%Y-%m-%d')

        query = f"""
        PREFIX ppd: <http://landregistry.data.gov.uk/def/ppi/>
        PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>

        SELECT ?price ?date ?paon ?saon ?street ?town ?postcode ?propertyType ?newBuild
        WHERE {{
            ?txn ppd:pricePaid ?price ;
                 ppd:transactionDate ?date ;
                 ppd:propertyAddress ?addr ;
                 ppd:propertyType ?propertyType .

            ?addr lrcommon:postcode ?postcode ;
                  lrcommon:street ?street ;
                  lrcommon:town ?town .

            OPTIONAL {{ ?addr lrcommon:paon ?paon }}
            OPTIONAL {{ ?addr lrcommon:saon ?saon }}
            OPTIONAL {{ ?txn ppd:newBuild ?newBuild }}

            FILTER (STRSTARTS(?postcode, "{outcode}"))
            FILTER (?date >= "{min_date}"^^xsd:date)
        }}
        ORDER BY DESC(?date)
        LIMIT {limit}
        """

        results = self._sparql_query(query)
        return self._parse_sparql_results(results)

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
        """Fetch transactions for an outcode area using SPARQL (more reliable than REST wildcards)."""
        # Calculate years back from min_date
        try:
            min_dt = datetime.strptime(min_date, '%Y-%m-%d')
            years_back = max(1, (datetime.now() - min_dt).days // 365)
        except:
            years_back = 3

        return self.get_sold_prices_by_outcode(outcode, limit=limit, years_back=years_back)

    def _parse_transactions(self, items: List[Dict]) -> List[Dict]:
        """Parse API response items into clean transaction records."""
        transactions = []

        for item in items:
            try:
                # Extract price
                price = item.get('pricePaid', 0)
                if isinstance(price, str):
                    price = int(price)

                # Extract date - format is "Fri, 20 Sep 2024"
                date_str = item.get('transactionDate', '')
                trans_date = None
                date_formatted = 'Unknown'

                if date_str:
                    try:
                        # Try parsing "Fri, 20 Sep 2024" format
                        from datetime import datetime
                        trans_date = datetime.strptime(date_str, '%a, %d %b %Y')
                        date_formatted = trans_date.strftime('%b %Y')
                    except:
                        try:
                            # Try ISO format as fallback
                            if isinstance(date_str, dict):
                                date_str = date_str.get('@value', '')
                            trans_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            date_formatted = trans_date.strftime('%b %Y')
                        except:
                            date_formatted = date_str[:12] if len(date_str) > 12 else date_str

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

                # Extract property type from nested object
                prop_type_obj = item.get('propertyType', {})
                if isinstance(prop_type_obj, dict):
                    # Get the label from the nested structure
                    labels = prop_type_obj.get('prefLabel', []) or prop_type_obj.get('label', [])
                    if labels and isinstance(labels, list) and len(labels) > 0:
                        label = labels[0]
                        if isinstance(label, dict):
                            prop_type = label.get('_value', 'Unknown')
                        else:
                            prop_type = str(label)
                    else:
                        # Fall back to parsing the _about URL
                        about = prop_type_obj.get('_about', '')
                        prop_type = about.split('/')[-1].replace('-', ' ').title() if about else 'Unknown'
                else:
                    prop_type = self.PROPERTY_TYPES.get(prop_type_obj, str(prop_type_obj))

                # Clean up property type
                prop_type = prop_type.replace('-', ' ').title()

                # New build flag
                new_build = item.get('newBuild', False)
                if isinstance(new_build, str):
                    new_build = new_build.lower() == 'true'

                # Estate type from nested object
                estate_type_obj = item.get('estateType', {})
                if isinstance(estate_type_obj, dict):
                    labels = estate_type_obj.get('prefLabel', []) or estate_type_obj.get('label', [])
                    if labels and isinstance(labels, list) and len(labels) > 0:
                        label = labels[0]
                        if isinstance(label, dict):
                            estate_type = label.get('_value', 'Unknown')
                        else:
                            estate_type = str(label)
                    else:
                        estate_type = 'Unknown'
                else:
                    estate_type = str(estate_type_obj).title() if estate_type_obj else 'Unknown'

                transactions.append({
                    'price': price,
                    'date': trans_date.strftime('%Y-%m-%d') if trans_date else date_str,
                    'date_formatted': date_formatted,
                    'address': address,
                    'street': street,
                    'postcode': postcode,
                    'property_type': prop_type,
                    'new_build': new_build,
                    'estate_type': estate_type
                })

            except Exception as e:
                print(f"Error parsing transaction: {e}")
                continue

        return transactions

    def get_similar_sales(
        self,
        postcode: str = None,
        property_type: Optional[str] = None,
        years_back: int = 2,
        limit: int = 20,
        address: str = None,
        town: str = None
    ) -> Dict:
        """
        Get similar property sales with statistics.

        Tries multiple strategies:
        1. Full postcode lookup (REST API)
        2. Outcode lookup (SPARQL)
        3. Street + town lookup (SPARQL)

        Args:
            postcode: Full or partial postcode
            property_type: Filter by property type
            years_back: Years of history
            limit: Max results
            address: Full address for street extraction
            town: Town/city name

        Returns:
            Dict with 'sales' list, 'stats' summary, and 'search_method' used
        """
        all_sales = []
        search_method = 'none'

        # Strategy 1: Try full postcode first
        if postcode:
            all_sales = self.get_sold_prices_by_postcode(postcode, limit=100, years_back=years_back)
            if all_sales:
                search_method = 'postcode'

        # Strategy 2: Try outcode via SPARQL if no results
        if not all_sales and postcode:
            outcode = self._extract_outcode(postcode)
            if outcode and len(outcode) >= 2:
                all_sales = self.get_sold_prices_by_outcode(outcode, limit=100, years_back=years_back)
                if all_sales:
                    search_method = 'outcode'

        # Strategy 3: Try address-based search via SPARQL
        if not all_sales and address:
            all_sales = self.get_sold_prices_by_address(address, town=town, limit=100, years_back=years_back)
            if all_sales:
                search_method = 'address'

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
            'stats': stats,
            'search_method': search_method
        }


# Singleton instance
land_registry = LandRegistryService()


def get_sold_prices(postcode: str, years_back: int = 2, limit: int = 20) -> Dict:
    """Convenience function to get sold prices for a postcode."""
    return land_registry.get_similar_sales(postcode=postcode, years_back=years_back, limit=limit)


def get_similar_sales(
    postcode: str = None,
    property_type: str = None,
    years_back: int = 2,
    address: str = None,
    town: str = None
) -> Dict:
    """
    Get similar property sales with statistics.

    Args:
        postcode: Full or partial UK postcode
        property_type: Filter by property type
        years_back: Years of history
        address: Full address for street-based search
        town: Town/city for address-based search

    Returns:
        Dict with 'sales', 'stats', and 'search_method'
    """
    return land_registry.get_similar_sales(
        postcode=postcode,
        property_type=property_type,
        years_back=years_back,
        address=address,
        town=town
    )
