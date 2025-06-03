import argparse
from app.agents.factory import create_agent_from_config

def main():
    parser = argparse.ArgumentParser(description="Run the Policy Agent with a context prompt.")
    parser.add_argument("prompt", type=str, help="Context prompt for generating policies.")
    parser.add_argument("--config", type=str, default="app/config/policy_agent.yaml", help="Path to the agent's YAML configuration file.")
    args = parser.parse_args()
    
    agent = create_agent_from_config(args.config)
    response = agent.run(args.prompt)
    print("\n Generated response:\n")
    print(response)

if __name__ == "__main__":
    main()

