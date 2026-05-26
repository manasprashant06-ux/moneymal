import { useEffect, useRef, useState } from 'react';
import { Network } from 'vis-network';
import { DataSet } from 'vis-data';

/* ─── Colour palette (matches legend in GraphPage) ─── */
const C = {
    HUB:    { bg: '#9b59b6', border: '#8e44ad', glow: 'rgba(155,89,182,0.45)'  }, // Purple
    BRIDGE: { bg: '#e67e22', border: '#d35400', glow: 'rgba(230,126,34,0.45)'  }, // Orange
    MULE:   { bg: '#f1c40f', border: '#f39c12', glow: 'rgba(241,196,15,0.45)'  }, // Yellow
    LEAF:   { bg: '#3498db', border: '#2980b9', glow: 'rgba(52,152,219,0.25)'  }, // Blue
};

function nodeColours(role) {
    if (role === 'HUB') return C.HUB;
    if (role === 'BRIDGE') return C.BRIDGE;
    if (role === 'MULE') return C.MULE;
    return C.LEAF;
}

/* ─── Rich HTML tooltip ─── */
function buildTooltip(n) {
    const verdict = n.verdict === 'BLOCK' ? '🔴 BLOCK' : n.verdict === 'REVIEW' ? '🟡 REVIEW' : '🟢 APPROVE';
    const role    = n.structural_role || 'LEAF';
    const GAT     = n.four_pillar_scores?.GAT ?? 0;
    const LSTM    = n.four_pillar_scores?.LSTM ?? 0;
    const EIF     = n.four_pillar_scores?.EIF ?? 0;
    const Rules   = n.four_pillar_scores?.Rules ?? 0;
    const mult    = n.four_pillar_scores?.Multiplier ?? 1.0;
    
    const patterns = (n.detected_patterns || []).join(', ') || 'None';
    const rings    = (n.ring_ids || []).join(', ')           || 'None';
    const inAmt    = n.total_incoming != null ? '₹' + n.total_incoming.toLocaleString() : '–';
    const outAmt   = n.total_outgoing != null ? '₹' + n.total_outgoing.toLocaleString() : '–';

    return `
        <div style="
            background:#0d1117;border:1px solid #30363d;border-radius:10px;
            padding:14px 18px;font-family:monospace;font-size:12px;color:#e6edf3;
            min-width:240px;line-height:1.8;box-shadow:0 8px 30px rgba(0,0,0,0.7);
        ">
            <div style="font-size:13px;font-weight:700;color:#58a6ff;margin-bottom:6px">${n.id} <span style="color:#8b949e;font-size:10px;font-weight:normal">[${role}]</span></div>
            <div>${verdict} &nbsp;<strong style="color:#fff">${Number(n.suspicion_score).toFixed(1)}</strong>/100</div>
            <hr style="border:none;border-top:1px solid #30363d;margin:8px 0">
            <div style="color:#8b949e;font-size:10px;letter-spacing:.08em">PILLAR SCORES</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px">
                <div><span style="color:#8b949e">GAT</span> ${GAT}/35</div>
                <div><span style="color:#8b949e">LSTM</span> ${LSTM}/25</div>
                <div><span style="color:#8b949e">EIF</span> ${EIF}/20</div>
                <div><span style="color:#8b949e">Rules</span> ${Rules}/20</div>
            </div>
            <div style="font-size:10px;margin-top:4px">Role Multiplier: <span style="color:#58a6ff">${mult.toFixed(2)}x</span></div>
            <hr style="border:none;border-top:1px solid #30363d;margin:8px 0">
            <div style="color:#8b949e;font-size:10px;letter-spacing:.08em">PATTERNS</div>
            <div>${patterns}</div>
            <div style="color:#8b949e;font-size:10px;letter-spacing:.08em;margin-top:6px">RING MEMBERSHIP</div>
            <div>${rings}</div>
            <hr style="border:none;border-top:1px solid #30363d;margin:8px 0">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px">
                <div><span style="color:#8b949e">Received</span>&nbsp;${inAmt}</div>
                <div><span style="color:#8b949e">Sent</span>&nbsp;${outAmt}</div>
            </div>
        </div>`;
}

