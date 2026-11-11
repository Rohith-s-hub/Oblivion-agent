approved = True
result = None
_needs_approval, _reason = tier_needs_approval(tool_name, tool_args, self.session_state)

if _needs_approval:
    if cb.on_approve_tool:
        try:
            approved = await cb.on_approve_tool(tool_name, tool_args)
        except Exception:
            approved = False
        if not approved:
            result = f"Denied: {tool_name}"
    else:
        if _reason == "destructive":
            approved = False
            result = "Blocked destructive action."

t0 = time.perf_counter()
if approved and result is None:
    try:
        result = await asyncio.to_thread(dispatch, tool_name, tool_args)
    except Exception as e:
        result = f"Error running {tool_name}: {e}"
elif not approved and result is None:
    result = "User denied permission."