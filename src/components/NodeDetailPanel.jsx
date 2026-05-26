import { motion } from 'framer-motion';

export default function NodeDetailPanel({ node, onClose }) {
    if (!node) return null;

    const score = Number(node.suspicion_score || 0).toFixed(1);
    const verdict = node.verdict || 'APPROVE';
    const role = node.structural_role || 'LEAF';
    const scoreColor = verdict === 'BLOCK' ? 'var(--color-risk-red)' : verdict === 'REVIEW' ? 'var(--color-risk-orange)' : 'var(--color-risk-green)';
    const roleColor = role === 'HUB' ? '#9b59b6' : role === 'BRIDGE' ? '#e67e22' : role === 'MULE' ? '#f1c40f' : '#3498db';
    const four_pillars = node.four_pillar_scores || {GAT: 0, LSTM: 0, EIF: 0, Rules: 0, Multiplier: 1.0};
    const riskLabel = score > 70 ? 'CRITICAL RISK' : score > 30 ? 'ELEVATED RISK' : 'LOW RISK';

    return (
        <motion.div
            className="side-panel"
            initial={{ x: 400, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 400, opacity: 0 }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
        >
            {/* Close button */}
            <button
                onClick={onClose}
                style={{
                    position: 'absolute', top: 16, right: 16,
                    background: 'none', border: 'none', color: 'var(--color-text-dim)',
                    cursor: 'pointer', fontSize: '1.2rem',
                }}
            >
                ✕
            </button>

            {/* Header */}
            <div style={{ marginBottom: 24 }}>
                <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--color-text-dim)', letterSpacing: '0.1em', marginBottom: 4 }}>
                    ACCOUNT DETAILS <span style={{ color: roleColor, fontWeight: 'bold' }}>[{role}]</span>
                </p>
                <h2 style={{ fontFamily: 'var(--font-mono)', fontSize: '1.1rem', fontWeight: 700, color: 'var(--color-accent)' }}>
                    {node.id}
                </h2>
            </div>

            {/* Risk Score Card */}
            <div className="glass-card p-5 mb-5" style={{ borderColor: `${scoreColor}30` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                        <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--color-text-dim)', letterSpacing: '0.08em', marginBottom: 8 }}>
                            ENFORCEMENT VERDICT
                        </p>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '2rem', fontWeight: 800, color: scoreColor, lineHeight: 1 }}>
                            {verdict}
                        </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                        <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--color-text-dim)', letterSpacing: '0.08em', marginBottom: 4 }}>
                            COMBINED SCORE
                        </p>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.5rem', fontWeight: 700, color: '#fff' }}>
                            {score}
                        </div>
                    </div>
                </div>

                <div style={{ marginTop: 20, height: 6, background: 'rgba(0,245,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                    <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${Math.min(100, score)}%` }}
                        transition={{ duration: 0.8, ease: 'easeOut' }}
                        style={{ height: '100%', background: scoreColor, borderRadius: 3, boxShadow: `0 0 10px ${scoreColor}50` }}
                    />
                </div>
                
                {/* 4 Pillar Breakdown */}
                <div style={{ marginTop: 16, background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '6px' }}>
                    <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--color-text-dim)', letterSpacing: '0.08em', marginBottom: 8 }}>4-PILLAR BREAKDOWN</p>
                    <div className="grid grid-cols-2 gap-2" style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#8b949e' }}>
                        <div className="flex justify-between"><span>GAT (35%)</span> <span style={{color: '#fff'}}>{four_pillars.GAT}</span></div>
                        <div className="flex justify-between"><span>LSTM (25%)</span> <span style={{color: '#fff'}}>{four_pillars.LSTM}</span></div>
                        <div className="flex justify-between"><span>EIF (20%)</span> <span style={{color: '#fff'}}>{four_pillars.EIF}</span></div>
                        <div className="flex justify-between"><span>Rules (20%)</span> <span style={{color: '#fff'}}>{four_pillars.Rules}</span></div>
                    </div>
                    <div className="mt-2 pt-2" style={{ borderTop: '1px solid rgba(255,255,255,0.1)', fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#8b949e' }}>
                        Structural Multiplier: <span style={{color: '#58a6ff'}}>{Number(four_pillars.Multiplier).toFixed(2)}x</span>
                    </div>
                </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-2 gap-3 mb-5">
                <div className="glass-card p-3 text-center">
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-accent)' }}>
                        {node.in_degree ?? '—'}
                    </div>
                    <div className="metric-label">In-Degree</div>
                </div>
                <div className="glass-card p-3 text-center">
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.2rem', fontWeight: 700, color: 'var(--color-accent)' }}>
                        {node.out_degree ?? '—'}
                    </div>
                    <div className="metric-label">Out-Degree</div>
                </div>
                <div className="glass-card p-3 text-center">
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.1rem', fontWeight: 700, color: 'var(--color-risk-green)' }}>
                        {node.total_incoming != null ? `₹${node.total_incoming.toLocaleString()}` : '—'}
                    </div>
                    <div className="metric-label">Total Incoming</div>
                </div>
                <div className="glass-card p-3 text-center">
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.1rem', fontWeight: 700, color: 'var(--color-risk-orange)' }}>
                        {node.total_outgoing != null ? `₹${node.total_outgoing.toLocaleString()}` : '—'}
                    </div>
                    <div className="metric-label">Total Outgoing</div>
                </div>
            </div>

            {/* Patterns */}
            <div className="mb-5">
                <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--color-text-dim)', letterSpacing: '0.08em', marginBottom: 10 }}>
                    DETECTED PATTERNS
                </p>
                <div className="flex flex-wrap gap-2">
                    {(node.detected_patterns || []).length > 0 ? (
                        node.detected_patterns.map((p) => (
                            <span key={p} className="pattern-chip" style={{ padding: '4px 10px' }}>{p}</span>
                        ))
                    ) : (
                        <span style={{ color: 'var(--color-text-dim)', fontSize: '0.75rem', fontFamily: 'var(--font-mono)' }}>
                            No patterns detected
                        </span>
                    )}
                </div>
            </div>

            {/* Risk Classification */}
            <div className="glass-card p-4">
                <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--color-text-dim)', letterSpacing: '0.08em', marginBottom: 8 }}>
                    CLASSIFICATION
                </p>
                <div className="flex items-center gap-3">
                    <div style={{
                        width: 12, height: 12, borderRadius: '50%',
                        background: scoreColor,
                        boxShadow: `0 0 10px ${scoreColor}60`,
                    }} />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', fontWeight: 600, color: scoreColor }}>
                        {riskLabel}
                    </span>
                </div>
                <p style={{ color: 'var(--color-text-dim)', fontSize: '0.7rem', marginTop: 8, lineHeight: 1.5 }}>
                    {score > 70
                        ? 'This account shows strong indicators of money mule activity. Immediate investigation recommended.'
                        : score > 30
                            ? 'This account has suspicious patterns warranting further review.'
                            : 'This account is within normal behavioral parameters.'
                    }
                </p>
            </div>
        </motion.div>
    );
}
