# Oldham Property Investment Dashboard

A Flask-based property investment dashboard for finding buy-to-let opportunities in Oldham, Greater Manchester. This tool scrapes property listings from Rightmove and Zoopla, analyzes rental market data, and provides BTL (Buy-to-Let) investment calculations.

## Features

- **Property Scraping**: Automated scraping of properties for sale and rent from Rightmove and Zoopla
- **Rental Market Analysis**: Average rent calculations by bedroom count based on current listings
- **BTL Calculator**: Calculate mortgage payments, yields, cash flow, and ROI
- **Property Filtering**: Filter by bedrooms, bathrooms, area, property type, and price
- **User Accounts**: Save properties to your personal dashboard with notes
- **API Endpoints**: RESTful API for programmatic access

## Disclaimer

This tool is for **personal use only**. Web scraping may be against the terms of service of some websites. Please:
- Respect rate limits and robots.txt
- Use the data for personal investment research only
- Do not redistribute scraped data commercially

## Installation

### Prerequisites

- Python 3.9+
- pip

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd propertyscraper
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install chromium
```

5. Initialize the database:
```bash
flask init-db
```

## Running the Application

### Start the Web Server

```bash
python run.py
```

Or using Flask:
```bash
export FLASK_APP=run.py
export FLASK_ENV=development
flask run
```

The application will be available at http://localhost:5000

### Running the Scraper

The scraper respects a 24-hour cooldown between runs to avoid excessive requests.

**Scrape all sources (sale and rental):**
```bash
flask scrape-properties
```

**Force scrape (ignore cooldown):**
```bash
flask scrape-properties --force
```

**Scrape specific source:**
```bash
flask scrape-properties --source rightmove
flask scrape-properties --source zoopla
```

**Scrape specific type:**
```bash
flask scrape-properties --type sale
flask scrape-properties --type rent
```

### Update Rental Averages

After scraping rental data, update the cached averages:
```bash
flask update-rental-averages
```

## Project Structure

```
propertyscraper/
├── app/
│   ├── __init__.py          # App factory and CLI commands
│   ├── models.py             # Database models
│   ├── routes/
│   │   ├── main.py           # Main page routes
│   │   ├── auth.py           # Authentication routes
│   │   └── api.py            # API endpoints
│   ├── scraper/
│   │   ├── base.py           # Base scraper class
│   │   ├── rightmove.py      # Rightmove scraper
│   │   ├── zoopla.py         # Zoopla scraper
│   │   └── runner.py         # Scraper orchestration
│   ├── services/
│   │   ├── calculator.py     # BTL calculator
│   │   └── rental_analysis.py # Rental market analysis
│   └── templates/            # Jinja2 templates
├── instance/                  # SQLite database (auto-created)
├── config.py                  # Configuration
├── run.py                     # Application entry point
├── requirements.txt           # Python dependencies
└── README.md
```

## API Endpoints

### Properties

- `GET /api/properties` - List properties with filters
  - Query params: `bedrooms`, `bathrooms`, `area`, `property_type`, `min_price`, `max_price`, `is_rental`, `sort`, `limit`, `offset`

- `GET /api/properties/<id>` - Get property details with BTL calculations
  - Query params: `deposit`, `interest`, `term`

### Rental Data

- `GET /api/rental-averages` - Get rental averages by bedroom count

### Calculator

- `POST /api/calculate` - Calculate BTL metrics
  - Body: `{"purchase_price": 150000, "monthly_rent": 750, "deposit_percent": 25, "interest_rate": 5.5, "mortgage_term": 25}`

### Saved Properties (requires authentication)

- `GET /api/saved-properties` - Get user's saved properties
- `POST /api/saved-properties` - Save a property
- `DELETE /api/saved-properties/<id>` - Remove a saved property

### Utility

- `GET /api/areas` - Get list of available areas
- `GET /api/stats` - Get overall statistics

## Configuration

Configuration is in `config.py`. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `SCRAPE_COOLDOWN_HOURS` | 24 | Hours between scrape runs |
| `MAX_PROPERTIES_PER_SCRAPE` | 50 | Maximum properties per scrape session |
| `SCRAPE_DELAY_MIN` | 3 | Minimum seconds between requests |
| `SCRAPE_DELAY_MAX` | 7 | Maximum seconds between requests |
| `DEFAULT_DEPOSIT_PERCENT` | 25 | Default BTL deposit percentage |
| `DEFAULT_INTEREST_RATE` | 5.5 | Default BTL interest rate |
| `DEFAULT_MORTGAGE_TERM_YEARS` | 25 | Default mortgage term |

## BTL Calculator Formulas

**Monthly Mortgage Payment (Amortization):**
```
M = P × [r(1+r)^n] / [(1+r)^n - 1]
```
Where: P = principal, r = monthly interest rate, n = number of payments

**Gross Yield:**
```
(Annual Rent / Purchase Price) × 100
```

**Cash Flow:**
```
Monthly Rent - Monthly Mortgage Payment
```

**ROI on Deposit:**
```
(Annual Cash Flow / Deposit Amount) × 100
```

## Tech Stack

- **Backend**: Flask, SQLAlchemy, Flask-Login
- **Database**: SQLite
- **Scraping**: Playwright (headless Chromium)
- **Frontend**: Jinja2 templates, Tailwind CSS (CDN)

## License

For personal use only. Not for commercial distribution.
