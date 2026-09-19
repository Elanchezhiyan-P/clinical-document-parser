"""FHIR parser -- accepts either FHIR JSON or FHIR XML, a single resource or
a Bundle. Every resource is kept as its full nested structure (nothing is
dropped) plus a best-effort human-readable one-line summary for common
resource types, so the UI can show a friendly headline while still exposing
every field underneath.
"""
import json
import defusedxml.ElementTree as ET


def _local(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _fhir_xml_element_to_value(el):
    """Converts one FHIR XML element into the equivalent JSON-ish Python
    value: a plain string for primitives (<x value="..."/>), or a dict/list
    for complex/repeating elements."""
    children = list(el)
    if not children:
        if "value" in el.attrib:
            return el.get("value")
        return None

    result = {}
    for child in children:
        tag = _local(child.tag)
        if tag == "extension":
            continue  # extensions add a lot of noise for a general viewer
        value = _fhir_xml_element_to_value(child)
        if tag in result:
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(value)
        else:
            result[tag] = value
    return result


def _fhir_xml_to_resource(el):
    resource = {"resourceType": _local(el.tag)}
    resource.update(_fhir_xml_element_to_value(el) or {})
    return resource


def _extract_resources(parsed):
    """parsed is a Python dict already (from JSON or converted from XML).
    Returns a flat list of resource dicts, unwrapping a Bundle if present."""
    if parsed.get("resourceType") == "Bundle":
        resources = []
        for entry in parsed.get("entry", []) or []:
            if isinstance(entry, dict) and "resource" in entry:
                resources.append(entry["resource"])
        return resources
    return [parsed]


def _join_name(name_obj):
    if isinstance(name_obj, list):
        name_obj = name_obj[0] if name_obj else None
    if not isinstance(name_obj, dict):
        return None
    given = name_obj.get("given")
    if isinstance(given, str):
        given = [given]
    given = given or []
    family = name_obj.get("family")
    text = name_obj.get("text")
    parts = given + ([family] if family else [])
    return " ".join(parts) if parts else text


def _codeable_concept_text(cc):
    if isinstance(cc, list):
        cc = cc[0] if cc else None
    if not isinstance(cc, dict):
        return cc if isinstance(cc, str) else None
    if cc.get("text"):
        return cc["text"]
    codings = cc.get("coding")
    if isinstance(codings, dict):
        codings = [codings]
    if codings:
        first = codings[0]
        return first.get("display") or first.get("code")
    return None


def _quantity_text(q):
    if not isinstance(q, dict):
        return None
    value = q.get("value")
    unit = q.get("unit") or q.get("code")
    if value is None:
        return None
    return f"{value} {unit}".strip() if unit else str(value)


# Best-effort one-line summaries per resource type. Anything not listed here
# (or any field a listed summarizer doesn't reach) is still fully present in
# the resource's raw structure -- these summaries are a convenience layer,
# never the only source of truth.
def _summarize(resource):
    rt = resource.get("resourceType")

    if rt == "Patient":
        return _join_name(resource.get("name")) or "Patient"
    if rt in ("Practitioner", "RelatedPerson", "Person"):
        return _join_name(resource.get("name")) or rt
    if rt == "Organization":
        return resource.get("name") or "Organization"
    if rt == "Condition":
        return _codeable_concept_text(resource.get("code")) or "Condition"
    if rt == "AllergyIntolerance":
        return _codeable_concept_text(resource.get("code")) or "Allergy"
    if rt in ("MedicationRequest", "MedicationStatement"):
        med = resource.get("medicationCodeableConcept") or resource.get("medication")
        return _codeable_concept_text(med) or rt
    if rt == "Observation":
        code = _codeable_concept_text(resource.get("code"))
        value = (
            _quantity_text(resource.get("valueQuantity"))
            or _codeable_concept_text(resource.get("valueCodeableConcept"))
            or resource.get("valueString")
        )
        if code and value:
            return f"{code}: {value}"
        return code or "Observation"
    if rt == "Procedure":
        return _codeable_concept_text(resource.get("code")) or "Procedure"
    if rt == "Immunization":
        return _codeable_concept_text(resource.get("vaccineCode")) or "Immunization"
    if rt == "DiagnosticReport":
        return _codeable_concept_text(resource.get("code")) or "Diagnostic Report"
    if rt == "Encounter":
        return _codeable_concept_text(resource.get("type")) or "Encounter"
    if rt == "FamilyMemberHistory":
        relationship = _codeable_concept_text(resource.get("relationship"))
        conditions = resource.get("condition")
        if isinstance(conditions, dict):
            conditions = [conditions]
        cond_text = ", ".join(
            filter(None, (_codeable_concept_text(c.get("code")) for c in (conditions or []) if isinstance(c, dict)))
        )
        return f"{relationship or 'Relative'}: {cond_text}" if cond_text else (relationship or "Family History")
    if rt == "Goal":
        return _codeable_concept_text(resource.get("description")) or "Goal"

    return resource.get("id") or rt or "Resource"


def parse_fhir(raw_bytes, xml=False):
    text = raw_bytes.decode("utf-8", errors="replace")

    if xml:
        root = ET.fromstring(raw_bytes)
        parsed = _fhir_xml_to_resource(root)
    else:
        parsed = json.loads(text)

    resources = _extract_resources(parsed)

    summarized = []
    for r in resources:
        if not isinstance(r, dict):
            continue
        summarized.append({
            "resource_type": r.get("resourceType", "Resource"),
            "id": r.get("id"),
            "summary": _summarize(r),
            "raw": r,
        })

    return {
        "format": "FHIR",
        "bundle_type": parsed.get("type") if parsed.get("resourceType") == "Bundle" else None,
        "resource_count": len(summarized),
        "resources": summarized,
    }
