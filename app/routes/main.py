"""Main application routes."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import desc, asc

from app.models import db, Property, SavedProperty, RentalAverage
from app.services.calculator import BTLCalculator
from app.services.rental_analysis import get_estimated_rent, get_rental_averages, get_rental_stats

main_bp = Blueprint('main', __name__)


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
