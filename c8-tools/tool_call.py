"""Part 1: your first tool call.  Run: python tool_call.py
The steps are in README.md. Each one adds a few lines to the bottom of this file."""
import csv, io, json, os, sys
import requests

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ---------- THE SHEET (given) ----------
# Plain code, no model: one lecture of the course sheet, looked up by its number.
SHEET = "https://docs.google.com/spreadsheets/d/1Kg6T-dJWaYx_JCPiRk3u0nBuAQcsCVRDPj1NFKP4WzM/gviz/tq?tqx=out:csv&headers=0&gid=368290478"

def get_lecture(number):
    for row in csv.reader(io.StringIO(requests.get(SHEET).text)):
        if row[1].startswith(f"{number}. "):
            return {"date": row[0], "title": row[1], "type": row[2], "tools": row[3]}
    return {"error": f"There is no lecture {number}. Lectures run from 1 to 19."}

# ---------- THE MODEL (given) ----------
# One message to Groq, one message back. Nothing is added that you do not send.
def ask_model(messages, tools=None):
    body = {"model": "openai/gpt-oss-120b", "messages": messages}
    if tools:
        body["tools"] = tools
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers={"Authorization": "Bearer " + GROQ_API_KEY}, json=body)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]

# ---------- YOUR SERVER (yours to write) ----------
# python tool_call.py                      asks the question below
# python tool_call.py "What is an API?"    asks your own
question = " ".join(sys.argv[1:]) or "When is Lecture 12 of 100xEngineers Cohort 8, and what is it about?"
messages = [{"role": "user", "content": question}]

# Step 2. The card: fill in the two empty strings.
card = {"type": "function", "function": {
    "name": "get_lecture",
    "description": "returns: details of a lecture; when to use: when user is asking specifically about a class or lecture in 100xEngineers cohort",                                                    # Use it when
    "parameters": {"type": "object",
                   "properties": {"number": {"type": "integer",
                                             "description": ""}},         # It needs
                   "required": ["number"]},
}}

reply = ask_model(messages, [card])                 # Step 2: send the card too
#print(json.dumps(reply, indent=2, ensure_ascii=False))

while reply.get("tool_calls"):# Step 3. Run the request the model wrote.
    args = reply.get("tool_calls", [{}])[0].get("function", {}).get("arguments", "{}")
    args = json.loads(args)
    if "number" not in args:
     raise ValueError("Model did not give us a number.")
    number = args["number"]
    lecture = get_lecture(number)
    print(lecture)

# Step 4. Hand the result back to the model and print its answer.
    messages.append(reply)
    messages.append({"role": "tool", "tool_call_id": reply["tool_calls"][0]["id"], "content": json.dumps(lecture)})
    reply = ask_model(messages, [card])
    
# Step 5. Turn steps 3 and 4 into a loop.
print(reply["content"])