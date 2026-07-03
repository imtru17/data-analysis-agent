'use client'

import type { DatasetTiles, TileColumn } from '@/lib/api'

// Phase-4 Data workbench: a grid of CLICKABLE profile tiles for a loaded FILE
// dataset. A header tile shows the total row count; one tile per column shows
// its distinct + null counts and dtype. A unique, non-null column is badged
// PK; a detected foreign key shows an "FK -> <dataset>.<col>" badge. Clicking a
// column tile opens the value-counts drill-in (handled by the parent). All data
// here is computed locally by the backend — no LLM call.

interface ProfileTilesProps {
  tiles: DatasetTiles
  selectedColumn: string | null
  onSelectColumn: (col: string) => void
}

export function ProfileTiles({ tiles, selectedColumn, onSelectColumn }: ProfileTilesProps) {
  return (
    <div data-testid="profile-tiles">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
        Profile tiles
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {/* Row-count header tile. */}
        <div
          data-testid="tile-row-count"
          className="rounded-lg border border-indigo-200 bg-indigo-50/60 p-3"
        >
          <p className="text-[11px] font-medium uppercase tracking-wide text-indigo-500">Rows</p>
          <p
            data-testid="tile-row-count-value"
            className="mt-0.5 text-lg font-semibold text-indigo-800"
          >
            {tiles.row_count.toLocaleString()}
          </p>
          <p className="mt-0.5 text-[11px] text-indigo-500">
            {tiles.columns.length} column{tiles.columns.length === 1 ? '' : 's'}
          </p>
        </div>

        {tiles.columns.map(col => (
          <ColumnTile
            key={col.name}
            col={col}
            selected={selectedColumn === col.name}
            onClick={() => onSelectColumn(col.name)}
          />
        ))}
      </div>
    </div>
  )
}

function ColumnTile({
  col,
  selected,
  onClick,
}: {
  col: TileColumn
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      data-testid="column-tile"
      data-column={col.name}
      aria-pressed={selected}
      onClick={onClick}
      className={`flex flex-col rounded-lg border p-3 text-left transition-colors ${
        selected
          ? 'border-indigo-400 bg-indigo-50/60 ring-1 ring-indigo-300'
          : 'border-gray-200 bg-white hover:border-indigo-300 hover:bg-indigo-50/40'
      }`}
    >
      <span className="flex items-center gap-1.5">
        <span className="truncate text-xs font-semibold text-gray-800" title={col.name}>
          {col.name}
        </span>
        {col.is_pk_candidate && (
          <span
            data-testid="pk-badge"
            title="Primary-key candidate: unique + non-null over the full data"
            className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700"
          >
            PK
          </span>
        )}
      </span>

      <span className="mt-0.5 truncate font-mono text-[10px] text-gray-400">{col.dtype}</span>

      <span className="mt-1.5 flex items-center gap-2 text-[11px] text-gray-600">
        <span data-testid="tile-distinct">
          <span className="font-semibold text-gray-800">{col.distinct.toLocaleString()}</span>{' '}
          distinct
        </span>
        <span data-testid="tile-nulls">
          <span className="font-semibold text-gray-800">{col.null_count.toLocaleString()}</span>{' '}
          null
        </span>
      </span>

      {col.fk_candidates.length > 0 && (
        <span className="mt-1.5 flex flex-wrap gap-1">
          {col.fk_candidates.map(fk => (
            <span
              key={`${fk.references_dataset_id}.${fk.references_column}`}
              data-testid="fk-badge"
              title={`Foreign-key candidate referencing ${fk.references_dataset_name}.${fk.references_column}`}
              className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700"
            >
              FK &rarr; {fkLabel(fk.references_dataset_name)}.{fk.references_column}
            </span>
          ))}
        </span>
      )}
    </button>
  )
}

// Strip a trailing extension so the badge reads "customers.id" not "customers.csv.id".
function fkLabel(datasetName: string): string {
  return datasetName.replace(/\.[^.]+$/, '')
}
