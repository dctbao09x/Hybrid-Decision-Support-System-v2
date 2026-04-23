from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class RuleDefinition:
    rule_id: str
    class_name: str
    group: str
    priority: int
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    extends: Optional[str] = None


@dataclass
class RuleGroup:
    name: str
    default_priority: int = 0
    enabled: bool = True
    rules: List[RuleDefinition] = field(default_factory=list)


@dataclass
class RuleSetConfig:
    version: str
    conflict_strategy: str
    groups: Dict[str, RuleGroup]
    conflict_groups: Dict[str, List[str]] = field(default_factory=dict)


DEFAULT_RULESET_PATH = Path(__file__).resolve().parent / "configs" / "ruleset_v1.yaml"
RULESET_REGISTRY_PATH = Path(__file__).resolve().parent / "configs" / "ruleset_registry.json"


class RuleConfigError(ValueError):
    pass


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore[import]
    except Exception as exc:  # pragma: no cover
        raise RuleConfigError(
            "PyYAML is required to load rule configs. Install with: pip install pyyaml"
        ) from exc

    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise RuleConfigError("ruleset config must be a mapping")

    return data


def _load_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import json  # type: ignore[import]
    except Exception as exc:  # pragma: no cover
        raise RuleConfigError("json is required to load ruleset registry") from exc

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def resolve_ruleset_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return path

    registry = _load_registry(RULESET_REGISTRY_PATH)
    active_path = registry.get("active_path")
    if isinstance(active_path, str) and active_path.strip():
        candidate = Path(active_path)
        if not candidate.is_absolute():
            candidate = RULESET_REGISTRY_PATH.parent / candidate
        return candidate

    return DEFAULT_RULESET_PATH


def _resolve_group_defaults(group_name: str, raw_group: Dict[str, Any]) -> RuleGroup:
    default_priority = int(raw_group.get("default_priority", 0))
    enabled = bool(raw_group.get("enabled", True))
    return RuleGroup(name=group_name, default_priority=default_priority, enabled=enabled)


def _build_rule_definitions(group: RuleGroup, raw_group: Dict[str, Any]) -> List[RuleDefinition]:
    rules_raw = raw_group.get("rules", [])
    if not isinstance(rules_raw, list):
        raise RuleConfigError(f"rules for group {group.name} must be a list")

    definitions: List[RuleDefinition] = []
    for item in rules_raw:
        if not isinstance(item, dict):
            raise RuleConfigError(f"rule entry in {group.name} must be a dict")

        rule_id = str(item.get("id") or item.get("class") or "").strip()
        class_name = str(item.get("class") or "").strip()

        if not rule_id or not class_name:
            raise RuleConfigError(f"rule entry missing id/class in group {group.name}")

        priority = int(item.get("priority", group.default_priority))
        enabled = bool(item.get("enabled", group.enabled))
        tags = list(item.get("tags", [])) if item.get("tags") else []
        params = dict(item.get("params", {})) if item.get("params") else {}
        extends = item.get("extends")

        definitions.append(
            RuleDefinition(
                rule_id=rule_id,
                class_name=class_name,
                group=group.name,
                priority=priority,
                enabled=enabled,
                tags=tags,
                params=params,
                extends=extends,
            )
        )

    return definitions


def _apply_inheritance(definitions: List[RuleDefinition]) -> List[RuleDefinition]:
    by_id = {d.rule_id: d for d in definitions}

    visited: Dict[str, bool] = {}
    visiting: Dict[str, bool] = {}

    def _visit(rule_id: str) -> None:
        if visiting.get(rule_id):
            raise RuleConfigError(f"circular inheritance detected at rule: {rule_id}")
        if visited.get(rule_id):
            return

        visiting[rule_id] = True
        rule = by_id.get(rule_id)
        if rule and rule.extends:
            base_id = rule.extends
            if base_id not in by_id:
                raise RuleConfigError(f"extends references unknown rule id: {base_id}")
            _visit(base_id)

        visiting.pop(rule_id, None)
        visited[rule_id] = True

    for rule in definitions:
        _visit(rule.rule_id)

    for rule in definitions:
        if not rule.extends:
            continue

        base = by_id.get(rule.extends)
        if not base:
            raise RuleConfigError(f"extends references unknown rule id: {rule.extends}")

        if rule.priority == 0:
            rule.priority = base.priority
        if not rule.tags:
            rule.tags = list(base.tags)

        inherited = dict(base.params)
        inherited.update(rule.params)
        rule.params = inherited

    return definitions


def _parse_conflict_groups(raw: Any) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    if not raw:
        return groups

    if isinstance(raw, dict):
        for name, values in raw.items():
            if isinstance(values, list):
                groups[str(name)] = [str(v) for v in values]
        return groups

    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", ""))
            flags = entry.get("flags", [])
            if name and isinstance(flags, list):
                groups[name] = [str(v) for v in flags]
        return groups

    return groups


def load_ruleset_config(path: Optional[Path] = None) -> RuleSetConfig:
    ruleset_path = resolve_ruleset_path(path)
    data = _load_yaml(ruleset_path)

    version = str(data.get("version", "unknown"))
    conflict_strategy = str(data.get("conflict_strategy", "ACCUMULATE")).upper()

    raw_groups = data.get("groups", {})
    if not isinstance(raw_groups, dict) or not raw_groups:
        raise RuleConfigError("ruleset config must contain groups")

    groups: Dict[str, RuleGroup] = {}

    for group_name, raw_group in raw_groups.items():
        if not isinstance(raw_group, dict):
            raise RuleConfigError(f"group {group_name} must be a mapping")

        group = _resolve_group_defaults(group_name, raw_group)
        definitions = _build_rule_definitions(group, raw_group)
        group.rules = definitions
        groups[group.name] = group

    # Apply inheritance across all groups
    all_defs: List[RuleDefinition] = []
    for group in groups.values():
        all_defs.extend(group.rules)

    _apply_inheritance(all_defs)

    conflict_groups = _parse_conflict_groups(data.get("conflict_groups"))

    return RuleSetConfig(
        version=version,
        conflict_strategy=conflict_strategy,
        groups=groups,
        conflict_groups=conflict_groups,
    )


def get_rule_catalog(path: Optional[Path] = None) -> Dict[str, List[str]]:
    ruleset = load_ruleset_config(path)
    catalog: Dict[str, List[str]] = {}

    for group_name, group in ruleset.groups.items():
        catalog[group_name] = [r.class_name for r in group.rules if r.enabled]

    return catalog
