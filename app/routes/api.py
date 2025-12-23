"""API routes for the property dashboard."""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app.models import db, Property, SavedProperty
from app.services.calculator import BTLCalculator
from app.services.rental_analysis import get_rental_averages, get_estimated_rent

api_bp = Blueprint('api', __name__)


@api_bp.route('/properties')
def get_properties():
    """Get properties with optional filters."""
    # Get filter parameters
    bedrooms = request.args.get('bedrooms', type=int)
    bathrooms = request.args.get('bathrooms', type=int)
    area = request.args.get('area')
    property_type = request.args.get('property_type')
    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)
    is_rental = request.args.get('is_rental', 'false').lower() == 'true'
    sort_by = request.args.get('sort', 'date_desc')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)

    # Build query
    query = Property.query.filter_by(is_rental=is_rental)

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

    # Get total count before pagination
    total = query.count()

    # Apply sorting
    if sort_by == 'price_asc':
        query = query.order_by(Property.price.asc())
    elif sort_by == 'price_desc':
        query = query.order_by(Property.price.desc())
    elif sort_by == 'date_asc':
        query = query.order_by(Property.listing_date.asc())
    else:
        query = query.order_by(Property.listing_date.desc())

    # Apply pagination
    properties = query.offset(offset).limit(limit).all()

    # Add yield estimates
    result = []
    for prop in properties:
        prop_dict = prop.to_dict()
        estimated_rent = get_estimated_rent(prop.bedrooms, prop.search_location)
        if estimated_rent and prop.price:
            prop_dict['estimated_rent'] = round(estimated_rent, 2)
            prop_dict['gross_yield'] = round(
                BTLCalculator.calculate_quick_yield(prop.price, estimated_rent), 2
            )
        result.append(prop_dict)

    return jsonify({
        'total': total,
        'offset': offset,
        'limit': limit,
        'properties': result
    })


@api_bp.route('/properties/<int:property_id>')
def get_property(property_id):
    """Get a single property with BTL calculations."""
    prop = Property.query.get_or_404(property_id)
    prop_dict = prop.to_dict()

    # Add rental estimate and BTL calculations
    estimated_rent = get_estimated_rent(prop.bedrooms, prop.search_location)
    if estimated_rent:
        prop_dict['estimated_rent'] = round(estimated_rent, 2)

        # Get calculator parameters from query string
        deposit_percent = request.args.get('deposit', 25, type=float)
        interest_rate = request.args.get('interest', 5.5, type=float)
        mortgage_term = request.args.get('term', 25, type=int)

        calculator = BTLCalculator(
            deposit_percent=deposit_percent,
            interest_rate=interest_rate,
            mortgage_term_years=mortgage_term
        )

        btl_results = calculator.calculate(prop.price, estimated_rent)
        prop_dict['btl_calculations'] = btl_results.to_dict()

    return jsonify(prop_dict)


@api_bp.route('/rental-averages')
def get_rental_averages_api():
    """Get rental averages by bedroom count, optionally filtered by location."""
    location = request.args.get('location')
    averages = get_rental_averages(location=location)
    return jsonify(averages)


@api_bp.route('/calculate', methods=['POST'])
def calculate_btl():
    """Calculate BTL metrics for given parameters."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    purchase_price = data.get('purchase_price')
    monthly_rent = data.get('monthly_rent')
    deposit_percent = data.get('deposit_percent', 25)
    interest_rate = data.get('interest_rate', 5.5)
    mortgage_term = data.get('mortgage_term', 25)

    if not purchase_price:
        return jsonify({'error': 'purchase_price is required'}), 400

    # If rent not provided, try to estimate from bedrooms
    if not monthly_rent:
        bedrooms = data.get('bedrooms')
        if bedrooms:
            monthly_rent = get_estimated_rent(bedrooms)

    calculator = BTLCalculator(
        deposit_percent=deposit_percent,
        interest_rate=interest_rate,
        mortgage_term_years=mortgage_term
    )

    results = calculator.calculate(purchase_price, monthly_rent)

    return jsonify(results.to_dict())


@api_bp.route('/saved-properties', methods=['GET'])
@login_required
def get_saved_properties():
    """Get current user's saved properties."""
    saved = SavedProperty.query.filter_by(user_id=current_user.id).order_by(
        SavedProperty.created_at.desc()
    ).all()

    result = []
    for sp in saved:
        sp_dict = sp.to_dict()
        # Add BTL calculations
        if sp.property and sp.property.price:
            estimated_rent = get_estimated_rent(sp.property.bedrooms, sp.property.search_location)
            if estimated_rent:
                sp_dict['estimated_rent'] = round(estimated_rent, 2)
                sp_dict['gross_yield'] = round(
                    BTLCalculator.calculate_quick_yield(sp.property.price, estimated_rent), 2
                )
        result.append(sp_dict)

    return jsonify({'saved_properties': result})


