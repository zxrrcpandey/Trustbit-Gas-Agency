import frappe


def validate(doc, method=None):
    """Fill blank Broker and Vehicle from the first Sales Invoice in the references."""
    if doc.broker and doc.gas_vehicle:
        return

    invoice = next(
        (
            ref.reference_name
            for ref in doc.references
            if ref.reference_doctype == "Sales Invoice" and ref.reference_name
        ),
        None,
    )
    if not invoice:
        return

    values = frappe.db.get_value(
        "Sales Invoice", invoice, ["broker", "gas_vehicle"], as_dict=True
    ) or {}
    doc.broker = doc.broker or values.get("broker")
    doc.gas_vehicle = doc.gas_vehicle or values.get("gas_vehicle")
