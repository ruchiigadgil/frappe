# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""Load and delete child rows that live below other child rows."""

from collections import defaultdict

import frappe
from frappe.model.utils import is_virtual_doctype
from frappe.utils import create_batch
from frappe.utils.password import delete_child_row_passwords

BATCH_SIZE = 1000
MAX_TABLE_DEPTH = 5


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


def load_level(row, fieldname: str, child_doctype: str) -> None:
	root, rows = _rows_at_level_of(row)
	rows = [other for other in rows if fieldname not in other.__dict__]
	children_by_parent = _children_by_parent(
		[str(other.name) for other in rows],
		row.doctype,
		fieldname,
		child_doctype,
		bool(root.flags.for_update),
	)
	for other in rows:
		other.__dict__[fieldname] = []
		other.extend(fieldname, children_by_parent[str(other.name)])


def delete_descendants(names_by_doctype: dict[str, list[str]]) -> None:
	"""Delete every row nested below the given rows, one query per table per level."""
	while names_by_doctype:
		next_level = defaultdict(list)
		for doctype, names in names_by_doctype.items():
			if not names:
				continue
			for fieldname, child_doctype in nested_tables(doctype):
				for batch in create_batch(names, BATCH_SIZE):
					filters = {"parent": ("in", batch), "parenttype": doctype, "parentfield": fieldname}
					if child_names := frappe.get_all(child_doctype, filters=filters, pluck="name"):
						delete_child_row_passwords(child_doctype, {"name": ("in", child_names)})
						frappe.db.delete(child_doctype, {"name": ("in", child_names)})
						next_level[child_doctype].extend(child_names)
		names_by_doctype = next_level


def save_descendants(rows: list) -> None:
	while rows:
		rows_by_doctype = defaultdict(list)
		for row in rows:
			rows_by_doctype[row.doctype].append(row)

		rows = []
		for doctype, parents in rows_by_doctype.items():
			for fieldname, child_doctype in nested_tables(doctype):
				children = [child for parent in parents for child in parent.get(fieldname)]
				parent_names = [str(parent.name) for parent in parents]
				delete_removed_rows(child_doctype, doctype, fieldname, parent_names, children)
				for child in children:
					child.db_update()
				rows.extend(children)


def delete_removed_rows(
	doctype: str, parenttype: str, parentfield: str, parent_names: list[str], kept_rows: list
) -> None:
	kept_rows = [row for row in kept_rows if row.name and not row.is_new()]
	batches = list(create_batch(parent_names, BATCH_SIZE))
	for batch in batches:
		filters = {"parenttype": parenttype, "parentfield": parentfield, "parent": ("in", batch)}
		batch_parents = set(batch)
		if kept := [row.name for row in kept_rows if len(batches) == 1 or str(row.parent) in batch_parents]:
			filters["name"] = ("not in", kept)

		if nested_tables(doctype):
			delete_descendants({doctype: frappe.get_all(doctype, filters=filters, pluck="name")})
		delete_child_row_passwords(doctype, filters)
		frappe.db.delete(doctype, filters)


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


def table_depth(doctype: str, istable: bool, child_doctype: str) -> int:
	return _levels_above(doctype, istable) + 1 + _levels_below(child_doctype)


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


def _levels_below(doctype: str) -> int:
	return max((1 + _levels_below(child) for _, child in nested_tables(doctype)), default=0)


def _levels_above(doctype: str, istable: bool) -> int:
	if not istable:
		return 0
	parents = {
		*frappe.get_all(
			"DocField", {"fieldtype": "Table", "options": doctype, "parenttype": "DocType"}, pluck="parent"
		),
		*frappe.get_all("Custom Field", {"fieldtype": "Table", "options": doctype}, pluck="dt"),
	}
	return max((1 + _levels_above(parent, frappe.get_meta(parent).istable) for parent in parents), default=1)


def _attach_children(rows, doctype, fieldname, child_doctype, for_update):
	children_by_parent = _children_by_parent(
		[str(row.name) for row in rows], doctype, fieldname, child_doctype, for_update
	)
	for row in rows:
		row[fieldname] = children_by_parent[str(row.name)]
	return [child for row in rows for child in row[fieldname]]


def _children_by_parent(parent_names, doctype, fieldname, child_doctype, for_update=False):
	children_by_parent = defaultdict(list)
	for batch in create_batch(parent_names, BATCH_SIZE):
		for child in frappe.qb.get_query(
			table=child_doctype,
			filters={"parent": ("in", batch), "parenttype": doctype, "parentfield": fieldname},
			fields=["*"],
			order_by="idx asc",
			for_update=for_update,
		).run(as_dict=True):
			children_by_parent[child.parent].append(child)
	return children_by_parent


def _rows_at_level_of(row) -> tuple:
	path, root = [], row
	while root.parent_doc is not None:
		path.append(root.parentfield)
		root = root.parent_doc

	rows = [root]
	for fieldname in reversed(path):
		rows = [child for parent in rows for child in parent.__dict__.get(fieldname, [])]
	if not any(other is row for other in rows):
		rows.append(row)
	return root, rows
