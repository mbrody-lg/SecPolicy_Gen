import os
import yaml
from collections import Counter
from typing import List, Dict, Optional
from datetime import datetime, timezone
from flask import current_app
from app import mongo
from app.agents.factory import create_agent_from_config
from app.agents.roles.evaluator import Evaluator

class Coordinator:
    def __init__(self):
        self.config_path = current_app.config.get("CONFIG_PATH", "/config/validator_agent.yaml")

        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config path not found: {self.config_path}")

        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.agent = create_agent_from_config(self.config)
        self.validation_config = self.config.get("validation", {})
        self.max_rounds = self.validation_config.get("rounds", 3)
        self.consensus_threshold = self.validation_config.get("consensus_threshold", 2)
        self.vote_strategy = self.validation_config.get("vote_strategy", "majority")
        self.debug_mode = current_app.config.get("DEBUG", True)
        self.evaluator = Evaluator()

    def validate_policy(self, policy_input: dict) -> dict:
        from app.services.logic import send_policy_update_to_policy_agent  # importar funció auxiliar

        context_id = policy_input.get("context_id")
        original_prompt = policy_input.get("policy_text", "")
        prompt = policy_input.get("policy_text", "")
        language = policy_input.get("language", "en")
        version = policy_input.get("policy_agent_version", "0.1.0")
        generated_at = policy_input.get("generated_at", datetime.now(timezone.utc).isoformat())

        validation_roles = [
            role for role in self.agent.roles
            if list(role.keys())[0] != "EVA"
        ]

        rounds_done = 0
        all_rounds = []

        while rounds_done < self.max_rounds:
            rounds_done += 1
            round_results = self.agent.run(prompt, context_id, only_roles=validation_roles)
            
            print(f"[DEBUG] Round {rounds_done} - Results:")
            print(round_results)
            
            all_rounds.append(round_results)

            if self.debug_mode:
                print(f"\n[Round {rounds_done}] Results:")
                for res in round_results:
                    print(f"  · [{res['role']}] → {res['status']}")
                    if res['status'] != 'accepted':
                        print(f"    Reason: {res.get('reason')}")
                        print(f"    Recommendations: {res.get('recommendations')}")

            evaluator_feedback = self.evaluator.evaluate(round_results, context_id)
            decision = evaluator_feedback.get("status", "review")

            self.log_validation(
                context_id, round_results, decision, rounds_done, True,
                all_rounds=all_rounds, evaluator_result=evaluator_feedback
            )

            if decision == "accepted":
                return self.build_response("accepted", round_results, context_id, language, prompt, version, generated_at, evaluator_feedback)

            elif decision in ["rejected", "review"]:
                if self.debug_mode:
                    print(f"\n→ {decision.upper()} — enviant a policy-agent per revisió")

                update_response = send_policy_update_to_policy_agent(
                    context_id=context_id,
                    language=language,
                    policy_text=original_prompt,
                    policy_agent_version=version,
                    generated_at=generated_at,
                    status=decision,
                    reasons=[r.get("reason") for r in round_results if r["status"] == decision],
                    recommendations=[
                        rec for r in round_results if r["status"] == decision
                        for rec in r.get("recommendations", [])
                    ]
                )

                # Actualitzem la nova política rebuda
                prompt = update_response.get("policy_text", prompt)
                version = update_response.get("policy_agent_version", version)
                generated_at = update_response.get("generated_at", datetime.now(timezone.utc).isoformat())

        if self.debug_mode:
            print("\nNo consensus reached. Launching final vote...")

        last_round = all_rounds[-1]
        final_decision = self.vote(last_round)
        evaluator_feedback = self.run_evaluator(last_round, context_id)

        self.log_validation(
            context_id, last_round, final_decision, self.max_rounds, False,
            all_rounds=all_rounds, evaluator_result=evaluator_feedback
        )

        return self.build_response(final_decision, last_round, context_id, language, prompt, version, generated_at, evaluator_feedback)


    def format_response(self, decision: str, last_round_results: List[Dict]) -> Dict:
        response = {
            "status": decision,
            "reasons": [],
            "recommendations": []
        }

        if decision == "accepted":
            response["text"] = next(
                (res["text"] for res in last_round_results if "text" in res),
                None
            )
        else:
            for res in last_round_results:
                if res["status"] == decision:
                    response["reasons"].append(res.get("reason", ""))
                    response["recommendations"].extend(res.get("recommendations", []))

        return response

    def vote(self, results: List[Dict]) -> str:
        statuses = [r["status"] for r in results if r["role"] != "EVA"]
        counts = Counter(statuses)
        return counts.most_common(1)[0][0]

    def log_validation(
        self,
        context_id: str,
        results: List[Dict],
        decision: str,
        round_num: int,
        consensus: bool,
        all_rounds: List[List[Dict]] = None,
        evaluator_result: Optional[Dict] = None,
    ):
        try:
            log_data = {
                "context_id": context_id,
                "timestamp": datetime.now(timezone.utc),
                "round": round_num,
                "consensus_achieved": consensus,
                "final_decision": decision,
                "last_round_results": results,
                "config_used": {
                    "rounds": self.max_rounds,
                    "threshold": self.consensus_threshold,
                    "strategy": self.vote_strategy
                }
            }

            if all_rounds:
                log_data["all_rounds"] = all_rounds
            if evaluator_result:
                log_data["evaluator_result"] = evaluator_result

            mongo.db.validations.insert_one(log_data)

        except Exception as e:
            if self.debug_mode:
                print(f"[LOGGING ERROR] {str(e)}")
                
    def build_response(
        self,
        decision: str,
        round_results: List[Dict],
        context_id: str,
        language: str,
        policy_text: str,
        version: str,
        generated_at: str,
        evaluator_feedback: Dict
    ) -> Dict:
        response = {
            "context_id": context_id,
            "language": language,
            "policy_text": policy_text,
            "policy_agent_version": version,
            "generated_at": generated_at,
            "evaluator_analysis": evaluator_feedback,
            "status": decision,
            "reasons": [],
            "recommendations": []
        }

        if decision == "accepted":
            response["text"] = next(
                (res["text"] for res in round_results if "text" in res and res["status"] == "accepted"),
                None
            )
        else:
            for res in round_results:
                if res["status"] == decision:
                    response["reasons"].append(res.get("reason", ""))
                    response["recommendations"].extend(res.get("recommendations", []))

        return response
