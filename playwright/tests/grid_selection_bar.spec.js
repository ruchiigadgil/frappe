import { test, expect } from "../support";

test.describe("Grid Selection Bar", () => {
	test.beforeAll(async ({ admin }) => {
		await admin.call("frappe.tests.ui_test_helpers.create_contact_phone_nos_records");
	});

	test.beforeEach(async ({ page }) => {
		await page.goto("/desk/contact/Test Contact");
	});

	const get_table = (page) => page.locator('.frappe-control[data-fieldname="phone_nos"]');
	const get_bar = (page) => get_table(page).locator(".grid-selection-bar");
	const select_page = (page) =>
		get_table(page).locator(".grid-heading-row .grid-row-check").click();

	test("replaces the footer while rows are selected", async ({ page }) => {
		const table = get_table(page);
		const row_check = table.locator('.grid-row[data-idx="1"] .grid-row-check');

		await row_check.click();
		await expect(get_bar(page)).toContainText("1 row selected");
		await expect(table.locator(".grid-footer")).toBeHidden();

		await row_check.click();
		await expect(get_bar(page)).toBeHidden();
		await expect(table.locator(".grid-footer")).toBeVisible();
	});

	test("header checkbox selects only the current page", async ({ page }) => {
		const table = get_table(page);
		const bar = get_bar(page);

		await select_page(page);
		await expect(bar).toContainText("50 rows selected");

		await expect(bar.locator(".grid-selection-page")).toHaveText("1 of 20");
		await expect(bar.getByRole("button", { name: "Previous page" })).toBeDisabled();
		await bar.getByRole("button", { name: "Next page" }).click();
		await expect(bar.locator(".grid-selection-page")).toHaveText("2 of 20");
		await expect(table.locator(".grid-body .grid-row-check:checked")).toHaveCount(0);
		await expect(table.locator(".grid-heading-row .grid-row-check")).not.toBeChecked();
		await expect(bar).toContainText("50 rows selected");
	});

	test("select all selects rows on every page and clear resets", async ({ page }) => {
		const bar = get_bar(page);

		await select_page(page);
		await bar.getByRole("button", { name: "Select all" }).click();
		await expect(bar).toContainText("1000 rows selected");
		await expect(bar.getByRole("button", { name: "Select all" })).toBeDisabled();

		await bar.getByRole("button", { name: "Clear selection" }).click();
		await expect(bar).toBeHidden();
		await expect(get_table(page).locator(".grid-row-check:checked")).toHaveCount(0);
	});

	test("asks before deleting selected rows", async ({ page }) => {
		const table = get_table(page);

		await table.locator('.grid-row[data-idx="1"] .grid-row-check').click();
		await table.locator('.grid-row[data-idx="2"] .grid-row-check').click();
		await get_bar(page).getByRole("button", { name: "Actions" }).click();
		await page.locator('.es-menu [role="menuitem"]', { hasText: "Delete" }).click();

		const dialog = page.locator(".modal-dialog:visible");
		await expect(dialog).toContainText("Are you sure you want to delete 2 rows?");
		await dialog.getByRole("button", { name: "Yes" }).click();

		await expect.poll(() => page.evaluate(() => cur_frm.doc.phone_nos.length)).toBe(998);
		await expect(get_bar(page)).toBeHidden();
	});
});
