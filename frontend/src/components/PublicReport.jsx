import React from "react";
import { StoreProvider, useStore } from "../store.jsx";
import Box from "./Box.jsx";
import { normS, styleObj, frameStyle } from "../model.js";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

async function getPublishedReport(slug) {
  const res = await fetch(`${API_BASE}/r/${encodeURIComponent(slug)}`);

  const text = await res.text();

  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error("Published report returned invalid JSON");
  }

  if (!res.ok) {
    throw new Error(data.error || `${res.status} ${res.statusText}`);
  }

  return data;
}

async function executePublished(slug, definition) {
  const res = await fetch(`${API_BASE}/r/${encodeURIComponent(slug)}/execute`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });

  const text = await res.text();

  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error("Published report execution returned invalid JSON");
  }

  if (!res.ok) {
    throw new Error(data.error || `${res.status} ${res.statusText}`);
  }

  return data;
}

export default function PublicReport() {
  const slug = window.location.pathname.split("/r/")[1];

  return (
    <StoreProvider>
      <PublicReportInner slug={decodeURIComponent(slug || "")} />
    </StoreProvider>
  );
}

function PublicReportInner({ slug }) {
  const { state, dispatch } = useStore();

  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const report = await getPublishedReport(slug);

        if (cancelled) return;

        dispatch({
          type: "open",
          doc: report.definition,
          key: report.process_key,
          connectionId: report.connection_id || null,
        });

        dispatch({
          type: "mode",
          mode: "preview",
        });

        try {
          const result = await executePublished(slug, report.definition);

          if (!cancelled) {
            dispatch({
              type: "results",
              results: result.results || {},
            });
          }
        } catch (executeError) {
          if (!cancelled) {
            setError(executeError.message);
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError(e.message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [slug, dispatch]);

  if (loading) {
    return (
      <div className="pane">
        <div className="hcard">
          <div style={{ padding: 30 }}>
            Loading dashboard...
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="pane">
        <div className="hcard">
          <div style={{ padding: 30 }}>
            <h2>Unable to load dashboard</h2>
            <div className="fx bad">{error}</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="pane public-report">
      <div className="wordmark">
        <b>NEXD</b>
        <span>Public Dashboard</span>
      </div>

      <PublicCanvas doc={state.doc} />
    </div>
  );
}

function PublicCanvas({ doc }) {
  return (
    <div className="sheet">
      <div
        className="rep-name-wrap"
        style={
          normS(doc.nameStyle).align
            ? { textAlign: normS(doc.nameStyle).align }
            : undefined
        }
      >
        <div
          className="rep-name"
          style={styleObj(normS(doc.nameStyle))}
        >
          {doc.name}
        </div>
      </div>

      {doc.sections.map((section, index) => (
        <PublicSection
          key={section.id}
          section={section}
          index={index + 1}
        />
      ))}
    </div>
  );
}

function PublicSection({ section, index }) {
  if (section.visible === false) return null;

  const cols = Math.max(
    1,
    Math.min(12, Number(section.cols) || 4)
  );

  const nst = normS(section.style);
  const dst = normS(section.descStyle);

  const nameVisible = section.nameVisible !== false;
  const subVisible = section.subVisible !== false;

  const ruleStyle = {
    ...(nst.color ? { background: nst.color } : {}),
    ...(nst.align === "center"
      ? { marginLeft: "auto", marginRight: "auto" }
      : nst.align === "right"
      ? { marginLeft: "auto" }
      : {}),
  };

  return (
    <div
      className={`sec${section.frame?.on ? " framed" : ""}`}
      style={frameStyle(section.frame)}
    >
      {nameVisible && (
        <>
          <div
            className="sec-head"
            style={
              nst.align
                ? {
                    justifyContent:
                      nst.align === "center"
                        ? "center"
                        : nst.align === "right"
                        ? "flex-end"
                        : "flex-start",
                  }
                : undefined
            }
          >
            <div
              className="sec-name"
              style={styleObj(nst)}
            >
              {section.name}
            </div>
          </div>

          {section.rule !== false && (
            <div
              className="sec-rule"
              style={ruleStyle}
            />
          )}
        </>
      )}

      {subVisible && (
        <div
          className="sec-desc"
          style={styleObj(dst)}
        >
          {section.desc}
        </div>
      )}

      <div
        className="grid"
        style={{
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
        }}
      >
        {section.boxes
          .filter((box) => box.visible !== false)
          .map((box) => (
            <PublicBox
              key={box.id}
              box={box}
              cols={cols}
            />
          ))}
      </div>
    </div>
  );
}

function PublicBox({ box, cols }) {
  const span = Math.max(
    1,
    Math.min(cols, box.span || 1)
  );

  return (
    <div
      className={`box${box.frame?.on ? " framed" : ""}`}
      style={{
        gridColumn: `span ${span}`,
        ...(box.style?.bg
          ? { background: box.style.bg }
          : {}),
        ...(box.style?.align
          ? { textAlign: box.style.align }
          : {}),
        ...frameStyle(box.frame),
      }}
    >
      {box.titleVisible !== false && (
        <div
          className="box-title"
          style={styleObj(normS(box.titleStyle))}
        >
          {box.title}
        </div>
      )}

      <div style={styleObj(box.style, { bg: true, align: true })}>
        <PublicBoxBody box={box} />
      </div>
    </div>
  );
}

function PublicBoxBody({ box }) {
  const { state } = useStore();
  const result = state.results[box.id];
  const locale = state.doc.numberFormat;

  if (box.kind === "note") {
    return (
      <div
        className="note-body"
        dangerouslySetInnerHTML={{
          __html: box.note?.html || "",
        }}
      />
    );
  }

  if (box.kind === "value") {
    if (result?.error) {
      return (
        <div className="ph">
          <b>Formula problem</b>
          <span>{result.error}</span>
        </div>
      );
    }

    const v = result?.value;

    return (
      <>
        <div
          className="kpi"
          style={{ color: box.value?.tone || "#1A2326" }}
        >
          {box.value?.prefix || ""}
          {v === null || v === undefined
            ? "—"
            : formatNumber(
                v,
                box.value?.decimals,
                locale
              )}
          {box.value?.suffix || ""}
          {box.value?.unit && (
            <span className="kpi-unit">
              {box.value.unit}
            </span>
          )}
        </div>

        {box.value?.note && (
          <div className="kpi-note">
            {box.value.note}
          </div>
        )}
      </>
    );
  }

  if (box.kind === "chart") {
    const Chart = require("../charts/Chart.jsx").default;

    const data = result?.data || [];

    if (!data.length) {
      return (
        <div className="ph">
          <b>No data</b>
        </div>
      );
    }

    return (
      <div className="chartwrap">
        <div className="chartsvg">
          <Chart data={data} cfg={box.chart} />
        </div>
      </div>
    );
  }

  const columns = (box.table?.columns || []).filter(
    (x) => x.on
  );

  const rows = result?.rows || [];

  if (!columns.length) {
    return (
      <div className="empty">
        No columns selected.
      </div>
    );
  }

  return (
    <table className="rt">
      <thead>
        <tr>
          {columns.map((col) => (
            <th
              key={col.col}
              className={
                col.align === "right" ? "num" : undefined
              }
            >
              {col.label || col.col}
            </th>
          ))}
        </tr>
      </thead>

      <tbody>
        {rows
          .slice(0, box.table?.limit || 10)
          .map((row, i) => (
            <tr
              key={i}
              className={
                box.table?.zebra && i % 2
                  ? "z"
                  : undefined
              }
            >
              {columns.map((col) => {
                const key = col.col.replace(/\./g, "__");

                return (
                  <td
                    key={col.col}
                    className={
                      col.align === "right"
                        ? "num"
                        : undefined
                    }
                  >
                    {row[key] ?? ""}
                  </td>
                );
              })}
            </tr>
          ))}
      </tbody>
    </table>
  );
}

function formatNumber(value, decimals, locale) {
  const n = Number(value);

  if (!Number.isFinite(n)) return String(value);

  return n.toLocaleString(locale || "en-IN", {
    minimumFractionDigits: decimals ?? 0,
    maximumFractionDigits: decimals ?? 0,
  });
}