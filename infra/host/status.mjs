// Read-only view of every registry entry: probe + pid record + listening socket -> table rows.
import { probe } from './probe.mjs';
import { isAlive, listeningPorts } from './processes.mjs';
import { readRecord } from './state.mjs';

export async function statusRows(services, paths, env = process.env) {
  const listeners = listeningPorts();
  const health = await Promise.all(services.map(entry => probe(entry, env)));
  return services.map((entry, index) => {
    const record = readRecord(paths, entry.id);
    const recorded = record && isAlive(record.pid) ? record : null;
    // The listener itself (a venv python.exe launcher or npm shim may be the recorded tree root).
    const pid = (entry.port === null ? null : listeners.get(entry.port)) ?? recorded?.pid ?? null;
    const startedAt = recorded?.startedAt ?? health[index].startedAt ?? null;
    return {
      id: entry.id,
      kind: entry.kind,
      port: entry.port,
      up: health[index].up,
      version: health[index].version ?? null,
      pid,
      startedAt,
      managed: recorded !== null,
      error: health[index].error ?? null,
    };
  });
}

export function formatUptime(startedAt, now = Date.now()) {
  if (!startedAt) return '-';
  const seconds = Math.max(0, Math.floor((now - Date.parse(startedAt)) / 1000));
  if (Number.isNaN(seconds)) return '-';
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds % 60}s`;
  return `${seconds}s`;
}

export function formatTable(rows, now = Date.now()) {
  const header = ['id', 'kind', 'port', 'state', 'version', 'pid', 'uptime'];
  const cells = rows.map(row => [
    row.id,
    row.kind,
    row.port === null ? '-' : String(row.port),
    row.up === null ? 'n/a' : row.up ? 'up' : 'down',
    row.version ?? '-',
    row.pid === null ? '-' : `${row.pid}${row.managed ? '' : '?'}`,
    formatUptime(row.startedAt, now),
  ]);
  const widths = header.map((title, column) => Math.max(title.length, ...cells.map(line => line[column].length)));
  const render = line => line.map((cell, column) => cell.padEnd(widths[column])).join('  ').trimEnd();
  return [render(header), render(widths.map(width => '-'.repeat(width))), ...cells.map(render)].join('\n');
}
