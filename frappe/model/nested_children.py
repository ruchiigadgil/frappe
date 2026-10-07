# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""Load and delete child rows that live below other child rows."""

from collections import defaultdict

import frappe
from frappe.model.utils import is_virtual_doctype
from frappe.utils.password import delete_child_row_passwords


def load_descendants(rows_by_doctype: dict[str, list[dict]], for_update: bool = False) -> None:
	"""Attach every nested table to the given child rows, one query per table per level."""
	while rows_by_doctype:
		next_level = defaultdict(list)
		for doctype, rows in rows_by_doctype.items():
			if not rows:
				continue
			for fieldname, child_doctype in nested_tables(doctype):
				next_level[child_doctype].extend(
					_attach_children(rows, doctype, fieldname, child_doctype, for_update)
				)
		rows_by_doctype = next_level


def delete_descendants(names_by_doctype: dict[str, list[str]]) -> None:
	"""Delete every row nested below the given rows, one query per table per level."""
	while names_by_doctype:
		next_level = defaultdict(list)
		for doctype, names in names_by_doctype.items():
			if not names:
				continue
			for fieldname, child_doctype in nested_tables(doctype):
				filters = {"parent": ("in", names), "parenttype": doctype, "parentfield": fieldname}
				if child_names := frappe.get_all(child_doctype, filters=filters, pluck="name"):
					delete_child_row_passwords(child_doctype, {"name": ("in", child_names)})
					frappe.db.delete(child_doctype, {"name": ("in", child_names)})
					next_level[child_doctype].extend(child_names)
		names_by_doctype = next_level


def descendant_doctypes(doctype: str, include_computed: bool = True) -> list[str]:
	"""Return every child DocType below `doctype`, at any depth, nearest first."""
	found, pending = [], [doctype]
	while pending:
		meta = frappe.get_meta(pending.pop(0))
		tables = meta._table_doctypes if include_computed else meta._non_computed_table_doctypes
		for child_doctype in tables.values():
			if child_doctype not in found:
				found.append(child_doctype)
				pending.append(child_doctype)
	return found


def table_path(doctype: str, target: str) -> list[tuple[str, str, str]] | None:
	"""Return the (parent doctype, table fieldname, child doctype) hops from `doctype` down to the
	nearest table of `target`, or None when `target` is not below `doctype`."""
	paths, pending = {doctype: []}, [doctype]
	while pending:
		current = pending.pop(0)
		for df in frappe.get_meta(current).get_table_fields():
			if df.options in paths:
				continue
			paths[df.options] = [*paths[current], (current, df.fieldname, df.options)]
			if df.options == target:
				return paths[target]
			pending.append(df.options)
	return None


def get_root(doctype: str, name: str) -> tuple[str, str]:
	"""Climb from a row's parent to the (doctype, name) of the document at the top of its tree."""
	while frappe.get_meta(doctype).istable:
		doctype, name = frappe.db.get_value(doctype, name, ["parenttype", "parent"])
	return doctype, name


def load_with_root(doctype: str, name: str):
	"""Load the document at the top of the tree that holds `doctype`/`name`, and that row in it."""
	if not frappe.get_meta(doctype).istable:
		doc = frappe.get_doc(doctype, name)
		return doc, doc

	parent = frappe.db.get_value(doctype, name, ["parenttype", "parent"])
	if not parent:
		raise frappe.DoesNotExistError(doctype=doctype)

	root, _ = load_with_root(*parent)
	return root, next((row for row in root.get_all_children(doctype) if row.name == name), None)


def nested_tables(doctype: str) -> list[tuple[str, str]]:
	"""Return (fieldname, child doctype) for the stored tables of `doctype`."""
	return [
		(fieldname, child_doctype)
		for fieldname, child_doctype in frappe.get_meta(doctype)._non_computed_table_doctypes.items()
		if not is_virtual_doctype(child_doctype)
	]


def _attach_children(rows, doctype, fieldname, child_doctype, for_update):
	rows_by_name = {row.name: row for row in rows}
	children = frappe.qb.get_query(
		table=child_doctype,
		filters={"parent": ("in", list(rows_by_name)), "parenttype": doctype, "parentfield": fieldname},
		fields=["*"],
		order_by="idx asc",
		for_update=for_update,
	).run(as_dict=True)

	for row in rows:
		row[fieldname] = []
	for child in children:
		rows_by_name[child.parent][fieldname].append(child)
	return children
