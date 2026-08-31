/* Box.jsx — one box on the canvas, its toolbar, and its settings panel.

   Everything is configured on the box itself. There is no separate inspector;
   selecting a box reveals its own strip and its own panel, in place. */

import React from "react";
import { useStore } from "../store.jsx";
import Chart, { Legend, legendItems } from "../charts/Chart.jsx";
import {
  AGGS, BOX_KINDS, CHARTS, FMTS, colOptions, fmtCell, fmtNumber,
  frameStyle, normS, styleObj, widthOptions,
} from "../model.js";
import {
  Check, Chips, ConfirmBar, DeleteButton, Field, FormatPanel, FrameControls,
  Group, Hint, Row, RoleChips, SegBar, Select, SourceEditor, Switch, Text, TextArea, Toggles,
} from "./Panels.jsx";
/* An editable line that writes on blur, so typing never re-renders the tree. */
function Editable({ value, onChange, className, placeholder, style }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (ref.current && ref.current.textContent !== (value || ""))
      ref.current.textContent = value || "";
  }, [value]);
  return (
    <div
      ref={ref}
      className={className}
      style={style}
      contentEditable
      suppressContentEditableWarning
      data-ph={placeholder}
      onBlur={(e) => onChange(e.currentTarget.textContent)}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }}
    />
  );
}

export default function Box({ box, cols }) {
  const { state, dispatch } = useStore();
  const selected = state.sel?.kind === "box" && state.sel.id === box.id;
  const pending = state.pendingDel?.kind === "box" && state.pendingDel.id === box.id;
  const design = state.mode === "design";
  const span = Math.max(1, Math.min(cols, box.span || 1));

  const set = (path, value) =>
    dispatch({ type: "set", target: "box", id: box.id, path, value });

  const cls = ["box"];
  if (box.frame?.on) cls.push("framed");
  if (box.visible === false) cls.push("boxoff");
  if (selected) cls.push("sel");

  return (
    <div
      className={cls.join(" ")}
      style={{
        gridColumn: `span ${span}`,
        ...(box.style.bg ? { background: box.style.bg } : {}),
        ...(box.style.align ? { textAlign: box.style.align } : {}),
        ...frameStyle(box.frame),
      }}
      onMouseDown={(e) => {
        if (!design) return;
        e.stopPropagation();
        if (!selected) dispatch({ type: "select", sel: { kind: "box", id: box.id } });
      }}
    >
      {selected && design && <Toolbar box={box} />}

      {box.titleVisible !== false && (
        <Editable className="box-title" value={box.title} placeholder="Unnamed box"
          style={styleObj(normS(box.titleStyle))}
          onChange={(v) => set("title", v)} />
      )}

      <div style={styleObj(box.style, { bg: true, align: true })}>
        <Body box={box} />
      </div>

      {pending ? (
        <ConfirmBar what={`the box "${box.title || "Unnamed"}"`}
          onYes={() => dispatch({ type: "delete", sel: { kind: "box", id: box.id } })}
          onNo={() => dispatch({ type: "cancelDel" })} />
      ) : selected && state.cfgOpen && design ? (
        <Panel box={box} cols={cols} />
      ) : null}
    </div>
  );
}

function Toolbar({ box }) {
  const { dispatch } = useStore();
  const stop = (fn) => (e) => { e.stopPropagation(); fn(); };
  return (
    <div className="btools">
      <button title="Set up this box"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={stop(() => dispatch({ type: "cfgOpen", open: true }))}>⚙</button>
      <button title="Move earlier" onMouseDown={(e) => e.stopPropagation()}
        onClick={stop(() => dispatch({ type: "moveBox", id: box.id, d: -1 }))}>←</button>
      <button title="Move later" onMouseDown={(e) => e.stopPropagation()}
        onClick={stop(() => dispatch({ type: "moveBox", id: box.id, d: 1 }))}>→</button>
      <button title="Duplicate" onMouseDown={(e) => e.stopPropagation()}
        onClick={stop(() => dispatch({ type: "dupBox", id: box.id }))}>⧉</button>
      <button className="warn" title="Delete this box" onMouseDown={(e) => e.stopPropagation()}
        onClick={stop(() => dispatch({ type: "askDel", sel: { kind: "box", id: box.id } }))}>✕</button>
    </div>
  );
}

