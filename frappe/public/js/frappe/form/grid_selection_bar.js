// Floating bar for bulk actions on selected rows. While rows are selected it
// replaces the grid footer, so it carries its own compact pager.
export default class GridSelectionBar {
	constructor(grid) {
		this.grid = grid;
		this.make();
	}

	refresh() {
		const count = this.grid.get_selected_children().length;
		this.grid.wrapper.toggleClass("grid-has-selection", count > 0);
		this.$label.text(count === 1 ? __("1 row selected") : __("{0} rows selected", [count]));
		this.$select_all.prop("disabled", count === this.grid.data.length);
		this.refresh_pager();
	}

	debounced_refresh = frappe.utils.debounce(() => this.refresh(), 100);

	select_all(checked) {
		this.grid.data.forEach((doc) => (doc.__checked = checked ? 1 : 0));
		this.grid.grid_rows.forEach((row) => row.refresh_check());
		this.grid.grid_pagination.update_select_all_checkbox();
		this.refresh();
	}

	go_to_page(step) {
		const pagination = this.grid.grid_pagination;
		pagination.go_to_page(pagination.page_index + step);
		this.refresh_pager();
	}

	delete_rows() {
		const { grid } = this;
		const count = grid.get_selected_children().length;

		// rows on unvisited pages have no GridRow, so only delete_all_rows reaches them
		if (grid.frm && count === grid.data.length) {
			grid.delete_all_rows();
		} else {
			frappe.confirm(__("Are you sure you want to delete {0} rows?", [count]), () =>
				grid.delete_rows()
			);
		}
	}

	get_actions() {
		const { grid } = this;
		const can_add_rows = !(grid.cannot_add_rows || grid.df.cannot_add_rows);

		return [
			grid.frm &&
				grid.meta?.allow_bulk_edit && {
					label: __("Edit"),
					icon: "pen",
					onclick: () => grid.bulk_edit_rows(),
				},
			can_add_rows && {
				label: __("Duplicate"),
				icon: "copy",
				onclick: () => grid.duplicate_rows(),
			},
			!grid.df.cannot_delete_rows && {
				label: __("Delete"),
				icon: "trash",
				theme: "red",
				onclick: () => this.delete_rows(),
			},
		].filter(Boolean);
	}

	refresh_pager() {
		const { page_index, page_length } = this.grid.grid_pagination;
		const total_pages = Math.ceil(this.grid.data.length / page_length);

		this.$pager.toggle(total_pages > 1);
		this.$page.html(`${page_index} <span>${__("of")}</span> ${total_pages}`);
		this.$prev.prop("disabled", page_index <= 1);
		this.$next.prop("disabled", page_index >= total_pages);
	}

	make() {
		this.$label = $(`<span class="grid-selection-label"></span>`);
		this.$select_all = this.make_button({
			label: __("Select all"),
			onclick: () => this.select_all(true),
		});

		this.$wrapper = $(`<div class="grid-selection-bar"></div>`)
			.append(
				$(`<input type="checkbox" checked disabled>`),
				this.$label,
				this.make_pager(),
				frappe.ui.dropdown({
					button: { icon: "ellipsis", variant: "ghost", title: __("Actions") },
					options: () => this.get_actions(),
					side: "top",
					align: "start",
				}),
				frappe.ui.divider({ orientation: "vertical", flex_item: true }),
				this.$select_all,
				this.make_button({
					icon: "x",
					title: __("Clear selection"),
					onclick: () => this.select_all(false),
				})
			)
			.insertAfter(this.grid.wrapper.find(".grid-footer"));
	}

	make_pager() {
		this.$page = $(`<span class="grid-selection-page"></span>`);
		this.$prev = this.make_button({
			icon: "chevron-left",
			title: __("Previous page"),
			onclick: () => this.go_to_page(-1),
		});
		this.$next = this.make_button({
			icon: "chevron-right",
			title: __("Next page"),
			onclick: () => this.go_to_page(1),
		});

		this.$pager = $(`<div class="grid-selection-pager"></div>`).append(
			this.$prev,
			this.$page,
			this.$next
		);
		return this.$pager;
	}

	make_button(opts) {
		return frappe.ui.button({ variant: "ghost", ...opts });
	}
}
