"""Coordinator orchestration for multi-round validator decisions."""

import logging
import os
from collections import Counter
from datetime import datetime, timezone
from typing import List, Dict, Optional

import yaml
from flask import current_app

from app import mongo
from app.agents.factory import create_agent_from_config
from app.agents.roles.evaluator import Evaluator
from app.observability import build_log_event, log_event

logger = logging.getLogger(__name__)

class Coordinator:
    """Runs multi-round worker validation and final decision orchestration."""

    def __init__(self):
        """Load configuration and initialize agent/evaluator dependencies."""
        self.config_path = current_app.config.get("CONFIG_PATH", "/config/validator_agent.yaml")

        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config path not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.agent = create_agent_from_config(self.config)
        self.validation = self.config.get("validation", {})
        self.debug_mode = current_app.config.get("DEBUG", True)
        self.evaluator = Evaluator()

    @property
    def max_rounds(self) -> int:
        """Return maximum validation rounds configured for coordinator flow."""
        return self.validation.get("rounds", 3)

    @property
    def consensus_threshold(self) -> int:
        """Return minimum threshold used by consensus configuration."""
        return self.validation.get("consensus_threshold", 2)

    @property
    def vote_strategy(self) -> str:
        """Return vote strategy name configured for fallback decisions."""
        return self.validation.get("vote_strategy", "majority")

    def validate_policy(self, policy_input: dict) -> dict:
        """Run iterative validation rounds and produce final policy decision payload."""
        from app.services.logic import send_policy_update_to_policy_agent

        context_id = policy_input.get("context_id")
        correlation_id = policy_input.get("correlation_id") or context_id
        prompt = policy_input.get("policy_text", "")
        language = policy_input.get("language", "en")
        version = policy_input.get("policy_agent_version", "0.1.0")
        generated_at = policy_input.get("generated_at", datetime.now(timezone.utc).isoformat())
        retrieval_evidence = policy_input.get("retrieval_evidence", [])

        validation_roles = [
            role for role in self.agent.roles
            if list(role.keys())[0] != "EVA"
        ]

        rounds_done = 0
        all_rounds = []

        while rounds_done < self.max_rounds:
            rounds_done += 1
            log_event(
                logger,
                logging.INFO,
                event="validator.validation.round_started",
                stage="validation",
                context_id=context_id,
                correlation_id=correlation_id,
                round=rounds_done,
            )
            round_results = self.agent.run(prompt, context_id, only_roles=validation_roles)

            all_rounds.append(round_results)

            if self.debug_mode:
                status_counts = Counter(res["status"] for res in round_results)
                log_event(
                    logger,
                    logging.DEBUG,
                    event="validator.validation.round_results",
                    stage="validation",
                    context_id=context_id,
                    correlation_id=correlation_id,
                    round=rounds_done,
                    status_counts=dict(status_counts),
                )

            evaluator_feedback = self.evaluator.evaluate(round_results, context_id)
            decision = evaluator_feedback.get("status", "review")
            log_event(
                logger,
                logging.INFO,
                event="validator.validation.round_evaluated",
                stage="validation",
                context_id=context_id,
                correlation_id=correlation_id,
                round=rounds_done,
                decision=decision,
            )

            self.log_validation(
                context_id, round_results, decision, rounds_done, True,
                all_rounds=all_rounds, evaluator_result=evaluator_feedback,
                correlation_id=correlation_id, retrieval_evidence=retrieval_evidence
            )

            if decision == "accepted":
                return self.build_response(
                    "accepted", round_results, context_id, language, prompt, version,
                    generated_at, evaluator_feedback, retrieval_evidence=retrieval_evidence
                )

            if decision in ["rejected", "review"]:
                log_event(
                    logger,
                    logging.INFO,
                    event="validator.validation.revision_requested",
                    stage="policy_update",
                    context_id=context_id,
                    correlation_id=correlation_id,
                    round=rounds_done,
                    decision=decision,
                )

                reasons, recommendations = self.collect_feedback(round_results, decision)
                update_response = send_policy_update_to_policy_agent(
                    context_id=context_id,
                    language=language,
                    policy_text=prompt,
                    policy_agent_version=version,
                    generated_at=generated_at,
                    status=decision,
                    reasons=reasons,
                    recommendations=recommendations,
                )
                if update_response.get("success") is False:
                    return update_response
                update_response = self.validate_policy_update_response(update_response, context_id)

                # Update prompt with returned policy revision
                prompt = update_response.get("policy_text", prompt)
                version = update_response.get("policy_agent_version", version)
                generated_at = update_response.get("generated_at", datetime.now(timezone.utc).isoformat())

        log_event(
            logger,
            logging.INFO,
            event="validator.validation.final_vote_started",
            stage="validation",
            context_id=context_id,
            correlation_id=correlation_id,
            round=self.max_rounds,
        )

        last_round = all_rounds[-1]
        final_decision = self.vote(last_round)
        evaluator_feedback = self.evaluator.evaluate(last_round, context_id)

        self.log_validation(
            context_id, last_round, final_decision, self.max_rounds, False,
            all_rounds=all_rounds, evaluator_result=evaluator_feedback,
            correlation_id=correlation_id, retrieval_evidence=retrieval_evidence
        )

        return self.build_response(
            final_decision, last_round, context_id, language, prompt, version,
            generated_at, evaluator_feedback, retrieval_evidence=retrieval_evidence
        )


    def format_response(self, decision: str, last_round_results: List[Dict]) -> Dict:
        """Format simplified decision payload from a round result set."""
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

    def validate_policy_update_response(self, update_response: dict, context_id: str) -> dict:
        """Ensure the policy-agent update response is usable before another round starts."""
        if not isinstance(update_response, dict):
            raise RuntimeError("Policy update endpoint returned an invalid response object.")

        policy_text = update_response.get("policy_text")
        if not isinstance(policy_text, str) or not policy_text.strip():
            raise RuntimeError("Policy update endpoint did not return revised policy text.")

        response_context_id = update_response.get("context_id")
        if response_context_id is not None and str(response_context_id) != str(context_id):
            raise RuntimeError("Policy update endpoint returned a mismatched context_id.")

        generated_at = update_response.get("generated_at")
        if generated_at is not None and not isinstance(generated_at, str):
            raise RuntimeError("Policy update endpoint returned an invalid generated_at value.")

        policy_agent_version = update_response.get("policy_agent_version")
        if policy_agent_version is not None and not isinstance(policy_agent_version, str):
            raise RuntimeError("Policy update endpoint returned an invalid policy_agent_version value.")

        return update_response

    def collect_feedback(self, results: List[Dict], decision: str) -> tuple[list[str], list[str]]:
        """Normalize reason/recommendation fields from validator round outputs."""
        reasons = []
        recommendations = []

        for result in results:
            if result["status"] != decision:
                continue

            reason_value = result.get("reason") or result.get("reasons")
            if isinstance(reason_value, str) and reason_value.strip():
                reasons.append(reason_value.strip())

            for recommendation in result.get("recommendations", []):
                if isinstance(recommendation, str) and recommendation.strip():
                    recommendations.append(recommendation.strip())

        return reasons, recommendations

    def vote(self, results: List[Dict]) -> str:
        """Compute final fallback decision using majority status vote."""
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
        correlation_id: str | None = None,
        retrieval_evidence: Optional[List[Dict]] = None,
    ):
        """Persist validation trace and metadata in MongoDB."""
        try:
            log_data = {
                "context_id": context_id,
                "correlation_id": correlation_id or context_id,
                "timestamp": datetime.now(timezone.utc),
                "round": round_num,
                "consensus_achieved": consensus,
                "final_decision": decision,
                "last_round_results": results,
                "ownership": {
                    "owner_service": "validator-agent",
                    "source_of_truth": True,
                    "collection": "validations",
                },
                "policy_ref": {
                    "owner_service": "policy-agent",
                    "source_collection": "policies",
                    "context_id": context_id,
                },
                "retrieval_evidence_summary": self.summarize_retrieval_evidence(retrieval_evidence or []),
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

        except Exception:
            logger.exception(
                build_log_event(
                    event="validator.validation.persistence_failed",
                    stage="persistence",
                    context_id=context_id,
                )
            )
                
    def build_response(
        self,
        decision: str,
        round_results: List[Dict],
        context_id: str,
        language: str,
        policy_text: str,
        version: str,
        generated_at: str,
        evaluator_feedback: Dict,
        retrieval_evidence: Optional[List[Dict]] = None,
    ) -> Dict:
        """Build final API response payload for accepted/review/rejected outcomes."""
        response = {
            "context_id": context_id,
            "language": language,
            "policy_text": policy_text,
            "policy_agent_version": version,
            "generated_at": generated_at,
            "evaluator_analysis": evaluator_feedback,
            "status": decision,
            "reasons": [],
            "recommendations": [],
            "retrieval_evidence": retrieval_evidence or [],
        }

        if decision == "accepted":
            response["text"] = next(
                (res["text"] for res in round_results if "text" in res and res["status"] == "accepted"),
                None
            )
        else:
            response["reasons"], response["recommendations"] = self.collect_feedback(
                round_results,
                decision,
            )

        return response

    @staticmethod
    def summarize_retrieval_evidence(retrieval_evidence: List[Dict]) -> Dict:
        """Return non-sensitive evidence coverage metadata for validation persistence."""
        citations = []
        collections = []
        families = []
        for item in retrieval_evidence:
            citation = item.get("citation")
            if citation:
                citations.append(citation)
            collection = item.get("collection")
            if collection and collection not in collections:
                collections.append(collection)
            family = item.get("family")
            if family and family not in families:
                families.append(family)
        return {
            "count": len(retrieval_evidence),
            "citations": citations[:20],
            "collections": collections,
            "families": families,
        }
