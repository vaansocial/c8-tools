import os
import json
import requests
import gradio as gr
from supabase import create_client, Client
from pydantic import BaseModel, Field
from typing import Optional

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "openai/gpt-oss-120b"

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in environment.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def list_concepts(query: str | None = None, limit: int = 5) -> list[dict]:
    """Retrieve concepts from Supabase, optionally filtered by keyword."""
    builder = supabase.table("concepts").select("id, concept_question").limit(limit)
    
    if query:
        builder = builder.ilike("concept_question", f"%{query}%")
        
    response = builder.execute()
    return response.data

def get_cases_by_concept(concept_id: str, limit: int = 3) -> list[dict]:
    """Retrieve scenarios and cases for a specific concept ID."""
    response = (
        supabase.table("cases")
        .select("id, concept_id, case_scenario, case_answer")
        .eq("concept_id", concept_id)
        .limit(limit)
        .execute()
    )
    return response.data

# 1. Pydantic schemas for parameter validation & documentation
class ListConceptsArgs(BaseModel):
    query: Optional[str] = Field(
        default=None, 
        description="Optional keyword to search or filter concepts, e.g. 'API' or 'backend'."
    )
    limit: int = Field(
        default=5, 
        description="Maximum number of concepts to retrieve. Defaults to 5."
    )

class GetCasesByConceptArgs(BaseModel):
    concept_id: str = Field(
        description="The ID of the concept to fetch cases for, e.g. 'C01', 'C02'."
    )
    limit: int = Field(
        default=3, 
        description="Maximum number of cases to return. Defaults to 3."
    )

# 2. Tool definitions passed to Groq
tools = [
    {
        "type": "function",
        "function": {
            "name": "list_concepts",
            "description": "Retrieve or search for concepts in the knowledge base.",
            "parameters": ListConceptsArgs.model_json_schema()
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_cases_by_concept",
            "description": "Fetch scenario cases belonging to a specific concept ID.",
            "parameters": GetCasesByConceptArgs.model_json_schema()
        }
    }
]

# 3. Tool Dispatcher Registry
AVAILABLE_TOOLS = {
    "list_concepts": list_concepts,
    "get_cases_by_concept": get_cases_by_concept
}

def groq_chat_completion(messages: list, tools_list: list = None) -> dict:
    """Helper to send a raw HTTP POST request to Groq."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": messages
    }
    if tools_list:
        payload["tools"] = tools_list
        payload["tool_choice"] = "auto"

    r = requests.post(GROQ_URL, headers=headers, json=payload)
    if not r.ok:
        raise RuntimeError(f"Groq API error ({r.status_code}): {r.text}")
    return r.json()

def run_conversation(user_prompt: str):
    messages = [
        {
            "role": "system",
            "content": "You are a friendly study assistant. Use the provided tools to fetch real concepts and cases from the database when answering questions."
        },
        {"role": "user", "content": user_prompt}
    ]

    print(f"\n🗣️ User: {user_prompt}\n")

    # Turn 1: Manual HTTP POST to Groq (passing tools)
    response_data = groq_chat_completion(messages=messages, tools_list=tools)
    response_message = response_data["choices"][0]["message"]
    
    # Check if the LLM wants to call any tools
    tool_calls = response_message.get("tool_calls")

    if not tool_calls:
        # LLM answered directly without calling any tools
        reply = response_message.get("content")
        print(f"🤖 Assistant: {reply}")
        return reply

    # IMPORTANT: Append the assistant's message (which holds the tool call request) to history
    messages.append(response_message)

    # Execute each tool requested by the model
    for tool_call in tool_calls:
        function_name = tool_call["function"]["name"]
        function_args = json.loads(tool_call["function"]["arguments"])
        
        print(f"🔧 LLM requested tool: '{function_name}' with args: {function_args}")

        # Look up function in registry and execute
        function_to_call = AVAILABLE_TOOLS.get(function_name)
        if function_to_call:
            tool_output = function_to_call(**function_args)
        else:
            tool_output = {"error": f"Tool '{function_name}' not found."}

        print(f"📦 Tool returned {len(tool_output) if isinstance(tool_output, list) else 1} record(s)")

        # IMPORTANT: Append tool output back with role="tool" and the exact tool_call_id
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "name": function_name,
            "content": json.dumps(tool_output)
        })

    # Turn 2: Second HTTP POST with history + tool results
    second_response_data = groq_chat_completion(messages=messages)
    final_reply = second_response_data["choices"][0]["message"]["content"]
    print(f"\n🤖 Assistant: {final_reply}\n")
    return final_reply

def respond(message: str, history: list):
    # 1. System prompt + prior chat history
    messages = [
        {
            "role": "system",
            "content": "You are a friendly study assistant. Use the provided tools to fetch real concepts and cases from the database when answering questions."
        }
    ]
    
    # Format Gradio's history (supports both dict format and classic tuple format)
    for item in history:
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": str(content)})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            user_turn, bot_turn = item
            if user_turn:
                messages.append({"role": "user", "content": str(user_turn)})
            if bot_turn:
                messages.append({"role": "assistant", "content": str(bot_turn)})
        
    messages.append({"role": "user", "content": message})

    # 2. Agent Execution Loop (allow up to 5 steps of tool chaining)
    MAX_STEPS = 5
    for step in range(MAX_STEPS):
        response_data = groq_chat_completion(messages=messages, tools_list=tools)
        response_message = response_data["choices"][0]["message"]
        tool_calls = response_message.get("tool_calls")

        # Base condition: LLM didn't call any tools -> it produced the final answer!
        if not tool_calls:
            return response_message.get("content") or ""

        # Otherwise, the LLM requested tool(s)
        messages.append(response_message)

        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            function_args = json.loads(tool_call["function"]["arguments"])
            
            print(f"🔧 [Step {step + 1}] Tool invoked: {function_name}({function_args})")
            
            function_to_call = AVAILABLE_TOOLS.get(function_name)
            if function_to_call:
                tool_output = function_to_call(**function_args)
            else:
                tool_output = {"error": f"Tool '{function_name}' not found."}

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": function_name,
                "content": json.dumps(tool_output)
            })

    return "Reached maximum tool execution limit."

demo = gr.ChatInterface(
    fn=respond,
    title="📚 SumJ AI Assistant",
    description="Ask questions about your concepts and cases. Powered by Tool Calling + Supabase + Groq."
)

if __name__ == "__main__":
    demo.launch()