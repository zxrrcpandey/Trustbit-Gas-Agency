frappe.query_reports["Cylinder Stock Summary"] = {
    filters: [
        {
            fieldname: "location",
            label: __("Location"),
            fieldtype: "Link",
            options: "Gas Agency Location",
        },
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_default("company"),
        },
    ],
};
