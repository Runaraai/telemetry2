import React from "react";

const nodeWidth = 240;
const nodeHeight = 120;

const THEMES = {
  light: {
    canvas: "#f7f8fb",
    panelBg: "#ffffff",
    panelBorder: "#e6e8ef",
    panelShadow: "0 8px 24px rgba(22,29,37,.08)",
    text: "#0f172a",
    textMuted: "#6b7280",
    nodeBg: "#ffffff",
    nodeBorder: "#d6dae4",
    blockBorder: "#3b82f6",
    blockBg: "#f8fafc",
    chipPrimaryBg: "#e8f1ff",
    chipPrimaryText: "#1e40af",
    chipNeutralBg: "#eef1f6",
    chipNeutralText: "#374151",
    edge: "#0ea5e9",
    edgeSelected: "#fbbf24",
    detailsBg: "#ffffff",
    detailsCardBg: "#f2f5fb",
    detailsBorder: "#e3e7ef",
  },
  dark: {
    canvas: "#0c1222",
    panelBg: "#0f172a",
    panelBorder: "#1e293b",
    panelShadow: "0 10px 28px rgba(0,0,0,.5)",
    text: "#e5e7eb",
    textMuted: "#9aa7bd",
    nodeBg: "#141a2c",
    nodeBorder: "#2b3650",
    blockBorder: "#60a5fa",
    blockBg: "#0e1527",
    chipPrimaryBg: "rgba(59,130,246,.18)",
    chipPrimaryText: "#b7d8ff",
    chipNeutralBg: "#1b2438",
    chipNeutralText: "#d1d7e6",
    edge: "#7dd3fc",
    edgeSelected: "#fbbf24",
    detailsBg: "#0f172a",
    detailsCardBg: "#141a2c",
    detailsBorder: "#2b3650",
  },
};

const formatBytes = (b) =>
  b >= 1e9
    ? `${(b / 1e9).toFixed(2)} GB`
    : b >= 1e6
    ? `${(b / 1e6).toFixed(2)} MB`
    : b >= 1e3
    ? `${(b / 1e3).toFixed(2)} KB`
    : `${b ?? 0} B`;

const formatOps = (x) =>
  x >= 1e12
    ? `${(x / 1e12).toFixed(1)}T`
    : x >= 1e9
    ? `${(x / 1e9).toFixed(1)}G`
    : x >= 1e6
    ? `${(x / 1e6).toFixed(1)}M`
    : x >= 1e3
    ? `${(x / 1e3).toFixed(1)}K`
    : `${x || 0}`;

function createLayout(nodes, edges, direction = "TB") {
  const map = new Map(nodes.map((n) => [n.id, { ...n, children: [], parents: [] }])); 
  edges.forEach((e) => {
    const s = map.get(e.source ?? e.src);
    const t = map.get(e.target ?? e.dst);
    if (s && t) {
      s.children.push(t);
      t.parents.push(s);
    }
  });

  const roots = Array.from(map.values()).filter((n) => n.parents.length === 0);
  if (roots.length === 0 && nodes.length) roots.push(map.get(nodes[0].id));

  const levels = [];
  const seen = new Set();
  const q = roots.map((r) => ({ node: r, level: 0 }));
  while (q.length) {
    const { node, level } = q.shift();
    if (seen.has(node.id)) continue;
    seen.add(node.id);
    (levels[level] ||= []).push(node);
    node.children.forEach((c) => {
      if (!seen.has(c.id)) q.push({ node: c, level: level + 1 });
    });
  }
  map.forEach((n) => {
    if (!seen.has(n.id)) (levels[levels.length] ||= []).push(n);
  });

  const levelSpacing = direction === "TB" ? 200 : 300;
  const nodeSpacing = direction === "TB" ? 280 : 200;

  const result = [];
  levels.forEach((group, li) => {
    const total = (group.length - 1) * nodeSpacing;
    const start = -total / 2;
    group.forEach((n, idx) => {
      result.push(
        direction === "TB"
          ? { ...n, x: start + idx * nodeSpacing, y: li * levelSpacing }
          : { ...n, x: li * levelSpacing, y: start + idx * nodeSpacing }
      );
    });
  });
  return result;
}

