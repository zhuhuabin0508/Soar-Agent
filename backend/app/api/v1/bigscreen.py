import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.system_config import DEFAULT_CONFIGS
from app.database import get_db
from app.dependencies import require_permission
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

_CFG_SUFFIXES = (
    "base_url",
    "path",
    "code",
    "appid",
    "username",
    "password",
    "usergroupid",
)


def _cfg_keys(prefix: str) -> tuple[str, ...]:
    return tuple(f"{prefix}.{s}" for s in _CFG_SUFFIXES)


def _load_cfg(db: Session, prefix: str) -> dict[str, str]:
    keys = _cfg_keys(prefix)
    cfg = {
        key: str((DEFAULT_CONFIGS.get(key) or {}).get("value") or "").strip()
        for key in keys
    }
    rows = (
        db.query(SystemConfig)
        .filter(SystemConfig.key.in_(keys))
        .all()
    )
    for r in rows:
        cfg[r.key] = (r.value or "").strip()
    return cfg


def _post_json(client: httpx.Client, url: str, payload: dict, label: str) -> dict:
    resp = client.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail=f"{label} 接口返回格式异常")
    return data


def _build_embed_url(db: Session, prefix: str, label: str) -> dict:
    cfg = _load_cfg(db, prefix)
    base_url = cfg.get(f"{prefix}.base_url", "").rstrip("/")
    path = cfg.get(f"{prefix}.path") or "/city/#/bigscreen"
    if not path.startswith("/"):
        path = "/" + path
    code = cfg.get(f"{prefix}.code", "")
    appid = cfg.get(f"{prefix}.appid", "")
    username = cfg.get(f"{prefix}.username", "")
    password = cfg.get(f"{prefix}.password", "")
    usergroupid = cfg.get(f"{prefix}.usergroupid") or "0"

    if not base_url:
        raise HTTPException(status_code=400, detail=f"请先在系统设置中配置{label} 平台基址")
    if not code or not appid:
        raise HTTPException(status_code=400, detail=f"请先在系统设置中配置{label} 的 code 与 appid")
    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail=f"请在系统设置 → 大屏2 · 深治慧 CIM 填写「免登账号」和「免登密码」。code / appid 是对方大屏编号，不要把登录账号密码填到这两项里",
        )

    encrypt_url = f"{base_url}/cim/sys/encryptStr"
    login_url = f"{base_url}/cim/sys/mLogin"
    encrypted = ""
    user_id = ""

    try:
        with httpx.Client(timeout=15) as client:
            enc = _post_json(client, encrypt_url, {"str": password, "encryptType": "0"}, label)
            result = enc.get("result") if isinstance(enc.get("result"), dict) else {}
            encrypted = str(result.get("encryptedStr") or "")
            if not enc.get("success") or not encrypted:
                logger.warning("%s 密码加密失败: code=%s message=%s", label, enc.get("code"), enc.get("message"))
                raise HTTPException(status_code=502, detail=enc.get("message") or f"{label} 密码加密失败")

            login = _post_json(
                client,
                login_url,
                {"username": username, "password": encrypted},
                label,
            )
            login_result = login.get("result") if isinstance(login.get("result"), dict) else {}
            token = str(login_result.get("token") or "")
            user_info = login_result.get("userInfo") if isinstance(login_result.get("userInfo"), dict) else {}
            user_id = str(user_info.get("id") or "")
            if not login.get("success") or not token:
                logger.warning("%s 换票失败: code=%s message=%s", label, login.get("code"), login.get("message"))
                raise HTTPException(status_code=502, detail=login.get("message") or f"{label} 登录换票失败")
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        logger.warning("%s 网络请求失败: %s", label, exc)
        raise HTTPException(status_code=502, detail=f"{label} 服务暂时不可用") from exc

    query = {
        "code": code,
        "appid": appid,
        "username": username,
        "password": encrypted,
        "usergroupid": usergroupid,
    }
    if user_id:
        query["userId"] = user_id
    return {"url": f"{base_url}{path}?{urlencode(query)}"}


router = APIRouter(prefix="/bigscreen", tags=["bigscreen"])
router2 = APIRouter(
    prefix="/bigscreen2",
    tags=["bigscreen"],
    dependencies=[Depends(require_permission("bigscreen2", "view"))],
)


def _cfg_value(db: Session, key: str) -> str:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row and (row.value or "").strip():
        return (row.value or "").strip()
    return str((DEFAULT_CONFIGS.get(key) or {}).get("value") or "").strip()


def _attach_bdv(embed: str, token: str, refresh: str, username: str) -> str:
    if "#" in embed:
        main, frag = embed.split("#", 1)
    else:
        main, frag = embed, "/Attack/"
    if not frag:
        frag = "/Attack/"
    if not frag.startswith("/"):
        frag = "/" + frag
    parsed = urlparse(main)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["bdv_token"] = token
    query["bdv_refresh"] = refresh
    query["bdv_username"] = username
    main = urlunparse(parsed._replace(query=urlencode(query)))
    return f"{main}#{frag}"


@router.get("/embed-url")
def get_yunfang_embed_url(
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("bigscreen", "view")),
) -> dict:
    embed = _cfg_value(db, "yunfang.embed_url")
    username = _cfg_value(db, "yunfang.username")
    password = _cfg_value(db, "yunfang.password")
    if not embed:
        raise HTTPException(status_code=400, detail="请在系统设置 → 大屏1 · 云防御 填写嵌入地址")
    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail="请在系统设置 → 大屏1 · 云防御 填写免登账号和免登密码",
        )
    parsed = urlparse(embed)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="大屏1 嵌入地址无效")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    login_url = f"{origin}/api/v1/account/login/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Origin": origin,
        "Referer": f"{origin}/",
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=20, headers=headers) as client:
            resp = client.post(login_url, json={"username": username, "password": password})
            try:
                data = resp.json()
            except ValueError:
                data = None
    except httpx.TimeoutException as exc:
        logger.warning("大屏1 登录超时: %s", exc)
        raise HTTPException(status_code=502, detail="大屏1 登录超时") from exc
    except httpx.HTTPError as exc:
        logger.warning("大屏1 网络请求失败: %s", exc)
        raise HTTPException(status_code=502, detail="大屏1 服务暂时不可用") from exc
    if not isinstance(data, dict) or data.get("status") != "success":
        msg = data.get("message") if isinstance(data, dict) else None
        if isinstance(msg, dict):
            msg = next(iter(msg.values()), None)
        raise HTTPException(status_code=502, detail=str(msg or "大屏1 登录失败"))
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    token = str(payload.get("token") or "")
    refresh = str(payload.get("refresh") or "")
    login_user = str(payload.get("username") or username)
    if not token or not refresh:
        raise HTTPException(status_code=502, detail="大屏1 登录未返回有效凭证")
    return {"url": _attach_bdv(embed, token, refresh, login_user)}


@router2.get("/embed-url")
def get_cim_embed_url(db: Session = Depends(get_db)) -> dict:
    return _build_embed_url(db, "bigscreen", "大屏2")
