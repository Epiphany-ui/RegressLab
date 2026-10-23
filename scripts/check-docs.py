#!/usr/bin/env python3
"""Check documentation, immutable research sources and draft schema boundaries.

This is documentation tooling, not a lab runner or a validator of real research
artifacts. All in-memory schema witnesses are explicitly synthetic.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".cache", ".venv", "node_modules", "dist", "var", "datasets", "checkpoints", "artifacts", "test-results", "playwright-report", "__pycache__", ".pytest_cache"}
SCHEMA_PATH = ROOT / "docs/engineering/v2/contracts/research-artifacts.schema.json"
MANIFEST_PATH = ROOT / "docs/research/v2/import-manifest.json"
results: list[dict] = []
warnings: list[dict] = []


def check(name, fn):
    try:
        detail = fn()
        results.append({"name": name, "status": "PASS", "detail": detail})
    except Exception as exc:
        results.append({"name": name, "status": "FAIL", "detail": str(exc)})


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def files(directory=ROOT):
    for child in sorted(directory.iterdir()):
        if child.name in EXCLUDED or child.is_symlink():
            continue
        if child.is_dir():
            yield from files(child)
        elif child.is_file():
            yield child


def load(path):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f"Duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Nonfinite JSON number: {value}")
        return number

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=nonfinite, parse_float=finite_float)


def pointer(document, ref):
    require(ref.startswith("#/"), f"Only local schema references are allowed: {ref}")
    value = document
    for part in ref[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


manifest = load(MANIFEST_PATH)
schema = load(SCHEMA_PATH)
fixture_sha = hashlib.sha256(b"synthetic-documentation-schema-witness-only").hexdigest()
fixture_uuid = "00000000-0000-4000-8000-000000000001"


def source_integrity():
    expected = {entry["path"] for entry in manifest["files"]}
    actual = {f"source/{p.name}" for p in (MANIFEST_PATH.parent / "source").iterdir() if p.is_file()}
    require(len(expected) == 8 and actual == expected, "Imported source file set differs from the supplied eight files")
    for entry in manifest["files"]:
        data = (MANIFEST_PATH.parent / entry["path"]).read_bytes()
        require(len(data) == entry["size_bytes"], f"Source size changed: {entry['path']}")
        require(hashlib.sha256(data).hexdigest() == entry["sha256"], f"Source bytes changed: {entry['path']}")
    return {"byte_identical_sources": len(expected)}


def local_links():
    missing_allowed = {(MANIFEST_PATH.parent / x["from"]).resolve(): (MANIFEST_PATH.parent / x["target"]).resolve() for x in manifest["known_missing_local_links"]}
    markdown_count = link_count = 0
    for path in files():
        if path.suffix != ".md":
            continue
        markdown_count += 1
        for match in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = match.group(1).strip()
            if target.startswith("<"):
                target = target[1:target.index(">")]
            else:
                target = re.split(r'\s+[\"\']', target, maxsplit=1)[0]
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve()
            link_count += 1
            if destination.exists():
                continue
            if missing_allowed.get(path.resolve()) == destination:
                warnings.append({"code": "SOURCE_ATTACHMENT_NOT_SUPPLIED", "source": str(path.relative_to(ROOT)), "target": target})
            else:
                raise AssertionError(f"Broken local link: {path.relative_to(ROOT)} -> {target}")
    require(len(warnings) == 1, "Expected exactly the recorded missing source Word attachment warning")
    return {"markdown_files": markdown_count, "local_links": link_count, "known_missing_attachments": len(warnings)}


def json_and_refs():
    count = 0
    for path in files():
        if path.suffix != ".json":
            continue
        doc = load(path)
        count += 1
        for node in walk(doc):
            if "$ref" in node:
                pointer(doc, node["$ref"])
    return {"json_files": count, "all_references": "local_and_resolved"}


def schema_meta():
    Draft202012Validator.check_schema(schema)
    return {"standard": "JSON Schema 2020-12", "definitions": len(schema["$defs"]), "top_level_artifact_kinds": len(schema["oneOf"])}


def validator(definition):
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"}, format_checker=FormatChecker())


def witness(node, definition=None):
    """Generate a shape witness, never a genuine dataset, model or run claim."""
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return witness(pointer(schema, node["$ref"]), name)
    if "const" in node:
        return copy.deepcopy(node["const"])
    if "enum" in node:
        return copy.deepcopy(node["enum"][0])
    if "anyOf" in node or "oneOf" in node:
        return witness((node.get("anyOf") or node["oneOf"])[0])
    kind = node.get("type")
    if kind == "object":
        value = {key: witness(node["properties"][key]) for key in node.get("required", [])}
        if "fixture" in value:
            value["fixture"] = True
        if definition == "HgcConfiguration":
            value["lambda"] = 0.5
            value["k"] = 3
        if definition == "StudyRegistration":
            value["parent_core_freeze_sha256"] = None
        if definition == "FreezeMatrix":
            value["parent_core_freeze_sha256"] = None
        if definition == "EvaluationResult":
            value["parent_core_freeze_sha256"] = None
        return value
    if kind == "array":
        length = node.get("minItems", 0)
        values = [witness((node.get("prefixItems") or [])[i] if i < len(node.get("prefixItems", [])) else node.get("items", {})) for i in range(length)]
        if node.get("uniqueItems"):
            for i in range(1, len(values)):
                if values[i] in values[:i]:
                    values[i] = f"fixture-{i}" if isinstance(values[i], str) else i
        return values
    if kind == "string":
        if node.get("format") == "uuid":
            return fixture_uuid
        if node.get("format") == "date-time":
            return "2026-10-23T00:00:00Z"
        pattern = node.get("pattern", "")
        if definition == "SHA256" or "[0-9a-f]{64}" in pattern and not any(prefix in pattern for prefix in ["si:", "sg:", "cell-"]):
            return fixture_sha
        if definition in {"SourceI", "SourceGroupI", "CellId"}:
            return {"SourceI": "si:", "SourceGroupI": "sg:", "CellId": "cell-"}[definition] + fixture_sha
        if "[0-9a-f]{40" in pattern:
            return fixture_sha[:40]
        if node.get("format") in {"uri", "uri-reference"}:
            return "https://example.invalid/synthetic-doc-check"
        value = "fixture" * max(1, (node.get("minLength", 1) + 6) // 7)
        return value[:node.get("maxLength", len(value))]
    if kind in {"integer", "number"}:
        return node.get("minimum", 0)
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return {}


def accepts(name, value, expected):
    errors = list(validator(name).iter_errors(value))
    require((not errors) == expected, f"{name}: expected {'accept' if expected else 'reject'}; " + "; ".join(f"{'.'.join(map(str,e.path))}: {e.message}" for e in errors[:2]))


def schema_shape_witnesses():
    names = [x["$ref"].rsplit("/", 1)[-1] for x in schema["oneOf"]]
    for name in names:
        value = witness(schema["$defs"][name], name)
        accepts(name, value, True)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    return {"synthetic_shape_witnesses": len(names), "scope": "shape_only_not_artifact_semantics"}


def rejects_history_target():
    value = witness(schema["$defs"]["HistoryView"], "HistoryView")
    accepts("HistoryView", value, True)
    for field, extra in [("target_predictions", []), ("f3", "forbidden"), ("sealed_target_path", "var/sealed-targets/forbidden")]:
        accepts("HistoryView", {**value, field: extra}, False)
    changed = copy.deepcopy(value)
    changed["historical_runs"][0]["slot"] = "f3"
    accepts("HistoryView", changed, False)
    accepts("HistoryView", {**value, "role": "C"}, False)
    return {"rejected_cases": 5}


def access_and_matrix_shapes():
    method = witness(schema["$defs"]["MethodRegistration"], "MethodRegistration")
    accepts("MethodRegistration", {**method, "access_tier": "HISTORY_LABEL_ONLY", "capabilities": ["TEXT", "TARGET_PARAMETERS"]}, False)
    accepts("MethodRegistration", {**method, "access_tier": "REFERENCE_SCORES", "capabilities": ["TEXT", "TARGET_FULL_PREDICTIONS"]}, False)
    accepts("MethodRegistration", {**method, "availability": "UNAVAILABLE_PREAPPROVED", "unavailability_reason": None}, False)
    reg = witness(schema["$defs"]["StudyRegistration"], "StudyRegistration")
    cell = witness(schema["$defs"]["SelectionCell"], "SelectionCell")
    cell.update(access_tier="TARGET_FULL_POOL", budget_semantics="FULL_POOL_ACCESS_REPORTED")
    accepts("StudyRegistration", {**reg, "expected_cells": [cell]}, False)
    enhanced = {**reg, "comparison_scope": "ENHANCED_TARGET_ACCESS", "parent_core_freeze_sha256": fixture_sha, "expected_cells": [cell], "full_target_prediction_unseal_authorization": "AFTER_PARENT_CORE_FREEZE_AND_OWN_REGISTRATION"}
    accepts("StudyRegistration", enhanced, True)
    accepts("StudyRegistration", {**enhanced, "parent_core_freeze_sha256": None}, False)
    matrix = witness(schema["$defs"]["FreezeMatrix"], "FreezeMatrix")
    accepts("FreezeMatrix", {**matrix, "undeclared_target_access_before_freeze": True}, False)
    accepts("FreezeMatrix", {**matrix, "comparison_scope": "ENHANCED_TARGET_ACCESS", "parent_core_freeze_sha256": None}, False)
    accepts("StudyRegistration", {**reg, "registration_phase": "FORMAL", "state": "DRAFT"}, False)
    accepts("SuiteFreeze", {**witness(schema["$defs"]["SuiteFreeze"], "SuiteFreeze"), "state": "FROZEN", "content_sha256": None}, False)
    return {"checks": 10, "enhanced_branch_witness": "synthetic_shape_only"}


def configuration_and_cost_shapes():
    cfg = witness(schema["$defs"]["HgcConfiguration"], "HgcConfiguration")
    accepts("HgcConfiguration", cfg, True)
    accepts("HgcConfiguration", {**cfg, "lambda": 0, "configuration_role": "PRIMARY"}, False)
    accepts("HgcConfiguration", {**cfg, "lambda": 0, "configuration_role": "ABLATION"}, True)
    accepts("HgcConfiguration", {**cfg, "lambda": 1, "configuration_role": "ABLATION"}, True)
    cost = witness(schema["$defs"]["CostLedger"], "CostLedger")
    accepts("CostLedger", {**cost, "phase": "TARGET_FULL_EVALUATION", "account": "PER_UNSEEN_UPDATE"}, False)
    accepts("CostLedger", {**cost, "phase": "TARGET_FULL_METHOD_ACCESS", "account": "RESEARCH_ONLY"}, False)
    accepts("CostLedger", {**cost, "measurement_status": "MEASURED", "wall_seconds": None}, False)
    accepts("CostLedger", {**cost, "measurement_status": "ESTIMATED", "measurement_note": "Synthetic shape test only; no measured cost."}, True)
    return {"checks": 8, "does_not_measure_actual_costs": True}


if __name__ == "__main__":
    check("Immutable eight-file source import", source_integrity)
    check("Local Markdown targets (one documented missing source attachment)", local_links)
    check("Strict JSON and local schema references", json_and_refs)
    check("Draft JSON Schema 2020-12 metaschema", schema_meta)
    check("Synthetic witnesses for all artifact shapes", schema_shape_witnesses)
    check("HistoryView rejects target and confirmation fields", rejects_history_target)
    check("Declared access tiers, scoped matrices and frozen identity shapes", access_and_matrix_shapes)
    check("HGC configuration/ablation and cost-account shape boundaries", configuration_and_cost_shapes)
    report = {"status": "FAIL" if any(x["status"] == "FAIL" for x in results) else "PASS", "scope": "Documentation and draft shape checks only; no HGC implementation, model training, real artifact semantics, access sandbox or experimental effect validation.", "checks": results, "warnings": warnings}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(1 if report["status"] == "FAIL" else 0)