const roleForNode = (n) => {
  if (n.type === "block") return "block";
  if (/(lm_head|embed_out|output|logits)$/i.test(n.id)) return "head";
  if (/(^|\.)(transformer|gpt|gpt_neox|model)$/.test(n.id)) return "transformer";
  return "kernel";
};

const roleColors = {
  light: { decoder: "#fce7f3", lm_head: "#dbeafe", embed_out: "#fef9c3", kernel: "#ffffff" },
  dark: { decoder: "#831843", lm_head: "#1e3a8a", embed_out: "#78350f", kernel: "#1f2937" },
};

// Enhanced decoder node coloring
const getDecoderNodeFill = (node, theme) => {
  const category = node.category || node.type;
  
  // Color mapping for different decoder operation types
  const decoderColors = {
    light: {
      'gemm': '#dbeafe',           // Light blue for matrix operations
      'attention.sdp': '#e9d5ff',  // Light purple for attention
      'attention': '#e9d5ff',      // Light purple for attention
      'norm': '#d1fae5',           // Light green for normalization
      'activation': '#fed7aa',     // Light orange for activations
      'layout': '#f3f4f6',         // Light gray for layout operations
      'eltwise': '#fecaca',        // Light red for element-wise operations
      'other': '#e2e8f0'           // Light slate for other operations
    },
    dark: {
      'gemm': '#1e3a8a',           // Dark blue for matrix operations
      'attention.sdp': '#581c87',  // Dark purple for attention
      'attention': '#581c87',      // Dark purple for attention
      'norm': '#064e3b',           // Dark green for normalization
      'activation': '#92400e',     // Dark orange for activations
      'layout': '#374151',         // Dark gray for layout operations
      'eltwise': '#991b1b',        // Dark red for element-wise operations
      'other': '#475569'           // Dark slate for other operations
    }
  };

  const colors = decoderColors[theme] || decoderColors.light;
  return colors[category] || colors.other;
};

// Enhanced node fill function
const getNodeFill = (node, theme) => {
  // If this is a decoder node (has category field), use decoder-specific coloring
  if (node.category) {
    return getDecoderNodeFill(node, theme);
  }
  
  // Otherwise use the original logic for workload nodes
  const id = node.id.toLowerCase();
  const colors = roleColors[theme] || roleColors.light;
  if (id.includes("decoder")) return colors.decoder;
  if (id.includes("lm_head")) return colors.lm_head;
  if (id.includes("embed_out")) return colors.embed_out;
  return colors.kernel;
};

// Add a function to get category abbreviation
const getCategoryAbbrev = (category) => {
  const abbrevs = {
    'gemm': 'MM',             // Matrix Multiplication
    'attention.sdp': 'ATT',   // Attention
    'attention': 'ATT',       // Attention
    'norm': 'NRM',           // Normalization
    'activation': 'ACT',     // Activation
    'layout': 'LAY',         // Layout/Reshape
    'eltwise': 'ELT',        // Element-wise
    'other': 'OTH'           // Other operations
  };
  return abbrevs[category] || abbrevs.other;
};

const DEFAULT_LAYER_PATTERNS = [
  /\.decoder\.layers\.(\d+)\b/i,
  /\.decoder\.blocks?\.(\d+)\b/i,
  /\.layers\.(\d+)\b/i,
  /\.h\.(\d+)\b/i,
  /\.blocks?\.(\d+)\b/i,
];

const getLayerIndex = (id, matchers) => {
  for (const rx of matchers) {
    const m = id.match(rx);
    if (m) return Number(m[1]);
  }
  return null;
};

