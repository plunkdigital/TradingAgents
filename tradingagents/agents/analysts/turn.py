"""One turn of a tool-using analyst, and its last turn once its tool rounds are spent."""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

WRAP_UP = (
    "You have used every tool round this report allows. Write your final report "
    "now from the tool results above, and say which data you could not retrieve."
)


def _missing_required_tool(required_tools, messages):
    """Only completed, non-error tool messages satisfy an optional requirement."""
    pending, completed = {}, set()
    for message in messages:
        if isinstance(message, AIMessage):
            pending.update({call["id"]: call["name"] for call in message.tool_calls})
        elif isinstance(message, ToolMessage) and message.status != "error":
            name = pending.pop(message.tool_call_id, None)
            if name is not None:
                completed.add(name)
    return next((name for name in required_tools if name not in completed), None)


def take_turn(prompt, llm, tools, messages, *, required_tools=()):
    """The analyst's reply and its report, which stays empty while it calls tools.

    Told to wrap up, it answers without tools: a model offered tools may call one
    whatever it is told. Its earlier calls and their results reach it as text,
    since a provider may refuse a history holding tool calls when none are bound.
    """
    if messages and isinstance(messages[-1], HumanMessage) and messages[-1].content == WRAP_UP:
        # The prompt lists the tools it offers; a model told of tools it cannot
        # call may still try, and some providers then answer with nothing.
        prompt = prompt.partial(tool_names="none; your tool rounds are spent")
        result = (prompt | llm).invoke(_as_text(messages))
        return result, result.content
    # Opt-in only. Let the model supply arguments, then let the existing ToolNode
    # execute and record the call. No synthetic tool results or extra source fetch.
    # A provider ignoring tool_choice may still finish early; downstream evidence
    # validation must withhold that report. The graph's round cap still applies.
    required = _missing_required_tool(required_tools, messages)
    bound = (llm.bind_tools([tool for tool in tools if tool.name == required], tool_choice=required)
             if required else llm.bind_tools(tools))
    result = (prompt | bound).invoke(messages)
    return result, "" if result.tool_calls else result.content


def _as_text(messages):
    """The history with its tool calls and tool results written out as plain messages."""
    written = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            said = message.content if isinstance(message.content, str) else ""
            calls = "; ".join(f"{c['name']}({json.dumps(c['args'], default=str)})" for c in message.tool_calls)
            written.append(AIMessage(content=f"{said}\n[Called {calls}]".strip()))
        elif isinstance(message, ToolMessage):
            written.append(HumanMessage(content=f"[{message.name or 'Tool'} returned]\n{message.content}"))
        else:
            written.append(message)
    return written
