/* One place that talks to the middleware. Everything else imports this. */
const BASE = import.meta.env.VITE_API_BASE || "/api";

let token = sessionStorage.getItem("nexd.token") || "";
export const setToken = (t) => {
  token = t || "";
  if (t) sessionStorage.setItem("nexd.token", t);
  else sessionStorage.removeItem("nexd.token");
};
export const hasToken = () => !!token;

async function call(path, { method = "GET", body, signal } = {}) {
  const res = await fetch(BASE + path, {
    method,
    signal,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

const api = {
  login: (username, password) =>
    call("/auth/login", { method: "POST", body: { username, password } }),

  connections: () => call("/connections"),
  createConnection: (c) => call("/connections", { method: "POST", body: c }),
  updateConnection: (id, c) => call(`/connections/${id}`, { method: "PUT", body: c }),
  deleteConnection: (id) => call(`/connections/${id}`, { method: "DELETE" }),
  testConnection: (id) => call(`/connections/${id}/test`, { method: "POST" }),

  catalog: (connectionId) =>
    call(`/catalog${connectionId ? `?connection_id=${connectionId}` : ""}`),

  processes: () => call("/processes"),
  process: (key) => call(`/processes/${key}`),
  createProcess: (definition, connectionId) =>
    call("/processes", { method: "POST", body: { definition, connection_id: connectionId } }),
  saveProcess: (key, definition, connectionId) =>
    call(`/processes/${key}`, { method: "PUT", body: { definition, connection_id: connectionId } }),
  deleteProcess: (key) => call(`/processes/${key}`, { method: "DELETE" }),

  executeAll: (key, definition, filters, signal) =>
    call(`/processes/${key}/execute-all`, {
      method: "POST", body: { definition, filters }, signal,
    }),
  previewSql: (key, box, definition, filters) =>
    call(`/processes/${key}/preview-sql`, {
      method: "POST", body: { box, definition, filters },
    }),
  filterOptions: (key, clientId) =>
    call(`/processes/${key}/filters/${clientId}/options`),

  publish: (key) => call(`/processes/${key}/publish`, { method: "POST" }),
  unpublish: (key) => call(`/processes/${key}/unpublish`, { method: "POST" }),
};

export default api;
