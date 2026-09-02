"""验证 _call_llm_stream 修复：reasoning_content 应推送为 thinking 事件。"""
import sys
sys.path.insert(0, "/app")

import asyncio
import time
from app.database import SessionLocal
from app.models.agent import Agent
from app.models.user import User
from app.agent.hermes.executor import HermesAgentExecutor

db = SessionLocal()
agent = db.query(Agent).filter(Agent.id == 5).first()
user = db.query(User).first()

print(f"Agent: {agent.name} (id={agent.id})")
print(f"User: {user.username} (id={user.id})")

executor = HermesAgentExecutor(db, agent, user)

thinking_count = 0
token_count = 0
first_event_time = None
start_time = time.time()

async def run():
    global thinking_count, token_count, first_event_time
    async for event in executor.run("1.1.1.1 的归属地是哪里？", session_id="test-fix"):
        etype = event.get("type", "")
        if first_event_time is None and etype in ("thinking", "token"):
            first_event_time = time.time()
            elapsed = first_event_time - start_time
            print(f"  首个输出事件: {etype}, 耗时 {elapsed:.2f}s")

        if etype == "thinking":
            thinking_count += 1
            if thinking_count <= 3:
                content = event.get("content", "")[:60]
                print(f"  [thinking #{thinking_count}] {content}")
        elif etype == "token":
            token_count += 1
            if token_count <= 5:
                content = event.get("content", "")[:60]
                print(f"  [token #{token_count}] {content}")
        elif etype == "tool_start":
            print(f"  [tool_start] {event.get('tool_name', '')}")
        elif etype == "tool_end":
            print(f"  [tool_end] {event.get('tool_name', '')}")
        elif etype == "done":
            print(f"  [done] content={repr(event.get('content', '')[:80])}")
        elif etype == "error":
            print(f"  [error] {event.get('message', '')}")
            break
        elif etype == "start":
            print(f"  [start] {event.get('message', '')}")

asyncio.run(run())

total_time = time.time() - start_time
print(f"\n=== 统计 ===")
print(f"总耗时: {total_time:.2f}s")
print(f"thinking 事件数: {thinking