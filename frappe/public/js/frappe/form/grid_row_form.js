export default class GridRowForm {
	constructor(opts) {
		$.extend(this, opts);
		this.wrapper = $('<div class="form-in-grid"></div>').appendTo(this.row.wrapper);
	}
	render() {
		var me = this;
		this.make_form();
		this.form_area.empty();
		frappe.utils.scroll_to(0, false, 0, this.wrapper.find(".grid-form-body"));

		this.layout = new frappe.ui.form.Layout({
			fields: this.row.docfields,
			body: this.form_area,
			no_submit_on_enter: true,
			frm: this.row.frm,
			grid: this.row.grid,
			grid_row: this.row,
			grid_row_form: this,
			is_child_table: true,
			doctype: this.row.grid.doctype,
		});
		this.layout.make();

		this.fields = this.layout.fields;
		this.fields_dict = this.layout.fields_dict;

		this.layout.refresh(this.row.doc);

		// copy get_query to fields
		for (var fieldname in this.row.grid.fieldinfo || {}) {
			var fi = this.row.grid.fieldinfo[fieldname];
			$.extend(me.fields_dict[fieldname], fi);
		}

		this.toggle_add_delete_button_display(this.wrapper);
		this.render_breadcrumbs();
		this.wrapper.toggleClass("nested-grid-form", this.is_nested_form());

		this.row.grid.open_grid_row = this;

		this.set_focus();
	}
	make_form() {
		if (!this.form_area) {
			let template = `<div class="grid-form-heading">
				<div class="grid-form-breadcrumbs hidden"></div>
				<div class="toolbar grid-header-toolbar">
					<span class="panel-title">
						${__("Editing Row")} #<span class="grid-form-row-index"></span></span>
					<span class="row-actions">
						${frappe.ui.button.html({
							icon: "x",
							title: __("Close"),
							css_class: "pull-right grid-collapse-row",
						})}
						${frappe.ui.button.html({
							label: __("Move"),
							css_class: "pull-right grid-move-row hidden-xs",
						})}
						${frappe.ui.button.html({
							icon: "copy",
							label: __("Duplicate"),
							css_class: "pull-right grid-duplicate-row hidden-xs",
						})}
						${frappe.ui.button.html({
							label: __("Insert Above"),
							css_class: "pull-right grid-insert-row hidden-xs",
						})}
						${frappe.ui.button.html({
							label: __("Insert Below"),
							css_class: "pull-right grid-insert-row-below hidden-xs",
						})}
						${frappe.ui.button.html({
							label: __("Delete"),
							theme: "red",
							css_class: "pull-right grid-delete-row",
						})}
					</span>
				</div>
			</div>
			<div class="grid-form-body">
				<div class="form-area"></div>
				<div class="grid-footer-toolbar hidden-xs flex justify-between">
					<div class="grid-shortcuts">
						<span> ${frappe.utils.icon("keyboard", "md")} </span>
						<span class="text-medium"> ${__("Shortcuts")}: </span>
						<kbd>${__("Ctrl + Up")}</kbd> . <kbd>${__("Ctrl + Down")}</kbd> . <kbd>${__("ESC")}</kbd>
					</div>
				</div>
			</div>`;

			$(template).appendTo(this.wrapper);
			this.form_area = this.wrapper.find(".form-area");
			this.row.set_row_index();
			this.set_form_events();
		}
	}
	set_form_events() {
		var me = this;
		this.wrapper.find(".grid-delete-row").on("click", function () {
			me.row.remove();
			return false;
		});
		this.wrapper.find(".grid-insert-row").on("click", function () {
			me.row.insert(true);
			return false;
		});
		this.wrapper.find(".grid-insert-row-below").on("click", function () {
			me.row.insert(true, true);
			return false;
		});
		this.wrapper.find(".grid-duplicate-row").on("click", function () {
			me.row.insert(true, true, true);
			return false;
		});
		this.wrapper.find(".grid-move-row").on("click", function () {
			me.row.move();
			return false;
		});
		this.wrapper.find(".grid-form-heading, .grid-footer-toolbar").on("click", function () {
			me.row.toggle_view();
			return false;
		});
	}
	render_breadcrumbs() {
		const $breadcrumbs = this.wrapper
			.children(".grid-form-heading")
			.find(".grid-form-breadcrumbs")
			.empty();
		const parent_rows = this.get_parent_rows();
		$breadcrumbs.toggleClass("hidden", !parent_rows.length);
		if (!parent_rows.length) return;

		const open_rows = [...parent_rows.slice(1), this.row];
		parent_rows.forEach((row, i) => {
			$(`<a class="grid-form-breadcrumb">${this.get_table_label(row)} #${row.doc.idx}</a>`)
				.on("click", () => {
					open_rows[i].toggle_view(false);
					return false;
				})
				.appendTo($breadcrumbs);
			$breadcrumbs.append(frappe.utils.icon("chevron-right", "xs"));
		});
		$breadcrumbs.append(`<span>${this.get_table_label(this.row)}</span>`);
	}
	is_nested_form() {
		return (
			this.get_parent_rows().length > 0 ||
			this.row.docfields.some((df) => df.fieldtype === "Table")
		);
	}
	get_parent_rows() {
		const rows = [];
		let $row = this.row.wrapper.parent().closest(".grid-row");
		while ($row.length) {
			rows.unshift($row.data("grid_row"));
			$row = $row.parent().closest(".grid-row");
		}
		return rows;
	}
	get_table_label(row) {
		const df = row.grid.df;
		return frappe.utils.escape_html(__(df.label || frappe.unscrub(df.fieldname)));
	}
	toggle_add_delete_button_display($parent) {
		$parent.find(".row-actions").toggle(this.row.grid.is_editable());
	}
	refresh_field(fieldname) {
		const field = this.fields_dict[fieldname];
		if (!field) return;

		field.docname = this.row.doc.name;
		field.refresh();
		this.layout && this.layout.refresh_dependency();
	}
	set_active_tab(tab) {
		// Store the active tab for this grid row form
		this.active_tab = tab;

		// When switching tabs in grid row forms, update field display for Geolocation/Signature fields
		// This is similar to the fix in frappe/frappe#27441 for regular forms
		let in_tab = false;
		for (const df of this.layout.fields) {
			const field = this.fields_dict[df.fieldname];
			if (df?.fieldtype === "Tab Break") {
				in_tab = df === tab?.df;
			} else if (typeof field?.on_section_collapse === "function") {
				field.on_section_collapse(!in_tab);
			}
		}
	}
	set_focus() {
		// wait for animation and then focus on the first row
		var me = this;
		setTimeout(function () {
			// a row opened inside this one meanwhile keeps the focus
			if (frappe.ui.form.get_open_grid_form() !== me.row) return;
			if ((me.row.frm && me.row.frm.doc.docstatus === 0) || !me.row.frm) {
				var first = me.form_area.find("input:first");
				if (
					first.length &&
					!["Date", "Datetime", "Time"].includes(first.attr("data-fieldtype"))
				) {
					try {
						first.get(0).focus();
					} catch (e) {
						//
					}
				}
			}
		}, 500);
	}
}
