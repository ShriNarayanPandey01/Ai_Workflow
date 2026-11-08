from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ai_workflow.contracts.nodes.catalog_loader import load_catalog_manifests
from ai_workflow.contracts.nodes.manifest import DefaultBinding, NodeManifest
from ai_workflow.nodes.base import NodeExecutor
from ai_workflow.tasks.base import DurableTaskExecutor


class RegistryError(Exception):
    """Base class for registry validation failures."""


class DuplicateRegistrationError(RegistryError):
    """Two executors claim the same node type."""


class OrphanExecutorError(RegistryError):
    """An executor was registered without a catalog manifest."""


class MissingExecutorError(RegistryError):
    """A catalog node has no registered executor."""


class WrongExecutorKindError(RegistryError):
    """Executor kind does not match manifest execution_mode."""


@dataclass(frozen=True, slots=True)
class NodeRegistration:
    """A catalog-backed inline node executor registration."""

    node_type: str
    manifest: NodeManifest
    executor_factory: Callable[[], NodeExecutor]
    default_bindings_by_port: dict[str, list[DefaultBinding]]


@dataclass(frozen=True, slots=True)
class TaskRegistration:
    """A catalog-backed durable task executor registration."""

    task_type: str
    manifest: NodeManifest
    executor_factory: Callable[[], DurableTaskExecutor]
    default_bindings_by_port: dict[str, list[DefaultBinding]]


class RuntimeRegistry:
    """Registers node and task executors against the contracts catalog."""

    def __init__(self, *, contracts_root: Path) -> None:
        """Initialize an empty registry rooted at the contracts directory."""
        self._contracts_root = contracts_root
        self._catalog: dict[str, NodeManifest] = {}
        self._node_factories: dict[str, Callable[[], NodeExecutor]] = {}
        self._task_factories: dict[str, Callable[[], DurableTaskExecutor]] = {}
        self._nodes: dict[str, NodeRegistration] = {}
        self._tasks: dict[str, TaskRegistration] = {}

    @property
    def contracts_root(self) -> Path:
        """Return the contracts root used to load catalog manifests."""
        return self._contracts_root

    @property
    def catalog(self) -> dict[str, NodeManifest]:
        """Return a copy of the loaded catalog manifests keyed by node type."""
        return dict(self._catalog)

    @property
    def nodes(self) -> dict[str, NodeRegistration]:
        """Return a copy of registered inline node executors."""
        return dict(self._nodes)

    @property
    def tasks(self) -> dict[str, TaskRegistration]:
        """Return a copy of registered durable task executors."""
        return dict(self._tasks)

    def register_node(
        self,
        executor_factory: Callable[[], NodeExecutor],
        *,
        node_type: str,
    ) -> None:
        """Register an inline node executor factory for a catalog node type."""
        if node_type in self._node_factories or node_type in self._task_factories:
            msg = f"Duplicate registration for node type: {node_type}"
            raise DuplicateRegistrationError(msg)
        self._node_factories[node_type] = executor_factory

    def register_task(
        self,
        executor_factory: Callable[[], DurableTaskExecutor],
        *,
        task_type: str,
    ) -> None:
        """Register a durable task executor factory for a catalog node type."""
        if task_type in self._node_factories or task_type in self._task_factories:
            msg = f"Duplicate registration for task type: {task_type}"
            raise DuplicateRegistrationError(msg)
        self._task_factories[task_type] = executor_factory

    def build(
        self,
        *,
        strict_catalog: bool = False,
        catalog_dir: Path | None = None,
    ) -> RuntimeRegistry:
        """Validate registrations against the catalog and finalize the registry."""
        self._catalog = load_catalog_manifests(
            self._contracts_root,
            catalog_dir=catalog_dir,
        )
        self._nodes.clear()
        self._tasks.clear()

        for node_type, factory in self._node_factories.items():
            manifest = self._catalog.get(node_type)
            if manifest is None:
                msg = f"No catalog manifest for registered executor: {node_type}"
                raise OrphanExecutorError(msg)
            if manifest.is_durable_task():
                msg = f"Inline executor registered for durable-task node: {node_type}"
                raise WrongExecutorKindError(msg)
            self._nodes[node_type] = NodeRegistration(
                node_type=node_type,
                manifest=manifest,
                executor_factory=factory,
                default_bindings_by_port=manifest.default_bindings_by_port(),
            )

        for task_type, factory in self._task_factories.items():
            manifest = self._catalog.get(task_type)
            if manifest is None:
                msg = f"No catalog manifest for registered task executor: {task_type}"
                raise OrphanExecutorError(msg)
            if not manifest.is_durable_task():
                msg = f"Durable task executor registered for inline node: {task_type}"
                raise WrongExecutorKindError(msg)
            self._tasks[task_type] = TaskRegistration(
                task_type=task_type,
                manifest=manifest,
                executor_factory=factory,
                default_bindings_by_port=manifest.default_bindings_by_port(),
            )

        if strict_catalog:
            registered = set(self._nodes) | set(self._tasks)
            for node_type, manifest in self._catalog.items():
                if manifest.execution_owner != "execution-engine":
                    continue
                # Durable-task nodes are executed by task workers (F15/F16) and
                # may legitimately lack an inline executor while that subsystem
                # is unimplemented; only inline nodes must have an executor.
                if manifest.is_durable_task():
                    continue
                if node_type not in registered:
                    msg = f"No executor registered for catalog node: {node_type}"
                    raise MissingExecutorError(msg)

        return self

    def get_node(self, node_type: str) -> NodeRegistration:
        """Return the registration for an inline node type."""
        try:
            return self._nodes[node_type]
        except KeyError as exc:
            msg = f"Node executor not registered: {node_type}"
            raise KeyError(msg) from exc

    def get_task(self, task_type: str) -> TaskRegistration:
        """Return the registration for a durable task type."""
        try:
            return self._tasks[task_type]
        except KeyError as exc:
            msg = f"Task executor not registered: {task_type}"
            raise KeyError(msg) from exc


def build_runtime_registry(
    *,
    contracts_root: Path,
    strict_catalog: bool = False,
    catalog_dir: Path | None = None,
) -> RuntimeRegistry:
    """Create an empty registry and build it against the contracts catalog.
       Used by execution api
    """
    registry = RuntimeRegistry(contracts_root=contracts_root)
    return registry.build(strict_catalog=strict_catalog, catalog_dir=catalog_dir)
