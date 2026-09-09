"""Generic HL7 v2.x parser (pipe-delimited segments).

Handles a batch file containing multiple messages (each starting with its own
MSH segment). Every segment and every field is preserved -- known segments
get human-readable field labels from SEGMENT_FIELD_NAMES, but an unrecognized
segment or a field beyond the known list is still shown (generically
labeled), so nothing from the source message is dropped.
"""

# Field labels for the segments this domain sees most often. Index 0 in each
# list corresponds to field 1 (the segment name itself, field 0, is never
# included here). Not exhaustive by design -- any field past the end of the
# list, or any segment not listed at all, still renders with a generic label.
SEGMENT_FIELD_NAMES = {
    "MSH": [
        "Field Separator", "Encoding Characters", "Sending Application", "Sending Facility",
        "Receiving Application", "Receiving Facility", "Date/Time of Message", "Security",
        "Message Type", "Message Control ID", "Processing ID", "Version ID",
    ],
    "PID": [
        "Set ID", "Patient ID", "Patient Identifier List", "Alternate Patient ID",
        "Patient Name", "Mother's Maiden Name", "Date/Time of Birth", "Administrative Sex",
        "Patient Alias", "Race", "Patient Address", "County Code", "Phone Number - Home",
        "Phone Number - Business", "Primary Language", "Marital Status", "Religion",
        "Patient Account Number", "SSN Number", "Driver's License Number", "Mother's Identifier",
        "Ethnic Group", "Birth Place", "Multiple Birth Indicator", "Birth Order",
    ],
    "PV1": [
        "Set ID", "Patient Class", "Assigned Patient Location", "Admission Type",
        "Preadmit Number", "Prior Patient Location", "Attending Doctor", "Referring Doctor",
        "Consulting Doctor", "Hospital Service", "Temporary Location", "Preadmit Test Indicator",
        "Readmission Indicator", "Admit Source", "Ambulatory Status", "VIP Indicator",
        "Admitting Doctor", "Patient Type", "Visit Number",
    ],
    "NK1": [
        "Set ID", "Name", "Relationship", "Address", "Phone Number", "Business Phone Number",
        "Contact Role",
    ],
    "OBR": [
        "Set ID", "Placer Order Number", "Filler Order Number", "Universal Service ID",
        "Priority", "Requested Date/Time", "Observation Date/Time", "Observation End Date/Time",
        "Collection Volume", "Collector Identifier", "Specimen Action Code", "Danger Code",
        "Relevant Clinical Info", "Specimen Received Date/Time", "Specimen Source",
        "Ordering Provider", "Order Callback Phone Number", "Placer Field 1", "Placer Field 2",
        "Filler Field 1", "Filler Field 2", "Results Rpt/Status Chng Date/Time",
        "Charge to Practice", "Diagnostic Serv Sect ID", "Result Status",
    ],
    "OBX": [
        "Set ID", "Value Type", "Observation Identifier", "Observation Sub-ID",
        "Observation Value", "Units", "Reference Range", "Abnormal Flags", "Probability",
        "Nature of Abnormal Test", "Observation Result Status", "Effective Date of Reference Range",
        "User Defined Access Checks", "Date/Time of the Observation",
    ],
    "ORC": [
        "Order Control", "Placer Order Number", "Filler Order Number", "Placer Group Number",
        "Order Status", "Response Flag", "Quantity/Timing", "Parent", "Date/Time of Transaction",
        "Entered By", "Verified By", "Ordering Provider", "Enterer's Location",
        "Call Back Phone Number", "Order Effective Date/Time",
    ],
    "DG1": [
        "Set ID", "Diagnosis Coding Method", "Diagnosis Code", "Diagnosis Description",
        "Diagnosis Date/Time", "Diagnosis Type", "Major Diagnostic Category",
        "Diagnostic Related Group", "DRG Approval Indicator", "DRG Grouper Review Code",
    ],
    "AL1": [
        "Set ID", "Allergen Type Code", "Allergen Code/Description", "Allergy Severity Code",
        "Allergy Reaction", "Identification Date",
    ],
    "RXA": [
        "Give Sub-ID Counter", "Administration Sub-ID Counter", "Date/Time Start of Administration",
        "Date/Time End of Administration", "Administered Code", "Administered Amount",
        "Administered Units", "Administered Dosage Form", "Administration Notes",
        "Administering Provider", "Administered-at Location", "Administered Per (Time Unit)",
        "Administered Strength", "Administered Strength Units", "Substance Lot Number",
        "Substance Expiration Date", "Substance Manufacturer Name",
    ],
    "RXE": [
        "Quantity/Timing", "Give Code", "Give Amount - Minimum", "Give Amount - Maximum",
        "Give Units", "Give Dosage Form", "Provider's Administration Instructions",
        "Deliver-to Location", "Substitution Status", "Dispense Amount", "Dispense Units",
        "Number of Refills", "Ordering Provider's DEA Number", "Pharmacist/Treatment Supplier's Verifier ID",
    ],
    "IN1": [
        "Set ID", "Insurance Plan ID", "Insurance Company ID", "Insurance Company Name",
        "Insurance Company Address", "Insurance Co Contact Person", "Insurance Co Phone Number",
        "Group Number", "Group Name", "Insured's Group Emp ID", "Insured's Group Emp Name",
        "Plan Effective Date", "Plan Expiration Date",
    ],
    "GT1": [
        "Set ID", "Guarantor Number", "Guarantor Name", "Guarantor Spouse Name",
        "Guarantor Address", "Guarantor Phone Number - Home", "Guarantor Phone Number - Business",
        "Guarantor Date/Time of Birth", "Guarantor Administrative Sex", "Guarantor Type",
        "Guarantor Relationship",
    ],
    "EVN": [
        "Event Type Code", "Recorded Date/Time", "Date/Time Planned Event", "Event Reason Code",
        "Operator ID", "Event Occurred",
    ],
}


