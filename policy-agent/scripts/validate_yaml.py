import os
import glob
from app.agents.factory import create_agent_from_config

def validate_all_configs(config_dir="configs/"):
    yaml_files = glob.glob(os.path.join(config_dir, "*.yaml"))
    if not yaml_files:
        print("No YAML file found in the configs/ folder")
        return

    print(f"Validating {len(yaml_files)} YAML file(s)...\n")

    for yaml_file in yaml_files:
        try:
            agent = create_agent_from_config(yaml_file)
            print(f"{os.path.basename(yaml_file)} → Vàlid [{agent.__class__.__name__}]")
        except Exception as e:
            print(f"{os.path.basename(yaml_file)} → ERROR: {str(e)}")

if __name__ == "__main__":
    validate_all_configs()
