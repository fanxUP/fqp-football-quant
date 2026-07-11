from typing import Any, Protocol


class ModuleContract(Protocol):
    module_code: str
    version: str

    def health_check(self) -> dict[str, Any]: ...

    def exposed_routes(self) -> list[str]: ...

    def scheduled_jobs(self) -> list[str]: ...

    def permissions(self) -> list[str]: ...
