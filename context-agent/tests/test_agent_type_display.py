from test_base import *
import importlib
from app import create_app

def test_agent_type_displayed(client):
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert "Agent:" in html
    assert "Mock" in html or "Openai" in html or "Claude" in html