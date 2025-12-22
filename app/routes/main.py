"""Main application routes."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from sqlalchemy import desc, asc
import threading
import csv
import io
from datetime import datetime

from app.models import db, Property, SavedProperty, RentalAverage, ScrapeLog
from app.services.calculator import BTLCalculator
from app.services.rental_analysis import get_estimated_rent, get_rental_averages, get_rental_stats

main_bp = Blueprint('main', __name__)

# Global scrape status tracking
scrape_status = {
    'running': False,
    'progress': 0,
    'stage': 'idle',
    'message': '',
    'source': '',
    'type': ''
}


@main_bp.route('/')
def index():
    """Home page - redirects to dashboard if logged in."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    # Show some stats for non-logged in users
    total_properties = Property.query.filter_by(is_rental=False).count()
    total_rentals = Property.query.filter_by(is_rental=True).count()

    return render_template('index.html',
                           total_properties=total_properties,
                           total_rentals=total_rentals)


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """User dashboard with saved properties."""
    saved = SavedProperty.query.filter_by(user_id=current_user.id).order_by(
        desc(SavedProperty.created_at)
    ).all()

    # Calculate stats
    total_saved = len(saved)
    yields = []
    cash_flows = []

    calculator = BTLCalculator()

    for sp in saved:
        if sp.property and sp.property.price:
            estimated_rent = get_estimated_rent(sp.property.bedrooms)
            if estimated_rent:
                result = calculator.calculate(sp.property.price, estimated_rent)
                if result.gross_yield_percent:
                    yields.append(result.gross_yield_percent)
                if result.monthly_cash_flow:
                    cash_flows.append(result.monthly_cash_flow)

    best_yield = max(yields) if yields else 0
    avg_cash_flow = sum(cash_flows) / len(cash_flows) if cash_flows else 0

    return render_template('dashboard.html',
                           saved_properties=saved,
                           total_saved=total_saved,
                           best_yield=best_yield,
                           avg_cash_flow=avg_cash_flow,
                           calculator=calculator,
                           get_estimated_rent=get_estimated_rent)


@main_bp.route('/properties')
def properties():
    """List all properties for sale with filters."""
    # Get filter parameters
    bedrooms = request.args.get('bedrooms', type=int)
    bathrooms = request.args.get('bathrooms', type=int)
    area = request.args.get('area')
    property_type = request.args.get('property_type')
    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)
    sort_by = request.args.get('sort', 'date_desc')

    # Base query - only sale properties
    query = Property.query.filter_by(is_rental=False)

    # Apply filters
    if bedrooms:
        if bedrooms >= 5:
            query = query.filter(Property.bedrooms >= 5)
        else:
            query = query.filter(Property.bedrooms == bedrooms)

    if bathrooms:
        if bathrooms >= 3:
            query = query.filter(Property.bathrooms >= 3)
        else:
            query = query.filter(Property.bathrooms == bathrooms)

    if area:
        query = query.filter(Property.area == area)

    if property_type:
        query = query.filter(Property.property_type == property_type)

    if min_price:
        query = query.filter(Property.price >= min_price)

    if max_price:
        query = query.filter(Property.price <= max_price)

    # Apply sorting
    if sort_by == 'price_asc':
        query = query.order_by(asc(Property.price))
    elif sort_by == 'price_desc':
        query = query.order_by(desc(Property.price))
    elif sort_by == 'date_asc':
        query = query.order_by(asc(Property.listing_date))
    else:  # date_desc (default)
        query = query.order_by(desc(Property.listing_date))

    properties_list = query.all()

    # Get unique areas and property types for filter dropdowns
    areas = db.session.query(Property.area).filter(
        Property.is_rental == False,
        Property.area.isnot(None)
    ).distinct().order_by(Property.area).all()
    areas = [a[0] for a in areas if a[0]]

    prop_types = db.session.query(Property.property_type).filter(
        Property.is_rental == False,
        Property.property_type.isnot(None)
    ).distinct().order_by(Property.property_type).all()
    prop_types = [p[0] for p in prop_types if p[0]]

    # Get saved property IDs for current user
    saved_ids = []
    if current_user.is_authenticated:
        saved = SavedProperty.query.filter_by(user_id=current_user.id).all()
        saved_ids = [s.property_id for s in saved]

    # Create calculator for yield estimates
    calculator = BTLCalculator()

    return render_template('properties.html',
                           properties=properties_list,
                           areas=areas,
                           property_types=prop_types,
                           saved_ids=saved_ids,
                           calculator=calculator,
                           get_estimated_rent=get_estimated_rent,
                           filters={
                               'bedrooms': bedrooms,
                               'bathrooms': bathrooms,
                               'area': area,
                               'property_type': property_type,
                               'min_price': min_price,
                               'max_price': max_price,
                               'sort': sort_by
                           })