function createWorkloadView(dag, matchers = DEFAULT_LAYER_PATTERNS) {
  const layerIds = new Set();
  const layerNodes = [];
  let totalOps = 0;
  let totalBytes = 0;

  for (const n of dag.nodes) {
    const idx = getLayerIndex(n.id, matchers);
    if (idx !== null && !Number.isNaN(idx)) {
      layerIds.add(n.id);
      layerNodes.push({ ...n, layerIndex: idx });
      totalOps += n.ops || 0;
      totalBytes += n.bytes?.HBM || 0;
    }
  }
  if (!layerNodes.length) return { nodes: dag.nodes, edges: dag.edges };

  const others = dag.nodes.filter((n) => !layerIds.has(n.id));
  const workloadNodes = others.map((n) => ({
    id: n.id,
    displayName: n.name || n.id,
    name: n.name,
    type: n.type,
    dtype: n.dtype,
    ops: n.ops,
    bytes: n.bytes,
  }));

  const decoderNode = {
    id: "decoder-block",
    displayName: `Decoder (${layerNodes.length} layers)`,
    name: "Decoder Block",
    type: "block",
    dtype: layerNodes[0]?.dtype,
    totalOps,
    totalBytes,
    layerCount: layerNodes.length,
  };

  const modelLike = workloadNodes.findIndex((n) =>
    /(^|\.)(model|gpt|gpt_neox|transformer)$/.test(n.id)
  );
  const headLike = workloadNodes.findIndex((n) => /(lm_head|embed_out|output|logits)$/i.test(n.id));
  if (modelLike >= 0 && headLike >= 0)
    workloadNodes.splice(Math.min(headLike, workloadNodes.length), 0, decoderNode);
  else workloadNodes.push(decoderNode);

  const seen = new Set();
  const outEdges = [];
  const add = (s, d, bytes) => {
    const k = `${s}->${d}`;
    if (!seen.has(k)) {
      seen.add(k);
      outEdges.push({ source: s, target: d, bytes });
    }
  };
  for (const e of dag.edges) {
    const sIs = layerIds.has(e.source ?? e.src);
    const dIs = layerIds.has(e.target ?? e.dst);
    if (!sIs && !dIs) add(e.source ?? e.src, e.target ?? e.dst, e.bytes);
    else if (!sIs && dIs) add(e.source ?? e.src, "decoder-block", e.bytes);
    else if (sIs && !dIs) add("decoder-block", e.target ?? e.dst, e.bytes);
  }
  return { nodes: workloadNodes, edges: outEdges };
}

const IconBtn = ({ title, onClick, children, t }) => (
  <button
    title={title}
    onClick={onClick}
    style={{
      width: 36,
      height: 36,
      display: "grid",
      placeItems: "center",
      borderRadius: 10,
      border: `1px solid ${t.panelBorder}`,
      background: t.panelBg,
      color: t.text,
      cursor: "pointer",
      boxShadow: t.panelShadow,
    }}
  >
    {children}
  </button>
);

const ZoomInIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24">
    <path d="M11 4v7H4v2h7v7h2v-7h7v-2h-7V4z" fill="currentColor" />
  </svg>
);
const ZoomOutIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24">
    <path d="M4 11v2h16v-2H4z" fill="currentColor" />
  </svg>
);
const FitIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24">
    <path
      d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </svg>
);
const ResetIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24">
    <path d="M12 6V3L8 7l4 4V8a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z" fill="currentColor" />
  </svg>
);
const FullscreenIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24">
    <path d="M4 4h7V2H2v9h2V4zm13-2v2h7v7h2V2h-9zM2 15v9h9v-2H4v-7H2zm20 7h-7v2h9v-9h-2v7z" fill="currentColor" />
  </svg>
);

