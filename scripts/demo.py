"""End-to-end demo over real MCP (stdio): plays the tool calls an AI agent makes for
"Is water damage from a burst pipe covered under Sarah Thompson's home policy, and what's the excess?"
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


def show(title: str, result) -> dict:
    data = json.loads(result.content[0].text)
    print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2)[:3500])
    return data


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "policy_assistant.server"], cwd=str(ROOT))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print("Tools:", ", ".join(t.name for t in tools.tools))

        client = show("get_client_policies", await session.call_tool(
            "get_client_policies", {"client": "Sarah Thompson"}))
        policy_id = next(p["policy_id"] for p in client["policies"] if p["status"] == "active")

        triage = show("check_claim_eligibility", await session.call_tool("check_claim_eligibility", {
            "policy_id": policy_id,
            "claim_description": "A pipe burst under the kitchen sink last night and flooded the kitchen "
                                 "floor and damaged the units. Client's mobile is 07700 900123.",
        }))

        show("search_policy_wording", await session.call_tool("search_policy_wording", {
            "query": "escape of water excess", "insurer_or_doc_id": "RIAS", "top_k": 3}))

        show("compare_coverage", await session.call_tool("compare_coverage", {
            "policy_a": policy_id, "policy_b": "esure", "topics": ["escape of water / burst pipes"]}))

        clause = next(c for c in triage["relevant_clauses"] if c["purpose"] == "cover")
        excess = triage["excess"]["total_excess_gbp"]
        show("draft_client_email", await session.call_tool("draft_client_email", {
            "client_id": client["client"]["client_id"],
            "policy_id": policy_id,
            "subject": "Your burst pipe - what your home policy covers",
            "body": "Dear {client_first_name},\n\nSorry to hear about the burst pipe. Your RIAS policy covers "
                    f"water leaking from fixed domestic water installations {clause['citation']}. "
                    f"The escape of water excess on your schedule is £{excess}, so you would pay the first "
                    f"£{excess} of the claim. Repairs to the pipe itself are not covered.\n\n"
                    "Please send photos of the damage and we will notify the insurer.\n\nKind regards,\nYour broker",
        }))


if __name__ == "__main__":
    asyncio.run(main())
