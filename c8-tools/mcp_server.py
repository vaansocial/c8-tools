"""Part 2: the same tool on the sheet's side, as an MCP server.  Run: python mcp_server.py
The steps are in README.md."""
import csv, io, socket, os
from typing import Annotated
import requests
from fastmcp import FastMCP
from supabase import Client, create_client

SHEET = "https://docs.google.com/spreadsheets/d/1Kg6T-dJWaYx_JCPiRk3u0nBuAQcsCVRDPj1NFKP4WzM/gviz/tq?tqx=out:csv&headers=0&gid=368290478"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

mcp = FastMCP("100x curriculum")

# Step 1 & 2. The function with its card (docstring and type hint)
@mcp.tool
def get_lecture(number: Annotated[int, "The lecture number, 1 to 19."]) -> dict:
    """returns: details of a lecture; when to use: when user is asking specifically about a class or lecture in 100xEngineers cohort"""
    for row in csv.reader(io.StringIO(requests.get(SHEET).text)):
        if row[1].startswith(f"{number}. "):
            return {"date": row[0], "title": row[1], "type": row[2], "tools": row[3]}
    return {"error": f"There is no lecture {number}. Lectures run from 1 to 19."}

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@mcp.tool
def list_concepts(query: Annotated[str | None, "Keyword to search within concept questions"] = None, 
                    limit: Annotated[int, "Maximum number of concepts to return"] = 5
                ) -> list[dict]:
    """Retrieve concepts from Supabase, optionally filtered by keyword."""
    builder = supabase.table("concepts").select("id, concept_question")
    
    if query:
        builder = builder.ilike("concept_question", f"%{query}%")
        
    response = builder.limit(limit).execute()
    return response.data

@mcp.tool
def get_cases_by_concept(concept_id: Annotated[str, "The UUID or ID of the concept"], 
                        limit: Annotated[int, "Maximum number of cases to return"] = 3
                        ) -> list[dict]:
    """Retrieve scenarios and cases for a specific concept ID."""
    response = (
        supabase.table("cases")
        .select("id, concept_id, case_scenario, case_answer")
        .eq("concept_id", concept_id)
        .limit(limit)
        .execute()
    )
    return response.data

# Any app can now reach it at http://localhost:8000/mcp
if __name__ == "__main__":
    if socket.socket().connect_ex(("127.0.0.1", 8000)) == 0:
        raise SystemExit("Port 8000 is already in use, probably by a server you started earlier. "
                         "Stop it with Ctrl+C in its terminal, or run: kill $(lsof -t -i:8000)")
    mcp.run(transport="http", port=8000)
