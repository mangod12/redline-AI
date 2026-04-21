async def select_responder(intent: str, severity: str) -> str:
    """Return responder category for MVP dispatch decisions."""
    if severity == "critical":
        if intent in {"fire", "gas_hazard"}:
            return "fire_dispatch"
        if intent in {"medical", "mental_health"}:
            return "ambulance"
        return "police_dispatch"

    if severity == "high":
        if intent in {"medical", "mental_health"}:
            return "ambulance"
        if intent in {"fire", "gas_hazard"}:
            return "fire_dispatch"
        return "police_dispatch"

    if severity == "medium":
        if intent == "medical":
            return "ambulance"
        return "general_responder"

    return "call_center_followup"
