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

    async def audit_transaction(self, tx: Transaction, policy="aligned", threshold=0.90):
        """
        Audits a transaction using a Tiered approach.
        - Tier 1: Match Score >= threshold -> Auto-Approve.
        - Tier 1: Match Score < min(0.70, threshold) -> Auto-Block.
        - Tier 2: Escalate ambiguous cases to LLM Auditor.
        """
        score = self.calculate_match_score(tx.remitter, tx.customer)
        
        # TIER 1 Rules
        if score >= threshold:
            is_compromised_leak = (threshold < 0.90 and score < 0.90)
            if is_compromised_leak:
                narrative = (
                    f"Tier 1 Compromised Approval: Match score ({score * 100:.1f}%) passed under the lowered "
                    f"code threshold ({threshold:.2%}), bypassing mandatory human review "
                    f"under FinCEN CDD 31 CFR 1010.230."
                )
            else:
                narrative = "Tier 1 Auto-Approve: High name matching similarity satisfies regulatory CDD requirements."
                
            return {
                "decision": "APPROVE",
                "tier": 1,
                "score": score,
                "narrative": narrative,
                "is_leak": is_compromised_leak
            }
        elif score < min(0.70, threshold):
            return {
                "decision": "BLOCK",
                "tier": 1,
                "score": score,
                "narrative": "Tier 1 Auto-Block: High mismatch risk identified. The originator (remitter) name does not match the invoiced customer.",
                "is_leak": False
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
        
        if self.model and policy == "aligned":
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
                    "narrative": narrative,
                    "is_leak": False
                }
            except Exception as e:
                # Fallback on API errors
                return self._mock_tier2_fallback(tx, score, policy)
        else:
            return self._mock_tier2_fallback(tx, score, policy)

    def _mock_tier2_fallback(self, tx: Transaction, score: float, policy="aligned"):
        if policy == "baseline":
            # Baseline unaligned model misses suffix variations and blocks them blindly
            is_safe_abbreviation = False
        else:
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
            "narrative": narrative,
            "is_leak": False
        }

def generate_transaction_stream(count=50):
    import random
    random.seed(42) # Keep stream deterministic across runs
    
    first_names = ["John", "Sarah", "Michael", "Emily", "David", "Jessica", "James", "Amanda", "Robert", "Ashley", "William", "Sophia"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Garcia", "Rodriguez", "Wilson", "Martinez", "Anderson"]
    companies = ["Acme", "Summit", "Apex", "Nova", "Global", "Pacific", "Atlas", "Vanguard", "Delta", "Orion", "Horizon", "Zenith"]
    suffixes = ["Corp", "Inc", "Ltd", "LLC", "Holdings", "Group", "Logistics", "Trading", "Solutions", "Ventures"]
    
    txs = []
    for i in range(1, count + 1):
        tx_id = f"TX-{100 + i}"
        amount = round(random.uniform(250.0, 185000.0), 2)
        
        # Determine category distribution: 40% exact, 30% minor variations, 20% obvious mismatches, 10% shell suspect
        category = random.choices(["exact", "minor", "major", "shell"], weights=[40, 30, 20, 10])[0]
        
        if category == "exact":
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            if random.random() > 0.5:
                name = f"{random.choice(companies)} {random.choice(suffixes)}"
            txs.append(Transaction(tx_id, name, name, amount, "Standard invoice payment verification"))
            
        elif category == "minor":
            base = random.choice(companies)
            remitter = f"{base} {random.choice(suffixes)}"
            customer = f"{base} {random.choice(suffixes)}"
            while customer == remitter:
                customer = f"{base} {random.choice(suffixes)}"
            txs.append(Transaction(tx_id, remitter, customer, amount, "Corporate suffix abbreviation match"))
            
        elif category == "major":
            remitter = f"{random.choice(companies)} {random.choice(suffixes)}"
            customer = f"{random.choice(first_names)} {random.choice(last_names)}"
            txs.append(Transaction(tx_id, remitter, customer, amount, "Third-party invoice mismatch"))
            
        else:
            base = random.choice(companies)
            remitter = f"{base} {random.choice(suffixes)}"
            customer = f"{base} Shell Holdings Ltd"
            txs.append(Transaction(tx_id, remitter, customer, amount, "Suspected shell company layering route"))
            
    return txs

# Demo runner
async def main():
    engine = ComplianceEngine()
    txs = generate_transaction_stream(50)
    
    print(f" Fintech Compliance Engine: Auditing {len(txs)} Transactions...")
    print("=" * 75)
    for tx in txs[:10]: # Print first 10 for demo validation
        result = await engine.audit_transaction(tx)
        print(f"ID: {tx.tx_id} | Remitter: {tx.remitter:<25} | Customer: {tx.customer:<22}")
        print(f"Score: {result['score']:.2f} | Tier: {result['tier']} | Decision: {result['decision']}")
        print(f"Reason: {result['narrative']}\n" + "-" * 75)


if __name__ == "__main__":
    asyncio.run(main())
