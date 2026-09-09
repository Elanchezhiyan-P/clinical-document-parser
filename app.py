"""Clinical Document Parser -- upload a C-CDA, HL7 v2.x, or FHIR (JSON/XML)
file and see every field it contains, without needing to know in advance
which format it is.
"""
import json
from datetime import datetime
from urllib.parse import quote, unquote

from flask import Flask, render_template, request, flash, redirect, url_for, make_response
import xml.etree.ElementTree as ET

from parsers import detect_format, parse_ccda, parse_hl7v2, parse_fhir
from parsers.detect import FORMAT_CCDA, FORMAT_HL7V2, FORMAT_FHIR_JSON, FORMAT_FHIR_XML, FORMAT_UNKNOWN

app = Flask(__name__)
app.secret_key = "dev-only-not-for-production"
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

LAST_VISIT_COOKIE = "last_document"
FORMAT_DISPLAY_NAMES = {
    FORMAT_CCDA: "a clinical record",
    FORMAT_HL7V2: "an HL7 message",
    FORMAT_FHIR_JSON: "a FHIR record",
    FORMAT_FHIR_XML: "a FHIR record",
}


def _read_last_visit():
    raw = request.cookies.get(LAST_VISIT_COOKIE)
    if not raw:
        return None
    try:
        return json.loads(unquote(raw))
    except (ValueError, TypeError):
        return None


@app.route("/")
def index():
    return render_template("index.html", last_visit=_read_last_visit())


@app.route("/upload", methods=["POST"])
def upload():
    uploaded = request.files.get("document")
    if not uploaded or uploaded.filename == "":
        flash("Choose a file first.")
        return redirect(url_for("index"))

    raw_bytes = uploaded.read()
    fmt = detect_format(raw_bytes)

    try:
        if fmt == FORMAT_CCDA:
            result = parse_ccda(raw_bytes)
        elif fmt == FORMAT_HL7V2:
            result = parse_hl7v2(raw_bytes)
        elif fmt == FORMAT_FHIR_JSON:
            result = parse_fhir(raw_bytes, xml=False)
        elif fmt == FORMAT_FHIR_XML:
            result = parse_fhir(raw_bytes, xml=True)
        else:
            flash(
                f"Could not identify the format of '{uploaded.filename}'. "
                "Expected a C-CDA XML document, an HL7 v2.x message (starting with MSH|), "
                "or a FHIR resource/Bundle (JSON or XML)."
            )
            return redirect(url_for("index"))
    except ET.ParseError as e:
        flash(f"'{uploaded.filename}' looked like XML but failed to parse: {e}")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Failed to parse '{uploaded.filename}': {type(e).__name__}: {e}")
        return redirect(url_for("index"))

    template = {
        FORMAT_CCDA: "result_ccda.html",
        FORMAT_HL7V2: "result_hl7v2.html",
        FORMAT_FHIR_JSON: "result_fhir.html",
        FORMAT_FHIR_XML: "result_fhir.html",
    }[fmt]

    response = make_response(render_template(template, filename=uploaded.filename, doc=result))

    # We don't keep the parsed record on the server (nothing is persisted
    # beyond this request), so this cookie can only remember what the file
    # was called and when it was viewed -- not restore the file itself.
    cookie_value = quote(json.dumps({
        "filename": uploaded.filename,
        "format_label": FORMAT_DISPLAY_NAMES.get(fmt, "a health record"),
        "viewed_at": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
    }))
    response.set_cookie(LAST_VISIT_COOKIE, cookie_value, max_age=60 * 60 * 24 * 30)
    return response


if __name__ == "__main__":
    app.run(debug=True, port=5057)
