"""测试当前两个 LLM 配置，查看 404 具体原因。"""
import sys
sys.path.insert(0, "/app")
import asyncio, httpx, json

async def test():
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30) as c:
        r = await c.post("/api/v1/auth/login", json={"username":"admin","password":"admin123"})
        token = r.json().get("access_token","")
        h = {"Authorization": f"Bearer {token}"}

        # 测试配置1
        print("="*60)
        print("配置1: GLM-5.2")
        r1 = await c.post("/api/v1/llm-configs/1/test", headers=h)
        d1 = r1.json()
        print(f"success: {d1.get('success')}")
        if d1.get("success"):
            print(f"✅ {d1.get('model')}: {d1.get('response','')[:50]}")
        else:
            print(f"❌ {d1.get('error','')[:300]}")

        # 测试配置2
        print("\n" + "="*60)
        print("配置2: Qwen/Qwen3-VL-Embedding-8B")
        r2 = await c.post("/api/v1/llm-configs/2/test", headers=h)
        d2 = r2.json()
        print(f"success: {d2.get('success')}")
        if d2.get("success"):
            print(f"✅ {d2.get('model')}")
        else:
            print(f"❌ {d2.get('error','')[:300]}")

        # 直接测试 SiliconFlow API
        print("\n" + "="*60)
        print("直接测试 SiliconFlow API")
        print("="*60)

        sf_key = "sk-torkvjjldmigioimijdyjhjhcbjruezervkicoouzmqjflur"

        # 测试 chat
        print("\n--- Chat: zai-org/GLM-5.2 ---")
        try:
            r = await c.post(
                "https://api.siliconflow.cn/v1/chat/completions",
                json={"model":"zai-org/GLM-5.2","messages":[{"role":"user","content":"hi"}],"max_tokens":5},
                headers={"Authorization":f"Bearer {sf_key}","Content-Type":"application/json"},
                timeout=15,
            )
            print(f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"失败: {e}")

        # 测试 embedding (标准)
        print("\n--- Embedding: Qwen/Qwen3-VL-Embedding-8B (标准 /embeddings) ---")
        try:
            r = await c.post(
                "https://api.siliconflow.cn/v1/embeddings",
                json={"model":"Qwen/Qwen3-VL-Embedding-8B","input":"测试"},
                headers={"Authorization":f"Bearer {sf_key}","Content-Type":"application/json"},
                timeout=15,
            )
            print(f"HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            print(f"失败: {e}")

        # 测试 embedding (BAAI/bge-m3 对比)
        print("\n--- Embedding: BAAI/bge-m3 (标准 /embeddings) ---")
        try:
            r = await c.post(
                "https://api.siliconflow.cn/v1/embeddings",
                json={"model":"BAAI/bge-m3","input":"测试"},
                headers={"Authorization":f"Bearer {sf_key}","Content-Type":"application/json"},
                timeout=15,
            )
            print(f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"失败: {e}")

asyncio.run(test())
