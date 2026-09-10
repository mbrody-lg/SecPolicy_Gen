from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT_DIR / "infrastructure" / "docker-compose.yml",
    ROOT_DIR / "infrastructure" / "docker-compose.local-oidc.yml",
)


def _images() -> dict[str, str]:
    images = {}
    for compose_file in COMPOSE_FILES:
        services = yaml.safe_load(compose_file.read_text(encoding="utf-8"))["services"]
        images.update(
            {name: service["image"] for name, service in services.items() if "image" in service}
        )
    return images


def test_compose_images_use_explicit_non_latest_tags():
    for service, image in _images().items():
        assert ":" in image, f"{service} image must use an explicit tag"
        assert not image.endswith(":latest"), f"{service} image must not use latest"


def test_supported_container_baselines_are_enforced():
    images = _images()

    assert images["mongo"].startswith("mongo:8.")
    assert images["chroma"].startswith("chromadb/chroma:1.")
    assert images["prometheus"].startswith("prom/prometheus:v3.")
    assert images["alloy"].startswith("grafana/alloy:v1.")
    assert "promtail" not in images