function CustomGraph({
  layoutedNodes,
  edges,
  theme,
  selectedNodeId,
  selectedEdgeId,
  onNodeClick,
  onEdgeClick,
  viewTransform,
  setViewTransform,
  onAutoFit,
  limits,
}) {
  const t = THEMES[theme];
  const svgRef = React.useRef(null);
  const panningRef = React.useRef({
    active: false,
    mx0: 0,
    my0: 0,
    vx0: 0,
    vy0: 0,
    w0: 0,
    h0: 0,
    rectW: 1,
    rectH: 1,
  });

  React.useEffect(() => {
    if (!layoutedNodes.length) return;
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    for (const n of layoutedNodes) {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + nodeWidth);
      maxY = Math.max(maxY, n.y + nodeHeight);
    }
    const pad = 80;
    onAutoFit?.({
      x: minX - pad,
      y: minY - pad,
      width: maxX - minX + pad * 2,
      height: maxY - minY + pad * 2,
    });
  }, [layoutedNodes, onAutoFit]);

  const clampWidth = (w) => {
    const baseW = limits.baseWidth || viewTransform.width;
    const minW = baseW / (limits.maxScale || 8);
    const maxW = baseW / (limits.minScale || 0.2);
    return Math.max(minW, Math.min(maxW, w));
  };

  const zoomAtPoint = (clientX, clientY, factor) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x_s = clientX - rect.left;
    const y_s = clientY - rect.top;

    const newW = clampWidth(viewTransform.width / factor);
    const scale = newW / viewTransform.width;
    const newH = viewTransform.height * scale;

    const xPrime = viewTransform.x + (x_s / rect.width) * (viewTransform.width - newW);
    const yPrime = viewTransform.y + (y_s / rect.height) * (viewTransform.height - newH);

    setViewTransform({ x: xPrime, y: yPrime, width: newW, height: newH });
  };

  const startPan = (e) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    panningRef.current = {
      active: true,
      mx0: e.clientX,
      my0: e.clientY,
      vx0: viewTransform.x,
      vy0: viewTransform.y,
      w0: viewTransform.width,
      h0: viewTransform.height,
      rectW: rect.width,
      rectH: rect.height,
    };
  };
  const doPan = (e) => {
    const p = panningRef.current;
    if (!p.active) return;
    const dx = e.clientX - p.mx0;
    const dy = e.clientY - p.my0;
    const xPrime = p.vx0 - dx * (p.w0 / p.rectW);
    const yPrime = p.vy0 - dy * (p.h0 / p.rectH);
    setViewTransform((v) => ({ ...v, x: xPrime, y: yPrime }));
  };
  const endPan = () => {
    panningRef.current.active = false;
  };

  const onWheel = (e) => {
    e.preventDefault();
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();

    if (e.ctrlKey || e.metaKey) {
      const step = 1.15;
      const factor = e.deltaY < 0 ? step : 1 / step;
      zoomAtPoint(e.clientX, e.clientY, factor);
    } else {
      setViewTransform((v) => ({
        ...v,
        x: v.x + e.deltaX * (v.width / rect.width),
        y: v.y + e.deltaY * (v.height / rect.height),
      }));
    }
  };

  const onDoubleClick = (e) => {
    e.preventDefault();
    const step = 1.4;
    const factor = e.shiftKey ? 1 / step : step;
    zoomAtPoint(e.clientX, e.clientY, factor);
  };

  const edgePaths = React.useMemo(() => {
    return edges
      .map((edge, index) => {
        const sourceNode = layoutedNodes.find((n) => n.id === (edge.source ?? edge.src));
        const targetNode = layoutedNodes.find((n) => n.id === (edge.target ?? edge.dst));
        if (!sourceNode || !targetNode) return null;

        const sourceX = sourceNode.x + nodeWidth / 2;
        const sourceY = sourceNode.y + nodeHeight;
        const targetX = targetNode.x + nodeWidth / 2;
        const targetY = targetNode.y;
        const midY = sourceY + (targetY - sourceY) / 2;
        const path = `M ${sourceX} ${sourceY} Q ${sourceX} ${midY} ${targetX} ${targetY}`;
        return {
          id: `${edge.source}-${edge.target}-${index}`,
          path,
          sourceX,
          sourceY,
          targetX,
          targetY,
          midX: (sourceX + targetX) / 2,
          midY: (sourceY + targetY) / 2,
          bytes: edge.bytes,
          source: edge.source,
          target: edge.target,
          sourceNode,
          targetNode,
        };
      })
      .filter(Boolean);
  }, [layoutedNodes, edges]);

  return (
    <svg
      ref={svgRef}
      width="100%"
      height="100%"
      viewBox={`${viewTransform.x} ${viewTransform.y} ${viewTransform.width} ${viewTransform.height}`}
      style={{
        background: t.canvas,
        touchAction: "none",
        userSelect: "none",
        cursor: panningRef.current.active ? "grabbing" : "grab",
      }}
      onClick={() => {
        onNodeClick(null);
        onEdgeClick(null);
      }}
      onWheel={onWheel}
      onMouseDown={startPan}
      onMouseMove={doPan}
      onMouseUp={endPan}
      onMouseLeave={endPan}
      onDoubleClick={onDoubleClick}
    >
      <defs>
        <filter id="drop-shadow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="4" stdDeviation="8" floodOpacity="0.1" />
        </filter>
        <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill={t.edge} />
        </marker>
        <marker id="arrowhead-selected" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill={t.edgeSelected} />
        </marker>
      </defs>

      {edgePaths.map((e) => {
        const isSel = selectedEdgeId === e.id;
        return (
          <g key={e.id}>
            <path
              d={e.path}
              stroke="transparent"
              strokeWidth="20"
              fill="none"
              onClick={(evt) => {
                evt.stopPropagation();
                onEdgeClick(e);
              }}
            />
            <path
              d={e.path}
              stroke={isSel ? t.edgeSelected : t.edge}
              strokeWidth={isSel ? 4 : 2}
              fill="none"
              markerEnd={`url(#${isSel ? "arrowhead-selected" : "arrowhead"})`}
              onClick={(evt) => {
                evt.stopPropagation();
                onEdgeClick(e);
              }}
            />
            {e.bytes && (
              <text
                x={e.midX}
                y={e.midY - 6}
                textAnchor="middle"
                fontSize="11"
                fontWeight="600"
                style={{ pointerEvents: "none" }}
                fill={t.text}
              >
                <tspan
                  x={e.midX}
                  dy="0"
                  style={{ fill: t.text, stroke: t.canvas, strokeWidth: 3, paintOrder: "stroke" }}
                >
                  {formatBytes(e.bytes)}
                </tspan>
              </text>
            )}
          </g>
        );
      })}

      {layoutedNodes.map((node) => {
        const isSel = selectedNodeId === node.id;
        const role = roleForNode(node);
        return (
          <g
            key={node.id}
            transform={`translate(${node.x}, ${node.y})`}
            onClick={(evt) => {
              evt.stopPropagation();
              onNodeClick(node);
            }}
            style={{ cursor: "pointer" }}
          >
            <rect
              width={nodeWidth}
              height={nodeHeight}
              rx="16"
              fill={getNodeFill(node, theme)}
              stroke={
                isSel
                  ? THEMES[theme].blockBorder
                  : node.type === "block" || node.category
                  ? THEMES[theme].blockBorder
                  : THEMES[theme].nodeBorder
              }
              strokeWidth={isSel ? 3 : 1}
              filter="url(#drop-shadow)"
            />
            <foreignObject width={nodeWidth} height={nodeHeight}>
              <div
                style={{
                  padding: 14,
                  height: "100%",
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  color: THEMES[theme].text,
                  fontFamily: "system-ui, sans-serif",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 650 }}>
                  <div
                    style={{
                      width: 18,
                      height: 18,
                      backgroundColor: node.category ? getDecoderNodeFill(node, theme) : THEMES[theme].blockBorder,
                      borderRadius: role === "head" ? "50%" : "4px",
                      opacity: 0.8,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: "8px",
                      fontWeight: "bold",
                      border: `1px solid ${THEMES[theme].nodeBorder}`,
                      color: THEMES[theme].text
                    }}
                  >
                    {node.category ? getCategoryAbbrev(node.category) : ''}
                  </div>
                  <div
                    title={node.displayName || node.name || node.id}
                    style={{ 
                      whiteSpace: "nowrap", 
                      overflow: "hidden", 
                      textOverflow: "ellipsis", 
                      fontSize: 13.5,
                      flex: 1
                    }}
                  >
                    {node.displayName || node.name || node.id}
                  </div>
                </div>
                
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: 999,
                      background: node.category ? getDecoderNodeFill(node, 'light') : THEMES.light.chipPrimaryBg,
                      color: THEMES.light.chipPrimaryText,
                      fontSize: 10.5,
                      fontWeight: 600,
                      border: `1px solid ${THEMES.light.chipPrimaryText}20`
                    }}
                  >
                    {node.category || node.type || "kernel"}
                  </span>
                  {node.dtype && (
                    <span
                      style={{
                        padding: "2px 8px",
                        borderRadius: 999,
                        background: THEMES.light.chipNeutralBg,
                        color: THEMES.light.chipNeutralText,
                        fontSize: 10.5,
                        fontWeight: 600,
                      }}
                    >
                      {node.dtype}
                    </span>
                  )}
                </div>
                
                <div style={{ 
                  fontSize: 11.5, 
                  color: THEMES[theme].textMuted, 
                  display: "flex", 
                  gap: 16, 
                  marginTop: 2,
                  flexWrap: "wrap"
                }}>
                  {(node.ops || node.totalOps) && <span>Ops: {formatOps(node.totalOps ?? node.ops)}</span>}
                  {(node.bytes?.HBM || node.totalBytes) && (
                    <span>Mem: {formatBytes(node.totalBytes ?? node.bytes?.HBM)}</span>
                  )}
                  {node.timing_us && node.timing_us.start_us !== undefined && (
                    <span>Time: {((node.timing_us.end_us - node.timing_us.start_us) / 1000).toFixed(2)}ms</span>
                  )}
                </div>
              </div>
            </foreignObject>
          </g>
        );
      })}
    </svg>
  );
}

