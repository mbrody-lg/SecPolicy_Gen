class MockPassiveGoalCreator:
    # No es modifica la proposta de prompt de l'usuari
    def execute(self, input_prompt: str) -> str:
        return input_prompt