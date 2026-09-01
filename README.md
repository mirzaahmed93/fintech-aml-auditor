# Fintech AML Compliance Auditor

An automated, reinforcement-learning-powered Pull Request (PR) compliance auditor and transaction screening engine. This system audits codebase modifications for Anti-Money Laundering (AML) compliance violations by fusing regulatory documentation into a codebase knowledge graph, utilizing adversarial co-training (self-play), and providing a human-in-the-loop compliance dashboard.

---

## Mission and Objectives

In modern fintech, minor modifications to transaction matching thresholds can bypass security controls and facilitate trade-based money laundering (TBML) or fraudulent activities. This auditor is designed to:
1. **Bridge the gap between regulatory requirements and source code** using semantic knowledge graphs.
2. **Train a specialized AI compliance auditor (Blue Team)** using **Group Relative Policy Optimization (GRPO)**.
3. **Harden the auditor using self-play** by training a **Rogue Developer (Red Team)** that attempts to inject hidden compliance bypasses in name matching or threshold algorithms.
4. **Empower Human Compliance Officers** to monitor transaction streams, review raw payloads, and actively train the AI through a visual dashboard.

---

## Mechanics: How It Works

This system combines modern reinforcement learning and efficient fine-tuning to train an expert compliance model:

* **Base Model (Qwen-9B)**: Acts as the foundation model for understanding code logic, parsing text, and reasoning about financial flows.
* **LoRA (Low-Rank Adaptation)**: Rather than retraining billions of weights in the base model, the base model is frozen. We train a lightweight adapter layer (a tiny fraction of the model size, ~20MB-50MB) containing compliance-specific knowledge. This reduces training compute requirements by over 98% while achieving high accuracy.
* **GRPO (Group Relative Policy Optimization)**: Instead of requiring an expensive helper "critic" model, GRPO generates a group of draft reviews for each code change, scores them against FinCEN CDD compliance rules, and adjusts the model based on relative draft quality.
* **Knowledge Graph (Graphify)**: Extracts structural relationships from code ASTs and regulatory guidelines (such as FinCEN 31 CFR 1010.230) so the model can cite exact legal rules when auditing code.
* **Continuous Feedback Loop**: When a human compliance officer overrides a flagged transaction in the dashboard, the decision is logged and can be used to run incremental fine-tuning epochs that align the model with human judgment.

---

## Architecture

```mermaid
graph TD
    Manual[docs/fincen_bsa_manual.md] -->|Graphify Extract| Graph[graph.json]
    Codebase[src/matcher_agent.py] -->|Graphify Extract| Graph
    
    subgraph Zero-Sum Self-Play Game Loop
        RogueDev[Rogue Developer - Red Team] -->|Generates Backdoor PR| PR[Candidate Code Change]
        Auditor[Compliance Auditor - Blue Team] -->|Reviews PR| AuditResult[Approve or Block]
        
        PR --> AuditResult
        AuditResult -->|Rewards: Catch/Bypass| RewardEngine[Reward Matrix]
        RewardEngine -->|Advantages| RogueDev
        RewardEngine -->|Advantages| Auditor
    end
```

---

## Streamlit Compliance Portal (Demo Overview)

The project includes a human-in-the-loop verification portal (`dashboard.py`). Run the portal locally using:
```bash
streamlit run dashboard.py
```

The portal exposes two key operational areas:

### Tab 1: Pull Request Audits (Code Safety Review)
* **Inbox**: Select from 50 synthetic PR changes generated during testing.
* **AI Auditor Narrative**: Explains the AML compliance risk of the code change.
* **Compliance Impact Card**: Summarizes the system modifications in a non-technical grid (e.g. comparing proposed threshold changes against the 90% FinCEN baseline) for regulators.
* **Decision Center**: Allows the compliance officer to manually confirm blocks or apply overrides.

### Tab 2: Live Transaction Stream and Halted Funds Escrow
* **Real-time Performance Metrics**: Displays transaction screening counts, auto-routing rates, live AI accuracy, and escrowed capital.
* **Collapsible Details (Raw and Reasoning)**: Allows inspectors to expand any transaction card to view:
  * **Raw JSON Payload**: Complete transaction structure (banking records, accounts, clearing routes).
  * **Deep Reasoning**: Matching similarity scores, compliance checklists, and the Graphify relationship mapping path.
* **Active Escrow Controls**: Flagged transactions are placed in a `HALTED & ESCROWED` state. Officers can click `Release Funds` or `Seize Funds` to update the transaction state.
* **Interactive Retraining**: If overrides are made on the unaligned model, a banner appears enabling you to click **`Fine-Tune Auditor Model on Overrides`**. This runs an incremental training epoch, updating the policy weights to automatically resolve those edge cases correctly.

---

## Repository Structure

* `docs/fincen_bsa_manual.md`: Regulatory manual detailing CDD guidelines and thresholds.
* `src/matcher_agent.py`: Baseline name-matching reconciliation engine.
* `generate_poisoned_prs.py`: Script to generate 50 mock pull requests (mix of compliant and poisoned code) for training.
* `train_auditor.py`: Training script for the Blue Team Compliance Auditor via GRPO.
* `red_team_agent.py`: Training script for the Rogue Developer adversarial agent.
* `compliance_engine.py`: Dual-tiered transaction screening and routing engine.
* `dashboard.py`: Streamlit human-in-the-loop web portal.
* `tinker.py`: Local SDK wrapper and simulator for offline/API-fallback testing.

---

## Setup and Installation

### 1. Initialize Environment
Set up a local virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### 2. Configure Environment Keys
Create a `.env` file in the root directory of the project to store your access credentials. This file is ignored by Git to protect your secrets:
```ini
GEMINI_API_KEY=your-gemini-api-key
```

### 3. Install Libraries and Generate Data
```bash
# Install local dependencies in editable mode
pip install -e /Users/ahmedmirza/git/graphify
pip install -e "/Users/ahmedmirza/git/tinker-cookbook[tutorials]"

# Generate mock PR database
python3 generate_poisoned_prs.py
```

---

## Running the Pipelines

### 1. Rebuild the Knowledge Graph
Ensure your `.env` contains your Gemini credentials and run the extraction:
```bash
# Extract semantic relations
python3 -m graphify extract .
```

### 2. Run Auditor and Red Team Training
Run the RL training scripts:
```bash
# Train Blue Team Auditor
python3 train_auditor.py

# Train Red Team Rogue Developer
python3 red_team_agent.py
```

### 3. Launch the Web Portal
```bash
streamlit run dashboard.py
```
