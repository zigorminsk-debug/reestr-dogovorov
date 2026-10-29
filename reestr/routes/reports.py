from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request, send_file

from ..db import get_db
from ..domain import ValidationError, parse_iso_date
from ..exporters import export_report
from ..query import load_contracts
from ..reports import REPORT_TYPES, build_report


bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def current_report(report_type: str) -> dict:
    if report_type not in REPORT_TYPES:
        raise KeyError(report_type)
    filters = request.args.to_dict()
    date_fields = {
        "counterparties": "contract_date",
        "payments": "payment_due_date",
        "overdue": "payment_due_date",
    }
    filters["date_field"] = date_fields[report_type]
    for field in ("date_from", "date_to"):
        if filters.get(field):
            try:
                filters[field] = parse_iso_date(filters[field])
            except ValueError as exc:
                raise ValidationError({field: str(exc)}) from exc
    if filters.get("date_from") and filters.get("date_to"):
        if filters["date_from"] > filters["date_to"]:
            raise ValidationError({"date_to": "Дата окончания раньше даты начала"})
    if report_type == "overdue" and not filters.get("status"):
        filters["status"] = "overdue"
    items = load_contracts(get_db(), filters)
    return build_report(report_type, items, filters)


@bp.get("/<report_type>")
def report_json(report_type: str):
    try:
        report = current_report(report_type)
    except KeyError:
        return jsonify({"error": "Неизвестный вид отчёта"}), 404
    return jsonify(report)


@bp.get("/<report_type>/export/<file_format>")
def report_export(report_type: str, file_format: str):
    try:
        report = current_report(report_type)
    except KeyError:
        return jsonify({"error": "Неизвестный вид отчёта"}), 404
    try:
        output, mimetype, extension = export_report(report, file_format)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    filename = f"otchet_{report_type}_{date.today().isoformat()}.{extension}"
    return send_file(output, as_attachment=True, download_name=filename, mimetype=mimetype)
