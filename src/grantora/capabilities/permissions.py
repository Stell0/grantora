DESCRIBE_PERMISSION = "capability.describe"

RISK_CLASS_PERMISSIONS = {
    "read_only": "capability.invoke.read_only",
    "draft": "capability.invoke.side_effect",
    "side_effect": "capability.invoke.side_effect",
    "destructive": "capability.invoke.destructive",
}


def invoke_permission_for_risk_class(risk_class: str) -> str | None:
    return RISK_CLASS_PERMISSIONS.get(risk_class)