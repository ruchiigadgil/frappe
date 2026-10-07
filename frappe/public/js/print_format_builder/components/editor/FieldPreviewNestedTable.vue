<template>
	<div
		class="child-table child-table--lined child-table--bordered"
		:data-fieldname="df.fieldname"
		data-fieldtype="Table"
	>
		<div v-if="df.label" class="label">{{ df.label }}</div>
		<table class="table">
			<thead>
				<tr>
					<th
						v-for="col in df.table_columns"
						:key="col.fieldname"
						class="column-header"
						:data-fieldtype="col.fieldtype"
						:data-fieldname="col.fieldname"
						:style="col.width ? `width: ${col.width}%` : ''"
					>
						{{ col.label || col.fieldname }}
					</th>
				</tr>
			</thead>
			<tbody>
				<tr
					v-for="{ row, i, nested } in body_rows"
					:key="nested ? `${i}-${nested.fieldname}` : i"
					:class="nested ? 'table-row nested-table-row' : i % 2 === 0 ? 'odd' : 'even'"
				>
					<td v-if="nested" class="column-value" :colspan="df.table_columns.length">
						<FieldPreviewNestedTable :df="nested" :rows="row[nested.fieldname]" />
					</td>
					<template v-else>
						<td
							v-for="col in df.table_columns"
							:key="col.fieldname"
							class="column-value"
							:data-fieldtype="col.fieldtype"
							:data-fieldname="col.fieldname"
						>
							{{ format_cell(row, col) }}
						</td>
					</template>
				</tr>
			</tbody>
		</table>
	</div>
</template>

<script setup>
import { computed, inject } from "vue";
import { useFieldFormat } from "../../composables/useFieldFormat";
import { nested_tables_in_row } from "../../utils";

const props = defineProps(["df", "rows"]);
const store = inject("$store");
const preview_doc = computed(() => store.preview_doc.value);

// one entry per printed row: each data row, then the tables nested inside it
const body_rows = computed(() =>
	(props.rows || []).flatMap((row, i) => [
		{ row, i },
		...nested_tables_in_row(props.df, row).map((nested) => ({ row, i, nested })),
	])
);

const { format_cell } = useFieldFormat(props, store, preview_doc);
</script>