/* ---------------- what a box shows ---------------- */
const stateNote = (box, catalog) => {
  if (!catalog.tables.length) return ["No tables available", "Connect a database in System Settings"];
  if (!box.src.base) return ["No table chosen", "Open Set up and pick one"];
  return ["Waiting on the database", "Run the report to fill this in"];
};

const Placeholder = ({ msg, sub, height }) => (
  <div className="ph" style={height ? { minHeight: height } : undefined}>
    <b>{msg}</b>{sub && <span>{sub}</span>}
  </div>
);

function Body({ box }) {
  const { state, dispatch } = useStore();
  const result = state.results[box.id];
  const locale = state.doc.numberFormat;

  if (box.kind === "note") {
    return (
      <Editable className="note-body" value={box.note.html}
        placeholder="Write a note, a caveat, a definition…"
        onChange={(v) => dispatch({ type: "set", target: "box", id: box.id, path: "note.html", value: v })} />
    );
  }

  if (box.kind === "value") {
    const c = box.value;
    let shown;
    if (c.source === "manual") {
      shown = (
        <Editable className="kpi-inline" value={c.manual} placeholder="0"
          onChange={(v) => dispatch({ type: "set", target: "box", id: box.id, path: "value.manual", value: v })} />
      );
    } else if (result?.error) {
      return <Placeholder msg="Formula problem" sub={result.error} />;
    } else {
      const v = result?.value;
      shown = v === null || v === undefined ? "—" : fmtNumber(v, c.decimals, locale);
    }
    return (
      <>
        <div className="kpi" style={{ color: c.tone || "#1A2326" }}>
          {c.prefix}{shown}{c.suffix}
          {c.unit && <span className="kpi-unit">{c.unit}</span>}
        </div>
        {c.delta && (
          <div className={`kpi-delta ${c.deltaDir}`}>
            {c.deltaDir === "up" ? "▲" : c.deltaDir === "down" ? "▼" : "■"} {c.delta}
          </div>
        )}
        {c.showTrack && (
          <div className="track">
            <i style={{ width: `${Math.max(0, Math.min(100, c.trackPct))}%`,
              background: c.tone || "#0D6E62" }} />
          </div>
        )}
        {c.note && <div className="kpi-note">{c.note}</div>}
      </>
    );
  }

  if (box.kind === "chart") {
    const c = box.chart;
    const data = result?.data || [];
    if (!data.length) {
      const [msg, sub] = stateNote(box, state.catalog);
      const label = (CHARTS.find((x) => x[0] === c.type) || ["", "Chart"])[1];
      return <Placeholder msg={`${label} · ${msg}`} sub={sub} height={c.height || 220} />;
    }
    const pos = c.legendPos || "bottom";
    return (
      <div className={`chartwrap lp-${pos}`}>
        <div className="chartsvg"><Chart data={data} cfg={c} /></div>
        {c.legend && <Legend items={legendItems(data, c)} position={pos} />}
      </div>
    );
  }

  /* table */
  const c = box.table;
  const shown = c.columns.filter((x) => x.on);
  if (!shown.length)
    return <div className="empty">No columns selected. Open <b>⚙ Set up</b> and tick some.</div>;
  const rows = result?.rows || [];
  const [msg, sub] = stateNote(box, state.catalog);
  const alias = (ref) => ref.replace(/\./g, "__");

  return (
    <table className="rt">
      <thead>
        <tr>
          {shown.map((col) => {
            const i = c.columns.indexOf(col);
            return (
              <th key={col.col} className={col.align === "right" ? "num" : undefined}
                style={{ ...styleObj(normS(c.headStyle)), ...(col.width ? { width: col.width } : {}) }}>
                <Editable value={col.label} placeholder="name"
                  onChange={(v) => dispatch({ type: "set", target: "box", id: box.id,
                    path: `table.columns.${i}.label`, value: v })} />
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.length ? rows.slice(0, c.limit || 10).map((r, i) => (
          <tr key={i} className={c.zebra && i % 2 ? "z" : undefined}>
            {shown.map((col) => (
              <td key={col.col}
                className={col.align === "right" ? "num" : undefined}
                style={col.align === "center" ? { textAlign: "center" } : undefined}>
                {fmtCell(r[alias(col.col)], col.fmt, locale)}
              </td>
            ))}
          </tr>
        )) : (
          <>
            {[0, 1, 2].map((i) => (
              <tr key={i} className={`ghost${c.zebra && i % 2 ? " z" : ""}`}>
                {shown.map((col) => (
                  <td key={col.col} className={col.align === "right" ? "num" : undefined}>—</td>
                ))}
              </tr>
            ))}
            <tr>
              <td className="ghost-note" colSpan={shown.length}>{msg} · {sub}</td>
            </tr>
          </>
        )}
      </tbody>
      {c.totals && rows.length > 0 && (
        <tfoot>
          <tr>
            {shown.map((col, i) => {
              const isNum = typeof rows[0][alias(col.col)] === "number";
              return (
                <td key={col.col} className={col.align === "right" ? "num" : undefined}>
                  {i === 0 ? "Total" : isNum
                    ? fmtCell(rows.reduce((a, r) => a + (+r[alias(col.col)] || 0), 0), col.fmt, locale)
                    : ""}
                </td>
              );
            })}
          </tr>
        </tfoot>
      )}
    </table>
  );
}

/* ---------------- settings ---------------- */
function Panel({ box, cols }) {
  const { state, dispatch } = useStore();
  const tab = state.cfgTab;
  const set = (path, value) =>
    dispatch({ type: "set", target: "box", id: box.id, path, value });
  const del = () => dispatch({ type: "askDel", sel: { kind: "box", id: box.id } });

  return (
    <div className="cfg" onMouseDown={(e) => e.stopPropagation()}>
      <div className="cfg-tabs">
        {["data", "format", "border"].map((t) => (
          <button key={t} aria-pressed={tab === t}
            onClick={() => dispatch({ type: "cfgTab", tab: t })}>
            {t === "data" ? "Data" : t === "format" ? "Format" : "Border"}
          </button>
        ))}
      </div>

      {tab === "border" && (
        <>
          <Group>Box border</Group>
          <FrameControls frame={box.frame} what="this box"
            onSet={(k, v) => set(`frame.${k}`, v)} />
          <Hint>Off keeps the standard box outline.</Hint>
          <Group>Remove</Group>
          <DeleteButton what="this box" onClick={del} />
        </>
      )}

      {tab === "format" && (
        <>
          {box.titleVisible !== false && (
            <FormatPanel label="Box title" style={box.titleStyle}
              onSet={(k, v) => set(`titleStyle.${k}`, v)} />
          )}
          <FormatPanel label={box.kind === "note" ? "Note text" : "Content"} style={box.style}
            onSet={(k, v) => set(`style.${k}`, v)} />
          <Group>Box</Group>
          <Toggles>
            <Check on={box.useFilters} label="Obey the filter bar"
              onChange={(v) => set("useFilters", v)} />
          </Toggles>
          {box.kind === "value" && <ValueFormat box={box} set={set} />}
          {box.kind === "chart" && <ChartFormat box={box} set={set} />}
          {box.kind === "table" && <TableFormat box={box} set={set} />}
          <Group>Remove</Group>
          <DeleteButton what="this box" onClick={del} />
        </>
      )}

      {tab === "data" && (
        <>
          <Row style={{ marginBottom: 2 }}>
            <Field label="Box name">
              <Text value={box.title} placeholder="Approval rate"
                onChange={(v) => set("title", v)} />
            </Field>
          </Row>
          <div className="swblock">
            <Switch on={box.visible !== false} label="Show this box"
              onChange={(v) => set("visible", v)} />
            <Switch on={box.titleVisible !== false} label="Show box heading"
              onChange={(v) => set("titleVisible", v)} />
          </div>
          <Group>Who can see this box on a published link</Group>
          <RoleChips value={box.roles} onChange={(v) => set("roles", v)} />
          <Hint>Nothing picked = shown on every published link, whatever role opened it.</Hint>
          <Group>This box shows</Group>
          <SegBar value={box.kind} options={BOX_KINDS} onChange={(v) => set("kind", v)} />
          <Row style={{ marginTop: 10 }}>
            <Field label="Width">
              <Select value={Math.max(1, Math.min(cols, box.span || 1))} numeric
                options={widthOptions(cols)} onChange={(v) => set("span", v)} />
            </Field>
          </Row>

          {box.kind === "value" && <ValueData box={box} set={set} />}
          {box.kind === "chart" && <ChartData box={box} set={set} />}
          {box.kind === "table" && <TableData box={box} set={set} />}
          {box.kind === "note" && (
            <Hint>Click into the box and type. Use <b>Format</b> for size, colour and alignment.</Hint>
          )}

          <Group>Remove</Group>
          <DeleteButton what="this box" onClick={del} />
        </>
      )}
    </div>
  );
}

/* ---- value ---- */
function ValueData({ box, set }) {
  const { state } = useStore();
  const c = box.value;
  const cols = colOptions(state.catalog, box.src).map((x) => x.name);
  return (
    <>
      <Group>Where the number comes from</Group>
      <Chips value={c.source} onChange={(v) => set("value.source", v)}
        options={[["data", "One aggregate"], ["formula", "An Excel formula"],
          ["manual", "A number I type"]]} />
      {c.source === "data" && (
        <Row style={{ marginTop: 9 }}>
          <Field label="Aggregate">
            <Select value={c.agg} options={AGGS} onChange={(v) => set("value.agg", v)} />
          </Field>
          <Field label="Of column">
            <Select value={c.column} options={cols} onChange={(v) => set("value.column", v)} />
          </Field>
        </Row>
      )}
      {c.source === "manual" && (
        <Hint>Click the number in the box and type over it.</Hint>
      )}
      {c.source === "formula" && <FormulaBuilder box={box} c={c} set={set} />}
      <Group>Presentation</Group> 
      <Row>
        <Field label="Prefix"><Text value={c.prefix} placeholder="₹" onChange={(v) => set("value.prefix", v)} /></Field>
        <Field label="Suffix"><Text value={c.suffix} placeholder="%" onChange={(v) => set("value.suffix", v)} /></Field>
        <Field label="Unit note"><Text value={c.unit} placeholder="per month" onChange={(v) => set("value.unit", v)} /></Field>
      </Row>
      <Row>
        <Field label="Change label">
          <Text value={c.delta} placeholder="8.2% vs last quarter" onChange={(v) => set("value.delta", v)} />
        </Field>
        <Field label="Direction">
          <Chips value={c.deltaDir} options={[["up", "▲"], ["down", "▼"], ["flat", "■"]]}
            onChange={(v) => set("value.deltaDir", v)} />
        </Field>
      </Row>
      <Row>
        <Field label="Footnote">
          <Text value={c.note} placeholder="Excludes cancelled orders" onChange={(v) => set("value.note", v)} />
        </Field>
      </Row>
      {c.source !== "manual" && <SourceEditor box={box} />}
    </>
  );
}

function buildFormula(c) {
  const wrap = (s) => {
    s = (s || "").trim();
    if (!s) return "0";
    return /^[[(]/.test(s) || /^-?\d+(\.\d+)?$/.test(s) ? s : `[${s}]`;
  };
  const body = `${wrap(c.fLeft)} ${c.fOp || "/"} ${wrap(c.fRight)}`
    + (c.fExtra?.trim() ? ` ${c.fExtra.trim()}` : "");
  return `=ROUND(${body}, ${c.round ?? 2})`;
}

const FORMULA_OPS = ["+", "-", "*", "/", "^"];

function FormulaBuilder({ box, c, set }) {
  const update = (patch) => {
    const next = { ...c, ...patch };
    set("value.formula", buildFormula(next));
    for (const [k, v] of Object.entries(patch)) set(`value.${k}`, v);
  };

  return (
    <>
            <Group>Round to</Group>
      <Field label="Decimal places">
        <Select value={String(c.round ?? 2)}
          options={[["1", "1 decimal"], ["2", "2 decimals"], ["3", "3 decimals"], ["4", "4 decimals"]]}
          onChange={(v) => update({ round: Number(v) })} />
      </Field>

      <Group>Build the formula</Group>
      <div className="fbrow">
        <Text value={c.fLeft} placeholder="e.g. Approved vendors"
          onChange={(v) => update({ fLeft: v })} />
        <Select value={c.fOp || "/"} options={FORMULA_OPS} onChange={(v) => update({ fOp: v })} />
        <Text value={c.fRight} placeholder="e.g. Total no of vendors"
          onChange={(v) => update({ fRight: v })} />
      </div>
      <Field label="Then (optional)">
        <Text value={c.fExtra} placeholder="* 100" onChange={(v) => update({ fExtra: v })} />
      </Field>
      <Hint>
        Runs after the division above, before rounding — so <span className="mono">* 100</span> here
        turns a ratio into a percentage. Pair it with a <span className="mono">%</span> suffix under
        Presentation below to label it.
      </Hint>

      <Group>The formula this builds</Group>
      <div className="sqlbox">{c.formula || buildFormula(c)}</div>
      <Hint>
        Type the name of another box in the first or third field and it's matched by title,
        e.g. <span className="mono">Approved vendors</span> becomes{" "}
        <span className="mono">[Approved vendors]</span> automatically. A plain number works too.
      </Hint>
    </>
  );
}

function ValueFormat({ box, set }) {
  const c = box.value;
  return (
    <>
      <Row>
        <Field label="Colour">
          <Chips value={c.tone} onChange={(v) => set("value.tone", v)}
            options={[["#1A2326", "Ink"], ["#0D6E62", "Oxide"], ["#3B5BA5", "Blue"],
              ["#96610A", "Amber"], ["#9E332B", "Iron"]]} />
        </Field>
        <Field label="Decimals">
          <Select value={c.decimals} numeric options={[0, 1, 2]}
            onChange={(v) => set("value.decimals", v)} />
        </Field>
      </Row>
      <Toggles>
        <Check on={c.showTrack} label="Progress bar" onChange={(v) => set("value.showTrack", v)} />
      </Toggles>
      {c.showTrack && (
        <Row>
          <Field label="Fill %">
            <Text type="number" value={c.trackPct} onChange={(v) => set("value.trackPct", Number(v))} />
          </Field>
        </Row>
      )}
    </>
  );
}

/* ---- chart ---- */
function ChartData({ box, set }) {
  const { state } = useStore();
  const c = box.chart;
  const cols = colOptions(state.catalog, box.src).map((x) => x.name);
  return (
    <>
      <Group>Chart</Group>
      <Chips value={c.type} options={CHARTS} onChange={(v) => set("chart.type", v)} />
      <Row style={{ marginTop: 9 }}>
        <Field label="Group by">
          <Select value={c.category} options={cols} onChange={(v) => set("chart.category", v)} />
        </Field>
        <Field label="Aggregate">
          <Select value={c.agg} options={AGGS} onChange={(v) => set("chart.agg", v)} />
        </Field>
        <Field label="Of column">
          <Select value={c.column} options={cols} onChange={(v) => set("chart.column", v)} />
        </Field>
      </Row>
      <Row>
        <Field label="Sort by">
          <Select value={c.sort} options={[["value", "Value"], ["label", "Name"]]}
            onChange={(v) => set("chart.sort", v)} />
        </Field>
        <Field label="Order">
          <Select value={c.dir} options={[["desc", "High → low"], ["asc", "Low → high"]]}
            onChange={(v) => set("chart.dir", v)} />
        </Field>
        <Field label="Keep top">
          <Select value={c.limit} numeric options={[[0, "All"], 5, 6, 8, 10, 12]}
            onChange={(v) => set("chart.limit", v)} />
        </Field>
      </Row>
      <SourceEditor box={box} />
    </>
  );
}

function ChartFormat({ box, set }) {
  const c = box.chart;
  return (
    <>
      <Row>
        <Field label="Height">
          <Select value={c.height} numeric options={[160, 200, 220, 260, 320, 400, 480]}
            onChange={(v) => set("chart.height", v)} />
        </Field>
        <Field label="Colour set">
          <Select value={c.palette} numeric
            options={[[0, "Oxide"], [1, "Blue"], [2, "Amber"], [3, "Iron"]]}
            onChange={(v) => set("chart.palette", v)} />
        </Field>
      </Row>
      <Toggles>
        <Check on={c.grid} label="Grid lines" onChange={(v) => set("chart.grid", v)} />
        <Check on={c.values} label="Show values" onChange={(v) => set("chart.values", v)} />
        <Check on={c.legend} label="Legend" onChange={(v) => set("chart.legend", v)} />
      </Toggles>
      {c.legend && (
        <Row>
          <Field label="Legend sits">
            <Chips value={c.legendPos || "bottom"}
              options={[["top", "Above"], ["bottom", "Below"], ["right", "Right"]]}
              onChange={(v) => set("chart.legendPos", v)} />
          </Field>
        </Row>
      )}
      <Hint>Box width is set in the Data tab; height is here.</Hint>
    </>
  );
}

/* ---- table ---- */
function TableData({ box, set }) {
  const { dispatch } = useStore();
  const c = box.table;
  return (
    <>
      <Group>Rows</Group>
      <Row>
        <Field label="Rows">
          <Select value={c.limit} numeric options={[5, 8, 10, 15, 25, 50]}
            onChange={(v) => set("table.limit", v)} />
        </Field>
        <Field label="Sort by">
          <Select value={c.sort} options={["", ...c.columns.map((x) => x.col)]}
            onChange={(v) => set("table.sort", v)} />
        </Field>
        <Field label="Order">
          <Select value={c.dir} options={[["asc", "A → Z"], ["desc", "Z → A"]]}
            onChange={(v) => set("table.dir", v)} />
        </Field>
      </Row>
      <Group>Columns — order, tick, rename, format</Group>
      <div className="collist">
        {c.columns.map((col, i) => (
          <div className="colrow" key={col.col}>
            <span className="colmv">
              <button className="xbtn" title="Move up"
                onClick={() => dispatch({ type: "moveColumn", id: box.id, index: i, d: -1 })}>↑</button>
              <button className="xbtn" title="Move down"
                onClick={() => dispatch({ type: "moveColumn", id: box.id, index: i, d: 1 })}>↓</button>
            </span>
            <input type="checkbox" checked={!!col.on}
              onChange={(e) => set(`table.columns.${i}.on`, e.target.checked)} />
            <span>
              <Text value={col.label} onChange={(v) => set(`table.columns.${i}.label`, v)} />
              <div className="cn">{col.col}</div>
            </span>
            <Select value={col.fmt} options={FMTS} onChange={(v) => set(`table.columns.${i}.fmt`, v)} />
            <Select value={col.align} options={[["left", "Left"], ["center", "Centre"], ["right", "Right"]]}
              onChange={(v) => set(`table.columns.${i}.align`, v)} />
            <Text value={col.width} placeholder="auto"
              onChange={(v) => set(`table.columns.${i}.width`, v)} />
          </div>
        ))}
      </div>
      <Hint>Headings are also editable straight in the rendered table.</Hint>
      <SourceEditor box={box} />
    </>
  );
}

function TableFormat({ box, set }) {
  const c = box.table;
  return (
    <>
      <Toggles>
        <Check on={c.zebra} label="Striped rows" onChange={(v) => set("table.zebra", v)} />
        <Check on={c.totals} label="Total row" onChange={(v) => set("table.totals", v)} />
      </Toggles>
      <FormatPanel label="Column headings" style={c.headStyle}
        onSet={(k, v) => set(`table.headStyle.${k}`, v)} />
    </>
  );
}
