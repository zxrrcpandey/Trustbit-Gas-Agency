frappe.ui.form.on("Sales Invoice", {
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
                        source_doctype: "Sales Invoice",
                        source_name: frm.doc.name,
                    });
                },
                __("Gas Agency")
            );
        }

        if (frm.doc.docstatus === 1 && !frm.doc.is_return) {
            show_credit_type(frm);

            if (
                frm.doc.pending_empties > 0 &&
                frappe.perm.has_perm("Sales Invoice", 0, "submit")
            ) {
                frm.add_custom_button(
                    __("Receive Empties"),
                    () => receive_empties(frm),
                    __("Gas Agency")
                );
            }
        }
    },
});

function show_credit_type(frm) {
    const amount_pending = frm.doc.outstanding_amount > 0;
    const cylinder_pending = frm.doc.pending_empties > 0;
    if (!amount_pending && !cylinder_pending) return;

    let type = __("Amount Pending");
    if (amount_pending && cylinder_pending) type = __("Both Pending");
    else if (cylinder_pending) type = __("Cylinder Pending");

    frm.set_intro(__("Credit Sale: {0}", [type]), "orange");
}

function receive_empties(frm) {
    frappe
        .call({
            method: "trustbit_gas_agency.utils.cylinder_exchange.list_pending_empties",
            args: { sales_invoice: frm.doc.name },
        })
        .then((r) => {
            const pending = r.message || [];
            if (!pending.length) {
                frappe.msgprint(__("No empties are pending on this invoice"));
                return;
            }

            const dialog = new frappe.ui.Dialog({
                title: __("Receive Empties"),
                fields: pending.map((row, i) => ({
                    fieldname: "qty_" + i,
                    fieldtype: "Float",
                    label: row.item_name || row.empty_item,
                    description: __("{0} pending", [row.qty]),
                    default: row.qty,
                })),
                primary_action_label: __("Receive"),
                primary_action(values) {
                    const empties = {};
                    pending.forEach((row, i) => {
                        if (values["qty_" + i] > 0) empties[row.empty_item] = values["qty_" + i];
                    });
                    frappe
                        .call({
                            method: "trustbit_gas_agency.utils.cylinder_exchange.receive_empties",
                            args: { sales_invoice: frm.doc.name, empties: empties },
                            freeze: true,
                        })
                        .then((r) => {
                            dialog.hide();
                            frappe.show_alert({
                                message: __("Empties received via {0}", [r.message]),
                                indicator: "green",
                            });
                            frm.reload_doc();
                        });
                },
            });
            dialog.show();
        });
}

frappe.ui.form.on("Sales Invoice Item", {
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