@main_bp.route('/properties/<int:property_id>')
def property_detail(property_id):
    """Property detail page."""
    prop = Property.query.get_or_404(property_id)

    # Check if saved by current user
    is_saved = False
    saved_notes = None
    if current_user.is_authenticated:
        saved = SavedProperty.query.filter_by(
            user_id=current_user.id,
            property_id=property_id
        ).first()
        if saved:
            is_saved = True
            saved_notes = saved.notes

    # Get rental average for this bedroom count
    estimated_rent = get_estimated_rent(prop.bedrooms)
    rental_avg = None
    if prop.bedrooms:
        rental_avg = RentalAverage.query.filter_by(bedrooms=prop.bedrooms).first()

    # Calculate BTL metrics with default values
    calculator = BTLCalculator()
    btl_results = None
    if prop.price and estimated_rent:
        btl_results = calculator.calculate(prop.price, estimated_rent)

    return render_template('property_detail.html',
                           property=prop,
                           is_saved=is_saved,
                           saved_notes=saved_notes,
                           estimated_rent=estimated_rent,
                           rental_avg=rental_avg,
                           btl_results=btl_results,
                           calculator=calculator)


@main_bp.route('/rentals')
def rentals():
    """Rental market overview page."""
    rental_averages = get_rental_averages()
    rental_stats = get_rental_stats()

    # Get rental listings
    rentals_list = Property.query.filter_by(is_rental=True).order_by(
        desc(Property.listing_date)
    ).limit(50).all()

    return render_template('rentals.html',
                           rental_averages=rental_averages,
                           rental_stats=rental_stats,
                           rentals=rentals_list)


@main_bp.route('/calculator')
def calculator_page():
    """Standalone BTL calculator page."""
    # Get rental averages for reference
    rental_averages = get_rental_averages()

    return render_template('calculator.html',
                           rental_averages=rental_averages)


@main_bp.route('/save-property/<int:property_id>', methods=['POST'])
@login_required
def save_property(property_id):
    """Save a property to user's dashboard."""
    prop = Property.query.get_or_404(property_id)

    # Check if already saved
    existing = SavedProperty.query.filter_by(
        user_id=current_user.id,
        property_id=property_id
    ).first()

    if existing:
        # Update notes if provided
        notes = request.form.get('notes')
        if notes is not None:
            existing.notes = notes
            db.session.commit()
            flash('Notes updated.', 'success')
    else:
        saved = SavedProperty(
            user_id=current_user.id,
            property_id=property_id,
            notes=request.form.get('notes')
        )
        db.session.add(saved)
        db.session.commit()
        flash('Property saved to your dashboard.', 'success')

    return redirect(request.referrer or url_for('main.property_detail', property_id=property_id))


@main_bp.route('/unsave-property/<int:property_id>', methods=['POST'])
@login_required
def unsave_property(property_id):
    """Remove a property from user's saved list."""
    saved = SavedProperty.query.filter_by(
        user_id=current_user.id,
        property_id=property_id
    ).first()

    if saved:
        db.session.delete(saved)
        db.session.commit()
        flash('Property removed from your dashboard.', 'success')

    return redirect(request.referrer or url_for('main.dashboard'))


@main_bp.route('/admin/scraper')
@login_required
def scraper_admin():
    """Scraper administration page."""
    # Get recent scrape logs
    recent_logs = ScrapeLog.query.order_by(desc(ScrapeLog.started_at)).limit(20).all()

    # Get stats
    total_properties = Property.query.filter_by(is_rental=False).count()
    total_rentals = Property.query.filter_by(is_rental=True).count()

    return render_template('admin/scraper.html',
                           recent_logs=recent_logs,
                           total_properties=total_properties,
                           total_rentals=total_rentals,
                           scrape_status=scrape_status)