const DEFAULT_VIEW = { x: -400, y: -300, width: 1200, height: 800 };

export default function EnhancedWorkloadGraph({
  dag,
  decoderDag,                 
  direction = "TB",
  height = 640,
  layerMatchers = DEFAULT_LAYER_PATTERNS,
  initialTheme = "dark",
}) {
  const [viewType, setViewType] = React.useState("decoder");
  const [selectedNode, setSelectedNode] = React.useState(null);
  const [selectedEdge, setSelectedEdge] = React.useState(null);
  const [selectedType, setSelectedType] = React.useState(null);
  const [theme, setTheme] = React.useState(initialTheme);
  const [viewTransform, setViewTransform] = React.useState(DEFAULT_VIEW);
  const [lastFitBounds, setLastFitBounds] = React.useState(null);
  const didFitRef = React.useRef(false);
  const containerRef = React.useRef(null);

  const t = THEMES[theme] || THEMES.light;

  const sample = {
    nodes: [
      { id: "transformer", name: "transformer", type: "kernel", ops: 78_770_688, bytes: { HBM: 157_737_984 }, dtype: "torch.float32" },
      { id: "transformer.h.0", name: "0", type: "kernel", ops: 226_498_560, bytes: { HBM: 29_187_072 }, dtype: "torch.float32" },
      { id: "transformer.h.1", name: "1", type: "kernel", ops: 226_498_560, bytes: { HBM: 29_187_072 }, dtype: "torch.float32" },
      { id: "lm_head", name: "lm_head", type: "kernel", ops: 1_235_116_032, bytes: { HBM: 157_605_952 }, dtype: "torch.float32" },
    ],
    edges: [
      { source: "transformer", target: "transformer.h.0", bytes: 49_152 },
      { source: "transformer.h.0", target: "transformer.h.1", bytes: 49_152 },
      { source: "transformer", target: "lm_head", bytes: 3_216_448 },
    ],
  };

  // choose which DAG to normalize based on tab + availability
  const normalized = React.useMemo(() => {
    const n = (viewType === "decoder" && decoderDag) ? decoderDag : (dag || sample);
    const edges = (n.edges || []).map((e) => ({
      source: e.source ?? e.src,
      target: e.target ?? e.dst,
      bytes: e.bytes,
    }));
    return { name: n.name || "", nodes: n.nodes || [], edges };
  }, [dag, decoderDag, viewType]);

  const data = React.useMemo(() => {
    return viewType === "workload"
      ? createWorkloadView(normalized, layerMatchers)
      : normalized;
  }, [normalized, viewType, layerMatchers]);

  const layoutedNodes = React.useMemo(
    () => createLayout(data.nodes, data.edges, direction),
    [data.nodes, data.edges, direction]
  );

  const onNodeClick = (node) => {
    setSelectedNode(node);
    setSelectedEdge(null);
    setSelectedType(node ? "node" : null);
  };
  const onEdgeClick = (edge) => {
    setSelectedEdge(edge);
    setSelectedNode(null);
    setSelectedType(edge ? "edge" : null);
  };

  const clampWidth = (w, baseW) => {
    const base = baseW || viewTransform.width;
    const minW = base / 8;
    const maxW = base / 0.2;
    return Math.max(minW, Math.min(maxW, w));
  };

  const handleZoomBtn = (factor) => {
    const centerZoom = (prev) => {
      const rectW = 1000,
        rectH = 1000;
      const x_s = rectW / 2,
        y_s = rectH / 2;
      const newW = clampWidth(prev.width / factor, lastFitBounds?.width ?? DEFAULT_VIEW.width);
      const scale = newW / prev.width;
      const newH = prev.height * scale;
      const xPrime = prev.x + (x_s / rectW) * (prev.width - newW);
      const yPrime = prev.y + (y_s / rectH) * (prev.height - newH);
      return { x: xPrime, y: yPrime, width: newW, height: newH };
    };
    setViewTransform((v) => centerZoom(v));
  };

  const handleFit = () => {
    if (lastFitBounds) setViewTransform(lastFitBounds);
  };
  const handleReset = () => setViewTransform(DEFAULT_VIEW);

  React.useEffect(() => {
    if (lastFitBounds && !didFitRef.current) {
      didFitRef.current = true;
      setViewTransform(lastFitBounds);
    }
  }, [lastFitBounds]);

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  };

  const btn = (active) => ({
    padding: "8px 16px",
    borderRadius: 10,
    border: `1px solid ${active ? "transparent" : t.panelBorder}`,
    background: active ? "#3b82f6" : t.panelBg,
    color: active ? "#fff" : t.text,
    fontWeight: 600,
    fontSize: 14,
    cursor: "pointer",
    boxShadow: active ? "0 0 0 2px rgba(59,130,246,.25)" : "none",
  });

  return (
    <div style={{ display: "flex", gap: 16, height, color: t.text }}>
      <div
        ref={containerRef}
        style={{
          flex: 1,
          minWidth: 0,
          height: "100%",
          background: t.canvas,
          border: `1px solid ${t.panelBorder}`,
          borderRadius: 20,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 16,
            left: 16,
            zIndex: 30,
            display: "flex",
            gap: 12,
            alignItems: "center",
            background: t.panelBg,
            border: `1px solid ${t.panelBorder}`,
            borderRadius: 14,
            boxShadow: t.panelShadow,
            padding: 8,
          }}
        >
          <button style={btn(viewType === "workload")} onClick={() => setViewType("workload")}>
            Workload
          </button>
          <button style={btn(viewType === "decoder")} onClick={() => setViewType("decoder")}>
            Decoder
          </button>
          <div style={{ width: 1, height: 26, background: t.panelBorder }} />
          <button style={btn(theme === "light")} onClick={() => setTheme("light")}>
            Light
          </button>
          <button style={btn(theme === "dark")} onClick={() => setTheme("dark")}>
            Dark
          </button>
        </div>

        <div
          style={{
            position: "absolute",
            right: 16,
            top: "50%",
            transform: "translateY(-50%)",
            zIndex: 40,
            display: "flex",
            flexDirection: "column",
            gap: 6,
            pointerEvents: "auto",
          }}
        >
          <IconBtn title="Zoom In" onClick={() => handleZoomBtn(1.2)} t={t}>
            <ZoomInIcon />
          </IconBtn>
          <IconBtn title="Zoom Out" onClick={() => handleZoomBtn(1 / 1.2)} t={t}>
            <ZoomOutIcon />
          </IconBtn>
          <IconBtn title="Fit View" onClick={handleFit} t={t}>
            <FitIcon />
          </IconBtn>
          <IconBtn title="Reset" onClick={handleReset} t={t}>
            <ResetIcon />
          </IconBtn>
          <IconBtn title="Fullscreen" onClick={toggleFullscreen} t={t}>
            <FullscreenIcon />
          </IconBtn>
        </div>

        <CustomGraph
          layoutedNodes={layoutedNodes}
          edges={data.edges}
          theme={theme}
          selectedNodeId={selectedNode?.id}
          selectedEdgeId={selectedEdge?.id}
          onNodeClick={onNodeClick}
          onEdgeClick={onEdgeClick}
          viewTransform={viewTransform}
          setViewTransform={setViewTransform}
          onAutoFit={(vb) => setLastFitBounds(vb)}
          limits={{
            baseWidth: lastFitBounds?.width ?? DEFAULT_VIEW.width,
            baseHeight: lastFitBounds?.height ?? DEFAULT_VIEW.height,
            minScale: 0.2,
            maxScale: 8,
          }}
        />
      </div>

      <div
        style={{
          width: 380,
          background: t.detailsBg,
          border: `1px solid ${t.panelBorder}`,
          borderRadius: 20,
          padding: 20,
          overflow: "auto",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
            {selectedType === "edge" ? "Connection Details" : viewType === "workload" ? "Component Details" : "Operation Details"}
          </h3>
          {(selectedNode || selectedEdge) && (
            <button
              onClick={() => {
                setSelectedNode(null);
                setSelectedEdge(null);
                setSelectedType(null);
              }}
              style={{
                fontSize: 12,
                color: t.textMuted,
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "4px 8px",
                borderRadius: 6,
                fontWeight: 500,
              }}
            >
              Clear
            </button>
          )}
        </div>

        {!selectedNode && !selectedEdge ? (
          <div
            style={{
              color: t.textMuted,
              textAlign: "center",
              padding: "40px 20px",
              background: t.detailsCardBg,
              borderRadius: 12,
              border: `1px dashed ${t.detailsBorder}`,
            }}
          >
            Click a node or edge to see details.
          </div>
        ) : selectedType === "edge" ? (
          <div style={{ display: "grid", gap: 14, fontSize: 14 }}>
            <div style={{ fontSize: 12, opacity: 0.7 }}>CONNECTION</div>
            <div style={{ fontFamily: "monospace", wordBreak: "break-all" }}>{selectedEdge.id}</div>
            <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>SOURCE</div>
            <div style={{ fontWeight: 600 }}>
              {selectedEdge.sourceNode?.displayName || selectedEdge.sourceNode?.name || selectedEdge.source}
            </div>
            <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>TARGET</div>
            <div style={{ fontWeight: 600 }}>
              {selectedEdge.targetNode?.displayName || selectedEdge.targetNode?.name || selectedEdge.target}
            </div>
            {selectedEdge.bytes && (
              <>
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>DATA TRANSFER</div>
                <div style={{ fontFamily: "monospace", fontWeight: 600, color: t.edgeSelected }}>
                  {formatBytes(selectedEdge.bytes)}
                </div>
              </>
            )}
          </div>
        ) : (
          <div style={{ display: "grid", gap: 14, fontSize: 14 }}>
            <div style={{ fontSize: 12, opacity: 0.7 }}>OPERATION ID</div>
            <div style={{ fontFamily: "monospace", wordBreak: "break-all" }}>{selectedNode.id}</div>
            
            {selectedNode.category && (
              <>
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>CATEGORY</div>
                <div style={{ fontWeight: 600, textTransform: "capitalize" }}>
                  {selectedNode.category}
                </div>
              </>
            )}
            
            {(selectedNode.ops || selectedNode.totalOps) && (
              <>
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>OPERATIONS</div>
                <div style={{ fontFamily: "monospace", fontWeight: 600 }}>
                  {(selectedNode.totalOps || selectedNode.ops).toLocaleString()}
                </div>
              </>
            )}
            
            {(selectedNode.bytes || selectedNode.totalBytes) && (
              <>
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>MEMORY</div>
                <div style={{ fontFamily: "monospace", fontWeight: 600 }}>
                  {selectedNode.bytes
                    ? Object.entries(selectedNode.bytes)
                        .map(([k, v]) => `${k}: ${formatBytes(v)}`)
                        .join("  •  ")
                    : formatBytes(selectedNode.totalBytes)}
                </div>
              </>
            )}
            
            {selectedNode.timing_us && (
              <>
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>TIMING</div>
                <div style={{ fontFamily: "monospace", fontWeight: 600 }}>
                  Duration: {((selectedNode.timing_us.end_us - selectedNode.timing_us.start_us) / 1000).toFixed(2)}ms
                </div>
              </>
            )}
            
            {selectedNode.shapes && selectedNode.shapes.length > 0 && (
              <>
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>TENSOR SHAPES</div>
                <div style={{ fontFamily: "monospace", fontSize: 12 }}>
                  {selectedNode.shapes.map((shape, idx) => (
                    <div key={idx}>[{shape.join(', ')}]</div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}