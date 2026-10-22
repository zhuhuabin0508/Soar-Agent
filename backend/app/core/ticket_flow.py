"""工单流程模板结构校验与字段值校验助手。

被 ``ticket_flows.py``（发布前校验）与 ``tickets.py``（发起/流转时校验）共用。

流程模板 ``nodes`` JSON 结构约定::

    {
      "start_groups": [1, 2],      # 可发起工单的分组 ID
      "nodes": [
        {
          "key": "n_report",        # 流程内唯一标识（发起后不可改名）
          "name": "监测预警",        # 显示名
          "type": "task",           # task=处理节点 / end=结束节点
          "group_id": 1,            # 处理分组 ID（end 节点可为空）
          "fields": [               # 本节点需填写的字段（可为空数组）
            {"key": "src_ip", "label": "源IP地址", "type": "ip",
             "required": true, "options": [], "placeholder": "",
             "default": "", "alert_field_mapping": "src_ip",
             "auto_enrich": true, "auto_agent": false}
            # auto_enrich：仅 ip 类型字段有效，控制发起时资产匹配 +
            # 威胁情报查询，默认 true（开启）
            # auto_agent：仅 ip 类型字段有效，控制发起时智能体研判
            #（IP 风险研判与封禁决策智能体），默认 false（关闭）
          ],
          "routes": [              # 流转路由（按序匹配，when=null 为默认路由）
            {"to": "n_judge", "label": "流转研判", "when": null},
            {"to": "end", "label": "结束", "when": {"field": "x", "op": "eq", "value": "是"}}
          ]
        },
        {"key": "end", "name": "结束", "type": "end", "fields": [], "routes": []}
      ]
    }

字段类型：text/textarea/number/datetime/select/switch/ip/url/file。
    条件操作符：eq / ne（switch 字段布尔值统一按 是/否 匹配）。
    节点超时提醒（阶段2）：
    - ``timeout_minutes``：节点停留超时阈值（分钟），空 = 不提醒
    - ``remind_interval_minutes``：超时期间重复提醒间隔（分钟），空或 0 = 仅首次提醒
    """
import re
from typing import Any, Callable, Optional

# 合法字段类型
FIELD_TYPES = {"text", "textarea", "number", "datetime", "select", "switch", "ip", "url", "file"}

# IP 字段宽松校验（IPv4 / IPv6）
_IP_RE = re.compile(
    r"^(?:(?:\d{1,3}\.){3}\d{1,3})$"          # IPv4
    r"|(?:^[0-9a-fA-F:]{2,45}$)"              # IPv6（宽松）
)


def iter_nodes(nodes_json: Any) -> list[tuple[str, dict]]:
    """遍历 nodes JSON，返回 [(key, node)]；结构非法时返回空列表。"""
    if not isinstance(nodes_json, dict):
        return []
    nodes = nodes_json.get("nodes")
    if not isinstance(nodes, list):
        return []
    out: list[tuple[str, dict]] = []
    for n in nodes:
        if isinstance(n, dict) and n.get("key"):
            out.append((str(n["key"]), n))
    return out


def get_node(nodes_json: Any, key: str) -> Optional[dict]:
    """按键取节点定义。"""
    for k, n in iter_nodes(nodes_json):
        if k == key:
            return n
    return None


def get_start_node(nodes_json: Any) -> Optional[dict]:
    """取首个处理节点（非 end）作为发起节点。"""
    for _, n in iter_nodes(nodes_json):
        if n.get("type") != "end":
            return n
    return None


def is_end_node(node: Optional[dict]) -> bool:
    """是否为结束节点。"""
    return bool(node) and node.get("type") == "end"


