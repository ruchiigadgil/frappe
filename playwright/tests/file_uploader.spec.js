import fs from "fs";
import path from "path";
import { test, expect } from "../support";
import { Api } from "../support/api";
import { site_url } from "../support/config";

const example_file = path.join(__dirname, "../fixtures/example.json");

async function open_upload_dialog(page, desk) {
	await page.evaluate(() => {
		new frappe.ui.FileUploader();
	});
	await page.waitForFunction(() => window.cur_dialog && cur_dialog.$wrapper.is(":visible"));
	return desk.get_open_dialog();
}

async function drop_example_file(page, dialog) {
	const content = fs.readFileSync(example_file).toString("base64");
	const data_transfer = await page.evaluateHandle((content) => {
		const data_transfer = new DataTransfer();
		const bytes = Uint8Array.from(atob(content), (char) => char.charCodeAt(0));
		data_transfer.items.add(new File([bytes], "example.json", { type: "application/json" }));
		return data_transfer;
	}, content);
	await dialog.locator(".file-upload-area").dispatchEvent("drop", {
		dataTransfer: data_transfer,
	});
}

const wait_for_upload = (page) =>
	page.waitForResponse(
		(res) => res.request().method() === "POST" && res.url().includes("/api/method/upload_file")
	);

test.describe("FileUploader", () => {
	test.beforeEach(async ({ page, desk }) => {
		await desk.login("Administrator");
		await page.goto("/desk");
		await desk.ready();
	});

	test("upload dialog api works", async ({ page, desk }) => {
		const dialog = await open_upload_dialog(page, desk);
		await expect(dialog).toContainText("Drag and drop files");
		await desk.hide_dialog();
	});

	test("should accept dropped files", async ({ page, desk }) => {
		const dialog = await open_upload_dialog(page, desk);

		await drop_example_file(page, dialog);

		await expect(dialog.locator(".file-name")).toContainText("example.json");
		const upload_file = wait_for_upload(page);
		await dialog.getByRole("button", { name: "Upload", exact: true }).click();
		expect((await upload_file).status()).toBe(200);
		await expect(page.locator(".modal:visible")).toHaveCount(0);
	});

	test("should accept uploaded files", async ({ page, desk, api }) => {
		const uploaded = await page.request.post("/api/method/upload_file", {
			headers: await api.headers(),
			multipart: {
				file: {
					name: "example.json",
					mimeType: "application/json",
					buffer: fs.readFileSync(example_file),
				},
				is_private: "1",
			},
		});
		expect(uploaded.status()).toBe(200);

		const dialog = await open_upload_dialog(page, desk);

		await dialog.getByRole("button", { name: "Library", exact: true }).click();
		await page
			.getByPlaceholder("Search by filename or extension", { exact: true })
			.pressSequentially("example.json");
		await desk.get_open_dialog().getByText("example.json", { exact: true }).first().click();
		const upload_file = wait_for_upload(page);
		await desk.get_open_dialog().getByRole("button", { name: "Upload", exact: true }).click();
		const response = await (await upload_file).json();
		expect(response.message).toHaveProperty("file_name", "example.json");
		await expect(page.locator(".modal:visible")).toHaveCount(0);
	});

	test.describe("Public file upload restriction", () => {
		const test_user = "test_file_uploader@example.com";
		const test_password = "test_password";
		const setting = "only_allow_system_managers_to_upload_public_files";
		let original_setting;

		const set_restriction = (admin, value) =>
			admin.set_value("System Settings", "System Settings", { [setting]: value });

		const open_desk_with_restriction = async (page, desk, value) => {
			await page.goto("/desk");
			await desk.ready();
			await page.evaluate(
				([setting, value]) => {
					frappe.boot.sysdefaults[setting] = value;
				},
				[setting, value]
			);
		};

		const open_dialog_with_file = async (page, desk) => {
			const dialog = await open_upload_dialog(page, desk);
			await drop_example_file(page, dialog);
			await expect(dialog.locator(".file-preview")).toBeAttached();
			return dialog;
		};

		test.beforeAll(async ({ admin }) => {
			original_setting = (await admin.get_doc("System Settings", "System Settings")).data[
				setting
			];
			await admin.call("frappe.tests.ui_test_helpers.create_test_user", {
				username: test_user,
			});
			await admin.call("frappe.tests.ui_test_helpers.add_remove_role", {
				action: "remove",
				user: test_user,
				role: "System Manager",
			});
			await admin.set_value("User", test_user, { new_password: test_password });
		});

		test.afterAll(async ({ admin }) => {
			await set_restriction(admin, original_setting);
			await admin.remove_doc("User", test_user, true);
		});

		test("should show checkbox and toggle when setting is disabled for System Manager", async ({
			page,
			desk,
			admin,
		}) => {
			await set_restriction(admin, 0);
			await open_desk_with_restriction(page, desk, 0);

			const dialog = await open_dialog_with_file(page, desk);

			await expect(dialog.locator("#uploader-private-checkbox")).toBeVisible();
			await expect(dialog.locator("#uploader-private-checkbox input")).toBeEnabled();

			const toggle_button = dialog.locator(".modal-footer .btn-modal-secondary");
			await expect(toggle_button).toBeVisible();
			await expect(toggle_button).toContainText("Set all");

			await desk.hide_dialog();
		});

		test("should show checkbox and toggle when setting is disabled for non-System Manager", async ({
			page,
			desk,
			admin,
		}) => {
			await set_restriction(admin, 0);

			await desk.login(test_user, test_password);
			await open_desk_with_restriction(page, desk, 0);

			const dialog = await open_dialog_with_file(page, desk);

			await expect(dialog.locator("#uploader-private-checkbox")).toBeVisible();
			await expect(dialog.locator("#uploader-private-checkbox input")).toBeEnabled();

			const toggle_button = dialog.locator(".modal-footer .btn-modal-secondary");
			await expect(toggle_button).toBeVisible();
			await expect(toggle_button).toContainText("Set all");

			await desk.hide_dialog();
		});

		test("should show checkbox and toggle when setting is enabled for System Manager", async ({
			page,
			desk,
			admin,
		}) => {
			await set_restriction(admin, 1);
			await open_desk_with_restriction(page, desk, 1);

			const dialog = await open_dialog_with_file(page, desk);

			await expect(dialog.locator("#uploader-private-checkbox")).toBeVisible();
			await expect(dialog.locator("#uploader-private-checkbox input")).toBeEnabled();

			const toggle_button = dialog.locator(".modal-footer .btn-modal-secondary");
			await expect(toggle_button).toBeVisible();
			await expect(toggle_button).toContainText("Set all");

			await desk.hide_dialog();
		});

		test("should show disabled checkbox and hide toggle when setting is enabled for non-System Manager", async ({
			page,
			desk,
			admin,
		}) => {
			await set_restriction(admin, 1);

			await desk.login(test_user, test_password);
			await open_desk_with_restriction(page, desk, 1);

			const dialog = await open_dialog_with_file(page, desk);

			await expect(dialog.locator("#uploader-private-checkbox")).toBeVisible();
			await expect(dialog.locator("#uploader-private-checkbox input")).toBeDisabled();

			await expect(dialog.locator(".modal-footer .btn-modal-secondary")).toBeHidden();

			await desk.hide_dialog();
		});
	});
});

