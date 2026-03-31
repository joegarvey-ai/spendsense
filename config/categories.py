"""Transaction categorization rules.

Each rule is a dict with:
    pattern  — regex matched against the transaction description (case-insensitive)
    tier1    — top-level category (Transfer, Income, Fixed, Essential, Non-Essential,
               Discretionary, Allocation)
    tier2    — sub-category (e.g. Groceries, Dining Out, Subscriptions)
    vendor   — friendly vendor name (or None for catch-all rules)

Rules are evaluated top-to-bottom; first match wins.

IMPORTANT — CUSTOMIZATION REQUIRED:
    The rules below are GENERALIZED EXAMPLES using common national-chain merchants.
    You MUST customize this file for your own financial institutions, local merchants,
    and spending patterns after your first SimpleFIN sync. Look at uncategorized
    transactions (`python -m src.cli uncategorized`) and add rules to match them.

HOW TO CUSTOMIZE:
    1. Add your own merchants below — follow the examples in each section.
    2. Use regex alternation (|) to match multiple transaction description variants.
    3. Put specific rules BEFORE general catch-alls (e.g. payroll before purchases).
    4. Re-run `python -m src.cli recategorize` after editing to re-classify all transactions.
"""

# ─── Double-Count Prevention: CC & Investment Company Patterns ───
# When a BANK account (checking/savings) has a transaction whose description matches
# one of these patterns AND the amount is negative (outgoing), the categorizer will
# automatically classify it as Transfer/CC Payment — even if no specific rule in RULES
# matches. This prevents the same money movement from being counted as both a CC payment
# debit AND the individual purchases on the card.
#
# The credit-card side (payment received) is typically handled by existing RULES patterns
# like "MOBILE PAYMENT.*THANK YOU" or "ACH Deposit.*Internet transfer from account ending".
#
# CUSTOMIZE: Add patterns for YOUR credit card companies. These are case-insensitive.
# Each entry needs a regex "pattern" and a "vendor" display name.
CC_COMPANY_PATTERNS = [
    # Capital One variants
    {"pattern": r"capital\s*one|cap\s*one|capitalone|capital\s+one\s+n\.?a\.?",
     "vendor": "Capital One"},
    # American Express variants
    {"pattern": r"\bamex\b|american\s*express|americanexpress",
     "vendor": "AMEX"},
    # Apple Card / Goldman Sachs variants
    {"pattern": r"apple\s*card|apple\s*goldman|applecard\s*gsbank",
     "vendor": "Apple Card"},
    # Bank of America variants
    {"pattern": r"bank\s+of\s+america|bk\s+of\s+amer|b\s*of\s*a\b|bofa\b",
     "vendor": "Bank of America"},
    # Affirm BNPL payment (not affirm.com charges, which are the installment itself)
    {"pattern": r"\baffirm\b(?!\.com)", "vendor": "Affirm"},
    # Add your credit card companies here:
    # {"pattern": r"chase|jpmorgan", "vendor": "Chase"},
    # {"pattern": r"discover", "vendor": "Discover"},
    # {"pattern": r"citi\b|citibank", "vendor": "Citi"},
    # {"pattern": r"wells\s*fargo", "vendor": "Wells Fargo"},
    # {"pattern": r"usaa", "vendor": "USAA"},
]

# When a BANK account has a transaction matching these patterns, it's categorized as
# Transfer/Investment Transfer instead of Allocation/Investments. This prevents
# double-counting when you also pull transactions from the brokerage itself (where
# the deposit appears as Allocation/Investments).
#
# CUSTOMIZE: Add patterns for YOUR brokerage(s).
INVESTMENT_COMPANY_PATTERNS = [
    {"pattern": r"\brobinhood\b", "vendor": "Robinhood"},
    # Add your brokerages here:
    # {"pattern": r"\bschwab\b|charles\s*schwab", "vendor": "Schwab"},
    # {"pattern": r"\bfidelity\b", "vendor": "Fidelity"},
    # {"pattern": r"\bvanguard\b", "vendor": "Vanguard"},
    # {"pattern": r"\betrade\b|e\*trade", "vendor": "E*TRADE"},
    # {"pattern": r"\bwealthfront\b", "vendor": "Wealthfront"},
    # {"pattern": r"\bbetterment\b", "vendor": "Betterment"},
]

