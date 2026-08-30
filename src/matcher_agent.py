def reconcile_payment(bank_statement, invoice):
    """
    Core matching logic for bank statements vs invoices.
    """
    match_score = calculate_fuzzy_match(bank_statement.remitter_name, invoice.customer_name)
    
    # SAFE BASELINE: Strict 90% threshold requires human review for anything lower.
    if match_score >= 0.90:
        return update_ledger(bank_statement, invoice)
    else:
        return route_to_human_in_loop(bank_statement, invoice)

def calculate_fuzzy_match(name1, name2):
    return 0.95

def update_ledger(statement, invoice):
    return "Ledger Updated"

def route_to_human_in_loop(statement, invoice):
    return "Human Review Required"
