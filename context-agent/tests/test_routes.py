from test_base import *

def test_dashboard_route(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b"Generated contexts" in response.data

def test_create_route_get(client):
    response = client.get('/create')
    assert response.status_code == 200
    assert b"Create a new context" in response.data