@api_bp.route('/saved-properties', methods=['POST'])
@login_required
def create_saved_property():
    """Save a property for the current user."""
    data = request.get_json()

    if not data or 'property_id' not in data:
        return jsonify({'error': 'property_id is required'}), 400

    property_id = data['property_id']
    notes = data.get('notes')

    # Check property exists
    prop = Property.query.get(property_id)
    if not prop:
        return jsonify({'error': 'Property not found'}), 404

    # Check if already saved
    existing = SavedProperty.query.filter_by(
        user_id=current_user.id,
        property_id=property_id
    ).first()

    if existing:
        # Update notes
        existing.notes = notes
        db.session.commit()
        return jsonify(existing.to_dict())

    # Create new saved property
    saved = SavedProperty(
        user_id=current_user.id,
        property_id=property_id,
        notes=notes
    )
    db.session.add(saved)
    db.session.commit()

    return jsonify(saved.to_dict()), 201


@api_bp.route('/saved-properties/<int:saved_id>', methods=['DELETE'])
@login_required
def delete_saved_property(saved_id):
    """Remove a saved property."""
    saved = SavedProperty.query.filter_by(
        id=saved_id,
        user_id=current_user.id
    ).first()

    if not saved:
        return jsonify({'error': 'Saved property not found'}), 404

    db.session.delete(saved)
    db.session.commit()

    return jsonify({'message': 'Removed successfully'})


@api_bp.route('/areas')
def get_areas():
    """Get list of unique areas from properties."""
    areas = db.session.query(Property.area).filter(
        Property.area.isnot(None)
    ).distinct().order_by(Property.area).all()

    return jsonify({'areas': [a[0] for a in areas if a[0]]})


@api_bp.route('/stats')
def get_stats():
    """Get overall statistics."""
    sale_count = Property.query.filter_by(is_rental=False).count()
    rental_count = Property.query.filter_by(is_rental=True).count()

    # Price stats for sales
    from sqlalchemy import func
    sale_stats = db.session.query(
        func.avg(Property.price).label('avg'),
        func.min(Property.price).label('min'),
        func.max(Property.price).label('max')
    ).filter(
        Property.is_rental == False,
        Property.price.isnot(None)
    ).first()

    return jsonify({
        'sale_properties': sale_count,
        'rental_properties': rental_count,
        'sale_price_avg': round(sale_stats.avg, 2) if sale_stats.avg else None,
        'sale_price_min': sale_stats.min,
        'sale_price_max': sale_stats.max
    })


