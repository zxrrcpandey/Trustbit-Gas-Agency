frappe.ui.form.on("Delivery Note", {
    refresh: function (frm) {
        // Show cylinder exchange info if location is set
        if (
            frm.doc.gas_agency_location &&
            frm.doc.docstatus === 1 &&
            frappe.model.can_read("Cylinder Exchange Log")
        ) {
            frm.add_custom_button(
                __("View Exchange Logs"),
                function () {
                    frappe.set_route("List", "Cylinder Exchange Log", {
                        source_doctype: "Delivery Note",
                        source_name: frm.doc.name,
                    });
                },
                __("Gas Agency")
            );
        }
    },
});

frappe.ui.form.on("Delivery Note Item", {
    item_code: function (frm, cdt, cdn) {
        var row = locals[cdt][cdn];
        if (row.item_code) {
            // Check if this item has a Cylinder Exchange Rule
            frappe.db.get_value(
                "Cylinder Exchange Rule",
                { name: row.item_code, is_active: 1 },
                ["name", "empty_item"],
                function (data) {
                    if (data && data.name) {
                        frappe.model.set_value(cdt, cdn, "is_gas_cylinder", 1);
                        frappe.model.set_value(
                            cdt,
                            cdn,
                            "cylinder_exchange_rule",
                            data.name
                        );
                    } else {
                        frappe.model.set_value(cdt, cdn, "is_gas_cylinder", 0);
                        frappe.model.set_value(
                            cdt,
                            cdn,
                            "cylinder_exchange_rule",
                            ""
                        );
                    }
                }
            );
        }
    },
});