RULES = [
    # ─── Credit Card Payments & Internal Transfers (exclude from spending) ───
    # These prevent double-counting: the CC payment from checking + the charges on the card.
    # CUSTOMIZE: Add patterns that match YOUR credit card payment descriptions.
    # Run `python -m src.cli uncategorized` to see your actual transaction descriptions.
    {"pattern": r"MOBILE PAYMENT.*THANK YOU", "tier1": "Transfer", "tier2": "CC Payment", "vendor": None},
    {"pattern": r"ACH Deposit.*Internet transfer from account ending", "tier1": "Transfer", "tier2": "CC Payment", "vendor": None},
    # Add your credit card payment patterns here (check your bank's transaction descriptions):
    # {"pattern": r"External Withdrawal.*YOUR_CC_COMPANY.*PAYMENT", "tier1": "Transfer", "tier2": "CC Payment", "vendor": "Your Card"},
    # {"pattern": r"YOUR_CARD_PAYMENT_PATTERN", "tier1": "Transfer", "tier2": "CC Payment", "vendor": "Your Card"},
    # Add your credit union / bank loan payment patterns here:
    # {"pattern": r"External Withdrawal.*YOUR_CREDIT_UNION", "tier1": "Transfer", "tier2": "Loan Payment", "vendor": "Your CU"},
    {"pattern": r"Online Banking Transfer|Deposit.*Transfer from XXXXXX|Withdrawal.*Transfer To XXXXXX", "tier1": "Transfer", "tier2": "Internal Transfer", "vendor": None},
    {"pattern": r"IN FLIGHT PURCHASE REBATE", "tier1": "Transfer", "tier2": "Credit/Rebate", "vendor": None},
    # Add your card statement credits / perks:
    # {"pattern": r"YOUR_CARD.*CREDIT", "tier1": "Transfer", "tier2": "Card Credit", "vendor": "Your Card"},

    # ─── Income (MUST come before spending rules for the same vendor) ───
    # IMPORTANT: If your employer also appears as a spending vendor (e.g. Amazon, Walmart),
    # put the payroll rule FIRST so deposits aren't categorized as purchases.
    # {"pattern": r"YOUR_EMPLOYER.*PAYROLL|External Deposit.*YOUR_EMPLOYER.*PAYMENTS", "tier1": "Income", "tier2": "Payroll", "vendor": "Your Employer"},
    {"pattern": r"PAYROLL|DIRECT DEPOSIT|DIR DEP", "tier1": "Income", "tier2": "Payroll", "vendor": None},
    {"pattern": r"External Deposit.*eBay Com|eBay Com.*PAYMENTS", "tier1": "Income", "tier2": "eBay Sales", "vendor": "eBay"},
    {"pattern": r"TURBOTAX.*IRS|IRS.*Refund", "tier1": "Income", "tier2": "Tax Refund", "vendor": "IRS"},
    {"pattern": r"External Deposit.*AIRBNB|AIRBNB.*INSTANT TRANSFER", "tier1": "Income", "tier2": "Airbnb", "vendor": "Airbnb"},
    {"pattern": r"AIRBNB \* HM|AIRBNB.*STAY", "tier1": "Non-Essential", "tier2": "Travel", "vendor": "Airbnb"},
    {"pattern": r"External Deposit.*VENMO.*CASHOUT|VENMO.*CASHOUT", "tier1": "Income", "tier2": "Venmo", "vendor": "Venmo"},
    {"pattern": r"Dividend/Interest", "tier1": "Allocation", "tier2": "Interest", "vendor": None},

    # ─── Investment Activity ───
    # Bank-side outgoing transfer = Transfer (not Allocation) to avoid double-counting.
    # CUSTOMIZE: Replace with your brokerage's transaction description patterns.
    # {"pattern": r"External Withdrawal.*YOUR_BROKERAGE", "tier1": "Transfer", "tier2": "Investment Transfer", "vendor": "Your Brokerage"},
    {"pattern": r"buy \d+\.\d+ shares", "tier1": "Allocation", "tier2": "Investments", "vendor": None},
    {"pattern": r"sell \d+\.\d+ shares", "tier1": "Allocation", "tier2": "Investments", "vendor": None},
    {"pattern": r"Cash dividend of", "tier1": "Allocation", "tier2": "Dividends", "vendor": None},
    {"pattern": r"Interest earned of", "tier1": "Allocation", "tier2": "Interest", "vendor": None},
    # Add your brokerage patterns:
    # {"pattern": r"SCHWAB|FIDELITY|VANGUARD|ROBINHOOD|ETRADE", "tier1": "Allocation", "tier2": "Investments", "vendor": None},

    # ─── Fixed expenses ───
    # Mortgage / rent:
    # {"pattern": r"YOUR_LENDER.*MORTGAGE|YOUR_LENDER.*HOME LOAN", "tier1": "Fixed", "tier2": "Mortgage", "vendor": "Your Lender"},
    # {"pattern": r"LANDLORD|RENT PAYMENT", "tier1": "Fixed", "tier2": "Rent", "vendor": None},
    # Insurance:
    # {"pattern": r"YOUR_INSURANCE_CO", "tier1": "Fixed", "tier2": "Life Insurance", "vendor": "Your Insurer"},
    # BNPL / installment payments:
    # {"pattern": r"AFFIRM|KLARNA|AFTERPAY", "tier1": "Fixed", "tier2": "Installment Payment", "vendor": None},
    # Phone installment:
    # {"pattern": r"YOUR_PHONE_FINANCING", "tier1": "Fixed", "tier2": "Phone Payment", "vendor": None},
    {"pattern": r"ANTHROPIC|CLAUDE", "tier1": "Fixed", "tier2": "AI Tools", "vendor": "Anthropic"},
    {"pattern": r"ADOBE|PHOTOSHOP|LIGHTROOM", "tier1": "Fixed", "tier2": "Software", "vendor": "Adobe"},
    {"pattern": r"LA FITNESS|PLANET FITNESS|ANYTIME FITNESS", "tier1": "Fixed", "tier2": "Gym", "vendor": None},
    {"pattern": r"XFINITY|COMCAST|SPECTRUM|AT&T.*INTERNET", "tier1": "Fixed", "tier2": "Internet", "vendor": None},
    {"pattern": r"NAME.CHEAP|NAMECHEAP|GODADDY|SQUARESPACE", "tier1": "Fixed", "tier2": "Web Hosting", "vendor": None},
    {"pattern": r"RENEWAL MEMBERSHIP FEE|ANNUAL FEE", "tier1": "Fixed", "tier2": "Annual Fees", "vendor": None},
    {"pattern": r"CLEAR \*CLEARME", "tier1": "Fixed", "tier2": "Clear Plus", "vendor": "Clear"},
    {"pattern": r"T-MOBILE|VERIZON|AT&T WIRELESS", "tier1": "Fixed", "tier2": "Cell Phone", "vendor": None},

    # ─── Essential ───
    # Groceries — add your local grocery stores:
    {"pattern": r"KROGER|FRED[\s\-]M|FREDMEYER|PUBLIX|HEB|MEIJER", "tier1": "Essential", "tier2": "Groceries", "vendor": None},
    {"pattern": r"COSTCO(?!.*GAS)(?!.*FUEL)", "tier1": "Essential", "tier2": "Groceries", "vendor": "Costco"},
    {"pattern": r"COSTCO.*GAS|COSTCO.*FUEL", "tier1": "Essential", "tier2": "Auto — Fuel", "vendor": "Costco Gas"},
    {"pattern": r"SAFEWAY|ALBERTSONS", "tier1": "Essential", "tier2": "Groceries", "vendor": None},
    {"pattern": r"TRADER JOE", "tier1": "Essential", "tier2": "Groceries", "vendor": "Trader Joe's"},
    {"pattern": r"WHOLEFDS|WHOLE FOODS", "tier1": "Essential", "tier2": "Groceries", "vendor": "Whole Foods"},
    {"pattern": r"CVS|WALGREEN", "tier1": "Essential", "tier2": "Pharmacy/Groceries", "vendor": None},
    {"pattern": r"TARGET", "tier1": "Essential", "tier2": "Groceries", "vendor": "Target"},
    {"pattern": r"WALMART|WAL-MART", "tier1": "Essential", "tier2": "Groceries", "vendor": "Walmart"},
    {"pattern": r"ALDI", "tier1": "Essential", "tier2": "Groceries", "vendor": "Aldi"},
    # Add your local butcher, bakery, farmers market, etc.:
    # {"pattern": r"LOCAL BUTCHER NAME", "tier1": "Essential", "tier2": "Groceries", "vendor": "Your Butcher"},

    # Fuel:
    {"pattern": r"SHELL|CHEVRON|ARCO|76\s|EXXON|MOBIL.*GAS|BP\s", "tier1": "Essential", "tier2": "Auto — Fuel", "vendor": None},
    # Auto maintenance — add your local shops:
    # {"pattern": r"YOUR MECHANIC|YOUR AUTO SHOP", "tier1": "Essential", "tier2": "Auto — Maintenance", "vendor": "Your Shop"},

    # Donations — add your organization patterns:
    # {"pattern": r"YOUR CHURCH|YOUR CHARITY", "tier1": "Essential", "tier2": "Donations", "vendor": "Your Org"},
    {"pattern": r"CHARITABLE|DONATION|GIVING", "tier1": "Essential", "tier2": "Donations", "vendor": None},

    # Utilities — add your local utility providers:
    # {"pattern": r"YOUR_ELECTRIC_COMPANY|YOUR_WATER_UTILITY", "tier1": "Essential", "tier2": "Utilities", "vendor": None},
    {"pattern": r"ELECTRIC|WATER.*UTIL|GAS.*UTIL|SEWER", "tier1": "Essential", "tier2": "Utilities", "vendor": None},
    {"pattern": r"USPS|UNITED STATES POSTAL|THE UPS STORE|UPS STORE", "tier1": "Essential", "tier2": "Shipping", "vendor": None},
    {"pattern": r"ATM Withdrawal", "tier1": "Essential", "tier2": "Cash", "vendor": None},
    {"pattern": r"DEPT OF REVENUE|STATE TAX", "tier1": "Essential", "tier2": "Taxes", "vendor": None},
    # Pet care — add your vet, groomer, etc.:
    # {"pattern": r"YOUR VET NAME", "tier1": "Essential", "tier2": "Pet — Vet", "vendor": "Your Vet"},
    {"pattern": r"ROVER\.COM", "tier1": "Essential", "tier2": "Pet — Care", "vendor": "Rover"},
    {"pattern": r"PETCO|PETSMART", "tier1": "Essential", "tier2": "Pet — Supplies", "vendor": None},

    # ─── Non-Essential: Dining Out ───
    {"pattern": r"DOORDASH", "tier1": "Non-Essential", "tier2": "Food Delivery", "vendor": "DoorDash"},
    {"pattern": r"UBER.*EAT|UBEREATS", "tier1": "Non-Essential", "tier2": "Food Delivery", "vendor": "Uber Eats"},
    {"pattern": r"GRUBHUB", "tier1": "Non-Essential", "tier2": "Food Delivery", "vendor": "GrubHub"},
    {"pattern": r"DOMINOS|DOMINO.S", "tier1": "Non-Essential", "tier2": "Food Delivery", "vendor": "Domino's"},
    {"pattern": r"STARBUCKS|SBUX", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Starbucks"},
    {"pattern": r"PANDA EXPRESS", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Panda Express"},
    {"pattern": r"WENDYS|WENDY.S", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Wendy's"},
    {"pattern": r"MCDONALD.S|MCDONALDS", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "McDonald's"},
    {"pattern": r"DAIRY QUEEN", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Dairy Queen"},
    {"pattern": r"CHIPOTLE", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Chipotle"},
    {"pattern": r"CHICK-FIL-A|CHICKFILA", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Chick-fil-A"},
    {"pattern": r"SHAKE SHACK", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Shake Shack"},
    {"pattern": r"CRUMBL", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Crumbl Cookies"},
    {"pattern": r"CHEESECAKE", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Cheesecake Factory"},
    {"pattern": r"APPLEBEES|APPLEBEE.S", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Applebee's"},
    {"pattern": r"SWEETGREEN", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Sweetgreen"},
    {"pattern": r"NORTH ITALIA", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "North Italia"},
    # Add your favorite local restaurants:
    # {"pattern": r"LOCAL RESTAURANT NAME", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": "Your Spot"},
    # Toast POS catch-all (many restaurants use this):
    {"pattern": r"TST\*", "tier1": "Non-Essential", "tier2": "Dining Out", "vendor": None},

    # ─── Non-Essential: Shopping & Services ───
    {"pattern": r"AMAZON\.COM|AMZN|AMAZON MKTP|AMAZON MARK", "tier1": "Non-Essential", "tier2": "Amazon", "vendor": "Amazon"},
    {"pattern": r"NORDSTROM", "tier1": "Non-Essential", "tier2": "Clothing", "vendor": "Nordstrom"},
    {"pattern": r"ONEQUINCE|QUINCE", "tier1": "Non-Essential", "tier2": "Clothing", "vendor": "Quince"},
    {"pattern": r"LULULEMON", "tier1": "Non-Essential", "tier2": "Clothing", "vendor": "Lululemon"},
    {"pattern": r"OLD NAVY|GAP\s|BANANA REPUBLIC", "tier1": "Non-Essential", "tier2": "Clothing", "vendor": None},
    {"pattern": r"PAPERSOURCE|PAPER SOURCE", "tier1": "Non-Essential", "tier2": "Shopping", "vendor": "Paper Source"},
    # Add your barber, salon, spa, etc.:
    # {"pattern": r"YOUR BARBER|YOUR SALON", "tier1": "Non-Essential", "tier2": "Personal Care", "vendor": "Your Barber"},

    # ─── Non-Essential: Subscriptions ───
    {"pattern": r"NETFLIX|HULU|DISNEY\+|SPOTIFY|YOUTUBE.*PREM|HBO|PARAMOUNT", "tier1": "Non-Essential", "tier2": "Subscriptions", "vendor": None},
    {"pattern": r"PAYPAL \*PATREON", "tier1": "Non-Essential", "tier2": "Subscriptions", "vendor": "Patreon"},
    {"pattern": r"Prime Video", "tier1": "Non-Essential", "tier2": "Subscriptions", "vendor": "Amazon Prime Video"},
    {"pattern": r"Xbox Game|XBOX", "tier1": "Non-Essential", "tier2": "Subscriptions", "vendor": "Xbox Game Pass"},
    {"pattern": r"PlayStation Network|PSN", "tier1": "Non-Essential", "tier2": "Subscriptions", "vendor": "PlayStation"},

    # ─── Non-Essential: Travel & Transport ───
    {"pattern": r"SOUTHWEST|DELTA|UNITED AIR|AMERICAN AIR|JETBLUE|ALASKA AIR", "tier1": "Non-Essential", "tier2": "Travel", "vendor": None},
    {"pattern": r"MARRIOTT|HILTON|HYATT|HOLIDAY INN", "tier1": "Non-Essential", "tier2": "Travel", "vendor": None},
    {"pattern": r"LYFT", "tier1": "Non-Essential", "tier2": "Rideshare", "vendor": "Lyft"},
    {"pattern": r"AplPay Uber Cash|UBER(?!.*EAT)", "tier1": "Non-Essential", "tier2": "Rideshare", "vendor": "Uber"},
    {"pattern": r"SPOTHERO", "tier1": "Non-Essential", "tier2": "Parking", "vendor": "SpotHero"},
    {"pattern": r"PARKING|PARK MOBILE|PARKWHIZ", "tier1": "Non-Essential", "tier2": "Parking", "vendor": None},

    # ─── Non-Essential: Entertainment ───
    {"pattern": r"FANDANGO", "tier1": "Non-Essential", "tier2": "Entertainment", "vendor": "Fandango"},
    {"pattern": r"CINEMARK|AMC THEATRE|REGAL CINEMA", "tier1": "Non-Essential", "tier2": "Entertainment", "vendor": None},
    # Add local entertainment venues, museums, ski resorts, etc.:
    # {"pattern": r"LOCAL MUSEUM|LOCAL SKI RESORT", "tier1": "Non-Essential", "tier2": "Entertainment", "vendor": "Your Venue"},
    # Venmo amount-based override example: -$40 monthly → cell phone bill shared via Venmo
    {"pattern": r"VENMO.*PAYMENT|External Withdrawal.*VENMO", "tier1": "Non-Essential", "tier2": "Venmo", "vendor": "Venmo",
     "amount_match": {"exact": -40.0, "override_tier1": "Fixed", "override_tier2": "Cell Phone"}},

    # ─── Non-Essential: Vending / Misc ───
    {"pattern": r"CTLP\*CANTEEN|CANTEEN VENDING", "tier1": "Non-Essential", "tier2": "Vending", "vendor": "Canteen"},

    # ─── Discretionary ───
    {"pattern": r"EBAY", "tier1": "Discretionary", "tier2": "Hobbies", "vendor": "eBay"},
    {"pattern": r"BEST BUY", "tier1": "Discretionary", "tier2": "Electronics/Devices", "vendor": "Best Buy"},
    {"pattern": r"AplPay APPLE\.COM/BIL|APPLE\.COM/BILL|APPLE STORE", "tier1": "Discretionary", "tier2": "Apple Services", "vendor": "Apple"},
    # Add your hobby shops, lessons, niche merchants:
    # {"pattern": r"YOUR HOBBY SHOP", "tier1": "Discretionary", "tier2": "Hobbies", "vendor": "Your Shop"},
    # {"pattern": r"YOUR INSTRUCTOR", "tier1": "Discretionary", "tier2": "Lessons", "vendor": "Your Instructor"},
    {"pattern": r"HALLMARK", "tier1": "Discretionary", "tier2": "Shopping", "vendor": "Hallmark"},
    # Add your Shopify / PayPal merchants:
    # {"pattern": r"PAYPAL \*MERCHANT_NAME", "tier1": "Discretionary", "tier2": "Shopping", "vendor": "Merchant"},
    # {"pattern": r"SP SHOPIFY_STORE", "tier1": "Discretionary", "tier2": "Shopping", "vendor": "Store Name"},

    # ─── Allocations (transfers to self) ───
    {"pattern": r"TRANSFER.*SAV|XFER.*SAV", "tier1": "Allocation", "tier2": "Savings", "vendor": None},

    # ─── Misc catch-alls ───
    {"pattern": r"PAYPAL INSTANT TRANSFER|PAYPAL.*INSTANT", "tier1": "Transfer", "tier2": "PayPal Transfer", "vendor": "PayPal"},

    # ─── Catch-all for PAYPAL (after specific PAYPAL rules) ───
    {"pattern": r"PAYPAL \*", "tier1": "Non-Essential", "tier2": "PayPal", "vendor": None},
    {"pattern": r"IAT.*PAYPAL", "tier1": "Transfer", "tier2": "PayPal Transfer", "vendor": "PayPal"},
]

# Catch-all: anything unmatched → Non-Essential / Misc, flagged for review
DEFAULT_CATEGORY = {"tier1": "Non-Essential", "tier2": "Misc / Uncategorized", "vendor": None}
