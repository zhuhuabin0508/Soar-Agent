import asyncio

from sqlalchemy.dialects import postgresql

from app.agent.discovery_search import (
    classify_keyword,
    clamp_limit,
    execute_search_discovered_assets,
    resolve_resource_types,
    split_keywords,
)
from app.models.govcloud_asset import RESOURCE_MODELS


def test_classify_keyword_keeps_ip_exact():
    assert classify_keyword("10.1.2.3") == "ip"
    assert classify_keyword("10.0.0.0/24") == "cidr"
    assert classify_keyword("6899c279368a6c00016717f8") == "id"
    assert classify_keyword("财务部") == "text"
    assert classify_keyword("云") == "text"


def test_split_keywords_caps_batch():
    raw = ",".join(f"10.0.0.{i % 255}" for i in range(40))
    assert len(split_keywords(raw)) == 30
    assert split_keywords(" 10.0.0.1，10.0.0.2;10.0.0.3 ") == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


def test_clamp_limit():
    assert clamp_limit(0) == 1
    assert clamp_limit(100) == 20
    assert clamp_limit("bad") == 10


def test_resolve_resource_types():
    codes, error = resolve_resource_types("")
    assert error is None
    assert codes == ["cloud_host", "bare_metal", "e_government_network", "elastic_ip"]
    codes, error = resolve_resource_types("cloud_host")
    assert error is None and codes == ["cloud_host"]
    codes, error = resolve_resource_types("unknown")
    assert codes == []
    assert error["count"] == 0


def test_ip_filter_matches_excel_ip_field():
    model = RESOURCE_MODELS["cloud_host"]
    clause = model.extra_excel["IP"].astext == "10.224.168.57"
    sql = str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "extra_excel" in sql
    assert "10.224.168.57" in sql
    assert "LIKE" not in sql.upper()


def test_empty_keyword_does_not_query():
    result = asyncio.run(execute_search_discovered_assets(keyword="   "))
    assert result["count"] == 0
    assert result["assets"] == []
    assert "请提供" in result["error"]
