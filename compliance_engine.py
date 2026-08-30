import os
import re
import asyncio
import google.generativeai as genai
from rapidfuzz import fuzz
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Setup Gemini model
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")
else:
    gemini_model = None

class Transaction:
    def __init__(self, tx_id, remitter, customer, amount, details=""):
        self.tx_id = tx_id
        self.remitter = remitter
        self.customer = customer
        self.amount = amount
        self.details = details

class ComplianceEngine:
    def __init__(self):
        self.model = gemini_model
        
    def calculate_match_score(self, name1, name2):
        """Tier 1: High-speed deterministic fuzzy matching using rapidfuzz."""
        # Normalize and strip names
        n1 = name1.strip().lower()
        n2 = name2.strip().lower()
        
        # Token sort ratio handles word ordering mismatches (e.g. "Ahmed Mirza" vs "Mirza Ahmed")
        return fuzz.token_sort_ratio(n1, n2) / 100.0

    async def audit_transaction(self, tx: Transaction):
        """
        Audits a transaction using a Tiered approach.
        - Tier 1: Match Score >= 0.90 -> Auto-Approve.
        - Tier 1: Match Score < 0.70 -> Auto-Block.
        - Tier 2: 0.70 <= Match Score < 0.90 -> Escalate to LLM Auditor.
        """
        score = self.calculate_match_score(tx.remitter, tx.customer)
        
        # TIER 1 Rules
        if score >= 0.90:
            return {
                "decision": "APPROVE",
                "tier": 1,
                "score": score,
                "narrative": "Tier 1 Auto-Approve: High name matching similarity satisfies the regulatory CDD requirements."
            }
        elif score < 0.70:
            return {
                "decision": "BLOCK",
                "tier": 1,
                "score": score,
                "narrative": "Tier 1 Auto-Block: High mismatch risk identified. The originator (remitter) name does not match the invoiced customer."
            }
            
        # TIER 2 Escalation (Cognitive LLM)
        prompt_text = (
            "You are a Fintech AML Compliance Auditor. Evaluate the following transaction under the FinCEN "
            "Customer Due Diligence (CDD) Final Rule (31 CFR § 1010.230 concerning Third-Party Payment Risk).\n\n"
            f"Transaction ID: {tx.tx_id}\n"
            f"Remitter (Bank Statement): {tx.remitter}\n"
            f"Customer (Invoice): {tx.customer}\n"
            f"Amount: ${tx.amount:,.2f}\n"
            f"Fuzzy Match Score: {score:.2f}\n"
            f"Context details: {tx.details}\n\n"
            "Evaluate if this represents a safe abbreviation, spelling variant, or a dangerous third-party shell payment. "
            "Respond in a paragraph explaining the AML risk, citing 31 CFR § 1010.230. Conclude with 'BLOCK' or 'APPROVE'."
        )
        
        if self.model:
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, lambda: self.model.generate_content(
                    prompt_text,
                    generation_config={"temperature": 0.2}
                ))
                narrative = response.text
                decision = "BLOCK" if "BLOCK" in narrative.upper() else "APPROVE"
                return {
                    "decision": decision,
                    "tier": 2,
                    "score": score,
                    "narrative": narrative
                }
            except Exception as e:
                # Fallback on API errors
                return self._mock_tier2_fallback(tx, score)
        else:
            return self._mock_tier2_fallback(tx, score)

    def _mock_tier2_fallback(self, tx: Transaction, score: float):
        # Standardize strings by removing common suffixes, middle initials, and punctuation
        def clean_name(name):
            n = name.lower()
            n = re.sub(r"\b(corp|corporation|ltd|limited|inc|incorporated|llc)\b", "", n)
            # Remove middle initials like " a. " or " a "
            n = re.sub(r"\b[a-z]\b\.?", "", n)
            n = re.sub(r"\s+", " ", n).strip()
            return n

        is_safe_abbreviation = clean_name(tx.remitter) == clean_name(tx.customer)
        
        if is_safe_abbreviation:
            decision = "APPROVE"
            narrative = (
                f"Tier 2 Escalation (Gemini Fallback): Evaluated names '{tx.remitter}' and '{tx.customer}'. "
                f"The mismatch is determined to be a safe legal suffix variation ('Corp' vs 'Corporation'). "
                f"This does not represent a third-party payment risk under 31 CFR § 1010.230. Decision: APPROVE."
            )
        else:
            decision = "BLOCK"
            narrative = (
                f"Tier 2 Escalation (Gemini Fallback): Evaluated names '{tx.remitter}' and '{tx.customer}'. "
                f"The mismatch indicates different entities (Third-Party Payment). This violates the FinCEN CDD "
                f"regulation (31 CFR § 1010.230) by auto-reconciling payments from a third-party company "
                f"without manual review, facilitating potential money laundering. Decision: BLOCK."
            )
            
        return {
            "decision": decision,
            "tier": 2,
            "score": score,
            "narrative": narrative
        }

# Demo runner
async def main():
    engine = ComplianceEngine()
    
    # Generate mock transactions
    txs = [
        Transaction("TX-101", "John Doe", "John Doe", 1500.00),
        Transaction("TX-102", "Xavier Holdings LLC", "Acme Corporation", 12000.00),
        Transaction("TX-103", "Ahmed Mirza", "Ahmed A. Mirza", 450.00, "Spelling difference in banking records"),
        Transaction("TX-104", "Goldman Trading Ltd", "Goldman Trading", 8500.00, "Corporate suffix abbreviation"),
        Transaction("TX-105", "Apex Corp", "Summit Logistics", 150000.00, "Payment routed from partner entity")
    ]
    
    print("🚀 Fintech Compliance Engine: Auditing Transaction Stream...")
    print("=" * 70)
    for tx in txs:
        result = await engine.audit_transaction(tx)
        print(f"ID: {tx.tx_id} | Remitter: {tx.remitter:<22} | Customer: {tx.customer:<20}")
        print(f"Score: {result['score']:.2f} | Tier: {result['tier']} | Decision: {result['decision']}")
        print(f"Reason: {result['narrative']}\n" + "-" * 70)

if __name__ == "__main__":
    asyncio.run(main())