def _split_messages(text):
    """A batch file may contain several MSH-delimited messages back to back."""
    lines = text.replace("\r\n", "\r").replace("\n", "\r").split("\r")
    messages, current = [], []
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("MSH") and current:
            messages.append(current)
            current = []
        current.append(line)
    if current:
        messages.append(current)
    return messages


def _parse_field(raw_field, component_sep, repetition_sep, subcomponent_sep):
    """A field may repeat (~) and each repetition may have components (^) and
    subcomponents (&). Returns the field as-is if it's a plain scalar,
    otherwise a nested list structure mirroring the HL7 encoding."""
    if repetition_sep in raw_field:
        return [_parse_field(rep, component_sep, repetition_sep, subcomponent_sep)
                for rep in raw_field.split(repetition_sep)]
    if component_sep in raw_field:
        components = raw_field.split(component_sep)
        return [c.split(subcomponent_sep) if subcomponent_sep in c else c for c in components]
    return raw_field


def _parse_segment(line, component_sep, repetition_sep, subcomponent_sep, field_sep):
    parts = line.split(field_sep)
    seg_id = parts[0]
    field_names = SEGMENT_FIELD_NAMES.get(seg_id, [])

    if seg_id == "MSH":
        # MSH is irregular: the field separator character itself IS MSH-1
        # and is consumed as the split delimiter, so it never appears as its
        # own token. Re-insert it so parts[i] lines up with field i for every
        # segment uniformly (parts[1] = encoding chars = MSH-2, etc.).
        parts = [parts[0], field_sep] + parts[1:]

    fields = []
    for i, raw in enumerate(parts[1:], start=1):
        if raw == "":
            continue
        label = field_names[i - 1] if i - 1 < len(field_names) else f"Field {i}"
        fields.append({
            "index": i,
            "label": label,
            "value": _parse_field(raw, component_sep, repetition_sep, subcomponent_sep),
            "raw": raw,
        })

    return {"segment_id": seg_id, "fields": fields, "raw_line": line}


def parse_hl7v2(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="replace").strip()
    message_blocks = _split_messages(text)

    messages = []
    for block in message_blocks:
        msh_line = block[0]
        field_sep = msh_line[3] if len(msh_line) > 3 else "|"
        encoding_chars = msh_line.split(field_sep)[1] if field_sep in msh_line else "^~\\&"
        component_sep = encoding_chars[0] if len(encoding_chars) > 0 else "^"
        repetition_sep = encoding_chars[1] if len(encoding_chars) > 1 else "~"
        escape_char = encoding_chars[2] if len(encoding_chars) > 2 else "\\"
        subcomponent_sep = encoding_chars[3] if len(encoding_chars) > 3 else "&"

        segments = [
            _parse_segment(line, component_sep, repetition_sep, subcomponent_sep, field_sep)
            for line in block
        ]

        msh_fields = {f["index"]: f["value"] for f in segments[0]["fields"]}
        message_type = msh_fields.get(9)
        if isinstance(message_type, list):
            message_type = "^".join(c for c in message_type if isinstance(c, str))

        messages.append({
            "message_type": message_type,
            "message_control_id": msh_fields.get(10),
            "sending_application": msh_fields.get(3),
            "sending_facility": msh_fields.get(4),
            "message_datetime": msh_fields.get(7),
            "encoding": {
                "field_separator": field_sep,
                "component_separator": component_sep,
                "repetition_separator": repetition_sep,
                "escape_character": escape_char,
                "subcomponent_separator": subcomponent_sep,
            },
            "segments": segments,
            "segment_count": len(segments),
        })

    return {
        "format": "HL7v2",
        "message_count": len(messages),
        "messages": messages,
    }
