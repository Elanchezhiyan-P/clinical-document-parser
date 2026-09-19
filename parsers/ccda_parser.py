"""Generic C-CDA (HL7 Clinical Document Architecture) parser.

Unlike a template-driven parser that only understands sections it was
specifically coded for, this walks *every* <section> in the document and
*every* clinically meaningful node inside each <entry>, so nothing in the
source document is silently dropped -- including sections this codebase has
never seen before.
"""
import defusedxml.ElementTree as ET
from datetime import date

def _format_date(raw):
    """CCDA dates are YYYYMMDD or YYYYMMDDHHMM[SS][+-ZZZZ]. Renders them as
    MM/DD/YYYY (with a time suffix when the source has one)."""
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) < 8:
        return raw
    try:
        year, month, day = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return raw
        text = f"{month:02d}/{day:02d}/{year:04d}"
        if len(digits) >= 12:
            hour, minute = int(digits[8:10]), int(digits[10:12])
            suffix = "AM" if hour < 12 else "PM"
            hour12 = hour % 12 or 12
            text += f" {hour12}:{minute:02d} {suffix}"
        return text
    except (ValueError, IndexError):
        return raw


def _date_sort_key(raw):
    """Sortable (year, month, day) tuple from a CCDA date, or a US-style
    MM/DD/YYYY string (what narrative tables in this codebase's sample
    documents use). Unparseable dates sort last."""
    if not raw:
        return (0, 0, 0)
    digits_only = "".join(c for c in raw if c.isdigit())
    if len(raw) >= 8 and raw[:8].isdigit():
        try:
            return (int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            pass
    if "/" in raw:
        parts = raw.strip().split("/")
        if len(parts) == 3:
            try:
                month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
                if year < 100:
                    year += 2000
                return (year, month, day)
            except ValueError:
                pass
    if "-" in raw and len(digits_only) >= 8:
        try:
            year, month, day = raw.split("-")[:3]
            return (int(year), int(month), int(day[:2]))
        except ValueError:
            pass
    return (0, 0, 0)


def _compute_age(raw_dob):
    """Age in whole years as of today, from a raw CCDA birthTime value."""
    if not raw_dob or len(raw_dob) < 8 or not raw_dob[:8].isdigit():
        return None
    try:
        year, month, day = int(raw_dob[0:4]), int(raw_dob[4:6]), int(raw_dob[6:8])
        born = date(year, month, day)
    except ValueError:
        return None
    today = date.today()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return age if 0 <= age <= 130 else None


NS = {"v3": "urn:hl7-org:v3", "sdtc": "urn:hl7-org:sdtc"}
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# Any element with one of these local (namespace-stripped) tag names is
# treated as a "clinical statement" worth summarizing when walking entries.
CLINICAL_TAGS = {
    "act", "observation", "substanceAdministration", "organizer",
    "procedure", "supply", "encounter", "regionOfInterest",
    "manufacturedMaterial", "playingEntity",
}

# manufacturedMaterial/playingEntity are named-entity containers (the actual
# drug or allergen), not clinical-statement nodes -- give them a plain label
# instead of showing their raw (lowercased, namespace-stripped) tag name.
TYPE_LABELS = {
    "manufacturedmaterial": "Medication",
    "playingentity": "Substance",
}

# Plain-language names for a non-clinical reader, keyed by the section's
# LOINC code (stable across documents) with a title-text fallback below.
# Also assigns an icon category so the UI can show a consistent glyph.
FRIENDLY_SECTION_LABELS = {
    "48765-2": ("Allergies", "allergy"),
    "11450-4": ("Health Conditions", "condition"),
    "10160-0": ("Medications", "medication"),
    "30954-2": ("Lab Results", "lab"),
    "8716-3": ("Vital Signs", "vitals"),
    "10157-6": ("Family Health History", "family"),
    "29762-2": ("Lifestyle & Social History", "social"),
    "47420-5": ("Functional Ability", "activity"),
    "29545-1": ("Physical Exam Findings", "exam"),
    "46240-8": ("Visit History", "visit"),
    "47519-4": ("Procedures", "procedure"),
    "18776-5": ("Referrals & Follow-Up", "referral"),
    "61144-2": ("Nutrition", "nutrition"),
    "61146-7": ("Care Goals", "goal"),
    "51848-0": ("Clinical Assessment", "assessment"),
    "10154-3": ("Chief Complaint", "exam"),
    "29299-5": ("Reason for Visit", "visit"),
    "10164-2": ("Current Illness Details", "assessment"),
    "10187-3": ("Symptom Review", "exam"),
}


# Facts that describe a *property* of a diagnosis (how old the patient was,
# how severe it is, the administrative wrapper code) rather than being the
# diagnosis itself, so they're excluded when picking the diagnosis's name.
ADMIN_FACT_LABELS = {
    "age at onset of clinical finding", "age at onset", "severity", "concern", "assertion",
}

# General medical knowledge linking a condition to commonly-ordered tests --
# used only to point out labs *already present in this document* that are
# typically relevant, never to imply the document itself states the link.
CONDITION_TEST_KEYWORDS = [
    (("diabetes", "diabetic"), ("a1c", "hba1c", "glucose", "glycated", "metabolic panel")),
    (("hyperlipidemia", "cholesterol", "lipid"), ("lipid", "cholesterol", "ldl", "hdl", "triglyceride")),
    (("hiv",), ("cd4", "viral load", "hiv")),
    (("hypertens",), ("renal", "creatinine", "potassium", "metabolic panel", "sodium")),
    (("kidney", "renal", "ckd"), ("creatinine", "gfr", "bun", "renal", "metabolic panel")),
    (("anemia",), ("hemoglobin", "hematocrit", "cbc", "iron", "ferritin")),
    (("thyroid",), ("tsh", "thyroid")),
    (("heart failure", "cardiomyopathy"), ("bnp", "probnp", "echocardiogram", "ejection")),
    (("copd", "asthma", "respiratory"), ("spirometry", "pulmonary", "abg", "oxygen")),
    (("obesity",), ("lipid", "glucose", "a1c", "metabolic panel")),
    (("osteoporosis",), ("vitamin d", "calcium", "bone density")),
    (("hepatitis", "liver"), ("hepatic", "liver", "alt", "ast", "bilirubin")),
]


def _suggested_tests_for(diagnosis_name_lower, lab_panel_names):
    for condition_keys, test_keys in CONDITION_TEST_KEYWORDS:
        if any(k in diagnosis_name_lower for k in condition_keys):
            return [
                panel for panel in lab_panel_names
                if any(t in panel.lower() for t in test_keys)
            ]
    return []


def _primary_diagnosis_text(facts):
    """Picks the fact that IS the diagnosis (e.g. "Type 2 diabetes mellitus"),
    as opposed to a fact describing one of its properties."""
    for f in facts:
        if (f.get("label") or "").strip().lower() in ADMIN_FACT_LABELS:
            continue
        code_system = (f.get("code_system_name") or "").upper()
        if f.get("value") and ("SNOMED" in code_system or "ICD" in code_system):
            return f["value"]
    return None


def _cross_reference(sections):
    """Links each diagnosis in the Health Conditions section to medications
    that name it as their reason (a real link present in the document via
    the substanceAdministration's RSON relationship) and, separately, flags
    lab panels already in the document that are commonly relevant to that
    diagnosis (general medical knowledge, clearly kept apart from the
    document-verified medication links)."""
    condition_section = next((s for s in sections if s["icon"] == "condition"), None)
    if condition_section is None:
        return
    med_section = next((s for s in sections if s["icon"] == "medication"), None)
    lab_section = next((s for s in sections if s["icon"] == "lab"), None)

    diagnoses = []
    for facts in condition_section["entries"]:
        name = _primary_diagnosis_text(facts)
        if name and name not in [d["name"] for d in diagnoses]:
            diagnoses.append({"name": name, "linked_medications": [], "linked_labs": [], "suggested_labs": []})

    diagnosis_by_key = {d["name"].lower(): d for d in diagnoses}

    if med_section:
        for facts in med_section["entries"]:
            med_name = next((f["label"] for f in facts if f["type"] == "Medication"), None)
            if not med_name:
                continue
            for f in facts:
                key = (f.get("value") or "").strip().lower()
                target = diagnosis_by_key.get(key)
                if target and med_name not in target["linked_medications"]:
                    target["linked_medications"].append(med_name)

    lab_panel_names = []
    if lab_section:
        for facts in lab_section["entries"]:
            panel_name = facts[0]["label"] if facts else None
            if not panel_name:
                continue
            lab_panel_names.append(panel_name)
            for f in facts:
                key = (f.get("value") or "").strip().lower()
                target = diagnosis_by_key.get(key)
                if target and panel_name not in target["linked_labs"]:
                    target["linked_labs"].append(panel_name)

    for d in diagnoses:
        already_linked = set(d["linked_labs"])
        d["suggested_labs"] = [
            p for p in _suggested_tests_for(d["name"].lower(), lab_panel_names)
            if p not in already_linked
        ]

    condition_section["diagnosis_links"] = [d for d in diagnoses if d["linked_medications"] or d["suggested_labs"] or d["linked_labs"]]


def _friendly_title(code, fallback_title):
    entry = FRIENDLY_SECTION_LABELS.get(code)
    if entry:
        return entry
    return (fallback_title, "general")


def _local(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _text(el):
    if el is None:
        return None
    joined = "".join(el.itertext()).strip()
    return joined or None


def _attr(el, name, default=None):
    return el.get(name, default) if el is not None else default


def _describe_value(value_el):
    """Renders a CDA <value>/xsi:type element as a human string."""
    if value_el is None:
        return None
    xsi_type = value_el.get(XSI_TYPE)
    if xsi_type == "CD" or xsi_type == "CE":
        display = value_el.get("displayName")
        code = value_el.get("code")
        if display:
            return display
        if code:
            return code
    if xsi_type == "PQ":
        value = value_el.get("value")
        unit = value_el.get("unit")
        if value is not None:
            return f"{value} {unit}".strip() if unit else value
    if xsi_type == "IVL_PQ":
        low = value_el.find("v3:low", NS)
        high = value_el.find("v3:high", NS)
        low_v = _attr(low, "value")
        high_v = _attr(high, "value")
        unit = _attr(low, "unit") or _attr(high, "unit")
        if low_v or high_v:
            return f"{low_v or '?'} - {high_v or '?'} {unit or ''}".strip()
    if xsi_type in ("ST", None):
        text = _text(value_el)
        if text:
            return text
    if xsi_type in ("BL",):
        return value_el.get("value")
    if xsi_type == "TS":
        return _format_date(value_el.get("value"))
    # Fallback: nullFlavor, or any leftover attributes/text
    if value_el.get("nullFlavor"):
        return None
    return _text(value_el) or value_el.get("value") or value_el.get("displayName")


def _describe_time(eff_time_el):
    if eff_time_el is None:
        return None
    if eff_time_el.get("value"):
        return _format_date(eff_time_el.get("value"))
    low = eff_time_el.find("v3:low", NS)
    high = eff_time_el.find("v3:high", NS)
    low_v = _format_date(_attr(low, "value"))
    high_v = _format_date(_attr(high, "value"))
    if low_v and high_v:
        return f"{low_v} - {high_v}"
    if low_v:
        return f"since {low_v}"
    if high_v:
        return f"until {high_v}"
    return None


def _summarize_entry(entry_el):
    """Flattens every clinical-statement node inside one <entry> into a list
    of {type, label, code, code_system, status, value, date} dicts, in
    document order, regardless of nesting depth or section."""
    facts = []
    for el in entry_el.iter():
        tag = _local(el.tag)
        if tag not in CLINICAL_TAGS:
            continue
        code_el = el.find("v3:code", NS)
        value_el = el.find("v3:value", NS)
        status_el = el.find("v3:statusCode", NS)
        eff_time_el = el.find("v3:effectiveTime", NS)

        label = _attr(code_el, "displayName")
        value = _describe_value(value_el)
        if not label and not value:
            continue  # nothing worth showing on this node

        fact = {
            "type": TYPE_LABELS.get(tag.lower(), tag),
            "label": label or _attr(code_el, "code") or tag,
            "code": _attr(code_el, "code"),
            "code_system_name": _attr(code_el, "codeSystemName"),
            "status": _attr(status_el, "code"),
            "value": value,
            "date": _describe_time(eff_time_el),
            "negated": el.get("negationInd") == "true",
        }
        facts.append(fact)
    return facts


DATE_COLUMN_HINTS = ("date", "onset", "collected", "performed")
STATUS_COLUMN_HINTS = ("status",)
ACTIVE_STATUS_VALUES = {"active", "current", "ongoing", "in progress"}


def _find_column(headers, hints):
    for i, h in enumerate(headers):
        h_lower = (h or "").strip().lower()
        if any(hint in h_lower for hint in hints):
            return i
    return None


def _parse_narrative(text_el):
    if text_el is None:
        return {"tables": [], "paragraphs": []}
    tables = []
    for table_el in text_el.findall(".//v3:table", NS):
        headers = [_text(th) or "" for th in table_el.findall(".//v3:thead//v3:th", NS)]
        rows = []
        for tr in table_el.findall(".//v3:tbody/v3:tr", NS):
            cells = [_text(td) or "" for td in tr.findall("v3:td", NS)]
            if cells:
                rows.append(cells)

        date_col = _find_column(headers, DATE_COLUMN_HINTS)
        if date_col is not None:
            rows.sort(
                key=lambda r: _date_sort_key(r[date_col]) if date_col < len(r) else (0, 0, 0),
                reverse=True,
            )

        status_col = _find_column(headers, STATUS_COLUMN_HINTS)
        active_rows, other_rows = None, None
        if status_col is not None:
            active_rows, other_rows = [], []
            for r in rows:
                is_active = status_col < len(r) and r[status_col].strip().lower() in ACTIVE_STATUS_VALUES
                (active_rows if is_active else other_rows).append(r)

        tables.append({
            "headers": headers,
            "rows": rows,
            "status_col_index": status_col,
            "active_rows": active_rows,
            "other_rows": other_rows,
        })

    paragraphs = []
    for p in text_el.findall(".//v3:paragraph", NS):
        t = _text(p)
        if t:
            paragraphs.append(t)
    for item in text_el.findall(".//v3:item", NS):
        t = _text(item)
        if t:
            paragraphs.append(t)

    return {"tables": tables, "paragraphs": paragraphs}


def _parse_section(section_el, depth=0):
    code_el = section_el.find("v3:code", NS)
    title_el = section_el.find("v3:title", NS)
    text_el = section_el.find("v3:text", NS)

    entries = []
    for entry_el in section_el.findall("v3:entry", NS):
        facts = _summarize_entry(entry_el)
        if facts:
            entries.append(facts)

    subsections = []
    for sub_component in section_el.findall("v3:component/v3:section", NS):
        subsections.append(_parse_section(sub_component, depth + 1))

    title = _text(title_el) or _attr(code_el, "displayName") or "Other Information"
    friendly_title, icon = _friendly_title(_attr(code_el, "code"), title)

    return {
        "title": title,
        "friendly_title": friendly_title,
        "icon": icon,
        "code": _attr(code_el, "code"),
        "code_system_name": _attr(code_el, "codeSystemName"),
        "narrative": _parse_narrative(text_el),
        "entries": entries,
        "subsections": subsections,
        "depth": depth,
    }


def _parse_name(name_el):
    if name_el is None:
        return None
    given = [_text(g) for g in name_el.findall("v3:given", NS) if _text(g)]
    family = _text(name_el.find("v3:family", NS))
    prefix = [_text(p) for p in name_el.findall("v3:prefix", NS) if _text(p)]
    suffix = [_text(s) for s in name_el.findall("v3:suffix", NS) if _text(s)]
    parts = prefix + given + ([family] if family else []) + suffix
    return " ".join(parts) if parts else _text(name_el)


def _parse_addr(addr_el):
    if addr_el is None or addr_el.get("nullFlavor"):
        return None
    lines = [_text(l) for l in addr_el.findall("v3:streetAddressLine", NS) if _text(l)]
    city = _text(addr_el.find("v3:city", NS))
    state = _text(addr_el.find("v3:state", NS))
    postal = _text(addr_el.find("v3:postalCode", NS))
    country = _text(addr_el.find("v3:country", NS))
    tail = ", ".join(x for x in [city, state, postal, country] if x)
    full = ", ".join(x for x in [", ".join(lines), tail] if x)
    return full or None


def _parse_telecom(telecom_els):
    results = []
    for t in telecom_els:
        if t.get("nullFlavor"):
            continue
        value = t.get("value", "")
        use = t.get("use")
        results.append(f"{value} ({use})" if use else value)
    return results


def _parse_demographics(root):
    patient_role = root.find(".//v3:recordTarget/v3:patientRole", NS)
    if patient_role is None:
        return {}
    patient = patient_role.find("v3:patient", NS)

    names = [_parse_name(n) for n in (patient.findall("v3:name", NS) if patient is not None else [])]
    addresses = [a for a in (_parse_addr(a) for a in patient_role.findall("v3:addr", NS)) if a]
    telecoms = _parse_telecom(patient_role.findall("v3:telecom", NS))

    gender_el = patient.find("v3:administrativeGenderCode", NS) if patient is not None else None
    dob_el = patient.find("v3:birthTime", NS) if patient is not None else None
    race_el = patient.find("v3:raceCode", NS) if patient is not None else None
    ethnicity_el = patient.find("v3:ethnicGroupCode", NS) if patient is not None else None
    marital_el = patient.find("v3:maritalStatusCode", NS) if patient is not None else None
    religion_el = patient.find("v3:religiousAffiliationCode", NS) if patient is not None else None
    language_el = patient.find(".//v3:languageCommunication/v3:languageCode", NS) if patient is not None else None
    id_els = patient_role.findall("v3:id", NS)
    guardian_el = patient.find(".//v3:guardian/v3:guardianPerson/v3:name", NS) if patient is not None else None
    birthplace_el = patient.find(".//v3:birthplace/v3:place/v3:addr", NS) if patient is not None else None

    return {
        "names": [n for n in names if n],
        "identifiers": [{"root": _attr(i, "root"), "extension": _attr(i, "extension")} for i in id_els],
        "gender": _attr(gender_el, "displayName") or _attr(gender_el, "code"),
        "birth_date": _format_date(_attr(dob_el, "value")),
        "age": _compute_age(_attr(dob_el, "value")),
        "race": _attr(race_el, "displayName"),
        "ethnicity": _attr(ethnicity_el, "displayName"),
        "marital_status": _attr(marital_el, "displayName"),
        "religion": _attr(religion_el, "displayName"),
        "preferred_language": _attr(language_el, "code"),
        "addresses": addresses,
        "telecoms": telecoms,
        "guardian": _parse_name(guardian_el),
        "birthplace": _parse_addr(birthplace_el),
    }


def _parse_participants(root):
    """Author(s), custodian, and the servicing provider/organization -- the
    people/orgs responsible for the DOCUMENT overall, not the patient, and
    not the many per-entry authors CCDA attaches to individual problems/
    medications/etc (findall('v3:author') with no './/' deliberately stays
    scoped to ClinicalDocument's direct children so those aren't swept in)."""
    participants = []

    for author in root.findall("v3:author", NS):
        person_name = _parse_name(author.find(".//v3:assignedPerson/v3:name", NS))
        org_name = _text(author.find(".//v3:representedOrganization/v3:name", NS))
        time_el = author.find("v3:time", NS)
        if person_name or org_name:
            participants.append({
                "role": "Author",
                "name": person_name,
                "organization": org_name,
                "date": _format_date(_attr(time_el, "value")),
            })

    custodian_org = _text(root.find("v3:custodian//v3:representedCustodianOrganization/v3:name", NS))
    if custodian_org:
        participants.append({"role": "Custodian", "name": None, "organization": custodian_org, "date": None})

    for performer in root.findall("v3:documentationOf/v3:serviceEvent/v3:performer", NS):
        person_name = _parse_name(performer.find(".//v3:assignedPerson/v3:name", NS))
        org_name = _text(performer.find(".//v3:representedOrganization/v3:name", NS))
        if person_name or org_name:
            participants.append({
                "role": "Performing Provider",
                "name": person_name,
                "organization": org_name,
                "date": None,
            })

    # Safety net: even scoped to the header, some documents legitimately
    # repeat the same person/org under two roles -- keep the first billing
    # of each (name, organization) pair rather than showing it twice.
    seen = set()
    deduped = []
    for p in participants:
        key = (p["name"], p["organization"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    return deduped


def parse_ccda(raw_bytes):
    root = ET.fromstring(raw_bytes)

    title_el = root.find("v3:title", NS)
    doc_code_el = root.find("v3:code", NS)
    doc_time_el = root.find("v3:effectiveTime", NS)
    doc_id_el = root.find("v3:id", NS)

    sections = []
    for section_el in root.findall(".//v3:component/v3:structuredBody/v3:component/v3:section", NS):
        sections.append(_parse_section(section_el))

    _cross_reference(sections)

    return {
        "format": "CCDA",
        "document_title": _text(title_el),
        "document_type": _attr(doc_code_el, "displayName"),
        "document_date": _format_date(_attr(doc_time_el, "value")),
        "document_id": _attr(doc_id_el, "root"),
        "demographics": _parse_demographics(root),
        "participants": _parse_participants(root),
        "sections": sections,
        "section_count": len(sections),
        "total_entries": sum(len(s["entries"]) for s in sections),
    }
