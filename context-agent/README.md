# Context-Agent

## Project Description
**Context-Agent** is a Flask-based microservice designed to collect structured information (business context) from the user and generate a context prompt for later use by the other agents (Policy-Agent and Validator-Agent). It works as a question “wizard” that allows creating or continuing multiple independent context threads. All information for each context is saved in MongoDB, including the history of questions and answers, in order to be able to resume or reference contexts at any time.

### Main Objectives
1. Provide an interactive flow of questions so that the user can describe their business context (country, region, sector, assets, methodologies, needs, etc.).
2. Generate a context prompt with the collected information, applying patterns such as `PassiveGoalCreator`, `ProactiveGoalCreator` and `PromptResponseOptimiser` (according to Liu et al. 2024).
3. Save all question and answer history to MongoDB, allowing multiple threads of work (each identified by a `context_id`), in the future per user.
4. Expose endpoints to:
- Create a new context.
- Continue an already started context.
- Get the context and the generated prompt.
- List existing contexts with filters by status or date.
- (Optional) Delete contexts in `TESTING` mode.
5. Integrate with **Policy-Agent**: once the context prompt is ready.

### Prerequisites

1. Docker & Docker Compose (recommended).
2. Python 3.9+ (if running without Docker).
3. Environment variables (outside Docker, if running locally):

        OPENAI_API_KEY
        MONGO_URI (ex.: mongodb://mongodb:27017/context-agent-db)
        FLASK_SECRET_KEY
        FLASK_ENV: development or production.
        CONFIG_PATH (path to context-agent.yaml)

### Configuration

#### YAML file (context-agent.yaml)
Review the config/examples/ folder and use what you think is best, be careful! with CONFIG_PATH

- `questions`: Sequential list of questions to be asked to the user. Each entry has:

      id: unique identifier of the question (e.g. country, sector).
      question: text of the question to display.

- `roles`: Sequence of roles that are applied after collecting all the answers:

      name: descriptive name (PassiveGoalCreator, etc.).
      type: openai (or mock for testing environment).
      instructions: textual template with placeholders.
      model: name of the OpenAI model (e.g. gpt-4o).
      temperature: float (0.0–1.0).
      max_tokens: integer to limit the answer.

### Contribution

1. Create a “fork” of the project.
2. Clone your fork locally.
3. Create a dedicated branch (e.g. feat/new-role-evaluation).
4. Commit your changes and run all tests, if you create new features please include at least one test:
5. Open a “Pull Request” explaining the proposed feature or fix.

### License

This project is released under the MIT license. See the LICENSE file for more details.
