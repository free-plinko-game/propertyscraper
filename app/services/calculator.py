"""Buy-to-Let Calculator service."""
from dataclasses import dataclass
from typing import Optional

from flask import current_app


@dataclass
class BTLResults:
    """Results from BTL calculation."""
    purchase_price: int
    deposit_percent: float
    deposit_amount: float
    loan_amount: float
    interest_rate: float
    mortgage_term_years: int
    monthly_mortgage_payment: float
    estimated_monthly_rent: Optional[float]
    monthly_cash_flow: Optional[float]
    annual_cash_flow: Optional[float]
    gross_yield_percent: Optional[float]
    net_yield_percent: Optional[float]
    roi_on_deposit_percent: Optional[float]

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'purchase_price': self.purchase_price,
            'deposit_percent': round(self.deposit_percent, 1),
            'deposit_amount': round(self.deposit_amount, 2),
            'loan_amount': round(self.loan_amount, 2),
            'interest_rate': round(self.interest_rate, 2),
            'mortgage_term_years': self.mortgage_term_years,
            'monthly_mortgage_payment': round(self.monthly_mortgage_payment, 2),
            'estimated_monthly_rent': round(self.estimated_monthly_rent, 2) if self.estimated_monthly_rent else None,
            'monthly_cash_flow': round(self.monthly_cash_flow, 2) if self.monthly_cash_flow else None,
            'annual_cash_flow': round(self.annual_cash_flow, 2) if self.annual_cash_flow else None,
            'gross_yield_percent': round(self.gross_yield_percent, 2) if self.gross_yield_percent else None,
            'net_yield_percent': round(self.net_yield_percent, 2) if self.net_yield_percent else None,
            'roi_on_deposit_percent': round(self.roi_on_deposit_percent, 2) if self.roi_on_deposit_percent else None,
        }


class BTLCalculator:
    """Buy-to-Let mortgage and yield calculator."""

    def __init__(self,
                 deposit_percent: Optional[float] = None,
                 interest_rate: Optional[float] = None,
                 mortgage_term_years: Optional[int] = None):
        """
        Initialize calculator with loan parameters.

        Args:
            deposit_percent: Deposit as percentage of purchase price (default 25%)
            interest_rate: Annual interest rate as percentage (default 5.5%)
            mortgage_term_years: Mortgage term in years (default 25)
        """
        self.deposit_percent = deposit_percent or current_app.config.get('DEFAULT_DEPOSIT_PERCENT', 25)
        self.interest_rate = interest_rate or current_app.config.get('DEFAULT_INTEREST_RATE', 5.5)
        self.mortgage_term_years = mortgage_term_years or current_app.config.get('DEFAULT_MORTGAGE_TERM_YEARS', 25)

    def calculate_monthly_payment(self, loan_amount: float) -> float:
        """
        Calculate monthly mortgage payment using standard amortization formula.

        Formula: M = P * [r(1+r)^n] / [(1+r)^n - 1]
        Where:
            M = monthly payment
            P = principal (loan amount)
            r = monthly interest rate
            n = total number of payments
        """
        if loan_amount <= 0:
            return 0.0

        # Convert annual rate to monthly
        monthly_rate = (self.interest_rate / 100) / 12

        # Total number of payments
        num_payments = self.mortgage_term_years * 12

        if monthly_rate == 0:
            return loan_amount / num_payments

        # Amortization formula
        payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** num_payments) / \
                  ((1 + monthly_rate) ** num_payments - 1)

        return payment

    def calculate(self, purchase_price: int, estimated_monthly_rent: Optional[float] = None) -> BTLResults:
        """
        Calculate all BTL metrics for a property.

        Args:
            purchase_price: Property purchase price in GBP
            estimated_monthly_rent: Expected monthly rental income

        Returns:
            BTLResults with all calculated metrics
        """
        # Calculate deposit and loan amounts
        deposit_amount = purchase_price * (self.deposit_percent / 100)
        loan_amount = purchase_price - deposit_amount

        # Calculate monthly mortgage payment
        monthly_mortgage = self.calculate_monthly_payment(loan_amount)

        # Initialize optional calculations
        monthly_cash_flow = None
        annual_cash_flow = None
        gross_yield = None
        net_yield = None
        roi_on_deposit = None

        if estimated_monthly_rent and estimated_monthly_rent > 0:
            # Monthly cash flow (rent - mortgage)
            monthly_cash_flow = estimated_monthly_rent - monthly_mortgage

            # Annual cash flow
            annual_cash_flow = monthly_cash_flow * 12

            # Gross yield % = (annual rent / purchase price) × 100
            annual_rent = estimated_monthly_rent * 12
            gross_yield = (annual_rent / purchase_price) * 100

            # Net yield (accounting for mortgage)
            if annual_cash_flow > 0:
                net_yield = (annual_cash_flow / purchase_price) * 100
            else:
                net_yield = (annual_cash_flow / purchase_price) * 100  # Will be negative

            # ROI on deposit = (annual profit / deposit) × 100
            if deposit_amount > 0:
                roi_on_deposit = (annual_cash_flow / deposit_amount) * 100

        return BTLResults(
            purchase_price=purchase_price,
            deposit_percent=self.deposit_percent,
            deposit_amount=deposit_amount,
            loan_amount=loan_amount,
            interest_rate=self.interest_rate,
            mortgage_term_years=self.mortgage_term_years,
            monthly_mortgage_payment=monthly_mortgage,
            estimated_monthly_rent=estimated_monthly_rent,
            monthly_cash_flow=monthly_cash_flow,
            annual_cash_flow=annual_cash_flow,
            gross_yield_percent=gross_yield,
            net_yield_percent=net_yield,
            roi_on_deposit_percent=roi_on_deposit
        )

    @staticmethod
    def calculate_quick_yield(purchase_price: int, monthly_rent: float) -> float:
        """
        Quick calculation of gross yield percentage.

        Args:
            purchase_price: Property purchase price
            monthly_rent: Monthly rental income

        Returns:
            Gross yield as percentage
        """
        if purchase_price <= 0:
            return 0.0
        annual_rent = monthly_rent * 12
        return (annual_rent / purchase_price) * 100