def validate_flow_structure(
    nodes_json: Any,
    *,
    group_ok: Optional[Callable[[int], bool]] = None,
) -> list[str]:
    """发布前校验流程结构，返回错误列表（空=通过）。

    Args:
        nodes_json: 流程模板 nodes 字段（完整 JSON 对象）。
        group_ok: 分组存在性校验回调（存在且启用返回 True）。
    """
    errors: list[str] = []
    if not isinstance(nodes_json, dict):
        return ["流程结构必须为 JSON 对象"]
    nodes = nodes_json.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["节点列表不能为空"]

    keys: set[str] = set()
    non_end = 0
    for idx, n in enumerate(nodes):
        pos = f"第 {idx + 1} 个节点"
        if not isinstance(n, dict):
            errors.append(f"{pos}：结构非法")
            continue
        key = n.get("key")
        if not key or not str(key).strip():
            errors.append(f"{pos}：缺少节点标识（key）")
        elif str(key) in keys:
            errors.append(f"{pos}：节点标识 {key} 重复")
        else:
            keys.add(str(key))

        if n.get("type") == "end":
            continue
        non_end += 1
        name = n.get("name") or key
        if not n.get("name"):
            errors.append(f"{pos}：缺少节点名称")

        # 处理分组
        gid = n.get("group_id")
        if gid in (None, ""):
            errors.append(f"{pos}（{name}）：未绑定处理分组")
        elif group_ok is not None and not group_ok(gid):
            errors.append(f"{pos}（{name}）：处理分组不存在或已停用（ID={gid}）")

        # 节点超时提醒配置：为空或正整数；重复间隔需 ≥0 且依赖超时阈值
        tm = n.get("timeout_minutes")
        tm_set = tm not in (None, "")
        if tm_set and (isinstance(tm, bool) or not isinstance(tm, (int, float)) or tm <= 0):
            errors.append(f"{pos}（{name}）：超时提醒分钟数必须为正整数")
        rim = n.get("remind_interval_minutes")
        rim_set = rim not in (None, "")
        if rim_set and (isinstance(rim, bool) or not isinstance(rim, (int, float)) or rim < 0):
            errors.append(f"{pos}（{name}）：重复提醒间隔必须为不小于 0 的整数（分钟）")
        if rim_set and not tm_set:
            errors.append(f"{pos}（{name}）：配置了重复提醒间隔但未配置超时提醒分钟数")

        # 字段
        fields = n.get("fields")
        fkeys: set[str] = set()
        if fields in (None, []):
            fields = []
        if not isinstance(fields, list):
            errors.append(f"{pos}（{name}）：字段定义必须为数组")
        else:
            for f in fields:
                if not isinstance(f, dict):
                    errors.append(f"{pos}（{name}）：存在非法字段定义")
                    continue
                fkey = f.get("key")
                flabel = f.get("label") or fkey
                if not fkey or not str(fkey).strip():
                    errors.append(f"{pos}（{name}）：存在缺少标识（key）的字段")
                elif str(fkey) in fkeys:
                    errors.append(f"{pos}（{name}）：字段标识 {fkey} 重复")
                else:
                    fkeys.add(str(fkey))
                if not f.get("label"):
                    errors.append(f"{pos}（{name}）：字段 {fkey} 缺少显示名（label）")
                ftype = f.get("type") or "text"
                if ftype not in FIELD_TYPES:
                    errors.append(f"{pos}（{name}）：字段 {flabel} 类型 {ftype} 不合法")
                if ftype == "select" and not f.get("options"):
                    errors.append(f"{pos}（{name}）：字段 {flabel} 为下拉选择但未配置选项")

        # 路由
        routes = n.get("routes")
        if not isinstance(routes, list) or not routes:
            errors.append(f"{pos}（{name}）：至少需要一条流转路由")
        else:
            has_default = False
            for r in routes:
                if not isinstance(r, dict):
                    errors.append(f"{pos}（{name}）：存在非法路由定义")
                    continue
                to = r.get("to")
                if not to:
                    errors.append(f"{pos}（{name}）：路由缺少去向节点")
                when = r.get("when")
                if when is None:
                    if has_default:
                        errors.append(f"{pos}（{name}）：存在多条默认路由")
                    has_default = True
                elif not isinstance(when, dict) or not when.get("field"):
                    errors.append(f"{pos}（{name}）：条件路由缺少判断字段")

    if non_end == 0:
        errors.append("流程至少需要一个处理节点")

    # 第二轮：路由指向校验（需要全量 key 集合）
    for _, n in iter_nodes(nodes_json):
        if is_end_node(n):
            continue
        name = n.get("name") or n.get("key")
        for r in n.get("routes") or []:
            if isinstance(r, dict) and r.get("to") and r["to"] not in keys:
                errors.append(f"节点 {name} 的流转去向 {r['to']} 不存在")

    # 发起分组
    start_groups = nodes_json.get("start_groups")
    if not isinstance(start_groups, list) or not start_groups:
        errors.append("未配置可发起工单的分组")
    else:
        if group_ok is not None:
            for gid in start_groups:
                if not group_ok(gid):
                    errors.append(f"发起分组 {gid} 不存在或已停用")

    # 抄送配置（模板级全局，可选）：[{type: user|group, id, name}]
    cc_targets = nodes_json.get("cc_targets")
    if cc_targets not in (None, []):
        if not isinstance(cc_targets, list):
            errors.append("抄送配置必须为数组")
        else:
            for t in cc_targets:
                if not isinstance(t, dict) or t.get("type") not in ("user", "group"):
                    errors.append("抄送配置存在非法对象（type 仅支持 user/group）")
                    break
                if isinstance(t.get("id"), bool) or not isinstance(t.get("id"), int):
                    errors.append(f"抄送对象 {t.get('name') or t.get('id')} 的 ID 必须为整数")
                    break

    return errors


