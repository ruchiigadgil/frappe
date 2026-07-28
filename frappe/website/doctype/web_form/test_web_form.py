# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
import json

import frappe
from frappe.core.doctype.doctype.doctype import clear_permissions_cache
from frappe.permissions import add_permission, reset_perms
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, set_request
from frappe.website.doctype.web_form.web_form import (
	accept,
	delete,
	delete_multiple,
	get_form_data,
	get_link_options,
	get_web_form_list,
)
from frappe.website.serve import get_response_content

EXTRA_TEST_RECORD_DEPENDENCIES = ["Web Form"]


class TestWebForm(IntegrationTestCase):
	def setUp(self):
		frappe.conf.disable_website_cache = True

	def tearDown(self):
		frappe.conf.disable_website_cache = False
		frappe.local.request = None
		frappe.set_user("Administrator")

	def test_accept(self):
		frappe.set_user("Administrator")

		doc = {
			"doctype": "Event",
			"subject": "_Test Event Web Form",
			"description": "_Test Event Description",
			"starts_on": "2014-09-09",
		}

		accept(web_form="manage-events", data=json.dumps(doc))

		self.event_name = frappe.db.get_value("Event", {"subject": "_Test Event Web Form"})
		self.assertTrue(self.event_name)

	def test_accept_and_delete_multiple_accept_native_payloads(self):
		frappe.set_user("Administrator")

		# accept with a native dict instead of a JSON string (frappe.parse_json passthrough)
		accept(
			web_form="manage-events",
			data={
				"doctype": "Event",
				"subject": "_Test Event Web Form Native",
				"description": "_Test Event Description",
				"starts_on": "2014-09-09",
			},
		)
		event_name = frappe.db.get_value("Event", {"subject": "_Test Event Web Form Native"})
		self.assertTrue(event_name)

		web_form = frappe.get_doc("Web Form", "manage-events")
		web_form.allow_delete = 1
		web_form.save(ignore_permissions=True)

		# delete_multiple with a native list of docnames
		delete_multiple("manage-events", [event_name])
		self.assertFalse(frappe.db.exists("Event", event_name))

	def test_edit(self):
		self.test_accept()

		doc = {
			"doctype": "Event",
			"subject": "_Test Event Web Form",
			"description": "_Test Event Description 1",
			"starts_on": "2014-09-09",
			"name": self.event_name,
		}

		self.assertNotEqual(
			frappe.db.get_value("Event", self.event_name, "description"), doc.get("description")
		)

		accept("manage-events", json.dumps(doc))

		self.assertEqual(frappe.db.get_value("Event", self.event_name, "description"), doc.get("description"))

	def test_webform_render(self):
		set_request(method="GET", path="manage-events/new")
		content = get_response_content("manage-events/new")
		self.assertIn('<h1 class="ellipsis">New Manage Events</h1>', content)
		self.assertIn('data-doctype="Web Form"', content)
		self.assertIn('data-path="manage-events/new"', content)
		self.assertIn('source-type="Generator"', content)

	def test_webform_html_meta_is_added(self):
		set_request(method="GET", path="manage-events/new")
		content = self.normalize_html(get_response_content("manage-events/new"))

		self.assertIn(self.normalize_html('<meta name="title" content="Test Meta Form Title">'), content)
		self.assertIn(
			self.normalize_html('<meta property="og:title" content="Test Meta Form Title">'), content
		)
		self.assertIn(
			self.normalize_html('<meta property="og:description" content="Test Meta Form Description">'),
			content,
		)
		self.assertIn(
			self.normalize_html('<meta property="og:image" content="https://frappe.io/files/frappe.png">'),
			content,
		)

	def test_web_form_request_renders_prefilled_values_for_guest(self):
		self.set_web_form_settings(key_required=1, login_required=0)
		web_form_request = self.create_web_form_request(
			web_form_values={
				"subject": "_Test Request Prefill",
				"starts_on": "2026-05-10",
			},
			doc_values={"description": "_Test Hidden Request Value"},
		)

		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict(web_form_request_key=web_form_request.key)
		set_request(
			method="GET",
			path="manage-events/new",
			query_string=f"web_form_request_key={web_form_request.key}",
		)
		content = get_response_content("manage-events/new")

		self.assertIn("_Test Request Prefill", content)
		self.assertIn(web_form_request.key, content)
		self.assertNotIn("_Test Hidden Request Value", content)

	def test_web_form_request_allows_guest_submission_once(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_edit=0, allow_multiple=0)
		web_form_request = self.create_web_form_request(
			doc_values={
				"event_type": "Public",
				"event_category": "Meeting",
			}
		)

		frappe.set_user("Guest")
		doc = {
			"doctype": "Event",
			"subject": "_Test Request Submission",
			"description": "_Test Visible Description",
			"starts_on": "2026-05-10",
		}

		event = accept(
			web_form="manage-events",
			data=json.dumps(doc),
			web_form_request_key=web_form_request.key,
		)

		self.assertEqual(event.event_type, "Public")
		self.assertEqual(event.event_category, "Meeting")
		self.assertEqual(event.description, "_Test Visible Description")

		web_form_request.reload()
		self.assertTrue(web_form_request.first_used_on)
		self.assertEqual([row.link_name for row in web_form_request.references], [event.name])

		with self.assertRaises(frappe.exceptions.LinkExpired):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"subject": "_Test Request Submission Again",
						"starts_on": "2026-05-10",
					}
				),
				web_form_request_key=web_form_request.key,
			)

	def test_one_time_key_allows_list_page_after_submission(self):
		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			allow_multiple=0,
			show_list=1,
		)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test One Time List",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		rows = get_web_form_list(
			web_form="manage-events",
			web_form_request_key=web_form_request.key,
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["subject"], "_Test One Time List")

		frappe.local.form_dict = frappe._dict(
			is_list=1,
			web_form_request_key=web_form_request.key,
		)
		set_request(
			method="GET",
			path="manage-events/list",
			query_string=f"web_form_request_key={web_form_request.key}",
		)
		content = get_response_content("manage-events/list")

		self.assertIn(web_form_request.key, content)

	def test_key_required_rejects_submission_without_key(self):
		self.set_web_form_settings(key_required=1, login_required=0)

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"subject": "_Test Request Missing Key",
						"starts_on": "2026-05-10",
					}
				),
			)

	def test_login_required_needs_key_and_login(self):
		self.set_web_form_settings(key_required=1, login_required=1)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})
		doc = {
			"doctype": "Event",
			"subject": "_Test Request With Login",
			"starts_on": "2026-05-10",
		}

		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			accept(
				web_form="manage-events",
				data=json.dumps(doc),
				web_form_request_key=web_form_request.key,
			)

		frappe.set_user("Administrator")
		with self.assertRaises(frappe.PermissionError):
			accept(web_form="manage-events", data=json.dumps(doc))

		event = accept(
			web_form="manage-events",
			data=json.dumps(doc),
			web_form_request_key=web_form_request.key,
		)
		self.assertEqual(event.event_type, "Public")

	def test_web_form_request_can_edit_existing_response(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_edit=1, allow_multiple=0)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test Request Editable",
					"description": "_Test Before Edit",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"name": event.name,
					"subject": "_Test Request Editable",
					"description": "_Test After Edit",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		self.assertEqual(event.description, "_Test After Edit")

	def test_pre_seeded_reference_edit_consumes_one_time_key(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_edit=1, allow_multiple=0)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "_Test Seeded Edit",
				"starts_on": "2026-05-10",
			}
		).insert(ignore_permissions=True)
		web_form_request = self.create_web_form_request(reference_docname=event.name)

		frappe.set_user("Guest")
		event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"name": event.name,
					"subject": "_Test Seeded Edit",
					"description": "_Test Edited Description",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		self.assertEqual(event.description, "_Test Edited Description")

		web_form_request.reload()
		self.assertTrue(web_form_request.first_used_on)
		self.assertEqual([row.link_name for row in web_form_request.references], [event.name])

		with self.assertRaises(frappe.exceptions.LinkExpired):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"subject": "_Test Seeded Edit Again",
						"starts_on": "2026-05-10",
					}
				),
				web_form_request_key=web_form_request.key,
			)

	def test_web_form_request_rejects_edit_when_allow_edit_disabled(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_edit=0, allow_multiple=0)
		web_form_request = self.create_web_form_request()

		frappe.set_user("Guest")
		event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test Request No Edit",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		with self.assertRaises(frappe.ValidationError):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"name": event.name,
						"subject": "_Test Request No Edit",
						"description": "_Test Edited",
						"starts_on": "2026-05-10",
					}
				),
				web_form_request_key=web_form_request.key,
			)

		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "_Test Seeded No Edit",
				"starts_on": "2026-05-10",
			}
		).insert(ignore_permissions=True)
		web_form_request = self.create_web_form_request(reference_docname=event.name)

		with self.assertRaises(frappe.ValidationError):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"name": event.name,
						"subject": "_Test Seeded No Edit",
						"description": "_Test Edited",
						"starts_on": "2026-05-10",
					}
				),
				web_form_request_key=web_form_request.key,
			)

	def test_web_form_request_can_submit_multiple_responses(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_multiple=1)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		first_event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test Request Multiple 1",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)
		second_event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test Request Multiple 2",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		web_form_request.reload()
		self.assertNotEqual(first_event.name, second_event.name)
		self.assertTrue(web_form_request.first_used_on)
		self.assertEqual(
			sorted(row.link_name for row in web_form_request.references),
			sorted([first_event.name, second_event.name]),
		)

	def test_web_form_request_can_delete_existing_response(self):
		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			allow_edit=1,
			allow_multiple=0,
			allow_delete=1,
		)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test Request Delete",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		delete("manage-events", event.name, web_form_request_key=web_form_request.key)
		self.assertFalse(frappe.db.exists("Event", event.name))

	def test_public_form_ignores_invalid_request_key(self):
		self.set_web_form_settings(login_required=0, key_required=0)

		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict(web_form_request_key="bad")
		set_request(
			method="GET",
			path="manage-events/new",
			query_string="web_form_request_key=bad",
		)
		content = get_response_content("manage-events/new")

		self.assertIn('<h1 class="ellipsis">New Manage Events</h1>', content)

	def test_public_form_ignores_valid_leaked_key_for_delete(self):
		self.set_web_form_settings(
			login_required=0,
			key_required=0,
			allow_delete=1,
			allow_edit=1,
			allow_multiple=0,
		)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "_Test Leaked Key Delete Guard",
				"starts_on": "2026-05-10",
			}
		).insert(ignore_permissions=True)
		web_form_request = self.create_web_form_request(reference_docname=event.name)

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			delete("manage-events", event.name, web_form_request_key=web_form_request.key)

		with self.assertRaises(frappe.PermissionError):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"name": event.name,
						"subject": "_Test Leaked Key Edit Guard",
						"starts_on": "2026-05-10",
					}
				),
				web_form_request_key=web_form_request.key,
			)

		self.assertTrue(frappe.db.exists("Event", event.name))
		self.assertEqual(
			frappe.db.get_value("Event", event.name, "subject"),
			"_Test Leaked Key Delete Guard",
		)

	def test_guest_cannot_delete_on_public_form_without_key(self):
		self.set_web_form_settings(login_required=0, key_required=0, allow_delete=1)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "_Test Guest Delete Guard",
				"starts_on": "2026-05-10",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Event", event.name, "owner", "Guest")

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			delete("manage-events", event.name)

	def test_guest_reference_doc_exposes_only_web_form_fields(self):
		"""Guest with a valid key viewing a bound document must only receive
		web-form field values in reference_doc, not the full document."""
		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			allow_edit=1,
			allow_multiple=0,
		)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "_Test Restricted Reference",
				"starts_on": "2026-05-10",
				"description": "_Test visible description",
				"event_type": "Private",
			}
		).insert(ignore_permissions=True)
		web_form_request = self.create_web_form_request(reference_docname=event.name)

		frappe.set_user("Guest")
		frappe.local.path = f"manage-events/{event.name}/edit"
		frappe.local.form_dict = frappe._dict(
			name=event.name,
			is_edit=1,
			web_form_request_key=web_form_request.key,
		)
		context = frappe._dict()
		frappe.get_doc("Web Form", "manage-events").get_context(context)

		reference_doc = context.reference_doc
		web_form = frappe.get_doc("Web Form", "manage-events")
		allowed_fields = {"name", "doctype", *(f.fieldname for f in web_form.web_form_fields)}

		self.assertEqual(set(reference_doc.keys()), allowed_fields)
		self.assertEqual(reference_doc["subject"], "_Test Restricted Reference")
		self.assertEqual(reference_doc["description"], "_Test visible description")
		self.assertNotIn("event_type", reference_doc)
		self.assertNotIn("owner", reference_doc)
		self.assertNotIn("creation", reference_doc)

	def test_guest_with_valid_key_can_render_bound_document_page(self):
		"""A Guest holding a valid request key bound to a document must be able
		to render the view/edit page instead of being redirected to /new."""
		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			allow_edit=1,
			allow_multiple=0,
		)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "_Test Bound Render",
				"starts_on": "2026-05-10",
				"event_type": "Public",
			}
		).insert(ignore_permissions=True)
		web_form_request = self.create_web_form_request(reference_docname=event.name)

		self.addCleanup(lambda: setattr(frappe.local, "request", None))

		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict(
			web_form_request_key=web_form_request.key,
			name=event.name,
		)
		set_request(
			method="GET",
			path=f"manage-events/{event.name}/edit",
			query_string=f"web_form_request_key={web_form_request.key}",
		)
		content = get_response_content(f"manage-events/{event.name}/edit")

		self.assertIn("_Test Bound Render", content)
		self.assertIn(web_form_request.key, content)

	def test_allow_multiple_request_supports_edit_and_delete_of_own_submissions(self):
		"""A key for an `allow_multiple` form authorises the holder to edit and
		delete every document submitted with it, even without login."""
		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			allow_multiple=1,
			allow_edit=1,
			allow_delete=1,
		)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		first_event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test Multi Manage 1",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)
		second_event = accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test Multi Manage 2",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"name": first_event.name,
					"subject": "_Test Multi Manage Edited",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)
		self.assertEqual(
			frappe.db.get_value("Event", first_event.name, "subject"),
			"_Test Multi Manage Edited",
		)

		delete(
			"manage-events",
			second_event.name,
			web_form_request_key=web_form_request.key,
		)
		self.assertFalse(frappe.db.exists("Event", second_event.name))
		self.assertTrue(frappe.db.exists("Event", first_event.name))

	def test_allow_multiple_request_rejects_docname_based_access(self):
		"""A key for an `allow_multiple` web form has no bound document, so it
		must not be usable to read, edit, or delete arbitrary records."""
		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			allow_multiple=1,
			allow_edit=1,
			allow_delete=1,
		)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		existing_event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "_Test Existing Event",
				"starts_on": "2026-05-10",
				"event_type": "Private",
			}
		).insert(ignore_permissions=True)

		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"name": existing_event.name,
						"subject": "_Test Hijacked Subject",
						"starts_on": "2026-05-10",
					}
				),
				web_form_request_key=web_form_request.key,
			)

		with self.assertRaises(frappe.PermissionError):
			delete(
				"manage-events",
				existing_event.name,
				web_form_request_key=web_form_request.key,
			)

		self.assertEqual(
			frappe.db.get_value("Event", existing_event.name, "subject"),
			"_Test Existing Event",
		)
		self.assertTrue(frappe.db.exists("Event", existing_event.name))

	def test_web_form_request_expiry_is_enforced(self):
		self.set_web_form_settings(key_required=1, login_required=0)
		web_form_request = self.create_web_form_request(
			expires_on=add_to_date(None, minutes=-1),
			doc_values={"event_type": "Public"},
		)

		frappe.set_user("Guest")
		with self.assertRaises(frappe.exceptions.LinkExpired):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"subject": "_Test Expired Request",
						"starts_on": "2026-05-10",
					}
				),
				web_form_request_key=web_form_request.key,
			)

	def test_get_web_form_list_returns_only_bound_documents(self):
		"""The list endpoint returns documents in the request's references and
		rejects documents that were not submitted with the key."""
		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			allow_multiple=1,
			show_list=1,
		)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		first_event = accept(
			web_form="manage-events",
			data=json.dumps({"doctype": "Event", "subject": "_Test List Bound 1", "starts_on": "2026-05-10"}),
			web_form_request_key=web_form_request.key,
		)
		second_event = accept(
			web_form="manage-events",
			data=json.dumps({"doctype": "Event", "subject": "_Test List Bound 2", "starts_on": "2026-05-10"}),
			web_form_request_key=web_form_request.key,
		)

		frappe.set_user("Administrator")
		unrelated_event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "_Test List Unrelated",
				"starts_on": "2026-05-10",
				"event_type": "Public",
			}
		).insert(ignore_permissions=True)

		frappe.set_user("Guest")
		rows = get_web_form_list(
			web_form="manage-events",
			web_form_request_key=web_form_request.key,
		)
		returned_names = {row["name"] for row in rows}
		self.assertEqual(returned_names, {first_event.name, second_event.name})
		self.assertNotIn(unrelated_event.name, returned_names)

	def test_get_web_form_list_rejects_invalid_key(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_multiple=1, show_list=1)

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_web_form_list(web_form="manage-events", web_form_request_key="not-a-real-key")

	def test_get_web_form_list_requires_login_when_login_required(self):
		"""A valid key alone is not enough when the Web Form requires login;
		both conditions must be met."""
		self.set_web_form_settings(key_required=1, login_required=1, allow_multiple=1, show_list=1)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_web_form_list(web_form="manage-events", web_form_request_key=web_form_request.key)

	def test_get_web_form_list_rejects_when_show_list_disabled(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_multiple=1, show_list=0)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_web_form_list(web_form="manage-events", web_form_request_key=web_form_request.key)

	def test_get_web_form_list_rejects_expired_key(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_multiple=1, show_list=1)
		web_form_request = self.create_web_form_request(
			expires_on=add_to_date(None, minutes=-1),
			doc_values={"event_type": "Public"},
		)

		frappe.set_user("Guest")
		with self.assertRaises(frappe.exceptions.LinkExpired):
			get_web_form_list(web_form="manage-events", web_form_request_key=web_form_request.key)

	def test_get_web_form_list_returns_only_list_fields(self):
		from frappe.website.doctype.web_form.web_form import get_web_form_list_fields

		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			allow_multiple=1,
			show_list=1,
		)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test List Fields",
					"starts_on": "2026-05-10",
					"description": "_Test secret description",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		rows = get_web_form_list(
			web_form="manage-events",
			web_form_request_key=web_form_request.key,
		)
		allowed_fields = set(get_web_form_list_fields(frappe.get_doc("Web Form", "manage-events")))
		for row in rows:
			self.assertEqual(set(row.keys()), allowed_fields)
			self.assertNotIn("description", row)

	def test_guest_still_requires_login_without_web_form_request(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			accept(
				web_form="manage-events",
				data=json.dumps(
					{
						"doctype": "Event",
						"subject": "_Test Guest Without Request",
						"starts_on": "2026-05-10",
					}
				),
			)

	def test_web_form_redirect_preserves_request_key(self):
		self.set_web_form_settings(key_required=1, login_required=0, show_list=1)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		frappe.local.path = "manage-events"
		frappe.local.form_dict = frappe._dict(web_form_request_key=web_form_request.key)
		web_form = frappe.get_doc("Web Form", "manage-events")

		with self.assertRaises(frappe.Redirect):
			web_form.get_context(frappe._dict())

		self.assertIn(web_form_request.key, frappe.flags.redirect_location)

	def test_web_form_breadcrumb_preserves_request_key(self):
		self.set_web_form_settings(
			key_required=1,
			login_required=0,
			show_list=1,
			allow_multiple=1,
		)
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		frappe.local.path = "manage-events/new"
		frappe.local.form_dict = frappe._dict(
			is_new=1,
			web_form_request_key=web_form_request.key,
		)
		set_request(
			method="GET",
			path="manage-events/new",
			query_string=f"web_form_request_key={web_form_request.key}",
		)
		context = frappe._dict()
		frappe.get_doc("Web Form", "manage-events").get_context(context)

		self.assertEqual(len(context.parents), 1)
		self.assertIn(web_form_request.key, context.parents[0]["route"])

	def test_get_form_data_requires_web_form_request_key_for_link_fields(self):
		self.set_web_form_settings(key_required=1, login_required=0)
		self.add_web_form_link_field()
		web_form_request = self.create_web_form_request()

		frappe.set_user("Guest")

		self.assertRaises(
			frappe.PermissionError,
			get_form_data,
			doctype="Event",
			web_form_name="manage-events",
		)

		result = get_form_data(
			doctype="Event",
			web_form_name="manage-events",
			web_form_request_key=web_form_request.key,
		)
		link_field = next(f for f in result.web_form.web_form_fields if f.fieldname == "reference_doctype")
		self.assertEqual(link_field.fieldtype, "Autocomplete")
		self.assertTrue(link_field.options)

	def test_get_form_data_allows_used_one_time_key_without_docname(self):
		self.set_web_form_settings(key_required=1, login_required=0, allow_multiple=0)
		self.add_web_form_link_field()
		web_form_request = self.create_web_form_request(doc_values={"event_type": "Public"})

		frappe.set_user("Guest")
		accept(
			web_form="manage-events",
			data=json.dumps(
				{
					"doctype": "Event",
					"subject": "_Test One Time Get Form Data",
					"starts_on": "2026-05-10",
				}
			),
			web_form_request_key=web_form_request.key,
		)

		result = get_form_data(
			doctype="Event",
			web_form_name="manage-events",
			web_form_request_key=web_form_request.key,
		)
		link_field = next(f for f in result.web_form.web_form_fields if f.fieldname == "reference_doctype")
		self.assertEqual(link_field.fieldtype, "Autocomplete")

	def test_guest_key_web_form_rejects_unauthorized_link_field_on_save(self):
		self.set_web_form_settings(key_required=1, login_required=0)
		web_form = frappe.get_doc("Web Form", "manage-events")
		original_fields = [field.as_dict() for field in web_form.web_form_fields]

		def restore_fields():
			restore_form = frappe.get_doc("Web Form", "manage-events")
			restore_form.web_form_fields = []
			for field in original_fields:
				restore_form.append("web_form_fields", field)
			restore_form.save(ignore_permissions=True)
			frappe.clear_document_cache("Web Form", "manage-events")

		self.addCleanup(restore_fields)

		web_form.append(
			"web_form_fields",
			{
				"fieldname": "restricted_link",
				"fieldtype": "Link",
				"label": "Restricted Link",
				"options": "User",
			},
		)

		with self.assertRaises(frappe.ValidationError):
			web_form.save()

	def test_get_link_options_blocked_for_unauthorized_link_on_guest_key_form(self):
		self.set_web_form_settings(key_required=1, login_required=0)

		frappe.get_doc(
			{
				"doctype": "Web Form Field",
				"parent": "manage-events",
				"parenttype": "Web Form",
				"parentfield": "web_form_fields",
				"fieldname": "restricted_link",
				"fieldtype": "Link",
				"label": "Restricted Link",
				"options": "User",
			}
		).insert(ignore_permissions=True)
		frappe.clear_document_cache("Web Form", "manage-events")

		def restore_fields():
			frappe.db.delete(
				"Web Form Field",
				{
					"parent": "manage-events",
					"parenttype": "Web Form",
					"fieldname": "restricted_link",
				},
			)
			frappe.clear_document_cache("Web Form", "manage-events")

		self.addCleanup(restore_fields)

		web_form_request = self.create_web_form_request()
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			get_link_options(
				"manage-events",
				"User",
				web_form_request_key=web_form_request.key,
			)

	def add_web_form_link_field(self):
		link_doctype = "Salutation"
		add_permission(link_doctype, "Guest", ptype="read")
		clear_permissions_cache(link_doctype)
		self.addCleanup(lambda: (reset_perms(link_doctype), clear_permissions_cache(link_doctype)))

		web_form = frappe.get_doc("Web Form", "manage-events")
		original_fields = [field.as_dict() for field in web_form.web_form_fields]

		def restore_fields():
			restore_form = frappe.get_doc("Web Form", "manage-events")
			restore_form.web_form_fields = []
			for field in original_fields:
				restore_form.append("web_form_fields", field)
			restore_form.save(ignore_permissions=True)
			frappe.clear_document_cache("Web Form", "manage-events")

		self.addCleanup(restore_fields)

		web_form.append(
			"web_form_fields",
			{
				"fieldname": "reference_doctype",
				"fieldtype": "Link",
				"label": "Reference Document Type",
				"options": link_doctype,
			},
		)
		web_form.save(ignore_permissions=True)
		frappe.clear_document_cache("Web Form", "manage-events")

	def create_web_form_request(
		self, web_form_values=None, doc_values=None, expires_on=None, reference_docname=None
	):
		references = []
		if reference_docname:
			doctype = frappe.db.get_value("Web Form", "manage-events", "doc_type")
			references = [{"link_doctype": doctype, "link_name": reference_docname}]

		return frappe.get_doc(
			{
				"doctype": "Web Form Request",
				"web_form": "manage-events",
				"references": references,
				"expires_on": expires_on,
				"web_form_values": json.dumps(web_form_values or {}),
				"doc_values": json.dumps(doc_values or {}),
			}
		).insert(ignore_permissions=True)

	def create_new_doctype_web_form(self, extra_fields=None, **web_form_settings):
		"""Insert a Web Form with `is_new_doctype=1` and return it.

		Cleans up both the generated DocType record and its underlying database
		table: `CREATE TABLE`/`ALTER TABLE` are DDL and are not rolled back with the
		rest of the test transaction, so they must be dropped explicitly.
		"""
		fields = extra_fields or [
			{"label": "Full Name", "fieldtype": "Data", "reqd": 1},
			{"label": "Salary", "fieldtype": "Currency"},
		]
		web_form = frappe.get_doc(
			{
				"doctype": "Web Form",
				"title": f"_Test New DocType Form {frappe.generate_hash(length=6)}",
				"is_new_doctype": 1,
				"module": "Website",
				"web_form_fields": fields,
				**web_form_settings,
			}
		)
		web_form.insert(ignore_permissions=True)

		def cleanup():
			doctype_name = web_form.doc_type
			frappe.delete_doc("Web Form", web_form.name, ignore_permissions=True, force=True)
			frappe.delete_doc("DocType", doctype_name, ignore_permissions=True, force=True)
			frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype_name}`")

		self.addCleanup(cleanup)
		return web_form

	def test_is_new_doctype_creates_backing_doctype(self):
		"""`is_new_doctype=1` must create a DocType from `web_form_fields` on first
		save and point `doc_type` at it, without `doc_type` ever being set up front
		-- this is the "create new DocType inline" path from the design discussion,
		as opposed to linking an existing DocType."""
		web_form = self.create_new_doctype_web_form()

		self.assertTrue(web_form.doc_type)
		self.assertTrue(web_form.doc_type.startswith(f"WebForm-{web_form.title}"))

		doctype = frappe.get_doc("DocType", web_form.doc_type)
		self.assertEqual(doctype.custom, 1)
		self.assertEqual({row.role for row in doctype.permissions}, {"System Manager"})

		meta = frappe.get_meta(web_form.doc_type)
		self.assertTrue(meta.has_field("full_name"))
		self.assertEqual(meta.get_field("full_name").fieldtype, "Data")
		self.assertTrue(meta.has_field("salary"))
		self.assertEqual(meta.get_field("salary").fieldtype, "Currency")

	def test_is_new_doctype_accepts_submissions_end_to_end(self):
		"""The generated DocType must be immediately usable through the normal
		`accept()` submission flow used by every other Web Form -- nothing about
		rendering or submission is aware of which path created `doc_type`."""
		web_form = self.create_new_doctype_web_form()

		frappe.set_user("Administrator")
		doc = accept(
			web_form=web_form.name,
			data=json.dumps(
				{"doctype": web_form.doc_type, "full_name": "_Test New Doctype Person", "salary": 50000}
			),
		)

		self.assertEqual(doc.full_name, "_Test New Doctype Person")
		self.assertEqual(doc.salary, 50000)

	def test_is_new_doctype_syncs_new_field_on_update(self):
		"""Adding a row to `web_form_fields` after creation must add the matching
		field to the backing DocType on the next save, so a field added later works
		exactly like one added at creation."""
		web_form = self.create_new_doctype_web_form()

		web_form.append("web_form_fields", {"label": "Department", "fieldtype": "Data"})
		web_form.save(ignore_permissions=True)

		meta = frappe.get_meta(web_form.doc_type)
		self.assertTrue(meta.has_field("department"))

	def test_is_new_doctype_skips_page_break_fields(self):
		"""`Page Break` is a Web Form-only pagination marker (splits the public form
		into pages) with no DocField equivalent -- it must stay on the form's own
		field list for rendering, but never reach the backing DocType's schema."""
		web_form = self.create_new_doctype_web_form(
			extra_fields=[
				{"label": "Full Name", "fieldtype": "Data"},
				{"label": "Page 2", "fieldtype": "Page Break"},
				{"label": "Department", "fieldtype": "Data"},
			]
		)

		self.assertTrue(any(f.fieldtype == "Page Break" for f in web_form.web_form_fields))

		meta = frappe.get_meta(web_form.doc_type)
		self.assertFalse(any(f.fieldtype == "Page Break" for f in meta.fields))

	def test_is_new_doctype_field_sync_is_a_noop_when_fields_unchanged(self):
		"""Re-saving the Web Form without touching `web_form_fields` must not
		re-save the backing DocType. This is the efficiency guard in
		`get_field_signature` -- without it, every save of an unrelated setting
		(e.g. the introduction text) would trigger a full DocType schema-sync
		check (`frappe.db.updatedb`)."""
		web_form = self.create_new_doctype_web_form()
		modified_before = frappe.db.get_value("DocType", web_form.doc_type, "modified")

		web_form.introduction_text = "_Test unrelated change"
		web_form.save(ignore_permissions=True)

		modified_after = frappe.db.get_value("DocType", web_form.doc_type, "modified")
		self.assertEqual(modified_before, modified_after)

	def test_is_new_doctype_derives_fieldname_from_label(self):
		"""A row saved without an explicit `fieldname` (the client leaves it blank
		and derives it from `label` once `is_new_doctype` is set, mirroring Custom
		Field's own label-to-fieldname convention) must have the server derive one
		too, so the field is still usable even if the client-side derivation is
		skipped (e.g. a direct API insert)."""
		web_form = self.create_new_doctype_web_form(
			extra_fields=[{"label": "Preferred Contact Method", "fieldtype": "Data"}]
		)

		self.assertEqual(web_form.web_form_fields[0].fieldname, "preferred_contact_method")

	def test_is_new_doctype_sanitizes_fieldname_typed_directly(self):
		"""`fieldname` is free text in New DocType mode (see `set_fields` in
		web_form.js), so a user can type a human label like "Driver Name" straight
		into it instead of the intended `label` column. Found via manual testing:
		this reached `DocType.insert()` unsanitized and failed with
		`InvalidColumnName: Fieldname driver name cannot have special characters`.
		The server must sanitize whatever ends up in `fieldname`, not just derive
		it when blank."""
		web_form = self.create_new_doctype_web_form(
			extra_fields=[{"label": "Driver Name", "fieldname": "Driver Name", "fieldtype": "Data"}]
		)

		self.assertEqual(web_form.web_form_fields[0].fieldname, "driver_name")
		meta = frappe.get_meta(web_form.doc_type)
		self.assertTrue(meta.has_field("driver_name"))

	def test_is_new_doctype_ignores_stale_reqd_on_layout_field(self):
		"""A Section/Column Break row can be left with a stale `reqd=1` if it was
		checked before the row's fieldtype was changed to a layout type (the
		existing `fieldtype` handler in web_form.js clears fieldname/label/options
		on that change, but not `reqd`). Found via manual testing: this reached
		`DocType.insert()` and failed with `IllegalMandatoryError: Field ... of
		type Section Break cannot be mandatory`. The server must not forward
		`reqd` for fieldtypes that carry no value."""
		web_form = self.create_new_doctype_web_form(
			extra_fields=[
				{"label": "Personal Info", "fieldtype": "Section Break", "reqd": 1},
				{"label": "Full Name", "fieldtype": "Data"},
			]
		)

		meta = frappe.get_meta(web_form.doc_type)
		self.assertEqual(meta.get_field("personal_info").reqd, 0)

	def set_web_form_settings(self, **settings):
		current_settings = frappe.db.get_value("Web Form", "manage-events", list(settings), as_dict=True)

		def restore_settings():
			frappe.db.set_value("Web Form", "manage-events", current_settings, update_modified=False)
			frappe.clear_document_cache("Web Form", "manage-events")

		self.addCleanup(restore_settings)
		frappe.db.set_value("Web Form", "manage-events", settings, update_modified=False)
		frappe.clear_document_cache("Web Form", "manage-events")
