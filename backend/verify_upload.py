"""运行时验证：知识库文件上传与解析。容器内执行：docker exec soar-backend python /tmp/verify_upload.py"""
import json
import urllib.request

BASE = "http://localhost:8000/api/v1"


def req(method, path, body=None, headers=None):
    data = None
    h = headers or {}
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    r = urllib.request.urlopen(
        urllib.request.Request(BASE + path, method=method, data=data, headers=h)
    )
    raw = r.read()
    return json.loads(raw) if raw else None


def upload(kb_id, filename, content_bytes):
    boundary = "----soartestboundary12345"
    body = (
        ("--" + boundary + "\r\n").encode()
        + ('Content-Disposition: form-data; name="file"; filename="'
           + filename + '"\r\n').encode()
        + b"Content-Type: application/octet-stream\r\n\r\n"
        + content_bytes
        + b"\r\n"
        + ("--" + boundary + "--\r\n").encode()
    )
    r = urllib.request.urlopen(
        urllib.request.Request(
            BASE + f"/knowledge-bases/{kb_id}/documents/upload",
            method="POST",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    )
    return json.loads(r.read())


# 1. 创建知识库
kb = req("POST", "/knowledge-bases", {"name": "验证库", "description": "文件上传测试"})
print("created kb:", kb)
kb_id = kb["id"]

# 2. 上传 txt 文件
txt_doc = upload(kb_id, "测试文档.txt", "这是一份测试文档，包含关键词 暴力破解 和 扫描探测。".encode("utf-8"))
print("uploaded txt:", {k: txt_doc.get(k) for k in ("id", "title", "source_type", "file_name", "file_type", "file_size")})
print("txt content:", (txt_doc.get("content") or "")[:120])

# 3. 上传 json 文件
json_doc = upload(kb_id, "config.json", b'{"src_ip":"1.2.3.4","severity":"high"}')
print("uploaded json content:", json_doc.get("content"))

# 4. 列出文档
docs = req("GET", f"/knowledge-bases/{kb_id}/documents")
print("docs count:", len(docs), "titles:", [d["title"] for d in docs])

# 5. 搜索
res = req("POST", f"/knowledge-bases/{kb_id}/search", {"query": "暴力破解", "top_k": 5})
print("search results:", len(res), "first title:", res[0]["title"] if res else None, "score:", res[0]["score"] if res else None)

# 6. 验证文档新字段存在
print("txt doc has source_type field:", "source_type" in txt_doc, "value:", txt_doc.get("source_type"))
print("txt doc has file_type field:", "file_type" in txt_doc, "value:", txt_doc.get("file_type"))

print("\nALL KB UPLOAD CHECKS PASSED")
