'use client';

interface Props {
  sql: string;
}

export default function SqlViewer({ sql }: Props) {
  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
        Generated SQL
      </h2>
      <pre
        id="sql-viewer"
        className="bg-gray-900 border border-gray-700 rounded-md p-4 text-sm text-green-400
                   whitespace-pre-wrap break-words overflow-x-auto"
      >
        {sql}
      </pre>
    </section>
  );
}