def _is_empty(v: Any) -> bool:
    """字段值是否为空（None / 空串 / 空白串）。"""
    return v is None or (isinstance(v, str) and not v.strip())


def validate_field_values(field_defs: Any, values: Any) -> list[str]:
    """按节点字段定义校验提交的字段值，返回错误列表（空=通过）。

    - 必填项不能为空
    - 拒绝未定义字段（防注入）
    - select 必须命中选项；number 必须可转数字；ip 做格式校验
    """
    if not isinstance(values, dict):
        return ["字段值必须为对象"]
    defs: dict[str, dict] = {}
    for f in field_defs or []:
        if isinstance(f, dict) and f.get("key"):
            defs[str(f["key"])] = f

    errors: list[str] = []
    for k in values:
        if k not in defs:
            errors.append(f"字段 {k} 未在当前节点定义，不允许提交")

    for key, f in defs.items():
        v = values.get(key)
        label = f.get("label") or key
        if _is_empty(v):
            if f.get("required"):
                errors.append(f"{label} 为必填项")
            continue
        ftype = f.get("type") or "text"
        if ftype == "select":
            opts = f.get("options") or []
            if str(v) not in [str(o) for o in opts]:
                errors.append(f"{label} 的值必须是可选项之一")
        elif ftype == "number":
            try:
                float(v)
            except (TypeError, ValueError):
                errors.append(f"{label} 必须为数字")
        elif ftype == "ip":
            if not _IP_RE.match(str(v)):
                errors.append(f"{label} 不是合法的 IP 地址")
    return errors


def _normalize_cond_value(v: Any) -> Any:
    """条件比较前归一化：布尔 → 是/否。"""
    if isinstance(v, bool):
        return "是" if v else "否"
    return v


def suggest_route(routes: Any, field_values: dict) -> tuple[Optional[str], Optional[str]]:
    """按条件评估路由建议。

    Returns:
        (条件命中建议的节点 key, 默认路由节点 key)
        - 建议 key：首条 when 条件命中的路由
        - 默认 key：首条 when=null 的路由（无则取首条路由）
    """
    suggested: Optional[str] = None
    default: Optional[str] = None
    first: Optional[str] = None
    for r in routes or []:
        if not isinstance(r, dict) or not r.get("to"):
            continue
        to = r["to"]
        if first is None:
            first = to
        when = r.get("when")
        if not when:
            if default is None:
                default = to
            continue
        actual = _normalize_cond_value(field_values.get(when.get("field")))
        expected = _normalize_cond_value(when.get("value"))
        op = when.get("op", "eq")
        matched = False
        if actual is not None:
            if op == "eq":
                matched = str(actual) == str(expected)
            elif op == "ne":
                matched = str(actual) != str(expected)
        if matched and suggested is None:
            suggested = to
    return suggested, (default if default is not None else first)
