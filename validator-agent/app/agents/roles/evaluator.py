import os
import yaml
from typing import List, Dict
from app.agents.factory import create_agent_from_config
from flask import current_app


class Evaluator:
    def __init__(self):
        self.config_path = current_app.config.get("CONFIG_PATH", "/config/validator_agent.yaml")

        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config path not found: {self.config_path}")

        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f)

        # Instancia l'agent segons la configuració YAML
        self.agent = create_agent_from_config(self.config)
        self.debug_mode = current_app.config.get("DEBUG", False)


    def evaluate(self, worker_outputs: List[Dict], context_id: str) -> Dict:
        """
        Construeix el prompt a partir dels resultats dels treballadors i
        executa el rol EVA per obtenir una avaluació final.
        TODO: fer servir prompt templates com OpenAIAgent
        """
        
        # 1. Generar context per a l'evaluator
        prompt = "=== Validations from Workers ===\n"
        for res in worker_outputs:
            role = res.get("role", "UNKNOWN")
            status = res.get("status", "undefined").upper()
            prompt += f"\n[{role}] → STATUS: {status}\n"

            if "text" in res:
                prompt += f"TEXT:\n{res['text']}\n"
            if "reason" in res:
                prompt += f"REASON:\n{res['reason']}\n"
            if "recommendations" in res:
                prompt += "RECOMMENDATIONS\n" + "\n".join(res["recommendations"]) + "\n"

        # 2. Buscar el rol EVA del YAML
        eva_roles = [role for role in self.config["roles"] if "EVA" in role]
        if not eva_roles:
            raise ValueError("No EVA role found in configuration.")

        # 3. Executar l'agent només amb EVA
        eva_key = next(iter(eva_roles[0].keys()))
            
        eva_result = self.agent.run(prompt, context_id, only_roles=[{eva_key: self.agent.roles_by_key[eva_key]}])
        return eva_result[0]  # Només hi ha un resultat esperat per EVA