test.describe("FileUploader library files", () => {
	test.describe.configure({ mode: "serial" });

	const test_user = "test_library_picker@example.com";
	const test_password = "test_password";
	const sample_image = path.join(__dirname, "../fixtures/sample_image.jpg");
	const library = {
		image: "library_picker_image.jpg",
		csv: "library_picker_rows.csv",
		link: "library_picker_link.jpg",
	};
	let errors = [];

	const card = (dialog) => dialog.locator(".file-preview-outline");

	async function add_library_files(playwright, base_url) {
		const request = await playwright.request.newContext({ baseURL: base_url });
		const login = await request.post("/api/method/login", {
			data: { usr: test_user, pwd: test_password },
		});
		expect(login.status()).toBe(200);
		const api = new Api(request);
		await add_library_file(api, library.image, fs.readFileSync(sample_image), 0);
		await add_library_file(api, library.csv, Buffer.from("Weight\n5\n6\n"), 1);
		await api.insert_doc("File", {
			file_name: library.link,
			file_url: "https://example.com/library_picker_link.jpg",
			folder: "Home",
		});
		await request.dispose();
	}

	async function add_library_file(api, file_name, buffer, is_private) {
		const res = await api.request.post("/api/method/upload_file", {
			headers: await api.headers(),
			multipart: {
				file: { name: file_name, mimeType: "application/octet-stream", buffer },
				is_private: String(is_private),
				folder: "Home",
			},
		});
		expect(res.status()).toBe(200);
	}

	async function pick_from_library(dialog, file_name) {
		await dialog.getByRole("button", { name: "Library", exact: true }).click();
		await dialog.getByPlaceholder("Search by filename or extension").fill(file_name);
		await dialog.locator(".tree-label", { hasText: file_name }).first().click();
	}

	test.beforeAll(async ({ admin, playwright }, workerInfo) => {
		await admin.call("frappe.tests.ui_test_helpers.create_test_user", {
			username: test_user,
		});
		await admin.call("frappe.tests.ui_test_helpers.add_remove_role", {
			action: "remove",
			user: test_user,
			role: "System Manager",
		});
		await admin.set_value("User", test_user, { new_password: test_password });
		await add_library_files(playwright, site_url(workerInfo.parallelIndex));
	});

	test.afterAll(async ({ admin }) => {
		const { data } = await admin.get_list("File", ["name"], [["owner", "=", test_user]]);
		for (const file of data) await admin.remove_doc("File", file.name, true);
		await admin.remove_doc("User", test_user, true);
	});

	test.beforeEach(async ({ page, desk }) => {
		errors = [];
		page.on("pageerror", (error) => errors.push(error.message));
		await desk.login(test_user, test_password);
		await page.goto("/desk");
		await desk.ready();
	});

	test.afterEach(async () => {
		expect(errors).toEqual([]);
	});

	test("shows a library image as a card with its thumbnail and size", async ({ page, desk }) => {
		const dialog = await open_upload_dialog(page, desk);
		await pick_from_library(dialog, library.image);

		await expect(card(dialog)).toHaveCount(1);
		await expect(card(dialog).locator(".file-icon img")).toHaveAttribute(
			"src",
			/\/files\/library_picker_image.*\.jpg$/
		);
		await expect(card(dialog).locator(".file-size")).toHaveText(/\d/);
		await expect(dialog.locator("#uploader-private-checkbox")).toHaveCount(0);
		await expect(dialog.locator("#uploader-optimize-checkbox")).toHaveCount(0);
		await expect(card(dialog).locator(".alert-warning")).toHaveCount(0);

		const upload_file = wait_for_upload(page);
		await dialog.getByRole("button", { name: "Upload", exact: true }).click();
		const response = await upload_file;
		expect(response.status()).toBe(200);
		expect((await response.json()).message.is_private).toBe(0);
	});

	test("shows a library csv without optimize and keeps it private", async ({ page, desk }) => {
		const dialog = await open_upload_dialog(page, desk);
		await pick_from_library(dialog, library.csv);

		await expect(card(dialog)).toHaveCount(1);
		await expect(card(dialog).locator(".file-icon img")).toHaveCount(0);
		await expect(dialog.locator("#uploader-optimize-checkbox")).toHaveCount(0);

		const upload_file = wait_for_upload(page);
		await dialog.getByRole("button", { name: "Upload", exact: true }).click();
		const response = await upload_file;
		expect(response.status()).toBe(200);
		expect((await response.json()).message.is_private).toBe(1);
	});

	test("shows an external library link without a thumbnail or size", async ({ page, desk }) => {
		const dialog = await open_upload_dialog(page, desk);
		await pick_from_library(dialog, library.link);

		await expect(card(dialog)).toHaveCount(1);
		await expect(card(dialog).locator(".file-icon img")).toHaveCount(0);
		await expect(card(dialog).locator(".file-size")).toHaveText("");
		await desk.hide_dialog();
	});

	test("hides Set all while only library files are picked", async ({ page, desk }) => {
		const dialog = await open_upload_dialog(page, desk);
		await pick_from_library(dialog, library.csv);

		await expect(card(dialog)).toHaveCount(1);
		await expect(dialog.locator(".modal-footer .btn-modal-secondary")).toBeHidden();

		await drop_example_file(page, dialog);
		await expect(card(dialog)).toHaveCount(2);
		await expect(dialog.locator(".modal-footer .btn-modal-secondary")).toBeVisible();
		await desk.hide_dialog();
	});
});
