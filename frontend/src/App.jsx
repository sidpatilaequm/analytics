/* App.jsx — the shell.

   One page. A row of buttons across the top, and a view that swaps beneath
   them: the report list, system settings, or the editor. */

import React from "react";
import api, { hasToken, setToken } from "./api.js";
import { StoreProvider, useStore } from "./store.jsx";
import { blankDoc, migrate } from "./model.js";
import Canvas from "./components/Canvas.jsx";
import { Reports, Settings } from "./components/Views.jsx";

export default function App() {
  return (
    <StoreProvider>
      <Shell />
    </StoreProvider>
  );
}

function Shell() {
  const { state, dispatch } = useStore();
  const [signedIn, setSignedIn] = React.useState(hasToken());
  const [saveMsg, setSaveMsg] = React.useState("");

  React.useEffect(() => {
    document.body.className = state.mode === "preview" ? "preview" : "design";
  }, [state.mode]);

  const reloadReports = React.useCallback(async () => {
    try { dispatch({ type: "reports", reports: await api.processes() }); }
    catch (e) { dispatch({ type: "error", error: e.message }); }
  }, [dispatch]);

  const reloadCatalog = React.useCallback(async () => {
    try {
      const r = await api.catalog(state.connectionId);
      dispatch({ type: "catalog", catalog: { tables: r.tables || [] } });
    } catch { dispatch({ type: "catalog", catalog: { tables: [] } }); }
  }, [dispatch, state.connectionId]);

  React.useEffect(() => {
    if (!signedIn) return;
    reloadReports();
    reloadCatalog();
  }, [signedIn, reloadReports, reloadCatalog]);

  /* ---- the execution loop: debounced, and abortable so a fast filter
     change cancels the request it supersedes ---- */
  React.useEffect(() => {
    if (state.view !== "editor" || !state.processKey) return undefined;
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      dispatch({ type: "busy", busy: true });
      try {
        const r = await api.executeAll(state.processKey, state.doc, state.filterState, ctrl.signal);
        dispatch({ type: "results", results: r.results || {} });
        dispatch({ type: "error", error: null });
      } catch (e) {
        if (e.name !== "AbortError") dispatch({ type: "error", error: e.message });
      } finally {
        dispatch({ type: "busy", busy: false });
      }
    }, 350);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [state.view, state.processKey, JSON.stringify(state.doc), JSON.stringify(state.filterState)]);

  React.useEffect(() => {
    setSaveMsg(state.dirty ? "unsaved changes" : state.processKey ? "saved" : "");
  }, [state.dirty, state.processKey]);

  if (!signedIn) return <Login onDone={() => setSignedIn(true)} />;

  const openReport = async (key) => {
    const full = await api.process(key);
    dispatch({ type: "open", doc: full.definition, key, connectionId: full.connection_id });
    reloadCatalog();
  };

  const newReport = async () => {
    const doc = { ...blankDoc(), sections: [] };
    const r = await api.createProcess(doc, state.connectionId);
    await reloadReports();
    dispatch({ type: "open", doc, key: r.process_key, connectionId: state.connectionId });
  };

  const save = async () => {
    if (!state.processKey) return;
    await api.saveProcess(state.processKey, state.doc, state.connectionId);
    dispatch({ type: "saved", key: state.processKey });
    setSaveMsg("saved just now");
    reloadReports();
  };

  const leave = async (view) => {
    if (state.dirty) await save();
    dispatch({ type: "close" });
    dispatch({ type: "view", view });
    reloadReports();
  };

  const publish = async () => {
    if (state.published) {
      await api.unpublish(state.processKey);
      dispatch({ type: "published", published: null });
    } else {
      await save();
      const r = await api.publish(state.processKey);
      dispatch({ type: "published", published: r });
    }
    reloadReports();
  };

  const editing = state.view === "editor";

  return (
    <div className="pane">
      <div className="wordmark"><b>NEXD</b><span>v14</span></div>

      <div className="pagebar">
        {editing ? (
          <>
            <button className="pb" onClick={() => leave("reports")}>Reports / Dashboards</button>
            <button className="pb" onClick={() => leave("settings")}>System Settings</button>
            <span className="pbsep" />
            <button className="pb" aria-pressed={state.mode === "design"}
              onClick={() => dispatch({ type: "mode", mode: "design" })}>Design</button>
            <button className="pb" aria-pressed={state.mode === "preview"}
              onClick={() => dispatch({ type: "mode", mode: "preview" })}>Preview</button>
            <button className="pb" onClick={save}>Save</button>
            <button className={`pb ${state.published ? "live" : "go"}`} onClick={publish}>
              {state.published ? "Unpublish" : "Publish"}
            </button>
            <button className="pb" onClick={() => leave("reports")}>Close</button>
          </>
        ) : (
          <>
            <button className="pb go" onClick={newReport}>New</button>
            <button className="pb" aria-pressed={state.view === "reports"}
              onClick={() => dispatch({ type: "view", view: "reports" })}>Reports / Dashboards</button>
            <button className="pb" aria-pressed={state.view === "settings"}
              onClick={() => dispatch({ type: "view", view: "settings" })}>System Settings</button>
          </>
        )}
        <span className="espacer" />
        <span className="sstate">{state.busy ? "running…" : saveMsg}</span>
      </div>

      {state.published && editing && (
        <div className="pubbar">
          <b>Live.</b>
          <code>{state.published.url}</code>
          <button className="sbtn" onClick={() =>
            navigator.clipboard?.writeText(state.published.url)}>Copy link</button>
          <span className="conn-sub">
            pinned to version {state.published.pinned_version}
          </span>
        </div>
      )}

      {state.error && <div className="fx bad" style={{ marginBottom: 14 }}>{state.error}</div>}

      {state.view === "reports" && (
        <Reports onOpen={openReport} onNew={newReport} reload={reloadReports} />
      )}
      {state.view === "settings" && <Settings reloadCatalog={reloadCatalog} />}
      {editing && <Canvas />}

      {state.notice && (
        <div className="toast" onAnimationEnd={() => dispatch({ type: "notice", notice: null })}>
          {state.notice}
        </div>
      )}
    </div>
  );
}

function Login({ onDone }) {
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState("");

  const submit = async () => {
    try {
      const r = await api.login(username, password);
      setToken(r.token);
      onDone();
    } catch (e) { setError(e.message); }
  };

  return (
    <div className="pane" style={{ maxWidth: 420, paddingTop: 80 }}>
      <div className="wordmark"><b>NEXD</b><span>v14</span></div>
      <section className="hcard">
        <header><h2>Sign in</h2></header>
        <div style={{ padding: "18px 20px" }}>
          <div className="fld">
            <label>Username</label>
            <input value={username} autoFocus
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()} />
          </div>
          <div className="fld">
            <label>Password</label>
            <input type="password" value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()} />
          </div>
          {error && <div className="fx bad">{error}</div>}
          <button className="pb go" style={{ width: "100%", marginTop: 12 }} onClick={submit}>
            Sign in
          </button>
        </div>
      </section>
    </div>
  );
}
