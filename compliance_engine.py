import os
import re
import asyncio
import google.generativeai as genai
from rapidfuzz import fuzz
from dotenv import load_dotenv

from src.compliance_graph import ComplianceGraph

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
    def __init__(self, tx_id, remitter, customer, amount, details="", origin_country="US"):
        self.tx_id = tx_id
        self.remitter = remitter
        self.customer = customer
        self.amount = amount
        self.details = details
        self.origin_country = origin_country

class ComplianceEngine:
    def __init__(self):
        self.model = gemini_model
        self.knowledge_graph = ComplianceGraph()
        
    def calculate_match_score(self, name1, name2):
        """Tier 1: High-speed deterministic fuzzy matching using rapidfuzz."""
        # Normalize and strip names
        n1 = name1.strip().lower()
        n2 = name2.strip().lower()
        
        # Token sort ratio handles word ordering mismatches (e.g. "Ahmed Mirza" vs "Mirza Ahmed")
        return fuzz.token_sort_ratio(n1, n2) / 100.0

    def calculate_structuring_risk(self, amount: float) -> float:
        """
        Evaluates Currency Transaction Reporting (CTR) structuring risk under 31 U.S.C. 5324.
        Amounts immediately below the $10,000 reporting threshold carry elevated suspicion.
        """
        # Highest risk band: $8,500.00 to $9,999.99 (intentional avoidance corridor)
        if 8500.0 <= amount < 10000.0:
            proximity = (amount - 8500.0) / 1500.0
            return round(0.75 + (0.20 * proximity), 2)
        elif 7000.0 <= amount < 8500.0:
            return 0.40
        else:
            return 0.05

    def calculate_jurisdiction_risk(self, country_code: str) -> float:
        """
        Evaluates geographic risk under FATF Recommendation 19 & FinCEN country advisories.
        Offshore financial centers and secrecy havens receive elevated risk multipliers.
        """
        code = country_code.upper().strip()
        high_risk_jurisdictions = {"KY", "VG", "SC", "PA", "CY", "AE", "BS", "MH"}
        medium_risk_jurisdictions = {"MT", "GI", "MU", "CW", "LU"}
        
        if code in high_risk_jurisdictions:
            return 0.85
        elif code in medium_risk_jurisdictions:
            return 0.50
        return 0.10

    def calculate_composite_risk(self, identity_score: float, structuring_risk: float, jurisdiction_risk: float):
        """
        Calculates weighted composite AML risk score and assigns a severity classification.
        - 50% Identity Discrepancy (1.0 - identity_score)
        - 30% Structuring / CTR Proximity
        - 20% Jurisdictional Exposure
        """
        identity_discrepancy = 1.0 - identity_score
        composite = (0.50 * identity_discrepancy) + (0.30 * structuring_risk) + (0.20 * jurisdiction_risk)
        composite = round(min(1.0, max(0.0, composite)), 2)
        
        if composite >= 0.70:
            level = "CRITICAL"
        elif composite >= 0.45:
            level = "HIGH"
        elif composite >= 0.25:
            level = "MEDIUM"
        else:
            level = "LOW"
            
        return composite, level

    async def audit_transaction(self, tx: Transaction, policy="aligned", threshold=0.90):
        """
        Audits a transaction using a Multi-Vector Tiered approach.
        - Vector 1: Identity Match (Fuzzy String Similarity)
        - Vector 2: Structuring Risk (31 U.S.C. 5324 CTR Corridor)
        - Vector 3: Geographic Risk (FATF Rec. 19 Secrecy Haven Multiplier)
        """
        score = self.calculate_match_score(tx.remitter, tx.customer)
        structuring_risk = self.calculate_structuring_risk(tx.amount)
        country = getattr(tx, "origin_country", "US")
        jurisdiction_risk = self.calculate_jurisdiction_risk(country)
        composite_risk, risk_level = self.calculate_composite_risk(score, structuring_risk, jurisdiction_risk)
        
        graph_traversal = self.knowledge_graph.get_compliance_traversal()
        
        has_multi_vector_red_flag = (structuring_risk > 0.60 or jurisdiction_risk > 0.60)
        
        # TIER 1 Rules
        # If multi-vector red flag is active, escalate past Tier 1 even if name matches
        if score >= threshold and not has_multi_vector_red_flag:
            is_compromised_leak = (threshold < 0.90 and score < 0.90)
            if is_compromised_leak:
                narrative = (
                    f"Tier 1 Compromised Approval: Match score ({score * 100:.1f}%) passed under the lowered "
                    f"code threshold ({threshold:.2%}), bypassing mandatory human review "
                    f"under FinCEN CDD 31 CFR 1010.230."
                )
            else:
                narrative = "Tier 1 Auto-Approve: High name matching similarity and clean multi-vector risk profile satisfy regulatory CDD requirements."
                
            return {
                "decision": "APPROVE",
                "tier": 1,
                "score": score,
                "structuring_risk": structuring_risk,
                "jurisdiction_risk": jurisdiction_risk,
                "composite_risk": composite_risk,
                "risk_level": risk_level,
                "origin_country": country,
                "narrative": narrative,
                "is_leak": is_compromised_leak,
                "graph_path": graph_traversal["formatted_path"],
                "graph_hops": graph_traversal["hops"]
            }
        elif score < min(0.70, threshold) and not has_multi_vector_red_flag:
            return {
                "decision": "BLOCK",
                "tier": 1,
                "score": score,
                "structuring_risk": structuring_risk,
                "jurisdiction_risk": jurisdiction_risk,
                "composite_risk": composite_risk,
                "risk_level": risk_level,
                "origin_country": country,
                "narrative": "Tier 1 Auto-Block: High mismatch risk identified. The originator (remitter) name does not match the invoiced customer.",
                "is_leak": False,
                "graph_path": graph_traversal["formatted_path"],
                "graph_hops": graph_traversal["hops"]
            }
            
        # TIER 2 Escalation (Cognitive LLM)
        graph_context = self.knowledge_graph.get_prompt_context()
        prompt_text = (
            "You are a Fintech AML Compliance Auditor. Evaluate the following transaction under the FinCEN "
            "Customer Due Diligence (CDD) Final Rule (31 CFR § 1010.230 concerning Third-Party Payment Risk) "
            "and Bank Secrecy Act anti-structuring provisions (31 U.S.C. § 5324).\n\n"
            f"{graph_context}\n\n"
            f"Transaction ID: {tx.tx_id}\n"
            f"Remitter (Bank Statement): {tx.remitter}\n"
            f"Customer (Invoice): {tx.customer}\n"
            f"Settlement Amount: ${tx.amount:,.2f} USD\n"
            f"Originating Country: {country}\n"
            f"Fuzzy Match Score: {score * 100:.1f}%\n"
            f"Structuring Risk Index: {structuring_risk:.2f} / 1.00\n"
            f"Jurisdictional Risk Index: {jurisdiction_risk:.2f} / 1.00\n"
            f"Composite Risk Score: {composite_risk:.2f} / 1.00 ({risk_level} RISK)\n"
            f"Context Details: {tx.details}\n\n"
            "Evaluate if this represents a safe abbreviation, spelling variant, an illicit third-party shell payment, "
            "or CTR structuring evasion. Respond in a concise paragraph explaining the AML risk, citing 31 CFR § 1010.230 "
            "and the retrieved knowledge graph traversal. Conclude with 'BLOCK' or 'APPROVE'."
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
                    "structuring_risk": structuring_risk,
                    "jurisdiction_risk": jurisdiction_risk,
                    "composite_risk": composite_risk,
                    "risk_level": risk_level,
                    "origin_country": country,
                    "narrative": narrative,
                    "is_leak": False,
                    "graph_path": graph_traversal["formatted_path"],
                    "graph_hops": graph_traversal["hops"]
                }
            except Exception as e:
                # Fallback on API errors
                return self._mock_tier2_fallback(tx, score, policy, graph_traversal, structuring_risk, jurisdiction_risk, composite_risk, risk_level)
        else:
            return self._mock_tier2_fallback(tx, score, policy, graph_traversal, structuring_risk, jurisdiction_risk, composite_risk, risk_level)

    def _mock_tier2_fallback(self, tx: Transaction, score: float, policy="aligned", graph_traversal=None, structuring_risk=0.05, jurisdiction_risk=0.10, composite_risk=0.10, risk_level="LOW"):
        if graph_traversal is None:
            graph_traversal = self.knowledge_graph.get_compliance_traversal()
            
        country = getattr(tx, "origin_country", "US")
        
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
        
        # If structuring or high-risk jurisdiction is severe, block regardless of abbreviation
        if structuring_risk > 0.60:
            decision = "BLOCK"
            narrative = (
                f"Tier 2 Escalation (Multi-Vector Alert): Evaluated transaction in amount of ${tx.amount:,.2f} from '{tx.remitter}'. "
                f"Severe structuring characteristics detected under 31 U.S.C. § 5324 (CTR threshold evasion band). "
                f"Escalated via knowledge graph traversal ({graph_traversal['formatted_path']}). Decision: BLOCK."
            )
        elif jurisdiction_risk > 0.60 and not is_safe_abbreviation:
            decision = "BLOCK"
            narrative = (
                f"Tier 2 Escalation (Geographic Alert): Wire originated from high-risk secrecy haven ({country}) "
                f"for remitter '{tx.remitter}'. Failed FATF Recommendation 19 enhanced due diligence and FinCEN CDD (31 CFR § 1010.230). "
                f"Escalated via knowledge graph traversal ({graph_traversal['formatted_path']}). Decision: BLOCK."
            )
        elif is_safe_abbreviation:
            decision = "APPROVE"
            narrative = (
                f"Tier 2 Escalation (Gemini Fallback): Evaluated names '{tx.remitter}' and '{tx.customer}' "
                f"via knowledge graph traversal ({graph_traversal['formatted_path']}). "
                f"The mismatch is determined to be a safe legal suffix variation ('Corp' vs 'Corporation') originating from {country}. "
                f"This does not represent a third-party payment risk under 31 CFR § 1010.230. Decision: APPROVE."
            )
        else:
            decision = "BLOCK"
            narrative = (
                f"Tier 2 Escalation (Gemini Fallback): Evaluated names '{tx.remitter}' and '{tx.customer}' "
                f"via knowledge graph traversal ({graph_traversal['formatted_path']}). "
                f"The mismatch indicates different entities (Third-Party Payment). This violates the FinCEN CDD "
                f"regulation (31 CFR § 1010.230) by auto-reconciling payments from a third-party company "
                f"without manual review, facilitating potential money laundering. Decision: BLOCK."
            )
            
        return {
            "decision": decision,
            "tier": 2,
            "score": score,
            "structuring_risk": structuring_risk,
            "jurisdiction_risk": jurisdiction_risk,
            "composite_risk": composite_risk,
            "risk_level": risk_level,
            "origin_country": country,
            "narrative": narrative,
            "is_leak": False,
            "graph_path": graph_traversal["formatted_path"],
            "graph_hops": graph_traversal["hops"]
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
        
        # Inject structuring amounts ($8,500 - $9,999) on specific test transactions
        if i in [12, 27, 44]:
            amount = round(random.choice([9850.00, 9920.00, 9750.00]), 2)
            structuring_note = " (CTR Avoidance Corridor Pattern)"
        else:
            amount = round(random.uniform(250.0, 185000.0), 2)
            structuring_note = ""
        
        # Determine category distribution: 40% exact, 30% minor variations, 20% obvious mismatches, 10% shell suspect
        category = random.choices(["exact", "minor", "major", "shell"], weights=[40, 30, 20, 10])[0]
        
        if category == "exact":
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            if random.random() > 0.5:
                name = f"{random.choice(companies)} {random.choice(suffixes)}"
            country = random.choice(["US", "US", "GB", "DE"])
            txs.append(Transaction(tx_id, name, name, amount, f"Standard invoice payment verification{structuring_note}", origin_country=country))
            
        elif category == "minor":
            base = random.choice(companies)
            remitter = f"{base} {random.choice(suffixes)}"
            customer = f"{base} {random.choice(suffixes)}"
            while customer == remitter:
                customer = f"{base} {random.choice(suffixes)}"
            country = random.choice(["US", "GB", "CA", "DE"])
            txs.append(Transaction(tx_id, remitter, customer, amount, f"Corporate suffix abbreviation match{structuring_note}", origin_country=country))
            
        elif category == "major":
            remitter = f"{random.choice(companies)} {random.choice(suffixes)}"
            customer = f"{random.choice(first_names)} {random.choice(last_names)}"
            country = random.choice(["KY", "VG", "PA", "US"])
            txs.append(Transaction(tx_id, remitter, customer, amount, f"Third-party invoice mismatch{structuring_note}", origin_country=country))
            
        else:
            base = random.choice(companies)
            remitter = f"{base} {random.choice(suffixes)}"
            customer = f"{base} Shell Holdings Ltd"
            country = random.choice(["KY", "VG", "SC", "CY"])
            txs.append(Transaction(tx_id, remitter, customer, amount, f"Suspected shell company layering route{structuring_note}", origin_country=country))
            
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