@api_bp.route('/map/properties')
def get_map_properties():
    """Get properties for map display with coordinates and yield data."""
    from sqlalchemy import func

    location = request.args.get('location')

    # Query properties with coordinates
    query = Property.query.filter(
        Property.is_rental == False,
        Property.latitude.isnot(None),
        Property.longitude.isnot(None)
    )

    if location:
        query = query.filter(Property.search_location == location)

    properties = query.all()

    result = []
    for prop in properties:
        prop_dict = {
            'id': prop.id,
            'address': prop.address,
            'price': prop.price,
            'bedrooms': prop.bedrooms,
            'bathrooms': prop.bathrooms,
            'property_type': prop.property_type,
            'latitude': prop.latitude,
            'longitude': prop.longitude,
            'search_location': prop.search_location,
            'area': prop.area
        }

        # Add yield estimate
        estimated_rent = get_estimated_rent(prop.bedrooms, prop.search_location)
        if estimated_rent and prop.price:
            prop_dict['estimated_rent'] = round(estimated_rent, 2)
            prop_dict['gross_yield'] = round(
                BTLCalculator.calculate_quick_yield(prop.price, estimated_rent), 2
            )
        else:
            prop_dict['estimated_rent'] = None
            prop_dict['gross_yield'] = None

        result.append(prop_dict)

    return jsonify({'properties': result})


@api_bp.route('/map/areas')
def get_map_areas():
    """Get aggregated stats per area for map display."""
    from sqlalchemy import func

    # Get stats per search_location
    results = db.session.query(
        Property.search_location,
        func.avg(Property.latitude).label('lat'),
        func.avg(Property.longitude).label('lng'),
        func.count(Property.id).label('property_count'),
        func.avg(Property.price).label('avg_price')
    ).filter(
        Property.is_rental == False,
        Property.latitude.isnot(None),
        Property.longitude.isnot(None),
        Property.search_location.isnot(None)
    ).group_by(Property.search_location).all()

    areas = {}
    for row in results:
        # Calculate average yield for this area
        avg_rent = get_estimated_rent(3, row.search_location)  # Use 3-bed as baseline
        avg_yield = 0
        if avg_rent and row.avg_price:
            avg_yield = (avg_rent * 12 / row.avg_price) * 100

        areas[row.search_location] = {
            'lat': row.lat,
            'lng': row.lng,
            'property_count': row.property_count,
            'avg_price': round(row.avg_price, 0) if row.avg_price else 0,
            'avg_rent': round(avg_rent, 0) if avg_rent else 0,
            'avg_yield': round(avg_yield, 2)
        }

    return jsonify(areas)


@api_bp.route('/map/geocode', methods=['POST'])
def geocode_properties():
    """Geocode properties that don't have coordinates."""
    from app.services.geocoding import geocode_all_properties

    # Geocode a batch of properties
    stats = geocode_all_properties(batch_size=20)

    return jsonify(stats)


@api_bp.route('/properties/<int:property_id>', methods=['DELETE'])
@login_required
def delete_property(property_id):
    """Delete a property from the database."""
    prop = Property.query.get_or_404(property_id)

    # Also delete any saved property references
    SavedProperty.query.filter_by(property_id=property_id).delete()

    db.session.delete(prop)
    db.session.commit()

    return jsonify({'message': 'Property deleted successfully', 'id': property_id})


@api_bp.route('/sold-prices/<postcode>')
@api_bp.route('/sold-prices/', defaults={'postcode': None})
def get_sold_prices(postcode):
    """
    Get sold property prices from Land Registry.

    Supports multiple search strategies:
    - By postcode (full or partial)
    - By address (street + town) if postcode not available

    Query params:
    - property_type: Filter by property type
    - years: Years of history (max 5)
    - limit: Max results (max 50)
    - address: Full address for street-based search
    - town: Town/city for address-based search
    """
    from app.services.land_registry import get_similar_sales

    # Get optional parameters
    property_type = request.args.get('property_type')
    years_back = request.args.get('years', 2, type=int)
    limit = request.args.get('limit', 20, type=int)
    address = request.args.get('address')
    town = request.args.get('town')

    # Cap limits for performance
    years_back = min(years_back, 5)
    limit = min(limit, 50)

    try:
        result = get_similar_sales(
            postcode=postcode,
            property_type=property_type,
            years_back=years_back,
            address=address,
            town=town
        )

        # Limit sales returned
        result['sales'] = result['sales'][:limit]

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'error': str(e),
            'sales': [],
            'stats': {'count': 0, 'avg_price': 0, 'min_price': 0, 'max_price': 0},
            'search_method': 'error'
        }), 500
