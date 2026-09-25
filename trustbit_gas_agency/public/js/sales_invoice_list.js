// A submitted sale that still owes money or empties shows its credit type
// (Amount / Cylinder / Both Pending) in place of ERPNext's payment status.
// Clicking the label lists every invoice of that type.
(() => {
    const settings = (frappe.listview_settings["Sales Invoice"] =
        frappe.listview_settings["Sales Invoice"] || {});
    const erpnext_indicator = settings.get_indicator;
    settings.add_fields = (settings.add_fields || []).concat([
        "outstanding_amount",
        "pending_empties",
        "is_return",
    ]);

    settings.get_indicator = function (doc) {
        if (doc.docstatus === 1 && !doc.is_return) {
            const amount_pending = doc.outstanding_amount > 0;
            const cylinder_pending = doc.pending_empties > 0;
            const sales = "docstatus,=,1|is_return,=,0|";

            if (amount_pending && cylinder_pending) {
                return [
                    __("Both Pending"),
                    "red",
                    sales + "outstanding_amount,>,0|pending_empties,>,0",
                ];
            }
            if (amount_pending) {
                return [
                    __("Amount Pending"),
                    "orange",
                    sales + "outstanding_amount,>,0|pending_empties,=,0",
                ];
            }
            if (cylinder_pending) {
                return [
                    __("Cylinder Pending"),
                    "purple",
                    sales + "outstanding_amount,<=,0|pending_empties,>,0",
                ];
            }
        }
        return erpnext_indicator && erpnext_indicator(doc);
    };
})();