@main_bp.route('/admin/scraper/start', methods=['POST'])
@login_required
def start_scraper():
    """Start the scraper via web interface."""
    global scrape_status

    if scrape_status['running']:
        return jsonify({'error': 'Scraper is already running'}), 400

    source = request.form.get('source', 'all')
    scrape_type = request.form.get('type', 'all')

    # Update status
    scrape_status['running'] = True
    scrape_status['progress'] = 0
    scrape_status['stage'] = 'starting'
    scrape_status['message'] = 'Initializing scraper...'
    scrape_status['source'] = source
    scrape_status['type'] = scrape_type

    # Run scraper in background thread
    from flask import current_app
    app = current_app._get_current_object()

    def run_scraper_thread():
        global scrape_status
        with app.app_context():
            try:
                from app.scraper.runner import run_scraper
                run_scraper(force=True, source=source, scrape_type=scrape_type)
                scrape_status['stage'] = 'completed'
                scrape_status['message'] = 'Scraping completed successfully'
                scrape_status['progress'] = 100
            except Exception as e:
                scrape_status['stage'] = 'error'
                scrape_status['message'] = f'Error: {str(e)}'
            finally:
                scrape_status['running'] = False

    thread = threading.Thread(target=run_scraper_thread)
    thread.daemon = True
    thread.start()

    flash(f'Scraper started for {source} ({scrape_type})', 'success')
    return redirect(url_for('main.scraper_admin'))


@main_bp.route('/admin/scraper/status')
@login_required
def scraper_status():
    """Get current scraper status (for AJAX polling)."""
    return jsonify(scrape_status)


@main_bp.route('/properties/export')
def export_properties():
    """Export all properties to CSV with investment calculations."""
    # Get parameters from query string
    mortgage_type = request.args.get('mortgage_type', 'interest_only')
    term = request.args.get('term', 25, type=int)
    appreciation = request.args.get('appreciation', 4.0, type=float)
    deposit_percent = request.args.get('deposit', 25.0, type=float)
    interest_rate = request.args.get('rate', 5.5, type=float)

    # Get all sale properties
    properties_list = Property.query.filter_by(is_rental=False).order_by(desc(Property.listing_date)).all()

    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        'ID', 'Address', 'Area', 'Price', 'Bedrooms', 'Bathrooms', 'Property Type',
        'Source', 'URL', 'Listed Date',
        'Est. Monthly Rent', 'Gross Yield %',
        'Deposit Amount', 'Loan Amount', 'Monthly Mortgage',
        'Monthly Cash Flow', 'Annual Cash Flow',
        'Future Property Value', 'Net Property Equity', 'Total Rental Profit',
        'Total Wealth Built', 'Total Profit', 'ROI on Deposit %'
    ])

    # Calculate metrics for each property
    for prop in properties_list:
        estimated_rent = get_estimated_rent(prop.bedrooms) or 0
        price = prop.price or 0

        # Calculate investment metrics
        deposit_amount = price * (deposit_percent / 100)
        loan_amount = price - deposit_amount
        monthly_rate = (interest_rate / 100) / 12
        num_payments = term * 12

        # Calculate mortgage payment
        if mortgage_type == 'interest_only':
            monthly_mortgage = loan_amount * monthly_rate
            remaining_loan = loan_amount
        else:
            if monthly_rate > 0:
                monthly_mortgage = loan_amount * (monthly_rate * ((1 + monthly_rate) ** num_payments)) / \
                                   (((1 + monthly_rate) ** num_payments) - 1)
            else:
                monthly_mortgage = loan_amount / num_payments
            remaining_loan = 0

        # Cash flow
        monthly_cash_flow = estimated_rent - monthly_mortgage if estimated_rent else 0
        annual_cash_flow = monthly_cash_flow * 12

        # Gross yield
        gross_yield = (estimated_rent * 12 / price * 100) if price and estimated_rent else 0

        # Future value and wealth
        future_value = price * ((1 + appreciation / 100) ** term) if price else 0
        net_equity = future_value - remaining_loan
        total_rental_profit = annual_cash_flow * term
        total_wealth = net_equity + total_rental_profit
        total_profit = total_wealth - deposit_amount
        roi_percent = (total_profit / deposit_amount * 100) if deposit_amount else 0

        writer.writerow([
            prop.id,
            prop.address,
            prop.area or '',
            price,
            prop.bedrooms or '',
            prop.bathrooms or '',
            prop.property_type or '',
            prop.source,
            prop.url,
            prop.listing_date.strftime('%Y-%m-%d') if prop.listing_date else '',
            round(estimated_rent, 0) if estimated_rent else '',
            round(gross_yield, 2) if gross_yield else '',
            round(deposit_amount, 0),
            round(loan_amount, 0),
            round(monthly_mortgage, 0),
            round(monthly_cash_flow, 0) if estimated_rent else '',
            round(annual_cash_flow, 0) if estimated_rent else '',
            round(future_value, 0),
            round(net_equity, 0),
            round(total_rental_profit, 0) if estimated_rent else '',
            round(total_wealth, 0),
            round(total_profit, 0),
            round(roi_percent, 1)
        ])

    # Create response
    output.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'properties_export_{timestamp}.csv'

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