/* ─── Component ─── */
export default function NetworkGraph({ data, onNodeClick }) {
    const containerRef = useRef(null);
    const networkRef   = useRef(null);
    const [stabilized, setStabilized] = useState(false);
    const [capped, setCapped] = useState(false);

    useEffect(() => {
        if (!containerRef.current || !data || !data.nodes.length) return;
        setStabilized(false);

        // Safeguard to prevent browser tab crash/freeze on dense datasets
        const MAX_RENDER_NODES = 400;
        const isCapped = data.nodes.length > MAX_RENDER_NODES;
        setCapped(isCapped);

        let renderedNodes = data.nodes;
        let renderedEdges = data.edges;

        if (isCapped) {
            renderedNodes = [...data.nodes]
                .sort((a, b) => (b.suspicion_score || 0) - (a.suspicion_score || 0))
                .slice(0, MAX_RENDER_NODES);
            const nodeIds = new Set(renderedNodes.map(n => n.id));
            renderedEdges = data.edges.filter(
                e => nodeIds.has(e.from) && nodeIds.has(e.to)
            );
        }

        /* ── nodes ── */
        const nodes = new DataSet(
            renderedNodes.map((n) => {
                const c      = nodeColours(n.structural_role || 'LEAF');
                const size   = n.suspicion_score > 70 ? 24 : n.suspicion_score > 30 ? 17 : 11;
                const inRing = (n.ring_ids || []).length > 0;
                return {
                    id:    n.id,
                    label: n.label || n.id,
                    title: buildTooltip(n),
                    color: {
                        background: c.bg,
                        border:     inRing ? '#FFFFFF' : c.border,
                        highlight:  { background: '#FFFFFF', border: '#00E5FF' },
                        hover:      { background: c.bg,      border: '#FFFFFF' },
                    },
                    size,
                    borderWidth:         inRing ? 3 : 1.5,
                    borderWidthSelected: 4,
                    font: {
                        size:       12,
                        color:      '#E8EAF6',
                        face:       'JetBrains Mono, Consolas, monospace',
                        background: 'rgba(10,14,26,0.80)',
                        strokeWidth: 0,
                        bold:       n.suspicion_score > 30 ? { color: '#FFFFFF', size: 13 } : false,
                    },
                    shadow: {
                        enabled: n.suspicion_score > 30,
                        color:   c.glow,
                        size:    n.suspicion_score > 70 ? 20 : 10,
                        x: 0, y: 0,
                    },
                    _raw: n,
                };
            })
        );

        /* ── edges ── */
        const edges = new DataSet(
            renderedEdges.map((e, i) => ({
                id:    `e-${i}`,
                from:  e.from,
                to:    e.to,
                value: e.value || 1,
                title: e.title ? `<span style="font-family:monospace;font-size:12px;color:#e6edf3">${e.title}</span>` : '',
                color: {
                    color:   'rgba(80,160,220,0.40)',
                    highlight:'rgba(0,229,255,0.95)',
                    hover:   'rgba(0,229,255,0.60)',
                    inherit: false,
                },
                arrows:         { to: { enabled: true, scaleFactor: 0.6, type: 'arrow' } },
                smooth:         { type: 'curvedCW', roundness: 0.18 },
                width:          1.0,
                selectionWidth: 3,
                scaling:        { min: 0.8, max: 5 },
            }))
        );

        /* ── options ── */
        const bigGraph = data.nodes.length > 300;
        const options = {
            autoResize: true,
            layout:  { improvedLayout: !bigGraph },
            physics: {
                solver: 'barnesHut',
                barnesHut: {
                    gravitationalConstant: -6000,
                    centralGravity:        0.12,
                    springLength:          170,
                    springConstant:        0.04,
                    damping:               0.13,
                    avoidOverlap:          0.65,
                },
                stabilization: {
                    enabled:        true,
                    iterations:     bigGraph ? 150 : 300,
                    updateInterval: 30,
                    fit:            true,
                },
                minVelocity: 0.75,
            },
            nodes:   { shape: 'dot', borderWidth: 1.5, borderWidthSelected: 4 },
            edges:   { width: 1.0, scaling: { min: 0.8, max: 5 } },
            interaction: {
                hover:           true,
                tooltipDelay:    80,
                zoomView:        true,
                dragView:        true,
                dragNodes:       true,
                multiselect:     false,
                hideEdgesOnDrag: bigGraph,
                keyboard:        false,
            },
        };

        /* ── mount ── */
        if (networkRef.current) { networkRef.current.destroy(); networkRef.current = null; }
        const network = new Network(containerRef.current, { nodes, edges }, options);
        networkRef.current = network;

        network.on('stabilizationIterationsDone', () => {
            network.setOptions({ physics: { enabled: false } });
            network.fit({ animation: { duration: 700, easingFunction: 'easeInOutQuad' } });
            setStabilized(true);
        });

        network.on('click', (params) => {
            if (params.nodes.length > 0) {
                const nodeId  = params.nodes[0];
                const rawNode = data.nodes.find((n) => String(n.id) === String(nodeId));
                if (rawNode && onNodeClick) onNodeClick(rawNode);
            }
        });

        return () => {
            if (networkRef.current) { networkRef.current.destroy(); networkRef.current = null; }
        };
    }, [data]); // onNodeClick intentionally omitted — stable callback, avoids full re-render

    return (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
            {/* Capped warning pill */}
            {capped && (
                <div style={{
                    position: 'absolute', top: 12, right: 12, zIndex: 5,
                    background: 'rgba(255, 159, 28, 0.15)',
                    border: '1px solid rgba(255, 159, 28, 0.3)',
                    borderRadius: 6, padding: '4px 10px',
                    fontFamily: 'JetBrains Mono, monospace', fontSize: '10px',
                    color: '#FF9F1C', letterSpacing: '0.05em',
                    pointerEvents: 'none',
                }}>
                    ⚠️ PERFORMANCE MODE: TOP 400 NODES
                </div>
            )}

            {/* Loading overlay */}
            {!stabilized && (
                <div style={{
                    position: 'absolute', inset: 0, zIndex: 10,
                    display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center',
                    background: 'rgba(11,15,26,0.80)',
                    backdropFilter: 'blur(6px)',
                    borderRadius: 'inherit',
                }}>
                    <div className="graph-spinner" />
                    <p style={{
                        marginTop: 16,
                        fontFamily: 'JetBrains Mono, monospace',
                        fontSize: '0.72rem',
                        color: 'rgba(0,229,255,0.75)',
                        letterSpacing: '0.14em',
                    }}>
                        BUILDING GRAPH…
                    </p>
                </div>
            )}
            <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
        </div>
    );
}
