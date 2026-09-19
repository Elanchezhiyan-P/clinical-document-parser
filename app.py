"""Clinical Document Parser -- upload a C-CDA, HL7 v2.x, or FHIR (JSON/XML)
file and see every field it contains, without needing to know in advance
which format it is.
"""
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

from flask import Flask, render_template, request, flash, redirect, url_for, make_response, abort
import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from parsers import detect_format, parse_ccda, parse_hl7v2, parse_fhir
from parsers.detect import FORMAT_CCDA, FORMAT_HL7V2, FORMAT_FHIR_JSON, FORMAT_FHIR_XML, FORMAT_UNKNOWN

SAMPLES_DIR = Path(__file__).parent / "samples"
# Shown as "Try a sample" buttons on the landing page so a first-time
# visitor can see the tool in action without needing a file of their own.
SAMPLE_FILES = {
    "ccda": ("sample_ccda.xml", "C-CDA clinical record"),
    "fhir-xml": ("sample_patient_fhir.xml", "FHIR patient (XML)"),
    "fhir-json": ("sample_bundle.json", "FHIR bundle (JSON)"),
    "hl7v2": ("sample_message.hl7", "HL7 v2.x message"),
}

app = Flask(__name__)
# Set SECRET_KEY in the deployment environment for a stable value (so
# signed cookies survive a redeploy); falling back to a random per-process
# key locally is fine since nothing here relies on sessions surviving a
# restart.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
# Vercel's own request body limit (4.5 MB on the Hobby plan) is hit before
# this ever would be, so this just makes the app's own limit realistic
# instead of promising a 25 MB upload that the platform would reject first.
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB

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
    return render_template("index.html", last_visit=_read_last_visit(), samples=SAMPLE_FILES)


@app.errorhandler(413)
def too_large(e):
    flash("That file is too large -- please choose one under 4 MB.")
    return redirect(url_for("index"))


def _render_document(filename, raw_bytes):
    """Detect the format, parse it, and render the matching result page.

    Shared by /upload (a real uploaded file) and /sample/<key> (one of the
    bundled sample files) so both go through identical parsing/error
    handling -- a sample is just a file whose bytes came from disk instead
    of a browser upload.
    """
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
                f"Could not identify the format of '{filename}'. "
                "Expected a C-CDA XML document, an HL7 v2.x message (starting with MSH|), "
                "or a FHIR resource/Bundle (JSON or XML)."
            )
            return redirect(url_for("index"))
    except ET.ParseError as e:
        flash(f"'{filename}' looked like XML but failed to parse: {e}")
        return redirect(url_for("index"))
    except DefusedXmlException:
        flash(
            f"'{filename}' was rejected: it defines XML entities in a way "
            "that's blocked as a safety measure (this stops maliciously crafted files "
            "from consuming excessive memory during parsing)."
        )
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Failed to parse '{filename}': {type(e).__name__}: {e}")
        return redirect(url_for("index"))

    template = {
        FORMAT_CCDA: "result_ccda.html",
        FORMAT_HL7V2: "result_hl7v2.html",
        FORMAT_FHIR_JSON: "result_fhir.html",
        FORMAT_FHIR_XML: "result_fhir.html",
    }[fmt]

    response = make_response(render_template(template, filename=filename, doc=result))

    # We don't keep the parsed record on the server (nothing is persisted
    # beyond this request), so this cookie can only remember what the file
    # was called and when it was viewed -- not restore the file itself.
    cookie_value = quote(json.dumps({
        "filename": filename,
        "format_label": FORMAT_DISPLAY_NAMES.get(fmt, "a health record"),
        "viewed_at": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
    }))
    response.set_cookie(LAST_VISIT_COOKIE, cookie_value, max_age=60 * 60 * 24 * 30)
    return response


@app.route("/upload", methods=["POST"])
def upload():
    uploaded = request.files.get("document")
    if not uploaded or uploaded.filename == "":
        flash("Choose a file first.")
        return redirect(url_for("index"))
    return _render_document(uploaded.filename, uploaded.read())


@app.route("/sample/<key>")
def sample(key):
    entry = SAMPLE_FILES.get(key)
    if not entry:
        abort(404)
    filename, _label = entry
    path = SAMPLES_DIR / filename
    return _render_document(filename, path.read_bytes())


if __name__ == "__main__":
    # This block only runs for `python app.py` (local dev / a real server
    # process); Vercel imports the `app` object directly and never executes
    # it, so DEBUG defaults off and has to be opted into explicitly.
    app.run(debug=os.environ.get("DEBUG") == "1", port=5057)
