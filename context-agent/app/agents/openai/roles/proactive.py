from app.agents.openai.client import OpenAIClient

class ProactiveGoalCreator(OpenAIClient):
    def execute(self, input_prompt: str) -> str:
        instructions = """
        Improve this objective to make it more effective in generating security context. 
        Enumerate which technical requirements must needed to secure this type of SME's.
        Enumerate which legal requirements must comply the company based on their operational context.
        - Once you have all the answers to the initial questionnaire, develop the policy strictly following the **Recommended Structure**:
        1. Introduction
        2. Scope
        2. General Objectives
        3. Risk Analysis
        4. Policy Development (with detailed sections)
        5. Technology Integration
        6. Employee Training
        7. Regulatory Compliance and Regulation
        8. Cost Management
        9. Continuous Improvement
        - Maintain a formal and structured tone.
        - Make sure to include specific examples (free tools, step-by-step procedures) adapted to the size of an SME.
        - Use subsections and lists to facilitate reading and practical application.
        - End with a **Expected Results** section and a brief **Conclusion**.
        """
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_prompt}
            ]
        )
        return response.choices[0].message.content.strip()