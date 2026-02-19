# Contributing to Security Policy Generation System

We appreciate your interest in contributing! This guide explains how to participate in the project.

## Code of Conduct

Be respectful, inclusive, and professional in all interactions.

## How to Contribute

### Reporting Issues

1. Check if the issue already exists on the issues page
2. Provide a clear title and description
3. Include steps to reproduce the problem
4. Attach relevant logs or error messages
5. Specify your environment (OS, Python version, Docker version)

### Submitting Changes

1. **Fork the repository**
   ```bash
   git clone https://github.com/your-username/SecPolicy_Gen.git
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feat/your-feature-name
   # or for bug fixes: git checkout -b fix/your-bug-fix
   ```

3. **Make your changes**
   - Follow the existing code style
   - Add tests for new functionality
   - Update documentation if needed

4. **Run tests locally**
   ```bash
   make context-tests
   make policy-tests
   make validator-tests
   ```

5. **Commit with clear messages**
   ```bash
   git commit -m "feat: add new validation role for CIS Controls"
   git commit -m "fix: resolve MongoDB connection timeout"
   ```

6. **Push to your fork**
   ```bash
   git push origin feat/your-feature-name
   ```

7. **Open a Pull Request**
   - Use a descriptive title
   - Explain what your change does and why
   - Link any related issues
   - Ensure all tests pass

## Development Setup

### Local Development with Docker

```bash
# Start all services
make up

# Access a specific agent shell
make context-shell
make policy-shell
make validator-shell
```

### Local Development without Docker

```bash
# Install dependencies for each agent
cd context-agent
pip install -r requirements.txt
python run.py

# In another terminal
cd policy-agent
pip install -r requirements.txt
python run.py

# In another terminal
cd validator-agent
pip install -r requirements.txt
python run.py
```

## Code Style Guidelines

### Python
- Follow PEP 8
- Use type hints where applicable
- Write clear variable and function names
- Add docstrings to functions and classes

### YAML Configuration
- Use 2 spaces for indentation
- Keep structure consistent with existing files
- Add comments for complex configurations

### Commit Messages
- Use present tense: "add feature" not "added feature"
- Use imperative mood: "move cursor to..." not "moves cursor to..."
- Use lowercase for the subject line
- Limit to 50 characters for the subject
- Add detailed explanation after a blank line if needed

## Testing Guidelines

### Write Tests For:
- New features
- Bug fixes
- Critical functionality
- Edge cases

### Run Tests
```bash
# All tests for a specific agent
make context-tests
make policy-tests
make validator-tests

# Individual test file
pytest tests/test_specific_feature.py

# With coverage
pytest --cov
```

## Documentation Guidelines

### Update Documentation When:
- Adding new features
- Changing API endpoints
- Modifying configuration options
- Adding new configuration parameters

### Documentation Format
- Use clear, concise language
- Provide practical examples
- Include expected outputs
- Explain non-obvious behavior

## Pull Request Checklist

Before submitting a PR, ensure:

- [ ] Code follows project style guidelines
- [ ] All tests pass locally
- [ ] New tests are added for new functionality
- [ ] Documentation is updated
- [ ] No unnecessary files are included
- [ ] Commit messages are clear
- [ ] Branch is up to date with main

## Project Structure

```
SecPolicy_Gen/
├── context-agent/       # User interaction service
│   ├── app/
│   │   ├── agents/      # Agent implementations
│   │   ├── routes/      # API endpoints
│   │   ├── services/    # Business logic
│   │   └── templates/   # HTML templates
│   ├── tests/           # Test suite
│   └── run.py          # Application entry point
├── policy-agent/        # Policy generation service
│   ├── app/
│   ├── scripts/         # Utility scripts
│   └── tests/
├── validator-agent/     # Validation service
│   ├── app/
│   └── tests/
├── infrastructure/      # Docker configuration
└── data/               # Regulatory documents
```

## Adding a New AI Backend (Claude, Mistral, etc.)

### 1. Create Agent Directory
```bash
mkdir -p context-agent/app/agents/mistral
```

### 2. Implement Agent Files
```python
# context-agent/app/agents/mistral/client.py
class MistralClient:
    """Mistral API client implementation"""
    def __init__(self, api_key):
        # Initialize Mistral SDK
        pass

# context-agent/app/agents/mistral/agent.py
from app.agents.base import Agent

class MistralAgent(Agent):
    """Mistral-based agent"""
    def __init__(self, config):
        super().__init__(config)
        self.client = MistralClient(config['api_key'])
```

### 3. Implement Roles
Reuse or adapt role patterns from the roles/ directory.

### 4. Register in Factory
The factory auto-discovers agents from the `agents/<type>/` directory structure.

### 5. Update Configuration
```yaml
roles:
  - name: MyRole
    type: mistral
    model: mistral-medium
    instructions: "Your instructions here"
```

## Questions?

- Check the [README](README.md) for general information
- Review individual agent [READMEs](./context-agent/README.md)
- Open an issue for clarification

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

