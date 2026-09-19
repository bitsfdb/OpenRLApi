from typing import Any
from pydantic import BaseModel, Field


class ProductResponse(BaseModel):
    id: int
    name: str
    Product: str | None = None
    category: str
    quality: str
    internal_name: str | None = None
    thumbnail_url: str | None = None
    translations: dict[str, str] | None = None

    model_config = {"extra": "allow"}


class ProductsMeta(BaseModel):
    returned: int
    total_filtered: int
    limit: int
    offset: int


class ProductsListResponse(BaseModel):
    meta: ProductsMeta
    products: list[ProductResponse]


class TitleResponse(BaseModel):
    id: str
    text: str
    category: str
    color: str | None = None
    glow: str | None = None
    translations: dict[str, str] | None = None

    model_config = {"extra": "allow"}


class TitlesMeta(BaseModel):
    returned: int
    total_filtered: int
    total_titles: int
    limit: int
    offset: int


class TitlesListResponse(BaseModel):
    meta: TitlesMeta
    titles: list[TitleResponse]
    categories: list[dict[str, Any]] | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    items_count: int
    titles_count: int
    languages_supported: int
