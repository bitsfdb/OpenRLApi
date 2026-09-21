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
    body = res.json()
    assert body["status"] == "online"
    assert body["name"] == "OpenRLApi"


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["items_count"] > 0
    assert body["titles_count"] > 0
    assert body["languages_supported"] == 12


def test_items_version():
    res = client.get("/items.ver")
    assert res.status_code == 200
    assert len(res.text.strip()) > 5


def test_items_json_multilang():
    res_esn = client.get("/items.json?l=ESN")
    assert res_esn.status_code == 200
    catalog_esn = res_esn.json()
    goldstone_esn = next(i for i in catalog_esn["items"] if i.get("ID") == 358 or i.get("id") == 358)
    assert goldstone_esn["Product"] == "Venturina (Premio Alfa)"

    res_pl = client.get("/items.json?l=PL")
    assert res_pl.status_code == 200
    catalog_pl = res_pl.json()
    goldstone_pl = next(i for i in catalog_pl["items"] if i.get("ID") == 358 or i.get("id") == 358)
    assert goldstone_pl["Product"] == "(Nagroda za alfę) Awenturyn"

    res_int = client.get("/items.json")
    assert res_int.status_code == 200
    catalog_int = res_int.json()
    goldstone_int = next(i for i in catalog_int["items"] if i.get("ID") == 358 or i.get("id") == 358)
    assert goldstone_int["Product"] == "(Alpha Reward) Goldstone"


def test_products_endpoint():
    res = client.get("/v2/rl/products/358?l=ESN")
    assert res.status_code == 200
    product = res.json()
    assert product["name"] == "Venturina (Premio Alfa)"
    assert product["category"] == "Wheels"

    res_search = client.get("/v2/rl/products?search=Awenturyn&l=PL")
    assert res_search.status_code == 200
    products = res_search.json()["products"]
    assert any(p["id"] == 358 for p in products)
    assert products[0]["name"] == "(Nagroda za alfę) Awenturyn"


def test_titles_endpoint():
    res_esn = client.get("/v2/rl/titles/CRL_Analyst?l=ESN")
    assert res_esn.status_code == 200
    assert res_esn.json()["text"] == "Analista CRL"

    res_pl = client.get("/v2/rl/titles/CRL_Analyst?l=PL")
    assert res_pl.status_code == 200
    assert res_pl.json()["text"] == "Analityk CRL"

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
