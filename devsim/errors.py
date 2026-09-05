class DevSimError(Exception):
    """Expected, user-facing DevSim failure."""

    code = "devsim_error"


class ConfigError(DevSimError):
    code = "config_error"


class SafetyError(DevSimError):
    code = "safety_error"


class AdapterError(DevSimError):
    code = "adapter_error"


class LifecycleError(DevSimError):
    code = "lifecycle_error"


class ScenarioError(DevSimError):
    code = "scenario_error"
