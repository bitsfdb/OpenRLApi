import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from openrlapi.main import app

client = TestClient(app)


def test_root():
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert data["name"] == "OpenRLApi"


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["items_count"] > 0
    assert data["titles_count"] > 0
    assert data["languages_supported"] == 12


def test_items_version():
    res = client.get("/items.ver")
    assert res.status_code == 200
    assert len(res.text.strip()) > 5


def test_items_json_multilang():
    # Spanish query
    res_esn = client.get("/items.json?l=ESN")
    assert res_esn.status_code == 200
    data_esn = res_esn.json()
    goldstone_esn = next(i for i in data_esn["items"] if i.get("ID") == 358 or i.get("id") == 358)
    assert goldstone_esn["Product"] == "Venturina (Premio Alfa)"

    # Polish query with l=PL alias
    res_pl = client.get("/items.json?l=PL")
    assert res_pl.status_code == 200
    data_pl = res_pl.json()
    goldstone_pl = next(i for i in data_pl["items"] if i.get("ID") == 358 or i.get("id") == 358)
    assert goldstone_pl["Product"] == "(Nagroda za alfę) Awenturyn"

    # Default English query
    res_int = client.get("/items.json")
    assert res_int.status_code == 200
    data_int = res_int.json()
    goldstone_int = next(i for i in data_int["items"] if i.get("ID") == 358 or i.get("id") == 358)
    assert goldstone_int["Product"] == "(Alpha Reward) Goldstone"


def test_products_endpoint():
    # Single product with l=ESN
    res = client.get("/v2/rl/products/358?l=ESN")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Venturina (Premio Alfa)"
    assert data["category"] == "Wheels"

    # Search in Polish
    res_search = client.get("/v2/rl/products?search=Awenturyn&l=PL")
    assert res_search.status_code == 200
    prods = res_search.json()["products"]
    assert any(p["id"] == 358 for p in prods)
    assert prods[0]["name"] == "(Nagroda za alfę) Awenturyn"


def test_titles_endpoint():
    # Spanish titles
    res_esn = client.get("/v2/rl/titles/CRL_Analyst?l=ESN")
    assert res_esn.status_code == 200
    assert res_esn.json()["text"] == "Analista CRL"

    # Polish titles
    res_pl = client.get("/v2/rl/titles/CRL_Analyst?l=PL")
    assert res_pl.status_code == 200
    assert res_pl.json()["text"] == "Analityk CRL"

    # Titles categories
    res_cats = client.get("/v2/rl/titles/categories")
    assert res_cats.status_code == 200
    assert res_cats.json()["category_count"] > 10


def test_categories_and_attributes():
    res_cats = client.get("/v2/rl/categories")
    assert res_cats.status_code == 200
    assert "Wheels" in res_cats.json()["categories"]

    res_attrs = client.get("/v2/rl/attributes")
    assert res_attrs.status_code == 200
    assert "Titanium White" in res_attrs.json()["paints"].values()
