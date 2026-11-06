# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from unittest.mock import patch

import frappe
from frappe.client import delete_doc, insert_doc, set_value
from frappe.core.doctype.doctype.test_doctype import new_doctype
from frappe.core.doctype.version.version import get_diff
from frappe.desk.form.activity import get_child_table_changes
from frappe.desk.form.grid_import import get_column_map
from frappe.desk.form.load import get_meta_bundle
from frappe.email.doctype.notification.notification import get_reference_doctype, get_reference_name
from frappe.model.delete_doc import get_linked_docs
from frappe.model.document import bulk_insert, get_docs
from frappe.model.mapper import get_mapped_doc
from frappe.model.meta import get_field_currency
from frappe.tests import IntegrationTestCase
from frappe.utils.global_search import rebuild_for_doctype, sync_global_search

PARENT = "Test Nested Parent"
CHILD = "Test Nested Child"
GRANDCHILD = "Test Nested Grandchild"
TARGET = "Test Nested Target"
READER = "nested.reader@example.com"
NESTED_FILE_URL = "https://example.com/nested.txt"
ROOT_SAVES = []


def record_root_save(doc, method=None):
	ROOT_SAVES.append(doc.name)


class TestNestedChildTable(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.drop_doctypes()
		new_doctype(TARGET).insert()
		new_doctype(
			GRANDCHILD,
			istable=1,
			fields=[
				{"fieldname": "serial", "label": "Serial", "fieldtype": "Data", "in_global_search": 1},
				{"fieldname": "email", "fieldtype": "Data", "options": "Email"},
				{"fieldname": "secret", "fieldtype": "Data", "permlevel": 1},
				{"fieldname": "pin", "fieldtype": "Data", "mask": 1},
				{"fieldname": "target", "fieldtype": "Link", "options": TARGET},
				{"fieldname": "doc_file", "fieldtype": "Attach"},
				{"fieldname": "price", "fieldtype": "Currency", "options": "currency"},
				{"fieldname": "status", "fieldtype": "Data", "default": "Open"},
			],
		).insert()
		new_doctype(
			CHILD,
			istable=1,
			fields=[
				{"fieldname": "item", "label": "Item", "fieldtype": "Data"},
				{"fieldname": "serials", "label": "Serials", "fieldtype": "Table", "options": GRANDCHILD},
			],
		).insert()
		new_doctype(
			PARENT,
			fields=[
				{"fieldname": "title", "label": "Title", "fieldtype": "Data"},
				{"fieldname": "currency", "fieldtype": "Data"},
				{"fieldname": "items", "label": "Items", "fieldtype": "Table", "options": CHILD},
			],
			permissions=[{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
		).insert()

	@classmethod
	def tearDownClass(cls):
		cls.drop_doctypes()
		frappe.db.commit()
		super().tearDownClass()

	@staticmethod
	def drop_doctypes():
		frappe.db.delete("File", {"file_url": NESTED_FILE_URL})
		for doctype in (PARENT, CHILD, GRANDCHILD, TARGET):
			frappe.delete_doc_if_exists("DocType", doctype, force=True)

	def make_parent(self, **grandchild_values):
		doc = frappe.new_doc(PARENT)
		doc.title = "Nested"
		for item, serials in {"A": ["A1", "A2"], "B": ["B1"]}.items():
			doc.append(
				"items",
				{"item": item, "serials": [{"serial": serial, **grandchild_values} for serial in serials]},
			)
		return doc.insert()

	def stored_serials(self, item_row):
		return frappe.get_all(
			GRANDCHILD,
			filters={"parent": item_row.name, "parenttype": CHILD},
			fields=["serial", "parentfield", "idx"],
			order_by="idx asc",
		)

	def make_reader(self):
		if not frappe.db.exists("User", READER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": READER,
					"first_name": "Nested Reader",
					"roles": [{"role": "System Manager"}],
				}
			).insert(ignore_permissions=True)

	def grant_parent_permlevel(self, permlevel, **rights):
		perm = frappe.get_doc(
			{
				"doctype": "DocPerm",
				"parent": PARENT,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": "System Manager",
				"permlevel": permlevel,
				**rights,
			}
		)
		perm.db_insert()
		frappe.clear_cache(doctype=PARENT)
		self.addCleanup(frappe.clear_cache, doctype=PARENT)
		self.addCleanup(frappe.db.delete, "DocPerm", {"name": perm.name})

	def set_table_permlevel(self, permlevel):
		filters = {"parent": CHILD, "fieldname": "serials"}
		frappe.db.set_value("DocField", filters, "permlevel", permlevel)
		frappe.clear_cache(doctype=CHILD)
		self.addCleanup(frappe.clear_cache, doctype=CHILD)
		self.addCleanup(frappe.db.set_value, "DocField", filters, "permlevel", 0)

	def test_insert_stores_grandchildren_under_their_child_row(self):
		doc = self.make_parent()

		self.assertEqual(
			self.stored_serials(doc.items[0]),
			[
				{"serial": "A1", "parentfield": "serials", "idx": 1},
				{"serial": "A2", "parentfield": "serials", "idx": 2},
			],
		)

	def test_get_doc_loads_every_level_with_one_query_per_table(self):
		name = self.make_parent().name
		frappe.get_doc(PARENT, name)  # warm the meta cache so only data queries are counted

		with self.assertQueryCount(3):
			doc = frappe.get_doc(PARENT, name)

		self.assertEqual([[s.serial for s in row.serials] for row in doc.items], [["A1", "A2"], ["B1"]])

	def test_lazy_doc_loads_each_nested_level_once_on_first_read(self):
		name = self.make_parent().name
		lazy = frappe.get_lazy_doc(PARENT, name)
		[row.serials for row in lazy.items]

		lazy = frappe.get_lazy_doc(PARENT, name)
		with self.assertQueryCount(1):
			items = lazy.items
		with self.assertQueryCount(1):
			serials = [[s.serial for s in row.serials] for row in items]

		self.assertEqual(serials, [["A1", "A2"], ["B1"]])

	def test_saving_a_lazy_doc_keeps_nested_rows_it_never_read(self):
		doc = self.make_parent()
		lazy = frappe.get_lazy_doc(PARENT, doc.name)
		lazy.items[0].item = "A changed"
		lazy.save()

		self.assertEqual(
			[[s.serial for s in self.stored_serials(row)] for row in doc.items], [["A1", "A2"], ["B1"]]
		)

	def test_get_docs_loads_grandchildren(self):
		name = self.make_parent().name

		(doc,) = get_docs(PARENT, filters={"name": name})

		self.assertEqual([s.serial for s in doc.items[0].serials], ["A1", "A2"])

	def test_save_links_grandchildren_of_a_new_child_row(self):
		doc = self.make_parent()
		doc.append("items", {"item": "C", "serials": [{"serial": "C1"}]})
		doc.save()

		self.assertEqual([s.serial for s in self.stored_serials(doc.items[-1])], ["C1"])

	def test_removing_a_child_row_deletes_its_grandchildren(self):
		doc = self.make_parent()
		removed = doc.items.pop(0)
		doc.save()

		self.assertFalse(self.stored_serials(removed))
		self.assertEqual(len(self.stored_serials(doc.items[0])), 1)

	def test_removing_a_grandchild_row(self):
		doc = self.make_parent()
		doc.items[0].serials.pop()
		doc.save()

		self.assertEqual([s.serial for s in self.stored_serials(doc.items[0])], ["A1"])

	def test_save_cleans_a_nested_table_once_for_all_its_parent_rows(self):
		doc = self.make_parent()
		doc.items[0].serials.pop(0)
		doc.items[1].serials.pop(0)

		with patch.object(frappe.db, "delete", wraps=frappe.db.delete) as delete:
			doc.save()

		self.assertEqual([call.args[0] for call in delete.call_args_list].count(GRANDCHILD), 1)
		self.assertEqual([[s.serial for s in self.stored_serials(row)] for row in doc.items], [["A2"], []])

	def test_load_save_and_delete_split_parent_rows_into_batches(self):
		with patch("frappe.model.nested_children.BATCH_SIZE", 1):
			doc = self.make_parent()
			doc.items[0].serials.pop(0)
			doc.save()

			reloaded = frappe.get_doc(PARENT, doc.name)
			self.assertEqual([[s.serial for s in row.serials] for row in reloaded.items], [["A2"], ["B1"]])

			reloaded.delete()
			self.assertFalse(frappe.get_all(GRANDCHILD, {"parent": ("in", [r.name for r in doc.items])}))

	def test_editing_a_grandchild_keeps_its_value_before_save(self):
		doc = self.make_parent()
		doc.items[0].serials[0].serial = "A1-edited"
		doc.save()

		row = doc.items[0].serials[0]
		self.assertEqual(row.get_doc_before_save().serial, "A1")
		self.assertTrue(row.has_value_changed("serial"))

	def test_delete_removes_every_level(self):
		doc = self.make_parent()
		item_names = [row.name for row in doc.items]

		frappe.delete_doc(PARENT, doc.name)

		self.assertFalse(frappe.get_all(CHILD, filters={"parent": doc.name}))
		self.assertFalse(frappe.get_all(GRANDCHILD, filters={"parent": ("in", item_names)}))

	def test_copy_doc_duplicates_every_level_with_new_names(self):
		doc = self.make_parent()

		copy = frappe.copy_doc(doc).insert()

		self.assertEqual([[s.serial for s in row.serials] for row in copy.items], [["A1", "A2"], ["B1"]])
		self.assertNotEqual(copy.items[0].serials[0].name, doc.items[0].serials[0].name)
		self.assertEqual(copy.items[0].serials[0].parent, copy.items[0].name)

	def test_child_table_cannot_contain_itself(self):
		for options in (GRANDCHILD, CHILD):
			with self.subTest(options=options):
				grandchild = frappe.get_doc("DocType", GRANDCHILD)
				grandchild.append("fields", {"fieldname": "loop", "fieldtype": "Table", "options": options})
				self.assertRaises(frappe.ValidationError, grandchild.save)

	def test_child_tables_cannot_nest_deeper_than_the_limit(self):
		with patch("frappe.core.doctype.doctype.doctype.MAX_TABLE_DEPTH", 1):
			self.assertRaises(frappe.ValidationError, frappe.get_doc("DocType", CHILD).save)
		frappe.get_doc("DocType", CHILD).save()

	def test_meta_bundle_includes_every_nested_child_doctype(self):
		self.assertEqual([meta["name"] for meta in get_meta_bundle(PARENT)], [PARENT, CHILD, GRANDCHILD])

	def test_grandchild_row_uses_the_root_document_permissions(self):
		row = self.make_parent().items[0].serials[0]

		self.assertEqual(row.get_permissions(), frappe.get_meta(PARENT).permissions)

	def test_grandchild_permlevel_is_judged_by_the_root_document(self):
		serial = self.make_parent().items[0].serials[0]
		self.make_reader()

		with self.set_user(READER):
			self.assertTrue(frappe.has_permission(GRANDCHILD, "read", serial))

		self.set_table_permlevel(1)
		with self.set_user(READER):
			self.assertFalse(frappe.has_permission(GRANDCHILD, "read", serial))

		self.grant_parent_permlevel(1, read=1)
		with self.set_user(READER):
			self.assertTrue(frappe.has_permission(GRANDCHILD, "read", serial))

	def test_read_strips_nested_fields_the_user_cannot_read(self):
		name = self.make_parent(secret="hidden").name
		self.make_reader()

		with self.set_user(READER):
			doc = frappe.get_doc(PARENT, name)
			doc.apply_fieldlevel_read_permissions()

		self.assertIsNone(doc.items[0].serials[0].get("secret"))

	def test_save_keeps_nested_fields_the_user_cannot_write(self):
		doc = self.make_parent(secret="original")
		self.make_reader()

		with self.set_user(READER):
			edited = frappe.get_doc(PARENT, doc.name)
			edited.items[0].serials[0].secret = "tampered"
			edited.save()

		self.assertEqual(frappe.db.get_value(GRANDCHILD, doc.items[0].serials[0].name, "secret"), "original")

	def test_masked_nested_fields_are_masked_and_not_overwritten_on_save(self):
		doc = self.make_parent(pin="1234")
		self.make_reader()

		with self.set_user(READER):
			masked = frappe.get_doc(PARENT, doc.name)
			masked.mask_fields()
			self.assertNotEqual(masked.items[0].serials[0].pin, "1234")
			masked.title = "Edited"
			masked.save()

		self.assertEqual(frappe.db.get_value(GRANDCHILD, doc.items[0].serials[0].name, "pin"), "1234")

	def test_client_set_value_on_a_grandchild_saves_the_root(self):
		doc = self.make_parent()
		serial = doc.items[0].serials[0]

		ROOT_SAVES.clear()

		with self.patch_hooks({"doc_events": {PARENT: {"on_update": f"{__name__}.record_root_save"}}}):
			frappe.local.doc_events_hooks = None  # doc_events are cached per request
			set_value(GRANDCHILD, serial.name, "serial", "A1-api")
		frappe.local.doc_events_hooks = None

		self.assertEqual(frappe.db.get_value(GRANDCHILD, serial.name, "serial"), "A1-api")
		self.assertEqual(ROOT_SAVES, [doc.name])

	def test_client_inserts_and_deletes_a_grandchild_through_the_root(self):
		doc = self.make_parent()
		item = doc.items[1]

		root = insert_doc(
			{
				"doctype": GRANDCHILD,
				"parenttype": CHILD,
				"parent": item.name,
				"parentfield": "serials",
				"serial": "B2",
			}
		)
		self.assertEqual(root.name, doc.name)
		self.assertEqual([s.serial for s in self.stored_serials(item)], ["B1", "B2"])

		delete_doc(GRANDCHILD, root.items[1].serials[-1].name)
		self.assertEqual([s.serial for s in self.stored_serials(item)], ["B1"])

	def test_version_diff_records_changes_inside_nested_tables(self):
		doc = frappe.get_doc(PARENT, self.make_parent().name)
		before = frappe.get_doc(PARENT, doc.name)
		doc.items[0].serials[0].serial = "A1-edited"
		doc.items[1].append("serials", {"serial": "B2"})
		doc.save()

		diff = get_diff(before, doc)

		self.assertFalse(diff.changed)
		self.assertEqual(
			[(path, changes) for path, _idx, _name, changes in diff.row_changed],
			[("items.serials", [("serial", "A1", "A1-edited")])],
		)
		self.assertEqual([(path, row["serial"]) for path, row in diff.added], [("items.serials", "B2")])

	def test_link_check_names_the_root_document(self):
		target = frappe.get_doc({"doctype": TARGET, "some_fieldname": "x"}).insert()
		doc = self.make_parent(target=target.name)

		links = get_linked_docs(target)

		self.assertEqual(
			{(link["reference_doctype"], link["reference_docname"]) for link in links}, {(PARENT, doc.name)}
		)

	def test_mapper_copies_nested_rows(self):
		source = self.make_parent()

		target = get_mapped_doc(PARENT, source.name, {PARENT: {"doctype": PARENT}})

		self.assertEqual([[s.serial for s in row.serials] for row in target.items], [["A1", "A2"], ["B1"]])
		self.assertTrue(all(s.is_new() for row in target.items for s in row.serials))

	def test_files_in_nested_attach_fields_are_attached_to_the_root(self):
		frappe.get_doc({"doctype": "File", "file_url": NESTED_FILE_URL}).insert()

		doc = self.make_parent(doc_file=NESTED_FILE_URL)

		self.assertTrue(
			frappe.db.exists(
				"File",
				{"file_url": NESTED_FILE_URL, "attached_to_doctype": PARENT, "attached_to_name": doc.name},
			)
		)

	def test_nested_currency_comes_from_the_nearest_parent_with_the_field(self):
		doc = self.make_parent()
		doc.currency = "EUR"
		doc.save()
		row = doc.items[0].serials[0]

		self.assertEqual(get_field_currency(row.meta.get_field("price"), row), "EUR")

	def test_timeline_shows_changes_inside_nested_tables(self):
		data = {
			"added": [["items.serials", {"serial": "B2"}]],
			"row_changed": [("items.serials", 0, "row", [("serial", "A1", "A1-edited")])],
		}

		changes = get_child_table_changes(data, PARENT, frappe.get_meta(PARENT), None, {})

		self.assertEqual([change["fieldname"] for change in changes], ["items.serials", "items.serials"])
		self.assertIn("A1-edited", changes[1]["text"])

	def test_new_grandchildren_get_their_defaults(self):
		doc = self.make_parent()

		self.assertEqual(frappe.db.get_value(GRANDCHILD, doc.items[0].serials[0].name, "status"), "Open")

	def test_db_update_all_writes_every_level(self):
		doc = self.make_parent()
		doc.items[0].serials[0].serial = "A1-raw"

		doc.db_update_all()

		self.assertEqual(frappe.db.get_value(GRANDCHILD, doc.items[0].serials[0].name, "serial"), "A1-raw")

	def test_bulk_insert_writes_every_level(self):
		doc = frappe.new_doc(PARENT)
		doc.append("items", {"item": "A", "serials": [{"serial": "A1"}, {"serial": "A2"}]})
		doc.set_new_name()
		doc.set_parent_in_children()

		bulk_insert(PARENT, [doc])

		self.assertEqual([s.serial for s in self.stored_serials(doc.items[0])], ["A1", "A2"])

	def global_search_content(self, name):
		filters = {"doctype": PARENT, "name": name}
		return frappe.db.get_value("__global_search", filters, "content", order_by=None) or ""

	def test_saving_indexes_nested_rows_in_global_search(self):
		doc = self.make_parent()

		sync_global_search()

		self.assertIn("A2", self.global_search_content(doc.name))

	def test_global_search_rebuild_indexes_nested_rows(self):
		doc = self.make_parent()
		frappe.db.delete("__global_search", {"doctype": PARENT})

		rebuild_for_doctype(PARENT)

		self.assertIn("B1", self.global_search_content(doc.name))

	def test_notification_recipients_from_a_nested_table(self):
		doc = self.make_parent(email="nested@example.com")
		notification = frappe.new_doc("Notification")
		notification.append("recipients", {"receiver_by_document_field": "email,items.serials"})

		recipients, _cc, _bcc = notification.get_list_of_recipients(doc, {})

		self.assertEqual(recipients, ["nested@example.com"])

	def test_notification_on_a_grandchild_references_the_root(self):
		doc = self.make_parent()
		serial = frappe.get_doc(GRANDCHILD, doc.items[0].serials[0].name)

		self.assertEqual((get_reference_doctype(serial), get_reference_name(serial)), (PARENT, doc.name))

	def test_standard_print_renders_nested_rows_under_their_row(self):
		doc = self.make_parent()

		html = frappe.get_print(PARENT, doc.name)

		self.assertEqual(html.count('data-fieldname="serials"'), len(doc.items))
		self.assertIn("A2", html)

	def test_print_hides_nested_columns_the_user_cannot_read(self):
		doc = self.make_parent(secret="hidden-value")
		self.make_reader()

		with self.set_user(READER):
			self.assertNotIn("hidden-value", frappe.get_print(PARENT, doc.name))

		self.grant_parent_permlevel(1, read=1)
		with self.set_user(READER):
			self.assertIn("hidden-value", frappe.get_print(PARENT, doc.name))

	def test_filter_by_a_dotted_nested_field(self):
		doc = self.make_parent()
		self.make_parent()

		self.assertEqual(
			frappe.get_list(PARENT, filters={"name": doc.name, "items.serials.serial": "B1"}, pluck="name"),
			[doc.name],
		)
		self.assertFalse(frappe.get_list(PARENT, filters={"items.serials.serial": "missing"}))

	def test_filter_naming_a_nested_child_doctype(self):
		doc = self.make_parent()

		names = frappe.get_list(
			PARENT, filters=[[PARENT, "name", "=", doc.name], [GRANDCHILD, "serial", "=", "A2"]], pluck="name"
		)

		self.assertEqual(names, [doc.name])

	def test_select_a_dotted_nested_field(self):
		doc = self.make_parent()

		rows = frappe.get_list(
			PARENT,
			filters={"name": doc.name},
			fields=["items.serials.serial as serial"],
			order_by="serial asc",
		)

		self.assertEqual([row.serial for row in rows], ["A1", "A2", "B1"])

	def test_grid_import_maps_columns_of_a_nested_table(self):
		doc = self.make_parent()

		column_map = get_column_map(PARENT, "items.serials", '["Serial", "secret"]', doc.name)

		self.assertEqual(column_map, {0: "serial"})

	def test_grid_import_rejects_a_path_through_a_non_table_field(self):
		self.assertRaises(frappe.ValidationError, get_column_map, PARENT, "items.item", "[]")

	def test_nested_filter_permlevel_is_judged_by_the_root_document(self):
		self.make_parent(secret="hidden")
		self.make_reader()

		with self.set_user(READER):
			self.assertRaises(
				frappe.PermissionError,
				frappe.get_list,
				PARENT,
				filters={"items.serials.secret": "hidden"},
			)
