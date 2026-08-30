import asyncio
import os
import torch
import tinker
from tinker import types, TensorData
# pyrefly: ignore [missing-import]
from tinker_cookbook.renderers import get_renderer, get_text_content

# Note: Assuming tinker is installed in the target execution environment.

async def aml_compliance_reward_function(model_output: str, pr_metadata_path: str) -> float:
    """
    Evaluates if the model successfully used Graphify tools to find the AML bug.
    """
    # 1. Parse ground truth from our synthetic sandbox
    with open(pr_metadata_path, "r") as f:
        meta = f.read()
    is_poisoned = "POISONED:True" in meta
    
    # 2. Check model output for correct citations and tool usage
    cited_fincen = "31 CFR § 1010.230" in model_output or "Third-Party Payment" in model_output
    used_graphify = "<tool_call>graphify_path" in model_output or "<tool_call>graphify_query" in model_output
    flagged_bug = "BLOCK" in model_output.upper()
    
    # 3. Grade the attempt (GRPO style reward)
    if is_poisoned:
        if cited_fincen and used_graphify and flagged_bug:
            return 1.0  # Perfect catch
        elif flagged_bug:
            return 0.5  # Caught it, but poor reasoning/tool use
        else:
            return 0.0  # Missed the bug
    else:
        if flagged_bug:
            return -1.0 # False positive, penalize heavily
        return 1.0      # Correctly approved a safe PR

async def train():
    service = tinker.ServiceClient()
    
    # STEP 1: Fast Prototyping Model (Later swap to "moonshotai/Kimi-K2.6" for production)
    base_model = "Qwen/Qwen3.5-9B-Base"
    
    training_client = await service.create_lora_training_client_async(
        base_model=base_model,
        rank=32
    )
    
    tokenizer = training_client.get_tokenizer()
    renderer = get_renderer("role_colon", tokenizer)
    
    sampling_params = tinker.types.SamplingParams(
        max_tokens=512,
        stop=renderer.get_stop_sequences(),
    )
    adam_params = tinker.AdamParams(learning_rate=2e-5, beta1=0.9, beta2=0.95)
    
    # STEP 2: Load synthetic PR data
    synthetic_prs_dir = "synthetic_prs"
    if not os.path.exists(synthetic_prs_dir):
        raise FileNotFoundError(f"Directory {synthetic_prs_dir} does not exist. Please run generate_poisoned_prs.py first.")
        
    pr_files = sorted([f for f in os.listdir(synthetic_prs_dir) if f.endswith("_matcher_agent.py")])
    train_data = []
    for pr_file in pr_files:
        pr_id = pr_file.split("_")[1]
        meta_file = f"pr_{pr_id}_meta.txt"
        pr_path = os.path.join(synthetic_prs_dir, pr_file)
        meta_path = os.path.join(synthetic_prs_dir, meta_file)
        if os.path.exists(meta_path):
            train_data.append((pr_path, meta_path))
            
    if not train_data:
        raise ValueError("No training data found in synthetic_prs directory.")
        
    print(f"Loaded {len(train_data)} synthetic PRs for training.")
    print(f"Starting GRPO RL training on {base_model}...")
    
    # STEP 3: Active Training Loop (GRPO Methodologies)
    batch_size = 4
    group_size = 4
    n_steps = len(train_data) // batch_size
    
    for step in range(n_steps):
        batch_rows = train_data[step * batch_size : (step + 1) * batch_size]
        sampling_client = await training_client.save_weights_and_get_sampling_client_async()
        
        prompts_P: list[tinker.ModelInput] = []
        _coros = []
        
        for code_path, meta_path in batch_rows:
            with open(code_path, "r") as f:
                pr_code = f.read()
                
            convo = [
                {
                    "role": "user",
                    "content": (
                        "Audit the following Pull Request for compliance with FinCEN AML CDD regulations "
                        "(specifically 31 CFR § 1010.230 concerning Third-Party Payment Risk). "
                        "You should perform a compliance query using `<tool_call>graphify_query` or `<tool_call>graphify_path` "
                        "and output a narrative explaining your decision. "
                        "Conclude your audit report with 'BLOCK' if there is any compliance risk (e.g. lowering the fuzzy-matching "
                        "threshold below 90% without human-in-the-loop review) or 'APPROVE' if it is safe.\n\n"
                        f"Code Change:\n{pr_code}"
                    )
                }
            ]
            prompt = renderer.build_generation_prompt(convo)
            prompts_P.append(prompt)
            _coros.append(
                sampling_client.sample_async(
                    prompt=prompt, num_samples=group_size, sampling_params=sampling_params
                )
            )
            
        sample_results_P = await asyncio.gather(*_coros)
        
        datums_D: list[tinker.Datum] = []
        rewards_P: list[float] = []
        n_degenerate = 0
        
        for sample_result, prompt, (code_path, meta_path) in zip(
            sample_results_P, prompts_P, batch_rows
        ):
            rewards_G: list[float] = []
            tokens_G_T: list[list[int]] = []
            logprobs_G_T: list[list[float]] = []
            
            for sequence in sample_result.sequences:
                tokens_G_T.append(sequence.tokens)
                logprobs_G_T.append(sequence.logprobs)
                
                parsed_message, _ = renderer.parse_response(sequence.tokens)
                content = get_text_content(parsed_message)
                
                reward = await aml_compliance_reward_function(content, meta_path)
                rewards_G.append(reward)
                
            mean_reward = sum(rewards_G) / len(rewards_G)
            advantages_G = [r - mean_reward for r in rewards_G]
            rewards_P.append(mean_reward)
            
            # Skip degenerate groups (all same reward -> zero advantage -> no signal)
            if all(a == 0.0 for a in advantages_G):
                n_degenerate += 1
                continue
                
            # Build Datum objects for the non-degenerate completions
            ob_len = prompt.length - 1
            for tokens, logprobs, advantage in zip(tokens_G_T, logprobs_G_T, advantages_G):
                model_input = prompt.append(tinker.types.EncodedTextChunk(tokens=tokens[:-1]))
                target_tokens = [0] * ob_len + tokens
                padded_logprobs = [0.0] * ob_len + logprobs
                padded_advantages = [0.0] * ob_len + [advantage] * (model_input.length - ob_len)
                
                datum = tinker.Datum(
                    model_input=model_input,
                    loss_fn_inputs={
                        "target_tokens": TensorData.from_torch(torch.tensor(target_tokens)),
                        "logprobs": TensorData.from_torch(torch.tensor(padded_logprobs)),
                        "advantages": TensorData.from_torch(torch.tensor(padded_advantages)),
                    }
                )
                datums_D.append(datum)
                
        # Gradient Update Step
        if len(datums_D) > 0:
            fwd_bwd_future = await training_client.forward_backward_async(
                datums_D, loss_fn="importance_sampling"
            )
            optim_future = await training_client.optim_step_async(adam_params)
            await fwd_bwd_future.result_async()
            await optim_future.result_async()
            
        mean_reward_batch = sum(rewards_P) / len(rewards_P) if rewards_P else 0.0
        print(f"Step {step + 1}/{n_steps} | Mean Reward: {mean_reward_batch:.3f} | Degenerate Groups: {n_degenerate}/{len(batch_rows)}")
        
    print("Training complete. Exporting weights...")
    sampling_client = await training_client.save_weights_and_get_sampling_client_async()
    print(f"Model exported and ready for sampling at: {sampling_client.model_path}")

if __name__ == "__main__":
    print("Tinker RL Setup Script Initialized.")
    # asyncio.run(train()) # Keep commented out to avoid requiring API keys on import/direct invocation.
