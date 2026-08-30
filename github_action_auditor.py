import subprocess
import sys

def run_graphify_update():
    print("Running lightweight AST update (graphify update .)...")
    try:
        # Assuming graphify is globally available or in .venv
        subprocess.run(["graphify", "update", "."], check=True)
    except Exception as e:
        print(f"Graphify update simulated. {e}")

def run_compliance_audit(pr_files):
    print(f"Auditing PR files: {pr_files}")
    # Here we would call the trained Tinker sampling_client
    print("Invoking Tinker-trained AML Compliance Agent...")
    
    # Mock output
    decision = "BLOCK"
    narrative = " Compliance Block (High Risk): The fuzzy match tolerance violates FinCEN CDD Rule (31 CFR § 1010.230)."
    
    if decision == "BLOCK":
        print(narrative)
        sys.exit(1)
    else:
        print(" PR is AML Compliant. Approving.")
        sys.exit(0)

if __name__ == "__main__":
    run_graphify_update()
    run_compliance_audit(["src/matcher_agent.py"])
