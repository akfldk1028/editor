from __future__ import annotations

import argparse
import json
import sys

from backend.app.modules.local_topology_planner.contracts import (
    TopologyContractError,
    dump_topology_proposals_json,
    parse_topology_proposals_json,
    require_distinct_layout_sequences,
)


def _prompt(request: dict) -> str:
    node_ids = [node["node_id"] for node in request["nodes"]]
    layout_node_groups = _layout_node_groups(request)
    count = request["candidate_count"]
    example = {
        "candidates": [
            {
                "candidate_id": "topology-1",
                "sequence": node_ids,
                "adjacencies": [
                    {
                        "source": node_ids[0],
                        "target": node_ids[1],
                        "relation": "functional_adjacency",
                        "weight": 1.0,
                    }
                ],
            }
        ]
    }
    return (
        f"Propose exactly {count} distinct early-design "
        f"{request['use_type']} spatial topology alternatives. "
        "Use the supplied floor boundary, access candidates, room area and "
        "shape constraints, frontage requirements, zones, and existing "
        "program edges as the spatial brief. The deterministic geometry "
        "solver will preserve mandatory constraints. Spatial brief JSON: "
        f"{json.dumps(request, ensure_ascii=False, separators=(',', ':'))}. "
        "Return JSON only in this shape: "
        f"{json.dumps(example, ensure_ascii=False)}. "
        "Every sequence must contain each allowed node id exactly once and "
        f"no other id: {', '.join(node_ids)}. "
        "Every candidate must change relative order inside at least one of "
        "these solver role groups: "
        f"{json.dumps(layout_node_groups, ensure_ascii=False)}. "
        f"candidate_id must be topology-1 through topology-{count}. "
        "Adjacency endpoints must be allowed ids and distinct. "
        "relation must be functional_adjacency or service_adjacent. "
        "Provide useful undirected adjacencies, vary sequence and topology, "
        "and do not emit Markdown or explanations."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    request = json.loads(sys.stdin.read())
    node_ids = tuple(node["node_id"] for node in request["nodes"])
    layout_node_groups = _layout_node_groups(request)
    candidate_count = int(request["candidate_count"])
    if not 1 <= candidate_count <= 8:
        raise ValueError("candidate_count must be between 1 and 8")

    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
    )

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_path,
        local_files_only=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_path,
        quantization_config=quantization,
        device_map="auto",
        dtype=torch.bfloat16,
        local_files_only=True,
    )
    prompt = _prompt(request)
    last_error = "no generation attempt"
    for attempt in range(args.attempts):
        torch.manual_seed(args.seed + attempt)
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(model.device)
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=min(3600, 400 + candidate_count * 420),
                do_sample=attempt > 0,
                temperature=0.4 if attempt > 0 else None,
                top_p=0.9 if attempt > 0 else None,
                pad_token_id=tokenizer.eos_token_id,
            )
        text = tokenizer.decode(
            output[0, inputs["input_ids"].shape[1] :],
            skip_special_tokens=True,
        )
        try:
            proposals = parse_topology_proposals_json(
                text,
                allowed_node_ids=node_ids,
                expected_count=candidate_count,
            )
            require_distinct_layout_sequences(
                proposals,
                layout_node_groups=layout_node_groups,
            )
        except TopologyContractError as error:
            last_error = str(error)
            prompt += (
                f"\nThe previous response failed validation: {last_error}. "
                "Regenerate the complete JSON object."
            )
            continue
        sys.stdout.write(dump_topology_proposals_json(proposals))
        return
    raise RuntimeError(
        f"model did not produce a valid topology after {args.attempts} attempts: "
        f"{last_error}"
    )


def _layout_node_groups(request: dict) -> tuple[tuple[str, ...], ...]:
    support_types = {"pantry", "restroom", "it_storage"}
    enforce_frontage = bool(request.get("street_edge_indices"))
    nodes = request["nodes"]
    return (
        tuple(
            node["node_id"]
            for node in nodes
            if enforce_frontage
            and node["frontage_required"]
            and node["space_type"] not in {"core", "open_work"}
        ),
        tuple(
            node["node_id"]
            for node in nodes
            if node["space_type"] in support_types
        ),
        tuple(
            node["node_id"]
            for node in nodes
            if node["space_type"] not in {"core", "open_work", *support_types}
            and not (enforce_frontage and node["frontage_required"])
        ),
    )


if __name__ == "__main__":
    main()
